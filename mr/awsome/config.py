from mr.awsome.common import Hooks
from ConfigParser import RawConfigParser
import os
import warnings


class BaseMassager(object):
    def __init__(self, sectiongroupname, key):
        self.sectiongroupname = sectiongroupname
        self.key = key

    def __call__(self, main_config, sectionname):
        return main_config[self.sectiongroupname][sectionname][self.key]


class BaseMassagerPlugin(BaseMassager):
    plugin = True


class BooleanMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        if value.lower() in ('true', 'yes', 'on'):
            return True
        elif value.lower() in ('false', 'no', 'off'):
            return False
        raise ValueError("Unknown value %s for %s in %s:%s." % (value, self.key, self.sectiongroupname, sectionname))


class IntegerMassager(BaseMassager):
    def __call__(self, config, sectionname):
        value = config[self.sectiongroupname][sectionname][self.key]
        return int(value)


class PathMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        value = os.path.expanduser(value)
        if not os.path.isabs(value):
            value = os.path.join(main_config.path, value)
        return value


def resolve_dotted_name(value):
    if '.' in value:
        prefix, name = value.rsplit('.', 1)
        _temp = __import__(prefix, globals(), locals(), [name], -1)
        return getattr(_temp, name)
    else:
        return __import__(value, globals(), locals(), [], -1)


class HooksMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        hooks = Hooks()
        for hook_spec in value.split():
            hooks.add(resolve_dotted_name(hook_spec)())
        return hooks


class MassagersMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        massagers = []
        for spec in value.split('\n'):
            spec = spec.strip()
            if not spec:
                continue
            key, massager = spec.split('=')
            sectiongroupname, key = tuple(x.strip() for x in key.split(':'))
            massager = resolve_dotted_name(massager.strip())
            massagers.append(massager(sectiongroupname, key))
        return massagers


class StartupScriptMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        result = dict()
        if value.startswith('gzip:'):
            value = value[5:]
            result['gzip'] = True
        if not os.path.isabs(value):
            value = os.path.join(main_config.path, value)
        result['path'] = value
        return result


class UserMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        if value == "*":
            import pwd
            value = pwd.getpwuid(os.getuid())[0]
        return value


class Config(dict):
    def _add_massager(self, massager):
        key = (massager.sectiongroupname, massager.key)
        if key in self.massagers:
            if not getattr(self.massagers[key], 'plugin', False):
                raise ValueError("Massager for option '%s' in section group '%s' already registered." % (massager.key, massager.sectiongroupname))
        self.massagers[key] = massager

    def _load_plugins(self):
        if self._bbb_config and 'plugin' not in self:
            # define default plugins for backward compatibility
            self['plugin'] = {
                'ec2': {
                    'module': 'mr.awsome.ec2'},
                'plain': {
                    'module': 'mr.awsome.plain'}}
            if 'instance' in self:
                warnings.warn("The 'instance' section type is deprecated, use 'ec2-instance' instead.")
                self['ec2-instance'] = self['instance']
                del self['instance']
            if 'securitygroup' in self:
                warnings.warn("The 'securitygroup' section type is deprecated, use 'ec2-securitygroup' instead.")
                self['ec2-securitygroup'] = self['securitygroup']
                del self['securitygroup']
            if 'server' in self:
                warnings.warn("The 'server' section type is deprecated, use 'plain-instance' instead.")
                self['plain-instance'] = self['server']
                del self['server']
            if 'global' in self and 'aws' in self['global']:
                warnings.warn("The 'aws' section type is deprecated, define an 'ec2-master' instead.")
                self.setdefault('ec2-master', {})
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
            for massager in getattr(module, 'get_massagers', lambda: [])():
                self._add_massager(massager)
            get_macro_cleaners = getattr(module, 'get_macro_cleaners', None)
            if get_macro_cleaners is not None:
                self.macro_cleaners.update(get_macro_cleaners(config))

    def _expand(self, sectiongroupname, sectionname, section, seen):
        if (sectiongroupname, sectionname) in seen:
            raise ValueError("Circular macro expansion.")
        seen.add((sectiongroupname, sectionname))
        macronames = section['<'].split()
        for macroname in macronames:
            if ':' in macroname:
                macrogroupname, macroname = macroname.split(':')
            else:
                macrogroupname = sectiongroupname
            macro = self[macrogroupname][macroname]
            if '<' in macro:
                self._expand(macrogroupname, macroname, macro, seen)
            if sectiongroupname in self.macro_cleaners:
                macro = dict(macro)
                self.macro_cleaners[sectiongroupname](macro)
            for key in macro:
                if key not in section:
                    section[key] = macro[key]
        # this needs to be after the recursive _expand call, so circles are
        # properly detected
        del section['<']

    def __init__(self, config, path=None, bbb_config=False):
        self.config = config
        self.path = path
        self._bbb_config = bbb_config
        self.massagers = {}
        self.macro_cleaners = {}

    def parse(self):
        _config = RawConfigParser()
        _config.optionxform = lambda s: s
        if getattr(self.config, 'read', None) is not None:
            _config.readfp(self.config)
        else:
            _config.read(self.config)
            self.path = os.path.dirname(self.config)
        for section in _config.sections():
            if ':' in section:
                sectiongroupname, sectionname = section.split(':')
            else:
                sectiongroupname, sectionname = 'global', section
            items = dict(_config.items(section))
            sectiongroup = self.setdefault(sectiongroupname, {})
            sectiongroup.setdefault(sectionname, {}).update(items)
        self._load_plugins()
        seen = set()
        for sectiongroupname in self:
            sectiongroup = self[sectiongroupname]
            for sectionname in sectiongroup:
                section = sectiongroup[sectionname]
                if '<' in section:
                    self._expand(sectiongroupname, sectionname, section, seen)
                if 'massagers' in section:
                    massagers = MassagersMassager(
                        sectiongroupname,
                        'massagers')(self, sectionname)
                    for massager in massagers:
                        self._add_massager(massager)
                for key in section:
                    massage = self.massagers.get((sectiongroupname, key))
                    if callable(massage):
                        section[key] = massage(self, sectionname)
        return self

    def get_section_with_overrides(self, sectiongroupname, sectionname, overrides):
        config = self[sectiongroupname][sectionname].copy()
        config['__groupname__'] = sectiongroupname
        config['__name__'] = sectionname
        if overrides is None:
            return config
        dummy = {sectiongroupname: {sectionname: config}}
        for key in overrides:
            config[key] = overrides[key]
            massage = self.massagers.get((sectiongroupname, key))
            if callable(massage):
                config[key] = massage(dummy, sectionname)
        return config
