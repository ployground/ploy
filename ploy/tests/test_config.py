from __future__ import print_function
try:
    from StringIO import StringIO
except ImportError:  # pragma: nocover
    from io import StringIO
from mock import patch
from ploy.config import Config
import os
import pytest


try:
    unicode
except NameError:  # pragma: nocover
    unicode = str


class TestConfig:
    def testEmpty(self):
        contents = StringIO("")
        config = Config(contents).parse()
        assert config == {}

    def testPlainSection(self):
        contents = StringIO("[foo]")
        config = Config(contents).parse()
        assert config == {'global': {'foo': {}}}

    def testGroupSection(self):
        contents = StringIO("[bar:foo]")
        config = Config(contents).parse()
        config == {'bar': {'foo': {}}}

    def testMixedSections(self):
        contents = StringIO("[bar:foo]\n[baz]")
        config = Config(contents).parse()
        assert config == {
            'bar': {'foo': {}},
            'global': {'baz': {}}}

    def testMacroExpansion(self):
        from ploy.config import ConfigValue
        contents = StringIO("\n".join([
            "[macro]",
            "macrovalue=1",
            "[baz]",
            "<=macro",
            "bazvalue=2"]))
        config = Config(contents).parse()
        assert config == {
            'global': {
                'macro': {'macrovalue': '1'},
                'baz': {'macrovalue': '1', 'bazvalue': '2'}}}
        assert isinstance(config['global']['baz']._dict['macrovalue'], ConfigValue)
        assert isinstance(config['global']['baz']._dict['bazvalue'], ConfigValue)

    def testGroupMacroExpansion(self):
        contents = StringIO("\n".join([
            "[group:macro]",
            "macrovalue=1",
            "[baz]",
            "<=group:macro",
            "bazvalue=2"]))
        config = Config(contents).parse()
        assert config == {
            'global': {
                'baz': {'macrovalue': '1', 'bazvalue': '2'}},
            'group': {
                'macro': {'macrovalue': '1'}}}

    def testCircularMacroExpansion(self):
        contents = StringIO("\n".join([
            "[macro]",
            "<=macro",
            "macrovalue=1"]))
        with pytest.raises(ValueError):
            Config(contents).parse()

    def testMacroCleaners(self):
        dummyplugin = DummyPlugin()
        plugins = dict(
            dummy=dict(
                get_macro_cleaners=dummyplugin.get_macro_cleaners))

        def cleaner(macro):
            if 'cleanvalue' in macro:
                del macro['cleanvalue']

        dummyplugin.macro_cleaners = {'global': cleaner}
        contents = StringIO("\n".join([
            "[group:macro]",
            "macrovalue=1",
            "cleanvalue=3",
            "[baz]",
            "<=group:macro",
            "bazvalue=2"]))
        config = Config(contents, plugins=plugins).parse()
        assert config == {
            'global': {
                'baz': {'macrovalue': '1', 'bazvalue': '2'}},
            'group': {
                'macro': {'macrovalue': '1', 'cleanvalue': '3'}}}

    def testOverrides(self):
        contents = StringIO("\n".join([
            "[section]",
            "value=1"]))
        config = Config(contents).parse()
        assert config == {'global': {'section': {'value': '1'}}}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides=None)
        assert result == {
            'value': '1'}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides={'value': '2'})
        assert result == {
            'value': '2'}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides={'value2': '2'})
        assert result == {
            'value': '1',
            'value2': '2'}
        # make sure nothing is changed afterwards
        assert config == {'global': {'section': {'value': '1'}}}

    def testSpecialKeys(self):
        contents = StringIO("\n".join([
            "[section]",
            "value=1"]))
        config = Config(contents).parse()
        assert config['global']['section']['__name__'] == 'section'
        assert config['global']['section']['__groupname__'] == 'global'


class DummyPlugin(object):
    def __init__(self):
        self.macro_cleaners = {}
        self.massagers = []

    def get_macro_cleaners(self, main_config):
        return self.macro_cleaners

    def get_massagers(self):
        return self.massagers


