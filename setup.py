from setuptools import setup
import os

version = "0.12"

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
HISTORY = open(os.path.join(here, 'HISTORY.rst')).read()

install_requires = [
    'setuptools',
    'boto >= 2.0',
    'Fabric >= 1.3.0',
    'lazy']

try:
    import argparse
    argparse    # make pyflakes happy...
except ImportError:
    install_requires.append('argparse >= 1.1')

setup(
    version=version,
    description="A script allowing to setup Amazon EC2 instances through configuration files.",
    long_description=README + "\n\n" + HISTORY,
    name="mr.awsome",
    author='Florian Schulze',
    author_email='florian.schulze@gmx.net',
    url='http://github.com/fschulze/mr.awsome',
    include_package_data=True,
    zip_safe=False,
    packages=['mr'],
    namespace_packages=['mr'],
    install_requires=install_requires,
    entry_points="""
      [console_scripts]
      aws = mr.awsome:aws
      assh = mr.awsome:aws_ssh
    """)
