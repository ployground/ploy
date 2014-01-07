from StringIO import StringIO
from mr.awsome.config import Config
from unittest2 import TestCase


class ConfigTests(TestCase):
    def testEmpty(self):
        contents = StringIO("")
        config = Config(contents).parse()
        self.assertDictEqual(config, {})

    def testPlainSection(self):
        contents = StringIO("[foo]")
        config = Config(contents).parse()
        self.assertDictEqual(config, {'global': {'foo': {}}})

    def testGroupSection(self):
        contents = StringIO("[bar:foo]")
        config = Config(contents).parse()
        self.assertDictEqual(config, {'bar': {'foo': {}}})

    def testMixedSections(self):
        contents = StringIO("[bar:foo]\n[baz]")
        config = Config(contents).parse()
        self.assertDictEqual(config, {
            'bar': {'foo': {}},
            'global': {'baz': {}}})

    def testMacroExpansion(self):
        contents = StringIO("\n".join([
            "[macro]",
            "macrovalue=1",
            "[baz]",
            "<=macro",
            "bazvalue=2"]))
        config = Config(contents).parse()
        self.assertDictEqual(config, {
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
        config = Config(contents).parse()
        self.assertDictEqual(config, {
            'global': {
                'baz': {'macrovalue': '1', 'bazvalue': '2'}},
            'group': {
                'macro': {'macrovalue': '1'}}})

    def testCircularMacroExpansion(self):
        contents = StringIO("\n".join([
            "[macro]",
            "<=macro",
            "macrovalue=1"]))
        with self.assertRaises(ValueError):
            Config(contents).parse()

    def testOverrides(self):
        contents = StringIO("\n".join([
            "[section]",
            "value=1"]))
        config = Config(contents).parse()
        self.assertDictEqual(
            config,
            {'global': {'section': {'value': '1'}}})
        self.assertDictEqual(
            config.get_section_with_overrides(
                'global',
                'section',
                overrides=None),
            {
                '__name__': 'section',
                '__groupname__': 'global',
                'value': '1'})
        self.assertDictEqual(
            config.get_section_with_overrides(
                'global',
                'section',
                overrides={'value': '2'}),
            {
                '__name__': 'section',
                '__groupname__': 'global',
                'value': '2'})
        self.assertDictEqual(
            config.get_section_with_overrides(
                'global',
                'section',
                overrides={'value2': '2'}),
            {
                '__name__': 'section',
                '__groupname__': 'global',
                'value': '1',
                'value2': '2'})
        # make sure nothing is changed afterwards
        self.assertDictEqual(
            config,
            {'global': {'section': {'value': '1'}}})


class DummyPlugin(object):
    def __init__(self):
        self.massagers = []

    def get_massagers(self):
        return self.massagers


class MassagerTests(TestCase):
    def setUp(self):
        TestCase.setUp(self)
        self.dummyplugin = DummyPlugin()
        Config.plugins = dict(
            dummy=dict(
                get_massagers=self.dummyplugin.get_massagers))

    def tearDown(self):
        TestCase.tearDown(self)
        del self.dummyplugin
        Config.plugins = None

    def testBaseMassager(self):
        from mr.awsome.config import BaseMassager

        self.dummyplugin.massagers.append(BaseMassager('section', 'value'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=1"]))
        config = Config(contents).parse()
        self.assertDictEqual(config['section'], {'foo': {'value': '1'}})

    def testBooleanMassager(self):
        from mr.awsome.config import BooleanMassager

        self.dummyplugin.massagers.append(BooleanMassager('section', 'value'))
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
                "[section:foo]",
                "value=%s" % value]))
            config = Config(contents).parse()
            self.assertDictEqual(config['section'], {'foo': {'value': expected}})
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=foo"]))
        with self.assertRaises(ValueError):
            Config(contents).parse()

    def testIntegerMassager(self):
        from mr.awsome.config import IntegerMassager

        self.dummyplugin.massagers.append(IntegerMassager('section', 'value'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=1"]))
        config = Config(contents).parse()
        self.assertDictEqual(config['section'], {'foo': {'value': 1}})
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=foo"]))
        with self.assertRaises(ValueError):
            Config(contents).parse()

    def testPathMassager(self):
        from mr.awsome.config import PathMassager

        self.dummyplugin.massagers.append(PathMassager('section', 'value1'))
        self.dummyplugin.massagers.append(PathMassager('section', 'value2'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value1=foo",
            "value2=/foo"]))
        config = Config(contents, path='/config').parse()
        self.assertDictEqual(config['section'], {'foo': {
            'value1': '/config/foo',
            'value2': '/foo'}})

    def testStartupScriptMassager(self):
        from mr.awsome.config import StartupScriptMassager

        self.dummyplugin.massagers.append(StartupScriptMassager('section', 'value1'))
        self.dummyplugin.massagers.append(StartupScriptMassager('section', 'value2'))
        self.dummyplugin.massagers.append(StartupScriptMassager('section', 'value3'))
        self.dummyplugin.massagers.append(StartupScriptMassager('section', 'value4'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value1=gzip:foo",
            "value2=foo",
            "value3=gzip:/foo",
            "value4=/foo"]))
        config = Config(contents, path='/config').parse()
        self.assertDictEqual(config['section'], {'foo': {
            'value1': {'gzip': True, 'path': '/config/foo'},
            'value2': {'path': '/config/foo'},
            'value3': {'gzip': True, 'path': '/foo'},
            'value4': {'path': '/foo'}}})

    def testUserMassager(self):
        from mr.awsome.config import UserMassager
        import os, pwd

        self.dummyplugin.massagers.append(UserMassager('section', 'value1'))
        self.dummyplugin.massagers.append(UserMassager('section', 'value2'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value1=*",
            "value2=foo"]))
        config = Config(contents).parse()
        self.assertDictEqual(config['section'], {'foo': {
            'value1': pwd.getpwuid(os.getuid())[0],
            'value2': 'foo'}})

    def testCustomMassager(self):
        from mr.awsome.config import BaseMassager

        class DummyMassager(BaseMassager):
            def __call__(self, config, sectionname):
                value = config[self.sectiongroupname][sectionname][self.key]
                return int(value)

        self.dummyplugin.massagers.append(DummyMassager('section', 'value'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=1"]))
        config = Config(contents).parse()
        self.assertDictEqual(config['section'], {'foo': {'value': 1}})

    def testMassagedOverrides(self):
        from mr.awsome.config import IntegerMassager

        self.dummyplugin.massagers.append(IntegerMassager('global', 'value'))
        self.dummyplugin.massagers.append(IntegerMassager('global', 'value2'))
        contents = StringIO("\n".join([
            "[section]",
            "value=1"]))
        config = Config(contents).parse()
        self.assertDictEqual(
            config['global'],
            {'section': {'value': 1}})
        self.assertDictEqual(
            config.get_section_with_overrides(
                'global',
                'section',
                overrides=None),
            {
                '__name__': 'section',
                '__groupname__': 'global',
                'value': 1})
        self.assertDictEqual(
            config.get_section_with_overrides(
                'global',
                'section',
                overrides={'value': '2'}),
            {
                '__name__': 'section',
                '__groupname__': 'global',
                'value': 2})
        self.assertDictEqual(
            config.get_section_with_overrides(
                'global',
                'section',
                overrides={'value2': '2'}),
            {
                '__name__': 'section',
                '__groupname__': 'global',
                'value': 1,
                'value2': 2})
        # make sure nothing is changed afterwards
        self.assertDictEqual(
            config['global'],
            {'section': {'value': 1}})
