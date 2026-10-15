# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""``openstack backup restore ...`` and ``openstack backup attachment ...``."""

from ferryclient.osc.v1 import base

COLUMNS = ("id", "point_id", "mode", "state", "source_tier",
           "estimated_restore_seconds", "actual_restore_seconds")

ATTACH_COLUMNS = ("id", "point_id", "state", "device", "created_at")

MODES = ["volume", "instance", "in_place", "bucket"]

TIERS = ["chunk", "rbd"]


def _listed(values):
    out = []
    for value in values or []:
        out.extend(item.strip() for item in value.split(",") if item.strip())
    return out


class ListRestore(base.FerryLister):
    """List restores."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--point", metavar="<point>", dest="point_id",
                            help="only restores of this point")
        parser.add_argument("--state", metavar="<state>")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's restores (operator; needs a "
                                 "system-scoped token)")
        return parser

    def take_action(self, parsed_args):
        restores = self.app_client.restore_list(
            point_id=parsed_args.point_id,
            state=parsed_args.state,
            limit=parsed_args.limit,
            project_id=parsed_args.project_id,
        )
        return COLUMNS, base.rows(restores, COLUMNS, parsed_args)


class ShowRestore(base.FerryShowOne):
    """Show a restore, including anything it created."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("restore", metavar="<restore>", help="restore id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.restore_show(parsed_args.restore), parsed_args)


class EstimateRestore(base.FerryShowOne):
    """Estimate how long a restore would take, without starting one."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--point", metavar="<point>", dest="point_id",
                            required=True, help="point to estimate")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.restore_estimate(
            point_id=parsed_args.point_id), parsed_args)


class CreateRestore(base.FerryShowOne):
    """Start a restore of a point.

    ``volume`` and ``instance`` create a new resource, and only they can give
    it a different shape: ``--disks`` for either, ``--flavor``,
    ``--networks``, ``--key-name`` and ``--security-groups`` for ``instance``
    alone. ``bucket`` restores an object namespace into a new bucket.
    ``in_place`` overwrites an existing resource, which destroys whatever is
    currently there. It is the one mode that can lose data if aimed at the
    wrong point, and is never a default.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--point", metavar="<point>", dest="point_id",
                            required=True,
                            help="point to restore (required)")
        parser.add_argument("--mode", metavar="<mode>", default="volume",
                            choices=MODES,
                            help="volume or instance build a new resource, "
                                 "bucket a new bucket, in_place overwrites the "
                                 "existing resource (default: volume)")
        parser.add_argument("--name", metavar="<name>",
                            help="name for the resource this creates; for "
                                 "mode bucket, the new bucket, which must not "
                                 "already exist")
        parser.add_argument("--volume-type", metavar="<type>",
                            help="volume type for restored volumes")
        parser.add_argument("--availability-zone", metavar="<az>",
                            help="target availability zone")
        parser.add_argument("--tier", metavar="<tier>", choices=TIERS,
                            help="restore from this tier, chunk or rbd, "
                                 "instead of the fastest available source")
        parser.add_argument("--flavor", metavar="<flavor>",
                            help="restore as new on a different flavor (mode "
                                 "instance)")
        parser.add_argument("--networks", metavar="<network,...>",
                            action="append",
                            help="restore as new onto these networks: one for "
                                 "every port, or one per port in order (mode "
                                 "instance; comma-separated, repeatable)")
        parser.add_argument("--key-name", metavar="<key-pair>",
                            help="restore as new with a different key pair "
                                 "(mode instance)")
        parser.add_argument("--security-groups", metavar="<group,...>",
                            action="append",
                            help="restore as new behind these security "
                                 "groups, by name or id (mode instance; "
                                 "comma-separated, repeatable)")
        parser.add_argument("--disks", metavar="<resource-id,...>",
                            action="append",
                            help="restore only these disks of the point, by "
                                 "resource id (mode volume or instance; "
                                 "comma-separated, repeatable)")
        parser.add_argument("--target-project", metavar="<project>",
                            dest="target_project_id",
                            help="restore into another project (operator; needs a "
                                 "system-scoped token)")
        parser.add_argument("--mapping-profile", metavar="<profile>",
                            help="recovery profile, by name, that translates "
                                 "flavors, networks and volume types for a "
                                 "point another cloud wrote")
        parser.add_argument("--confirm-unresolved", metavar="<element>",
                            action="append",
                            help="accept an element the recovery profile "
                                 "could not map, as element or element:source "
                                 "(repeatable)")
        parser.add_argument("--property", metavar="<key=value>",
                            action="append", dest="properties",
                            help="metadata on the created resource "
                                 "(repeatable)")
        parser.add_argument("--acknowledge-partial", action="store_true",
                            help="proceed even though the point does not "
                                 "cover every resource it was meant to")
        parser.add_argument("--wait", action="store_true",
                            help="wait for the restore to finish")
        return parser

    def take_action(self, parsed_args):
        body = {"point_id": parsed_args.point_id, "mode": parsed_args.mode}
        for key, value in (
            ("name", parsed_args.name),
            ("volume_type", parsed_args.volume_type),
            ("availability_zone", parsed_args.availability_zone),
            ("tier", parsed_args.tier),
            ("target_project_id", parsed_args.target_project_id),
            ("mapping_profile", parsed_args.mapping_profile),
            ("confirm_unresolved", parsed_args.confirm_unresolved),
            ("flavor", parsed_args.flavor),
            ("key_name", parsed_args.key_name),
            ("networks", _listed(parsed_args.networks)),
            ("security_groups", _listed(parsed_args.security_groups)),
            ("resource_ids", _listed(parsed_args.disks)),
        ):
            if value:
                body[key] = value
        if parsed_args.properties:
            body["metadata"] = base.parse_properties(parsed_args.properties)
        if parsed_args.acknowledge_partial:
            body["acknowledge_partial"] = True
        result = self.app_client.restore_create(body)
        if parsed_args.wait:
            base.wait_for_job(self.app_client, result.get("job_id"))
        return base.show(result, parsed_args)