@pytest.mark.parametrize("value, expected", [
    (True, True),
    (False, False),
    ("true", True),
    ("yes", True),
    ("on", True),
    ("false", False),
    ("no", False),
    ("off", False),
    ("foo", None)])
def test_value_asbool(value, expected):
    from ploy.config import value_asbool
    assert value_asbool(value) == expected


class TestMassagers:
    @pytest.fixture(autouse=True)
    def setup_dummyplugin(self):
        self.dummyplugin = DummyPlugin()
        self.plugins = dict(
            dummy=dict(
                get_massagers=self.dummyplugin.get_massagers))

    def testBaseMassager(self):
        from ploy.config import BaseMassager

        self.dummyplugin.massagers.append(BaseMassager('section', 'value'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=1"]))
        config = Config(contents, plugins=self.plugins).parse()
        assert config['section'] == {'foo': {'value': '1'}}

    def testBooleanMassager(self):
        from ploy.config import BooleanMassager

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
            config = Config(contents, plugins=self.plugins).parse()
            assert config['section'] == {'foo': {'value': expected}}
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=foo"]))
        config = Config(contents, plugins=self.plugins).parse()
        with pytest.raises(ValueError):
            config['section']['foo']['value']

    def testIntegerMassager(self):
        from ploy.config import IntegerMassager

        self.dummyplugin.massagers.append(IntegerMassager('section', 'value'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=1"]))
        config = Config(contents, plugins=self.plugins).parse()
        assert config['section'] == {'foo': {'value': 1}}
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=foo"]))
        config = Config(contents, plugins=self.plugins).parse()
        with pytest.raises(ValueError):
            config['section']['foo']['value']

    def testPathMassager(self):
        from ploy.config import PathMassager

        self.dummyplugin.massagers.append(PathMassager('section', 'value1'))
        self.dummyplugin.massagers.append(PathMassager('section', 'value2'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value1=foo",
            "value2=/foo"]))
        config = Config(contents, path='/config', plugins=self.plugins).parse()
        assert config['section'] == {
            'foo': {
                'value1': '/config/foo',
                'value2': '/foo'}}

    def testStartupScriptMassager(self):
        from ploy.config import StartupScriptMassager

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
        config = Config(contents, path='/config', plugins=self.plugins).parse()
        assert config['section'] == {
            'foo': {
                'value1': {'gzip': True, 'path': '/config/foo'},
                'value2': {'path': '/config/foo'},
                'value3': {'gzip': True, 'path': '/foo'},
                'value4': {'path': '/foo'}}}

    def testUserMassager(self):
        from ploy.config import UserMassager
        import pwd

        self.dummyplugin.massagers.append(UserMassager('section', 'value1'))
        self.dummyplugin.massagers.append(UserMassager('section', 'value2'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value1=*",
            "value2=foo"]))
        config = Config(contents, plugins=self.plugins).parse()
        assert config['section'] == {
            'foo': {
                'value1': pwd.getpwuid(os.getuid())[0],
                'value2': 'foo'}}

    def testCustomMassager(self):
        from ploy.config import BaseMassager

        class DummyMassager(BaseMassager):
            def __call__(self, config, sectionname):
                value = BaseMassager.__call__(self, config, sectionname)
                return int(value)

        self.dummyplugin.massagers.append(DummyMassager('section', 'value'))
        contents = StringIO("\n".join([
            "[section:foo]",
            "value=1"]))
        config = Config(contents, plugins=self.plugins).parse()
        assert config['section'] == {'foo': {'value': 1}}

    def testCustomMassagerForAnyGroup(self):
        from ploy.config import BaseMassager

        class DummyMassager(BaseMassager):
            def __call__(self, config, sectiongroupname, sectionname):
                value = BaseMassager.__call__(self, config, sectionname)
                return (sectiongroupname, value)

        self.dummyplugin.massagers.append(DummyMassager(None, 'value'))
        contents = StringIO("\n".join([
            "[section1:foo]",
            "value=1",
            "[section2:bar]",
            "value=2"]))
        config = Config(contents, plugins=self.plugins).parse()
        assert config == {
            'section1': {
                'foo': {'value': ('section1', '1')}},
            'section2': {
                'bar': {'value': ('section2', '2')}}}

    def testConflictingMassagerRegistration(self):
        from ploy.config import BooleanMassager, IntegerMassager

        config = Config(StringIO('')).parse()
        config.add_massager(BooleanMassager('section', 'value'))
        with pytest.raises(ValueError) as e:
            config.add_massager(IntegerMassager('section', 'value'))
        assert unicode(e.value) == "Massager for option 'value' in section group 'section' already registered."

    def testMassagedOverrides(self):
        from ploy.config import IntegerMassager

        self.dummyplugin.massagers.append(IntegerMassager('global', 'value'))
        self.dummyplugin.massagers.append(IntegerMassager('global', 'value2'))
        contents = StringIO("\n".join([
            "[section]",
            "value=1"]))
        config = Config(contents, plugins=self.plugins).parse()
        assert config['global'] == {'section': {'value': 1}}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides=None)
        assert result == {
            'value': 1}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides={'value': '2'})
        assert result == {
            'value': 2}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides={'value2': '2'})
        assert result == {
            'value': 1,
            'value2': 2}
        # make sure nothing is changed afterwards
        assert config['global'] == {'section': {'value': 1}}

    def testSectionMassagedOverrides(self):
        from ploy.config import IntegerMassager

        contents = StringIO("\n".join([
            "[section]",
            "value=1"]))
        config = Config(contents, plugins=self.plugins).parse()
        config['global']['section'].add_massager(IntegerMassager('global', 'value'))
        config['global']['section'].add_massager(IntegerMassager('global', 'value2'))
        assert config['global'] == {'section': {'value': 1}}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides=None)
        assert result == {
            'value': 1}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides={'value': '2'})
        assert result == {
            'value': 2}
        result = config.get_section_with_overrides(
            'global',
            'section',
            overrides={'value2': '2'})
        assert result == {
            'value': 1,
            'value2': 2}
        # make sure nothing is changed afterwards
        assert config['global'] == {'section': {'value': 1}}


