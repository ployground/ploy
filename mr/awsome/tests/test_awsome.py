from mock import patch
from mr.awsome import AWS
from unittest2 import TestCase
import logging
import os
import pytest
import tempfile
import shutil


log = logging.getLogger('test')


class DummyHooks(object):
    def after_terminate(self, server):
        log.info('after_terminate')

    def before_start(self, server):
        log.info('before_start')

    def startup_script_options(self, options):
        log.info('startup_script_options')


class AwsomeTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        open(os.path.join(self.directory, 'aws.conf'), 'w')

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

    def testFileConfigName(self):
        aws = AWS(configpath=self.directory, configname='foo.conf')
        self.assertEqual(
            aws.configfile,
            os.path.join(self.directory, 'foo.conf'))

    def testMissingConfig(self):
        os.remove(os.path.join(self.directory, 'aws.conf'))
        aws = AWS(configpath=self.directory)
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                aws.config
            LogMock.error.assert_called_with("Config '%s' doesn't exist." % aws.configfile)

    def testCallWithNoArguments(self):
        aws = AWS(configpath=self.directory)
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                aws(['./bin/aws'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage:', output)
        self.assertIn('too few arguments', output)

    def testKnownHostsWithNoConfigErrors(self):
        os.remove(os.path.join(self.directory, 'aws.conf'))
        aws = AWS(configpath=self.directory)
        with pytest.raises(SystemExit):
            aws.known_hosts

    def testKnownHosts(self):
        aws = AWS(configpath=self.directory)
        self.assertEqual(
            aws.known_hosts,
            os.path.join(self.directory, 'known_hosts'))

    def testConflictingPluginCommandName(self):
        aws = AWS(configpath=self.directory)
        aws.plugins = dict(dummy=dict(
            get_commands=lambda x: [
                ('ssh', None)]))
        with patch('mr.awsome.log') as LogMock:
            with pytest.raises(SystemExit):
                aws([])
        LogMock.error.assert_called_with("Command name '%s' of '%s' conflicts with existing command name.", 'ssh', 'dummy')


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
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'start', 'foo'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        assert len(LogMock.info.call_args_list) == 1
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert call_args[2].keys() == ['servers']
        assert call_args[2]['servers'].keys() == ['foo']

    def testCallWithInvalidOverride(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'start', 'foo', '-o', 'ham:egg,spam:1'])
        LogMock.error.assert_called_with("Invalid format for override 'ham:egg,spam:1', should be NAME=VALUE.")

    def testCallWithOverride(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'start', 'foo', '-o', 'ham=egg'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        assert len(LogMock.info.call_args_list) == 2
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert sorted(call_args[2].keys()) == ['ham', 'servers']
        assert call_args[2]['servers'].keys() == ['foo']
        assert LogMock.info.call_args_list[1] == (('status: %s', 'foo'), {})

    def testCallWithOverrides(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'start', 'foo', '-o', 'ham=egg', 'spam=1'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        assert len(LogMock.info.call_args_list) == 2
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert sorted(call_args[2].keys()) == ['ham', 'servers', 'spam']
        assert call_args[2]['servers'].keys() == ['foo']
        assert LogMock.info.call_args_list[1] == (('status: %s', 'foo'), {})

    def testCallWithMissingStartupScript(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(self.directory, 'startup')]))
        with patch('mr.awsome.common.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'startup'))

    def testCallWithTooBigStartupScript(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with patch('mr.awsome.log') as LogMock:
            with patch('mr.awsome.common.log') as CommonLogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo'])
                except SystemExit:  # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)

    def testHook(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'hooks = mr.awsome.tests.test_awsome.DummyHooks']))
        with patch('mr.awsome.tests.test_awsome.log') as LogMock:
            self.aws(['./bin/aws', 'start', 'foo'])
        assert LogMock.info.call_args_list == [
            (('before_start',), {}),
            (('startup_script_options',), {})]


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
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'status', 'foo'])
            except SystemExit:  # pragma: no cover - only if something is wrong
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
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'stop', 'foo'])
            except SystemExit:  # pragma: no cover - only if something is wrong
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
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'terminate', 'foo'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        LogMock.info.assert_called_with('terminate: %s', 'foo')

    def testHook(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'hooks = mr.awsome.tests.test_awsome.DummyHooks']))
        with patch('mr.awsome.tests.test_awsome.log') as LogMock:
            self.aws(['./bin/aws', 'terminate', 'foo'])
        assert LogMock.info.call_args_list == [(('after_terminate',), {})]


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
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('mr.awsome.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'debug', 'foo'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 0, 1024)

    def testCallWithMissingStartupScript(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(self.directory, 'startup')]))
        with patch('mr.awsome.common.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'startup'))

    def testCallWithTooBigStartupScript(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with patch('mr.awsome.log') as LogMock:
            with patch('mr.awsome.common.log') as CommonLogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo'])
                except SystemExit:  # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)

    def testCallWithVerboseOption(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write('FooBar')
        with patch('sys.stdout') as StdOutMock:
            with patch('mr.awsome.log') as LogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo', '-v'])
                except SystemExit:  # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'FooBar')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 6, 1024), {}), (('Startup script:',), {})])

    def testCallWithTemplateStartupScript(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with patch('sys.stdout') as StdOutMock:
            with patch('mr.awsome.log') as LogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo', '-v'])
                except SystemExit:  # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'bar')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 3, 1024), {}), (('Startup script:',), {})])

    def testCallWithOverride(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with patch('sys.stdout') as StdOutMock:
            with patch('mr.awsome.log') as LogMock:
                try:
                    self.aws(['./bin/aws', 'debug', 'foo', '-v', '-o', 'foo=hamster'])
                except SystemExit:  # pragma: no cover - only if something is wrong
                    self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'hamster')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 7, 1024), {}), (('Startup script:',), {})])


