Overview
========

Ploy is a commandline-tool to provision, manage and control server instances.
There are plugins for EC2 (ploy_ec2), FreeBSD Jails (ploy_ezjail) and more.
You can create, delete, monitor and ssh into instances while ploy handles the details like ssh fingerprint checking.
Additional plugins provide advanced functionality like integrating Fabric (ploy_fabric) and Ansible (ploy_ansible).

You can find the detailed documentation at http://ploy.readthedocs.org/en/latest/


Installation
============

ploy is best installed with easy_install, pip or with zc.recipe.egg in a buildout.
It installs two scripts, ``ploy`` and ``ploy-ssh``.


Configuration
=============

All information about server instances is located in ``ploy.conf``, which by default is looked up in ``etc/ploy.conf``.


Plugins
=======

Support for backends and further functionality is implemented by plugins. One plugin is included with ploy.

``plain``
  For regular servers accessible via ssh.

You can see which plugins are available in your current installation with ``ploy -v``.


Plain
-----

With plain instances you can put infos about servers into the configuration to benefit from some ploy features like ssh fingerprint checking and plugins like the Fabric integration.


Options
~~~~~~~

``host`` or ``ip``
  (**required**) The host name or address for the server.

``user``
  The default user for ssh connections. If it's set to ``*`` then the current
  local user name is used.

``port``
  The ssh port number.

``ssh-fingerprints``
  (**required**) The ssh fingerprints of the server.
  If set to ``ask`` then manual interactive verification is enabled.
  If set to ``ignore`` then no verification is performed at all!
  You can also point this to a public ssh host key file to let the fingerprint be extracted automatically.
  Multiple fingerprints can be specified one per line, or separated by commas.
  The format of fingerprints is either 16 bytes as hex numbers separated by colons,
  the same 16 bytes prefixed by ``MD5:``,
  or the hash type, followed by a colon and the base 64 encoded hash digest.

``password-fallback``
  If this boolean is true, then using a password as fallback is enabled if the
  ssh key doesn't work. This is off by default.
  You may be asked more than once for the password.
  The first time is by paramiko which always happens, but is remembered.
  The other times is by the ssh command line tool if it's invoked.

``password``
  Never use this directly! If password-fallback is enabled this password is
  used. This is mainly meant for Fabric scripts which have other ways to get
  the password. On use case is bootstrapping `FreeBSD <http://www.freebsd.org/>`_
  from an `mfsBSD <http://mfsbsd.vx.sk/>`_ distribution where the password is
  fixed.

``proxycommand``
  The command to use in the ProxyCommand option for ssh when using the ``ploy-ssh``
  command. There are some variables which can be used:

    ``path``
      The directory of the ploy.conf file. Useful if you want to use the ``ploy-ssh``
      command itself for the proxy.

    ``known_hosts``
      The absolute path to the known_hosts file managed by ploy.

    ``instances``
      The variables of other instances. For example: instances.foo.ip

  In addition to these the variables of the instance itself are available.

  A full example for a proxycommand::

    proxycommand = {path}/../bin/ploy-ssh vm-master -W {ip}:22

``ssh-key-filename``
  Location of private ssh key to use.

``ssh-extra-args``
  A list of settings separated by newlines passed on to ssh.

  Example::

    ssh-extra-args = ForwardAgent yes


SSH integration
===============

ploy provides an additional tool ``ploy-ssh`` to easily perform SSH based
operations against named instances. Particularly, it encapsulates the
entire *SSH fingerprint* mechanism. For example EC2 instances are often
short-lived and normally trigger warnings, especially, if you are using
elastic IPs.

  Note:: it does so not by simply turning off these checks, but by transparently updating its own fingerprint list using mechanisms provided by the backend plugins.

The easiest scenario is simply to create an SSH session with an instance. You
can either use the ssh subcommand of the ploy tool like so::

  ploy ssh INSTANCENAME

Alternatively you can use the ploy-ssh command directly, like so::

  ploy-ssh INSTANCENAME

The latter has been provided to support scp and rsync. Here are some
examples, you get the idea::

  scp -S `pwd`/bin/ploy-ssh some.file demo-server:/some/path/
  rsync -e "bin/ploy-ssh" some/path fschulze@demo-server:/some/path


Instance names
==============

Instances have an **id** which is the part after the colon in the configuration.
They also have a **unique id** which has the form ``[masterid]-[instanceid]``.
The ``[masterid]`` depends on the plugin.
For plain instances it is ``plain``.
The ``[instanceid]`` is the **id** of the instance.
So, if you have the following config::

  [plain-instance:foo]
  ...

Then the **unique id** of the instance is ``plain-foo``.


Macro expansion
===============

In the ``ploy.conf`` you can use macro expansion for cleaner configuration
files. That looks like this::

  [ec2-instance:demo-server2]
  <= demo-server
  securitygroups = demo-server2

  [ec2-securitygroup:demo-server2]
  <= demo-server

All the options from the specified macro are copied with some exceptions depending on the backend plugin.

If you want to copy data from some other kind of options, you can add a colon
in the macro name. This is useful if you want to have a base for instances
like this::

  [macro:base-instance]
  keypair = default
  region = eu-west-1
  placement = eu-west-1a

  [ec2-instance:server]
  <= macro:base-instance
  ...


Massaging of config values
==========================

Plugins and ploy massage certain string values from the config to convert them to other types and do formatting or expansion.

You can use that yourself, which is useful for the Fabric integration and other things.

Here is a simple example::

  [section]
  massagers =
    intvalue=ploy.config.IntegerMassager
    boolvalue=ploy.config.BooleanMassager
  intvalue = 1
  boolvalue = yes

If you now access those values from for example a fabric task, you get the correct type instead of strings.

The above syntax registers the massagers only for that section.
You can register massagers for other sections or even section groups with this syntax::

  massagers =
    [option]=[sectiongroup]:import.path.to.massager
    [option]=[sectiongroup]:[section]:import.path.to.massager

The parts have the following meaning:

  ``[option]``
    This is the name of the option which should be massaged

  ``[sectiongroup]``
    The name of the section group.
    That's the part before the optional colon in a section.
    To match sections without a colon, use ``global``.
    To match every section, use ``*``.

  ``[section]``
    The name of the section to which this massager is applied.
    If empty, the current section is used.


Buildout specifics
==================

With zc.recipe.egg you can set a custom configfile location like this::

  [ploy]
  recipe = zc.recipe.egg
  eggs = ploy
  arguments = configpath="${buildout:directory}/etc/", configname="servers.cfg"
