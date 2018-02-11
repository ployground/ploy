from __future__ import unicode_literals
from ploy import Controller
import os
import paramiko
import pytest


class TestPlain:
    @pytest.fixture
    def ctrl(self, ployconf):
        import ploy.plain
        ctrl = Controller(ployconf.directory)
        ctrl.plugins = {
            'plain': ploy.plain.plugin}
        return ctrl

    def testInstanceHasNoStatus(self, ctrl, mock, ployconf):
        ployconf.fill([
            '[plain-instance:foo]'])
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'status', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testInstanceCantBeStarted(self, ctrl, mock, ployconf):
        ployconf.fill([
            '[plain-instance:foo]'])
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'start', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testInstanceCantBeStopped(self, ctrl, mock, ployconf):
        ployconf.fill([
            '[plain-instance:foo]'])
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testInstanceCantBeTerminated(self, ctrl, mock, ployconf):
        ployconf.fill([
            '[plain-instance:foo]'])
        with mock.patch('sys.stderr') as StdErrMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'stop', 'foo'])
        output = "".join(x[0][0] for x in StdErrMock.write.call_args_list)
        assert "invalid choice: 'foo'" in output

    def testSSHWithNoHost(self, ctrl, mock, ployconf):
        ployconf.fill([
            '[plain-instance:foo]'])
        with mock.patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'ssh', 'foo'])
        assert LogMock.error.call_args_list == [
            (("Couldn't validate fingerprint for ssh connection.",), {}),
            (("No host or ip set in config.",), {}),
            (('Is the instance finished starting up?',), {})]

    def testSSHWithFingerprintMismatch(self, ctrl, mock, ployconf, sshclient):
        ployconf.fill([
            '[plain-instance:foo]',
            'host = localhost',
            'fingerprint = foo'])
        sshclient().connect.side_effect = paramiko.SSHException(
            "Fingerprint doesn't match for localhost (got bar, expected foo)")
        with mock.patch('ploy.log') as LogMock:
            with pytest.raises(SystemExit):
                ctrl(['./bin/ploy', 'ssh', 'foo'])
        assert LogMock.error.call_args_list == [
            (("Couldn't validate fingerprint for ssh connection.",), {}),
            (("Fingerprint doesn't match for localhost (got bar, expected foo)",), {}),
            (('Is the instance finished starting up?',), {})]

    def testSSH(self, ctrl, os_execvp_mock, ployconf, sshclient):
        ployconf.fill([
            '[plain-instance:foo]',
            'host = localhost',
            'fingerprint = foo'])
        ctrl(['./bin/ploy', 'ssh', 'foo'])
        known_hosts = os.path.join(ployconf.directory, 'known_hosts')
        os_execvp_mock.assert_called_with(
            'ssh',
            ['ssh', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])

    def testSSHExtraArgs(self, ctrl, os_execvp_mock, ployconf, sshclient):
        ployconf.fill([
            '[plain-instance:foo]',
            'host = localhost',
            'fingerprint = foo',
            'ssh-extra-args = forwardagent yes'])
        ctrl(['./bin/ploy', 'ssh', 'foo'])
        known_hosts = os.path.join(ployconf.directory, 'known_hosts')
        os_execvp_mock.assert_called_with(
            'ssh',
            ['ssh', '-o', 'Forwardagent=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=%s' % known_hosts, '-l', 'root', '-p', '22', 'localhost'])


@pytest.yield_fixture
def sshclient(mock):
    with mock.patch("ploy.plain.wait_for_ssh"):
        with mock.patch("ploy.plain.wait_for_ssh_on_sock"):
            with mock.patch("paramiko.SSHClient") as ssh_client_mock:
                yield ssh_client_mock


@pytest.fixture
def filled_ployconf(confmaker):
    configfile = confmaker('ploy.conf')
    configfile.fill('\n'.join([
        '[plain-instance:foo]',
        '[plain-instance:master]',
        'host=example.com',
        'fingerprint=master']))
    return configfile


@pytest.fixture
def ctrl(filled_ployconf, tempdir):
    import ploy.plain
    ctrl = Controller(tempdir.directory)
    ctrl.plugins = {
        'plain': ploy.plain.plugin}
    ctrl.configfile = filled_ployconf.path
    return ctrl


@pytest.fixture
def instance(ctrl):
    return ctrl.instances['foo']


def test_conn_no_host(instance, mock):
    with mock.patch('ploy.common.log') as LogMock:
        with pytest.raises(SystemExit):
            instance.conn
    assert LogMock.error.call_args_list == [
        (("Couldn't connect to plain-instance:foo.",), {}),
        (("No host or ip set in config.",), {})]


def test_no_fingerprint(instance):
    instance.config['host'] = 'localhost'
    with pytest.raises(paramiko.SSHException) as e:
        instance.get_ssh_fingerprints()
    assert e.value.args[0] == "No fingerprint set in config."