class ListCommandTests(TestCase):
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
                self.aws(['./bin/aws', 'list'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws list', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingList(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'list', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws list', output)
        self.assertIn("argument list: invalid choice: 'foo'", output)

    def testCallWithExistingListButNoMastersWithSnapshots(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('sys.stdout') as StdOutMock:
            try:
                self.aws(['./bin/aws', 'list', 'snapshots'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        output = filter(None, output.split('\n'))
        assert len(output) == 1

    def testCallWithExistingListAndDummySnapshots(self):
        import mr.awsome.tests.dummy_plugin
        snapshots = {}

        def get_masters(aws):
            master = mr.awsome.tests.dummy_plugin.Master(
                aws, 'dummy-master', {})
            print "get_masters called"
            master.snapshots = snapshots
            return [master]

        self.aws.plugins = {'dummy': {'get_masters': get_masters}}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('sys.stdout') as StdOutMock:
            try:
                self.aws(['./bin/aws', 'list', 'snapshots'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        output = filter(None, output.split('\n'))
        assert len(output) == 2
        assert output[0] == 'get_masters called'

        # now with data
        class Snapshot(object):
            def __init__(self, **kw):
                self.__dict__.update(kw)
        snapshots['foo'] = Snapshot(
            id='foo', start_time='20:00',
            volume_size='100', volume_id='0sht80sht',
            progress=80, description='bar')
        with patch('sys.stdout') as StdOutMock:
            try:
                self.aws(['./bin/aws', 'list', 'snapshots'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        output = filter(None, output.split('\n'))
        assert len(output) == 2
        assert 'description' in output[0]
        assert output[1].split() == [
            'foo', '20:00', '100', 'GB', '0sht80sht', '80', 'bar']


class SSHCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)
        self._os_execvp_mock = patch("os.execvp")
        self.os_execvp_mock = self._os_execvp_mock.start()

    def tearDown(self):
        self.os_execvp_mock = self._os_execvp_mock.stop()
        del self.os_execvp_mock
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
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'ssh', 'foo'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.assertEquals(
            LogMock.info.call_args_list,
            [
                (('init_ssh_key: %s %s', 'foo', None), {}),
                (('client.get_transport',), {}),
                (('sock.close',), {}),
                (('client.close',), {})])
        known_hosts = os.path.join(self.directory, 'known_hosts')
        self.os_execvp_mock.assert_called_with(
            'ssh',
            ['ssh', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])


class SnapshotCommandTests(TestCase):
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
                self.aws(['./bin/aws', 'snapshot'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws snapshot', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'snapshot', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws snapshot', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('mr.awsome.tests.dummy_plugin.log') as LogMock:
            try:
                self.aws(['./bin/aws', 'snapshot', 'foo'])
            except SystemExit:  # pragma: no cover - only if something is wrong
                self.fail("SystemExit raised")
        self.assertEquals(
            LogMock.info.call_args_list,
            [
                (('snapshot: %s', 'foo'), {})])


class HelpCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)
        self._write_config('')

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'aws.conf'), 'w') as f:
            f.write(content)

    def testCallWithNoArguments(self):
        with patch('sys.stdout') as StdOutMock:
            self.aws(['./bin/aws', 'help'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertIn('usage: aws help', output)
        self.assertIn('Name of the command you want help for.', output)

    def testCallWithNonExistingCommand(self):
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'help', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: aws help', output)
        self.assertIn("argument command: invalid choice: 'foo'", output)

    def testCallWithExistingCommand(self):
        with patch('sys.stdout') as StdOutMock:
            with self.assertRaises(SystemExit):
                self.aws(['./bin/aws', 'help', 'start'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertIn('usage: aws start', output)
        self.assertIn('Starts the instance', output)

    def testZSHHelperCommands(self):
        with patch('sys.stdout') as StdOutMock:
            self.aws(['./bin/aws', 'help', '-z'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertIn('start', output.split('\n'))

    def testZSHHelperCommand(self):
        import mr.awsome.tests.dummy_plugin
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('sys.stdout') as StdOutMock:
            self.aws(['./bin/aws', 'help', '-z', 'start'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert output == 'foo\n'


class InstanceTests(TestCase):
    def setUp(self):
        import mr.awsome.tests.dummy_plugin
        self.directory = tempfile.mkdtemp()
        self.aws = AWS(self.directory)
        self.aws.plugins = {'dummy': mr.awsome.tests.dummy_plugin.plugin}
        self._write_file('\n'.join([
            '[dummy-master:master]',
            '[instance:foo]',
            'master = master',
            'startup_script = startup']))
        self._write_file('startup', name='startup')

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _write_file(self, content, name='aws.conf'):
        with open(os.path.join(self.directory, name), 'w') as f:
            f.write(content)

    def testStartupScript(self):
        instance = self.aws.instances['foo']
        startup = instance.startup_script()
        assert startup == 'startup'
