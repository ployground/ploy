from StringIO import StringIO
from mr.awsome.config import Config
from unittest import TestCase


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
