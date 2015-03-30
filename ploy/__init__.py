from __future__ import print_function
import pkg_resources
from lazy import lazy
from ploy.config import Config, DictMixin
from ploy import template
import logging
import argparse
import os
import socket
import sys
import weakref


# shutup pyflakes
__all__ = [template.__name__]


log = logging.getLogger('ploy')


try:
    unicode
except NameError:  # pragma: nocover
    unicode = str


def versionaction_factory(ctrl):
    class VersionAction(argparse.Action):
        def __init__(self, *args, **kw):
            kw['nargs'] = 0
            argparse.Action.__init__(self, *args, **kw)

        def __call__(self, parser, namespace, values, option_string=None):
            import inspect
            versions = [repr(pkg_resources.get_distribution("ploy"))]
            for plugin in ctrl.plugins.values():
                for item in plugin.values():
                    module = inspect.getmodule(item)
                    try:
                        pkg = pkg_resources.get_distribution(module.__name__)
                    except pkg_resources.DistributionNotFound:
                        continue
                    versions.append(repr(pkg))
                    break
            print('\n'.join(sorted(versions)))
            sys.exit(0)
    return VersionAction


class LazyInstanceDict(DictMixin):
    def __init__(self, ctrl):
        self._cache = dict()
        self._dict = dict()
        self.ctrl = weakref.ref(ctrl)

    def __getitem__(self, key):
        if key in self._cache:
            return self._cache[key]
        try:
            instance = self._dict[key]
        except KeyError:
            ctrl = self.ctrl()
            candidates = []
            for sectionname, section in ctrl.config.items():
                if key in section:
                    candidates.append("    %s:%s" % (sectionname, key))
            if candidates:
                log.error("Instance '%s' not found. Did you forget to install a plugin? The following sections might match:\n%s" % (
                    key, "\n".join(candidates)))
            raise
        get_massagers = getattr(instance, 'get_massagers', lambda: [])
        for massager in get_massagers():
            instance.config.add_massager(massager)
        for plugin in self.plugins.values():
            if 'augment_instance' not in plugin:
                continue
            plugin['augment_instance'](instance)
        self._cache[key] = instance
        return instance

    def __setitem__(self, key, value):
        self._dict[key] = value

    def __delitem__(self, key):
        del self._dict[key]
        self._cache.pop(key, None)

    def keys(self):
        return self._dict.keys()

    def close_connections(self):
        for instance_id in self._cache:
            self[instance_id].close_conn()

    def __len__(self):
        return len(self._dict)

    def __iter__(self):
        return iter(self.keys())


