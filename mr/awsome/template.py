from StringIO import StringIO
import email
import gzip
import os


class Template(object):
    def __init__(self, path):
        self.path = path
        self.template = email.message_from_file(open(path))

    def __call__(self, **kwargs):
        options = {}
        for key, value in self.template.items():
            commands, value = value.rsplit(None, 1)
            for cmd in commands.split(','):
                if cmd == 'file':
                    path = value
                    if not os.path.isabs(path):
                        path = os.path.join(os.path.dirname(self.path), path)
                    value = open(path).read()
                elif cmd == 'base64':
                    value = value.encode("base64")
                elif cmd == 'format':
                    value = value.format(**kwargs)
                elif cmd == 'template':
                    path = value
                    if not os.path.isabs(path):
                        path = os.path.join(os.path.dirname(self.path), path)
                    value = Template(path)(**kwargs)
                elif cmd == 'gzip':
                    s = StringIO()
                    gz = gzip.GzipFile(mode='wb', fileobj=s)
                    gz.write(value)
                    gz.close()
                    value = s.getvalue()
                elif cmd == 'escape_eol':
                    value = value.replace('\n', '\\n')
                else:
                    raise ValueError("Unknown command '%s' for option '%s' in startup script '%s'." % (cmd, key, self.path))
            options[key] = value
        for key in kwargs:
            options[key] = kwargs[key]
        return self.template.get_payload().format(**options)
