try:
    from cStringIO import StringIO
except ImportError: # pragma: no cover
    from StringIO import StringIO
import gzip
import logging
import sys


log = logging.getLogger('mr.awsome')


def gzip_string(value):
    s = StringIO()
    gz = gzip.GzipFile(mode='wb', fileobj=s)
    gz.write(value)
    gz.close()
    return s.getvalue()


class StartupScriptMixin(object):
    def get_config(self, overrides=None):
        return self.master.main_config.get_section_with_overrides(
            self.sectiongroupname, self.id, overrides)

    def startup_script(self, overrides=None, debug=False):
        from mr.awsome import template # avoid circular import

        config = self.get_config(overrides)
        startup_script_path = config.get('startup_script', None)
        if startup_script_path is None:
            return ''
        startup_script = template.Template(
            startup_script_path['path'],
            pre_filter=template.strip_hashcomments,
        )
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
            log.error("Startup script too big.")
            if not debug:
                sys.exit(1)
        return result
