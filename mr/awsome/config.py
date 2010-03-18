from ConfigParser import RawConfigParser


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

    def _expand(self, sectiongroupname, sectionname, section, seen):
        if (sectiongroupname, sectionname) in seen:
            raise ValueError("Circular macro expansion.")
        macrogroupname = sectiongroupname
        macroname = section['<']
        seen.add((sectiongroupname, sectionname))
        if ':' in macroname:
            macrogroupname, macroname = macroname.split(':')
        macro = self[macrogroupname][macroname]
        if '<' in macro:
            self._expand(macrogroupname, macroname, macro, seen)
        # this needs to be after the recursive _expand call, so circles are
        # properly detected
        del section['<']
        for key in macro:
            if sectiongroupname in ('instance',):
                if key in ('ip', 'volumes'):
                    continue
            if key not in section:
                section[key] = macro[key]

    def __init__(self, configs):
        _config = RawConfigParser()
        _config.optionxform = lambda s: s
        _config.read(configs)
        for section in _config.sections():
            if ':' in section:
                sectiongroupname, sectionname = section.split(':')
            else:
                sectiongroupname, sectionname = 'global', section
            items = dict(_config.items(section))
            sectiongroup = self.setdefault(sectiongroupname, {})
            sectiongroup.setdefault(sectionname, {}).update(items)
        seen = set()
        for sectiongroupname in self:
            sectiongroup = self[sectiongroupname]
            for sectionname in sectiongroup:
                section = sectiongroup[sectionname]
                if '<' in section:
                    self._expand(sectiongroupname, sectionname, section, seen)
                for key in section:
                    fname = 'massage_%s_%s' % (sectiongroupname, key)
                    massage = getattr(self, fname, None)
                    if callable(massage):
                        section[key] = massage(section[key])
