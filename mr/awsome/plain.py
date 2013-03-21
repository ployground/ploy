from mr.awsome.common import BaseMaster, FabricMixin
import os


class InstanceFormattingWrapper(object):
    def __init__(self, instance):
        self.instance = instance

    def __getattr__(self, name):
        return self.instance.config[name]


class Instance(FabricMixin):
    def __init__(self, master, sid, config):
        self.id = sid
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

    def init_ssh_key(self, user=None):
        try:  # pragma: no cover - we support both
            import paramiko
            paramiko  # shutup pyflakes
        except ImportError:  # pragma: no cover - we support both
            import ssh as paramiko

        class ServerHostKeyPolicy(paramiko.MissingHostKeyPolicy):
            def __init__(self, fingerprint):
                self.fingerprint = fingerprint

            def missing_host_key(self, client, hostname, key):
                fingerprint = ':'.join("%02x" % ord(x) for x in key.get_fingerprint())
                if fingerprint == self.fingerprint:
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
        client = paramiko.SSHClient()
        sshconfig = paramiko.SSHConfig()
        sshconfig.parse(open(os.path.expanduser('~/.ssh/config')))
        fingerprint = self.get_fingerprint()
        client.set_missing_host_key_policy(ServerHostKeyPolicy(fingerprint))
        known_hosts = self.master.known_hosts
        proxy_command = self.config.get('proxycommand', None)
        if proxy_command is None:
            proxy_command = sshconfig.lookup(host).get('proxycommand', None)
        else:
            d = dict(
                (k, InstanceFormattingWrapper(v))
                for k, v in self.master.instances.items())
            d.update(self.config)
            proxy_command = proxy_command.format(**d)
        if proxy_command:
            sock = paramiko.ProxyCommand(proxy_command)
        else:
            sock = None
        while 1:
            if os.path.exists(known_hosts):
                client.load_host_keys(known_hosts)
            try:
                hostname = sshconfig.lookup(host).get('hostname', host)
                port = sshconfig.lookup(host).get('port', port)
                if user is None:
                    user = sshconfig.lookup(host).get('user', 'root')
                    user = self.config.get('user', user)
                client_args = dict(
                    port=int(port),
                    username=user,
                    key_filename=self.config.get('ssh-key-filename', None),
                    sock=sock)
                client.connect(hostname, **client_args)
                break
            except paramiko.BadHostKeyException:
                if os.path.exists(known_hosts):
                    os.remove(known_hosts)
                client.get_host_keys().clear()
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
    from mr.awsome.config import PathMassager, UserMassager

    sectiongroupname = 'plain-instance'
    return [
        UserMassager(sectiongroupname, 'user'),
        PathMassager(sectiongroupname, 'fabfile')]


def get_masters(main_config):
    masters = main_config.get('plain-master', {'default': {}})
    for master, master_config in masters.iteritems():
        yield Master(main_config, master, master_config)
