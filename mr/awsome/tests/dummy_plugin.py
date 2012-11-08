from mr.awsome.common import BaseMaster, StartupScriptMixin
from mr.awsome.config import StartupScriptMassager
import logging


log = logging.getLogger('mr.awsome.dummy_plugin')


class MockClient(object):
    def close(self):
        log.info('client.close')


class Instance(StartupScriptMixin):
    max_startup_script_size = 1024

    def __init__(self, master, sid, config):
        self.id = sid
        self.master = master
        self.config = config

    def get_host(self):
        return self.config['host']

    def start(self, overrides=None):
        log.info('start: %s %s', self.id, overrides)

    def status(self):
        log.info('status: %s', self.id)

    def stop(self):
        log.info('stop: %s', self.id)

    def terminate(self):
        log.info('terminate: %s', self.id)

    def init_ssh_key(self, user=None):
        host = self.get_host()
        port = self.config.get('port', 22)
        log.info('init_ssh_key: %s %s', self.id, user)
        if user is None:
            user = self.config.get('user', 'root')
        return dict(
            user=user,
            host=host,
            port=port,
            client=MockClient(),
            UserKnownHostsFile=self.master.known_hosts)


class Master(BaseMaster):
    sectiongroupname = 'dummy-instance'
    instance_class = Instance


def get_massagers():
    return [
        StartupScriptMassager('dummy-instance', 'startup_script')]


def get_masters(main_config):
    masters = main_config.get('dummy-master', {'default': {}})
    for master, master_config in masters.iteritems():
        yield Master(main_config, master, master_config)