def test_conn_fingerprint_mismatch(instance, mock, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    sshclient().connect.side_effect = paramiko.SSHException(
        "Fingerprint doesn't match for localhost (got bar, expected foo)")
    with mock.patch('ploy.common.log') as CommonLogMock:
        with mock.patch('ploy.plain.log') as PlainLogMock:
            with pytest.raises(SystemExit):
                instance.conn
    assert CommonLogMock.error.call_args_list == [
        mock.call("Couldn't connect to plain-instance:foo."),
        mock.call("Fingerprint doesn't match for localhost (got bar, expected foo)")]
    assert PlainLogMock.error.call_args_list == [
        mock.call("Failed to connect to plain-instance:foo (localhost)"),
        mock.call("username: root"),
        mock.call("port: 22")]


def test_ssh_fingerprints_none_set(instance):
    instance.config['host'] = 'localhost'
    with pytest.raises(paramiko.SSHException) as e:
        instance.get_ssh_fingerprints()
    assert str(e.value) == 'No fingerprint set in config.'


def test_ssh_fingerprints_ask(instance):
    from ploy.common import SSHKeyFingerprintAsk
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'ask'
    (result,) = instance.get_ssh_fingerprints()
    assert isinstance(result, SSHKeyFingerprintAsk)


def test_ssh_fingerprints_ignore(instance):
    from ploy.common import SSHKeyFingerprintIgnore
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'ignore'
    (result,) = instance.get_ssh_fingerprints()
    assert isinstance(result, SSHKeyFingerprintIgnore)


def test_ssh_fingerprints_auto(instance):
    from ploy.common import SSHKeyFingerprintInstance
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'auto'
    (result,) = instance.get_ssh_fingerprints()
    assert isinstance(result, SSHKeyFingerprintInstance)


def test_ssh_fingerprints_fingerprint(instance):
    from ploy.common import SSHKeyFingerprint
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'a6:7f:6a:a5:8a:7c:26:45:46:ca:d9:d9:8c:f2:64:27'
    (result,) = instance.get_ssh_fingerprints()
    assert isinstance(result, SSHKeyFingerprint)


def test_ssh_fingerprints_fingerprint_auto(instance):
    from ploy.common import SSHKeyFingerprint, SSHKeyFingerprintInstance
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'a6:7f:6a:a5:8a:7c:26:45:46:ca:d9:d9:8c:f2:64:27\nauto'
    (fingerprint, auto) = instance.get_ssh_fingerprints()
    assert isinstance(fingerprint, SSHKeyFingerprint)
    assert isinstance(auto, SSHKeyFingerprintInstance)


def test_conn(instance, mock, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    conn = instance.conn
    assert len(conn.method_calls) == 3
    assert conn.method_calls[0][0] == 'set_missing_host_key_policy'
    assert conn.method_calls[1] == mock.call.connect('localhost', username='root', key_filename=None, password=None, sock=None, port=22)
    assert conn.method_calls[2] == mock.call.save_host_keys(instance.master.known_hosts)


def test_conn_cached(instance, mock, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    first_client = mock.MagicMock()
    second_client = mock.MagicMock()
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


def test_conn_cached_closed(instance, mock, sshclient):
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    first_client = mock.MagicMock()
    first_client.get_transport.return_value = None
    second_client = mock.MagicMock()
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
    assert second_client.method_calls[1] == mock.call.connect('localhost', username='root', key_filename=None, password=None, sock=None, port=22)
    assert second_client.method_calls[2] == mock.call.save_host_keys(instance.master.known_hosts)


def test_bad_hostkey(instance, mock):
    with open(instance.master.known_hosts, 'w') as f:
        f.write('foo')
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    with mock.patch("paramiko.SSHClient.connect") as connect_mock:
        connect_mock.side_effect = [
            paramiko.BadHostKeyException(
                'localhost', paramiko.PKey('bar'), paramiko.PKey('foo')),
            None]
        instance.init_ssh_key()
    assert os.path.exists(instance.master.known_hosts)
    with open(instance.master.known_hosts) as f:
        assert f.read() == ''


def test_proxycommand(instance, mock, sshclient, tempdir):
    with open(instance.master.known_hosts, 'w') as f:
        f.write('foo')
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    instance.config['proxycommand'] = 'nohup {path}/../bin/ploy-ssh {instances[foo].host} -o UserKnownHostsFile={known_hosts}'
    with mock.patch("paramiko.ProxyCommand") as ProxyCommandMock:
        info = instance.init_ssh_key()
    proxycommand = 'nohup %s/../bin/ploy-ssh localhost -o UserKnownHostsFile=%s' % (tempdir.directory, instance.master.known_hosts)
    assert info['ProxyCommand'] == proxycommand
    assert ProxyCommandMock.call_args_list == [mock.call(proxycommand)]


def test_proxycommand_with_instance(ctrl, mock, sshclient):
    master = ctrl.instances['master']
    instance = ctrl.instances['foo']
    with open(instance.master.known_hosts, 'w') as f:
        f.write('foo')
    instance.config['host'] = 'localhost'
    instance.config['fingerprint'] = 'foo'
    instance.config['proxycommand'] = instance.proxycommand_with_instance(master)
    with mock.patch("paramiko.ProxyCommand") as ProxyCommandMock:
        info = instance.init_ssh_key()
    proxycommand = 'nohup ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%s -l root -p 22 example.com -W localhost:22' % instance.master.known_hosts
    assert info['ProxyCommand'] == proxycommand
    assert ProxyCommandMock.call_args_list == [mock.call(proxycommand)]


def test_proxycommand_through_instance(ctrl, mock, filled_ployconf, sshclient):
    filled_ployconf.append('[plain-instance:bar]')
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
    with mock.patch("paramiko.ProxyCommand") as ProxyCommandMock:
        info = instance2.init_ssh_key()
    proxycommand = 'nohup ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%s -l root -p 22 example.com -W localhost:22' % instance.master.known_hosts
    proxycommand2 = "nohup ssh -o 'ProxyCommand=%s' -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%s -l root -p 22 localhost -W bar.example.com:22" % (proxycommand, instance.master.known_hosts)
    assert info['ProxyCommand'] == proxycommand2
    assert ProxyCommandMock.call_args_list == [mock.call(proxycommand2)]


def test_missing_host_key_mismatch(mock, sshclient):
    from ploy.common import SSHKeyFingerprint
    from ploy.plain import ServerHostKeyPolicy
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprint('SHA256:LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564')])  # that's sha256 of 'foo'
    key = mock.MagicMock()
    key.get_name.return_value = 'ssh-rsa'
    key.asbytes.return_value = b'bar'
    key.get_bits.return_value = None
    with pytest.raises(paramiko.SSHException) as e:
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert str(e.value) == (
        "Fingerprint doesn't match for localhost (got "
        "[SSHKeyFingerprint('SHA256:/N4rLtula/QIYB+3If6bXDONEO5CnqBPrlURto+/j7k', keytype='rsa')], "
        "expected: [SSHKeyFingerprint('SHA256:LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564')])")


def test_missing_host_key(mock, tempdir, sshclient):
    from ploy.common import SSHKeyFingerprint
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprint('SHA256:LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564')])  # that's sha256 of 'foo'
    key = mock.MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.mock_calls == [
        mock.call.get_host_keys(),
        mock.call.get_host_keys().add('localhost', 'ssh-rsa', key),
        mock.call.save_host_keys(known_hosts)]