def _make_config(massagers):
    return Config(StringIO("\n".join([
        "[section1]",
        "massagers = %s" % massagers,
        "value = 1",
        "[section2]",
        "value = 2",
        "[foo:bar]",
        "value = 3"]))).parse()


def _expected(first, second, third):
    return {
        'global': {
            'section1': {
                'value': first('1')},
            'section2': {
                'value': second('2')}},
        'foo': {
            'bar': {
                'value': third('3')}}}


@pytest.mark.parametrize("description, massagers, expected", [
    (
        'empty',
        '', (str, str, str)),
    (
        'current section',
        'value=ploy.config.IntegerMassager', (int, str, str)),
    (
        'current section alternate',
        '::value=ploy.config.IntegerMassager', (int, str, str)),
    (
        'different section',
        ':section2:value = ploy.config.IntegerMassager', (str, int, str)),
    (
        'different section alternate',
        'global:section2:value = ploy.config.IntegerMassager', (str, int, str)),
    (
        'multiple massagers',
        'value = ploy.config.IntegerMassager\n    :section2:value = ploy.config.IntegerMassager', (int, int, str)),
    (
        'for section group',
        'global:value = ploy.config.IntegerMassager', (int, int, str)),
    (
        'for everything',
        '*:value = ploy.config.IntegerMassager', (int, int, int))])
def test_valid_massagers_specs_in_config(description, massagers, expected):
    config = _make_config(massagers)
    expected = _expected(*expected)
    print("Description of failed test:\n    %s\n" % description)
    assert dict(config) == expected


