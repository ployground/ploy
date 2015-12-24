from __future__ import print_function
from lazy import lazy
from io import BytesIO
try:
    from shlex import quote as shquote
except ImportError:  # pragma: nocover
    from pipes import quote as shquote  # for Python 2.7
import gzip
import logging
import os
import paramiko
import re
import subprocess
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


def shjoin(args):
    return ' '.join(shquote(x) for x in args)


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
            shebang = b"#!/bin/sh"
            if result['original'].startswith('#!'):
                shebang = result['original'].splitlines()[0].encode('ascii')
            result['raw'] = b"\n".join([
                b"#!/bin/sh",
                b"tail -n+4 $0 | gunzip -c | " + shebang[2:],
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
        from ploy.config import ConfigSection  # avoid circular import
        self.id = id
        self.ctrl = ctrl
        assert self.ctrl.__class__.__name__ == 'Controller'
        self.main_config = self.ctrl.config
        if not isinstance(master_config, ConfigSection):
            master_config = ConfigSection(master_config)
        self.master_config = master_config
        self.known_hosts = self.ctrl.known_hosts
        self.instances = {}
        if getattr(self, 'section_info', None) is None:
            self.section_info = {
                None: self.instance_class,
                self.sectiongroupname: self.instance_class}
        for sectiongroupname, instance_class in self.section_info.items():
            for sid, config in self.main_config.get(sectiongroupname, {}).items():
                masters = config.get('master', self.id).split()
                if self.id not in masters:
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
    paramiko = paramiko

    def __init__(self, master, sid, config):
        self.id = self.validate_id(sid)
        self.master = master
        self.config = config
        self.hooks = InstanceHooks(self)

    def __repr__(self):
        return "<%s.%s uid=%r>" % (
            self.__class__.__module__, self.__class__.__name__,
            self.uid)

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
    def _sshconfig(self):
        sshconfig = self.paramiko.SSHConfig()
        path = os.path.expanduser('~/.ssh/config')
        if not os.path.exists(path):
            return sshconfig
        with open(path) as f:
            sshconfig.parse(f)
        return sshconfig

    @lazy
    def sshconfig(self):
        return self._sshconfig.lookup(self.get_host())

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
        ssh_options = dict(
            (k.lower(), v)
            for k, v in ssh_info.items()
            if k[0].isupper())
        config_agent = self.sshconfig.get('forwardagent', 'no').lower() == 'yes'
        forward_agent = ssh_options.get('forwardagent', 'no').lower() == 'yes'
        self._conn._ploy_forward_agent = forward_agent or config_agent
        return self._conn

    def close_conn(self):
        if getattr(self, '_conn', None) is not None:
            if self._conn.get_transport() is not None:
                self._conn.close()

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

    def proxycommand_with_instance(self, instance):
        instance_ssh_info = instance.init_ssh_key()
        instance_ssh_args = instance.ssh_args_from_info(instance_ssh_info)
        ssh_args = ['nohup', 'ssh']
        ssh_args.extend(instance_ssh_args)
        ssh_args.extend(['-W', '%s:%s' % (self.get_host(), self.get_port())])
        return shjoin(ssh_args)


class Executor:
    def __init__(self, instance=None, prefix_args=(), splitlines=False):
        self.instance = instance
        self.prefix_args = tuple(prefix_args)
        self.splitlines = splitlines

    def __call__(self, *cmd_args, **kw):
        args = self.prefix_args + cmd_args
        rc = kw.pop('rc', None)
        out = kw.pop('out', None)
        err = kw.pop('err', None)
        stdin = kw.pop('stdin', None)
        if self.instance is None:
            log.debug('Executing locally:\n%s', args)
            popen_kw = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if stdin is not None:
                popen_kw['stdin'] = subprocess.PIPE
            proc = subprocess.Popen(args, **popen_kw)
            _out, _err = proc.communicate(input=stdin)
            _rc = proc.returncode
        else:
            cmd = shjoin(args)
            log.debug('Executing on instance %s:\n%s', self.instance.uid, cmd)
            chan = self.instance.conn.get_transport().open_session()
            if stdin is not None:
                rin = chan.makefile('wb', -1)
            rout = chan.makefile('rb', -1)
            rerr = chan.makefile_stderr('rb', -1)
            forward = None
            if self.instance.conn._ploy_forward_agent:
                forward = self.instance.paramiko.agent.AgentRequestHandler(chan)
            chan.exec_command(cmd)
            if stdin is not None:
                rin.write(stdin)
                rin.flush()
                chan.shutdown_write()
            _out = rout.read()
            _err = rerr.read()
            _rc = chan.recv_exit_status()
            chan.close()
            if forward is not None:
                forward.close()
        result = []
        if rc is None:
            result.append(_rc)
        else:
            try:
                if not any(x == _rc for x in rc):
                    raise subprocess.CalledProcessError(_rc, ' '.join(args), _err)
            except TypeError:
                pass
            if rc != _rc:
                raise subprocess.CalledProcessError(_rc, ' '.join(args), _err)
        if out is None:
            if self.splitlines:
                _out = _out.splitlines()
            result.append(_out)
        else:
            if out != _out:
                if _rc == 0:
                    log.error(_out)
                raise subprocess.CalledProcessError(_rc, ' '.join(args), _err)
        if err is None:
            if self.splitlines:
                _err = _err.splitlines()
            result.append(_err)
        else:
            if err != _err:
                if _rc == 0:
                    log.error(_err)
                raise subprocess.CalledProcessError(_rc, ' '.join(args), _err)
        if len(result) == 0:
            return
        elif len(result) == 1:
            return result[0]
        return tuple(result)


class Hooks(object):
    def __init__(self):
        self.hooks = []

    def add(self, hook):
        self.hooks.append(hook)
