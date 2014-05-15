from lazy import lazy
from mr.awsome.common import BaseMaster, BaseInstance, import_paramiko, yesno
import getpass
import logging
import os
import sys


log = logging.getLogger('mr.awsome')


def ServerHostKeyPolicy(*args, **kwarks):
    paramiko = import_paramiko()

    class ServerHostKeyPolicy(paramiko.MissingHostKeyPolicy):
        def __init__(self, fingerprint_func):
            self.fingerprint_func = fingerprint_func
            self.ask = True

        @lazy
        def fingerprint(self):
            return self.fingerprint_func()

        def missing_host_key(self, client, hostname, key):
            fingerprint = ':'.join("%02x" % ord(x) for x in key.get_fingerprint())
            if self.fingerprint.lower() == 'ask':
                if not self.ask:
                    return
                if yesno("WARNING! Automatic fingerprint checking disabled.\nGot fingerprint %s.\nContinue?" % fingerprint):
                    self.ask = False
                    return
                sys.exit(1)
            elif fingerprint == self.fingerprint or self.fingerprint.lower() == 'ignore':
                if self.fingerprint.lower() == 'ignore':
                    log.warn("Fingerprint verification disabled!")
                client._host_keys.add(hostname, key.get_name(), key)
                if client._host_keys_filename is not None:
                    client.save_host_keys(client._host_keys_filename)
                return
            raise paramiko.SSHException("Fingerprint doesn't match for %s (got %s, expected %s)" % (hostname, fingerprint, self.fingerprint))

    return ServerHostKeyPolicy(*args, **kwarks)


class InstanceFormattingWrapper(object):
    def __init__(self, instance):
        self.instance = instance

    def __getattr__(self, name):
        return self.instance.config[name]


class Instance(BaseInstance):
    def get_host(self):
        if 'host' not in self.config:
            return self.config['ip']
        return self.config['host']

    def get_fingerprint(self):
        fingerprint = self.config.get('fingerprint')
        if fingerprint is None:
            fingerprint = self.master.master_config.get('fingerprint')
        if fingerprint is None:
            raise self.paramiko.SSHException("No fingerprint set in config.")
        return fingerprint

    @lazy
    def paramiko(self):
        return import_paramiko()

    @lazy
    def sshconfig(self):
        sshconfig = self.paramiko.SSHConfig()
        path = os.path.expanduser('~/.ssh/config')
        if not os.path.exists(path):
            return sshconfig
        with open(path) as f:
            sshconfig.parse(f)
        return sshconfig

    @lazy
    def proxy_command(self):
        proxy_command = self.config.get('proxycommand', None)
        if proxy_command is None:
            return self.sshconfig.lookup(self.get_host()).get('proxycommand', None)
        else:
            d = dict(
                instances=dict(
                    (k, InstanceFormattingWrapper(v))
                    for k, v in self.master.instances.items()))
            d.update(self.config)
            d['known_hosts'] = self.master.known_hosts
            d['path'] = self.master.main_config.path
            return proxy_command.format(**d)

    def init_ssh_key(self, user=None):
        paramiko = self.paramiko
        sshconfig = self.sshconfig
        try:
            host = self.get_host()
        except KeyError:
            raise paramiko.SSHException("No host or ip set in config.")
        port = self.config.get('port', 22)
        hostname = sshconfig.lookup(host).get('hostname', host)
        port = sshconfig.lookup(host).get('port', port)
        password = None
        client = paramiko.SSHClient()
        fingerprint_func = self.get_fingerprint
        client.set_missing_host_key_policy(ServerHostKeyPolicy(fingerprint_func))
        known_hosts = self.master.known_hosts
        client.known_hosts = None
        proxy_host = self.config.get('proxyhost', None)
        proxy_command = self.proxy_command
        if proxy_command and not proxy_host:
            try:
                sock = paramiko.ProxyCommand(proxy_command)
            except Exception:
                log.error("The following ProxyCommand failed:\n%s" % proxy_command)
                raise
        elif proxy_host:
            proxy_instance = self.master.aws.instances[proxy_host]
            sock = proxy_instance.conn.get_transport().open_channel(
                'direct-tcpip',
                (hostname, port),
                ('127.0.0.1', 0))
        else:
            sock = None
        while 1:
            if os.path.exists(known_hosts):
                client.load_host_keys(known_hosts)
            try:
                if user is None:
                    user = sshconfig.lookup(host).get('user', 'root')
                    user = self.config.get('user', user)
                client_args = dict(
                    port=int(port),
                    username=user,
                    key_filename=self.config.get('ssh-key-filename', None),
                    password=password,
                    sock=sock)
                client.connect(hostname, **client_args)
                break
            except paramiko.AuthenticationException:
                if not self.config.get('password-fallback', False):
                    raise
                if password is None and 'password' in self.config:
                    password = self.config['password']
                else:
                    password = getpass.getpass("Password for '%s@%s:%s': " % (user, host, port))
            except paramiko.BadHostKeyException:
                if os.path.exists(known_hosts):
                    os.remove(known_hosts)
                    open(known_hosts, 'w').close()
                client.get_host_keys().clear()
            except paramiko.SSHException:
                log.error('Failed to connect to %s (%s)' % (self.id, hostname))
                for option in ('username', 'password', 'port', 'key_filename', 'sock'):
                    if client_args[option] is not None:
                        log.error('%s: %r' % (option, client_args[option]))
                raise
        client.save_host_keys(known_hosts)
        result = dict(
            user=user,
            host=host,
            port=port,
            client=client,
            UserKnownHostsFile=known_hosts)
        if proxy_command:
            result['ProxyCommand'] = proxy_command
        return result


class Master(BaseMaster):
    sectiongroupname = 'plain-instance'
    instance_class = Instance


def get_massagers():
    from mr.awsome.config import BooleanMassager, UserMassager

    sectiongroupname = 'plain-instance'
    return [
        UserMassager(sectiongroupname, 'user'),
        BooleanMassager(sectiongroupname, 'password-fallback')]


def get_masters(aws):
    masters = aws.config.get('plain-master', {'plain-master': {}})
    for master, master_config in masters.iteritems():
        yield Master(aws, master, master_config)


plugin = dict(
    get_massagers=get_massagers,
    get_masters=get_masters)
