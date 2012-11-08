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
        result = startup_script(**config)
        if startup_script_path.get('gzip', False):
            result = "\n".join([
                "#!/bin/bash",
                "tail -n+4 $0 | gunzip -c | bash",
                "exit $?",
                gzip_string(result)
            ])
        max_size = getattr(self, 'max_startup_script_size', None)
        if max_size is not None and len(result) >= max_size:
            log.error("Startup script too big (%s > %s).", len(result), max_size)
            if not debug:
                sys.exit(1)
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

    def startup_script_options(self, options):
        for func in self._iter_funcs('startup_script_options'):
            func(options)
