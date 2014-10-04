from __future__ import print_function
from mock import patch
import pytest
import os
import shutil
import tempfile


class Directory:
    def __init__(self, directory):
        self.directory = directory

    def __getitem__(self, name):
        path = os.path.join(self.directory, name)
        assert not os.path.relpath(path, self.directory).startswith('..')
        return File(path)


class File:
    def __init__(self, path):
        self.directory = os.path.dirname(path)
        self.path = path

    def fill(self, content):
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)
        with open(self.path, 'w') as f:
            if isinstance(content, (list, tuple)):
                content = '\n'.join(content)
            f.write(content)

    def append(self, content):
        if isinstance(content, (list, tuple)):
            content = '\n'.join(content)
        self.fill("%s\n%s" % (self.content(), content))

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
        import mock
    return mock


@pytest.yield_fixture
def ployconf(tempdir):
    """ Returns a Configfile object which manages ploy.conf.
    """
    yield tempdir['etc/ploy.conf']


@pytest.yield_fixture
def os_execvp_mock():
    with patch("os.execvp") as os_execvp_mock:
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
