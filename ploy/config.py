from __future__ import unicode_literals
from ploy.common import Hooks
try:
    import configparser
except ImportError:  # pragma: nocover
    import ConfigParser as configparser  # for Python 2.7
from collections import MutableMapping
from io import BytesIO
from ploy.common import split_option
from pluggy import HookimplMarker
from weakref import proxy
import attr
import inspect
import logging
import os
import sys
import warnings


log = logging.getLogger('ploy')
hookimpl = HookimplMarker("ploy")


try:
    basestring
except NameError:  # pragma: nocover
    basestring = str


_marker = object()


def value_asbool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in ('true', 'yes', 'on'):
        return True
    elif value.lower() in ('false', 'no', 'off'):
        return False


class BaseMassager(object):
    def __init__(self, sectiongroupname, key):
        self.sectiongroupname = sectiongroupname
        self.key = key

    def path(self, config, sectionname):
        return config.get_path(self.key)

    def __call__(self, config, sectionname):
        value = config._dict[self.key]
        if isinstance(value, ConfigValue):
            return value.value
        return value


class BooleanMassager(BaseMassager):
    def __call__(self, config, sectionname):
        value = BaseMassager.__call__(self, config, sectionname)
        value = value_asbool(value)
        if value is None:
            raise ValueError("Unknown value %s for %s in %s:%s." % (value, self.key, self.sectiongroupname, sectionname))
        return value


class IntegerMassager(BaseMassager):
    def __call__(self, config, sectionname):
        value = BaseMassager.__call__(self, config, sectionname)
        return int(value)


def expand_path(value, base):
    value = os.path.expanduser(value)
    if not os.path.isabs(value):
        value = os.path.join(base, value)
    return os.path.normpath(value)


class PathMassager(BaseMassager):
    _massage_for_yaml = False

    def __call__(self, config, sectionname):
        value = BaseMassager.__call__(self, config, sectionname)
        return expand_path(value, self.path(config, sectionname))


def resolve_dotted_name(value):
    if '.' in value:
        prefix, name = value.rsplit('.', 1)
        _temp = __import__(prefix, globals(), locals(), [str(name)])
        return getattr(_temp, name)
    else:
        return __import__(value, globals(), locals(), [])


class HooksMassager(BaseMassager):
    _massage_for_yaml = False

    def __call__(self, config, sectionname):
        value = BaseMassager.__call__(self, config, sectionname)
        hooks = Hooks()
        for hook_spec in value.split():
            hooks.add(resolve_dotted_name(hook_spec)())
        return hooks


class StartupScriptMassager(BaseMassager):
    _massage_for_yaml = False

    def __call__(self, config, sectionname):
        value = BaseMassager.__call__(self, config, sectionname)
        if not value:
            return
        result = dict()
        if value.startswith('gzip:'):
            value = value[5:]
            result['gzip'] = True
        if not os.path.isabs(value):
            value = os.path.join(self.path(config, sectionname), value)
        result['path'] = value
        return result


class UserMassager(BaseMassager):
    _massage_for_yaml = False

    def __call__(self, config, sectionname):
        value = BaseMassager.__call__(self, config, sectionname)
        if value == "*":
            import pwd
            value = pwd.getpwuid(os.getuid())[0]
        return value


@attr.s(slots=True)
class ConfigValue(object):
    path = attr.ib()
    value = attr.ib()
    src = attr.ib(default=None)
    comment = attr.ib(default=None)


def get_package_name(module):
    f = getattr(module, '__file__', '')
    if (('__init__.py' in f) or ('__init__$py' in f)):  # empty at >>>
        # Module is a package
        return module.__name__
    else:
        return module.__name__.rsplit('.', 1)[0]


def get_caller_src():
    skip = frozenset([
        ('_abcoll', 'setdefault'),
        ('_abcoll', 'update'),
        ('ploy.config', '__init__'),
        ('ploy.proxy', '__setitem__')])
    stop = frozenset([
        ('ploy.proxy', '__init__'),
        ('ploy.proxy', '_proxied_instance')])
    frame = sys._getframe(2)
    while frame.f_back is not None:
        f_code = frame.f_code
        lineno = frame.f_lineno
        module_globals = frame.f_globals
        frame = frame.f_back
        module_name = module_globals.get('__name__') or '__main__'
        if (module_name, f_code.co_name) in skip:
            continue
        if (module_name, f_code.co_name) in stop:
            return
        package_name = get_package_name(sys.modules[module_name])
        f = getattr(sys.modules[package_name], '__file__', '')
        path = os.path.relpath(f_code.co_filename, os.path.dirname(f))
        return "%s:%s:%s" % (package_name, path, lineno)
    sys.exit(0)


