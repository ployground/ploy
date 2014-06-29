from mock import patch
from ploy import Controller
from unittest2 import TestCase
import logging
import os
import pytest


log = logging.getLogger('test')


class DummyHooks(object):
    def after_terminate(self, instance):
        log.info('after_terminate')

    def before_start(self, instance):
        log.info('before_start')

    def startup_script_options(self, options):
        log.info('startup_script_options')


class AwsomeTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_configfile(self, ployconf):
        self.directory = ployconf.directory
        ployconf.fill([])
        self.configfile = ployconf

    def testDefaultConfigPath(self):
        ctrl = Controller()
        ctrl(['./bin/ploy', 'help'])
        self.assertEqual(ctrl.configfile, 'etc/ploy.conf')

    def testDirectoryAsConfig(self):
        ctrl = Controller(configpath=self.directory)
        ctrl(['./bin/ploy', 'help'])
        assert ctrl.configfile == self.configfile.path

    def testFileConfigName(self):
        ctrl = Controller(configpath=self.directory, configname='foo.conf')
        ctrl(['./bin/ploy', 'help'])
        self.assertEqual(
            ctrl.configfile,
            os.path.join(self.directory, 'foo.conf'))

    def testMissingConfig(self):
        os.remove(self.configfile.path)
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        with patch('ploy.log') as LogMock:
            with self.assertRaises(SystemExit):
                ctrl.config
            LogMock.error.assert_called_with("Config '%s' doesn't exist." % ctrl.configfile)

    def testCallWithNoArguments(self):
        ctrl = Controller(configpath=self.directory)
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                ctrl(['./bin/ploy'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage:', output)
        self.assertIn('too few arguments', output)

    def testOverwriteConfigPath(self):
        open(os.path.join(self.directory, 'foo.conf'), 'w').write('\n'.join([
            '[global]',
            'foo = bar']))
        ctrl = Controller(configpath=self.directory)
        ctrl(['./bin/ploy', '-c', os.path.join(self.directory, 'foo.conf'), 'help'])
        assert ctrl.configfile == os.path.join(self.directory, 'foo.conf')
        assert ctrl.config == {'global': {'global': {'foo': 'bar'}}}

    def testKnownHostsWithNoConfigErrors(self):
        os.remove(self.configfile.path)
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        with pytest.raises(SystemExit):
            ctrl.known_hosts

    def testKnownHosts(self):
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        self.assertEqual(
            ctrl.known_hosts,
            os.path.join(self.directory, 'known_hosts'))

    def testConflictingPluginCommandName(self):
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        ctrl.plugins = dict(dummy=dict(
            get_commands=lambda x: [
                ('ssh', None)]))
        with patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl([])
        LogMock.error.assert_called_with("Command name '%s' of '%s' conflicts with existing command name.", 'ssh', 'dummy')

    def testConflictingInstanceShortName(self):
        import ploy.tests.dummy_plugin
        import ploy.plain
        self.configfile.fill([
            '[dummy-instance:foo]',
            '[plain-instance:foo]'])
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        ctrl.plugins = {
            'dummy': ploy.tests.dummy_plugin.plugin,
            'plain': ploy.plain.plugin}
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'ssh', 'bar'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "(choose from 'default-foo', 'plain-master-foo')" in output

    def testInvalidInstanceName(self):
        import ploy.tests.dummy_plugin
        self.configfile.fill([
            '[dummy-instance:fo o]'])
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        with patch('ploy.common.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'ssh', 'bar'])
        LogMock.error.assert_called_with("Invalid instance name 'fo o'. An instance name may only contain letters, numbers, dashes and underscores.")


class StartCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf, tempdir):
        self.directory = ployconf.directory
        self.tempdir = tempdir
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'start'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy start', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'start', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy start', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'start', 'foo'])
        assert len(LogMock.info.call_args_list) == 1
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert call_args[2].keys() == ['instances']
        assert sorted(call_args[2]['instances'].keys()) == ['default-foo', 'foo']

    def testCallWithInvalidOverride(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'start', 'foo', '-o', 'ham:egg,spam:1'])
        LogMock.error.assert_called_with("Invalid format for override 'ham:egg,spam:1', should be NAME=VALUE.")

    def testCallWithOverride(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'start', 'foo', '-o', 'ham=egg'])
        assert len(LogMock.info.call_args_list) == 2
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert sorted(call_args[2].keys()) == ['ham', 'instances']
        assert sorted(call_args[2]['instances'].keys()) == ['default-foo', 'foo']
        assert LogMock.info.call_args_list[1] == (('status: %s', 'foo'), {})

    def testCallWithOverrides(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'start', 'foo', '-o', 'ham=egg', 'spam=1'])
        assert len(LogMock.info.call_args_list) == 2
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert sorted(call_args[2].keys()) == ['ham', 'instances', 'spam']
        assert sorted(call_args[2]['instances'].keys()) == ['default-foo', 'foo']
        assert LogMock.info.call_args_list[1] == (('status: %s', 'foo'), {})

    def testCallWithMissingStartupScript(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(self.directory, 'startup')]))
        with patch('ploy.common.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'startup'))

    def testCallWithTooBigStartupScript(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with patch('ploy.log') as LogMock:
            with patch('ploy.common.log') as CommonLogMock:
                self.ctrl(['./bin/ploy', 'debug', 'foo'])
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)

    def testHook(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        startup = self.tempdir['startup']
        startup.fill(';;;;;;;;;;')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup.path,
            'hooks = ploy.tests.test_ploy.DummyHooks']))
        with patch('ploy.tests.test_ploy.log') as LogMock:
            self.ctrl(['./bin/ploy', 'start', 'foo'])
        assert LogMock.info.call_args_list == [
            (('before_start',), {}),
            (('startup_script_options',), {})]


class StatusCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'status'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy status', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'status', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy status', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'status', 'foo'])
        LogMock.info.assert_called_with('status: %s', 'foo')


class StopCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'stop'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy stop', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy stop', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'stop', 'foo'])
        LogMock.info.assert_called_with('stop: %s', 'foo')


class TerminateCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'terminate'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy terminate', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'terminate', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy terminate', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'terminate', 'foo'])
        LogMock.info.assert_called_with('terminate: %s', 'foo')

    def testHook(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'hooks = ploy.tests.test_ploy.DummyHooks']))
        with patch('ploy.tests.test_ploy.log') as LogMock:
            self.ctrl(['./bin/ploy', 'terminate', 'foo'])
        assert LogMock.info.call_args_list == [(('after_terminate',), {})]


class DebugCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.directory = ployconf.directory
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'debug'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy debug', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'debug', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy debug', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.log') as LogMock:
            self.ctrl(['./bin/ploy', 'debug', 'foo'])
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 0, 1024)

    def testCallWithMissingStartupScript(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(self.directory, 'startup')]))
        with patch('ploy.common.log') as LogMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'startup'))

    def testCallWithTooBigStartupScript(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with patch('ploy.log') as LogMock:
            with patch('ploy.common.log') as CommonLogMock:
                self.ctrl(['./bin/ploy', 'debug', 'foo'])
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)

    def testCallWithVerboseOption(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write('FooBar')
        with patch('sys.stdout') as StdOutMock:
            with patch('ploy.log') as LogMock:
                self.ctrl(['./bin/ploy', 'debug', 'foo', '-v'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'FooBar')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 6, 1024), {}), (('Startup script:',), {})])

    def testCallWithTemplateStartupScript(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with patch('sys.stdout') as StdOutMock:
            with patch('ploy.log') as LogMock:
                self.ctrl(['./bin/ploy', 'debug', 'foo', '-v'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'bar')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 3, 1024), {}), (('Startup script:',), {})])

    def testCallWithOverride(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        startup = os.path.join(self.directory, 'startup')
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with patch('sys.stdout') as StdOutMock:
            with patch('ploy.log') as LogMock:
                self.ctrl(['./bin/ploy', 'debug', 'foo', '-v', '-o', 'foo=hamster'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertEquals(output, 'hamster')
        self.assertEquals(
            LogMock.info.call_args_list,
            [(('Length of startup script: %s/%s', 7, 1024), {}), (('Startup script:',), {})])


class ListCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'list'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy list', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingList(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'list', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy list', output)
        self.assertIn("argument listname: invalid choice: 'foo'", output)

    def testCallWithExistingListButNoMastersWithSnapshots(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('sys.stdout') as StdOutMock:
            self.ctrl(['./bin/ploy', 'list', 'dummy'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        output = filter(None, output.splitlines())
        assert output == ['list_dummy']


@pytest.yield_fixture
def os_execvp_mock():
    with patch("os.execvp") as os_execvp_mock:
        yield os_execvp_mock


class SSHCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf, os_execvp_mock):
        self.directory = ployconf.directory
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill
        self.os_execvp_mock = os_execvp_mock

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'ssh'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy ssh', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'ssh', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy ssh', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'ssh', 'foo'])
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
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'snapshot'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy snapshot', output)
        self.assertIn('too few arguments', output)

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'snapshot', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy snapshot', output)
        self.assertIn("argument instance: invalid choice: 'foo'", output)

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'snapshot', 'foo'])
        self.assertEquals(
            LogMock.info.call_args_list,
            [
                (('snapshot: %s', 'foo'), {})])


class HelpCommandTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill
        self._write_config('')

    def testCallWithNoArguments(self):
        with patch('sys.stdout') as StdOutMock:
            self.ctrl(['./bin/ploy', 'help'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertIn('usage: ploy help', output)
        self.assertIn('Name of the command you want help for.', output)

    def testCallWithNonExistingCommand(self):
        with patch('sys.stderr') as StdErrMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'help', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        self.assertIn('usage: ploy help', output)
        self.assertIn("argument command: invalid choice: 'foo'", output)

    def testCallWithExistingCommand(self):
        with patch('sys.stdout') as StdOutMock:
            with self.assertRaises(SystemExit):
                self.ctrl(['./bin/ploy', 'help', 'start'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertIn('usage: ploy start', output)
        self.assertIn('Starts the instance', output)

    def testZSHHelperCommands(self):
        with patch('sys.stdout') as StdOutMock:
            self.ctrl(['./bin/ploy', 'help', '-z'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        self.assertIn('start', output.splitlines())

    def testZSHHelperCommand(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('sys.stdout') as StdOutMock:
            self.ctrl(['./bin/ploy', 'help', '-z', 'start'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert output.splitlines() == ['default-foo', 'foo']


class InstanceTests(TestCase):
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf, tempdir):
        import ploy.tests.dummy_plugin
        ployconf.fill([
            '[dummy-master:master]',
            '[instance:foo]',
            'master = master',
            'startup_script = ../startup'])
        tempdir['startup'].fill('startup')
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}

    def testStartupScript(self):
        instance = self.ctrl.instances['foo']
        startup = instance.startup_script()
        assert startup == 'startup'
