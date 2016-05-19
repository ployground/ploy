from mock import MagicMock, call, patch
from ploy import Controller
import os
import pytest


try:
    unicode
except NameError:  # pragma: nocover
    unicode = str


class TestPlain:
    @pytest.fixture(autouse=True)
    def setup_ctrl(self, os_execvp_mock, paramiko, sshclient, sshconfig, tempdir):
        import ploy.plain
        self.directory = tempdir.directory
        self.ctrl = Controller(self.directory)
        self.ctrl.plugins = {
            'plain': ploy.plain.plugin}
        self.paramiko = paramiko
        self.ssh_client_mock = sshclient
        self.os_execvp_mock = os_execvp_mock

    def _write_config(self, content):
        with open(os.path.join(self.directory, 'ploy.conf'), 'w') as f:
            f.write(content)

    def testInstanceHasNoStatus(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'status', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testInstanceCantBeStarted(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'start', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testInstanceCantBeStopped(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testInstanceCantBeTerminated(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testSSHWithNoHost(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]']))
        with patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'ssh', 'foo'])
        assert LogMock.error.call_args_list == [
            (("Couldn't validate fingerprint for ssh connection.",), {}),
            (("No host or ip set in config.",), {}),
            (('Is the instance finished starting up?',), {})]

    def testSSHWithFingerprintMismatch(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]',
            'host = localhost',
            'fingerprint = foo']))
        self.ssh_client_mock().connect.side_effect = self.paramiko.SSHException(
            "Fingerprint doesn't match for localhost (got bar, expected foo)")
        with patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                self.ctrl(['./bin/ploy', 'ssh', 'foo'])
        assert LogMock.error.call_args_list == [
            (("Couldn't validate fingerprint for ssh connection.",), {}),
            (("Fingerprint doesn't match for localhost (got bar, expected foo)",), {}),
            (('Is the instance finished starting up?',), {})]

    def testSSH(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]',
            'host = localhost',
            'fingerprint = foo']))
        self.ctrl(['./bin/ploy', 'ssh', 'foo'])
        known_hosts = os.path.join(self.directory, 'known_hosts')
        self.os_execvp_mock.assert_called_with(
            'ssh',
            ['ssh', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])

    def testSSHExtraArgs(self):
        self._write_config('\n'.join([
            '[plain-instance:foo]',
            'host = localhost',
            'fingerprint = foo',
            'ssh-extra-args = forwardagent yes']))
        self.ctrl(['./bin/ploy', 'ssh', 'foo'])
        known_hosts = os.path.join(self.directory, 'known_hosts')
        self.os_execvp_mock.assert_called_with(
            'ssh',
            ['ssh', '-o', 'Forwardagent=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])


@pytest.fixture
def paramiko():
    from ploy.common import import_paramiko
    return import_paramiko()


@pytest.yield_fixture
def sshconfig(paramiko):
    with patch("%s.SSHConfig" % paramiko.__name__) as ssh_config_mock:
        ssh_config_mock().lookup.return_value = {}
        yield ssh_config_mock


@pytest.yield_fixture
def sshclient(paramiko):
    with patch("%s.SSHClient" % paramiko.__name__) as ssh_client_mock:
        yield ssh_client_mock


@pytest.fixture
def ployconf(tempdir):
    configfile = tempdir['ploy.conf']
    configfile.fill('\n'.join([
        '[plain-instance:foo]',
        '[plain-instance:master]',
        'host=example.com',
        'fingerprint=master']))
    return configfile


@pytest.fixture
def ctrl(ployconf, tempdir, sshconfig):
    import ploy.plain
    ctrl = Controller(tempdir.directory)
    ctrl.plugins = {
        'plain': ploy.plain.plugin}
    ctrl.configfile = ployconf.path
    return ctrl


@pytest.fixture
def instance(ctrl):
    return ctrl.instances['foo']


def test_conn_no_host(instance):
    with patch('ploy.common.log') as LogMock:
        with pytest.raises(SystemExit):
            instance.conn
    assert LogMock.error.call_args_list == [
        (("Couldn't connect to plain-instance:foo.",), {}),
        (("No host or ip set in config.",), {})]


def test_conn_no_fingerprint(instance):
    instance.config['host'] = 'localhost'
    with patch('ploy.common.log') as LogMock:
        with pytest.raises(SystemExit):
            instance.conn
    assert LogMock.error.call_args_list == [
        (("Couldn't connect to plain-instance:foo.",), {}),
        (("No fingerprint set in config.",), {})]


def test_conn_fingerprint_mismatch(instance, paramiko, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    sshclient().connect.side_effect = paramiko.SSHException(
        "Fingerprint doesn't match for localhost (got bar, expected foo)")
    with patch('ploy.common.log') as CommonLogMock:
        with patch('ploy.plain.log') as PlainLogMock:
            with pytest.raises(SystemExit):
                instance.conn
    assert CommonLogMock.error.call_args_list == [
        (("Couldn't connect to plain-instance:foo.",), {}),
        (("Fingerprint doesn't match for localhost (got bar, expected foo)",), {})]
    assert PlainLogMock.error.call_args_list == [
        (("Failed to connect to plain-instance:foo (localhost)",), {}),
        (("username: 'root'",), {}),
        (("port: 22",), {})]


def test_conn(instance, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    conn = instance.conn
    assert len(conn.method_calls) == 3
    assert conn.method_calls[0][0] == 'set_missing_host_key_policy'
    assert conn.method_calls[1] == call.connect('localhost', username='root', key_filename=None, password=None, sock=None, port=22)
    assert conn.method_calls[2] == call.save_host_keys(instance.master.known_hosts)


def test_conn_cached(instance, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    first_client = MagicMock()
    second_client = MagicMock()
    sshclient.side_effect = [first_client, second_client]
    conn = instance.conn
    assert len(first_client.method_calls) == 3
    assert [x[0] for x in first_client.method_calls] == [
        'set_missing_host_key_policy',
        'connect',
        'save_host_keys']
    conn1 = instance.conn
    assert conn1 is conn
    assert conn1 is first_client
    assert conn1 is not second_client
    assert len(first_client.method_calls) == 4
    assert [x[0] for x in first_client.method_calls] == [
        'set_missing_host_key_policy',
        'connect',
        'save_host_keys',
        'get_transport']


def test_conn_cached_closed(instance, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    first_client = MagicMock()
    first_client.get_transport.return_value = None
    second_client = MagicMock()
    sshclient.side_effect = [first_client, second_client]
    conn = instance.conn
    assert len(first_client.method_calls) == 3
    assert [x[0] for x in first_client.method_calls] == [
        'set_missing_host_key_policy',
        'connect',
        'save_host_keys']
    conn1 = instance.conn
    assert conn1 is not conn
    assert conn1 is not first_client
    assert conn1 is second_client
    assert len(first_client.method_calls) == 4
    assert [x[0] for x in first_client.method_calls] == [
        'set_missing_host_key_policy',
        'connect',
        'save_host_keys',
        'get_transport']
    assert len(second_client.method_calls) == 3
    assert second_client.method_calls[0][0] == 'set_missing_host_key_policy'
    assert second_client.method_calls[1] == call.connect('localhost', username='root', key_filename=None, password=None, sock=None, port=22)
    assert second_client.method_calls[2] == call.save_host_keys(instance.master.known_hosts)


def test_bad_hostkey(instance, paramiko):
    with open(instance.master.known_hosts, 'w') as f:
        f.write('foo')
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    with patch("%s.SSHClient.connect" % paramiko.__name__) as connect_mock:
        connect_mock.side_effect = [
            paramiko.BadHostKeyException(
                'localhost', paramiko.PKey('bar'), paramiko.PKey('foo')),
            None]
        instance.init_ssh_key()
    assert os.path.exists(instance.master.known_hosts)
    with open(instance.master.known_hosts) as f:
        assert f.read() == ''


def test_proxycommand(instance, paramiko, sshclient, tempdir):
    with open(instance.master.known_hosts, 'w') as f:
        f.write('foo')
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    instance.config['proxycommand'] = 'nohup {path}/../bin/ploy-ssh {instances[foo].host} -o UserKnownHostsFile={known_hosts}'
    with patch("%s.ProxyCommand" % paramiko.__name__) as ProxyCommandMock:
        info = instance.init_ssh_key()
    proxycommand = 'nohup %s/../bin/ploy-ssh localhost -o UserKnownHostsFile=%s' % (tempdir.directory, instance.master.known_hosts)
    assert info['ProxyCommand'] == proxycommand
    assert ProxyCommandMock.call_args_list == [call(proxycommand)]


def test_proxycommand_with_instance(ctrl, paramiko, sshclient):
    master = ctrl.instances['master']
    instance = ctrl.instances['foo']
    with open(instance.master.known_hosts, 'w') as f:
        f.write('foo')
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    instance.config['proxycommand'] = instance.proxycommand_with_instance(master)
    with patch("%s.ProxyCommand" % paramiko.__name__) as ProxyCommandMock:
        info = instance.init_ssh_key()
    proxycommand = 'nohup ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%s -l root -p 22 example.com -W localhost:22' % instance.master.known_hosts
    assert info['ProxyCommand'] == proxycommand
    assert ProxyCommandMock.call_args_list == [call(proxycommand)]


def test_proxycommand_through_instance(ctrl, ployconf, paramiko, sshclient):
    ployconf.append('[plain-instance:bar]')
    master = ctrl.instances['master']
    instance = ctrl.instances['foo']
    instance2 = ctrl.instances['bar']
    with open(instance.master.known_hosts, 'w') as f:
        f.write('foo')
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    instance.config['proxycommand'] = instance.proxycommand_with_instance(master)
    instance2.config['host'] = 'bar.example.com'
    instance2.config['fingerprint'] = 'foo'
    instance2.config['proxycommand'] = instance2.proxycommand_with_instance(instance)
    with patch("%s.ProxyCommand" % paramiko.__name__) as ProxyCommandMock:
        info = instance2.init_ssh_key()
    proxycommand = 'nohup ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%s -l root -p 22 example.com -W localhost:22' % instance.master.known_hosts
    proxycommand2 = "nohup ssh -o 'ProxyCommand=%s' -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%s -l root -p 22 localhost -W bar.example.com:22" % (proxycommand, instance.master.known_hosts)
    assert info['ProxyCommand'] == proxycommand2
    assert ProxyCommandMock.call_args_list == [call(proxycommand2)]


def test_missing_host_key_mismatch(paramiko, sshclient):
    from ploy.common import SSHKeyFingerprint
    from ploy.plain import ServerHostKeyPolicy
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprint('SHA256:LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564')])  # that's sha256 of 'foo'
    key = MagicMock()
    key.asbytes.return_value = b'bar'
    key.get_bits.return_value = None
    with pytest.raises(paramiko.SSHException) as e:
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert unicode(e.value) == (
        "Fingerprint doesn't match for localhost (got "
        "['SHA256:/N4rLtula/QIYB+3If6bXDONEO5CnqBPrlURto+/j7k'], "
        "expected: ['SHA256:LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564'])")


def test_missing_host_key(tempdir, sshclient):
    from ploy.common import SSHKeyFingerprint
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprint('SHA256:LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564')])  # that's sha256 of 'foo'
    key = MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.mock_calls == [
        call.get_host_keys(),
        call.get_host_keys().add('localhost', 'ssh-rsa', key),
        call.save_host_keys(known_hosts)]


def test_missing_host_key_ignore(tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintIgnore
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintIgnore()])
    key = MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with patch('ploy.common.log') as LogMock:
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.mock_calls == [
        call.get_host_keys(),
        call.get_host_keys().add('localhost', 'ssh-rsa', key),
        call.save_host_keys(known_hosts)]
    assert LogMock.method_calls == [
        call.warn(
            'Fingerprint verification disabled!\n'
            'Got fingerprint ac:bd:18:db:4c:c2:f8:5c:ed:ef:65:4f:cc:c4:a4:d8.')]


def test_missing_host_key_ask_answer_no(tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintAsk
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintAsk()])
    key = MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with patch("ploy.common.yesno") as yesno_mock:
        yesno_mock.return_value = False
        with pytest.raises(SystemExit):
            shkp.missing_host_key(sshclient, 'localhost', key)


def test_missing_host_key_ask_answer_yes(tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintAsk
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintAsk()])
    key = MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with patch("ploy.common.yesno") as yesno_mock:
        yesno_mock.return_value = True
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.method_calls == []


def test_missing_host_key_ask_answer_yes_and_try_again(tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintAsk
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintAsk()])
    key = MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with patch("ploy.common.yesno") as yesno_mock:
        # if yesno is called twice, it throws an error
        yesno_mock.side_effect = [True, RuntimeError]
        shkp.missing_host_key(sshclient, 'localhost', key)
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.method_calls == []


def test_instance_get_fingerprint():
    pass
