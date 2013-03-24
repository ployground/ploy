try:
    import cStringIO
    StringIO = cStringIO.StringIO  # shutup pyflakes
except ImportError:  # pragma: no cover
    from StringIO import StringIO
import gzip
import logging
import os
import sys


log = logging.getLogger('mr.awsome')


def gzip_string(value):
    s = StringIO()
    gz = gzip.GzipFile(mode='wb', fileobj=s)
    gz.write(value)
    gz.close()
    return s.getvalue()


def strip_hashcomments(value):
    lines = value.split('\n')
    result = []
    if lines[0].rstrip() in ('#!/bin/sh', '#!/bin/bash'):
        for index, line in enumerate(lines):
            if index > 0 and line.strip().startswith('#'):
                continue
            result.append(line)
    else:
        return "\n".join(lines)
    return "\n".join(result)


class StartupScriptMixin(object):
    def get_config(self, overrides=None):
        return self.master.main_config.get_section_with_overrides(
            self.sectiongroupname, self.id, overrides)

    def startup_script(self, overrides=None, debug=False):
        from mr.awsome import template  # avoid circular import

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
        if 'hooks' in config:
            config['hooks'].startup_script_options(config)
        result = dict(original=startup_script(**config))
        if startup_script_path.get('gzip', False):
            result['raw'] = "\n".join([
                "#!/bin/bash",
                "tail -n+4 $0 | gunzip -c | bash",
                "exit $?",
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


class FabricMixin(object):
    def do(self, task, *args, **kwargs):
        from mr.awsome import fabric_integration
        # this needs to be done before any other fabric module import
        fabric_integration.patch()
        orig_instances = fabric_integration.instances
        orig_log = fabric_integration.log
        fabric_integration.instances = self.master.instances
        fabric_integration.log = log

        from fabric.main import extract_tasks
        from fabric.state import env
        env.reject_unknown_hosts = True
        env.disable_known_hosts = True
        env.known_hosts = self.master.known_hosts

        fabfile = self.config['fabfile']
        with open(fabfile) as f:
            source = f.read()
        code = compile(source, fabfile, 'exec')
        g = {
            '__file__': fabfile}
        exec code in g, g
        new_style, classic, default = extract_tasks(g.items())
        callables = new_style if env.new_style_tasks else classic
        orig_host_string = env.host_string
        env.host_string = "{}@{}".format(
            self.config.get('user', 'root'),
            self.id)
        result = callables[task](*args, **kwargs)
        fabric_integration.instances = orig_instances
        fabric_integration.log = orig_log
        del env['reject_unknown_hosts']
        del env['disable_known_hosts']
        env.host_string = orig_host_string
        return result


class BaseMaster(object):
    def __init__(self, main_config, id, master_config):
        self.id = id
        self.main_config = main_config
        self.master_config = master_config
        self.known_hosts = os.path.join(self.main_config.path, 'known_hosts')
        self.instances = {}
        if getattr(self, 'section_info', None) is None:
            self.section_info = {self.sectiongroupname: self.instance_class}
        for sectiongroupname, instance_class in self.section_info.items():
            for sid, config in self.main_config.get(sectiongroupname, {}).iteritems():
                self.instances[sid] = instance_class(self, sid, config)
                self.instances[sid].sectiongroupname = sectiongroupname


class Hooks(object):
    def __init__(self):
        self.hooks = []

    def add(self, hook):
        self.hooks.append(hook)

    def _iter_funcs(self, func_name):
        for hook in self.hooks:
            func = getattr(hook, func_name, None)
            if func is not None:
                yield func

    def after_terminate(self, server):
        for func in self._iter_funcs('after_terminate'):
            func(server)

    def before_start(self, server):
        for func in self._iter_funcs('before_start'):
            func(server)

    def startup_script_options(self, options):
        for func in self._iter_funcs('startup_script_options'):
            func(options)
