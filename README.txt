**Overview**

mr.awsome is a commandline-tool (aws) to manage and control Amazon
Webservice's EC2 instances. Once configured with your AWS key, you can
create, delete, monitor and ssh into instances, as well as perform scripted
tasks on them (via fabfiles).
Examples are adding additional, pre-configured webservers to a cluster
(including updating the load balancer), performing automated software
deployments and creating backups - each with just one call from the
commandline. Aw(e)some, indeed, if we may say so...

**Installation**

mr.awsome is best installed with easy_install, pip or with zc.recipe.egg in
a buildout. It installs two scripts, ``aws`` and ``assh``.

**Configuration**

To authorize itself against AWS, mr.awsome uses the following two environment
variables::

  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY

You can find their values at `http://aws.amazon.com`_ under *'Your Account'-'Security Credentials'.*

You can also put them into files and point to them in the ``[aws]`` section
with the ``access-key-id`` and ``secret-access-key`` options. It's best to
put them in ``~/.aws/`` and make sure only your user can read them.

All other information about server instances is located in ``aws.conf``, which
by default is looked up in ``etc/aws.conf``.

Before you can create a server instance with the ``create`` command described below, you first have to declare a security group in
your ``aws.conf`` like this::

  [securitygroup:demo-server]
  description = Our Demo-Server
  connections =
    tcp 22 22 0.0.0.0/0
    tcp 80 80 0.0.0.0/0

The security group is used for both the firewall settings, as documented in
the AWS docs, and to find the server instance associated with it.

Then you can add the info about the server instance itself like this::

  [instance:demo-server]
  keypair = default
  securitygroups = demo-server
  region = eu-west-1
  placement = eu-west-1a
  # we use images from `http://alestic.com/`_
  # Ubuntu 9.10 Karmic server 32-bit Europe
  image = ami-a62a01d2
  startup_script = startup-demo-server
  fabfile = `fabfile.py`_

**Startup scripts**

The startup_script option above allows you to write a script which is run
right after instance creation to setup your server. This feature is supported
by many AMI images and was made popular by `http://alestic.com/`_ (See
`http://alestic.com/2009/06/ec2-user-data-scripts`_).

Most of the time these are bash scripts like this (for Ubuntu in this case)::

  #!/bin/bash
  set -e -x
  export DEBIAN_FRONTEND=noninteractive
  apt-get update && apt-get upgrade -y

The ``set -e -x`` is for debugging. You can see the commands which ran and their output in ``/var/log/syslog`` once you are logged into the server.

The startup scripts have a maximum size of 16kb. You can check the size with
the ``debug`` command of the ``aws`` script.

The startup script is basically a template for the Python string format
method (See `http://docs.python.org/library/string.html#formatstrings`_). So
anything inside curly brackets is expanded. To get normal curly brackets,
when you write bash functions etc, just double them like this::

  function LOG() {{ echo "$*"; }}

If you want to include any files for something like ssh ``authorized_keys``, you do something the following::

  authorized_keys: file,escape_eol ssh-authorized_keys

  #!/bin/bash
  ...
  /bin/bash -c "echo -e \"{authorized_keys}\" >> /root/.ssh/authorized_keys"


So the startup script basically has rfc822 syntax (internally the e-mail
parser is used). The ``file,escape_eol`` tells the script that the ``ssh-
authorized_keys`` string should be used as a filename for a file which is then
read and the ``\n`` characters are escaped so the resulting string can be used
in the ``echo -e`` command.

You have the following possibilities (brain dump, needs fleshing out):
 -   file
 -   base64
 -   format
 -   template
 -   gzip
 -   escape_eol

In addition to that, you have access to some more variables. For example full
access to the server config in the aws.conf. With servers[demo-
server].instance.dns_name for example, you can get the current DNS name of
the server (this only works with other servers already started, not the one
for which the startup script is for, since the DNS isn't set at the time the
script is created).

You can add a ``gzip:`` prefix before the filename to let the script be self
extracting. The code used looks like this::

  #!/bin/bash
  tail -n+4 $0 | gunzip -c | bash
  exit $?

Directly after that follows the binary data of the gzipped startup script.

**Controlling instances**

 -   start
 -   stop
 -   status

**Snapshots**

(Needs description of volumes in "Configuration")

**SSH integration**

mr.awsome provides an additional tool ``assh`` to easily perform SSH based
operations against named EC2 instances. Particularly, it encapsulates the
entire *SSH fingerprint* mechanism, as EC2 instances are often short-lived and
normally trigger warnings, especially, if you are using elastic IPs.

  Note:: it does so not by simply turning off these checks, but by transparently updating its own fingerprint list (it relies on the console output of the instance to provide the fingerprint via the AWS API, some imags may not be configured to do so) when adding new instances.

The easiest scenario is simply to create an SSH session with an instance. You
can either use the ssh subcommand of the aws tool like so::

  aws ssh SERVERNAME

Alternatively you can use the assh command direct, like so::

  assh SERVERNAME

The latter has been provided to support scp and rsync. Here are some
examples, you get the idea::

  scp -S `pwd`/bin/assh some.file demo-server:/some/path/
  rsync -e "bin/assh" some/path fschulze@demo-server:/some/path


**Fabric integration**

Since ``Fabric <http://fabfile.org/`_>`_ basically works through ssh, all the
bits necessary for ssh integration are also needed for Fabric. To make it
easy to run fabfiles, you specifiy them with the "fabfile" option in your
aws.conf and use the ``do`` command to run them.

Take the following `fabfile.py`_ as an example::

  from fabric.api import env, run

  env.reject_unknown_hosts = True
  env.disable_known_hosts = True

  def get_syslog():
    run("echo /var/log/syslog")

If you have that fabfile for the demo-server above, you can then run the
command with "bin/aws demo-server do get_syslog".

For more info about fabfiles, read the docs at `http://fabfile.org/`_.

.. _http://aws.amazon.com: http://aws.amazon.com/
.. _http://alestic.com/: http://alestic.com/
.. _fabfile.py: http://fabfile.py/
.. _http://alestic.com/2009/06/ec2-user-data-scripts:
    http://alestic.com/2009/06/ec2-user-data-scripts
.. _http://docs.python.org/library/string.html#formatstrings:
    http://docs.python.org/library/string.html#formatstrings
.. _http://fabfile.org/: http://fabfile.org/


**Macro expansion**

In the ``aws.conf`` you can use macro expansion for cleaner configuration
files. This looks like this::

  [instance:demo-server2]
  <= demo-server
  securitygroups = demo-server2

  [securitygroup:demo-server2]
  <= demo-server

All the options from the specified macro are copied with some important exceptions:

  * For instances the ``ip`` and ``volumes`` options aren't copied.

If you want to copy data from some other kind of options, you can add a colon
in the macro name. This is useful if you want to have a base for instances
like this::

  [macro:base-instance]
  keypair = default
  region = eu-west-1
  placement = eu-west-1a

  [instance:server]
  <= macro:base-instance
  ...
