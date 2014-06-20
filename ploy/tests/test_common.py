from StringIO import StringIO
from mock import patch
from ploy.common import InstanceHooks, BaseInstance, StartupScriptMixin
from ploy.config import Config, StartupScriptMassager
from unittest2 import TestCase
import os
import pytest


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


class StartupScriptTests(TestCase):
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
        self.assertMultiLineEqual(result, "")

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
        self.assertMultiLineEqual(result, "")

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
        assert result[:48] == "\n".join([
            "#!/bin/sh",
            "tail -n+4 $0 | gunzip -c | sh",
            "exit $?",
            ""])
        payload = result[48:]
        header = payload[:10]
        body = payload[10:]
        self.assertEqual(header[:4], "\x1f\x8b\x08\x00")  # magic + compression + flags
        self.assertEqual(header[8:], "\x02\xff")  # extra flags + os
        self.assertEqual(body, "\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00")

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
        self.assertMultiLineEqual(result, "")

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

    def raw_input_result(q):
        assert q == question
        a = raw_input_values.pop()
        print q, repr(a)
        return a

    with patch('__builtin__.raw_input') as RawInput:
        RawInput.side_effect = raw_input_result
        try:
            assert yesno('Foo', default, all) == expected
        except Exception as e:
            assert type(e) == expected
