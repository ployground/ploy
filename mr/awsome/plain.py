import os


class Instance(object):
    def __init__(self, master, sid, config):
        self.id = sid
        self.master = master
        self.config = config

    def get_host(self):
        return self.config['host']

    def get_fingerprint(self):
        from paramiko import SSHException

        fingerprint = self.config.get('fingerprint')
        if fingerprint is None:
            raise SSHException("No fingerprint set in config")
        return fingerprint

    def init_ssh_key(self, user=None):
        import paramiko

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

        host = self.get_host()
        port = self.config.get('port', 22)
        client = paramiko.SSHClient()
        sshconfig = paramiko.SSHConfig()
        sshconfig.parse(open(os.path.expanduser('~/.ssh/config')))
        fingerprint = self.get_fingerprint()
        client.set_missing_host_key_policy(ServerHostKeyPolicy(fingerprint))
        known_hosts = self.master.known_hosts
        while 1:
            if os.path.exists(known_hosts):
                client.load_host_keys(known_hosts)
            try:
                hostname = sshconfig.lookup(host).get('hostname', host)
                port = sshconfig.lookup(host).get('port', port)
                if user is None:
                    user = sshconfig.lookup(host).get('user', 'root')
                    user = self.config.get('user', user)
                client.connect(hostname, int(port), user)
                break
            except paramiko.BadHostKeyException:
                if os.path.exists(known_hosts):
                    os.remove(known_hosts)
                client.get_host_keys().clear()
        client.save_host_keys(known_hosts)
        return user, host, port, client, known_hosts


class Master(object):
    def __init__(self, config, id):
        self.id = id
        self.config = config
        self.known_hosts = os.path.join(self.config.path, 'known_hosts')
        self.instances = {}
        for sid, config in self.config.get('plain-instance', {}).iteritems():
            self.instances[sid] = Instance(self, sid, config)


def get_massagers():
    def massage_fabfile(config, value):
        if not os.path.isabs(value):
            value = os.path.join(config.path, value)
        return value

    def massage_user(config, value):
        if value == "*":
            import pwd
            value = pwd.getpwuid(os.getuid())[0]
        return value

    return {
        ("plain-instance", 'user'): massage_user,
        ("plain-instance", 'fabfile'): massage_fabfile}


def get_masters(config):
    masters = config.get('plain-master', {'default': {}})
    for master in masters:
        yield Master(config, master)
