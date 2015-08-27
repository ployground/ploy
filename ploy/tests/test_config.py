from __future__ import print_function, unicode_literals
from ploy.config import Config
import os
import pytest


@pytest.fixture
def make_parsed_config(make_file_io):

    def make_parsed_config(content, path=None, plugins=None):
        return Config(
            make_file_io(content),
            path=path,
            plugins=plugins).parse()

    return make_parsed_config


class TestConfig:
    def testEmpty(self, make_parsed_config):
        config = make_parsed_config(u"")
        assert config == {}

    def testPlainSection(self, make_parsed_config):
        config = make_parsed_config(u"[foo]")
        assert config == {'global': {'foo': {}}}

    def testGroupSection(self, make_parsed_config):
        config = make_parsed_config(u"[bar:foo]")
        config == {'bar': {'foo': {}}}

    def testMixedSections(self, make_parsed_config):
        config = make_parsed_config(u"""
            [bar:foo]
            [baz]""")
        assert config == {
            'bar': {'foo': {}},
            'global': {'baz': {}}}

    def testMacroExpansion(self, make_parsed_config):
        from ploy.config import ConfigValue
        config = make_parsed_config(u"""
            [macro]
            macrovalue=1
            [baz]
            <=macro
            bazvalue=2""")
        assert config == {
            'global': {
                'macro': {'macrovalue': '1'},
                'baz': {'macrovalue': '1', 'bazvalue': '2'}}}
        assert isinstance(config['global']['baz']._dict['macrovalue'], ConfigValue)
        assert isinstance(config['global']['baz']._dict['bazvalue'], ConfigValue)

    def testGroupMacroExpansion(self, make_parsed_config):
        config = make_parsed_config(u"""
            [group:macro]
            macrovalue=1
            [baz]
            <=group:macro
            bazvalue=2""")
        assert config == {
            'global': {
                'baz': {'macrovalue': '1', 'bazvalue': '2'}},
            'group': {
                'macro': {'macrovalue': '1'}}}

    def testCircularMacroExpansion(self, make_file_io):
        contents = make_file_io(u"""
            [macro]
            <=macro
            macrovalue=1""")
        with pytest.raises(ValueError):
            Config(contents).parse()

    def testMacroCleaners(self, make_parsed_config):
        dummyplugin = DummyPlugin()
        plugins = dict(
            dummy=dict(
                get_macro_cleaners=dummyplugin.get_macro_cleaners))

        def cleaner(macro):
            if 'cleanvalue' in macro:
                del macro['cleanvalue']

        dummyplugin.macro_cleaners = {'global': cleaner}
        config = make_parsed_config(
            u"""
                [group:macro]
                macrovalue=1
                cleanvalue=3
                [baz]
                <=group:macro
                bazvalue=2""",
            plugins=plugins)
        assert config == {
            'global': {
                'baz': {'macrovalue': '1', 'bazvalue': '2'}},
            'group': {
                'macro': {'macrovalue': '1', 'cleanvalue': '3'}}}

    def testOverrides(self, make_parsed_config):
        config = make_parsed_config(u"""
            [section]
            value=1""")
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

    def testSpecialKeys(self, make_parsed_config):
        config = make_parsed_config(u"""
            [section]
            value=1""")
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
    @pytest.fixture
    def plugin(self):
        return DummyPlugin()

    @pytest.fixture
    def make_parsed_config_plugins(self, make_parsed_config, plugin):
        from functools import partial
        plugins = dict(
            dummy=dict(
                get_massagers=plugin.get_massagers))
        return partial(make_parsed_config, plugins=plugins)

    def testBaseMassager(self, make_parsed_config_plugins, plugin):
        from ploy.config import BaseMassager

        plugin.massagers.append(BaseMassager('section', 'value'))
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value=1""")
        assert config['section'] == {'foo': {'value': '1'}}

    def testBooleanMassager(self, make_parsed_config_plugins, plugin):
        from ploy.config import BooleanMassager

        plugin.massagers.append(BooleanMassager('section', 'value'))
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
            config = make_parsed_config_plugins(
                u"""
                    [section:foo]
                    value=%s""" % value)
            assert config['section'] == {'foo': {'value': expected}}
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value=foo""")
        with pytest.raises(ValueError):
            config['section']['foo']['value']

    def testIntegerMassager(self, make_parsed_config_plugins, plugin):
        from ploy.config import IntegerMassager

        plugin.massagers.append(IntegerMassager('section', 'value'))
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value=1""")
        assert config['section'] == {'foo': {'value': 1}}
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value=foo""")
        with pytest.raises(ValueError):
            config['section']['foo']['value']

    def testPathMassager(self, make_parsed_config_plugins, plugin):
        from ploy.config import PathMassager

        plugin.massagers.append(PathMassager('section', 'value1'))
        plugin.massagers.append(PathMassager('section', 'value2'))
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value1=foo
                value2=/foo""",
            path='/config')
        assert config['section'] == {
            'foo': {
                'value1': '/config/foo',
                'value2': '/foo'}}

    def testStartupScriptMassager(self, make_parsed_config_plugins, plugin):
        from ploy.config import StartupScriptMassager

        plugin.massagers.append(StartupScriptMassager('section', 'value1'))
        plugin.massagers.append(StartupScriptMassager('section', 'value2'))
        plugin.massagers.append(StartupScriptMassager('section', 'value3'))
        plugin.massagers.append(StartupScriptMassager('section', 'value4'))
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value1=gzip:foo
                value2=foo
                value3=gzip:/foo
                value4=/foo""",
            path='/config')
        assert config['section'] == {
            'foo': {
                'value1': {'gzip': True, 'path': '/config/foo'},
                'value2': {'path': '/config/foo'},
                'value3': {'gzip': True, 'path': '/foo'},
                'value4': {'path': '/foo'}}}

    def testUserMassager(self, make_parsed_config_plugins, plugin):
        from ploy.config import UserMassager
        import pwd

        plugin.massagers.append(UserMassager('section', 'value1'))
        plugin.massagers.append(UserMassager('section', 'value2'))
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value1=*
                value2=foo""")
        assert config['section'] == {
            'foo': {
                'value1': pwd.getpwuid(os.getuid())[0],
                'value2': 'foo'}}

    def testCustomMassager(self, make_parsed_config_plugins, plugin):
        from ploy.config import BaseMassager

        class DummyMassager(BaseMassager):
            def __call__(self, config, sectionname):
                value = BaseMassager.__call__(self, config, sectionname)
                return int(value)

        plugin.massagers.append(DummyMassager('section', 'value'))
        config = make_parsed_config_plugins(
            u"""
                [section:foo]
                value=1""")
        assert config['section'] == {'foo': {'value': 1}}

    def testCustomMassagerForAnyGroup(self, make_parsed_config_plugins, plugin):
        from ploy.config import BaseMassager

        class DummyMassager(BaseMassager):
            def __call__(self, config, sectiongroupname, sectionname):
                value = BaseMassager.__call__(self, config, sectionname)
                return (sectiongroupname, value)

        plugin.massagers.append(DummyMassager(None, 'value'))
        config = make_parsed_config_plugins(
            u"""
                [section1:foo]
                value=1
                [section2:bar]
                value=2""")
        assert config == {
            'section1': {
                'foo': {'value': ('section1', '1')}},
            'section2': {
                'bar': {'value': ('section2', '2')}}}

    def testConflictingMassagerRegistration(self, make_parsed_config):
        from ploy.config import BooleanMassager, IntegerMassager

        config = make_parsed_config(u"")
        config.add_massager(BooleanMassager('section', 'value'))
        with pytest.raises(ValueError) as e:
            config.add_massager(IntegerMassager('section', 'value'))
        assert str(e.value) == "Massager for option 'value' in section group 'section' already registered."

    def testMassagedOverrides(self, make_parsed_config_plugins, plugin):
        from ploy.config import IntegerMassager

        plugin.massagers.append(IntegerMassager('global', 'value'))
        plugin.massagers.append(IntegerMassager('global', 'value2'))
        config = make_parsed_config_plugins(
            u"""
                [section]
                value=1""").parse()
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

    def testSectionMassagedOverrides(self, make_parsed_config_plugins, plugin):
        from ploy.config import IntegerMassager

        config = make_parsed_config_plugins(
            u"""
                [section]
                value=1""")
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
def test_valid_massagers_specs_in_config(description, make_parsed_config, massagers, expected):
    config = make_parsed_config([
        "[section1]",
        "massagers = %s" % massagers,
        "value = 1",
        "[section2]",
        "value = 2",
        "[foo:bar]",
        "value = 3"])
    print("Description of failed test:\n    %s\n" % description)
    assert dict(config) == {
        'global': {
            'section1': {
                'value': expected[0]('1')},
            'section2': {
                'value': expected[1]('2')}},
        'foo': {
            'bar': {
                'value': expected[2]('3')}}}


class TestMassagersFromConfig:
    def testInvalid(self, make_file_io, mock):
        contents = make_file_io(u"""
            [section]
            massagers = foo
            value = 1""")
        with mock.patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert LogMock.error.call_args_list == [
            (("Invalid massager spec '%s' in section '%s:%s'.", 'foo', 'global', 'section'), {})]

    def testTooManyColonsInSpec(self, make_file_io, mock):
        contents = make_file_io(u"""
            [section]
            massagers = :::foo=ploy.config.IntegerMassager
            value = 1""")
        with mock.patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert LogMock.error.call_args_list == [
            (("Invalid massager spec '%s' in section '%s:%s'.", ':::foo=ploy.config.IntegerMassager', 'global', 'section'), {})]

    def testUnknownModuleFor(self, make_file_io, mock):
        contents = make_file_io(u"""
            [section]
            massagers = foo=bar
            value = 1""")
        with mock.patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert len(LogMock.error.call_args_list) == 1
        assert LogMock.error.call_args_list[0][0][0] == "Can't import massager from '%s'.\n%s"
        assert LogMock.error.call_args_list[0][0][1] == 'bar'
        assert LogMock.error.call_args_list[0][0][2].startswith('No module named')
        assert 'bar' in LogMock.error.call_args_list[0][0][2]

    def testUnknownAttributeFor(self, make_file_io, mock):
        contents = make_file_io(u"""
            [section]
            massagers = foo=ploy.foobar
            value = 1""")
        with mock.patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(contents).parse()
        assert len(LogMock.error.call_args_list) == 1
        assert len(LogMock.error.call_args_list[0][0]) == 3
        assert LogMock.error.call_args_list[0][0][0] == "Can't import massager from '%s'.\n%s"
        assert LogMock.error.call_args_list[0][0][1] == 'ploy.foobar'
        assert LogMock.error.call_args_list[0][0][2].endswith("has no attribute 'foobar'")
        assert LogMock.error.call_args_list[0][1] == {}


class TestConfigExtend:
    def testExtend(self, confmaker):
        ployconf = confmaker('ploy.conf')
        ployconf.fill(
            '\n'.join([
                '[global]',
                'extends = foo.conf',
                'ham = egg']))
        confmaker('foo.conf').fill(
            '\n'.join([
                '[global]',
                'foo = bar',
                'ham = pork']))
        config = Config(ployconf.path).parse()
        assert config == {
            'global': {
                'global': {
                    'foo': 'bar', 'ham': 'egg'}}}

    def testCircularExtend(self, confext, confmaker, mock):
        ployconf = confmaker('ploy.conf')
        ployconf.fill(
            '\n'.join([
                '[global]',
                'extends = foo.conf',
                'ham = egg']))
        confmaker('foo.conf').fill(
            '\n'.join([
                '[global]',
                'extends = foo.conf',
                'ham = pork']))
        with mock.patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(ployconf.path).parse()
        path = os.path.join(ployconf.directory, 'foo.conf')
        path = path.replace('.conf', confext)
        assert LogMock.error.call_args_list == [
            (("Circular config file extension on '%s'.", path), {})]

    def testDoubleExtend(self, confmaker):
        ployconf = confmaker('ploy.conf')
        ployconf.fill(
            '\n'.join([
                '[global]',
                'extends = foo.conf',
                'ham = egg']))
        confmaker('foo.conf').fill(
            '\n'.join([
                '[global]',
                'extends = bar.conf',
                'foo = blubber',
                'ham = pork']))
        confmaker('bar.conf').fill(
            '\n'.join([
                '[global]',
                'foo = bar',
                'ham = pork']))
        config = Config(ployconf.path).parse()
        assert config == {
            'global': {
                'global': {
                    'foo': 'blubber', 'ham': 'egg'}}}

    def testExtendFromDifferentDirectoryWithMassager(self, confmaker):
        from ploy.config import PathMassager
        ployconf = confmaker('ploy.conf')
        os.mkdir(os.path.join(ployconf.directory, 'bar'))
        ployconf.fill(
            '\n'.join([
                '[global]',
                'extends = bar/foo.conf',
                'ham = egg']))
        confmaker('bar/foo.conf').fill(
            '\n'.join([
                '[global]',
                'foo = blubber',
                'ham = pork']))
        config = Config(ployconf.path).parse()
        config.add_massager(PathMassager('global', 'foo'))
        config.add_massager(PathMassager('global', 'ham'))
        assert config == {
            'global': {
                'global': {
                    'foo': os.path.join(ployconf.directory, 'bar', 'blubber'),
                    'ham': os.path.join(ployconf.directory, 'egg')}}}

    def testExtendFromMissingFile(self, confext, confmaker, mock):
        ployconf = confmaker('ploy.conf')
        ployconf.fill(
            '\n'.join([
                '[global:global]',
                'extends = foo.conf',
                'ham = egg']))
        with mock.patch('ploy.config.log') as LogMock:
            with pytest.raises(SystemExit):
                Config(ployconf.path).parse()
        path = os.path.join(ployconf.directory, 'foo.conf')
        path = path.replace('.conf', confext)
        assert LogMock.error.call_args_list == [
            (("Config file '%s' doesn't exist.", path), {})]


class TestYAMLConversion:
    @pytest.fixture
    def make_config_obj(self, tempdir):

        def make_config_obj(content, name='ploy.conf'):
            tempdir[name].fill(content, allow_conf=True)
            config = Config(tempdir[name].path)
            config.parse()
            return config

        return make_config_obj

    def testEmpty(self, make_config_obj, tempdir, yaml_dumper):
        config = make_config_obj(u"")
        config._dump_yaml(yaml_dumper)
        assert yaml_dumper.output == {}

    def testEmptySection(self, make_file_content, make_config_obj, tempdir, yaml_dumper):
        config = make_config_obj(u"[instance:foo]")
        config._dump_yaml(yaml_dumper)
        assert yaml_dumper.output == {
            'ploy.yml': make_file_content(u"""\
                instance:
                    foo: {}
                """)}

    def testComments(self, make_file_content, make_config_obj, tempdir, yaml_dumper):
        config = make_config_obj(u"""\
            # starting comment
            REM a comment

            [global]

            # macros

            [macros:bar]

            # instances

            # foo

            [instance:foo]
            #section comment
            ham1 = bar1; not an option comment
            ham2 = bar2# not an option comment
            ham3 = bar3 # not an option comment
            ham = bar ; option comment
            remark = not a comment

            # bar

            [instance:bar]
            ham = foo

            ; ending comment
            rem another comment
            """)
        config._dump_yaml(yaml_dumper)
        assert list(yaml_dumper.output.keys()) == ['ploy.yml']
        assert yaml_dumper.output['ploy.yml'] == make_file_content(u"""\
            global:
                # starting comment
                # a comment
                global: {}
            macros:
                # macros
                bar: {}
            instance:
                # instances
                # foo
                foo:
                    #section comment
                    ham1: bar1; not an option comment
                    ham2: bar2# not an option comment
                    ham3: 'bar3 # not an option comment'
                    ham: bar  # option comment
                    remark: not a comment
                # bar
                bar:
                    ham: foo
            # ending comment
            # another comment
            """)
