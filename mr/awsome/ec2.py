from lazy import lazy
from mr.awsome.common import BaseMaster, FabricMixin, StartupScriptMixin
from mr.awsome.config import BaseMassager, BooleanMassager
from mr.awsome.config import HooksMassager, PathMassager
from mr.awsome.config import StartupScriptMassager
import datetime
import logging
import os
import sys
import time


log = logging.getLogger('mr.awsome.ec2')


class InitSSHKeyMixin(object):
    def init_ssh_key(self, user=None):
        try:  # pragma: no cover - we support both
            import paramiko
            paramiko  # shutup pyflakes
        except ImportError:  # pragma: no cover - we support both
            import ssh as paramiko

        class AWSHostKeyPolicy(paramiko.MissingHostKeyPolicy):
            def __init__(self, instance):
                self.instance = instance

            def missing_host_key(self, client, hostname, key):
                fingerprint = ':'.join("%02x" % ord(x) for x in key.get_fingerprint())
                if self.instance.public_dns_name == hostname:
                    output = self.instance.get_console_output().output
                    if output is None or output.strip() == '':
                        raise paramiko.SSHException('No console output (yet) for %s' % hostname)
                    if fingerprint in output:
                        client._host_keys.add(hostname, key.get_name(), key)
                        if client._host_keys_filename is not None:
                            client.save_host_keys(client._host_keys_filename)
                        return
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
        client_args = dict(
            port=int(port),
            username=user,
            key_filename=self.config.get('ssh-key-filename', None))
        known_hosts = self.master.known_hosts
        while 1:
            if os.path.exists(known_hosts):
                client.load_host_keys(known_hosts)
            try:
                client.connect(host, **client_args)
                break
            except paramiko.BadHostKeyException:
                if os.path.exists(known_hosts):
                    os.remove(known_hosts)
                client.get_host_keys().clear()
        client.save_host_keys(known_hosts)
        return dict(
            user=user,
            host=host,
            port=port,
            client=client,
            UserKnownHostsFile=known_hosts)


class ConnMixin(object):
    @lazy
    def conn(self):
        region_id = self.config.get(
            'region',
            self.master.master_config.get('region', None))
        if region_id is None:
            log.error("No region set in ec2-instance:%s or ec2-master:%s config" % (self.id, self.master.id))
            sys.exit(1)
        return self.master.get_conn(region_id)


class Instance(FabricMixin, StartupScriptMixin, InitSSHKeyMixin, ConnMixin):
    max_startup_script_size = 16 * 1024

    def __init__(self, master, sid, config):
        self.id = sid
        self.master = master
        self.config = config

    @lazy
    def instance(self):
        instances = []
        for reservation in self.conn.get_all_instances():
            groups = set(x.name for x in reservation.groups)
            for instance in reservation.instances:
                if instance.state in ['shutting-down', 'terminated']:
                    continue
                tags = getattr(instance, 'tags', {})
                if not tags or not tags.get('Name'):
                    if groups != self.config['securitygroups']:
                        continue
                else:
                    if tags['Name'] != self.id:
                        continue
                instances.append(instance)
        if len(instances) < 1:
            log.info("Instance '%s' unavailable.", self.id)
            return
        elif len(instances) > 1:
            log.warn("More than one instance found, using first.")
        instance = instances[0]
        log.info("Instance '%s' (%s) available.", self.id, instance.id)
        return instance

    def image(self):
        images = self.conn.get_all_images([self.config['image']])
        return images[0]

    def securitygroups(self):
        securitygroups = getattr(self, '_securitygroups', None)
        if securitygroups is None:
            self._securitygroups = securitygroups = Securitygroups(self)
        sgs = []
        for sgid in self.config.get('securitygroups', []):
            sgs.append(securitygroups.get(sgid, create=True))
        return sgs

    def get_host(self):
        return self.instance.public_dns_name

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
        if instance.state not in ('running', 'stopped'):
            log.info("Instance state: %s", instance.state)
            log.info("Instance not terminated")
            return
        volumes_to_delete = []
        if 'snapshots' in self.config and self.config.get('delete-volumes-on-terminate', False):
            snapshots = self.master.snapshots
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
            if instance.state == 'stopping':
                log.info("The instance is currently stopping")
                return
            if instance.state == 'stopped':
                log.info("Starting stopped instance '%s'" % self.id)
                instance.modify_attribute('instanceType', config.get('instance_type', 'm1.small'))
                instance.modify_attribute('blockDeviceMapping', config.get('device_map', None))
                instance.start()
            else:
                log.info("Instance already started, waiting until it's available")
        else:
            log.info("Creating instance '%s'" % self.id)
            reservation = self.image().run(
                1, 1, config['keypair'],
                instance_type=config.get('instance_type', 'm1.small'),
                block_device_map=config.get('device_map', None),
                security_groups=self.securitygroups(),
                user_data=self.startup_script(overrides=overrides),
                placement=config['placement']
            )
            instance = reservation.instances[0]
            log.info("Instance created, waiting until it's available")
        while instance.state != 'running':
            if instance.state != 'pending':
                log.error("Something went wrong, instance status: %s", instance.state)
                return
            time.sleep(5)
            sys.stdout.write(".")
            sys.stdout.flush()
            instance.update()
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.conn.create_tags([instance.id], {"Name": self.id})
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

    def snapshot(self, devs=None):
        if devs is None:
            devs = set()
        else:
            devs = set(devs)
        volume_ids = [x[0] for x in self.config.get('volumes', []) if x[1] in devs]
        volumes = dict((x.id, x) for x in self.conn.get_all_volumes())
        for volume_id in volume_ids:
            volume = volumes[volume_id]
            date = datetime.datetime.now().strftime("%Y%m%d%H%M")
            description = "%s-%s" % (date, volume_id)
            log.info("Creating snapshot for volume %s on %s (%s)" % (volume_id, self.id, description))
            volume.create_snapshot(description=description)


