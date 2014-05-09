import pkg_resources
from lazy import lazy
from mr.awsome.config import Config
from mr.awsome import template
import logging
import argparse
import os
import sys


# shutup pyflakes
__all__ = [template.__name__]


log = logging.getLogger('mr.awsome')


class LazyInstanceDict(dict):
    def __getitem__(self, key):
        cache = getattr(self, '_cache', None)
        if cache is None:
            cache = self._cache = {}
        if key in self._cache:
            return self._cache[key]
        instance = dict.__getitem__(self, key)
        for plugin in self.plugins.values():
            if 'augment_instance' not in plugin:
                continue
            plugin['augment_instance'](instance)
        self._cache[key] = instance
        return instance


class AWS(object):
    def __init__(self, configpath=None, configname=None):
        plog = logging.getLogger('paramiko.transport')
        log.setLevel(logging.INFO)
        plog.setLevel(logging.WARN)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        log.addHandler(ch)
        plog.addHandler(ch)
        if configname is None:
            configname = 'aws.conf'
        if configpath is None:
            configpath = 'etc'
        self.configfile = os.path.join(configpath, configname)

    @lazy
    def plugins(self):
        plugins = {}
        group = 'mr.awsome.plugins'
        for entrypoint in pkg_resources.iter_entry_points(group=group):
            plugin = entrypoint.load()
            plugins[entrypoint.name] = plugin
        return plugins

    @lazy
    def config(self):
        configpath = os.path.abspath(self.configfile)
        if not os.path.exists(configpath):
            log.error("Config '%s' doesn't exist." % configpath)
            sys.exit(1)
        config = Config(configpath, plugins=self.plugins)
        config.parse()
        return config

    @lazy
    def masters(self):
        result = {}
        for plugin in self.plugins.values():
            if 'get_masters' in plugin:
                for master in plugin['get_masters'](self):
                    if master.id in result:
                        log.error("Master id '%s' already in use." % master.id)
                        sys.exit(1)
                    result[master.id] = master
        return result

    @lazy
    def known_hosts(self):
        return os.path.join(self.config.path, 'known_hosts')

    def get_masters(self, command):
        masters = []
        for master in self.masters.values():
            if getattr(master, command, None) is not None:
                masters.append(master)
        return masters

    @lazy
    def instances(self):
        result = LazyInstanceDict()
        instances = []
        instances.extend((None, i) for i in self.config.get('instance', {}))
        for master in self.masters.values():
            instances.extend((master, i) for i in master.instances)
        instance_name_count = dict()
        for master, instance_id in instances:
            count = instance_name_count.get(instance_id, 0)
            instance_name_count[instance_id] = count + 1
        for master, instance_id in instances:
            if master is None:
                iconfig = self.config['instance'][instance_id]
                if 'master' not in iconfig:
                    log.error("Instance 'instance:%s' has no master set." % instance_id)
                    sys.exit(1)
                master = self.masters[iconfig['master']]
                if instance_id in master.instances:
                    log.error("Instance 'instance:%s' conflicts with another instance with id '%s' in master '%s'." % (instance_id, instance_id, master.id))
                    sys.exit(1)
                instance_class = master.section_info.get(None)
                if instance_class is None:
                    log.error("Master '%s' has no default instance class." % (master.id))
                    sys.exit(1)
                master.instances[instance_id] = instance_class(master, instance_id, iconfig)
            if instance_name_count[instance_id] > 1:
                name = '%s-%s' % (master.id, instance_id)
            else:
                name = instance_id
            result[name] = master.instances[instance_id]
        result.plugins = self.plugins
        return result

    def get_instances(self, command):
        instances = {}
        for instance_id in self.instances:
            instance = self.instances[instance_id]
            if getattr(instance, command, None) is not None:
                instances[instance_id] = instance
        return instances

    def cmd_status(self, argv, help):
        """Prints status"""
        parser = argparse.ArgumentParser(
            prog="aws status",
            description=help,
        )
        instances = self.get_instances(command='status')
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(instances))
        args = parser.parse_args(argv)
        server = instances[args.server[0]]
        server.status()

    def cmd_stop(self, argv, help):
        """Stops the instance"""
        parser = argparse.ArgumentParser(
            prog="aws stop",
            description=help,
        )
        instances = self.get_instances(command='stop')
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(instances))
        args = parser.parse_args(argv)
        server = instances[args.server[0]]
        server.stop()

    def cmd_terminate(self, argv, help):
        """Terminates the instance"""
        parser = argparse.ArgumentParser(
            prog="aws terminate",
            description=help,
        )
        instances = self.get_instances(command='terminate')
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(instances))
        args = parser.parse_args(argv)
        server = instances[args.server[0]]
        server.terminate()
        server.hooks.after_terminate(server)

    def _parse_overrides(self, options):
        overrides = dict()
        if options.overrides is not None:
            for override in options.overrides:
                if '=' not in override:
                    log.error("Invalid format for override '%s', should be NAME=VALUE." % override)
                    sys.exit(1)
                key, value = override.split('=', 1)
                key = key.strip()
                value = value.strip()
                if key == '':
                    log.error("Empty key for override '%s'." % override)
                    sys.exit(1)
                overrides[key] = value
        return overrides

    def cmd_start(self, argv, help):
        """Starts the instance"""
        parser = argparse.ArgumentParser(
            prog="aws start",
            description=help,
        )
        instances = self.get_instances(command='start')
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(instances))
        parser.add_argument("-o", "--override", nargs="*", type=str,
                            dest="overrides", metavar="OVERRIDE",
                            help="Option to override in server config for startup script (name=value).")
        args = parser.parse_args(argv)
        overrides = self._parse_overrides(args)
        overrides['servers'] = self.instances
        server = instances[args.server[0]]
        server.hooks.before_start(server)
        instance = server.start(overrides)
        if instance is None:
            return
        server.status()

    def cmd_debug(self, argv, help):
        """Prints some debug info for this script"""
        parser = argparse.ArgumentParser(
            prog="aws debug",
            description=help,
        )
        instances = self.get_instances(command='startup_script')
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(instances))
        parser.add_argument("-v", "--verbose", dest="verbose",
                            action="store_true", help="Print more info and output the startup script")
        parser.add_argument("-c", "--console-output", dest="console_output",
                            action="store_true", help="Prints the console output of the instance if available")
        parser.add_argument("-i", "--interactive", dest="interactive",
                            action="store_true", help="Creates a connection and drops you into pdb")
        parser.add_argument("-r", "--raw", dest="raw",
                            action="store_true", help="Outputs the raw possibly compressed startup script")
        parser.add_argument("-o", "--override", nargs="*", type=str,
                            dest="overrides", metavar="OVERRIDE",
                            help="Option to override server config for startup script (name=value).")
        args = parser.parse_args(argv)
        overrides = self._parse_overrides(args)
        overrides['servers'] = self.instances
        server = instances[args.server[0]]
        startup_script = server.startup_script(overrides=overrides, debug=True)
        max_size = getattr(server, 'max_startup_script_size', 16 * 1024)
        log.info("Length of startup script: %s/%s", len(startup_script['raw']), max_size)
        if args.verbose:
            if 'startup_script' in server.config:
                if startup_script['original'] == startup_script['raw']:
                    log.info("Startup script:")
                elif args.raw:
                    log.info("Compressed startup script:")
                else:
                    log.info("Uncompressed startup script:")
            else:
                log.info("No startup script specified")
        if args.raw:
            print startup_script['raw'],
        elif args.verbose:
            print startup_script['original'],
        if args.console_output:
            print server.instance.get_console_output().output
        if args.interactive:  # pragma: no cover
            import readline
            conn = server.conn
            instance = server.instance
            conn, instance  # shutup pyflakes
            readline.parse_and_bind('tab: complete')
            local = locals()
            try:
                import rlcompleter
                readline.set_completer(rlcompleter.Completer(local).complete)
            except ImportError:
                pass
            __import__("code").interact(local=local)

    def cmd_list(self, argv, help):
        """Return a list of various AWS things"""
        parser = argparse.ArgumentParser(
            prog="aws list",
            description=help,
        )
        parser.add_argument("list", nargs=1,
                            metavar="list",
                            help="Name of list to show.",
                            choices=['snapshots'])
        args = parser.parse_args(argv)
        if args.list[0] == 'snapshots':
            snapshots = []
            for master in self.get_masters('snapshots'):
                snapshots.extend(master.snapshots.values())
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
        instances = self.get_instances(command='init_ssh_key')
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance or server from the config.",
                            choices=list(instances))
        parser.add_argument("...", nargs=argparse.REMAINDER,
                            help="ssh options")
        iargs = enumerate(argv)
        sid_index = None
        user = None
        for i, arg in iargs:
            if not arg.startswith('-'):
                sid_index = i
                break
            else:
                if arg[1] in '1246AaCfgKkMNnqsTtVvXxYy':
                    continue
                elif arg[1] in 'bcDeFiLlmOopRSw':
                    value = iargs.next()
                    if arg[1] == 'l':
                        user = value[1]
                    continue
        # fake parsing for nice error messages
        if sid_index is None:
            parser.parse_args([])
        else:
            sid = argv[sid_index]
            if '@' in sid:
                user, sid = sid.split('@', 1)
            parser.parse_args([sid])
        server = instances[sid]
        if user is None:
            user = server.config.get('user')
        try:  # pragma: no cover - we support both
            from paramiko import SSHException
            SSHException  # shutup pyflakes
        except ImportError:  # pragma: no cover - we support both
            from ssh import SSHException
        try:
            ssh_info = server.init_ssh_key(user=user)
        except SSHException, e:
            log.error("Couldn't validate fingerprint for ssh connection.")
            log.error(unicode(e))
            log.error("Is the server finished starting up?")
            sys.exit(1)
        client = ssh_info['client']
        client.get_transport().sock.close()
        client.close()
        additional_args = []
        for key in ssh_info:
            if key[0].isupper():
                additional_args.append('-o')
                additional_args.append('%s=%s' % (key, ssh_info[key]))
        if 'user' in ssh_info:
            additional_args.append('-l')
            additional_args.append(ssh_info['user'])
        if 'port' in ssh_info:
            additional_args.append('-p')
            additional_args.append(str(ssh_info['port']))
        if 'host' in ssh_info:
            additional_args.append(ssh_info['host'])
        if server.config.get('ssh-key-filename'):
            additional_args.append('-i')
            additional_args.append(server.config.get('ssh-key-filename'))
        argv[sid_index:sid_index + 1] = additional_args
        argv[0:0] = ['ssh']
        os.execvp('ssh', argv)

    def cmd_snapshot(self, argv, help):
        """Creates a snapshot of the volumes specified in the configuration"""
        parser = argparse.ArgumentParser(
            prog="aws snapshot",
            description=help,
        )
        instances = self.get_instances(command='snapshot')
        parser.add_argument("server", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=list(instances))
        args = parser.parse_args(argv)
        server = instances[args.server[0]]
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
            else:  # pragma: no cover
                if hasattr(self.cmds[args.command], 'get_completion'):
                    for item in self.cmds[args.command].get_completion():
                        print item
                elif args.command in ('do', 'ssh'):
                    for server in self.get_instances(command='init_ssh_key'):
                        print server
                elif args.command == 'debug':
                    for server in self.get_instances(command='startup_script'):
                        print server
                elif args.command == 'list':
                    for subcmd in ('snapshots',):
                        print subcmd
                elif args.command != 'help':
                    for server in self.get_instances(command=args.command):
                        print server
        else:
            if args.command is None:
                parser.print_help()
            else:
                cmd = self.cmds[args.command]
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

        self.cmds = dict(
            (x[4:], getattr(self, x))
            for x in dir(self) if x.startswith('cmd_'))
        for pluginname, plugin in self.plugins.items():
            if 'get_commands' not in plugin:
                continue
            for cmd, func in plugin['get_commands'](self):
                if cmd in self.cmds:
                    log.error("Command name '%s' of '%s' conflicts with existing command name.", cmd, pluginname)
                    sys.exit(1)
                self.cmds[cmd] = func
        cmdparsers = parser.add_subparsers(title="commands")
        self.subparsers = {}
        for cmd, func in self.cmds.items():
            subparser = cmdparsers.add_parser(cmd, help=func.__doc__)
            subparser.set_defaults(func=func)
            self.subparsers[cmd] = subparser
        main_argv = []
        for arg in argv:
            main_argv.append(arg)
            if arg in self.cmds:
                break
        sub_argv = argv[len(main_argv):]
        args = parser.parse_args(main_argv[1:])
        if args.configfile is not None:
            self.configfile = args.configfile
        args.func(sub_argv, args.func.__doc__)


def aws(configpath=None, configname=None):  # pragma: no cover
    argv = sys.argv[:]
    aws = AWS(configpath=configpath, configname=configname)
    return aws(argv)


def aws_ssh(configpath=None, configname=None):  # pragma: no cover
    argv = sys.argv[:]
    argv.insert(1, "ssh")
    aws = AWS(configpath=configpath, configname=configname)
    return aws(argv)