class Controller(object):
    def __init__(self, configpath=None, configname=None, progname=None):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        plog = logging.getLogger('paramiko.transport')
        plog.setLevel(logging.WARN)
        if configname is None:
            configname = 'ploy.conf'
        if configpath is None:
            configpath = 'etc'
        self.configname = configname
        self.configpath = configpath
        if progname is None:
            progname = 'ploy'
        self.progname = progname

    @lazy
    def plugins(self):
        plugins = {}
        group = 'ploy.plugins'
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
        result = LazyInstanceDict(self)
        try:
            config = self.config
        except SystemExit:
            return result
        for instance_id in config.get('instance', {}):
            iconfig = config['instance'][instance_id]
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
            instance = instance_class(master, instance_id, iconfig)
            instance.sectiongroupname = 'instance'
            master.instances[instance_id] = instance
        shortname_map = {}
        for master in self.masters.values():
            for instance_id in master.instances:
                instance = master.instances[instance_id]
                key = instance.uid
                result[key] = instance
                shortname_map.setdefault(instance_id, []).append(instance)
        for shortname, instances in shortname_map.items():
            if len(instances) == 1:
                result[shortname] = instances[0]
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
            prog="%s status" % self.progname,
            description=help,
        )
        instances = self.get_instances(command='status')
        parser.add_argument("instance", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=sorted(instances))
        args = parser.parse_args(argv)
        instance = instances[args.instance[0]]
        instance.status()

    def cmd_stop(self, argv, help):
        """Stops the instance"""
        parser = argparse.ArgumentParser(
            prog="%s stop" % self.progname,
            description=help,
        )
        instances = self.get_instances(command='stop')
        parser.add_argument("instance", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=sorted(instances))
        args = parser.parse_args(argv)
        instance = instances[args.instance[0]]
        instance.stop()

    def cmd_terminate(self, argv, help):
        """Terminates the instance"""
        from ploy.common import yesno
        parser = argparse.ArgumentParser(
            prog="%s terminate" % self.progname,
            description=help,
        )
        instances = self.get_instances(command='terminate')
        parser.add_argument("instance", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=sorted(instances))
        args = parser.parse_args(argv)
        instance = instances[args.instance[0]]
        if not yesno("Are you sure you want to terminate '%s'?" % instance.config_id):
            return
        instance.hooks.before_terminate(instance)
        instance.terminate()
        instance.hooks.after_terminate(instance)

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
            prog="%s start" % self.progname,
            description=help,
        )
        instances = self.get_instances(command='start')
        parser.add_argument("instance", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=sorted(instances))
        parser.add_argument("-o", "--override", nargs="*", type=str,
                            dest="overrides", metavar="OVERRIDE",
                            help="Option to override in instance config for startup script (name=value).")
        args = parser.parse_args(argv)
        overrides = self._parse_overrides(args)
        overrides['instances'] = self.instances
        instance = instances[args.instance[0]]
        instance.hooks.before_start(instance)
        result = instance.start(overrides)
        instance.hooks.after_start(instance)
        if result is None:
            return
        instance.status()

    def cmd_annotate(self, argv, help):
        """Prints annotated config"""
        parser = argparse.ArgumentParser(
            prog="%s annotate" % self.progname,
            description=help,
        )
        parser.parse_args(argv)
        list(self.instances.values())  # trigger instance augmentation
        for global_section in sorted(self.config):
            for sectionname in sorted(self.config[global_section]):
                print("[%s:%s]" % (global_section, sectionname))
                section = self.config[global_section][sectionname]
                for option, value in sorted(section._dict.items()):
                    print("%s = %s" % (option, value.value))
                    print("    %s" % value.src)
                print()

    def cmd_debug(self, argv, help):
        """Prints some debug info for this script"""
        parser = argparse.ArgumentParser(
            prog="%s debug" % self.progname,
            description=help,
        )
        instances = self.instances
        parser.add_argument("instance", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=sorted(instances))
        parser.add_argument("-v", "--verbose", dest="verbose",
                            action="store_true", help="Print more info and output the startup script")
        parser.add_argument("-c", "--console-output", dest="console_output",
                            action="store_true", help="Prints the console output of the instance if available")
        parser.add_argument("-i", "--interactive", dest="interactive",
                            action="store_true", help="Creates a connection and drops you into an interactive Python session")
        parser.add_argument("-r", "--raw", dest="raw",
                            action="store_true", help="Outputs the raw possibly compressed startup script")
        parser.add_argument("-o", "--override", nargs="*", type=str,
                            dest="overrides", metavar="OVERRIDE",
                            help="Option to override instance config for startup script (name=value).")
        args = parser.parse_args(argv)
        overrides = self._parse_overrides(args)
        overrides['instances'] = self.instances
        instance = instances[args.instance[0]]
        if hasattr(instance, 'startup_script'):
            startup_script = instance.startup_script(overrides=overrides, debug=True)
            max_size = getattr(instance, 'max_startup_script_size', 16 * 1024)
            log.info("Length of startup script: %s/%s", len(startup_script['raw']), max_size)
            if args.verbose:
                if 'startup_script' in instance.config:
                    if startup_script['original'] == startup_script['raw']:
                        log.info("Startup script:")
                    elif args.raw:
                        log.info("Compressed startup script:")
                    else:
                        log.info("Uncompressed startup script:")
                else:
                    log.info("No startup script specified")
            if args.raw:
                print(startup_script['raw'], end='')
            elif args.verbose:
                print(startup_script['original'], end='')
        if args.console_output:
            if hasattr(instance, 'get_console_output'):
                print(instance.get_console_output())
            else:
                log.error("The instance doesn't support console output.")
        if args.interactive:  # pragma: no cover
            import readline
            from pprint import pprint
            local = dict(
                ctrl=self,
                instances=self.instances,
                instance=instance,
                pprint=pprint)
            readline.parse_and_bind('tab: complete')
            try:
                import rlcompleter
                readline.set_completer(rlcompleter.Completer(local).complete)
            except ImportError:
                pass
            __import__("code").interact(local=local)

    def cmd_list(self, argv, help):
        """Return a list of various things"""
        parser = argparse.ArgumentParser(
            prog="%s list" % self.progname,
            description=help,
        )
        parser.add_argument("list", nargs=1,
                            metavar="listname",
                            help="Name of list to show.",
                            choices=sorted(self.list_cmds))
        parser.add_argument("listopts",
                            metavar="...",
                            nargs=argparse.REMAINDER,
                            help="list command options")
        args = parser.parse_args(argv)
        for name, func in sorted(self.list_cmds[args.list[0]]):
            func(args.listopts, func.__doc__)

    def cmd_ssh(self, argv, help):
        """Log into the instance with ssh using the automatically generated known hosts"""
        parser = argparse.ArgumentParser(
            prog="%s ssh" % self.progname,
            description=help,
        )
        instances = self.get_instances(command='init_ssh_key')
        parser.add_argument("instance", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=sorted(instances))
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
        instance = instances[sid]
        if user is None:
            user = instance.config.get('user')
        try:
            ssh_info = instance.init_ssh_key(user=user)
        except (instance.paramiko.SSHException, socket.error) as e:
            log.error("Couldn't validate fingerprint for ssh connection.")
            log.error(unicode(e))
            log.error("Is the instance finished starting up?")
            sys.exit(1)
        client = ssh_info['client']
        client.get_transport().sock.close()
        client.close()
        argv[sid_index:sid_index + 1] = instance.ssh_args_from_info(ssh_info)
        argv[0:0] = ['ssh']
        os.execvp('ssh', argv)

    def cmd_snapshot(self, argv, help):
        """Creates a snapshot of the volumes specified in the configuration"""
        parser = argparse.ArgumentParser(
            prog="%s snapshot" % self.progname,
            description=help,
        )
        instances = self.get_instances(command='snapshot')
        parser.add_argument("instance", nargs=1,
                            metavar="instance",
                            help="Name of the instance from the config.",
                            choices=sorted(instances))
        args = parser.parse_args(argv)
        instance = instances[args.instance[0]]
        instance.snapshot()

    def cmd_help(self, argv, help):
        """Print help"""
        parser = argparse.ArgumentParser(
            prog="%s help" % self.progname,
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
                    print(cmd)
            else:  # pragma: no cover
                if hasattr(self.cmds[args.command], 'get_completion'):
                    for item in self.cmds[args.command].get_completion():
                        print(item)
                elif args.command in ('do', 'ssh'):
                    for instance in self.get_instances(command='init_ssh_key'):
                        print(instance)
                elif args.command == 'debug':
                    for instance in sorted(self.instances):
                        print(instance)
                elif args.command == 'list':
                    for subcmd in sorted(self.list_cmds):
                        print(subcmd)
                elif args.command != 'help':
                    for instance in sorted(self.get_instances(command=args.command)):
                        print(instance)
        else:
            if args.command is None:
                parser.print_help()
            else:
                cmd = self.cmds[args.command]
                cmd(['-h'], cmd.__doc__)

    def __call__(self, argv):
        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        configfile = os.path.join(self.configpath, self.configname)
        parser.add_argument('-c', '--config',
                            dest="configfile",
                            default=configfile,
                            help="Use the specified config file.")

        parser.add_argument('-v', '--version',
                            action=versionaction_factory(self),
                            help="Print versions and exit")

        parser.add_argument('-d', '--debug',
                            action="store_true",
                            help="Enable debug logging")

        self.cmds = dict(
            (x[4:], getattr(self, x))
            for x in dir(self) if x.startswith('cmd_'))
        self.list_cmds = {}
        for pluginname, plugin in self.plugins.items():
            if 'get_commands' in plugin:
                for cmd, func in plugin['get_commands'](self):
                    if cmd in self.cmds:
                        log.error("Command name '%s' of '%s' conflicts with existing command name.", cmd, pluginname)
                        sys.exit(1)
                    self.cmds[cmd] = func
            if 'get_list_commands' in plugin:
                for cmd, func in plugin['get_list_commands'](self):
                    self.list_cmds.setdefault(cmd, []).append((pluginname, func))
        cmdparsers = parser.add_subparsers(title="commands")
        cmdparsers.required = True
        cmdparsers.dest = 'commands'
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
        self.configfile = args.configfile
        if args.debug:
            logging.root.setLevel(logging.DEBUG)
        try:
            args.func(sub_argv, args.func.__doc__)
        finally:
            self.instances.close_connections()


def ploy(configpath=None, configname=None, progname=None):  # pragma: no cover
    argv = sys.argv[:]
    ctrl = Controller(configpath=configpath, configname=configname, progname=progname)
    return ctrl(argv)


def ploy_ssh(configpath=None, configname=None, progname=None):  # pragma: no cover
    argv = sys.argv[:]
    argv.insert(1, "ssh")
    ctrl = Controller(configpath=configpath, configname=configname, progname=progname)
    return ctrl(argv)
