from boto.ec2.securitygroup import GroupOrCIDR
from boto.exception import EC2ResponseError
from mr.awsome.common import gzip_string
from mr.awsome.config import Config
from mr.awsome.lazy import lazy
from mr.awsome import template
import boto.ec2
import datetime
import logging
import argparse
import os
import paramiko
import pkg_resources
import subprocess
import sys
import time


log = logging.getLogger('mr.awsome')


class AWSHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, instance):
        self.instance = instance

    def missing_host_key(self, client, hostname, key):
        fingerprint = ':'.join("%02x" % ord(x) for x in key.get_fingerprint())
        if self.instance.public_dns_name == hostname:
            fp_start = False
            output = self.instance.get_console_output().output
            if output.strip() == '':
                raise paramiko.SSHException('No console output (yet) for %s' % hostname)
            for line in output.split('\n'):
                if fp_start:
                    if fingerprint in line:
                        client._host_keys.add(hostname, key.get_name(), key)
                        if client._host_keys_filename is not None:
                            client.save_host_keys(client._host_keys_filename)
                        return
                if '-----BEGIN SSH HOST KEY FINGERPRINTS-----' in line:
                    fp_start = True
                elif '-----END SSH HOST KEY FINGERPRINTS-----' in line:
                    fp_start = False
        raise paramiko.SSHException('Unknown server %s' % hostname)


class ServerHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint

    def missing_host_key(self, client, hostname, key):
        fingerprint = ':'.join("%02x" % ord(x) for x in key.get_fingerprint())
        if fingerprint == self.fingerprint:
            client._host_keys.add(hostname, key.get_name(), key)
            if client._host_keys_filename is not None:
                client.save_host_keys(client._host_keys_filename)
            return
        raise paramiko.SSHException("Fingerprint doesn't match for %s (got %s, expected %s)" % (hostname, fingerprint, self.fingerprint))


class Securitygroups(object):
    def __init__(self, server):
        self.server = server
        self.update()

    def update(self):
        self.securitygroups = dict((x.name, x) for x in self.server.conn.get_all_security_groups())

    def get(self, sgid, create=False):
        if not 'securitygroup' in self.server.ec2.config:
            log.error("No security groups defined in configuration.")
            sys.exit(1)
        securitygroup = self.server.ec2.config['securitygroup'][sgid]
        if sgid not in self.securitygroups:
            if not create:
                raise KeyError
            sg = self.server.conn.create_security_group(sgid, securitygroup['description'])
            self.update()
        else:
            sg = self.securitygroups[sgid]
        if create:
            rules = set()
            for rule in sg.rules:
                for grant in rule.grants:
                    if grant.cidr_ip:
                        rules.add((rule.ip_protocol, int(rule.from_port),
                                   int(rule.to_port), grant.cidr_ip))
                    else:
                        rules.add('%s-%s' % (grant.name, grant.owner_id))
            for connection in securitygroup['connections']:
                if connection in rules:
                    continue
                if '-' in connection[3]:
                    if connection[3] in rules:
                        continue
                    grant = GroupOrCIDR()
                    grant.name, grant.ownerid = connection[3].rsplit('-', 1)
                    sg.authorize(src_group=grant)
                else:
                    sg.authorize(*connection)
        return sg