class ConfigSection(MutableMapping):
    def __init__(self, *args, **kw):
        self._dict = {}
        for k, v in dict(*args, **kw).items():
            self[k] = v
        self.sectionname = None
        self.sectiongroupname = None
        self._config = None
        self.massagers = {}

    def add_massager(self, massager):
        key = (massager.sectiongroupname, massager.key)
        existing = self.massagers.get(key)
        if existing is not None:
            equal_class = massager.__class__ == existing.__class__
            equal_vars = vars(massager) == vars(existing)
            if equal_class and equal_vars:
                # massager is same as existing
                return
            raise ValueError("Massager for option '%s' in section group '%s' already registered." % (massager.key, massager.sectiongroupname))
        self.massagers[key] = massager

    def __delitem__(self, key):
        del self._dict[key]

    def get_path(self, key, default=_marker):
        if default is not _marker:
            if key not in self._dict:
                return default
        return self._dict[key].path

    def _get_massager(self, key):
        if key in self._dict:
            if self._config is not None:
                massage = self._config.massagers.get((self.sectiongroupname, key))
                if not callable(massage):
                    massage = self._config.massagers.get((None, key))
                    if callable(massage):
                        if len(inspect.getargspec(massage.__call__).args) == 3:
                            return (massage, (self.sectionname,))
                        else:
                            return (massage, (self.sectiongroupname, self.sectionname))
                else:
                    return (massage, (self.sectionname,))
            massage = self.massagers.get((self.sectiongroupname, key))
            if callable(massage):
                return (massage, (self.sectionname, ))
        return (None, None)

    def __getitem__(self, key):
        if key == '__groupname__':
            return self.sectiongroupname
        if key == '__name__':
            return self.sectionname
        (massager, args) = self._get_massager(key)
        if massager is not None:
            return massager(self, *args)
        value = self._dict[key]
        if isinstance(value, ConfigValue):
            return value.value
        return value

    def __setitem__(self, key, value):
        if not isinstance(value, ConfigValue):
            src = None
            if not isinstance(value, ConfigSection):
                src = get_caller_src()
            value = ConfigValue(None, value, src=src)
        self._dict[key] = value
        if self._config is not None:
            self._config._values.append(
                (self.sectiongroupname, self.sectionname, key, value))

    def keys(self):
        return self._dict.keys()

    def __len__(self):
        return len(self._dict)

    def __iter__(self):
        return iter(self.keys())

    def copy(self):
        new = ConfigSection()
        new._dict = self._dict.copy()
        new.sectionname = self.sectionname
        new.sectiongroupname = self.sectiongroupname
        new.massagers = self.massagers.copy()
        new._config = self._config
        return new

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, dict(self))


class ConfigParser(configparser.RawConfigParser):
    def optionxform(self, s):
        return s


@attr.s(slots=True)
class _RawConfigValue(object):
    src = attr.ib()
    path = attr.ib()
    section = attr.ib()
    key = attr.ib()
    value = attr.ib()
    comments = attr.ib(default=(None, None))


class _ConfigDict(configparser._default_dict):
    prefix_comment = None
    key_prefix_comments = None
    key_comments = None

    def set_prefix_comment(self, value):
        self.prefix_comment = value

    def set_key_prefix_comment(self, key, value):
        if self.key_prefix_comments is None:
            self.key_prefix_comments = dict()
        self.key_prefix_comments[key] = value

    def set_key_comment(self, key, value):
        if self.key_comments is None:
            self.key_comments = dict()
        self.key_comments[key] = value


