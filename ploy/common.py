from __future__ import print_function, unicode_literals
from contextlib import closing
from lazy import lazy
from io import BytesIO
try:
    from shlex import quote as shquote
except ImportError:  # pragma: nocover
    from pipes import quote as shquote  # for Python 2.7
import binascii
import gzip
import hashlib
import logging
import os
import paramiko
import re
import select
import socket
import subprocess
import sys


log = logging.getLogger('ploy')


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
        if default == 'all':
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


def sorted_choices(choices):
    return sorted(str(x) for x in choices)


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
    def __init__(self, ctrl, mid, master_config):
        from ploy.config import ConfigSection  # avoid circular import
        self.id = mid
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
                self.main_config.setdefault(instance_class.sectiongroupname, config.__class__())
                self.main_config[instance_class.sectiongroupname][sid] = config.copy()
                self.instances[sid] = instance_class(self, sid, self.main_config[instance_class.sectiongroupname][sid])
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
        sshconfig = paramiko.SSHConfig()
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
        except paramiko.SSHException as e:
            log.error("Couldn't connect to %s." % (self.config_id))
            log.error(str(e))
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


class BaseExecutor:
    def __init__(self, instance=None, prefix_args=(), splitlines=False):
        self.instance = instance
        self.prefix_args = tuple(prefix_args)
        self.splitlines = splitlines

    def _run(self):
        raise NotImplementedError

    def __call__(self, *cmd_args, **kw):
        args = self.prefix_args + cmd_args
        rc = kw.pop('rc', None)
        out = kw.pop('out', None)
        err = kw.pop('err', None)
        stdin = kw.pop('stdin', None)
        (_rc, _out, _err) = self._run(args, stdin)
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
                result.append(_out.decode('utf-8').splitlines())
            else:
                result.append(_out)
        else:
            if out != _out:
                if _rc == 0:
                    log.error(_out.decode('utf-8'))
                    log.error(_err.decode('utf-8'))
                raise subprocess.CalledProcessError(_rc, ' '.join(args), _err)
        if err is None:
            if self.splitlines:
                result.append(_err.decode('utf-8').splitlines())
            else:
                result.append(_err)
        else:
            if err != _err:
                if _rc == 0:
                    log.error(_out.decode('utf-8'))
                    log.error(_err.decode('utf-8'))
                raise subprocess.CalledProcessError(_rc, ' '.join(args), _err)
        if len(result) == 0:
            return
        elif len(result) == 1:
            return result[0]
        return tuple(result)


class LocalExecutor(BaseExecutor):
    def __init__(self, **kw):
        BaseExecutor.__init__(self, **kw)

    def _run(self, args, stdin):
        log.debug('Executing locally:\n%s', args)
        popen_kw = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if stdin is not None:
            popen_kw['stdin'] = subprocess.PIPE
        proc = subprocess.Popen(args, **popen_kw)
        (out, err) = proc.communicate(input=stdin)
        rc = proc.returncode
        return (rc, out, err)


class InstanceExecutor(BaseExecutor):
    def __init__(self, instance, **kw):
        BaseExecutor.__init__(self, **kw)
        self.instance = instance

    def _run(self, args, stdin):
        cmd = shjoin(args)
        log.debug('Executing on instance %s:\n%s', self.instance.uid, cmd)
        chan = self.instance.conn.get_transport().open_session()
        if stdin is not None:
            rin = chan.makefile('wb', -1)
        rout = chan.makefile('rb', -1)
        rerr = chan.makefile_stderr('rb', -1)
        forward = None
        if self.instance.conn._ploy_forward_agent:
            forward = paramiko.agent.AgentRequestHandler(chan)
        chan.exec_command(cmd)
        if stdin is not None:
            rin.write(stdin)
            rin.flush()
            rin.close()
            del rin
            chan.shutdown_write()
        out_chunks = []
        err_chunks = []
        assert chan == rout.channel
        assert chan == rerr.channel
        while 1:
            # stop if channel was closed prematurely,
            # and there is no data in the buffers
            should_break = True
            (readq, _, _) = select.select([chan], [], [])
            assert len(readq) == 1 and readq[0] == chan
            if chan.recv_ready():
                out_chunks.append(chan.recv(len(chan.in_buffer)))
                should_break = False
            if chan.recv_stderr_ready():
                err_chunks.append(chan.recv_stderr(len(chan.in_stderr_buffer)))
                should_break = False
            should_break = (
                should_break
                and chan.exit_status_ready()
                and not chan.recv_ready()
                and not chan.recv_stderr_ready())
            if should_break:
                break
        rc = chan.recv_exit_status()
        chan.shutdown_read()
        chan.close()
        rout.close()
        rerr.close()
        if forward is not None:
            forward.close()
        return (rc, b''.join(out_chunks), b''.join(err_chunks))


