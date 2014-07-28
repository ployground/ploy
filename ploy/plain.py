from lazy import lazy
from ploy.common import BaseMaster, BaseInstance, import_paramiko, yesno
import getpass
import logging
import os
import socket
import subprocess
import sys


log = logging.getLogger('ploy')


def get_key_fingerprint(key):
    key_fingerprint = key.get_fingerprint()
    if isinstance(key_fingerprint[0], int):
        return ':'.join("%02x" % x for x in key_fingerprint)
    return ':'.join("%02x" % ord(x) for x in key_fingerprint)


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
            fingerprint = get_key_fingerprint(key)
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
                client.get_host_keys().add(hostname, key.get_name(), key)
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
    sectiongroupname = 'plain-instance'

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
        path = os.path.join(self.master.main_config.path, fingerprint)
        if os.path.exists(path):
            try:
                result = subprocess.check_output(['ssh-keygen', '-lf', path])
            except subprocess.CalledProcessError as e:
                log.error("Couldn't get fingerprint from '%s':\n%s" % (path, e))
                sys.exit(1)
            else:
                fingerprint = result.split()[1]
        return fingerprint

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

    def get_proxy_sock(self, hostname, port):
        paramiko = self.paramiko
        proxy_command = self.proxy_command
        if proxy_command:
            try:
                sock = paramiko.ProxyCommand(proxy_command)
            except Exception:
                log.error("The following ProxyCommand failed:\n%s" % proxy_command)
                raise
        else:
            sock = None
        return sock

    def init_ssh_key(self, user=None):
        paramiko = self.paramiko
        sshconfig = self.sshconfig
        try:
            host = self.get_host()
        except KeyError:
            raise paramiko.SSHException("No host or ip set in config.")
        port = 22
        if hasattr(self, 'get_port'):
            port = self.get_port()
        port = self.config.get('port', port)
        hostname = sshconfig.lookup(host).get('hostname', host)
        port = sshconfig.lookup(host).get('port', port)
        password = None
        client = paramiko.SSHClient()
        fingerprint_func = self.get_fingerprint
        client.set_missing_host_key_policy(ServerHostKeyPolicy(fingerprint_func))
        known_hosts = self.master.known_hosts
        client.known_hosts = None
        while 1:
            sock = self.get_proxy_sock(hostname, port)
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
                    log.error('Failed to connect to %s (%s)' % (self.config_id, hostname))
                    for option in ('username', 'password', 'port', 'key_filename', 'sock'):
                        if client_args[option] is not None:
                            log.error('%s: %r' % (option, client_args[option]))
                    raise
                if password is None and 'password' in self.config:
                    password = self.config['password']
                else:
                    password = getpass.getpass("Password for '%s@%s:%s': " % (user, host, port))
            except paramiko.BadHostKeyException:
                host_keys = client.get_host_keys()
                if port == 22:
                    key_hostname = hostname
                else:
                    key_hostname = "[%s]:%s" % (hostname, port)
                bad_key = host_keys.lookup(key_hostname)
                keys = [x for x in host_keys.items() if x[1] != bad_key]
                if os.path.exists(known_hosts):
                    os.remove(known_hosts)
                    open(known_hosts, 'w').close()
                host_keys.clear()
                for name, key in keys:
                    for subkey in key.values():
                        host_keys.add(name, subkey.get_name(), subkey)
                client.save_host_keys(known_hosts)
            except (paramiko.SSHException, socket.error):
                log.error('Failed to connect to %s (%s)' % (self.config_id, hostname))
                for option in ('username', 'password', 'port', 'key_filename', 'sock'):
                    if client_args[option] is not None:
                        log.error('%s: %r' % (option, client_args[option]))
                raise
            if sock is not None:
                sock.close()
        client.save_host_keys(known_hosts)
        result = dict(
            user=user,
            host=host,
            port=port,
            client=client,
            UserKnownHostsFile=known_hosts)
        if self.proxy_command:
            result['ProxyCommand'] = self.proxy_command
        return result


class Master(BaseMaster):
    sectiongroupname = 'plain-instance'
    instance_class = Instance


def get_massagers():
    from ploy.config import BooleanMassager, UserMassager

    sectiongroupname = 'plain-instance'
    return [
        UserMassager(sectiongroupname, 'user'),
        BooleanMassager(sectiongroupname, 'password-fallback')]


def get_masters(ctrl):
    masters = ctrl.config.get('plain-master', {'plain': {}})
    for master, master_config in masters.items():
        yield Master(ctrl, master, master_config)


plugin = dict(
    get_massagers=get_massagers,
    get_masters=get_masters)
