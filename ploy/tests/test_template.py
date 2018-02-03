from __future__ import unicode_literals
from ploy.template import Template
import base64
import pytest


class TestTemplate:
    @pytest.fixture
    def template(self, tempdir):
        return tempdir['template.txt']

    def testEmpty(self, template):
        template.fill("")
        template = Template(template.path)
        result = template()
        assert result == ""

    def testPreFilter(self, template):
        template.fill("\n".join(str(x) for x in range(3)))
        template = Template(template.path, pre_filter=lambda x: x.replace("1\n", ""))
        result = template()
        assert result == "0\n2"

    def testPostFilter(self, template):
        template.fill("\n".join(str(x) for x in range(3)))
        template = Template(template.path, post_filter=lambda x: x.replace("1\n", ""))
        result = template()
        assert result == "0\n2"

    def testKeywordOption(self, template):
        template.fill("{option}")
        template = Template(template.path)
        result = template(option="foo")
        assert result == "foo"

    def testBase64Option(self, template):
        template.fill("option: base64 1\n\n{option}")
        template = Template(template.path)
        result = template()
        assert result == "MQ==\n"
        assert base64.decodestring(result.encode('ascii')) == b"1"

    def testEscapeEolOption(self, tempdir, template):
        template.fill("option: file,escape_eol test.txt\n\n{option}")
        template = Template(template.path)
        tempdir['test.txt'].fill("1\n2\n")
        result = template()
        assert result == "1\\n2\\n"

    def testFileOption(self, tempdir, template):
        template.fill("option: file test.txt\n\n{option}")
        template = Template(template.path)
        tempdir['test.txt'].fill("1")
        result = template()
        assert result == "1"

    def testFormatOption(self, template):
        template.fill("option: format {foo}\n\n{option}")
        template = Template(template.path)
        result = template(foo=1)
        assert result == "1"

    def testGzipOption(self, template):
        template.fill("option: gzip,base64 1\n\n{option}")
        template = Template(template.path)
        result = template()
        payload = base64.decodestring(result.encode('ascii'))
        header = payload[:10]
        body = payload[10:]
        assert header[:4] == b"\x1f\x8b\x08\x00"  # magic + compression + flags
        assert header[8:] == b"\x02\xff"  # extra flags + os
        assert body == b"3\x04\x00\xb7\xef\xdc\x83\x01\x00\x00\x00"

    def testTemplateOption(self, tempdir, template):
        template.fill("template: template test.txt\n\n{template}")
        template = Template(template.path)
        tempdir['test.txt'].fill("option: format 1\n\n{option}")
        result = template()
        assert result == "1"

    def testUnkownOption(self, template):
        template.fill("option: foo 1\n\n{option}")
        template = Template(template.path)
        with pytest.raises(ValueError):
            template()
