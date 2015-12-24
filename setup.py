from setuptools import setup
import os

version = "2.0.0.dev0"

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
    description="A tool to manage servers through a central configuration. Plugins allow provisioning, configuration and other management tasks.",
    long_description=README + "\n\n" + HISTORY,
    name="ploy",
    author='Florian Schulze',
    author_email='florian.schulze@gmx.net',
    license="BSD 3-Clause License",
    url='http://github.com/ployground/ploy',
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
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
    """)
