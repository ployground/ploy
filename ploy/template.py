from ploy.common import gzip_string
import base64
import email
import os


class Template(object):
    def __init__(self, path, pre_filter=None, post_filter=None):
        self.path = path
        self.template = email.message_from_file(open(path))
        self.pre_filter = pre_filter
        self.post_filter = post_filter

    def __call__(self, **kwargs):
        options = {}
        body = self.template.get_payload()
        if callable(self.pre_filter):
            body = self.pre_filter(body)
        for key, value in self.template.items():
            commands, value = value.rsplit(None, 1)
            for cmd in commands.split(','):
                if cmd == 'file':
                    path = value
                    if not os.path.isabs(path):
                        path = os.path.join(os.path.dirname(self.path), path)
                    value = open(path).read()
                elif cmd == 'base64':
                    if not isinstance(value, bytes):
                        value = value.encode('ascii')
                    value = base64.encodestring(value).decode('ascii')
                elif cmd == 'format':
                    value = value.format(**kwargs)
                elif cmd == 'template':
                    path = value
                    if not os.path.isabs(path):
                        path = os.path.join(os.path.dirname(self.path), path)
                    value = Template(path)(**kwargs)
                elif cmd == 'gzip':
                    value = gzip_string(value)
                elif cmd == 'escape_eol':
                    value = value.replace('\n', '\\n')
                else:
                    raise ValueError("Unknown command '%s' for option '%s' in startup script '%s'." % (cmd, key, self.path))
            options[key] = value
        for key in kwargs:
            options[key] = kwargs[key]
        result = body.format(**options)
        if callable(self.post_filter):
            result = self.post_filter(result)
        return result
