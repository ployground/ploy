from lazy import lazy
from mr.awsome.common import BaseMaster, FabricMixin, yesno
import getpass
import logging
import os
import sys


log = logging.getLogger('mr.awsome')


class InstanceFormattingWrapper(object):
    def __init__(self, instance):
        self.instance = instance

    def __getattr__(self, name):
        return self.instance.config[name]


class Instance(FabricMixin):
    def __init__(self, master, sid, config):
        validate_id = getattr(self, 'validate_id', lambda x: x)
        self.id = validate_id(sid)
        self.master = master
        self.config = config

    def get_host(self):
        return self.config['host']

    def get_fingerprint(self):
        try:  # pragma: no cover - we support both
            from paramiko import SSHException
            SSHException  # shutup pyflakes
        except ImportError:  # pragma: no cover - we support both
            from ssh import SSHException

        fingerprint = self.config.get('fingerprint')
        if fingerprint is None:
            raise SSHException("No fingerprint set in config.")
        return fingerprint

    @lazy
    def paramiko(self):
        try:  # pragma: no cover - we support both
            import paramiko
            paramiko  # shutup pyflakes
        except ImportError:  # pragma: no cover - we support both
            import ssh as paramiko
        return paramiko

    @lazy
    def sshconfig(self):
        sshconfig = self.paramiko.SSHConfig()
        sshconfig.parse(open(os.path.expanduser('~/.ssh/config')))
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
        class ServerHostKeyPolicy(paramiko.MissingHostKeyPolicy):
            def __init__(self, fingerprint):
                self.fingerprint = fingerprint
                self.ask = True

            def missing_host_key(self, client, hostname, key):
                fingerprint = ':'.join("%02x" % ord(x) for x in key.get_fingerprint())
                if self.fingerprint.lower() in ('ask', 'none'):
                    if not self.ask:
                        return
                    if yesno("WARNING! Automatic fingerprint checking disabled.\nGot fingerprint %s.\nContinue?" % fingerprint):
                        self.ask = False
                        return
                    sys.exit(1)
                elif fingerprint == self.fingerprint:
                    client._host_keys.add(hostname, key.get_name(), key)
                    if client._host_keys_filename is not None:
                        client.save_host_keys(client._host_keys_filename)
                    return
                raise paramiko.SSHException("Fingerprint doesn't match for %s (got %s, expected %s)" % (hostname, fingerprint, self.fingerprint))

        try:
            host = self.get_host()
        except KeyError:
            raise paramiko.SSHException("No host set in config.")
        port = self.config.get('port', 22)
        hostname = sshconfig.lookup(host).get('hostname', host)
        port = sshconfig.lookup(host).get('port', port)
        password = None
        client = paramiko.SSHClient()
        fingerprint = self.get_fingerprint()
        client.set_missing_host_key_policy(ServerHostKeyPolicy(fingerprint))
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
            proxy_instance = self.master.instances[proxy_host]
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
            except paramiko.PasswordRequiredException:
                if not self.config.get('password-fallback', False):
                    raise
                if 'password' in self.config:
                    password = self.config['password']
                else:
                    password = getpass.getpass("Password for '%s@%s:%s': " % (user, host, port))
            except paramiko.AuthenticationException as e:
                if not 'keyboard-interactive' in e.allowed_types:
                    raise
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

    @property
    def conn(self):
        if getattr(self, '_conn', None) is not None:
            if self._conn.get_transport() is not None:
                return self._conn
        try:
            from paramiko import SSHException
            SSHException  # shutup pyflakes
        except ImportError:
            from ssh import SSHException
        try:
            ssh_info = self.init_ssh_key()
        except SSHException, e:
            log.error("Couldn't connect to %s." % self.id)
            log.error(unicode(e))
            sys.exit(1)
        self._conn = ssh_info['client']
        return self._conn


class Master(BaseMaster):
    sectiongroupname = 'plain-instance'
    instance_class = Instance


def get_massagers():
    from mr.awsome.config import BooleanMassager, PathMassager, UserMassager

    sectiongroupname = 'plain-instance'
    return [
        UserMassager(sectiongroupname, 'user'),
        BooleanMassager(sectiongroupname, 'password-fallback'),
        PathMassager(sectiongroupname, 'fabfile')]


def get_masters(aws):
    masters = aws.config.get('plain-master', {'default': {}})
    for master, master_config in masters.iteritems():
        yield Master(aws, master, master_config)


plugin = dict(
    get_massagers=get_massagers,
    get_masters=get_masters)