class CommentedConfigParser(configparser.RawConfigParser):
    def _read(self, fp, fpname):
        self._dict = _ConfigDict
        cursect = None                        # None, or a dictionary
        optname = None
        lineno = 0
        e = None                              # None, or an exception
        comments = []
        while True:
            line = fp.readline()
            if not line:
                if comments:
                    self.comments = comments
                break
            lineno = lineno + 1
            # blank line?
            if line.strip() == '':
                continue
            # comment?
            if line[0] in '#;':
                comments.append((line[0:1], line[1:]))
                continue
            if line.split(None, 1)[0].lower() == 'rem' and line[0] in "rR":
                comments.append((line[0:3], line[3:]))
                # no leading whitespace
                continue
            # continuation line?
            if line[0].isspace() and cursect is not None and optname:
                value = line.strip()
                if value:
                    cursect[optname].append(value)
            # a section header or option header?
            else:
                # is it a section header?
                mo = self.SECTCRE.match(line)
                if mo:
                    sectname = mo.group('header')
                    if sectname in self._sections:
                        cursect = self._sections[sectname]
                    elif sectname == configparser.DEFAULTSECT:
                        cursect = self._defaults
                    else:
                        cursect = self._dict()
                        cursect['__name__'] = sectname
                        self._sections[sectname] = cursect
                    if comments:
                        cursect.set_prefix_comment(comments)
                        comments = []
                    # So sections can't start with a continuation line
                    optname = None
                # no section header in the file?
                elif cursect is None:
                    raise configparser.MissingSectionHeaderError(fpname, lineno, line)
                # an option line?
                else:
                    mo = self._optcre.match(line)
                    if mo:
                        optname, vi, optval = mo.group('option', 'vi', 'value')
                        optname = optname.rstrip()
                        if comments:
                            cursect.set_key_prefix_comment(optname, comments)
                            comments = []
                        # This check is fine because the OPTCRE cannot
                        # match if it would set optval to None
                        if optval is not None:
                            if vi in ('=', ':') and ';' in optval:
                                # ';' is a comment delimiter only if it follows
                                # a spacing character
                                pos = optval.find(';')
                                if pos != -1 and optval[pos - 1].isspace():
                                    cursect.set_key_comment(
                                        optname, [(optval[pos:pos + 1], optval[pos + 1:])])
                                    optval = optval[:pos]
                            optval = optval.strip()
                            # allow empty values
                            if optval == '""':
                                optval = ''
                            cursect[optname] = [optval]
                        else:
                            # valueless option handling
                            cursect[optname] = optval
                    else:
                        # a non-fatal parsing error occurred.  set up the
                        # exception but keep going. the exception will be
                        # raised at the end of the file and will contain a
                        # list of all bogus lines
                        if not e:
                            e = configparser.ParsingError(fpname)
                        e.append(lineno, repr(line))
        # if any parsing errors occurred, raise an exception
        if e:
            raise e

        # join the multi-line values collected while reading
        all_sections = [self._defaults]
        all_sections.extend(self._sections.values())
        for options in all_sections:
            for name, val in options.items():
                if isinstance(val, list):
                    options[name] = '\n'.join(val)


def _read_config(config, path, parser, shallow=False):
    result = []
    stack = [config]
    seen = set()
    while 1:
        config = stack.pop()
        if config in seen:
            log.error("Circular config file extension on '%s'.", config)
            sys.exit(1)
        seen.add(config)
        src = None
        if isinstance(config, basestring):
            src = os.path.relpath(config)
        try:
            _config = parser(
                comment_prefixes=('#', ';', 'REM ', 'rem ', 'REm ', 'ReM ', 'rEM ', 'Rem ', 'rEm ', 'reM '),
                inline_comment_prefixes=(';',))
        except TypeError:
            _config = parser()
        if getattr(config, 'read', None) is not None:
            _config.readfp(config)
            config.seek(0)
        else:
            if not os.path.exists(config):
                log.error("Config file '%s' doesn't exist.", config)
                sys.exit(1)
            _config.read(config)
            path = os.path.dirname(config)
        comments = getattr(_config, 'comments', None)
        if comments is not None:
            assert not isinstance(_config, ConfigParser)
            result.append(_RawConfigValue(
                src=src,
                path=path,
                section=None,
                key=None,
                value=None,
                comments=(comments, None)))
        for sectionname, section in reversed(list(_config._sections.items())):
            key_comments = getattr(section, 'key_comments', None) or {}
            key_prefix_comments = getattr(section, 'key_prefix_comments', None) or {}
            for key, value in reversed(list(section.items())):
                if key == '__name__':
                    continue
                result.append(_RawConfigValue(
                    src=src,
                    path=path,
                    section=sectionname,
                    key=key,
                    value=value,
                    comments=(key_prefix_comments.get(key), key_comments.get(key))))
            prefix_comment = getattr(section, 'prefix_comment', None)
            result.append(_RawConfigValue(
                src=src,
                path=path,
                section=sectionname,
                key=None,
                value=None,
                comments=(prefix_comment, None)))
        if _config.has_option('global', 'extends'):
            extends = _config.get('global', 'extends').split()
        elif _config.has_option('global:global', 'extends'):
            extends = _config.get('global:global', 'extends').split()
        else:
            break
        if shallow:
            break
        stack[0:0] = [
            os.path.abspath(os.path.join(path, x))
            for x in reversed(extends)]
    return list(reversed(result))