def Executor(instance=None, **kw):
    if instance is None:
        return LocalExecutor(**kw)
    return InstanceExecutor(**kw)


class Hooks(object):
    def __init__(self):
        self.hooks = []

    def add(self, hook):
        self.hooks.append(hook)


def split_option(option):
    return list(filter(None, (x.strip() for x in re.split(',|\n', option.strip()))))


def parse_fingerprint(data):
    if hasattr(data, 'split'):
        parts = data.split(':')
        if len(parts) == 17:
            return (
                parts[0].lower(),
                binascii.unhexlify("".join(parts[1:])))
        elif len(parts) == 16:
            return (
                'md5',
                binascii.unhexlify("".join(parts)))
        elif len(parts) == 2:
            return (
                parts[0].lower(),
                binascii.a2b_base64(parts[1] + "==="))
        raise ValueError("Unknown fingerprint format: %s" % data)
    raise ValueError("Unknown fingerprint type: %r" % data)


def format_fingerprint(fingerprint):
    if fingerprint[0] == 'md5':
        if isinstance(fingerprint[1][0], int):
            return ':'.join("%02x" % x for x in fingerprint[1])
        return ':'.join("%02x" % ord(x) for x in fingerprint[1])
    return "%s:%s" % (
        fingerprint[0].upper(),
        binascii.b2a_base64(fingerprint[1]).decode('ascii').rstrip().rstrip('='))


class SSHKeyFingerprint(object):
    store = True

    def __init__(self, fingerprint, keylen=None, keytype=None):
        self.fingerprint = fingerprint
        if not isinstance(self.fingerprint, tuple):
            self.fingerprint = parse_fingerprint(fingerprint)
        if keylen is not None and not isinstance(keylen, int):
            keylen = int(keylen)
        self.keylen = keylen
        if keytype is not None:
            keytype = keytype.lower()
        self.keytype = keytype

    def match(self, other):
        return (
            self.fingerprint == other.fingerprint
            and (
                self.keylen is None
                or other.keylen is None
                or self.keylen == other.keylen)
            and (
                self.keytype is None
                or other.keytype is None
                or self.keytype == other.keytype))

    def __str__(self):
        return format_fingerprint(self.fingerprint)

    def __repr__(self):
        result = "%s('%s'" % (
            self.__class__.__name__,
            format_fingerprint(self.fingerprint))
        if self.keylen is not None:
            result += ", keylen=%r" % self.keylen
        if self.keytype is not None:
            result += ", keytype='%s'" % self.keytype
        return "%s)" % result


class SSHKeyFingerprintAsk(object):
    store = False

    def __init__(self):
        self.ask = True

    def match(self, other):
        if not self.ask:
            return True
        msg = (
            "WARNING! Automatic fingerprint checking disabled.\n"
            "Got fingerprint %s.\n"
            "Continue?" % other)
        if yesno(msg):
            self.ask = False
            return True
        sys.exit(1)

    def __str__(self):
        return "ask"


class SSHKeyFingerprintIgnore(object):
    store = True

    def match(self, other):
        log.warn(
            "Fingerprint verification disabled!\n"
            "Got fingerprint %s." % other)
        return True

    def __str__(self):
        return "ignore"