def test_missing_host_key_ignore(mock, tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintIgnore
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintIgnore()])
    key = mock.MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with mock.patch('ploy.common.log') as LogMock:
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.mock_calls == [
        mock.call.get_host_keys(),
        mock.call.get_host_keys().add('localhost', 'ssh-rsa', key),
        mock.call.save_host_keys(known_hosts)]
    assert LogMock.method_calls == [
        mock.call.warn(
            'Fingerprint verification disabled!\n'
            'Got fingerprint ac:bd:18:db:4c:c2:f8:5c:ed:ef:65:4f:cc:c4:a4:d8.')]


def test_missing_host_key_ask_answer_no(mock, tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintAsk
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintAsk()])
    key = mock.MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with mock.patch("ploy.common.yesno") as yesno_mock:
        yesno_mock.return_value = False
        with pytest.raises(SystemExit):
            shkp.missing_host_key(sshclient, 'localhost', key)


def test_missing_host_key_ask_answer_yes(mock, tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintAsk
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintAsk()])
    key = mock.MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with mock.patch("ploy.common.yesno") as yesno_mock:
        yesno_mock.return_value = True
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.method_calls == []


def test_missing_host_key_ask_answer_yes_and_try_again(mock, tempdir, sshclient):
    from ploy.common import SSHKeyFingerprintAsk
    from ploy.plain import ServerHostKeyPolicy
    known_hosts = tempdir['known_hosts'].path
    sshclient._host_keys_filename = known_hosts
    shkp = ServerHostKeyPolicy(lambda: [SSHKeyFingerprintAsk()])
    key = mock.MagicMock()
    key.asbytes.return_value = b'foo'
    key.get_name.return_value = 'ssh-rsa'
    with mock.patch("ploy.common.yesno") as yesno_mock:
        # if yesno is called twice, it throws an error
        yesno_mock.side_effect = [True, RuntimeError]
        shkp.missing_host_key(sshclient, 'localhost', key)
        shkp.missing_host_key(sshclient, 'localhost', key)
    assert sshclient.method_calls == []


def test_instance_get_fingerprint():
    pass
