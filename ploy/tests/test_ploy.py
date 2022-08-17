from __future__ import unicode_literals
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


@pytest.fixture
def ctrl(ployconf):
    ctrl = Controller(ployconf.directory)
    ctrl.configfile = ployconf.path
    return ctrl


@pytest.fixture
def ctrl_dummy_plugin(ctrl):
    import ploy.tests.dummy_plugin
    ctrl.plugins = {'dummy': ploy.tests.dummy_plugin.plugin}
    return ctrl


class TestPloy:
    def testDefaultConfigPath(self):
        ctrl = Controller()
        ctrl(['./bin/ploy', 'help'])
        assert ctrl.configfile == 'etc/ploy.conf'

    def testDirectoryAsConfig(self, confext, ployconf):
        if confext == '.yml':
            pytest.skip("Default is .conf, so we don't check with .yml")
        ctrl = Controller(configpath=ployconf.directory)
        ctrl(['./bin/ploy', 'help'])
        assert ctrl.configfile == ployconf.path

    def testFileConfigName(self, ployconf):
        ctrl = Controller(configpath=ployconf.directory, configname='foo.conf')
        ctrl(['./bin/ploy', 'help'])
        assert ctrl.configfile == os.path.join(ployconf.directory, 'foo.conf')

    def testMissingConfig(self, mock, ployconf):
        ctrl = Controller(configpath=ployconf.directory)
        ctrl.configfile = ployconf.path
        with mock.patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl.config
            LogMock.error.assert_called_with("Config '%s' doesn't exist." % ctrl.configfile)

    def testCallWithNoArguments(self, mock, ployconf):
        ctrl = Controller(configpath=ployconf.directory)
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage:' in output
        assert too_view_arguments in output

    def testOverwriteConfigPath(self, ployconf):
        ployconf.makedirs()
        open(os.path.join(ployconf.directory, 'foo.conf'), 'w').write('\n'.join([
            '[global]',
            'foo = bar']))
        ctrl = Controller(configpath=ployconf.directory)
        ctrl(['./bin/ploy', '-c', os.path.join(ployconf.directory, 'foo.conf'), 'help'])
        assert ctrl.configfile == os.path.join(ployconf.directory, 'foo.conf')
        assert ctrl.config == {'global': {'global': {'foo': 'bar'}}}

    def testKnownHostsWithNoConfigErrors(self, ctrl, ployconf):
        with pytest.raises(SystemExit):
            ctrl.known_hosts

    def testKnownHosts(self, ctrl, ployconf):
        ployconf.fill([])
        assert ctrl.known_hosts == os.path.join(ployconf.directory, 'known_hosts')

    def testConflictingPluginCommandName(self, ctrl, mock, ployconf):
        ctrl.plugins = dict(dummy=dict(
            get_commands=lambda x: [
                ('ssh', None)]))
        with mock.patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl([])
        LogMock.error.assert_called_with("Command name '%s' of '%s' conflicts with existing command name.", 'ssh', 'dummy')

    def testConflictingInstanceShortName(self, ctrl, mock, ployconf):
        import ploy.plain
        ployconf.fill([
            '[dummy-instance:foo]',
            '[plain-instance:foo]'])
        ctrl.plugins = {
            'dummy': ploy.tests.dummy_plugin.plugin,
            'plain': ploy.plain.plugin}
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'ssh', 'bar'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "(choose from 'default-foo', 'plain-foo')" in output

    def testInvalidInstanceName(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill([
            '[dummy-instance:fo o]'])
        with mock.patch('ploy.common.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl_dummy_plugin(['./bin/ploy', 'ssh', 'bar'])
        LogMock.error.assert_called_with("Invalid instance name 'fo o'. An instance name may only contain letters, numbers, dashes and underscores.")

    def testInstanceAugmentation(self, ctrl_dummy_plugin, ployconf):
        ployconf.fill([
            '[dummy-instance:foo]'])
        assert 'dummy_augmented' in ctrl_dummy_plugin.instances['foo'].config
        assert ctrl_dummy_plugin.instances['foo'].config['dummy_augmented'] == 'augmented massaged'

    def testInstanceAugmentationProxiedMaster(self, ctrl, ployconf):
        import ploy.tests.dummy_proxy_plugin
        import ploy.plain
        ployconf.fill([
            '[plain-instance:foo]',
            'somevalue = ham',
            '[dummy-master:master]',
            'instance = foo',
            '[dummy-instance:bar]',
            'dummy_value = egg'])
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
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'start'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy start' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'start', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy start' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'start', 'foo'])
        assert len(LogMock.info.call_args_list) == 1
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert list(call_args[2].keys()) == ['instances']
        assert sorted(call_args[2]['instances'].keys()) == ['default-foo', 'foo']

    def testCallWithInvalidOverride(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        with mock.patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl_dummy_plugin(['./bin/ploy', 'start', 'foo', '-o', 'ham:egg,spam:1'])
        LogMock.error.assert_called_with("Invalid format for override 'ham:egg,spam:1', should be NAME=VALUE.")

    def testCallWithOverride(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'start', 'foo', '-o', 'ham=egg'])
        assert len(LogMock.info.call_args_list) == 2
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert sorted(call_args[2].keys()) == ['ham', 'instances']
        assert sorted(call_args[2]['instances'].keys()) == ['default-foo', 'foo']
        assert LogMock.info.call_args_list[1] == (('status: %s', 'foo'), {})

    def testCallWithOverrides(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'start', 'foo', '-o', 'ham=egg', 'spam=1'])
        assert len(LogMock.info.call_args_list) == 2
        call_args = LogMock.info.call_args_list[0][0]
        assert call_args[0] == 'start: %s %s'
        assert call_args[1] == 'foo'
        assert sorted(call_args[2].keys()) == ['ham', 'instances', 'spam']
        assert sorted(call_args[2]['instances'].keys()) == ['default-foo', 'foo']
        assert LogMock.info.call_args_list[1] == (('status: %s', 'foo'), {})

    def testCallWithMissingStartupScript(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(ployconf.directory, 'startup')]))
        with mock.patch('ploy.common.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(ployconf.directory, 'startup'))

    def testCallWithTooBigStartupScript(self, ctrl_dummy_plugin, mock, ployconf):
        startup = os.path.join(ployconf.directory, 'startup')
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with mock.patch('ploy.log') as LogMock:
            with mock.patch('ploy.common.log') as CommonLogMock:
                ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo'])
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)

    def testHook(self, ctrl_dummy_plugin, mock, ployconf, tempdir):
        startup = tempdir['startup']
        startup.fill(';;;;;;;;;;')
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup.path,
            'hooks = ploy.tests.test_ploy.DummyHooks']))
        with mock.patch('ploy.tests.test_ploy.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'start', 'foo'])
        assert LogMock.info.call_args_list == [
            (('before_start',), {}),
            (('startup_script_options',), {})]


class TestStatusCommand:
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'status'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy status' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'status', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy status' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'status', 'foo'])
        LogMock.info.assert_called_with('status: %s', 'foo')


