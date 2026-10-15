import yaml

from ferryclient.osc.v1 import base

BINDING_COLUMNS = ("id", "origin_cloud", "source_resource_id",
                   "target_project_id", "rung", "points_adopted",
                   "last_adopted_at", "last_error")
PROFILE_COLUMNS = ("id", "name", "origin_cloud", "flavor_map", "network_map",
                   "volume_type_map")
GROUP_COLUMNS = ("group_uid", "name", "origin_cloud", "source_project", "rung",
                 "member_count", "version", "published_at", "registered_as")
PROFILE_MAPS = (
    ("flavor_map", "--flavor-map"),
    ("network_map", "--network-map"),
    ("subnet_map", "--subnet-map"),
    ("volume_type_map", "--volume-type-map"),
    ("az_map", "--az-map"),
    ("security_group_map", "--security-group-map"),
    ("keypair_map", "--keypair-map"),
)


def with_rung(binding):
    return dict(binding,
                rung="warm" if binding.get("standby_pool") else "cold")


class ListRecoveryBinding(base.FerryLister):
    """List recovery bindings (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--repository", metavar="<repository>",
                            help="only bindings reading this repository, by "
                                 "name or id")
        parser.add_argument("--origin-cloud", metavar="<cloud>",
                            help="only bindings for points this cloud wrote")
        parser.add_argument("--target-project", metavar="<project>",
                            help="only bindings adopting into this project")
        return parser

    def take_action(self, parsed_args):
        repository = None
        if parsed_args.repository:
            repository = self.app_client.repository_find(
                parsed_args.repository)
        bindings = self.app_client.binding_list(
            repository_id=repository,
            origin_cloud=parsed_args.origin_cloud,
            target_project_id=parsed_args.target_project)
        return BINDING_COLUMNS, base.rows(
            [with_rung(b) for b in bindings], BINDING_COLUMNS, parsed_args)


class ShowRecoveryBinding(base.FerryShowOne):
    """Show a recovery binding (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("binding", metavar="<binding>", help="binding id")
        return parser

    def take_action(self, parsed_args):
        binding = self.app_client.binding_show(parsed_args.binding)
        return base.show(with_rung(binding), parsed_args)


class CreateRecoveryBinding(base.FerryShowOne):
    """Claim a resource another cloud backed up for a project here (operator).

    Nothing is adopted without a binding. Once it exists, every catalogue pass
    adopts the resource's points into the target project, those catalogued
    before the binding included, and they restore like any other point. With ``--standby-pool`` the binding is warm:
    a standby is registered in that pool on the first adopted point and kept
    current by replaying each new point into it. A resource binds once.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--repository", metavar="<repository>",
                            required=True,
                            help="repository the points are read from, by "
                                 "name or id")
        parser.add_argument("--origin-cloud", metavar="<cloud>",
                            required=True,
                            help="cloud that wrote the points, as its point "
                                 "objects name it")
        parser.add_argument("--source-project", metavar="<project>",
                            help="project the resource belonged to there, "
                                 "for the record")
        parser.add_argument("--resource", metavar="<resource>", required=True,
                            help="id of the backed-up resource in the origin "
                                 "cloud")
        parser.add_argument("--target-project", metavar="<project>",
                            required=True,
                            help="project here the points are adopted into")
        parser.add_argument("--target-domain", metavar="<domain>",
                            help="domain of the target project; needed only "
                                 "when the service cannot look the project up")
        parser.add_argument("--standby-site", metavar="<site>",
                            help="site the standby lives at, by name or id; "
                                 "defaults to this cloud's own")
        parser.add_argument("--standby-pool", metavar="<pool>",
                            help="pool a standby is kept current in, which "
                                 "makes the binding warm")
        parser.add_argument("--standby-prefix", metavar="<prefix>",
                            help="prefix for the standby's image names")
        return parser

    def take_action(self, parsed_args):
        if parsed_args.standby_prefix and not parsed_args.standby_pool:
            raise SystemExit("--standby-prefix needs --standby-pool; without "
                             "a pool there is no copy for it to name")
        body = {
            "repository_id": self.app_client.repository_find(
                parsed_args.repository),
            "origin_cloud": parsed_args.origin_cloud,
            "source_resource_id": parsed_args.resource,
            "target_project_id": parsed_args.target_project,
        }
        site = None
        if parsed_args.standby_site:
            site = self.app_client.site_find(parsed_args.standby_site)
        for key, value in (
            ("source_project", parsed_args.source_project),
            ("target_domain_id", parsed_args.target_domain),
            ("standby_site_id", site),
            ("standby_pool", parsed_args.standby_pool),
            ("standby_prefix", parsed_args.standby_prefix),
        ):
            if value:
                body[key] = value
        return base.show(with_rung(self.app_client.binding_create(body)),
                         parsed_args)


class DeleteRecoveryBinding(base.FerryCommand):
    """End one or more recovery bindings (operator).

    No further points are adopted and the standby's replays stop. Points
    already adopted stay, and so does any standby the binding registered.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("binding", metavar="<binding>", nargs="+")
        return parser

    def take_action(self, parsed_args):
        for binding in parsed_args.binding:
            self.app_client.binding_delete(binding)


class DryRunRecoveryBinding(base.FerryShowOne):
    """Resolve what recovering a bound resource here would build (operator).

    Creates nothing. Resolves one of the binding's adopted points, the newest
    unless ``--point`` names one, against this cloud's own flavors, networks,
    volume types and security groups, and answers what would be created, what
    will differ and what cannot be mapped. An unresolved element is accepted
    only by naming it with ``--confirm-unresolved``.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("binding", metavar="<binding>", help="binding id")
        parser.add_argument("--point", metavar="<point>",
                            help="adopted point to resolve; defaults to the "
                                 "newest")
        profile = parser.add_mutually_exclusive_group()
        profile.add_argument("--profile", metavar="<profile>",
                             help="stored recovery profile to translate with, "
                                  "by name")
        profile.add_argument("--profile-file", metavar="<file>",
                             help="an inline profile as YAML or JSON")
        parser.add_argument("--confirm-unresolved", metavar="<element>",
                            action="append", dest="confirm_unresolved",
                            help="unresolved element to accept, as the "
                                 "resolution names it, e.g. network:net-1 "
                                 "(repeatable)")
        return parser

    def take_action(self, parsed_args):
        body = {}
        if parsed_args.point:
            body["point_id"] = parsed_args.point
        if parsed_args.profile:
            body["profile"] = parsed_args.profile
        if parsed_args.profile_file:
            with open(parsed_args.profile_file, "r", encoding="utf-8") as fh:
                body["mapping_profile"] = yaml.safe_load(fh) or {}
        if parsed_args.confirm_unresolved:
            body["confirm_unresolved"] = parsed_args.confirm_unresolved
        return base.show(
            self.app_client.binding_dry_run(parsed_args.binding, body or None),
            parsed_args)


class ListRecoveryGroup(base.FerryLister):
    """List the protection groups a repository describes (operator).

    Each is the newest version of a group document another region wrote, as
    this region's catalogue read it. ``registered_as`` names this region's
    recovery of it, once one is registered with ``openstack backup group
    register``.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository>",
                            help="repository to read, by name or id")
        parser.add_argument("--origin-cloud", metavar="<cloud>",
                            help="only groups this cloud wrote")
        return parser

    def take_action(self, parsed_args):
        groups = self.app_client.repository_groups(
            parsed_args.repository, origin_cloud=parsed_args.origin_cloud)
        return GROUP_COLUMNS, base.rows(groups, GROUP_COLUMNS, parsed_args)


