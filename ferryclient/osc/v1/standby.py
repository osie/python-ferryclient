from ferryclient.osc.v1 import base

COLUMNS = ("id", "resource_id", "state", "applied_point_id", "applied_at",
           "applied_snap", "site_id", "target_pool")


class ListStandby(base.FerryLister):
    """List this project's standbys."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--project", metavar="<project>",
                            help="list this project's standbys (operator)")
        return parser

    def take_action(self, parsed_args):
        standbys = self.app_client.standby_list(project_id=parsed_args.project)
        return COLUMNS, base.rows(standbys, COLUMNS, parsed_args)


class ShowStandby(base.FerryShowOne):
    """Show a standby."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("standby", metavar="<standby>", help="standby id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.standby_show(parsed_args.standby),
                         parsed_args)


class CreateStandby(base.FerryShowOne):
    """Register a standby for a resource (operator).

    A standby is a copy of one resource's disks, as images in a pool, kept
    current by replaying each new point into it. ``--pool`` must be set aside
    for standbys, because every replay overwrites what it holds.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--project", metavar="<project>", required=True,
                            help="project the standby belongs to, which can "
                                 "read and promote it")
        parser.add_argument("--domain", metavar="<domain>",
                            help="domain of that project; needed only when "
                                 "the service cannot look the project up")
        parser.add_argument("--resource", metavar="<resource>", required=True,
                            help="protected resource the standby shadows")
        parser.add_argument("--pool", metavar="<pool>", required=True,
                            help="pool the standby's images are kept in")
        parser.add_argument("--image-prefix", metavar="<prefix>",
                            help="prefix for the image names, so one pool can "
                                 "hold many standbys")
        parser.add_argument("--site", metavar="<site>",
                            help="site the standby lives at, by name or id; "
                                 "defaults to this cloud's own")
        parser.add_argument("--group", metavar="<group>",
                            help="protection group, by name or id, a "
                                 "failover finds it through")
        return parser

    def take_action(self, parsed_args):
        body = {"project_id": parsed_args.project,
                "resource_id": parsed_args.resource,
                "target_pool": parsed_args.pool}
        site = None
        if parsed_args.site:
            site = self.app_client.site_find(parsed_args.site)
        group = None
        if parsed_args.group:
            group = self.app_client.group_find(parsed_args.group)
        for key, value in (
            ("domain_id", parsed_args.domain),
            ("target_prefix", parsed_args.image_prefix),
            ("site_id", site),
            ("group_id", group),
        ):
            if value:
                body[key] = value
        return base.show(self.app_client.standby_create(body), parsed_args)


class DeleteStandby(base.FerryCommand):
    """Deregister one or more standbys (operator).

    Replays stop and the record is forgotten. The images are left in the
    pool, because they may be what you are about to fail over onto.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("standby", metavar="<standby>", nargs="+")
        return parser

    def take_action(self, parsed_args):
        for standby in parsed_args.standby:
            self.app_client.standby_delete(standby)


class PromoteStandby(base.FerryShowOne):
    """Turn a standby into volumes you can boot.

    The volumes are cloned from the standby's applied snapshot, so they hold
    exactly the backup it last finished, even while an update runs or after
    one failed. A standby with no applied snapshot yet is refused. It creates
    one volume per disk in the standby's project, boot disk first, and nothing
    else: booting them is yours to do.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("standby", metavar="<standby>", help="standby id")
        parser.add_argument("--name-prefix", metavar="<prefix>",
                            help="prefix for the new volumes' names; defaults "
                                 "to the standby's image prefix")
        parser.add_argument("--volume-type", metavar="<type>",
                            help="volume type here; defaults to the block "
                                 "storage service's")
        parser.add_argument("--availability-zone", metavar="<zone>",
                            help="availability zone here; defaults to the "
                                 "block storage service's")
        return parser

    def take_action(self, parsed_args):
        body = {}
        for key, value in (
            ("name_prefix", parsed_args.name_prefix),
            ("volume_type", parsed_args.volume_type),
            ("availability_zone", parsed_args.availability_zone),
        ):
            if value:
                body[key] = value
        return base.show(
            self.app_client.standby_promote(parsed_args.standby, body or None),
            parsed_args)
