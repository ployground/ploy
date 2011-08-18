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

    def testCallWithNoArguments(self):
        aws = AWS()
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                aws(['./bin/aws'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage:', output)
        self.assertIn('too few arguments', output)


class StartCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'start'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws start', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'start', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws start', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'start', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.assertTrue(LogMock.info.called)
        self.assertEquals(LogMock.info.call_args[0][0], 'start: %s %s')
        self.assertEquals(LogMock.info.call_args[0][1], 'foo')
        self.assertEquals(LogMock.info.call_args[0][2].keys(), ['servers'])
        self.assertEquals(LogMock.info.call_args[0][2]['servers'].keys(), ['foo'])

    def testCallWithInvalidOverride(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'start', 'foo', '-o', 'ham:egg,spam:1'])
        LogMock.error.assert_called_with("Invalid format for override 'ham:egg,spam:1', should be NAME=VALUE.")

    def testCallWithOverride(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'start', 'foo', '-o', 'ham=egg'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.assertTrue(LogMock.info.called)
        self.assertEquals(LogMock.info.call_args[0][0], 'start: %s %s')
        self.assertEquals(LogMock.info.call_args[0][1], 'foo')
        self.assertEquals(
            sorted(LogMock.info.call_args[0][2].keys()),
            sorted(['servers', 'ham']))
        self.assertEquals(LogMock.info.call_args[0][2]['servers'].keys(), ['foo'])
        self.assertEquals(LogMock.info.call_args[0][2]['ham'], 'egg')

    def testCallWithOverrides(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'start', 'foo', '-o', 'ham=egg', 'spam=1'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.assertTrue(LogMock.info.called)
        self.assertEquals(LogMock.info.call_args[0][0], 'start: %s %s')
        self.assertEquals(LogMock.info.call_args[0][1], 'foo')
        self.assertEquals(
            sorted(LogMock.info.call_args[0][2].keys()),
            sorted(['servers', 'ham', 'spam']))
        self.assertEquals(LogMock.info.call_args[0][2]['servers'].keys(), ['foo'])

    def testCallWithMissingStartupScript(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(self.directory, 'startup')]))
        with patch('mr.awsome.common.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'startup'))

    def testCallWithTooBigStartupScript(self):
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with patch('mr.awsome.log') as LogMock:
            with patch('mr.awsome.common.log') as CommonLogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo'])
                except SystemExit: # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)


class StatusCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws status', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'status', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws status', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'status', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        LogMock.info.assert_called_with('status: %s', 'foo')


class StopCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'stop'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws stop', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws stop', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'stop', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        LogMock.info.assert_called_with('stop: %s', 'foo')


class TerminateCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'terminate'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws terminate', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'terminate', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws terminate', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'terminate', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        LogMock.info.assert_called_with('terminate: %s', 'foo')


class DebugCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'debug'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws debug', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'debug', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws debug', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'debug', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 0, 1024)

    def testCallWithMissingStartupScript(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(self.directory, 'startup')]))
        with patch('mr.awsome.common.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'startup'))

    def testCallWithTooBigStartupScript(self):
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with patch('mr.awsome.log') as LogMock:
            with patch('mr.awsome.common.log') as CommonLogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo'])
                except SystemExit: # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)

    def testCallWithVerboseOption(self):
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write('FooBar')
        with patch('sys.stdout') as StdOutMock:
            with patch('mr.awsome.log') as LogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo', '-v'])
                except SystemExit: # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'FooBar')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 6, 1024), {}), (('Startup script:',), {})])

    def testCallWithTemplateStartupScript(self):
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with patch('sys.stdout') as StdOutMock:
            with patch('mr.awsome.log') as LogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo', '-v'])
                except SystemExit: # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'bar')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 3, 1024), {}), (('Startup script:',), {})])

    def testCallWithOverride(self):
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with patch('sys.stdout') as StdOutMock:
            with patch('mr.awsome.log') as LogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo', '-v', '-o', 'foo=hamster'])
                except SystemExit: # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'hamster')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 7, 1024), {}), (('Startup script:',), {})])


class DoCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'do'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws do', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'do', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws do', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstanceButTooViewArguments(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'do', 'foo'])
        LogMock.error.assert_called_with('No fabfile declared.')

    def testCallWithMissingFabfileDeclaration(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]']))
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'do', 'foo', 'something'])
        LogMock.error.assert_called_with('No fabfile declared.')

    def testCallWithExistingInstance(self):
        fabfile = os.path.join(self.directory, 'fabfile.py')
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'host = localhost',
            'fabfile = %s' % fabfile]))
        with open(fabfile, 'w') as f:
            f.write('\n'.join([
                'def something():',
                '    print "something"']))
        from mr.awsome import fabric_integration
        # this needs to be done before any other fabric module import
        fabric_integration.patch()
        with patch('fabric.main.main') as FabricMainMock:
            self.aws(['./bin/aws', 'do', 'foo', 'something'])
        FabricMainMock.assert_called_with()


class SSHCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)
        self._subprocess_call_mock = patch("subprocess.call")
        self.subprocess_call_mock = self._subprocess_call_mock.start()

    def tearDown(self):
        self.subprocess_call_mock = self._subprocess_call_mock.stop()
        del self.subprocess_call_mock
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'ssh'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws ssh', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'ssh', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws ssh', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        self._write_config('\n'.join([
            '[plugin:null]',
            'module = mr.awsome.tests.dummy_plugin',
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'ssh', 'foo'])
            except SystemExit: # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('init_ssh_key: %s %s', 'foo', None), {}), (('client.close',), {})])
        known_hosts = os.path.join(self.directory, 'known_hosts')
        self.subprocess_call_mock.assert_called_with(
            ['ssh', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])
