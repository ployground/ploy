from setuptools import setup
import os

version = "0.7"

setup(
    version=version,
    description="A script allowing to setup Amazon EC2 instances through configuration files.",
    long_description=open("README.txt").read() + "\n\n" +
                     open(os.path.join("docs", "HISTORY.txt")).read(),
    name="mr.awsome",
    author='Florian Schulze',
    author_email='florian.schulze@gmx.net',
    url='http://github.com/fschulze/mr.awsome',
    include_package_data=True,
    zip_safe=False,
    packages=['mr'],
    namespace_packages=['mr'],
    install_requires=[
        'setuptools',
        'boto >= 1.9b',
        'Fabric >= 0.9.0',
        'argparse >= 1.1',
    ],
    entry_points="""
      [console_scripts]
      aws = mr.awsome:aws
      assh = mr.awsome:aws_ssh
    """,
)