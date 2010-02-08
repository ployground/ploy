from ConfigParser import RawConfigParser
from boto.ec2.securitygroup import GroupOrCIDR
from StringIO import StringIO
from textwrap import dedent
import boto.ec2
import datetime
import email
import fabric.main
import fabric.network
import fabric.state
import gzip
import logging
import paramiko
import optparse
import os
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


class Config(dict):
    def massage_instance_securitygroups(self, value):
        securitygroups = []
        for securitygroup in value.split(','):
            securitygroups.append(securitygroup.strip())
        return set(securitygroups)

    def massage_instance_volumes(self, value):
        volumes = []
        for line in value.split('\n'):
            volume = line.split()
            if not len(volume):
                continue
            volumes.append((volume[0], volume[1]))
        return tuple(volumes)

    def massage_securitygroup_connections(self, value):
        connections = []
        for line in value.split('\n'):
            connection = line.split()
            if not len(connection):
                continue
            connections.append((connection[0], int(connection[1]),
                                int(connection[2]), connection[3]))
        return tuple(connections)

    def __init__(self, configs):
        _config = RawConfigParser()
        _config.optionxform = lambda s: s
        _config.read(configs)
        for section in _config.sections():
            sectiongroupname, sectionname = section.split(':')
            items = dict(_config.items(section))
            sectiongroup = self.setdefault(sectiongroupname, {})
            sectiongroup.setdefault(sectionname, {}).update(items)
        for sectiongroupname in self:
            sectiongroup = self[sectiongroupname]
            for sectionname in sectiongroup:
                section = sectiongroup[sectionname]
                for key in section:
                    fname = 'massage_%s_%s' % (sectiongroupname, key)
                    massage = getattr(self, fname, None)
                    if callable(massage):
                        section[key] = massage(section[key])


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


class Template(object):
    def __init__(self, path):
        self.path = path
        self.template = email.message_from_file(open(path))

    def __call__(self, **kwargs):
        options = {}
        for key, value in self.template.items():
            commands, value = value.rsplit(None, 1)
            for cmd in commands.split(','):
                if cmd == 'file':
                    path = value
                    if not os.path.isabs(path):
                        path = os.path.join(os.path.dirname(self.path), path)
                    value = open(path).read()
                elif cmd == 'base64':
                    value = value.encode("base64")
                elif cmd == 'format':
                    value = value.format(**kwargs)
                elif cmd == 'template':
                    path = value
                    if not os.path.isabs(path):
                        path = os.path.join(os.path.dirname(self.path), path)
                    value = Template(path)(**kwargs)
                elif cmd == 'gzip':
                    s = StringIO()
                    gz = gzip.GzipFile(mode='wb', fileobj=s)
                    gz.write(value)
                    gz.close()
                    value = s.getvalue()
                elif cmd == 'escape_eol':
                    value = value.replace('\n', '\\n')
                else:
                    raise ValueError("Unknown command '%s' for option '%s' in startup script '%s'." % (cmd, key, self.path))
            options[key] = value
        for key in kwargs:
            options[key] = kwargs[key]
        return self.template.get_payload().format(**options)


class Server(object):
    def __init__(self, ec2, sid):
        self.id = sid
        self.ec2 = ec2
        self.config = self.ec2.config['instance'][sid]
        self._securitygroups = Securitygroups(self)

    @property
    def conn(self):
        conn = getattr(self, '_conn', None)
        if conn is not None:
            return conn
        regions = dict((x.name, x) for x in boto.ec2.regions())
        self._conn = regions[self.config['region']].connect()
        return self._conn

    @property
    def instance(self):
        instance = getattr(self, '_instance', None)
        if instance is not None:
            return instance
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
        self._instance = instances[0]
        return self._instance

    def image(self):
        images = self.conn.get_all_images([self.config['image']])
        return images[0]

    def securitygroups(self):
        sgs = []
        for sgid in self.config['securitygroups']:
            sgs.append(self._securitygroups.get(sgid, create=True))
        return sgs

    def startup_script(self, overrides):
        startup_script_path = self.config['startup_script']
        if not os.path.isabs(startup_script_path):
            startup_script_path = os.path.join(self.ec2.configpath,
                                               startup_script_path)
        startup_script = Template(startup_script_path)
        result = startup_script(
            servers=self.ec2.servers,
            tag=overrides.get('tag', self.config.get('tag')),
        )
        if len(result) >= 16*1024:
            log.error("Startup script too big.")
            sys.exit(1)
        return result

    def start(self, overrides={}):
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
                user_data=self.startup_script(overrides),
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
                log.error("Unkown volume %s" % volume_id)
                return
            volume = volumes[volume_id]
            if volume.attachment_state() == 'attached':
                continue
            log.info("Attaching storage (%s on %s)" % (volume_id, device))
            self.conn.attach_volume(volume_id, instance.id, device)
        return instance

    def init_ssh_key(self, user=None):
        fabric.state.env.reject_unknown_hosts = True
        fabric.state.env.disable_known_hosts = True
        #user, host, port = fabric.network.normalize(hoststr)
        instance = self.instance
        if user is None:
            user = 'root'
        host = str(instance.public_dns_name)
        port = 22
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(AWSHostKeyPolicy(instance))
        known_hosts = os.path.join(self.ec2.configpath, 'known_hosts')
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
        # store the connection in the fabric connection cache
        real_key = fabric.network.join_host_strings(user, host, port)
        fabric.state.connections[real_key] = client
        return real_key, known_hosts


