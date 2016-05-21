Changelog
=========

1.3.0 - 2016-05-21
------------------

* Add option ``ssh_fingerprints`` which allows to specify multiple fingerprints.
  [fschulze]

* Support new output of ``ssh-keygen`` which includes the hash type and
  defaults to ``SHA256``.
  [fschulze]


1.2.1 - 2015-08-27
------------------

* Allow to specify multiple masters per instance.
  [fschulze]


1.2.0 - 2015-03-05
------------------

* Add ``Executor`` helper to handle local and remote command execution. It's
  also handling ssh agent forwarding enabled by either the users ssh config
  or the ``ssh-extra-args`` option.
  [fschulze]


1.1.0 - 2015-02-28
------------------

* Add ``ssh-extra-args`` option.
  [fschulze]

* Add ``annotate`` command to print the configuration with the source of each
  setting.
  [fschulze]

* Allow custom shebang in gzipped startup scripts.
  [fschulze]


1.0.3 - 2015-01-22
------------------

* Drop bad entries from our ``known_hosts`` file to prevent failures
  in paramiko.
  [fschulze]

* Set ``StrictHostKeyChecking=yes`` for all ssh connections to prevent
  interactive asking.
  [fschulze]


1.0.2 - 2014-10-04
------------------

* Ask before terminating an instance.
  [fschulze]

* Fix config setting propagation in some cases of proxied instances.
  [fschulze]

* Close all connections before exiting. This prevents hangs caused by open
  proxy command threads.
  [fschulze]

* Add option to log debug output.
  [fschulze]

* Add helpers to setup proxycommand in plugins.
  [fschulze]


1.0.1 - 2014-08-13
------------------

* Fix error output for plain instances on ssh connection failures.
  [fschulze]


1.0.0 - 2014-07-19
------------------

* Fix removal of bad host keys when using non standard ssh port.
  [fschulze]

* Renamed ``plain-master`` to ``plain``, so the uids of instances are nicer.
  [fschulze]


1.0rc15 - 2014-07-16
--------------------

* Only remove bad host key from known_hosts instead of clearing it completely.
  [fschulze]

* Removed support for ``proxyhost`` option. It caused hangs and failures on
  missing or invalid ssh fingerprints.
  [fschulze]

* Allow empty ``startup_script`` option to mean use no startup script.
  [fschulze]


1.0rc14 - 2014-07-15
--------------------

* Allow ``fingerprint`` to be set to a public host key file.
  [fschulze]


1.0rc13 - 2014-07-08
--------------------

* Better error message for instances missing because the plugin isn't installed.
  [fschulze]

* Fix tests when ploy itself isn't installed.
  [fschulze]


1.0rc12 - 2014-07-08
--------------------

* Use plain conftest.py instead of pytest plugin.
  [fschulze]


1.0rc11 - 2014-07-05
--------------------

* Fix uid method for master instances.
  [fschulze]


1.0rc10 - 2014-07-04
--------------------

* Print plugin versions with ``-v`` and ``--versions``.
  [fschulze]

* Python 3 compatibility.
  [fschulze]


1.0rc9 - 2014-06-29
-------------------

* Let plugins add type of lists to show with the ``list`` command.
  [fschulze]

* Use ``server`` and ``instance`` consistently.
  [fschulze]

* Always make instances accessible by their full name in the form of
  "[master_id]-[instance_id]". Only if there is no conflict, the short version
  with just "[instance_id]" is also available for convenience.
  [fschulze]

* Add instance id validator which limits to letters, numbers, dashes and
  underscores.
  [fschulze]

* Renamed from mr.awsome to ploy.
  [fschulze]


1.0rc8 - 2014-06-16
-------------------

* Give a bit more info on ssh connection failures.
  [fschulze]


1.0rc7 - 2014-06-11
-------------------

* Expose some test fixtures for reuse in plugins.
  [fschulze]

* Add before_terminate and after_start hooks and make it simple for plugins
  to add their own hooks.
  [fschulze]


1.0rc6 - 2014-06-10
-------------------

* Add ``get_path`` method to ConfigSection class.
  [fschulze]


1.0rc5 - 2014-06-09
-------------------

* Provide helper method ``ssh_args_from_info`` on BaseInstance to get the
  arguments for running the ssh executable from the info provided by
  init_ssh_key.
  [fschulze]

* Allow overwriting the command name in help messages for bsdploy.
  [fschulze]

* Make debug command usable for instances that don't have a startup script.
  [fschulze]

* Instances can provide a get_port method to return a default port.
  [fschulze]

* Catch socket errors in init_ssh_key of plain instances to print additional
  info for debugging.
  [fschulze]

* Delay setting of config file path to expose too early use of config in
  plugins. Refs #29
  [fschulze]


1.0rc4 - 2014-05-21
-------------------

* Fix massagers for ``[instance:...]`` sections.
  [fschulze]

* Copy massagers in ConfigSection.copy, so overrides in startup script work
  correctly.
  [fschulze]


1.0rc3 - 2014-05-15
-------------------

* Fetch fingerprints only when necessary. This speeds up connections when the
  fingerprint in known_hosts is still valid.
  [fschulze]


1.0rc2 - 2014-05-14
-------------------

* Moved setuptools-git from setup.py to .travis.yml, it's only needed for
  releases and testing.
  [fschulze]

* More tests.
  [fschulze]


1.0rc1 - 2014-03-23
-------------------

* Test, enhance and document adding massagers via config.
  [fschulze]

* Moved ec2 and fabric integration into separate plugins.
  [fschulze]

* You can now have instances with the same name if the belong to different
  masters, they will then get the name of the master as a prefix to their name.
  [fschulze]

* Add possibility to overwrite the default config name.
  [tomster]

* Improved ``proxycommand`` and documented it.
  [fschulze]

* Make the AWS instance available in masters. This changes the ``get_masters``
  plugin interface.
  [fschulze]

* Use os.execvp instead of subprocess.call. This allows the use of ``assh`` in
  the ``proxycommand`` option, which greatly simplifies it's use.
  [fschulze]

* Added command plugin hooks.
  [fschulze]

* The variable substitution for the ``proxycommand`` option now makes the other
  instances available in a dict under ``instances``. And adds ``known_hosts``.
  [fschulze]

* Load plugins via entry points instead of the ``plugin`` section in the config.
  [fschulze]

* Allow fallback to password for ssh to plain instances.
  [fschulze]

* Add option to ask for manual fingerprint validation for plain instances.
  [fschulze]


0.13 - 2013-09-20
-----------------

* Use os.path.expanduser on all paths, so that one can use ~ in config values
  like the aws keys.
  [fschulze]


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
  [tomster (Tom Lazar), fschulze]

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
  [natea (Nate Aune), fschulze]

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
