from ploy.tests.dummy_plugin import Master as BaseMaster, get_instance_massagers
from ploy.proxy import ProxyInstance


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


def get_masters(ctrl):
    masters = ctrl.config.get('dummy-master', {'default': {}})
    for master, master_config in masters.items():
        yield Master(ctrl, master, master_config)


plugin = dict(
    get_massagers=get_massagers,
    get_masters=get_masters)
