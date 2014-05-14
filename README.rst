.. contents::


Overview
========

mr.awsome is a commandline-tool (aws) to provision, manage and control server instances.
What kind of server instances these are depends on the used plugins.
There are plugins for EC2 (mr.awsome.ec2), FreeBSD Jails (mr.awsome.ezjail) and more.
You can create, delete, monitor and ssh into instances while mr.awsome handles the details like ssh fingerprint checking.
Additional plugins provide advanced functionality like integrating Fabric (mr.awsome.fabric) and Ansible (mr.awsome.ansible).

Installation
============

mr.awsome is best installed with easy_install, pip or with zc.recipe.egg in a buildout. It installs two scripts, ``aws`` and ``assh``.

With zc.recipe.egg you can set a custom configfile location like this::

  [aws]
  recipe = zc.recipe.egg
  eggs = mr.awsome
  arguments = configpath="${buildout:directory}/etc/", configname="servers.cfg"

As of this writing the pycrypto package is throwing some deprecation warnings, you might want to disable them by adding an initialization option to the aws part like this::

  initialization =
      import warnings
      warnings.filterwarnings("ignore", ".*", DeprecationWarning, "Crypto\.Hash\.MD5", 6)
      warnings.filterwarnings("ignore", ".*", DeprecationWarning, "Crypto\.Hash\.SHA", 6)
      warnings.filterwarnings("ignore", ".*", DeprecationWarning, "Crypto\.Util\.randpool", 40)


Configuration
=============

All information about server instances is located in ``aws.conf``, which by default is looked up in ``etc/aws.conf``.


Plugins
=======

Support for backends and further functionality is implemented by plugins. One plugin is included with mr.awsome.

``plain``
  For regular servers accessible via ssh.


Plain
-----

With plain instances you can put infos about servers into the configuration to benefit from some mr.awsome features like ssh fingerprint checking and plugins like the Fabric integration.

Options
~~~~~~~

``host`` or ``ip``
  (**required**) The host name or address for the server.

``user``
  The default user for ssh connections. If it's set to ``*`` then the current
  local user name is used.

``port``
  The ssh port number.

``fingerprint``
  (**required**) The ssh fingerprint of the server.
  If set to ``ask`` then manual interactive verification is enabled.
  If set to ``ignore`` then no verification is performed at all!

``password-fallback``
  If this boolean is true, then using a password as fallback is enabled if the
  ssh key doesn't work. This is off by default.

``password``
  Never use this directly! If password-fallback is enabled this password is
  used. This is mainly meant for Fabric scripts which have other ways to get
  the password. On use case is bootstrapping `FreeBSD <http://www.freebsd.org/>`_
  from an `mfsBSD <http://mfsbsd.vx.sk/>`_ distribution where the password is
  fixed.

``proxyhost``
  The id of another instance declared in aws.conf which is used to create a
  tunnel to the ssh port of this instance.

``proxycommand``
  The command to use in the ProxyCommand option for ssh when using the ``assh``
  command. There are some variables which can be used:

    ``path``
      The directory of the aws.conf file. Useful if you want to use the ``assh``
      command itself for the proxy.

    ``known_hosts``
      The absolute path to the known_hosts file managed by mr.awsome.

    ``instances``
      The variables of other instances. For example: instances.foo.ip

  In addition to these the variables of the instance itself are available.

  A full example for a proxycommand::

    proxycommand = {path}/../bin/assh vm-master -W {ip}:22


SSH integration
===============

mr.awsome provides an additional tool ``assh`` to easily perform SSH based
operations against named instances. Particularly, it encapsulates the
entire *SSH fingerprint* mechanism. For example EC2 instances are often
short-lived and normally trigger warnings, especially, if you are using
elastic IPs.

  Note:: it does so not by simply turning off these checks, but by transparently updating its own fingerprint list using mechanisms provided by the backend plugins.

The easiest scenario is simply to create an SSH session with an instance. You
can either use the ssh subcommand of the aws tool like so::

  aws ssh SERVERNAME

Alternatively you can use the assh command directly, like so::

  assh SERVERNAME

The latter has been provided to support scp and rsync. Here are some
examples, you get the idea::

  scp -S `pwd`/bin/assh some.file demo-server:/some/path/
  rsync -e "bin/assh" some/path fschulze@demo-server:/some/path


Macro expansion
===============

In the ``aws.conf`` you can use macro expansion for cleaner configuration
files. That looks like this::

  [ec2-instance:demo-server2]
  <= demo-server
  securitygroups = demo-server2

  [ec2-securitygroup:demo-server2]
  <= demo-server

All the options from the specified macro are copied with some important exceptions depending on the backend:

  * For instances the ``ip`` and ``volumes`` options aren't copied.

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

Plugins and mr.awsome massage certain string values from the config to convert them to other types and do formatting or expansion.

You can use that yourself, which is useful for the Fabric integration and other things.

Here is a simple example::

  [section]
  massagers =
    intvalue=mr.awsome.config.IntegerMassager
    boolvalue=mr.awsome.config.BooleanMassager
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
