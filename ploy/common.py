from __future__ import print_function
from lazy import lazy
try:
    from cStringIO import StringIO as BytesIO
except ImportError:  # pragma: no cover
    try:
        from StringIO import StringIO as BytesIO
    except ImportError:
        from io import BytesIO
import gzip
import logging
import re
import sys


log = logging.getLogger('ploy')


try:
    unicode
except NameError:  # pragma: nocover
    unicode = str

try:
    get_input = raw_input
except NameError:  # pragma: nocover
    get_input = input


def import_paramiko():  # pragma: no cover - we support both
    try:
        import paramiko
    except ImportError:
        import ssh as paramiko
    return paramiko


def gzip_string(value):
    s = BytesIO()
    gz = gzip.GzipFile(mode='wb', fileobj=s)
    if not isinstance(value, bytes):
        value = value.encode('ascii')
    gz.write(value)
    gz.close()
    return bytes(s.getvalue())


def strip_hashcomments(value):
    lines = value.splitlines()
    result = []
    if lines and lines[0].rstrip() in ('#!/bin/sh', '#!/bin/bash'):
        for index, line in enumerate(lines):
            if index > 0 and line.strip().startswith('#'):
                continue
            result.append(line)
    else:
        return "\n".join(lines)
    return "\n".join(result)


def yesno(question, default=None, all=False):
    if default is True:
        question = "%s [Yes/no" % question
        answers = {
            False: ('n', 'no'),
            True: ('', 'y', 'yes'),
        }
    elif default is False:
        question = "%s [yes/No" % question
        answers = {
            False: ('', 'n', 'no'),
            True: ('y', 'yes'),
        }
    else:
        question = "%s [yes/no" % question
        answers = {
            False: ('n', 'no'),
            True: ('y', 'yes'),
        }
    if all:
        if default is 'all':
            answers['all'] = ('', 'a', 'all')
            question = "%s/All" % question
        else:
            answers['all'] = ('a', 'all')
            question = "%s/all" % question
    question = "%s] " % question
    while 1:
        answer = get_input(question).lower()
        for option in answers:
            if answer in answers[option]:
                return option
        if all:
            print("You have to answer with y, yes, n, no, a or all.", file=sys.stderr)
        else:
            print("You have to answer with y, yes, n or no.", file=sys.stderr)


class StartupScriptMixin(object):
    def startup_script(self, overrides=None, debug=False):
        from ploy import template  # avoid circular import

        config = self.get_config(overrides)
        startup_script_path = config.get('startup_script', None)
        if startup_script_path is None:
            if debug:
                return dict(original='', raw='')
            else:
                return ''
        try:
            startup_script = template.Template(
                startup_script_path['path'],
                pre_filter=strip_hashcomments,
            )
        except IOError as e:
            if e.args[0] == 2:
                log.error("Startup script '%s' not found.", startup_script_path['path'])
                sys.exit(1)
            raise
        self.hooks.startup_script_options(config)
        result = dict(original=startup_script(**config))
        if startup_script_path.get('gzip', False):
            result['raw'] = b"\n".join([
                b"#!/bin/sh",
                b"tail -n+4 $0 | gunzip -c | sh",
                b"exit $?",
                gzip_string(result['original'])
            ])
        else:
            result['raw'] = result['original']
        max_size = getattr(self, 'max_startup_script_size', None)
        if max_size is not None and len(result['raw']) >= max_size:
            log.error("Startup script too big (%s > %s).", len(result['raw']), max_size)
            if not debug:
                sys.exit(1)
        if debug:
            return result
        else:
            return result['raw']


class BaseMaster(object):
    def __init__(self, ctrl, id, master_config):
        self.id = id
        self.ctrl = ctrl
        assert self.ctrl.__class__.__name__ == 'Controller'
        self.main_config = self.ctrl.config
        self.master_config = master_config
        self.known_hosts = self.ctrl.known_hosts
        self.instances = {}
        if getattr(self, 'section_info', None) is None:
            self.section_info = {
                None: self.instance_class,
                self.sectiongroupname: self.instance_class}
        for sectiongroupname, instance_class in self.section_info.items():
            for sid, config in self.main_config.get(sectiongroupname, {}).items():
                if self.id != config.get('master', self.id):
                    continue
                self.instances[sid] = instance_class(self, sid, config)
                self.instances[sid].sectiongroupname = sectiongroupname


class InstanceHooks(object):
    def __init__(self, instance):
        self.instance = instance

    def _iter_funcs(self, func_name):
        hooks = []
        for plugin in self.instance.master.ctrl.plugins.values():
            if 'get_hooks' not in plugin:
                continue
            hooks.extend(plugin['get_hooks']())
        if 'hooks' in self.instance.config:
            hooks.extend(self.instance.config['hooks'].hooks)
        for hook in hooks:
            func = getattr(hook, func_name, None)
            if func is not None:
                yield func

    def __getattr__(self, name):
        return lambda *args, **kwargs: [
            func(*args, **kwargs)
            for func in self._iter_funcs(name)]


class BaseInstance(object):
    def __init__(self, master, sid, config):
        self.id = self.validate_id(sid)
        self.master = master
        self.config = config
        self.hooks = InstanceHooks(self)
        get_massagers = getattr(self, 'get_massagers', lambda: [])
        for massager in get_massagers():
            self.config.add_massager(massager)

    _id_regexp = re.compile('^[a-zA-Z0-9-_]+$')

    def validate_id(self, sid):
        if self._id_regexp.match(sid) is None:
            log.error("Invalid instance name '%s'. An instance name may only contain letters, numbers, dashes and underscores." % sid)
            sys.exit(1)
        return sid

    @property
    def uid(self):
        master_instance = getattr(self.master, 'instance', None)
        if master_instance is self:
            return self.id
        else:
            return "%s-%s" % (self.master.id, self.id)

    @property
    def config_id(self):
        return "%s:%s" % (self.sectiongroupname, self.id)

    @lazy
    def paramiko(self):
        return import_paramiko()

    @property
    def conn(self):
        if getattr(self, '_conn', None) is not None:
            if self._conn.get_transport() is not None:
                return self._conn
        try:
            ssh_info = self.init_ssh_key()
        except self.paramiko.SSHException as e:
            log.error("Couldn't connect to %s." % (self.config_id))
            log.error(unicode(e))
            sys.exit(1)
        self._conn = ssh_info['client']
        return self._conn

    def get_config(self, overrides=None):
        return self.master.main_config.get_section_with_overrides(
            self.sectiongroupname, self.id, overrides)

    def ssh_args_from_info(self, ssh_info):
        additional_args = []
        for key in sorted(ssh_info):
            if key[0].isupper():
                additional_args.append('-o')
                additional_args.append('%s=%s' % (key, ssh_info[key]))
        if 'user' in ssh_info:
            additional_args.append('-l')
            additional_args.append(ssh_info['user'])
        if 'port' in ssh_info:
            additional_args.append('-p')
            additional_args.append(str(ssh_info['port']))
        if 'host' in ssh_info:
            additional_args.append(ssh_info['host'])
        if self.config.get('ssh-key-filename'):
            additional_args.append('-i')
            additional_args.append(self.config.get('ssh-key-filename'))
        return additional_args


class Hooks(object):
    def __init__(self):
        self.hooks = []

    def add(self, hook):
        self.hooks.append(hook)
