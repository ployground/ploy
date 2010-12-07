# Inspired by zope.cachedescriptors.property.Lazy


class lazy(object):
    """Lazy attributes.

    Used as a decorator to create lazy attributes. Lazy
    attributes are evaluated on first use.
    """

    def __init__(self, func):
        self.__func = func
        self.__name__ = func.__name__
        self.__module__ = func.__module__
        self.__doc__ = func.__doc__
        self.__dict__.update(func.__dict__)

    def __get__(self, inst, cls):
        if inst is None:
            return self
        name = self.__name__
        value = self.__func(inst)
        inst.__dict__[name] = value
        return value
