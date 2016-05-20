from __future__ import print_function
try:
    from StringIO import StringIO
except ImportError:  # pragma: nocover
    from io import StringIO
from mock import patch
from ploy.common import InstanceHooks, BaseInstance, StartupScriptMixin
from ploy.common import SSHKeyFingerprint, parse_ssh_keygen
from ploy.config import Config, StartupScriptMassager
import os
import pytest
import textwrap


class MockController(object):
    plugins = {}


class MockMaster(object):
    def __init__(self, main_config):
        self.ctrl = MockController()
        self.main_config = main_config


class MockInstance(BaseInstance, StartupScriptMixin):
    sectiongroupname = "instance"

    def __init__(self):
        self.config = {}
        self.id = "foo"
        self.hooks = InstanceHooks(self)


class TestStartupScript:
    @pytest.fixture(autouse=True)
    def setup_tempdir(self, tempdir):
        self.tempdir = tempdir
        self.directory = tempdir.directory

    def _create_config(self, contents, path=None):
        contents = StringIO(contents)
        config = Config(contents, path=path)
        config.add_massager(
            StartupScriptMassager('instance', 'startup_script'))
        return config.parse()

    def testNoStartupScript(self):
        instance = MockInstance()
        config = self._create_config("[instance:foo]")
        instance.master = MockMaster(config)
        result = instance.startup_script()
        assert result == ""

    def testMissingStartupScript(self):
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        with patch('ploy.common.log') as CommonLogMock:
            with pytest.raises(SystemExit):
                instance.startup_script()
        CommonLogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'foo'))

    def testEmptyStartupScript(self):
        self.tempdir['foo'].fill("")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        result = instance.startup_script()
        assert result == ""

    def testGzip(self):
        self.tempdir['foo'].fill("")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = gzip:foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        result = instance.startup_script()
        expected = b"\n".join([
            b"#!/bin/sh",
            b"tail -n+4 $0 | gunzip -c | /bin/sh",
            b"exit $?",
            b""])
        assert result[:len(expected)] == expected
        payload = result[len(expected):]
        header = payload[:10]
        body = payload[10:]
        assert header[:4] == b"\x1f\x8b\x08\x00"  # magic + compression + flags
        assert header[8:] == b"\x02\xff"  # extra flags + os
        assert body == b"\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    def testGzipCustomShebang(self):
        self.tempdir['foo'].fill("#!/usr/bin/env python")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = gzip:foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        result = instance.startup_script()
        expected = b"\n".join([
            b"#!/bin/sh",
            b"tail -n+4 $0 | gunzip -c | /usr/bin/env python",
            b"exit $?",
            b""])
        assert result[:len(expected)] == expected

    def test_strip_hashcomments(self):
        self.tempdir['foo'].fill([
            "#!/bin/bash",
            "some command",
            "#some comment",
            "    # an indented comment",
            "and another command"])
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        result = instance.startup_script()
        assert result == "\n".join([
            "#!/bin/bash",
            "some command",
            "and another command"])

    def testMaxSizeOk(self):
        self.tempdir['foo'].fill("")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        instance.max_startup_script_size = 10
        result = instance.startup_script()
        assert result == ""

    def testMaxSizeExceeded(self):
        self.tempdir['foo'].fill("aaaaabbbbbccccc")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        instance.max_startup_script_size = 10
        with patch('ploy.common.log') as LogMock:
            with pytest.raises(SystemExit):
                instance.startup_script()
            LogMock.error.assert_called_with('Startup script too big (%s > %s).', 15, 10)

    def testMaxSizeExceededDebug(self):
        self.tempdir['foo'].fill("aaaaabbbbbccccc")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        instance.max_startup_script_size = 10
        with patch('ploy.common.log') as LogMock:
            instance.startup_script(debug=True)
            LogMock.error.assert_called_with('Startup script too big (%s > %s).', 15, 10)