class ListRecoveryProfile(base.FerryLister):
    """List recovery profiles (operator)."""

    def take_action(self, parsed_args):
        profiles = self.app_client.recovery_profile_list()
        return PROFILE_COLUMNS, base.rows(profiles, PROFILE_COLUMNS,
                                          parsed_args)


class CreateRecoveryProfile(base.FerryShowOne):
    """Create a recovery profile (operator).

    A named, reusable translation from another cloud's flavors, networks,
    volume types, availability zones, security groups and key pairs to this
    cloud's. With no ``--origin-cloud`` it applies to points from any cloud.
    A restore or a binding dry-run asks for it by name.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("name", metavar="<name>", help="profile name")
        parser.add_argument("--origin-cloud", metavar="<cloud>",
                            help="cloud whose points this translates, as its "
                                 "point objects name it")
        for _key, flag in PROFILE_MAPS:
            parser.add_argument(flag, metavar="<from=to>", action="append",
                                help="source to target (repeatable)")
        parser.add_argument("--floating-pool", metavar="<pool>")
        parser.add_argument("--flavor-fallback-by-spec", action="store_true",
                            help="pick the nearest flavor by spec when no "
                                 "name matches")
        parser.add_argument("--recreate-security-groups", action="store_true",
                            help="recreate a source security group here when "
                                 "none maps to it")
        parser.add_argument("--import-keypair", action="store_true",
                            help="import the source's key pair here when none "
                                 "maps to it")
        return parser

    def take_action(self, parsed_args):
        body = {"name": parsed_args.name}
        if parsed_args.origin_cloud:
            body["origin_cloud"] = parsed_args.origin_cloud
        for key, flag in PROFILE_MAPS:
            pairs = getattr(parsed_args, key)
            if pairs:
                body[key] = base.parse_properties(pairs, flag=flag)
        if parsed_args.floating_pool:
            body["floating_pool"] = parsed_args.floating_pool
        for key in ("flavor_fallback_by_spec", "recreate_security_groups",
                    "import_keypair"):
            if getattr(parsed_args, key):
                body[key] = True
        return base.show(self.app_client.recovery_profile_create(body),
                         parsed_args)


class DeleteRecoveryProfile(base.FerryCommand):
    """Delete one or more recovery profiles, by name or id (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("profile", metavar="<profile>", nargs="+")
        return parser

    def take_action(self, parsed_args):
        for profile in parsed_args.profile:
            self.app_client.recovery_profile_delete(profile)