class Connection(InitSSHKeyMixin, ConnMixin):
    """ This is more or less a dummy object to get a connection to AWS for
        Fabric scripts. """
    def __init__(self, master, sid, config):
        self.id = sid
        self.master = master
        self.config = config

    def get_host(self):
        return None


class Securitygroups(object):
    def __init__(self, server):
        self.server = server
        self.update()

    def update(self):
        self.securitygroups = dict((x.name, x) for x in self.server.conn.get_all_security_groups())

    def get(self, sgid, create=False):
        if not 'ec2-securitygroup' in self.server.master.main_config:
            log.error("No security groups defined in configuration.")
            sys.exit(1)
        securitygroup = self.server.master.main_config['ec2-securitygroup'][sgid]
        if sgid not in self.securitygroups:
            if not create:
                raise KeyError
            if 'description' in securitygroup:
                description = securitygroup['description']
            else:
                description = "security settings for %s" % sgid
            sg = self.server.conn.create_security_group(sgid, description)
            self.update()
        else:
            sg = self.securitygroups[sgid]
        if create:
            from boto.ec2.securitygroup import GroupOrCIDR

            rules = {}
            for rule in sg.rules:
                for grant in rule.grants:
                    if grant.cidr_ip:
                        key = (
                            rule.ip_protocol,
                            int(rule.from_port),
                            int(rule.to_port),
                            grant.cidr_ip)
                    else:
                        key = (
                            rule.ip_protocol,
                            int(rule.from_port),
                            int(rule.to_port),
                            grant.name)
                    rules[key] = (rule, grant)
            # cleanup rules from config
            connections = []
            for connection in securitygroup['connections']:
                if connection[3].endswith("-%s" % sg.owner_id):
                    # backward compatibility, strip the owner_id
                    connection = (
                        connection[0],
                        connection[1],
                        connection[2],
                        connection[3].rstrip("-%s" % sg.owner_id))
                connections.append(connection)
            # delete rules which aren't defined in the config
            for connection in set(rules).difference(connections):
                rule, grant = rules[connection]
                status = sg.revoke(
                    ip_protocol=rule.ip_protocol,
                    from_port=int(rule.from_port),
                    to_port=int(rule.to_port),
                    cidr_ip=grant.cidr_ip,
                    src_group=grant)
                if status:
                    del rules[connection]
            for connection in connections:
                if connection in rules:
                    continue
                cidr_ip = None
                src_group = None
                if '/' in connection[3]:
                    cidr_ip = connection[3]
                else:
                    src_group = GroupOrCIDR()
                    src_group.name = connection[3]
                    src_group.ownerid = sg.owner_id
                sg.authorize(
                    ip_protocol=connection[0],
                    from_port=connection[1],
                    to_port=connection[2],
                    cidr_ip=cidr_ip,
                    src_group=src_group)
        return sg


