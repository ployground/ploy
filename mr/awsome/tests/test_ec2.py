from mock import patch
from mr.awsome import AWS
from unittest2 import skip, TestCase
import os
import tempfile
import shutil


class MockConsoleOutput(object):
    def __init__(self, output):
        self.output = output


class MockInstance(object):
    def __init__(self):
        self.state = 'running'
        self._public_ip = "257.1.2.3"
        self._private_ip = "10.0.0.1"
        self._console_output = ''

    @property
    def dns_name(self):
        return "ec2-%s.example.com" % self._public_ip.replace('.', '-')

    @property
    def private_dns_name(self):
        return "ec2-%s.example.com" % self._private_ip.replace('.', '-')

    @property
    def public_dns_name(self):
        return "ec2-%s.example.com" % self._public_ip.replace('.', '-')

    def get_console_output(self):
        return MockConsoleOutput(self._console_output)


class MockReservation(object):
    def __init__(self):
        self.instances = []


class MockSecuritygroup(object):
    def __init__(self, name):
        self.name = name


class MockConnection(object):
    def __init__(self):
        self.reservations = []

    def get_all_instances(self):
        return self.reservations[:]


class MockRegion(object):
    def __init__(self):
        self.connection = MockConnection()

    def connect(self, aws_access_key_id=None, aws_secret_access_key=None):
        return self.connection


