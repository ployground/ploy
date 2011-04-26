from mr.awsome import template
from mr.awsome.common import gzip_string
from mr.awsome.lazy import lazy
import datetime
import logging
import os
import sys
import time


log = logging.getLogger('mr.awsome.ec2')


class Instance(object):
    def __init__(self, ec2, sid):
        self.id = sid
        self.ec2 = ec2
        self.config = self.ec2.config['ec2-instance'][sid]

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

    def get_config(self, overrides=None):
        massagers = get_massagers()
        if overrides is None:
            overrides = {}
        config = self.config.copy()
        for key in overrides:
            massage = massagers.get(('ec2-instance', key))
            if callable(massage):
                config[key] = massage(self.ec2.config, overrides[key])
        return config

    def get_host(self):
        return self.instance.public_dns_name

    def startup_script(self, overrides=None, debug=False):
        config = self.get_config(overrides)
        startup_script_path = config.get('startup_script', None)
        if startup_script_path is None:
            return ''
        startup_script = template.Template(
            startup_script_path['path'],
            pre_filter=template.strip_hashcomments,
        )
        result = startup_script(**config)
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

    def status(self):
        instance = self.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            return
        log.info("Instance running.")
        log.info("Instances DNS name %s", instance.dns_name)
        log.info("Instances private DNS name %s", instance.private_dns_name)
        log.info("Instances public DNS name %s", instance.public_dns_name)
        output = instance.get_console_output().output
        if output.strip():
            log.info("Console output available. SSH fingerprint verification possible.")
        else:
            log.warn("Console output not (yet) available. SSH fingerprint verification not possible.")

    def stop(self):
        from boto.exception import EC2ResponseError

        instance = self.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            log.info("Instance not stopped")
            return
        try:
            rc = self.conn.stop_instances([instance.id])
            instance._update(rc[0])
        except EC2ResponseError, e:
            log.error(e.error_message)
            if 'cannot be stopped' in e.error_message:
                log.error("Did you mean to terminate the instance?")
            log.info("Instance not stopped")
            return
        log.info("Instance stopped")

    def terminate(self):
        instance = self.instance
        if instance is None:
            return
        if instance.state != 'running':
            log.info("Instance state: %s", instance.state)
            log.info("Instance not terminated")
            return
        volumes_to_delete = []
        if 'snapshots' in self.config and self.config.get('delete-volumes-on-terminate', False):
            snapshots = {}
            for master in self.get_masters('snapshots'):
                snapshots.update(master.snapshots)
            volumes = dict((x.volume_id, d) for d, x in instance.block_device_mapping.items())
            for volume in self.conn.get_all_volumes(volume_ids=volumes.keys()):
                snapshot_id = volume.snapshot_id
                if snapshot_id in snapshots:
                    volumes_to_delete.append(volume)
        rc = self.conn.terminate_instances([instance.id])
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

    def start(self, overrides=None):
        config = self.get_config(overrides)
        instance = self.instance
        if instance is not None:
            log.info("Instance state: %s", instance.state)
            log.info("Instance already started, waiting until it's available")
        else:
            log.info("Creating instance '%s'" % self.id)
            reservation = self.image().run(
                1, 1, config['keypair'],
                instance_type=config.get('instance_type', 'm1.small'),
                security_groups=self.securitygroups(),
                user_data=self.startup_script(),
                placement=config['placement']
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
        ip = config.get('ip', None)
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
        for volume_id, device in config.get('volumes', []):
            if volume_id not in volumes:
                log.error("Unknown volume %s" % volume_id)
                return
            volume = volumes[volume_id]
            if volume.attachment_state() == 'attached':
                continue
            log.info("Attaching storage (%s on %s)" % (volume_id, device))
            self.conn.attach_volume(volume_id, instance.id, device)

        snapshots = dict((x.id, x) for x in self.conn.get_all_snapshots(owner="self"))
        for snapshot_id, device in config.get('snapshots', []):
            if snapshot_id not in snapshots:
                log.error("Unknown snapshot %s" % snapshot_id)
                return
            log.info("Creating volume from snapshot: %s" % snapshot_id)
            snapshot = snapshots[snapshot_id]
            volume = self.conn.create_volume(snapshot.volume_size, config['placement'], snapshot_id)
            log.info("Attaching storage (%s on %s)" % (volume.id, device))
            self.conn.attach_volume(volume.id, instance.id, device)

        return instance

    def init_ssh_key(self, user=None):
        import paramiko

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


class Securitygroups(object):
    def __init__(self, server):
        self.server = server
        self.update()

    def update(self):
        self.securitygroups = dict((x.name, x) for x in self.server.conn.get_all_security_groups())

    def get(self, sgid, create=False):
        if not 'ec2-securitygroup' in self.server.ec2.config:
            log.error("No security groups defined in configuration.")
            sys.exit(1)
        securitygroup = self.server.ec2.config['ec2-securitygroup'][sgid]
        if sgid not in self.securitygroups:
            if not create:
                raise KeyError
            sg = self.server.conn.create_security_group(sgid, securitygroup['description'])
            self.update()
        else:
            sg = self.securitygroups[sgid]
        if create:
            from boto.ec2.securitygroup import GroupOrCIDR

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


class Master(object):
    def __init__(self, config, id):
        self.id = id
        self.config = config
        self.known_hosts = os.path.join(self.config.path, 'known_hosts')
        self.instances = {}
        for sid in self.config.get('ec2-instance', {}):
            self.instances[sid] = Instance(self, sid)

    @lazy
    def credentials(self):
        aws_id = None
        aws_key = None
        if 'AWS_ACCESS_KEY_ID' not in os.environ or 'AWS_SECRET_ACCESS_KEY' not in os.environ:
            try:
                id_file = self.config['ec2-master']['default']['access-key-id']
                key_file = self.config['ec2-master']['default']['secret-access-key']
            except KeyError:
                log.error("You need to either set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or add the path to files containing them to the config. You can find the values at http://aws.amazon.com under 'Your Account'-'Security Credentials'.")
                sys.exit(1)
            id_file = os.path.abspath(os.path.expanduser(id_file))
            if not os.path.exists(id_file):
                log.error("The access-key-id file at '%s' doesn't exist." % id_file)
                sys.exit(1)
            key_file = os.path.abspath(os.path.expanduser(key_file))
            if not os.path.exists(key_file):
                log.error("The secret-access-key file at '%s' doesn't exist." % key_file)
                sys.exit(1)
            aws_id = open(id_file).readline().strip()
            aws_key = open(key_file).readline().strip()
        return (aws_id, aws_key)

    @lazy
    def regions(self):
        import boto.ec2

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
                'ec2-master', {}).get(
                    'default', {}).get(
                        'region', None)
        if region_id is None:
            log.error("No region set in ec2-master:default config")
            sys.exit(1)
        region = self.regions[region_id]
        return region.connect(
            aws_access_key_id=aws_id, aws_secret_access_key=aws_key
        )