class Instance(object):
    def __init__(self, ec2, sid):
        self.id = sid
        self.ec2 = ec2
        self.config = self.ec2.config['instance'][sid]

    @lazy
    def conn(self):
        (aws_id, aws_key) = self.ec2.credentials
        region_id = self.config.get(
            'region',
            self.ec2.config.get(
                'global',
                {}).get(
                    'aws', {}).get(
                        'region', None))
        if region_id is None:
            log.error("No region set in server and global config")
            sys.exit(1)
        region = self.ec2.regions[region_id]
        return region.connect(
            aws_access_key_id=aws_id, aws_secret_access_key=aws_key
        )

    @lazy
    def instance(self):
        instances = []
        for reservation in self.conn.get_all_instances():
            groups = set(x.id for x in reservation.groups)
            if groups != self.config['securitygroups']:
                continue
            for instance in reservation.instances:
                if instance.state in ['shutting-down', 'terminated']:
                    continue
                instances.append(instance)
        if len(instances) < 1:
            log.info("Instance '%s' unavailable" % self.id)
            return
        elif len(instances) > 1:
            log.warn("More than one instance found, using first.")
        log.info("Instance '%s' available" % self.id)
        return instances[0]

    def image(self):
        images = self.conn.get_all_images([self.config['image']])
        return images[0]

    def securitygroups(self):
        securitygroups = getattr(self, '_securitygroups', None)
        if securitygroups is None:
            self._securitygroups = securitygroups = Securitygroups(self)
        sgs = []
        for sgid in self.config['securitygroups']:
            sgs.append(securitygroups.get(sgid, create=True))
        return sgs

    def startup_script(self, debug=False):
        startup_script_path = self.config.get('startup_script', None)
        if startup_script_path is None:
            return ''
        startup_script = template.Template(
            startup_script_path['path'],
            pre_filter=template.strip_hashcomments,
        )
        options = self.config.copy()
        options.update(dict(
            servers=self.ec2.all,
        ))
        result = startup_script(**options)
        if startup_script_path.get('gzip', False):
            result = "\n".join([
                "#!/bin/bash",
                "tail -n+4 $0 | gunzip -c | bash",
                "exit $?",
                gzip_string(result)
            ])
        if len(result) >= 16*1024:
            log.error("Startup script too big.")
            if not debug:
                sys.exit(1)
        return result

    def start(self):
        instance = self.instance
        if instance is not None:
            log.info("Instance state: %s", instance.state)
            log.info("Instance already started, waiting until it's available")
        else:
            log.info("Creating instance '%s'" % self.id)
            reservation = self.image().run(
                1, 1, self.config['keypair'],
                instance_type=self.config.get('instance_type', 'm1.small'),
                security_groups=self.securitygroups(),
                user_data=self.startup_script(),
                placement=self.config['placement']
            )
            instance = reservation.instances[0]
            log.info("Instance created, waiting until it's available")
        while instance.state != 'running':
            if instance.state != 'pending':
                log.error("Something went wrong, instance status: %s", instance.status)
                return
            time.sleep(5)
            sys.stdout.write(".")
            sys.stdout.flush()
            instance.update()
        sys.stdout.write("\n")
        sys.stdout.flush()
        ip = self.config.get('ip', None)
        if ip is not None:
            addresses = [x for x in self.conn.get_all_addresses()
                         if x.public_ip == ip]
            if len(addresses) > 0:
                if addresses[0].instance_id != instance.id:
                    if instance.use_ip(addresses[0]):
                        log.info("Assigned IP %s to instance '%s'", addresses[0].public_ip, self.id)
                    else:
                        log.error("Couldn't assign IP %s to instance '%s'", addresses[0].public_ip, self.id)
                        return
        volumes = dict((x.id, x) for x in self.conn.get_all_volumes())
        for volume_id, device in self.config.get('volumes', []):
            if volume_id not in volumes:
                log.error("Unknown volume %s" % volume_id)
                return
            volume = volumes[volume_id]
            if volume.attachment_state() == 'attached':
                continue
            log.info("Attaching storage (%s on %s)" % (volume_id, device))
            self.conn.attach_volume(volume_id, instance.id, device)

        snapshots = dict((x.id, x) for x in self.conn.get_all_snapshots(owner="self"))
        for snapshot_id, device in self.config.get('snapshots', []):
            if snapshot_id not in snapshots:
                log.error("Unknown snapshot %s" % snapshot_id)
                return
            log.info("Creating volume from snapshot: %s" % snapshot_id)
            snapshot = snapshots[snapshot_id]
            volume = self.conn.create_volume(snapshot.volume_size, self.config['placement'], snapshot_id)
            log.info("Attaching storage (%s on %s)" % (volume.id, device))
            self.conn.attach_volume(volume.id, instance.id, device)

        return instance

    def init_ssh_key(self, user=None):
        instance = self.instance
        if instance is None:
            log.error("Can't establish ssh connection.")
            return
        if user is None:
            user = 'root'
        host = str(instance.public_dns_name)
        port = 22
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(AWSHostKeyPolicy(instance))
        known_hosts = self.ec2.known_hosts
        while 1:
            if os.path.exists(known_hosts):
                client.load_host_keys(known_hosts)
            try:
                client.connect(host, int(port), user)
                break
            except paramiko.BadHostKeyException:
                if os.path.exists(known_hosts):
                    os.remove(known_hosts)
                client.get_host_keys().clear()
        client.save_host_keys(known_hosts)
        return user, host, port, client, known_hosts

    def snapshot(self, devs=None):
        if devs is None:
            devs=set()
        else:
            devs=set(devs)
        volume_ids = [x[0] for x in self.config.get('volumes', []) if x[1] in devs]
        volumes = dict((x.id, x) for x in self.conn.get_all_volumes())
        for volume_id in volume_ids:
            volume = volumes[volume_id]
            date = datetime.datetime.now().strftime("%Y%m%d%H%M")
            description = "%s-%s" % (date, volume_id)
            log.info("Creating snapshot for volume %s on %s (%s)" % (volume_id, self.id, description))
            volume.create_snapshot(description=description)