class TestMassagersFromConfig:
    def testInvalid(self):
        contents = StringIO("\n".join([
            "[section]",
            "massagers = foo",
            "value = 1"]))
        with patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert LogMock.error.call_args_list == [
            (("Invalid massager spec '%s' in section '%s:%s'.", 'foo', 'global', 'section'), {})]

    def testTooManyColonsInSpec(self):
        contents = StringIO("\n".join([
            "[section]",
            "massagers = :::foo=ploy.config.IntegerMassager",
            "value = 1"]))
        with patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert LogMock.error.call_args_list == [
            (("Invalid massager spec '%s' in section '%s:%s'.", ':::foo=ploy.config.IntegerMassager', 'global', 'section'), {})]

    def testUnknownModuleFor(self):
        contents = StringIO("\n".join([
            "[section]",
            "massagers = foo=bar",
            "value = 1"]))
        with patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert len(LogMock.error.call_args_list) == 1
        assert LogMock.error.call_args_list[0][0][0] == "Can't import massager from '%s'.\n%s"
        assert LogMock.error.call_args_list[0][0][1] == 'bar'
        assert LogMock.error.call_args_list[0][0][2].startswith('No module named')
        assert 'bar' in LogMock.error.call_args_list[0][0][2]

    def testUnknownAttributeFor(self):
        contents = StringIO("\n".join([
            "[section]",
            "massagers = foo=ploy.foobar",
            "value = 1"]))
        with patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert LogMock.error.call_args_list == [
            (("Can't import massager from '%s'.\n%s", 'ploy.foobar', "'module' object has no attribute 'foobar'"), {})]


class TestConfigExtend:
    @pytest.fixture(autouse=True)
    def setup_tempdir(self, tempdir):
        self.tempdir = tempdir
        self.directory = tempdir.directory

    def _write_config(self, conf, content):
        self.tempdir[conf].fill(content)

    def testExtend(self):
        ployconf = 'ploy.conf'
        self._write_config(
            ployconf,
            '\n'.join([
                '[global]',
                'extends = foo.conf',
                'ham = egg']))
        self._write_config(
            'foo.conf',
            '\n'.join([
                '[global]',
                'foo = bar',
                'ham = pork']))
        config = Config(os.path.join(self.directory, ployconf)).parse()
        assert config == {
            'global': {
                'global': {
                    'foo': 'bar', 'ham': 'egg'}}}

    def testDoubleExtend(self):
        ployconf = 'ploy.conf'
        self._write_config(
            ployconf,
            '\n'.join([
                '[global]',
                'extends = foo.conf',
                'ham = egg']))
        self._write_config(
            'foo.conf',
            '\n'.join([
                '[global]',
                'extends = bar.conf',
                'foo = blubber',
                'ham = pork']))
        self._write_config(
            'bar.conf',
            '\n'.join([
                '[global]',
                'foo = bar',
                'ham = pork']))
        config = Config(os.path.join(self.directory, ployconf)).parse()
        assert config == {
            'global': {
                'global': {
                    'foo': 'blubber', 'ham': 'egg'}}}

    def testExtendFromDifferentDirectoryWithMassager(self):
        from ploy.config import PathMassager
        os.mkdir(os.path.join(self.directory, 'bar'))
        ployconf = 'ploy.conf'
        self._write_config(
            ployconf,
            '\n'.join([
                '[global]',
                'extends = bar/foo.conf',
                'ham = egg']))
        self._write_config(
            'bar/foo.conf',
            '\n'.join([
                '[global]',
                'foo = blubber',
                'ham = pork']))
        config = Config(os.path.join(self.directory, ployconf)).parse()
        config.add_massager(PathMassager('global', 'foo'))
        config.add_massager(PathMassager('global', 'ham'))
        assert config == {
            'global': {
                'global': {
                    'foo': os.path.join(self.directory, 'bar', 'blubber'),
                    'ham': os.path.join(self.directory, 'egg')}}}

    def testExtendFromMissingFile(self):
        ployconf = 'ploy.conf'
        self._write_config(
            ployconf,
            '\n'.join([
                '[global:global]',
                'extends = foo.conf',
                'ham = egg']))
        with patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(os.path.join(self.directory, ployconf)).parse()
        assert LogMock.error.call_args_list == [
            (("Config file '%s' doesn't exist.", os.path.join(self.directory, 'foo.conf')), {})]