def get_massagers():
    def massage_instance_fabfile(config, value):
        if not os.path.isabs(value):
            value = os.path.join(config.path, value)
        return value

    def massage_instance_startup_script(config, value):
        result = dict()
        if value.startswith('gzip:'):
            value = value[5:]
            result['gzip'] = True
        if not os.path.isabs(value):
            value = os.path.join(config.path, value)
        result['path'] = value
        return result

    def massage_instance_securitygroups(config, value):
        securitygroups = []
        for securitygroup in value.split(','):
            securitygroups.append(securitygroup.strip())
        return set(securitygroups)

    def massage_instance_volumes(config, value):
        volumes = []
        for line in value.split('\n'):
            volume = line.split()
            if not len(volume):
                continue
            volumes.append((volume[0], volume[1]))
        return tuple(volumes)

    def massage_instance_snapshots(config, value):
        snapshots = []
        for line in value.split('\n'):
            snapshot = line.split()
            if not len(snapshot):
                continue
            snapshots.append((snapshot[0], snapshot[1]))
        return tuple(snapshots)

    def massage_instance_delete_volumes_on_terminate(config, value):
        if value.lower() in ('true', 'yes', 'on'):
            return True
        elif value.lower() in ('false', 'no', 'off'):
            return False
        raise ValueError("Unknown value %s for delete-volumes-on-terminate." % value)

    def massage_securitygroup_connections(config, value):
        connections = []
        for line in value.split('\n'):
            connection = line.split()
            if not len(connection):
                continue
            connections.append((connection[0], int(connection[1]),
                                int(connection[2]), connection[3]))
        return tuple(connections)

    return {
        ("ec2-instance", 'fabfile'): massage_instance_fabfile,
        ("ec2-instance", 'startup_script'): massage_instance_startup_script,
        ("ec2-instance", 'securitygroups'): massage_instance_securitygroups,
        ("ec2-instance", 'volumes'): massage_instance_volumes,
        ("ec2-instance", 'snapshots'): massage_instance_snapshots,
        ("ec2-instance", 'delete-volumes-on-terminate'): massage_instance_delete_volumes_on_terminate,
        ("ec2-securitygroup", 'connections'): massage_securitygroup_connections}


def get_macro_cleaners(config):
    def clean_instance(macro):
        for key in macro.keys():
            if key in ('ip', 'volumes'):
                del macro[key]

    return {"ec2-instance": clean_instance}


def get_masters(config):
    masters = config.get('ec2-master', {})
    for master in masters:
        yield Master(config, master)
