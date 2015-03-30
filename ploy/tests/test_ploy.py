from mock import patch
from ploy import Controller
import logging
import os
import pytest
import sys


log = logging.getLogger('test')


class DummyHooks(object):
    def after_terminate(self, instance):
        log.info('after_terminate')

    def before_start(self, instance):
        log.info('before_start')

    def startup_script_options(self, options):
        log.info('startup_script_options')


if sys.version_info < (3,):  # pragma: nocover
    too_view_arguments = 'too few arguments'
else:  # pragma: nocover
    too_view_arguments = 'the following arguments are required'


class TestPloy:
    @pytest.fixture(autouse=True)
    def setup_configfile(self, ployconf):
        self.directory = ployconf.directory
        ployconf.fill([])
        self.configfile = ployconf

    def testDefaultConfigPath(self):
        ctrl = Controller()
        ctrl(['./bin/ploy', 'help'])
        assert ctrl.configfile == 'etc/ploy.conf'

    def testDirectoryAsConfig(self):
        ctrl = Controller(configpath=self.directory)
        ctrl(['./bin/ploy', 'help'])
        assert ctrl.configfile == self.configfile.path

    def testFileConfigName(self):
        ctrl = Controller(configpath=self.directory, configname='foo.conf')
        ctrl(['./bin/ploy', 'help'])
        assert ctrl.configfile == os.path.join(self.directory, 'foo.conf')

    def testMissingConfig(self):
        os.remove(self.configfile.path)
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        with patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl.config
            LogMock.error.assert_called_with("Config '%s' doesn't exist." % ctrl.configfile)

    def testCallWithNoArguments(self):
        ctrl = Controller(configpath=self.directory)
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage:' in output
        assert too_view_arguments in output

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
        assert ctrl.known_hosts == os.path.join(self.directory, 'known_hosts')

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
        assert "(choose from 'default-foo', 'plain-foo')" in output

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

    def testInstanceAugmentation(self):
        import ploy.tests.dummy_plugin
        self.configfile.fill([
            '[dummy-instance:foo]'])
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        ctrl.plugins = {
            'dummy': ploy.tests.dummy_plugin.plugin}
        assert 'dummy_augmented' in ctrl.instances['foo'].config
        assert ctrl.instances['foo'].config['dummy_augmented'] == 'augmented massaged'

    def testInstanceAugmentationProxiedMaster(self):
        import ploy.tests.dummy_proxy_plugin
        import ploy.plain
        self.configfile.fill([
            '[plain-instance:foo]',
            'somevalue = ham',
            '[dummy-master:master]',
            'instance = foo',
            '[dummy-instance:bar]',
            'dummy_value = egg'])
        ctrl = Controller(configpath=self.directory)
        ctrl.configfile = self.configfile.path
        ctrl.plugins = {
            'dummy': ploy.tests.dummy_proxy_plugin.plugin,
            'plain': ploy.plain.plugin}
        # trigger augmentation of all instances
        instances = dict(ctrl.instances)
        # check the proxied value, which is only accessible through the instance config
        assert 'somevalue' in instances['master'].config
        assert instances['master'].config['somevalue'] == 'ham'
        # we check that the main config is updated for the remaining values,
        # not only the individual instance configs
        assert 'dummy_value' in ctrl.config['dummy-instance']['bar']
        assert ctrl.config['dummy-instance']['bar']['dummy_value'] == 'egg massaged'
        assert 'dummy_augmented' in ctrl.config['dummy-instance']['bar']
        assert ctrl.config['dummy-instance']['bar']['dummy_augmented'] == 'augmented massaged'


class TestStartCommand:
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
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'start'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy start' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'start', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy start' in output
        assert "argument instance: invalid choice: 'foo'" in output

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
        assert list(call_args[2].keys()) == ['instances']
        assert sorted(call_args[2]['instances'].keys()) == ['default-foo', 'foo']

    def testCallWithInvalidOverride(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
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
            with pytest.raises(SystemExit):
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


class TestStatusCommand:
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'status'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy status' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'status', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy status' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'status', 'foo'])
        LogMock.info.assert_called_with('status: %s', 'foo')