def read_config(config, path, shallow=False):
    _control_config = _read_config(config, path, ConfigParser, shallow=shallow)
    _config = _read_config(config, path, CommentedConfigParser, shallow=shallow)
    index = 0
    for item in _config:
        if item.section is None:
            assert item.key is None
            assert item.value is None
            continue
        if _control_config[index].comments != (None, None):
            assert _control_config[index].comments == item.comments
        index += 1
    return _config


def read_yml_config(config, path):
    from ruamel.yaml import YAML
    result = []
    stack = [config]
    seen = set()
    while 1:
        config = stack.pop()
        if config in seen:
            log.error("Circular config file extension on '%s'.", config)
            sys.exit(1)
        seen.add(config)
        yaml = YAML(typ='rt')
        if getattr(config, 'read', None) is not None:
            _config = yaml.load(config)
        else:
            if not os.path.exists(config):
                log.error("Config file '%s' doesn't exist.", config)
                sys.exit(1)
            with open(config, 'r') as f:
                _config = yaml.load(f)
            path = os.path.dirname(config)
        if not _config:
            _config = {}
        src = None
        if isinstance(config, basestring):
            src = os.path.relpath(config)
        for sectiongroupname in reversed(list(_config.keys())):
            for sectionname in reversed(list(_config[sectiongroupname].keys())):
                for key, value in reversed(list(_config[sectiongroupname][sectionname].items())):
                    result.append(_RawConfigValue(
                        src=src,
                        path=path,
                        section="%s:%s" % (sectiongroupname, sectionname),
                        key=key,
                        value=value))
                result.append(_RawConfigValue(
                    src=src,
                    path=path,
                    section="%s:%s" % (sectiongroupname, sectionname),
                    key=None,
                    value=None))
        extends = None
        if 'global' in _config:
            if 'extends' in _config['global']:
                extends = _config['global']['extends'].split()
            elif 'global' in _config['global'] and 'extends' in _config['global']['global']:
                extends = _config['global']['global']['extends'].split()
        if not extends:
            break
        stack[0:0] = [
            os.path.abspath(os.path.join(path, x))
            for x in reversed(extends)]
    return reversed(result)


def _make_comment(value, indent):
    from ruamel import yaml
    result = []
    for item in value.split('\n'):
        result.append(
            yaml.tokens.CommentToken(
                "#%s\n" % item,
                yaml.error.CommentMark(indent),
                yaml.error.CommentMark(0)))
    return result