class TestStopCommand:
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'stop'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy stop' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy stop' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'stop', 'foo'])
        LogMock.info.assert_called_with('stop: %s', 'foo')


class TestTerminateCommand:
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'terminate'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy terminate' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'terminate', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy terminate' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, ctrl_dummy_plugin, mock, ployconf, yesno_mock):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        yesno_mock.expected = [
            ("Are you sure you want to terminate 'dummy-instance:foo'?", True)]
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'terminate', 'foo'])
        LogMock.info.assert_called_with('terminate: %s', 'foo')

    def testHook(self, ctrl_dummy_plugin, mock, ployconf, yesno_mock):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'hooks = ploy.tests.test_ploy.DummyHooks']))
        yesno_mock.expected = [
            ("Are you sure you want to terminate 'dummy-instance:foo'?", True)]
        with mock.patch('ploy.tests.test_ploy.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'terminate', 'foo'])
        assert LogMock.info.call_args_list == [(('after_terminate',), {})]


class TestDebugCommand:
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'debug'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy debug' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'debug', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy debug' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]']))
        with mock.patch('ploy.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo'])
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 0, 1024)

    def testCallWithMissingStartupScript(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % os.path.join(ployconf.directory, 'startup')]))
        with mock.patch('ploy.common.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo'])
        LogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(ployconf.directory, 'startup'))

    def testCallWithTooBigStartupScript(self, ctrl_dummy_plugin, mock, ployconf):
        startup = os.path.join(ployconf.directory, 'startup')
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write(';;;;;;;;;;' * 150)
        with mock.patch('ploy.log') as LogMock:
            with mock.patch('ploy.common.log') as CommonLogMock:
                ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo'])
        LogMock.info.assert_called_with('Length of startup script: %s/%s', 1500, 1024)
        CommonLogMock.error.assert_called_with('Startup script too big (%s > %s).', 1500, 1024)

    def testCallWithVerboseOption(self, ctrl_dummy_plugin, mock, ployconf):
        startup = os.path.join(ployconf.directory, 'startup')
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup]))
        with open(startup, 'w') as f:
            f.write('FooBar')
        with mock.patch('sys.stdout') as StdOutMock:
            with mock.patch('ploy.log') as LogMock:
                ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo', '-v'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert output == 'FooBar'
        assert LogMock.info.call_args_list == [
            (('Length of startup script: %s/%s', 6, 1024), {}), (('Startup script:',), {})]

    def testCallWithTemplateStartupScript(self, ctrl_dummy_plugin, mock, ployconf):
        startup = os.path.join(ployconf.directory, 'startup')
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with mock.patch('sys.stdout') as StdOutMock:
            with mock.patch('ploy.log') as LogMock:
                ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo', '-v'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert output == 'bar'
        assert LogMock.info.call_args_list == [
            (('Length of startup script: %s/%s', 3, 1024), {}), (('Startup script:',), {})]

    def testCallWithOverride(self, ctrl_dummy_plugin, mock, ployconf):
        startup = os.path.join(ployconf.directory, 'startup')
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'startup_script = %s' % startup,
            'foo = bar']))
        with open(startup, 'w') as f:
            f.write('{foo}')
        with mock.patch('sys.stdout') as StdOutMock:
            with mock.patch('ploy.log') as LogMock:
                ctrl_dummy_plugin(['./bin/ploy', 'debug', 'foo', '-v', '-o', 'foo=hamster'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert output == 'hamster'
        assert LogMock.info.call_args_list == [
            (('Length of startup script: %s/%s', 7, 1024), {}), (('Startup script:',), {})]


class TestListCommand:
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'list'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy list' in output
        assert too_view_arguments in output

    def testCallWithNonExistingList(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'list', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy list' in output
        assert "argument listname: invalid choice: 'foo'" in output

    def testCallWithExistingListButNoMastersWithSnapshots(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with mock.patch('sys.stdout') as StdOutMock:
            ctrl_dummy_plugin(['./bin/ploy', 'list', 'dummy'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        output = list(filter(None, output.splitlines()))
        assert output == ['list_dummy']


class TestSSHCommand:
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'ssh'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy ssh' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'ssh', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy ssh' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, ctrl_dummy_plugin, mock, os_execvp_mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'ssh', 'foo'])
        assert LogMock.info.call_args_list == [
            (('init_ssh_key: %s %s', 'foo', None), {}),
            (('client.get_transport',), {}),
            (('sock.close',), {}),
            (('client.close',), {})]
        known_hosts = os.path.join(ployconf.directory, 'known_hosts')
        os_execvp_mock.assert_called_with(
            'ssh',
            ['ssh', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])


class TestSnapshotCommand:
    def testCallWithNoArguments(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'snapshot'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy snapshot' in output
        assert too_view_arguments in output

    def testCallWithNonExistingInstance(self, ctrl, mock, ployconf):
        ployconf.fill('')
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'snapshot', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy snapshot' in output
        assert "argument instance: invalid choice: 'foo'" in output

    def testCallWithExistingInstance(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with mock.patch('ploy.tests.dummy_plugin.log') as LogMock:
            ctrl_dummy_plugin(['./bin/ploy', 'snapshot', 'foo'])
        assert LogMock.info.call_args_list == [
            (('snapshot: %s', 'foo'), {})]


class TestHelpCommand:
    def testCallWithNoArguments(self, ctrl, mock):
        with mock.patch('sys.stdout') as StdOutMock:
            ctrl(['./bin/ploy', 'help'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert 'usage: ploy help' in output
        assert 'Name of the command you want help for.' in output

    def testCallWithNonExistingCommand(self, ctrl, mock):
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'help', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert 'usage: ploy help' in output
        assert "argument command: invalid choice: 'foo'" in output

    def testCallWithExistingCommand(self, ctrl, mock):
        with mock.patch('sys.stdout') as StdOutMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'help', 'start'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert 'usage: ploy start' in output
        assert 'Starts the instance' in output

    def testZSHHelperCommands(self, ctrl, mock):
        with mock.patch('sys.stdout') as StdOutMock:
            ctrl(['./bin/ploy', 'help', '-z'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert 'start' in output.splitlines()

    def testZSHHelperCommand(self, ctrl_dummy_plugin, mock, ployconf):
        ployconf.fill('\n'.join([
            '[dummy-instance:foo]',
            'host = localhost']))
        with mock.patch('sys.stdout') as StdOutMock:
            ctrl_dummy_plugin(['./bin/ploy', 'help', '-z', 'start'])
        output = "".join(x[0][0] for x in StdOutMock.write.call_args_list)
        assert output.splitlines() == ['default-foo', 'foo']


class TestInstance:
    def testStartupScript(self, ctrl_dummy_plugin, ployconf, tempdir):
        ployconf.fill([
            '[dummy-master:master]',
            '[instance:foo]',
            'master = master',
            'startup_script = ../startup'])
        tempdir['startup'].fill('startup')
        instance = ctrl_dummy_plugin.instances['foo']
        startup = instance.startup_script()
        assert startup == 'startup'
