Changelog
=========

0.12 - 2013-09-11
-----------------

* There is no need to add the AWS account id to security group names anymore.
  [fschulze]

* Rules are removed from security groups if they aren't defined in the config.
  [fschulze]

* Allow adding of custom config massagers from inside the config.
  [fschulze]

* Support block device maps to enable use of more than one ephemeral disk.
  [fschulze]

* Added ``do`` method on ec2 and plain instances which allows to call fabric
  commands.
  [fschulze]

* Use PathMassager for ``access-key-id`` and ``secret-access-key`` in the
  ``ec2-master`` section. This might break existing relative paths for these
  options.
  [fschulze]

* Added support for EBS boot instances.
  [fschulze]

* Add option ``ssh-key-filename`` to point to a private ssh key for ec2 and
  plain instances.
  [fschulze]

* Fix Fabric integration for newer versions of Fabric.
  [fschulze]

* Support ``proxycommand`` option for plain instances. This also caused a
  change in the ``init_ssh_key`` API for plugins.
  [fschulze]

* Support ``ProxyCommand`` from ``~/.ssh/config`` for plain instances.
  Requires Fabric 1.5.0 and Paramiko 1.9.0 or newer.
  [fschulze]


0.11 - 2012-11-08
-----------------

* Support both the ``ssh`` and ``paramiko`` libraries depending on which
  Fabric version is used.
  [fschulze]


0.10 - 2012-06-04
-----------------

* Added ``ec2-connection`` which helps in writing Fabric scripts which don't
  connect to a server but need access to the config and AWS (like uploading
  something to S3).
  [fschulze]

* Fix several problems with using a user name other than ``root`` for the
  ``do`` and ``ssh`` commands.
  [fschulze]

* Require Fabric >= 1.3.0.
  [fschulze]

* Require boto >= 2.0.
  [fschulze]

* Added hook for startup script options.
  [fschulze]

* Added possibility to configure hooks.
  [fschulze]

* Refactored to enable plugins for different virtualization or cloud providers.
  [fschulze]

* Added lots of tests.
  [fschulze]


0.9 - 2010-12-09
----------------

* Overwrites now also affect server creation, not just the startup script.
  [fschulze]

* Added ``list`` command which supports just listing ``snapshots`` for now.
  [fschulze]

* Added ``delete-volumes-on-terminate`` option to delete volumes created from
  snapshots on instance termination.
  [fschulze]

* Added support for creating volumes from snapshots on instance start.
  [natea, fschulze]

* Added support for ``~/.ssh/config``. This is a bit limited, because the
  paramiko config parser isn't very good.
  [fschulze]

* Added ``help`` command which provides some info for zsh autocompletion.
  [fschulze]

0.8 - 2010-04-21
----------------

* For the ``do`` command the Fabric options ``reject_unknown_hosts`` and
  ``disable_known_hosts`` now default to true.
  [fschulze]

* Allow adding normal servers to use with ``ssh`` and ``do`` commands.
  [fschulze]

* Refactored ssh connection handling to only open network connections when
  needed. Any fabric option which doesn't need a connection runs right away
  now (like ``-h`` and ``-l``).
  [fschulze]

* Fix status output after ``start``.
  [fschulze]

0.7 - 2010-03-22
----------------

* Added ``snapshot`` method to Server class for easy access from fabfiles.
  [fschulze]

0.6 - 2010-03-18
----------------

* It's now possible to specify files which contain the aws keys in the
  ``[aws]`` section with the ``access-key-id`` and ``secret-access-key``
  options.
  [fschulze]

* Added ``-c``/``--config`` option to specify the config file to use.
  [fschulze]

* Added ``-v``/``--version`` option.
  [tomster, fschulze]

* Comment lines in the startup script are now removed before any variables
  in it are expanded, not afterwards.
  [fschulze]

* Use argparse library instead of optparse for more powerful command line
  parsing.
  [fschulze]

0.5 - 2010-03-11
----------------

* Added gzipping of startup script by looking for ``gzip:`` prefix in the
  filename.
  [fschulze]

* Added macro expansion similar to zc.buildout 1.4.
  [fschulze]

0.4 - 2010-02-18
----------------

* Check console output in ``status`` and tell user about it.
  [fschulze]

* Friendly message instead of traceback when trying to ssh into an unavailable
  server.
  [fschulze]

* Remove comment lines from startup script if it's starting with ``#!/bin/sh``
  or ``#!/bin/bash``.
  [fschulze]

* Removed ``-r`` option for ``start`` and ``debug`` commands and replaced it
  with more general ``-o`` option.
  [fschulze]

* Made startup script optional (not all AMIs support it, especially Windows
  ones).
  [fschulze]

* The ``stop`` command actually only stops an instance now (only works with
  instances booted from an EBS volume) and the new ``terminate`` command now
  does what ``stop`` did before.
  [fschulze]

* Better error message when no console output is available for ssh finger
  print validation.
  [fschulze]

* Fixed indentation in documentation.
  [natea, fschulze]

0.3 - 2010-02-08
----------------

* Removed the ``[host_string]`` prefix of the ``do`` command output.
  [fschulze]

0.2 - 2010-02-02
----------------

* Snapshots automatically get a description with date and volume id.
  [fschulze]

* The ssh command can now be used with scp and rsync.
  [fschulze]


0.1 - 2010-01-21
----------------

* Initial release
  [fschulze]
