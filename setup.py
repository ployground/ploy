from setuptools import setup
import os

version = "1.0rc10"

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
HISTORY = open(os.path.join(here, 'HISTORY.rst')).read()

install_requires = [
    'lazy',
    'paramiko',
    'setuptools']

try:
    import argparse
    argparse    # make pyflakes happy...
except ImportError:
    install_requires.append('argparse >= 1.1')

setup(
    version=version,
    description="A script allowing to setup Amazon EC2 instances through configuration files.",
    long_description=README + "\n\n" + HISTORY,
    name="ploy",
    author='Florian Schulze',
    author_email='florian.schulze@gmx.net',
    license="BSD 3-Clause License",
    url='http://github.com/ployground/ploy',
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Topic :: System :: Installation/Setup',
        'Topic :: System :: Systems Administration'],
    include_package_data=True,
    zip_safe=False,
    packages=['ploy', 'ploy.tests'],
    install_requires=install_requires,
    entry_points="""
        [console_scripts]
        ploy = ploy:ploy
        ploy-ssh = ploy:ploy_ssh
        [ploy.plugins]
        plain = ploy.plain:plugin
        [pytest11]
        ploy = ploy.tests.pytest_plugin
    """)
