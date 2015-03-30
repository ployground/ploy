from lazy import lazy
from ploy.common import BaseInstance
from ploy.config import ConfigSection
import logging
import sys


log = logging.getLogger('ploy')


class ProxyConfigSection(ConfigSection):
    def __setitem__(self, name, value):
        ConfigSection.__setitem__(self, name, value)
        if not hasattr(self, '_proxied'):
            return
        self._proxied[name] = value

    def __delitem__(self, name):
        ConfigSection.__delitem__(self, name)
        if not hasattr(self, '_proxied'):
            return
        del self._proxied[name]


class ProxyInstance(BaseInstance):
    def __init__(self, master, sid, config, instance):
        _config = ProxyConfigSection()
        _config.update(config)
        if isinstance(instance, BaseInstance):
            self.__dict__['_proxied_instance'] = instance
            _config._proxied = instance.config
        else:
            self._proxied_id = instance
        BaseInstance.__init__(self, master, sid, _config)

    @lazy
    def _proxied_instance(self):
        ctrl = self.__dict__['master'].ctrl
        if 'masters' not in ctrl.__dict__:
            raise AttributeError()
        instances = ctrl.instances
        if self._proxied_id not in instances:
            log.error(
                "The to be proxied instance '%s' for master '%s' wasn't found." % (
                    self._proxied_id,
                    self.master.id))
            sys.exit(1)
        orig = instances[self._proxied_id]
        config = orig.config.copy()
        config.update(self.__dict__['config'])
        config.massagers.clear()
        instance = orig.__class__(orig.master, orig.id, config)
        self.config.update(config)
        self.config._proxied = instance.config
        return instance

    def __getattr__(self, name):
        if '_proxied_instance' not in self.__dict__ and name == 'validate_id':
            raise AttributeError(name)
        return getattr(self._proxied_instance, name)