class Server(object):
    def __init__(self, ec2, sid):
        self.id = sid
        self.ec2 = ec2
        self.config = self.ec2.config['server'][sid]

    def init_ssh_key(self, user=None):
        host = str(self.config['host'])
        port = 22
        client = paramiko.SSHClient()
        sshconfig = paramiko.SSHConfig()
        sshconfig.parse(open(os.path.expanduser('~/.ssh/config')))
        client.set_missing_host_key_policy(ServerHostKeyPolicy(self.config['fingerprint']))
        known_hosts = self.ec2.known_hosts
        while 1:
            if os.path.exists(known_hosts):
                client.load_host_keys(known_hosts)
            try:
                hostname = sshconfig.lookup(host).get('hostname', host)
                port = sshconfig.lookup(host).get('port', port)
                if user is None:
                    user = sshconfig.lookup(host).get('user', 'root')
                    user = self.config.get('user', user)
                client.connect(hostname, int(port), user)
                break
            except paramiko.BadHostKeyException:
                if os.path.exists(known_hosts):
                    os.remove(known_hosts)
                client.get_host_keys().clear()
        client.save_host_keys(known_hosts)
        return user, host, port, client, known_hosts


class EC2(object):
    def __init__(self, configpath):
        configpath = os.path.abspath(configpath)
        if not os.path.exists(configpath):
            log.error("Config '%s' doesn't exist." % configpath)
            sys.exit(1)
        if os.path.isdir(configpath):
            configpath = os.path.join(configpath, 'aws.conf')
        self.config = Config(configpath)
        self.known_hosts = os.path.join(self.config.path, 'known_hosts')
        self.instances = {}
        for sid in self.config.get('instance', {}):
            self.instances[sid] = Instance(self, sid)
        self.servers = {}
        for sid in self.config.get('server', {}):
            self.servers[sid] = Server(self, sid)
        intersection = set(self.instances).intersection(set(self.servers))
        if len(intersection) > 0:
            log.error("Instance and server names must be unique, the following names are duplicated:")
            log.error("\n".join(intersection))
            sys.exit(1)
        self.all = {}
        self.all.update(self.instances)
        self.all.update(self.servers)

    @lazy
    def credentials(self):
        aws_id = None
        aws_key = None
        if 'AWS_ACCESS_KEY_ID' not in os.environ or 'AWS_SECRET_ACCESS_KEY' not in os.environ:
            try:
                id_file = self.config['global']['aws']['access-key-id']
                key_file = self.config['global']['aws']['secret-access-key']
            except KeyError:
                log.error("You need to either set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or add the path to files containing them to the config. You can find the values at http://aws.amazon.com under 'Your Account'-'Security Credentials'.")
                sys.exit(1)
            id_file = os.path.abspath(os.path.expanduser(os.path.expandvars(id_file)))
            if not os.path.exists(id_file):
                log.error("The access-key-id file at '%s' doesn't exist." % id_file)
                sys.exit(1)
            key_file = os.path.abspath(os.path.expanduser(os.path.expendvars(key_file)))
            if not os.path.exists(key_file):
                log.error("The secret-access-key file at '%s' doesn't exist." % key_file)
                sys.exit(1)
            aws_id = open(id_file).readline().strip()
            aws_key = open(key_file).readline().strip()
        return (aws_id, aws_key)

    @lazy
    def regions(self):
        (aws_id, aws_key) = self.credentials
        return dict((x.name, x) for x in boto.ec2.regions(
            aws_access_key_id=aws_id, aws_secret_access_key=aws_key
        ))

    @property
    def snapshots(self):
        return dict((x.id, x) for x in self.conn.get_all_snapshots(owner="self"))

    @lazy
    def conn(self):
        (aws_id, aws_key) = self.credentials
        region_id = self.config.get(
                'global', {}).get(
                    'aws', {}).get(
                        'region', None)
        if region_id is None:
            log.error("No region set in global config")
            sys.exit(1)
        region = self.regions[region_id]
        return region.connect(
            aws_access_key_id=aws_id, aws_secret_access_key=aws_key
        )


