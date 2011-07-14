from StringIO import StringIO
from mock import patch
from mr.awsome.common import StartupScriptMixin
from mr.awsome.config import Config, StartupScriptMassager
from unittest2 import TestCase
import os
import shutil
import tempfile


class MockMaster(object):
    def __init__(self, main_config):
        self.main_config = main_config


class MockInstance(StartupScriptMixin):
    sectiongroupname = "instance"

    def __init__(self):
        self.id = "foo"


class StartupScriptTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory)
        del self.directory

    def _create_config(self, contents, path=None):
        contents = StringIO(contents)
        config = Config(contents, path=path)
        config._add_massager(
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
        with patch('mr.awsome.common.log') as CommonLogMock:
            with self.assertRaises(SystemExit) as exc:
                instance.startup_script()
        CommonLogMock.error.assert_called_with(
            "Startup script '%s' not found.",
            os.path.join(self.directory, 'foo'))

    def testEmptyStartupScript(self):
        with open(os.path.join(self.directory, 'foo'), 'w') as f:
            f.write("")
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
        with open(os.path.join(self.directory, 'foo'), 'w') as f:
            f.write("")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = gzip:foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        result = instance.startup_script()
        self.assertMultiLineEqual(result[:52], "\n".join([
            "#!/bin/bash",
            "tail -n+4 $0 | gunzip -c | bash",
            "exit $?",
            ""]))
        payload = result[52:]
        header = payload[:10]
        body = payload[10:]
        self.assertEqual(header[:4], "\x1f\x8b\x08\x00") # magic + compression + flags
        self.assertEqual(header[8:], "\x02\xff") # extra flags + os
        self.assertEqual(body, "\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00")

    def testMaxSizeOk(self):
        with open(os.path.join(self.directory, 'foo'), 'w') as f:
            f.write("")
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
        with open(os.path.join(self.directory, 'foo'), 'w') as f:
            f.write("aaaaabbbbbccccc")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        instance.max_startup_script_size = 10
        with patch('mr.awsome.common.log') as LogMock:
            with self.assertRaises(SystemExit):
                instance.startup_script()
            LogMock.error.assert_called_with('Startup script too big (%s > %s).', 15, 10)

    def testMaxSizeExceededDebug(self):
        with open(os.path.join(self.directory, 'foo'), 'w') as f:
            f.write("aaaaabbbbbccccc")
        instance = MockInstance()
        config = self._create_config(
            "\n".join([
                "[instance:foo]",
                "startup_script = foo"]),
            path=self.directory)
        instance.master = MockMaster(config)
        instance.max_startup_script_size = 10
        with patch('mr.awsome.common.log') as LogMock:
            instance.startup_script(debug=True)
            LogMock.error.assert_called_with('Startup script too big (%s > %s).', 15, 10)
