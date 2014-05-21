from mr.awsome.common import BaseInstance, BaseMaster, StartupScriptMixin
from mr.awsome.config import HooksMassager
from mr.awsome.config import StartupScriptMassager
import logging


log = logging.getLogger('mr.awsome.dummy_plugin')


class MockSock(object):
    def close(self):
        log.info('sock.close')


class MockTransport(object):
    sock = MockSock()


class MockClient(object):
    def get_transport(self):
        log.info('client.get_transport')
        return MockTransport()

    def close(self):
        log.info('client.close')


class Instance(BaseInstance, StartupScriptMixin):
    sectiongroupname = 'dummy-instance'
    max_startup_script_size = 1024

    def get_host(self):
        return self.config['host']

    def get_massagers(self):
        return get_instance_massagers()

    def snapshot(self):
        log.info('snapshot: %s', self.id)

    def start(self, overrides=None):
        self.startup_script(overrides=overrides)
        log.info('start: %s %s', self.id, overrides)
        # this is here to get full coverage of the cmd_start method in common.py
        if overrides.keys() != ['servers']:
            return overrides

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


def get_instance_massagers(sectiongroupname='instance'):
    return [
        HooksMassager(sectiongroupname, 'hooks'),
        StartupScriptMassager(sectiongroupname, 'startup_script')]


def get_massagers():
    return get_instance_massagers('dummy-instance')


def get_masters(aws):
    masters = aws.config.get('dummy-master', {'default': {}})
    for master, master_config in masters.iteritems():
        yield Master(aws, master, master_config)


plugin = dict(
    get_massagers=get_massagers,
    get_masters=get_masters)
