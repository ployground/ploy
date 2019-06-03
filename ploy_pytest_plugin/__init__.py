from __future__ import print_function, unicode_literals
from io import StringIO
import pytest
import os
import shutil
import tempfile
import textwrap


class Directory:
    def __init__(self, directory):
        self.directory = directory

    def mkdir(self, name):
        path = os.path.join(self.directory, name)
        os.mkdir(path)
        return Directory(path)

    def __getitem__(self, name):
        path = os.path.join(self.directory, name)
        assert not os.path.relpath(path, self.directory).startswith('..')
        return File(path)


class File:
    def __init__(self, path):
        self.directory = os.path.dirname(path)
        self.path = path

    def makedirs(self):
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)

    def fill(self, content, allow_conf=False):
        if self.path.endswith('.conf') and not allow_conf:
            raise ValueError
        self.makedirs()
        with open(self.path, 'w') as f:
            f.write(make_file_content(content))

    def content(self):
        with open(self.path) as f:
            return f.read()


@pytest.yield_fixture
def tempdir():
    """ Returns an object for easy use of a temporary directory which is
        cleaned up afterwards.

        Use tempdir[filepath] to access files.
        Use .fill(lines) on the returned object to write content to the file.
    """
    directory = tempfile.mkdtemp()
    yield Directory(directory)
    shutil.rmtree(directory)


@pytest.fixture(scope="session")
def mock():
    try:
        from unittest import mock
    except ImportError:  # pragma: nocover
        import mock  # for Python 2.7
    return mock


def make_file_content(content):
    if isinstance(content, StringIO):
        return content.getvalue()
    if isinstance(content, (list, tuple)):
        content = u"\n".join(content)
    return textwrap.dedent(content)


@pytest.fixture(name="make_file_content")
def _make_file_content():
    return make_file_content


@pytest.fixture
def make_file_io(make_file_content):
    from io import StringIO

    def make_file_io(content):
        return StringIO(make_file_content(content))

    return make_file_io


class Writer:
    def __init__(self):
        self.full_output = dict()
        self.output = dict()

    def __call__(self, dirname, basename, value):
        if basename is not None:
            basename = basename.replace('.conf', '.yml')
        self.full_output.setdefault((dirname, basename), []).append(value)
        self.output[basename] = value.decode('ascii')


@pytest.fixture
def yaml_dumper():
    return Writer()


@pytest.fixture(params=[".conf", ".yml"])
def confext(request):
    return request.param


@pytest.fixture
def confmaker(request, tempdir, confext):
    from io import StringIO
    from ploy.config import Config, read_config

    class Confmaker:
        def __init__(self, conf):
            conf = conf.replace('.conf', confext)
            self.conf = tempdir[conf]
            self.directory = self.conf.directory
            self.path = self.conf.path
            self._content = ""

        def makedirs(self):
            if not os.path.exists(self.directory):
                os.makedirs(self.directory)

        def fill(self, content):
            self._content = make_file_content(content)
            self._write()

        def append(self, content):
            self._content += "\n" + make_file_content(content)
            self._write()

        def content(self):
            return self._content

        def _write(self):
            self.makedirs()
            content = self._content
            if confext == '.yml' and content:
                config = Config(StringIO(content))
                _config = read_config(config.config, config.path, shallow=True)
                config._parse(_config)
                writer = Writer()
                config._dump_yaml(writer)
                (content,) = writer.full_output[(None, None)]
            with open(self.path, 'wb') as f:
                if isinstance(content, str):
                    content = content.encode('ascii')
                f.write(content)

    return Confmaker


@pytest.yield_fixture
def ployconf(confmaker):
    return confmaker('etc/ploy.conf')


@pytest.yield_fixture
def os_execvp_mock(mock):
    with mock.patch("os.execvp") as os_execvp_mock:
        yield os_execvp_mock


@pytest.fixture
def yesno_mock(mock, monkeypatch):
    yesno = mock.Mock()

    def _yesno(question):
        try:
            expected = yesno.expected.pop(0)
        except IndexError:  # pragma: nocover
            expected = '', False
        cmd, result = expected
        assert question == cmd
        print(question)
        return result

    yesno.side_effect = _yesno
    yesno.expected = []
    monkeypatch.setattr('ploy.common.yesno', yesno)
    return yesno
