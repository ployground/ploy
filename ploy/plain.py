from lazy import lazy
from ploy.common import BaseMaster, BaseInstance
from ploy.common import SSHKeyFingerprint
from ploy.common import SSHKeyFingerprintAsk
from ploy.common import SSHKeyFingerprintIgnore
from ploy.common import SSHKeyFingerprintInstance
from ploy.common import SSHKeyInfo
from ploy.common import import_paramiko
from ploy.common import parse_fingerprint, parse_ssh_keygen
import getpass
import logging
import os
import re
import socket
import subprocess
import sys


log = logging.getLogger('ploy')


def ServerHostKeyPolicy(*args, **kwarks):
    paramiko = import_paramiko()

    class ServerHostKeyPolicy(paramiko.MissingHostKeyPolicy):
        def __init__(self, fingerprints_func):
            self.fingerprints_func = fingerprints_func

        @lazy
        def fingerprints(self):
            return self.fingerprints_func()

        def missing_host_key(self, client, hostname, key):
            ssh_key_info = SSHKeyInfo(key)
            for fingerprint in self.fingerprints:
                if fingerprint in ssh_key_info:
                    if not fingerprint.store:
                        return
                    client.get_host_keys().add(hostname, key.get_name(), key)
                    if client._host_keys_filename is not None:
                        client.save_host_keys(client._host_keys_filename)
                    return
            raise paramiko.SSHException(
                "Fingerprint doesn't match for %s (got %s, expected: %s)" % (
                    hostname,
                    ssh_key_info.get_fingerprints(),
                    [str(x) for x in self.fingerprints]))

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

    def get_port(self):
        return self.config.get('port', 22)

    def get_ssh_fingerprints(self):
        fingerprints = self.config.get('ssh-fingerprints')
        if fingerprints is None:
            fingerprints = self.config.get('fingerprint')
        if fingerprints is None:
            fingerprints = self.master.master_config.get('ssh-fingerprints')
        if fingerprints is None:
            fingerprints = self.master.master_config.get('fingerprint')
        if fingerprints is None:
            if getattr(self, 'get_fingerprint', None) is not None:
                fingerprints = 'auto'
        if fingerprints is None:
            raise self.paramiko.SSHException("No fingerprint set in config.")
        fingerprints = [x.strip() for x in re.split(',|\n', fingerprints.strip())]
        result = []
        for fingerprint in fingerprints:
            path = os.path.join(self.master.main_config.path, fingerprint)
            if os.path.exists(path):
                try:
                    text = subprocess.check_output(['ssh-keygen', '-lf', path])
                except subprocess.CalledProcessError as e:
                    log.error("Couldn't get fingerprint from '%s':\n%s" % (path, e))
                    sys.exit(1)
                result.extend(parse_ssh_keygen(text))
                continue
            if fingerprint.lower() == 'auto':
                result.append(SSHKeyFingerprintInstance(self))
                continue
            if fingerprint.lower() == 'ask':
                result.append(SSHKeyFingerprintAsk())
                continue
            if fingerprint.lower() == 'ignore':
                result.append(SSHKeyFingerprintIgnore())
                continue
            result.append(SSHKeyFingerprint(parse_fingerprint(fingerprint)))
        return result

    @lazy
    def proxy_command(self):
        proxy_command = self.config.get('proxycommand', None)
        if proxy_command is None:
            return self.sshconfig.get('proxycommand', None)
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

    def _fix_known_hosts(self, known_hosts):
        lines = []
        with open(known_hosts, 'r') as f:
            for lineno, line in enumerate(f):
                line = line.strip()
                if (len(line) == 0) or (line[0] == '#'):
                    continue
                try:
                    self.paramiko.hostkeys.HostKeyEntry.from_line(line, lineno)
                except self.paramiko.hostkeys.InvalidHostKey:
                    continue
                lines.append(line + '\n')
        with open(known_hosts, 'w') as f:
            f.writelines(lines)

    def init_ssh_key(self, user=None):
        paramiko = self.paramiko
        try:
            host = self.get_host()
        except KeyError:
            raise paramiko.SSHException("No host or ip set in config.")
        port = self.get_port()
        hostname = self.sshconfig.get('hostname', host)
        port = self.sshconfig.get('port', port)
        password = None
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(ServerHostKeyPolicy(self.get_ssh_fingerprints))
        known_hosts = self.master.known_hosts
        client.known_hosts = None
        while 1:
            sock = self.get_proxy_sock(hostname, port)
            if os.path.exists(known_hosts):
                self._fix_known_hosts(known_hosts)
                client.load_host_keys(known_hosts)
            try:
                if user is None:
                    user = self.sshconfig.get('user', 'root')
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
            UserKnownHostsFile=known_hosts,
            StrictHostKeyChecking="yes")
        for arg in self.config.get('ssh-extra-args', '').splitlines():
            (key, value) = arg.split(None, 1)
            result[key.title()] = value
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