class SSHKeyFingerprintInstance(object):
    store = True

    def __init__(self, instance):
        self.instance = instance
        self.fingerprints = None

    def match(self, other):
        if self.fingerprints is None:
            func = getattr(self.instance, 'get_fingerprints', None)
            if func is not None:
                self.fingerprints = [
                    SSHKeyFingerprint(**x) for x in func()]
            func = getattr(self.instance, 'get_fingerprint', None)
            if func is not None and not self.fingerprints:
                try:
                    self.fingerprints = [SSHKeyFingerprint(func())]
                except paramiko.SSHException as e:
                    log.error(str(e))
                    pass
        if not self.fingerprints:
            return False
        for fingerprint in self.fingerprints:
            if fingerprint.match(other):
                return True

    def __str__(self):
        return "auto"


class SSHKeyInfo(object):
    def __init__(self, key):
        self.keytype = None
        if key.get_name().startswith('ssh-'):
            self.keytype = key.get_name()[4:]
        self.keylen = key.get_bits()
        self.data = key.asbytes()
        self.fingerprints = {}

    def __contains__(self, other):
        hashtypes = ['md5', 'sha256']
        fingerprint = getattr(other, 'fingerprint', None)
        if fingerprint is not None:
            hashtypes = [fingerprint[0]]
        for hashtype in hashtypes:
            if hashtype not in self.fingerprints:
                hash_func = getattr(hashlib, hashtype, None)
                if hash_func is None:
                    continue
                self.fingerprints[hashtype] = SSHKeyFingerprint(
                    (hashtype, hash_func(self.data).digest()),
                    keylen=self.keylen, keytype=self.keytype)
            fingerprint = self.fingerprints[hashtype]
            if other.match(fingerprint):
                return True
        return False

    def get_fingerprint_objects(self):
        return [x[1] for x in sorted(self.fingerprints.items())]

    def get_fingerprints(self):
        return [str(x) for x in self.get_fingerprint_objects()]

    def __repr__(self):
        return "%s(%r, %r, %r)" % (
            self.__class__.__name__, self.keytype, self.keylen, self.fingerprints)


re_hex_byte = '[0-9a-fA-F]{2}'
re_fingerprint = "(?:%s:){15}%s" % (re_hex_byte, re_hex_byte)
re_fingerprint_md5 = "(?:[^:]+:%s)" % re_fingerprint
re_fingerprint_other = "(?:[^:]+:[0-9a-zA-Z+/=]+)"
re_fingerprint_info = r"^.*?(\d+)\s+(%s|%s|%s)(.*)$" % (re_fingerprint, re_fingerprint_md5, re_fingerprint_other)
fingerprint_regexp = re.compile(re_fingerprint_info, re.MULTILINE)
fingerprint_type_regexp = re.compile(r"\((.*?)\)")


def parse_ssh_keygen(text):
    fingerprints = []
    for match in fingerprint_regexp.findall(text):
        info = dict(keylen=int(match[0]), fingerprint=match[1])
        key_info = match[2].lower()
        if '(rsa1)' in key_info or 'ssh_host_key' in key_info:
            info['keytype'] = 'rsa1'
        elif '(rsa)' in key_info or 'ssh_host_rsa_key' in key_info:
            info['keytype'] = 'rsa'
        elif '(dsa)' in key_info or 'ssh_host_dsa_key' in key_info:
            info['keytype'] = 'dsa'
        elif '(ecdsa)' in key_info or 'ssh_host_ecdsa_key' in key_info:
            info['keytype'] = 'ecdsa'
        else:
            match = fingerprint_type_regexp.search(key_info)
            if match:
                info['keytype'] = match.group(1)
        fingerprints.append(SSHKeyFingerprint(**info))
    return fingerprints


def wait_for_ssh(host, port, timeout=5):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        if s.connect_ex((host, port)) == 0:
            if s.recv(128).startswith(b'SSH-2'):
                return


def wait_for_ssh_on_sock(socket_factory, timeout=5):
    sock = socket_factory()
    if sock is None:
        return
    with closing(sock) as s:
        s.settimeout(timeout)
        if s.recv(128).startswith(b'SSH-2'):
            return
