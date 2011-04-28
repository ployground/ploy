from ConfigParser import RawConfigParser
import os


class BaseMassager(object):
    def __init__(self, sectiongroupname, key):
        self.sectiongroupname = sectiongroupname
        self.key = key

    def __call__(self, main_config, sectionname):
        return main_config[self.sectiongroupname][sectionname][self.key]


class BooleanMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        if value.lower() in ('true', 'yes', 'on'):
            return True
        elif value.lower() in ('false', 'no', 'off'):
            return False
        raise ValueError("Unknown value %s for %s in %s:%s." % (value, self.key, self.sectiongroupname, sectionname))


class PathMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        if not os.path.isabs(value):
            value = os.path.join(main_config.path, value)
        return value


class UserMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        if value == "*":
            import pwd
            value = pwd.getpwuid(os.getuid())[0]
        return value


class Config(dict):
    def _load_plugins(self):
        if self._bbb_config and 'plugin' not in self:
            # define default plugins for backward compatibility
            self['plugin'] = {
                'ec2': {
                    'module': 'mr.awsome.ec2'},
                'plain': {
                    'module': 'mr.awsome.plain'}}
            if 'instance' in self:
                self['ec2-instance'] = self['instance']
                del self['instance']
            if 'securitygroup' in self:
                self['ec2-securitygroup'] = self['securitygroup']
                del self['securitygroup']
            if 'server' in self:
                self['plain-instance'] = self['server']
                del self['server']
            if 'global' in self and 'aws' in self['global']:
                self['ec2-master'] = {}
                self['ec2-master']['default'] = self['global']['aws']
                del self['global']['aws']
                if len(self['global']) == 0:
                    del self['global']
            if 'plain-master' not in self:
                self['plain-master'] = {'default': {}}
        for config in self.get('plugin', {}).values():
            if '.' in config['module']:
                prefix, name = config['module'].rsplit('.', 1)
                _temp = __import__(prefix, globals(), locals(), [name], -1)
                module = getattr(_temp, name)
            else:
                module = __import__(config['module'], globals(), locals(), [], -1)
            config['module'] = module
            for massager in getattr(module, 'get_massagers', lambda:[])():
                key = (massager.sectiongroupname, massager.key)
                if key in self.massagers:
                    raise ValueError("Massager for option '%s' in section group '%s' already registered." % (massager.key, massager.sectiongroupname))
                self.massagers[key] = massager
            get_macro_cleaners = getattr(module, 'get_macro_cleaners', None)
            if get_macro_cleaners is not None:
                self.macro_cleaners.update(get_macro_cleaners(config))

    def _expand(self, sectiongroupname, sectionname, section, seen):
        if (sectiongroupname, sectionname) in seen:
            raise ValueError("Circular macro expansion.")
        macrogroupname = sectiongroupname
        macroname = section['<']
        seen.add((sectiongroupname, sectionname))
        if ':' in macroname:
            macrogroupname, macroname = macroname.split(':')
        macro = self[macrogroupname][macroname]
        if '<' in macro:
            self._expand(macrogroupname, macroname, macro, seen)
        # this needs to be after the recursive _expand call, so circles are
        # properly detected
        del section['<']
        if sectiongroupname in self.macro_cleaners:
            macro = dict(macro)
            self.macro_cleaners[sectiongroupname](macro)
        for key in macro:
            if key not in section:
                section[key] = macro[key]

    def __init__(self, config, path=None, bbb_config=False):
        self._bbb_config = bbb_config
        _config = RawConfigParser()
        _config.optionxform = lambda s: s
        if getattr(config, 'read', None) is not None:
            _config.readfp(config)
            self.path = path
        else:
            _config.read(config)
            self.path = os.path.dirname(config)
        for section in _config.sections():
            if ':' in section:
                sectiongroupname, sectionname = section.split(':')
            else:
                sectiongroupname, sectionname = 'global', section
            items = dict(_config.items(section))
            sectiongroup = self.setdefault(sectiongroupname, {})
            sectiongroup.setdefault(sectionname, {}).update(items)
        self.massagers = {}
        self.macro_cleaners = {}
        self._load_plugins()
        seen = set()
        for sectiongroupname in self:
            sectiongroup = self[sectiongroupname]
            for sectionname in sectiongroup:
                section = sectiongroup[sectionname]
                if '<' in section:
                    self._expand(sectiongroupname, sectionname, section, seen)
                for key in section:
                    massage = self.massagers.get((sectiongroupname, key))
                    if callable(massage):
                        section[key] = massage(self, sectionname)