class Servers(object):
    def __init__(self, ec2):
        self.ec2 = ec2
        self._cache = {}

    def __iter__(self):
        instances = self.ec2.config.get('instance')
        if instances is None:
            log.error("No instances defined in configuration file.")
            sys.exit(1)
        return iter(instances)

    def __getitem__(self, sid):
        if sid not in self._cache:
            self._cache[sid] = Server(self.ec2, sid)
        return self._cache[sid]


class EC2(object):
    def __init__(self, configpath):
        if not os.path.exists(configpath):
            log.error("Config path '%s' doesn't exist." % configpath)
            sys.exit(1)
        self.configpath = configpath
        self.config = Config(os.path.join(self.configpath, 'aws.conf'))
        self.servers = Servers(self)


class AWS(object):
    def __init__(self):
        log.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        log.addHandler(ch)
        if 'AWS_ACCESS_KEY_ID' not in os.environ or 'AWS_SECRET_ACCESS_KEY' not in os.environ:
            log.error("You need to set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables. You can find the values at http://aws.amazon.com under 'Your Account'-'Security Credentials'.")
            sys.exit(1)

    def list_servers(self):
        print("Available servers:")
        for sid in self.ec2.servers:
            print("    %s" % sid)

    def cmd_help(self):
        """Prints usage"""
        print dedent("""\
        Usage: develop <command> [server and/or options]
               develop <server> <command> [options]

        Available commands:""")
        for key in dir(self):
            if key.startswith('cmd_'):
                print "    %-16s%s" % (key[4:], getattr(getattr(self, key), '__doc__'))

    def cmd_status(self):
        """Prints status"""
        parser = optparse.OptionParser(
            usage="%prog status <server>",
        )
        options, args = parser.parse_args(sys.argv[2:])
        if len(args) < 1:
            print parser.format_help()
            self.list_servers()
            return
        if len(args) > 1:
            log.error("You need to specify exactly one server")
            return
        server = self.ec2.servers[args[0]]
        instance = server.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            return
        log.info("Instance running.")
        log.info("Instances DNS name %s", instance.dns_name)
        log.info("Instances public DNS name %s", instance.public_dns_name)

    def cmd_stop(self):
        """Stops the instance"""
        parser = optparse.OptionParser(
            usage="%prog stop <server>",
        )
        options, args = parser.parse_args(sys.argv[2:])
        if len(args) < 1:
            print parser.format_help()
            self.list_servers()
            return
        if len(args) > 1:
            log.error("You need to specify exactly one server")
            return
        server = self.ec2.servers[args[0]]
        instance = server.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            log.info("Instance not stopped")
            return
        instance.stop()
        log.info("Instance stopped")

    def cmd_start(self):
        """Starts the instance"""
        overrides = dict()
        parser = optparse.OptionParser(
            usage="%prog start [options] <server>",
        )
        parser.add_option("-r", "--revision", dest="revision",
                          metavar="REV", help="The revision which should be checked out.")
        options, args = parser.parse_args(sys.argv[2:])
        if options.revision is not None:
            overrides['tag'] = options.revision
        if len(args) < 1:
            print parser.format_help()
            self.list_servers()
            return
        if len(args) > 1:
            log.error("You need to specify exactly one server")
            return
        server = self.ec2.servers[args[0]]
        instance = server.start(overrides)
        if instance is None:
            return
        self.cmd_status()

    def cmd_debug(self):
        """Prints some debug info for this script"""
        overrides = dict()
        parser = optparse.OptionParser(
            usage="%prog debug [options] <server>",
        )
        parser.add_option("-v", "--verbose", dest="verbose",
                          action="store_true", help="Print more info")
        parser.add_option("-i", "--interactive", dest="interactive",
                          action="store_true", help="Creates a connection and drops you into pdb")
        parser.add_option("-r", "--revision", dest="revision",
                          metavar="REV", help="The revision which should be checked out.")
        options, args = parser.parse_args(sys.argv[2:])
        if options.revision is not None:
            overrides['tag'] = options.revision
        if len(args) < 1:
            print parser.format_help()
            self.list_servers()
            return
        if len(args) > 1:
            log.error("You need to specify exactly one server")
            return
        server = self.ec2.servers[args[0]]
        log.info("Length of startup script: %s/%s", len(server.startup_script(overrides)), 16*1024)
        if options.verbose:
            log.info("Startup script:\n%s", server.startup_script(overrides))
        if options.interactive:
            conn = server.conn
            instance = server.instance
            from pdb import set_trace
            set_trace()

    def cmd_do(self):
        """Do stuff on the cluster (using fabric)"""
        parser = optparse.OptionParser(
            usage="%prog do <server> [fabric options]",
        )

        if len(sys.argv) < 3:
            print parser.format_help()
            self.list_servers()
            return
        old_sys_argv = sys.argv
        old_cwd = os.getcwd()
        hoststr = None
        try:
            sid = sys.argv[2]
            server = self.ec2.servers[sid]
            try:
                hoststr, known_hosts = server.init_ssh_key()
            except paramiko.SSHException:
                log.error("Couldn't validate fingerprint for ssh connection. Is the server finished starting up?")
                return
            fabfile = server.config.get('fabfile')
            if fabfile is None:
                log.error("No fabfile declared.")
                return
            newargv = ['fab', '-H', hoststr]
            if fabfile is not None:
                if not os.path.isabs(fabfile):
                    fabfile = os.path.join(self.ec2.configpath, fabfile)
                newargv = newargv + ['-f', fabfile]
            sys.argv = newargv + sys.argv[3:]

            # setup environment
            os.chdir(os.path.dirname(fabfile))
            fabric.state.env.servers = self.ec2.servers
            fabric.state.env.server = server
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
            if hoststr is not None:
                fabric.state.connections[hoststr].close()
            sys.argv = old_sys_argv

    def cmd_ssh(self):
        """Log into the server with ssh using the automatically generated known hosts"""
        parser = optparse.OptionParser(
            usage="%prog ssh <server>",
        )
        args = sys.argv[2:]
        iargs = enumerate(args)
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
            print parser.format_help()
            self.list_servers()
            return
        server = self.ec2.servers[args[sid_index]]
        try:
            hoststr, known_hosts = server.init_ssh_key()
        except paramiko.SSHException:
            log.error("Couldn't validate fingerprint for ssh connection. Is the server finished starting up?")
            return
        fabric.state.connections[hoststr].close()
        user, host, port = fabric.network.normalize(hoststr)
        known_hosts = os.path.join(self.ec2.configpath, 'known_hosts')
        args[sid_index:sid_index+1] = ['-o', 'UserKnownHostsFile=%s' % known_hosts,
                                       '-l', user,
                                       host]
        args[0:0] = ['ssh']
        subprocess.call(args)

    def cmd_snapshot(self):
        """Creates a snapshot of the volumes specified in the configuration"""
        parser = optparse.OptionParser(
            usage="%prog snapshot <id>",
        )
        options, args = parser.parse_args(sys.argv[2:])
        if len(args) < 1:
            print parser.format_help()
            self.list_servers()
            return
        if len(args) > 1:
            log.error("You need to specify exactly one server")
            return
        sid = args[0]
        server = self.ec2.servers[sid]
        volume_ids = [x[0] for x in server.config.get('volumes', [])]
        volumes = dict((x.id, x) for x in server.conn.get_all_volumes())
        for volume_id in volume_ids:
            volume = volumes[volume_id]
            date = datetime.datetime.now().strftime("%Y%m%d%H%M")
            description = "%s-%s" % (date, volume_id)
            log.info("Creating snapshot for volume %s on %s (%s)" % (volume_id, sid, description))
            volume.create_snapshot(description=description)

    def __call__(self, configpath=None):
        if configpath is None:
            log.error("Config path not given (argument to this script).")
            sys.exit(1)
        self.ec2 = EC2(configpath)
        if len(sys.argv) < 2:
            self.cmd_help()
        else:
            cmd = getattr(self, "cmd_%s" % sys.argv[1], None)
            if cmd is None:
                arg = sys.argv[1]
                if arg in self.ec2.servers:
                    del sys.argv[1]
                    sys.argv.insert(2, arg)
                    cmd = getattr(self, "cmd_%s" % sys.argv[1], self.unknown)
                else:
                    cmd = self.unknown
            cmd()

    def ssh(self, configpath=None):
        sys.argv.insert(1, "ssh")
        self(configpath=configpath)

    def unknown(self):
        log.error("Unknown command '%s'." % sys.argv[1])
        log.info("Type '%s help' for usage." % os.path.basename(sys.argv[0]))
        sys.exit(1)


aws = AWS()
aws_ssh = aws.ssh