class ListAttachment(base.FerryLister):
    """List attached backups."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--point", metavar="<point>", dest="point_id")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's attachments (operator; needs a "
                                 "system-scoped token)")
        return parser

    def take_action(self, parsed_args):
        attachments = self.app_client.attachment_list(
            point_id=parsed_args.point_id, limit=parsed_args.limit,
            project_id=parsed_args.project_id)
        return ATTACH_COLUMNS, base.rows(attachments, ATTACH_COLUMNS, parsed_args)


class CreateAttachment(base.FerryShowOne):
    """Attach one disk of a backup read-only to a running instance.

    The point is to get at a few files without rehydrating the whole image.
    The attachment detaches and cleans itself up when its --ttl runs out.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--point", metavar="<point>", dest="point_id",
                            required=True, help="point to attach (required)")
        parser.add_argument("--instance", metavar="<instance>",
                            dest="target_instance_id", required=True,
                            help="running instance to attach it to "
                                 "(required)")
        parser.add_argument("--disk", metavar="<resource-id>",
                            dest="resource_id",
                            help="which disk of a multi-disk point to attach, "
                                 "by resource id; default the root disk")
        parser.add_argument("--device", metavar="<device>",
                            help="guest device name, e.g. /dev/vdb")
        parser.add_argument("--ttl", metavar="<duration>", default="4h",
                            help="detach and clean up after this long, e.g. "
                                 "30m or 24h (default: 4h)")
        parser.add_argument("--wait", action="store_true",
                            help="wait for the attachment to be ready")
        return parser

    def take_action(self, parsed_args):
        body = {"point_id": parsed_args.point_id,
                "target_instance_id": parsed_args.target_instance_id,
                "expires_in": parsed_args.ttl}
        if parsed_args.resource_id:
            body["resource_id"] = parsed_args.resource_id
        if parsed_args.device:
            body["device"] = parsed_args.device
        result = self.app_client.attachment_create(body)
        if parsed_args.wait:
            base.wait_for_job(self.app_client, result.get("job_id"))
        return base.show(result, parsed_args)


class DeleteAttachment(base.FerryCommand):
    """Detach one or more attached backups."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("attachment", metavar="<attachment>", nargs="+")
        return parser

    def take_action(self, parsed_args):
        for attachment in parsed_args.attachment:
            self.app_client.attachment_delete(attachment)
