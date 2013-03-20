from mock import patch
from mr.awsome import AWS
from unittest2 import TestCase
import os
import tempfile
import shutil


class PlainTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)
        try:  # pragma: no cover - we support both
            self._ssh_client_mock = patch("paramiko.SSHClient")
        except ImportError:  # pragma: no cover - we support both
            self._ssh_client_mock = patch("ssh.SSHClient")
        self.ssh_client_mock = self._ssh_client_mock.start()
        try:  # pragma: no cover - we support both
            self._ssh_config_mock = patch("paramiko.SSHConfig")
        except ImportError:  # pragma: no cover - we support both
            self._ssh_config_mock = patch("ssh.SSHConfig")
        self.ssh_config_mock = self._ssh_config_mock.start()
        self.ssh_config_mock().lookup.return_value = {}
        self._subprocess_call_mock = patch("subprocess.call")
        self.subprocess_call_mock = self._subprocess_call_mock.start()

    def tearDown(self):
        self.subprocess_call_mock = self._subprocess_call_mock.stop()
        del self.subprocess_call_mock
        self.ssh_config_mock = self._ssh_config_mock.stop()
        del self.ssh_config_mock
        self.ssh_client_mock = self._ssh_client_mock.stop()
        del self.ssh_client_mock
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testInstanceHasNoStatus(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn("invalid choice: 'foo'", output)

    def testInstanceCantBeStarted(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'start', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn("invalid choice: 'foo'", output)

    def testInstanceCantBeStopped(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn("invalid choice: 'foo'", output)

    def testInstanceCantBeTerminated(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn("invalid choice: 'foo'", output)

    def testSSHWithNoHost(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'ssh', 'foo'])
        self.assertEquals(
            LogMock.error.call_args_list, [
                (("Couldn't validate fingerprint for ssh connection.",), {}),
                (("No host set in config.",), {}),
                (('Is the server finished starting up?',), {})])

    def testSSHWithNoFingerprint(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]',
            'host = localhost']))
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'ssh', 'foo'])
        self.assertEquals(
            LogMock.error.call_args_list, [
                (("Couldn't validate fingerprint for ssh connection.",), {}),
                (("No fingerprint set in config.",), {}),
                (('Is the server finished starting up?',), {})])

    def testSSH(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]',
            'host = localhost',
            'fingerprint = foo']))
        try:
            self.aws(['./bin/aws', 'ssh', 'foo'])
        except SystemExit: # pragma: no cover - only if something is wrong
            self.fail("SystemExit raised")
        known_hosts = os.path.join(self.directory, 'known_hosts')
        self.subprocess_call_mock.assert_called_with(
            ['ssh', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])
