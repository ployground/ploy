from mr.awsome.proxy import ProxyInstance
import pytest


@pytest.fixture
def aws(awsconf):
    from mr.awsome import AWS
    import mr.awsome.plain
    import mr.awsome.tests.dummy_proxy_plugin
    awsconf.fill([''])
    aws = AWS(configpath=awsconf.directory)
    aws.plugins = {
        'dummy': mr.awsome.tests.dummy_proxy_plugin.plugin,
        'plain': mr.awsome.plain.plugin}
    aws.configfile = awsconf.path
    return aws


def test_proxy_with_default_instance_object(aws, awsconf):
    from mr.awsome.tests.dummy_plugin import Instance
    awsconf.fill([
        '[dummy-master:foo]'])
    master = aws.masters['foo']
    assert isinstance(master.instance, ProxyInstance)
    assert isinstance(master.instance.instance, Instance)


def test_proxy_instance(aws, awsconf):
    from mr.awsome.plain import Instance
    awsconf.fill([
        '[plain-instance:bar]',
        '[dummy-master:foo]',
        'instance = bar'])
    master = aws.masters['foo']
    assert isinstance(master.instance, ProxyInstance)
    assert isinstance(master.instance.instance, Instance)


def test_proxy_nonexisting_instance(aws, awsconf):
    awsconf.fill([
        '[dummy-master:foo]',
        'instance = bar'])
    master = aws.masters['foo']
    assert isinstance(master.instance, ProxyInstance)
    with pytest.raises(ValueError) as e:
        master.instance.instance
    assert e.value.args == ("The to be proxied instance 'bar' for master 'foo' wasn't found.",)


def test_proxy_config_values_passed_on(aws, awsconf):
    awsconf.fill([
        '[plain-instance:bar]',
        'ham = 1',
        '[dummy-master:foo]',
        'instance = bar'])
    bar = aws.instances['bar']
    foo = aws.instances['foo']
    proxy = aws.masters['foo'].instance
    # we have to trigger the lazy attribute
    proxied = aws.masters['foo'].instance.instance
    assert bar.config == {'ham': '1'}
    assert foo.config == {'ham': '1', 'instance': 'bar'}
    assert proxy.config == {'ham': '1', 'instance': 'bar'}
    assert proxied.config == {'ham': '1', 'instance': 'bar'}
    del proxy.config['ham']
    assert bar.config == {'ham': '1'}
    assert foo.config == {'instance': 'bar'}
    assert proxy.config == {'instance': 'bar'}
    assert proxied.config == {'instance': 'bar'}
    proxy.config['egg'] = 'spam'
    assert bar.config == {'ham': '1'}
    assert foo.config == {'egg': 'spam', 'instance': 'bar'}
    assert proxy.config == {'egg': 'spam', 'instance': 'bar'}
    assert proxied.config == {'egg': 'spam', 'instance': 'bar'}
