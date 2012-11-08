import fabric.network
try:
    import paramiko
    paramiko  # shutup pyflakes
except ImportError:
    import ssh as paramiko


instances = None
log = None


class HostConnectionCache(object):
    def __init__(self):
        self._cache = dict()

    def keys(self):
        return self._cache.keys()

    def opened(self, key):
        return key in self._cache

    def __delitem__(self, key):
        self._cache[key].close()
        del self._cache[key]

    def __contains__(self, key):
        return key in self._cache

    def __getitem__(self, key):
        r = fabric.network.host_regex.match(key).groupdict()
        user = r['user'] or 'root'
        host = r['host']
        if key in self._cache:
            return self._cache[key]
        server = instances[host]
        try:
            user, host, port, client, known_hosts = server.init_ssh_key(user=user)
        except paramiko.SSHException, e:
            log.error("Couldn't validate fingerprint for ssh connection.")
            log.error(e)
            log.error("Is the server finished starting up?")
            return
        self._cache[key] = client
        return client


def normalize(host_string, omit_port=False):
    # Gracefully handle "empty" input by returning empty output
    if not host_string:
        return ('', '') if omit_port else ('', '', '')
    # Get user, host and port separately
    r = fabric.network.host_regex.match(host_string).groupdict()
    user = r['user'] or 'root'
    host = r['host']
    port = r['port'] or '22'
    if host in instances:
        host = instances[host].get_host()
    if omit_port:
        return user, host
    return user, host, port


def patch():
    fabric.network.normalize = normalize
    fabric.network.HostConnectionCache = HostConnectionCache
