from pluggy import HookspecMarker


hookspec = HookspecMarker("ploy")


@hookspec
def ploy_locate_config(fn):
    pass


@hookspec(firstresult=True)
def ploy_load_config(fn, plugins):
    pass