class Master(BaseMaster):
    section_info = {
        'ec2-instance': Instance,
        'ec2-connection': Connection}

    @lazy
    def credentials(self):
        aws_id = None
        aws_key = None
        if 'AWS_ACCESS_KEY_ID' not in os.environ or 'AWS_SECRET_ACCESS_KEY' not in os.environ:
            try:
                id_file = self.master_config['access-key-id']
                key_file = self.master_config['secret-access-key']
            except KeyError:
                log.error("You need to either set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or add the path to files containing them to the config. You can find the values at http://aws.amazon.com under 'Your Account'-'Security Credentials'.")
                sys.exit(1)
            id_file = os.path.abspath(os.path.expanduser(id_file))
            if not os.path.exists(id_file):
                log.error("The access-key-id file at '%s' doesn't exist.", id_file)
                sys.exit(1)
            key_file = os.path.abspath(os.path.expanduser(key_file))
            if not os.path.exists(key_file):
                log.error("The secret-access-key file at '%s' doesn't exist.", key_file)
                sys.exit(1)
            aws_id = open(id_file).readline().strip()
            aws_key = open(key_file).readline().strip()
        return (aws_id, aws_key)

    @lazy
    def regions(self):
        from boto.ec2 import regions

        (aws_id, aws_key) = self.credentials
        return dict((x.name, x) for x in regions(
            aws_access_key_id=aws_id, aws_secret_access_key=aws_key
        ))

    @property
    def snapshots(self):
        return dict((x.id, x) for x in self.conn.get_all_snapshots(owner="self"))

    def get_conn(self, region_id):
        (aws_id, aws_key) = self.credentials
        try:
            region = self.regions[region_id]
        except KeyError:
            log.error("Region '%s' not found in regions returned by EC2.", region_id)
            sys.exit(1)
        return region.connect(
            aws_access_key_id=aws_id, aws_secret_access_key=aws_key
        )

    @lazy
    def conn(self):
        region_id = self.master_config.get('region', None)
        if region_id is None:
            log.error("No region set in ec2-master:%s config" % self.id)
            sys.exit(1)
        return self.get_conn(region_id)


class SecuritygroupsMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        securitygroups = []
        for securitygroup in value.split(','):
            securitygroups.append(securitygroup.strip())
        return set(securitygroups)


class DevicemapMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        from boto.ec2.blockdevicemapping import BlockDeviceMapping
        from boto.ec2.blockdevicemapping import BlockDeviceType

        value = main_config[self.sectiongroupname][sectionname][self.key]
        device_map = BlockDeviceMapping()
        for mapping in value.split():
            device_path, ephemeral_name = mapping.split(':')
            device = BlockDeviceType()
            device.ephemeral_name = ephemeral_name
            device_map[device_path] = device
        return device_map


class VolumesMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        volumes = []
        for line in value.split('\n'):
            volume = line.split()
            if not len(volume):
                continue
            volumes.append((volume[0], volume[1]))
        return tuple(volumes)


class SnapshotsMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        snapshots = []
        for line in value.split('\n'):
            snapshot = line.split()
            if not len(snapshot):
                continue
            snapshots.append((snapshot[0], snapshot[1]))
        return tuple(snapshots)


class ConnectionsMassager(BaseMassager):
    def __call__(self, main_config, sectionname):
        value = main_config[self.sectiongroupname][sectionname][self.key]
        connections = []
        for line in value.split('\n'):
            connection = line.split()
            if not len(connection):
                continue
            connections.append((connection[0], int(connection[1]),
                                int(connection[2]), connection[3]))
        return tuple(connections)


def get_massagers():
    massagers = []

    sectiongroupname = 'ec2-master'
    massagers.extend([
        PathMassager(sectiongroupname, 'access-key-id'),
        PathMassager(sectiongroupname, 'secret-access-key')])

    sectiongroupname = 'ec2-instance'
    massagers.extend([
        HooksMassager(sectiongroupname, 'hooks'),
        PathMassager(sectiongroupname, 'fabfile'),
        PathMassager(sectiongroupname, 'ssh-key-filename'),
        StartupScriptMassager(sectiongroupname, 'startup_script'),
        SecuritygroupsMassager(sectiongroupname, 'securitygroups'),
        VolumesMassager(sectiongroupname, 'volumes'),
        DevicemapMassager(sectiongroupname, 'device_map'),
        SnapshotsMassager(sectiongroupname, 'snapshots'),
        BooleanMassager(sectiongroupname, 'delete-volumes-on-terminate')])

    sectiongroupname = 'ec2-connection'
    massagers.extend([
        PathMassager(sectiongroupname, 'fabfile')])

    sectiongroupname = 'ec2-securitygroup'
    massagers.extend([
        ConnectionsMassager(sectiongroupname, 'connections')])

    return massagers


def get_macro_cleaners(main_config):
    def clean_instance(macro):
        for key in macro.keys():
            if key in ('ip', 'volumes'):
                del macro[key]

    return {"ec2-instance": clean_instance}


def get_masters(main_config):
    masters = main_config.get('ec2-master', {})
    for master, master_config in masters.iteritems():
        yield Master(main_config, master, master_config)
