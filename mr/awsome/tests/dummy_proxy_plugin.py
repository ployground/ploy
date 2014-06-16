from mr.awsome.tests.dummy_plugin import Master as BaseMaster, get_instance_massagers
from mr.awsome.proxy import ProxyInstance


class Master(BaseMaster):
    def __init__(self, *args, **kwargs):
        BaseMaster.__init__(self, *args, **kwargs)
        if 'instance' not in self.master_config:
            instance = self.instance_class(self, self.id, self.master_config)
        else:
            instance = self.master_config['instance']
        self.instance = ProxyInstance(self, self.id, self.master_config, instance)
        self.instance.sectiongroupname = self.sectiongroupname
        self.instances[self.id] = self.instance


def get_massagers():
    return get_instance_massagers('dummy-instance')


def get_masters(aws):
    masters = aws.config.get('dummy-master', {'default': {}})
    for master, master_config in masters.iteritems():
        yield Master(aws, master, master_config)


plugin = dict(
    get_massagers=get_massagers,
    get_masters=get_masters)
