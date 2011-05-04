from mock import patch
from mr.awsome import AWS
from unittest2 import TestCase
import os
import tempfile
import shutil


class AwsomeTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def testDefaultConfigPath(self):
        aws = AWS()
        self.assertEqual(aws.configfile, 'etc/aws.conf')

    def testDirectoryAsConfig(self):
        aws = AWS(configpath=self.directory)
        self.assertEqual(
            aws.configfile,
            os.path.join(self.directory, 'aws.conf'))

    def testFileAsConfig(self):
        aws = AWS(configpath=os.path.join(self.directory, 'foo.conf'))
        self.assertEqual(
            aws.configfile,
            os.path.join(self.directory, 'foo.conf'))

    def testMissingConfig(self):
        aws = AWS(configpath=self.directory)
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                aws.config
            LogMock.error.assert_called_with("Config '%s' doesn't exist." % aws.configfile)

    def testAWSEntryPoint(self):
        import mr.awsome
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                mr.awsome.aws(self.directory)
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage:', output)
        self.assertIn('too few arguments', output)

    def testAWSSSHEntryPoint(self):
        import mr.awsome
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write("")
        with patch('sys.stderr') as StdErrMock:
            mr.awsome.aws_ssh(self.directory)
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage:', output)
        self.assertIn('Log into the server with ssh using the automatically generated known hosts', output)

    def testCallWithNoArguments(self):
        aws = AWS()
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                aws([])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage:', output)
        self.assertIn('too few arguments', output)
