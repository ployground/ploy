import paramiko


class HostConnectionCache(object):
    def __init__(self):
        self._cache = dict()

    def set_ec2(self, ec2):
        self._ec2 = ec2

    def set_log(self, log):
        self._log = log

    def keys(self):
        return self._cache.keys()

    def opened(self, key):
        if key in self._cache:
            return True

    def __getitem__(self, key):
        if key not in self._cache and key in self._ec2.servers:
            server = self._ec2.servers[key]
            try:
                user, host, port, client, known_hosts = server.init_ssh_key()
            except paramiko.SSHException, e:
                self._log.error("Couldn't validate fingerprint for ssh connection.")
                self._log.error(e)
                self._log.error("Is the server finished starting up?")
                return
            self._cache[key] = client
            return client
        return self._cache[key]


def patch():
    import fabric.network
    fabric.network.HostConnectionCache = HostConnectionCache