class TestStopCommand:
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'stop'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy stop' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy stop' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'stop', 'foo'])
        LogMock.info.assert_called_with('stop: %s', 'foo')


class TestTerminateCommand:
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'terminate'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy terminate' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'terminate', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy terminate' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, yesno_mock):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]']))
        yesno_mock.expected = [
            ("Are you sure you want to terminate 'dummy-instance:foo'?", True)]
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'terminate', 'foo'])
        LogMock.info.assert_called_with('terminate: %s', 'foo')

    def testHook(self, yesno_mock):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'hooks = ploy.tests.test_ploy.DummyHooks']))
        yesno_mock.expected = [
            ("Are you sure you want to terminate 'dummy-instance:foo'?", True)]
        with patch('ploy.tests.test_ploy.log') as LogMock:
            self.ctrl(['./bin/ploy', 'terminate', 'foo'])
        assert LogMock.info.call_args_list == [(('after_terminate',), {})]


class TestDebugCommand:
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.directory = ployconf.directory
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'debug'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy debug' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'debug', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy debug' in output
        assert "argument instance: invalid choice: 'foo'" in output

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
            with pytest.raises(SystemExit):
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
        assert output == 'FooBar'
        assert LogMock.info.call_args_list == [
            (('Length of startup script: %s/%s', 6, 1024), {}), (('Startup script:',), {})]

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
        assert output == 'bar'
        assert LogMock.info.call_args_list == [
            (('Length of startup script: %s/%s', 3, 1024), {}), (('Startup script:',), {})]

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
        assert output == 'hamster'
        assert LogMock.info.call_args_list == [
            (('Length of startup script: %s/%s', 7, 1024), {}), (('Startup script:',), {})]


class TestListCommand:
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'list'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy list' in output
        assert too_view_arguments in output

    def testCallWithNonExistingList(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'list', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy list' in output
        assert "argument listname: invalid choice: 'foo'" in output

    def testCallWithExistingListButNoMastersWithSnapshots(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('sys.stdout') as StdOutMock:
            self.ctrl(['./bin/ploy', 'list', 'dummy'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        output = list(filter(None, output.splitlines()))
        assert output == ['list_dummy']


class TestSSHCommand:
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
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'ssh'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy ssh' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'ssh', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy ssh' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'ssh', 'foo'])
        assert LogMock.info.call_args_list == [
            (('init_ssh_key: %s %s', 'foo', None), {}),
            (('client.get_transport',), {}),
            (('sock.close',), {}),
            (('client.close',), {})]
        known_hosts = os.path.join(self.directory, 'known_hosts')
        self.os_execvp_mock.assert_called_with(
            'ssh',
            ['ssh', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])


class TestSnapshotCommand:
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, ployconf):
        self.ctrl = Controller(ployconf.directory)
        self.ctrl.configfile = ployconf.path
        self._write_config = ployconf.fill

    def testCallWithNoArguments(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'snapshot'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy snapshot' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self):
        self._write_config('')
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'snapshot', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy snapshot' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self):
        import ploy.tests.dummy_plugin
        self.ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
        self._write_config('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with patch('ploy.tests.dummy_plugin.log') as LogMock:
            self.ctrl(['./bin/ploy', 'snapshot', 'foo'])
        assert LogMock.info.call_args_list == [
            (('snapshot: %s', 'foo'), {})]


class TestHelpCommand:
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
        assert 'usage: ploy help' in output
        assert 'Name of the command you want help for.' in output

    def testCallWithNonExistingCommand(self):
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'help', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy help' in output
        assert "argument command: invalid choice: 'foo'" in output

    def testCallWithExistingCommand(self):
        with patch('sys.stdout') as StdOutMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'help', 'start'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert 'usage: ploy start' in output
        assert 'Starts the instance' in output

    def testZSHHelperCommands(self):
        with patch('sys.stdout') as StdOutMock:
            self.ctrl(['./bin/ploy', 'help', '-z'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert 'start' in output.splitlines()

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


class TestInstance:
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