class TestBaseMaster:
    @pytest.yield_fixture
    def ctrl(self, ployconf):
        from ploy import Controller
        import ploy.tests.dummy_plugin
        ployconf.fill([
            '[dummy-master:warden]',
            '[dummy-master:master]',
            '[dummy-master:another]',
            '[dummy-instance:foo]',
            'master = warden',
            '[dummy-instance:bar]',
            'master = master',
            '[dummy-instance:ham]',
            'master = warden master',
            '[dummy-instance:egg]'])
        ctrl = Controller(configpath=ployconf.directory)
        ctrl.plugins = {
            'dummy': ploy.tests.dummy_plugin.plugin}
        ctrl.configfile = ployconf.path
        yield ctrl

    def test_master_association(self, ctrl):
        assert sorted(ctrl.instances) == sorted([
            'warden-foo', 'foo',
            'master-bar', 'bar',
            'warden-ham', 'master-ham',
            'warden-egg', 'master-egg', 'another-egg'])


@pytest.mark.parametrize("default, all, question, answer, expected", [
    (None, False, 'Foo [yes/no] ', ['y'], True),
    (None, False, 'Foo [yes/no] ', ['yes'], True),
    (None, False, 'Foo [yes/no] ', ['Yes'], True),
    (None, False, 'Foo [yes/no] ', ['YES'], True),
    (None, False, 'Foo [yes/no] ', ['n'], False),
    (None, False, 'Foo [yes/no] ', ['no'], False),
    (None, False, 'Foo [yes/no] ', ['No'], False),
    (None, False, 'Foo [yes/no] ', ['NO'], False),
    (None, True, 'Foo [yes/no/all] ', ['a'], 'all'),
    (None, True, 'Foo [yes/no/all] ', ['all'], 'all'),
    (None, True, 'Foo [yes/no/all] ', ['All'], 'all'),
    (None, True, 'Foo [yes/no/all] ', ['ALL'], 'all'),
    (None, False, 'Foo [yes/no] ', ['YEbUS'], IndexError),
    (None, False, 'Foo [yes/no] ', ['NarNJa'], IndexError),
    (None, True, 'Foo [yes/no/all] ', ['ALfred'], IndexError),
    (True, False, 'Foo [Yes/no] ', [''], True),
    (False, False, 'Foo [yes/No] ', [''], False),
    ('all', True, 'Foo [yes/no/All] ', [''], 'all')])
def test_yesno(default, all, question, answer, expected):
    from ploy.common import yesno
    raw_input_values = answer

    def get_input_result(q):
        assert q == question
        a = raw_input_values.pop()
        print(q, repr(a))
        return a

    with patch('ploy.common.get_input') as RawInput:
        RawInput.side_effect = get_input_result
        try:
            assert yesno('Foo', default, all) == expected
        except Exception as e:
            assert type(e) == expected


