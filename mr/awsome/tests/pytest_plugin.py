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
        with open(self.path, 'w') as f:
            if hasattr(content, '__iter__'):
                content = '\n'.join(content)
            f.write(content)


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


@pytest.yield_fixture
def awsconf(tempdir):
    """ Returns a Configfile object which manages aws.conf.
    """
    yield tempdir['aws.conf']
