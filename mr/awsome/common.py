try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import gzip


def gzip_string(value):
    s = StringIO()
    gz = gzip.GzipFile(mode='wb', fileobj=s)
    gz.write(value)
    gz.close()
    return s.getvalue()