@pytest.mark.parametrize("text, keyinfo", [
    (
        textwrap.dedent("""
            ec2: -----BEGIN SSH HOST KEY FINGERPRINTS-----
            ec2: 2048 a6:7f:6a:a5:8a:7c:26:45:46:ca:d9:d9:8c:f2:64:27 /etc/ssh/ssh_host_key.pub
            ec2: 2048 b6:57:b7:52:4e:36:94:ab:9c:ec:a1:b3:56:71:80:e0 /etc/ssh/ssh_host_rsa_key.pub
            ec2: 1024 62:47:49:82:83:9a:d8:1d:b8:c6:8f:dd:4d:d8:9a:2e /etc/ssh/ssh_host_dsa_key.pub
            ec2: -----END SSH HOST KEY FINGERPRINTS-----
            """),
        [
            SSHKeyFingerprint(keylen=2048, keytype='rsa1', fingerprint='a6:7f:6a:a5:8a:7c:26:45:46:ca:d9:d9:8c:f2:64:27'),
            SSHKeyFingerprint(keylen=2048, keytype='rsa', fingerprint='b6:57:b7:52:4e:36:94:ab:9c:ec:a1:b3:56:71:80:e0'),
            SSHKeyFingerprint(keylen=1024, keytype='dsa', fingerprint='62:47:49:82:83:9a:d8:1d:b8:c6:8f:dd:4d:d8:9a:2e')]),
    (
        textwrap.dedent("""
            -----BEGIN SSH HOST KEY FINGERPRINTS-----
            2048 2e:68:49:26:49:07:67:31:f1:33:92:18:09:c3:6a:ae /etc/ssh/ssh_host_rsa_key.pub (RSA)
            1024 4b:99:0e:4a:a4:3e:b4:e5:ef:42:5e:43:07:93:91:a0 /etc/ssh/ssh_host_dsa_key.pub (DSA)
            -----END SSH HOST KEY FINGERPRINTS-----
            """),
        [
            SSHKeyFingerprint(keylen=2048, keytype='rsa', fingerprint='2e:68:49:26:49:07:67:31:f1:33:92:18:09:c3:6a:ae'),
            SSHKeyFingerprint(keylen=1024, keytype='dsa', fingerprint='4b:99:0e:4a:a4:3e:b4:e5:ef:42:5e:43:07:93:91:a0')]),
    (
        textwrap.dedent("""
            2048 MD5:cd:be:b8:a2:57:bf:71:5c:ed:14:b8:27:e8:e1:4a:a6 ~/.ssh/id_dsa.pub (DSA)
            2048 SHA256:maRuD3fpz+6JXV5RZK/g5/rToUH9XrxyKgl7yewS6ZY ~/.ssh/id_dsa.pub (DSA)
            """),
        [
            SSHKeyFingerprint(keylen=2048, keytype='dsa', fingerprint='cd:be:b8:a2:57:bf:71:5c:ed:14:b8:27:e8:e1:4a:a6'),
            SSHKeyFingerprint(keylen=2048, keytype='dsa', fingerprint='SHA256:maRuD3fpz+6JXV5RZK/g5/rToUH9XrxyKgl7yewS6ZY')]),
    (
        textwrap.dedent("""
            ec2: #############################################################
            ec2: -----BEGIN SSH HOST KEY FINGERPRINTS-----
            ec2: 1024 7b:0d:a3:0d:9e:fc:f3:97:bb:a8:d2:1d:05:3f:d5:f9  root@ip-172-31-27-225 (DSA)
            ec2: 256 96:c6:3c:47:7b:11:eb:8a:ca:78:ed:20:d6:21:f2:b7  root@ip-172-31-27-225 (ECDSA)
            ec2: 256 56:0f:1a:4d:cc:66:0a:9e:90:d5:1d:98:3a:03:ef:b6  root@ip-172-31-27-225 (ED25519)
            ec2: 2048 b6:8a:43:51:72:af:49:88:a5:d6:c5:7f:3c:fd:91:70  root@ip-172-31-27-225 (RSA1)
            ec2: 2048 ef:85:3d:e6:ab:c4:18:88:81:63:08:0f:32:8a:9d:e0  root@ip-172-31-27-225 (RSA)
            ec2: -----END SSH HOST KEY FINGERPRINTS-----
            ec2: #############################################################
            """),
        [
            SSHKeyFingerprint(keylen=1024, keytype='dsa', fingerprint='7b:0d:a3:0d:9e:fc:f3:97:bb:a8:d2:1d:05:3f:d5:f9'),
            SSHKeyFingerprint(keylen=256, keytype='ecdsa', fingerprint='96:c6:3c:47:7b:11:eb:8a:ca:78:ed:20:d6:21:f2:b7'),
            SSHKeyFingerprint(keylen=256, keytype='ed25519', fingerprint='56:0f:1a:4d:cc:66:0a:9e:90:d5:1d:98:3a:03:ef:b6'),
            SSHKeyFingerprint(keylen=2048, keytype='rsa1', fingerprint='b6:8a:43:51:72:af:49:88:a5:d6:c5:7f:3c:fd:91:70'),
            SSHKeyFingerprint(keylen=2048, keytype='rsa', fingerprint='ef:85:3d:e6:ab:c4:18:88:81:63:08:0f:32:8a:9d:e0')])])
def test_parse_ssh_keygen(text, keyinfo):
    assert all(a.match(b) for a, b in zip(parse_ssh_keygen(text), keyinfo))
