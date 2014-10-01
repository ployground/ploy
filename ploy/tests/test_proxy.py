from mock import call, Mock
from ploy.proxy import ProxyInstance
import pytest


@pytest.fixture
def ctrl(ployconf):
    from ploy import Controller
    import ploy.plain
    import ploy.tests.dummy_proxy_plugin
    ployconf.fill([''])
    ctrl = Controller(configpath=ployconf.directory)
    ctrl.plugins = {
        'dummy': ploy.tests.dummy_proxy_plugin.plugin,
        'plain': ploy.plain.plugin}
    ctrl.configfile = ployconf.path
    return ctrl


def test_proxy_with_default_instance_object(ctrl, ployconf):
    from ploy.tests.dummy_plugin import Instance
    ployconf.fill([
        '[dummy-master:foo]'])
    master = ctrl.masters['foo']
    assert isinstance(master.instance, ProxyInstance)
    assert isinstance(master.instance._proxied_instance, Instance)


def test_proxy_instance(ctrl, ployconf):
    from ploy.plain import Instance
    ployconf.fill([
        '[plain-instance:bar]',
        '[dummy-master:foo]',
        'instance = bar'])
    master = ctrl.masters['foo']
    assert isinstance(master.instance, ProxyInstance)
    assert isinstance(master.instance._proxied_instance, Instance)


def test_proxy_nonexisting_instance(capsys, ctrl, monkeypatch, ployconf):
    ployconf.fill([
        '[vb-instance:bar]',
        '[dummy-master:foo]',
        'instance = bar'])
    master = ctrl.masters['foo']
    assert isinstance(master.instance, ProxyInstance)
    log_mock = Mock()
    monkeypatch.setattr('ploy.log', log_mock)
    monkeypatch.setattr('ploy.proxy.log', log_mock)
    with pytest.raises(SystemExit):
        master.instance.instance
    assert log_mock.error.call_args_list == [
        call("Instance 'bar' not found. Did you forget to install a plugin? The following sections might match:\n    vb-instance:bar"),
        call("The to be proxied instance 'bar' for master 'foo' wasn't found.")]


def test_proxy_config_values_passed_on_with_default_instance_object(ctrl, ployconf):
    ployconf.fill([
        '[dummy-master:foo]',
        'ham = 1'])
    proxy = ctrl.instances['foo']
    proxied = proxy._proxied_instance
    assert proxy is not proxied
    assert proxy.config == {'ham': '1'}
    assert proxied.config == {'ham': '1'}
    del proxy.config['ham']
    assert proxy.config == {}
    assert proxied.config == {}
    proxy.config['egg'] = 'spam'
    assert proxy.config == {'egg': 'spam'}
    assert proxied.config == {'egg': 'spam'}


def test_proxy_config_values_passed_on(ctrl, ployconf):
    ployconf.fill([
        '[plain-instance:bar]',
        'ham = 1',
        '[dummy-master:foo]',
        'instance = bar'])
    bar = ctrl.instances['bar']
    foo = ctrl.instances['foo']
    proxy = ctrl.masters['foo'].instance
    # we have to trigger the lazy attribute
    proxied = ctrl.masters['foo'].instance._proxied_instance
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