class EC2SetupTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)
        self._boto_ec2_regions_mock = patch("boto.ec2.regions")
        self.boto_ec2_regions_mock = self._boto_ec2_regions_mock.start()

    def tearDown(self):
        self.boto_ec2_regions_mock = self.boto_ec2_regions_mock.stop()
        del self.boto_ec2_regions_mock
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testNoRegionSet(self):
        self._write_config('\n'.join([
            '[ec2-master:default]',
            '[ec2-instance:foo]']))
        with patch('mr.awsome.ec2.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status', 'foo'])
        LogMock.error.assert_called_with('No region set in ec2-instance:foo or ec2-master:default config')

    def testNoAWSCredentialsSet(self):
        self._write_config('\n'.join([
            '[ec2-master:default]',
            'region = eu-west-1',
            '[ec2-instance:foo]']))
        with patch('mr.awsome.ec2.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status', 'foo'])
        LogMock.error.assert_called_with("You need to either set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or add the path to files containing them to the config. You can find the values at http://aws.amazon.com under 'Your Account'-'Security Credentials'.")

    def testAWSCredentialKeyFileMissing(self):
        key = os.path.join(self.directory, 'key')
        secret = os.path.join(self.directory, 'secret')
        self._write_config('\n'.join([
            '[ec2-master:default]',
            'region = eu-west-1',
            'access-key-id = %s' % key,
            'secret-access-key = %s' % secret,
            '[ec2-instance:foo]']))
        with patch('mr.awsome.ec2.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status', 'foo'])
        LogMock.error.assert_called_with("The access-key-id file at '%s' doesn't exist.", key)

    def testAWSCredentialSecretFileMissing(self):
        key = os.path.join(self.directory, 'key')
        with open(key, 'w') as f:
            f.write('ham')
        secret = os.path.join(self.directory, 'secret')
        self._write_config('\n'.join([
            '[ec2-master:default]',
            'region = eu-west-1',
            'access-key-id = %s' % key,
            'secret-access-key = %s' % secret,
            '[ec2-instance:foo]']))
        with patch('mr.awsome.ec2.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status', 'foo'])
        LogMock.error.assert_called_with("The secret-access-key file at '%s' doesn't exist.", secret)

    def testUnknownRegion(self):
        key = os.path.join(self.directory, 'key')
        with open(key, 'w') as f:
            f.write('ham')
        secret = os.path.join(self.directory, 'secret')
        with open(secret, 'w') as f:
            f.write('egg')
        self._write_config('\n'.join([
            '[ec2-master:default]',
            'region = eu-west-1',
            'access-key-id = %s' % key,
            'secret-access-key = %s' % secret,
            '[ec2-instance:foo]']))
        self.boto_ec2_regions_mock.return_value = []
        with patch('mr.awsome.ec2.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status', 'foo'])
        LogMock.error.assert_called_with("Region '%s' not found in regions returned by EC2.", 'eu-west-1')

    def testAWSKeysInEnvironment(self):
        self._write_config('\n'.join([
            '[ec2-master:default]',
            'region = eu-west-1',
            '[ec2-instance:foo]']))
        region = MockRegion()
        region.name = 'eu-west-1'
        self.boto_ec2_regions_mock.return_value = [region]
        with patch('mr.awsome.ec2.log') as LogMock:
            if 'AWS_ACCESS_KEY_ID' in os.environ: # pragma: no cover
                del os.environ['AWS_ACCESS_KEY_ID']
            os.environ['AWS_ACCESS_KEY_ID'] = 'ham'
            if 'AWS_SECRET_ACCESS_KEY' in os.environ: # pragma: no cover
                del os.environ['AWS_SECRET_ACCESS_KEY']
            os.environ['AWS_SECRET_ACCESS_KEY'] = 'egg'
            try:
                self.aws(['./bin/aws', 'status', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
            finally:
                if 'AWS_ACCESS_KEY_ID' in os.environ:
                    del os.environ['AWS_ACCESS_KEY_ID']
                if 'AWS_SECRET_ACCESS_KEY' in os.environ:
                    del os.environ['AWS_SECRET_ACCESS_KEY']
        self.boto_ec2_regions_mock.assert_called_with(
            aws_access_key_id=None, aws_secret_access_key=None)
        LogMock.info.assert_called_with("Instance '%s' unavailable.", 'foo')


class EC2Tests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)
        self._boto_ec2_regions_mock = patch("boto.ec2.regions")
        self.boto_ec2_regions_mock = self._boto_ec2_regions_mock.start()
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
        self.key = os.path.join(self.directory, 'key')
        with open(self.key, 'w') as f:
            f.write('ham')
        self.secret = os.path.join(self.directory, 'secret')
        with open(self.secret, 'w') as f:
            f.write('egg')

    def tearDown(self):
        self.subprocess_call_mock = self._subprocess_call_mock.stop()
        del self.subprocess_call_mock
        self.ssh_config_mock = self._ssh_config_mock.stop()
        del self.ssh_config_mock
        self.ssh_client_mock = self._ssh_client_mock.stop()
        del self.ssh_client_mock
        self.boto_ec2_regions_mock = self.boto_ec2_regions_mock.stop()
        del self.boto_ec2_regions_mock
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write('\n'.join([
                '[ec2-master:default]',
                'region = eu-west-1',
                'access-key-id = %s' % self.key,
                'secret-access-key = %s' % self.secret]))
            f.write('\n')
            f.write(content)

    def testStatusOnUnavailableInstance(self):
        self._write_config('\n'.join([
            '[ec2-instance:foo]']))
        region = MockRegion()
        region.name = 'eu-west-1'
        self.boto_ec2_regions_mock.return_value = [region]
        with patch('mr.awsome.ec2.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'status', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.boto_ec2_regions_mock.assert_called_with(
            aws_access_key_id='ham', aws_secret_access_key='egg')
        LogMock.info.assert_called_with("Instance '%s' unavailable.", 'foo')

    @skip("TODO")
    def testNoSecurityGroupDefined(self):
        return NotImplemented

    def testStatus(self):
        self._write_config('\n'.join([
            '[ec2-instance:foo]',
            'securitygroups = foo']))
        region = MockRegion()
        region.name = 'eu-west-1'
        reservation = MockReservation()
        reservation.groups = [MockSecuritygroup('foo')]
        region.connection.reservations.append(reservation)
        instance = MockInstance()
        instance.id = 'i-12345678'
        reservation.instances.append(instance)
        self.boto_ec2_regions_mock.return_value = [region]
        with patch('mr.awsome.ec2.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'status', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.boto_ec2_regions_mock.assert_called_with(
            aws_access_key_id='ham', aws_secret_access_key='egg')
        self.assertEquals(
            LogMock.info.call_args_list, [
                (("Instance '%s' (%s) available.", 'foo', instance.id), {}),
                (("Instance running.",), {}),
                (("Instances DNS name %s", 'ec2-257-1-2-3.example.com'), {}),
                (("Instances private DNS name %s", 'ec2-10-0-0-1.example.com'), {}),
                (("Instances public DNS name %s", 'ec2-257-1-2-3.example.com'), {})])

    # def testInstanceHasNoStatus(self):
    #     key = os.path.join(self.directory, 'key')
    #     with open(key, 'w') as f:
    #         f.write('ham')
    #     secret = os.path.join(self.directory, 'secret')
    #     with open(secret, 'w') as f:
    #         f.write('egg')
    #     self._write_config('\n'.join([
    #         '[ec2-master:default]',
    #         'region = eu-west-1',
    #         'access-key-id = %s' % key,
    #         'secret-access-key = %s' % secret,
    #         '[ec2-instance:foo]']))
    #     region = MockRegion()
    #     region.name = 'eu-west-1'
    #     self.boto_ec2_regions_mock.return_value = [region]
    #     with patch('sys.stderr') as StdErrMock:
    #         with self.assertRaises(SystemExit):
    #             self.aws(['./bin/aws', 'status', 'foo'])
    #     import pdb; pdb.set_trace( )
    #     output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
    #     self.assertIn("invalid choice: 'foo'", output)
    # 
    # def testInstanceCantBeStarted(self):
    #     self._write_config('\n'.join([
    #         '[ec2-instance:foo]']))
    #     with patch('sys.stderr') as StdErrMock:
    #         with self.assertRaises(SystemExit):
    #             self.aws(['./bin/aws', 'start', 'foo'])
    #     output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
    #     self.assertIn("invalid choice: 'foo'", output)
    # 
    # def testInstanceCantBeStopped(self):
    #     self._write_config('\n'.join([
    #         '[ec2-instance:foo]']))
    #     with patch('sys.stderr') as StdErrMock:
    #         with self.assertRaises(SystemExit):
    #             self.aws(['./bin/aws', 'stop', 'foo'])
    #     output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
    #     self.assertIn("invalid choice: 'foo'", output)
    # 
    # def testInstanceCantBeTerminated(self):
    #     self._write_config('\n'.join([
    #         '[ec2-instance:foo]']))
    #     with patch('sys.stderr') as StdErrMock:
    #         with self.assertRaises(SystemExit):
    #             self.aws(['./bin/aws', 'stop', 'foo'])
    #     output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
    #     self.assertIn("invalid choice: 'foo'", output)
    # 
    # def testSSHWithNoHost(self):
    #     self._write_config('\n'.join([
    #         '[ec2-instance:foo]']))
    #     with patch('mr.awsome.log') as LogMock:
    #         with self.assertRaises(SystemExit):
    #             self.aws(['./bin/aws', 'ssh', 'foo'])
    #     self.assertEquals(
    #         LogMock.error.call_args_list, [
    #             (("Couldn't validate fingerprint for ssh connection.",), {}),
    #             (("No host set in config.",), {}),
    #             (('Is the server finished starting up?',), {})])
    # 
    # def testSSHWithNoFingerprint(self):
    #     self._write_config('\n'.join([
    #         '[ec2-instance:foo]',
    #         'host = localhost']))
    #     with patch('mr.awsome.log') as LogMock:
    #         with self.assertRaises(SystemExit):
    #             self.aws(['./bin/aws', 'ssh', 'foo'])
    #     self.assertEquals(
    #         LogMock.error.call_args_list, [
    #             (("Couldn't validate fingerprint for ssh connection.",), {}),
    #             (("No fingerprint set in config.",), {}),
    #             (('Is the server finished starting up?',), {})])
    # 
    # def testSSH(self):
    #     self._write_config('\n'.join([
    #         '[ec2-instance:foo]',
    #         'host = localhost',
    #         'fingerprint = foo']))
    #     try:
    #         self.aws(['./bin/aws', 'ssh', 'foo'])
    #     except SystemExit:
    #         self.fail("SystemExit raised")
    #     known_hosts = os.path.join(self.directory, 'known_hosts')
    #     self.subprocess_call_mock.assert_called_with(
    #         ['ssh', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', 'localhost'])