class AWS(object):
    def __init__(self, configfile=None):
        log.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        log.addHandler(ch)
        if configfile is None:
            configfile = 'etc/aws.conf'
        self.configfile = configfile

    @lazy
    def ec2(self):
        if self.configfile is None:
            log.error("Config path not given (argument to this script).")
            sys.exit(1)
        return EC2(self.configfile)

    def _status(self, server):
        instance = server.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            return
        log.info("Instance running.")
        log.info("Instances DNS name %s", instance.dns_name)
        log.info("Instances public DNS name %s", instance.public_dns_name)
        output = instance.get_console_output().output
        if output.strip():
            log.info("Console output available. SSH fingerprint verification possible.")
        else:
            log.warn("Console output not (yet) available. SSH fingerprint verification not possible.")

    def cmd_status(self, argv, help):
        """Prints status"""
        parser = argparse.ArgumentParser(
            prog="aws status",
            description=help,
        )
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(self.ec2.instances))
        args = parser.parse_args(argv)
        server = self.ec2.instances[args.server[0]]
        return self._status(server)

    def cmd_stop(self, argv, help):
        """Stops the instance"""
        parser = argparse.ArgumentParser(
            prog="aws stop",
            description=help,
        )
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(self.ec2.instances))
        args = parser.parse_args(argv)
        server = self.ec2.instances[args.server[0]]
        instance = server.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            log.info("Instance not stopped")
            return
        try:
            rc = server.conn.stop_instances([instance.id])
            instance._update(rc[0])
        except EC2ResponseError, e:
            log.error(e.error_message)
            if 'cannot be stopped' in e.error_message:
                log.error("Did you mean to terminate the instance?")
            log.info("Instance not stopped")
            return
        log.info("Instance stopped")

    def cmd_terminate(self, argv, help):
        """Terminates the instance"""
        parser = argparse.ArgumentParser(
            prog="aws terminate",
            description=help,
        )
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(self.ec2.instances))
        args = parser.parse_args(argv)
        server = self.ec2.instances[args.server[0]]
        instance = server.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            log.info("Instance not terminated")
            return
        volumes_to_delete = []
        if 'snapshots' in server.config and server.config.get('delete-volumes-on-terminate', False):
            snapshots = self.ec2.snapshots
            volumes = dict((x.volume_id, d) for d, x in instance.block_device_mapping.items())
            for volume in server.conn.get_all_volumes(volume_ids=volumes.keys()):
                snapshot_id = volume.snapshot_id
                if snapshot_id in snapshots:
                    volumes_to_delete.append(volume)
        rc = server.conn.terminate_instances([instance.id])
        instance._update(rc[0])
        log.info("Instance terminating")
        if len(volumes_to_delete):
            log.info("Instance terminating, waiting until it's terminated")
            while instance.state != 'terminated':
                time.sleep(5)
                sys.stdout.write(".")
                sys.stdout.flush()
                instance.update()
            sys.stdout.write("\n")
            sys.stdout.flush()
            log.info("Instance terminated")
            for volume in volumes_to_delete:
                log.info("Deleting volume %s", volume.id)
                volume.delete()

    def _parse_overrides(self, options):
        overrides = dict()
        if options.overrides is not None:
            for override in options.overrides:
                if '=' not in override:
                    log.error("Invalid format for override '%s', should be NAME=VALUE." % override)
                    return
                key, value = override.split('=')
                key = key.strip()
                value = value.strip()
                if key == '':
                    log.error("Empty key for everride '%s'." % override)
                    return
                fname = 'massage_instance_%s' % key.replace('-', '_')
                massage = getattr(self.ec2.config, fname, None)
                if callable(massage):
                    overrides[key] = massage(value)
                else:
                    overrides[key] = value
        return overrides

    def cmd_start(self, argv, help):
        """Starts the instance"""
        parser = argparse.ArgumentParser(
            prog="aws start",
            description=help,
        )
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(self.ec2.instances))
        parser.add_argument("-o", "--override", nargs="*", type=str,
                            dest="overrides", metavar="OVERRIDE",
                            help="Option to override in server config for startup script (name=value).")
        args = parser.parse_args(argv)
        overrides = self._parse_overrides(args)
        server = self.ec2.instances[args.server[0]]
        server.config.update(overrides)
        instance = server.start()
        if instance is None:
            return
        return self._status(server)

    def cmd_debug(self, argv, help):
        """Prints some debug info for this script"""
        parser = argparse.ArgumentParser(
            prog="aws debug",
            description=help,
        )
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(self.ec2.instances))
        parser.add_argument("-v", "--verbose", dest="verbose",
                          action="store_true", help="Print more info")
        parser.add_argument("-i", "--interactive", dest="interactive",
                          action="store_true", help="Creates a connection and drops you into pdb")
        parser.add_argument("-o", "--override", nargs="*", type=str,
                            dest="overrides", metavar="OVERRIDE",
                            help="Option to override server config for startup script (name=value).")
        args = parser.parse_args(argv)
        overrides = self._parse_overrides(args)
        server = self.ec2.instances[args.server[0]]
        server.config.update(overrides)
        startup_script = server.startup_script(debug=True)
        log.info("Length of startup script: %s/%s", len(startup_script), 16*1024)
        if args.verbose:
            log.info("Startup script:")
            print startup_script,
        if args.interactive:
            import readline
            conn = server.conn
            instance = server.instance
            conn, instance # shutup pyflakes
            readline.parse_and_bind('tab: complete')
            __import__("code").interact(local=locals())

    def cmd_do(self, argv, help):
        """Do stuff on the cluster (using fabric)"""
        parser = argparse.ArgumentParser(
            prog="aws do",
            description=help,
            add_help=False,
        )
        parser.add_argument("server", nargs=1,
                            metavar="server",
                            help="Name of the instance or server from the config.",
                            choices=list(self.ec2.all))
        parser.add_argument("...", nargs=argparse.REMAINDER,
                            help="Fabric options")
        if len(argv) < 2:
            parser.print_help()
            return
        old_sys_argv = sys.argv
        old_cwd = os.getcwd()

        import fabric_integration
        # this needs to be done before any other fabric module import
        fabric_integration.patch()

        import fabric.state
        import fabric.main

        hoststr = None
        try:
            fabric_integration.ec2 = self.ec2
            fabric_integration.log = log
            hoststr = argv[0]
            server = self.ec2.all[hoststr]
            # prepare the connection
            fabric.state.env.reject_unknown_hosts = True
            fabric.state.env.disable_known_hosts = True

            fabfile = server.config.get('fabfile')
            if fabfile is None:
                log.error("No fabfile declared.")
                return
            newargv = ['fab', '-H', hoststr, '-r', '-D']
            if fabfile is not None:
                newargv = newargv + ['-f', fabfile]
            sys.argv = newargv + argv[1:]

            # setup environment
            os.chdir(os.path.dirname(fabfile))
            fabric.state.env.servers = self.ec2.all
            fabric.state.env.server = server
            known_hosts = self.ec2.known_hosts
            fabric.state.env.known_hosts = known_hosts

            class StdFilter(object):
                def __init__(self, org):
                    self.org = org
                    self.flush = self.org.flush

                def write(self, msg):
                    lines = msg.split('\n')
                    prefix = '[%s] ' % fabric.state.env.host_string
                    for index, line in enumerate(lines):
                        if line.startswith(prefix):
                            lines[index] = line[len(prefix):]
                    self.org.write('\n'.join(lines))

            sys.stdout = StdFilter(sys.stdout)
            sys.stderr = StdFilter(sys.stderr)

            fabric.main.main()
        finally:
            if fabric.state.connections.opened(hoststr):
                fabric.state.connections[hoststr].close()
            sys.argv = old_sys_argv
            os.chdir(old_cwd)

    def cmd_list(self, argv, help):
        """Return a list of various AWS things"""
        parser = argparse.ArgumentParser(
            prog="aws ssh",
            description=help,
        )
        parser.add_argument("list", nargs=1,
                            metavar="list",
                            help="Name of list to show.",
                            choices=['snapshots'])
        args = parser.parse_args(argv)
        if args.list[0] == 'snapshots':
            snapshots = self.ec2.snapshots.values()
            snapshots = sorted(snapshots, key=lambda x: x.start_time)
            print "id            time                      size   volume       progress description"
            for snapshot in snapshots:
                info = snapshot.__dict__
                print "{id} {start_time} {volume_size:>4} GB {volume_id} {progress:>8} {description}".format(**info)

    def cmd_ssh(self, argv, help):
        """Log into the server with ssh using the automatically generated known hosts"""
        parser = argparse.ArgumentParser(
            prog="aws ssh",
            description=help,
        )
        parser.add_argument("server", nargs=1,
                            metavar="server",
                            help="Name of the instance or server from the config.",
                            choices=list(self.ec2.all))
        parser.add_argument("...", nargs=argparse.REMAINDER,
                            help="Fabric options")
        iargs = enumerate(argv)
        sid_index = None
        for i, arg in iargs:
            if not arg.startswith('-'):
                sid_index = i
                break
            else:
                if arg[1] in '1246AaCfgKkMNnqsTtVvXxYy':
                    continue
                elif arg[1] in 'bcDeFiLlmOopRSw':
                    continue
        if sid_index is None:
            parser.print_help()
            return
        server = self.ec2.all[argv[sid_index]]
        try:
            user, host, port, client, known_hosts = server.init_ssh_key()
        except paramiko.SSHException, e:
            log.error("Couldn't validate fingerprint for ssh connection.")
            log.error(e)
            log.error("Is the server finished starting up?")
            return
        client.close()
        argv[sid_index:sid_index+1] = ['-o', 'UserKnownHostsFile=%s' % known_hosts,
                                       '-l', user,
                                       host]
        argv[0:0] = ['ssh']
        subprocess.call(argv)

    def cmd_snapshot(self, argv, help):
        """Creates a snapshot of the volumes specified in the configuration"""
        parser = argparse.ArgumentParser(
            prog="aws status",
            description=help,
        )
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(self.ec2.instances))
        args = parser.parse_args(argv)
        server = self.ec2.instances[args.server[0]]
        server.snapshot()

    def cmd_help(self, argv, help):
        """Print help"""
        parser = argparse.ArgumentParser(
            prog="aws help",
            description=help,
        )
        parser.add_argument('-z', '--zsh',
                            action='store_true',
                            help="Print info for zsh autocompletion")
        parser.add_argument("command", nargs='?',
                            metavar="command",
                            help="Name of the command you want help for.",
                            choices=self.subparsers.keys())
        args = parser.parse_args(argv)
        if args.zsh:
            if args.command is None:
                for cmd in self.subparsers.keys():
                    print cmd
            else:
                if args.command != 'help':
                    for server in self.ec2.instances:
                        print server
        else:
            if args.command is None:
                parser.print_help()
            else:
                cmd = getattr(self, "cmd_%s" % args.command)
                cmd(['-h'], cmd.__doc__)

    def __call__(self, argv):
        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        parser.add_argument('-c', '--config',
                            dest="configfile",
                            default=self.configfile,
                            help="Use the specified config file.")

        version = pkg_resources.get_distribution("mr.awsome").version
        parser.add_argument('-v', '--version',
                            action='version',
                            version='mr.awsome %s' % version,
                            help="Print version and exit")

        cmds = [x[4:] for x in dir(self) if x.startswith('cmd_')]
        cmdparsers = parser.add_subparsers(title="commands")
        self.subparsers = {}
        for cmdname in cmds:
            cmd = getattr(self, "cmd_%s" % cmdname)
            subparser = cmdparsers.add_parser(cmdname, help=cmd.__doc__)
            subparser.set_defaults(func=cmd)
            self.subparsers[cmdname] = subparser
        main_argv = []
        for arg in argv:
            main_argv.append(arg)
            if arg in cmds:
                break
        sub_argv = argv[len(main_argv):]
        args = parser.parse_args(main_argv[1:])
        if args.configfile is not None:
            self.configfile = args.configfile
        args.func(sub_argv, args.func.__doc__)


def aws(configpath=None):
    argv = sys.argv[:]
    aws = AWS(configfile=configpath)
    return aws(argv)

def aws_ssh(configpath=None):
    argv = sys.argv[:]
    argv.insert(1, "ssh")
    aws = AWS(configfile=configpath)
    return aws(argv)
