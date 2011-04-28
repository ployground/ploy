from StringIO import StringIO
from mr.awsome.config import Config
from unittest import TestCase


dummyplugin = None


class ConfigTests(TestCase):
    def testEmpty(self):
        contents = StringIO("")
        config = Config(contents)
        self.assertEqual(config, {})

    def testPlainSection(self):
        contents = StringIO("[foo]")
        config = Config(contents)
        self.assertEqual(config, {'global': {'foo': {}}})

    def testGroupSection(self):
        contents = StringIO("[bar:foo]")
        config = Config(contents)
        self.assertEqual(config, {'bar': {'foo': {}}})

    def testMixedSections(self):
        contents = StringIO("[bar:foo]\n[baz]")
        config = Config(contents)
        self.assertEqual(config, {
            'bar': {'foo': {}},
            'global': {'baz': {}}})

    def testMacroExpansion(self):
        contents = StringIO("\n".join([
            "[macro]",
            "macrovalue=1",
            "[baz]",
            "<=macro",
            "bazvalue=2"]))
        config = Config(contents)
        self.assertEqual(config, {
            'global': {
                'macro': {'macrovalue': '1'},
                'baz': {'macrovalue': '1', 'bazvalue': '2'}}})

    def testGroupMacroExpansion(self):
        contents = StringIO("\n".join([
            "[group:macro]",
            "macrovalue=1",
            "[baz]",
            "<=group:macro",
            "bazvalue=2"]))
        config = Config(contents)
        self.assertEqual(config, {
            'global': {
                'baz': {'macrovalue': '1', 'bazvalue': '2'}},
            'group': {
                'macro': {'macrovalue': '1'}}})

    def testCircularMacroExpansion(self):
        contents = StringIO("\n".join([
            "[macro]",
            "<=macro",
            "macrovalue=1"]))
        self.assertRaises(ValueError, Config, contents)

    def testDefaultPlugins(self):
        from mr.awsome import ec2, plain
        contents = StringIO("")
        config = Config(contents, bbb_config=True)
        self.assertEquals(config, {
            'plugin': {
                'ec2': {
                    'module': ec2},
                'plain': {
                    'module': plain}},
            'plain-master': {
                'default': {}}})


class DummyPlugin(object):
    def __init__(self):
        self.massagers = []

    def get_massagers(self):
        return self.massagers


class MassagerTests(TestCase):
    def setUp(self):
        TestCase.setUp(self)
        global dummyplugin
        dummyplugin = DummyPlugin()
        self.plugin_config = "[plugin:dummy]\nmodule=mr.awsome.tests.test_config.dummyplugin"

    def tearDown(self):
        TestCase.tearDown(self)
        global dummyplugin
        dummyplugin = None

    def testBaseMassager(self):
        from mr.awsome.config import BaseMassager

        dummyplugin.massagers.append(BaseMassager('section', 'value'))
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value=1"]))
        config = Config(contents)
        self.assertEquals(config['section'], {'foo': {'value': '1'}})

    def testBooleanMassager(self):
        from mr.awsome.config import BooleanMassager

        dummyplugin.massagers.append(BooleanMassager('section', 'value'))
        test_values = (
            ('true', True),
            ('True', True),
            ('yes', True),
            ('Yes', True),
            ('on', True),
            ('On', True),
            ('false', False),
            ('False', False),
            ('no', False),
            ('No', False),
            ('off', False),
            ('Off', False))
        for value, expected in test_values:
            contents = StringIO("\n".join([
                self.plugin_config,
                "[section:foo]",
                "value=%s" % value]))
            config = Config(contents)
            self.assertEquals(config['section'], {'foo': {'value': expected}})
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value=foo"]))
        self.assertRaises(ValueError, Config, contents)

    def testIntegerMassager(self):
        from mr.awsome.config import IntegerMassager

        dummyplugin.massagers.append(IntegerMassager('section', 'value'))
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value=1"]))
        config = Config(contents)
        self.assertEquals(config['section'], {'foo': {'value': 1}})
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value=foo"]))
        self.assertRaises(ValueError, Config, contents)

    def testPathMassager(self):
        from mr.awsome.config import PathMassager

        dummyplugin.massagers.append(PathMassager('section', 'value1'))
        dummyplugin.massagers.append(PathMassager('section', 'value2'))
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value1=foo",
            "value2=/foo"]))
        config = Config(contents, path='/config')
        self.assertEquals(config['section'], {'foo': {
            'value1': '/config/foo',
            'value2': '/foo'}})

    def testStartupScriptMassager(self):
        from mr.awsome.config import StartupScriptMassager

        dummyplugin.massagers.append(StartupScriptMassager('section', 'value1'))
        dummyplugin.massagers.append(StartupScriptMassager('section', 'value2'))
        dummyplugin.massagers.append(StartupScriptMassager('section', 'value3'))
        dummyplugin.massagers.append(StartupScriptMassager('section', 'value4'))
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value1=gzip:foo",
            "value2=foo",
            "value3=gzip:/foo",
            "value4=/foo"]))
        config = Config(contents, path='/config')
        self.assertEquals(config['section'], {'foo': {
            'value1': {'gzip': True, 'path': '/config/foo'},
            'value2': {'path': '/config/foo'},
            'value3': {'gzip': True, 'path': '/foo'},
            'value4': {'path': '/foo'}}})

    def testUserMassager(self):
        from mr.awsome.config import UserMassager
        import os, pwd

        dummyplugin.massagers.append(UserMassager('section', 'value1'))
        dummyplugin.massagers.append(UserMassager('section', 'value2'))
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value1=*",
            "value2=foo"]))
        config = Config(contents)
        self.assertEquals(config['section'], {'foo': {
            'value1': pwd.getpwuid(os.getuid())[0],
            'value2': 'foo'}})

    def testCustomMassager(self):
        from mr.awsome.config import BaseMassager

        class DummyMassager(BaseMassager):
            def __call__(self, config, sectionname):
                value = config[self.sectiongroupname][sectionname][self.key]
                return int(value)

        dummyplugin.massagers.append(DummyMassager('section', 'value'))
        contents = StringIO("\n".join([
            self.plugin_config,
            "[section:foo]",
            "value=1"]))
        config = Config(contents)
        self.assertEquals(config['section'], {'foo': {'value': 1}})
