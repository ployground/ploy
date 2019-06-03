from setuptools import setup
import os

version = "2.0.0b2"

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
HISTORY = open(os.path.join(here, 'HISTORY.rst')).read()

install_requires = [
    'attrs',
    'lazy',
    'paramiko',
    'pluggy',
    'ruamel.yaml',
    'setuptools']

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
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: System :: Installation/Setup',
        'Topic :: System :: Systems Administration'],
    include_package_data=True,
    zip_safe=False,
    packages=['ploy', 'ploy.tests', 'ploy_pytest_plugin'],
    install_requires=install_requires,
    python_requires='>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*',
    entry_points="""
        [console_scripts]
        ploy = ploy:ploy
        ploy-ssh = ploy:ploy_ssh
        [ploy.plugins]
        plain = ploy.plain:plugin
        [pytest11]
        ploy_pytest_plugin = ploy_pytest_plugin
    """)