class Config(ConfigSection):
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
                macro = macro.copy()
                self.macro_cleaners[sectiongroupname](macro)
            for key in macro:
                if key not in section:
                    section._dict[key] = macro._dict[key]
        # this needs to be after the recursive _expand call, so circles are
        # properly detected
        del section['<']

    def __init__(self, config, path=None, plugins=None):
        ConfigSection.__init__(self)
        self._values = []
        self.config = config
        if path is None:
            if getattr(config, 'read', None) is None:
                path = os.path.dirname(config)
        self.path = path
        self.macro_cleaners = {}
        if plugins is not None:
            for plugin in plugins.values():
                for massager in plugin.get('get_massagers', lambda: [])():
                    self.add_massager(massager)
                if 'get_macro_cleaners' in plugin:
                    self.macro_cleaners.update(plugin['get_macro_cleaners'](self))

    def get_section(self, sectiongroupname, sectionname):
        sectiongroup = self[sectiongroupname]
        if sectionname not in sectiongroup:
            section = ConfigSection()
            section.sectiongroupname = sectiongroupname
            section.sectionname = sectionname
            section._config = proxy(self)
            sectiongroup[sectionname] = section
        return sectiongroup[sectionname]

    def _parse(self, _config):
        for info in _config:
            if info.section is None:
                self._values.append((None, None, None, ConfigValue(info.path, None, src=info.src, comment=info.comments)))
                continue
            if ':' in info.section:
                sectiongroupname, sectionname = info.section.split(':')
            else:
                sectiongroupname, sectionname = 'global', info.section
            if sectiongroupname == 'global' and sectionname == 'global' and info.key == 'extends':
                self._values.append((sectiongroupname, sectionname, info.key, ConfigValue(info.path, info.value, src=info.src, comment=info.comments)))
                continue
            sectiongroup = self.setdefault(sectiongroupname, ConfigSection())
            self.get_section(sectiongroupname, sectionname)
            if info.key is None:
                self._values.append((sectiongroupname, sectionname, info.key, ConfigValue(info.path, info.value, src=info.src, comment=info.comments)))
            else:
                if info.key == 'massagers':
                    for spec in info.value.splitlines():
                        spec = spec.strip()
                        if not spec:
                            continue
                        if '=' not in spec:
                            log.error("Invalid massager spec '%s' in section '%s:%s'.", spec, sectiongroupname, sectionname)
                            sys.exit(1)
                        massager_key, massager = spec.split('=')
                        massager_key = massager_key.strip()
                        massager = massager.strip()
                        if ':' in massager_key:
                            parts = tuple(x.strip() for x in massager_key.split(':'))
                            if len(parts) == 2:
                                massager_sectiongroupname, massager_key = parts
                                massager_sectionname = None
                            elif len(parts) == 3:
                                massager_sectiongroupname, massager_sectionname, massager_key = parts
                            else:
                                log.error("Invalid massager spec '%s' in section '%s:%s'.", spec, sectiongroupname, sectionname)
                                sys.exit(1)
                            if massager_sectiongroupname == '':
                                massager_sectiongroupname = sectiongroupname
                            if massager_sectiongroupname == '*':
                                massager_sectiongroupname = None
                            if massager_sectionname == '':
                                massager_sectionname = sectionname
                        else:
                            massager_sectiongroupname = sectiongroupname
                            massager_sectionname = sectionname
                        try:
                            massager = resolve_dotted_name(massager)
                        except ImportError as e:
                            log.error("Can't import massager from '%s'.\n%s", massager, str(e))
                            sys.exit(1)
                        except AttributeError as e:
                            log.error("Can't import massager from '%s'.\n%s", massager, str(e))
                            sys.exit(1)
                        massager = massager(massager_sectiongroupname, massager_key)
                        if massager_sectionname is None:
                            self.add_massager(massager)
                        else:
                            massager_section = self.get_section(
                                sectiongroupname, massager_sectionname)
                            massager_section.add_massager(massager)
                else:
                    sectiongroup[sectionname][info.key] = ConfigValue(
                        info.path, info.value, src=info.src, comment=info.comments)
        if 'plugin' in self:  # pragma: no cover
            warnings.warn("The 'plugin' section isn't used anymore.")
            del self['plugin']
        seen = set()
        for sectiongroupname in self:
            sectiongroup = self[sectiongroupname]
            for sectionname in sectiongroup:
                section = sectiongroup[sectionname]
                if '<' in section:
                    self._expand(sectiongroupname, sectionname, section, seen)
        return self

    def parse(self):
        if isinstance(self.config, basestring) and self.config.endswith('.yml'):
            _config = read_yml_config(self.config, self.path)
        else:
            _config = read_config(self.config, self.path)
        return self._parse(_config)

    def get_section_with_overrides(self, sectiongroupname, sectionname, overrides):
        config = self[sectiongroupname][sectionname].copy()
        if overrides is not None:
            config._dict.update(overrides)
        return config

    def _dump_yaml(self, writer):
        from ruamel.yaml import YAML
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
        configs = dict()
        sectiongroup = None
        section = None
        for sectiongroupname, sectionname, key, value in self._values:
            if value.comment:
                (prefix_comment, comment) = value.comment
            else:
                (prefix_comment, comment) = (None, None)
            if prefix_comment:
                prefix_comment = "\n".join(x[1].rstrip() for x in prefix_comment)
            if comment:
                comment = "\n".join(x[1][1:].rstrip() for x in comment)
            if value.path:
                conf_key = os.path.abspath(value.src)
            else:
                conf_key = None
            conf = configs.setdefault(conf_key, CommentedMap())
            if sectiongroupname is None:
                assert sectionname is None
                if prefix_comment:
                    conf._yaml_add_comment([None, None])
                    conf.yaml_end_comment_extend(_make_comment(prefix_comment, 0))
                    pass
                continue
            sectiongroup = conf.setdefault(sectiongroupname, CommentedMap())
            section = sectiongroup.setdefault(sectionname, CommentedMap())
            if key is not None:
                configsection = self[sectiongroupname][sectionname]
                out_value = value.value
                _get_massager = getattr(configsection, '_get_massager', None)
                if _get_massager is not None:
                    (massager, args) = configsection._get_massager(key)
                    _massage_for_yaml = getattr(massager, '_massage_for_yaml', True)
                    if _massage_for_yaml:
                        try:
                            out_value = configsection[key]
                        except KeyError:
                            pass
                if isinstance(out_value, basestring):
                    if key == 'extends':
                        out_value = out_value.replace('.conf', '.yml')
                    if '\n' in out_value:
                        out_value = split_option(out_value)
                if isinstance(out_value, (tuple, set)):
                    out_value = list(out_value)
                if isinstance(out_value, list):
                    for index, item in enumerate(out_value):
                        if isinstance(item, dict):
                            out_value[index] = CommentedMap(item.items())
                        if isinstance(item, tuple):
                            out_value[index] = CommentedSeq(item)
                            out_value[index].fa.set_flow_style()
                        if isinstance(item, list):
                            out_value[index] = CommentedSeq(item)
                section[key] = out_value
                if prefix_comment:
                    section._yaml_add_comment([None, _make_comment(prefix_comment, 8)], key=key)
                if comment:
                    section.yaml_add_eol_comment(comment, key=key)
            else:
                if prefix_comment:
                    sectiongroup._yaml_add_comment([None, _make_comment(prefix_comment, 4)], key=sectionname)
        for conf in configs:
            if conf is None:
                dirname = None
                basename = None
            else:
                dirname, basename = os.path.split(conf)
            yaml = YAML(typ='rt')
            content = BytesIO()
            yaml.indent(mapping=4, sequence=4, offset=2)
            yaml.dump(configs[conf], content)
            writer(dirname, basename, content.getvalue())

    def dump_yaml(self):
        def writer(dirname, basename, value):
            if dirname is None:
                return
            filename = os.path.join(dirname, basename.replace('.conf', '.yml'))
            with open(filename, 'w') as f:
                f.write(value)
            log.info('Wrote %s', os.path.relpath(filename))
        self._dump_yaml(writer)
        sys.exit(0)


class ConfigPlugin:
    @hookimpl
    def ploy_locate_config(self, fn):
        if fn.endswith('.conf') and os.path.exists(fn):
            return fn

    @hookimpl
    def ploy_load_config(self, fn, plugins):
        if not fn.endswith('.conf'):
            return
        config = Config(fn, plugins=plugins)
        _config = read_config(config.config, config.path)
        config._parse(_config)
        return config


class YamlConfigPlugin:
    @hookimpl
    def ploy_locate_config(self, fn):
        fn = os.path.splitext(fn)[0] + '.yml'
        if fn.endswith('.yml') and os.path.exists(fn):
            return fn

    @hookimpl
    def ploy_load_config(self, fn, plugins):
        if not fn.endswith('.yml'):
            return
        config = Config(fn, plugins=plugins)
        _config = read_yml_config(config.config, config.path)
        config._parse(_config)
        return config
