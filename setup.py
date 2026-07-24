from setuptools import setup
import os

version = "3.0.0.dev0"

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
HISTORY = open(os.path.join(here, 'HISTORY.rst')).read()

install_requires = [
    'attrs',
    'lazy',
    'paramiko',
    'pluggy',
    'ruamel.yaml']

setup(
    version=version,
    description="A tool to manage servers through a central configuration. Plugins allow provisioning, configuration and other management tasks.",
    long_description=README + "\n\n" + HISTORY,
    name="ploy",
    author="Florian Schulze",
    author_email="mail@florian-schulze.net",
    license="BSD 3-Clause License",
    url="http://github.com/ployground/ploy",
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: System :: Installation/Setup",
        "Topic :: System :: Systems Administration",
    ],
    include_package_data=True,
    zip_safe=False,
    packages=["ploy", "ploy.tests", "ploy_pytest_plugin"],
    install_requires=install_requires,
    python_requires=">=3.8",
    entry_points="""
        [console_scripts]
        ploy = ploy:ploy
        ploy-ssh = ploy:ploy_ssh
        [ploy.plugins]
        plain = ploy.plain:plugin
        [pytest11]
        ploy_pytest_plugin = ploy_pytest_plugin
    """,
)
