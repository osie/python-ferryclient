# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""``openstack backup point ...``: the backups themselves."""

from ferryclient.osc.v1 import base

COLUMNS = ("id", "plan_id", "resource_kind", "resource_id", "state",
           "tier_state", "roles", "created_at")


class ListPoint(base.FerryLister):
    """List backup points."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--plan", metavar="<plan>", dest="plan_id",
                            help="only points from this plan")
        parser.add_argument("--resource", metavar="<id>", dest="resource_id",
                            help="only points for this resource")
        parser.add_argument("--state", metavar="<state>",
                            help="only points in this state")
        parser.add_argument("--limit", type=int,
                            help="maximum points returned")
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's points (operator; needs a "
                                 "system-scoped token)")
        base.add_scope_argument(parser)
        return parser

    def take_action(self, parsed_args):
        plan_id = parsed_args.plan_id
        if plan_id:
            plan_id = self.app_client.plan_find(plan_id)
        points = self.app_client.point_list(
            plan_id=plan_id,
            resource_id=parsed_args.resource_id,
            state=parsed_args.state,
            limit=parsed_args.limit,
            project_id=parsed_args.project_id,
            scope=parsed_args.scope,
        )
        return COLUMNS, base.rows(points, COLUMNS, parsed_args)


class ShowPoint(base.FerryShowOne):
    """Show a backup point."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("point", metavar="<point>", help="point id")
        base.add_scope_argument(parser)
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.point_show(
            parsed_args.point, scope=parsed_args.scope), parsed_args)


class CreatePoint(base.FerryShowOne):
    """Take a manual backup now, of a plan or of one resource into a vault.

    Returns as soon as the job is queued rather than when the backup finishes;
    the returned job id is what to watch with ``openstack backup job show``.

    With --plan it runs under the plan's policy, into the plan's vault. Without,
    --resource names one server or volume, --resource-kind says which, and
    --vault names where it is kept; a resource in a plan whose vault is that
    one is backed up in the plan. --keep-until is within the vault's terms and
    is required into a vault, or --until-deleted where the vault offers it; on
    a locked repository nobody can erase the backup before its date.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--plan", metavar="<plan>", dest="plan_id",
                            help="plan to run")
        parser.add_argument("--resource", metavar="<id>", action="append",
                            dest="resource_ids",
                            help="with --plan, limit the run to these "
                                 "resources (repeatable); without, the one "
                                 "resource to back up")
        parser.add_argument("--resource-kind", metavar="<kind>",
                            choices=["instance", "volume"],
                            help="without --plan: instance or volume")
        target = parser.add_mutually_exclusive_group()
        target.add_argument("--vault", metavar="<vault>",
                            help="without --plan: the vault to keep it in")
        target.add_argument("--policy", metavar="<policy>",
                            help="without --plan, instead of --vault: the "
                                 "protection policy whose vault keeps it")
        parser.add_argument("--consistency", metavar="<level>",
                            choices=["filesystem", "crash"],
                            help="without --plan: freeze the guest or not; "
                                 "default this cloud's")
        until = parser.add_mutually_exclusive_group()
        until.add_argument("--keep-until", metavar="<timestamp>",
                           help="keep until this RFC 3339 timestamp, e.g. "
                                "2027-01-31T23:59:59Z")
        until.add_argument("--until-deleted", action="store_true",
                           help="keep it until somebody deletes it, where the "
                                "vault offers that")
        parser.add_argument("--force-full", action="store_true",
                            help="read the whole image instead of a diff")
        parser.add_argument("--wait", action="store_true",
                            help="wait for the backup job(s) to finish")
        return parser

    def take_action(self, parsed_args):
        if parsed_args.plan_id:
            if (parsed_args.resource_kind or parsed_args.vault or
                    parsed_args.policy or parsed_args.consistency):
                raise SystemExit(
                    "--resource-kind, --vault, --policy and --consistency "
                    "are for one resource into a vault")
            body = {"plan_id": self.app_client.plan_find(parsed_args.plan_id)}
            if parsed_args.resource_ids:
                body["resource_ids"] = parsed_args.resource_ids
        else:
            ids = parsed_args.resource_ids or []
            if (len(ids) != 1 or not parsed_args.resource_kind or
                    not (parsed_args.vault or parsed_args.policy)):
                raise SystemExit(
                    "--plan, or one --resource with --resource-kind and "
                    "--vault or --policy, is required")
            body = {"resource_id": ids[0],
                    "resource_kind": parsed_args.resource_kind}
            if parsed_args.vault:
                body["vault_id"] = self.app_client.vault_find(parsed_args.vault)
            else:
                body["policy_id"] = self.app_client.policy_find(parsed_args.policy)
            if parsed_args.consistency:
                body["consistency"] = parsed_args.consistency
        if parsed_args.keep_until:
            body["keep_until"] = parsed_args.keep_until
        if parsed_args.until_deleted:
            body["until_deleted"] = True
        if parsed_args.force_full:
            body["force_full"] = True
        result = self.app_client.point_create(body)
        if parsed_args.wait:
            runs = result.get("runs") or []
            job_ids = [r.get("job_id") for r in runs if r.get("job_id")]
            if not job_ids and result.get("job_id"):
                job_ids = [result["job_id"]]
            for job_id in job_ids:
                base.wait_for_job(self.app_client, job_id)
        return base.show(result, parsed_args)


class VerifyPoint(base.FerryShowOne):
    """Re-read a backup now and record what was found.

    Every chunk the backup references is fetched again and re-hashed.
    Verification otherwise runs as a rolling background pass, and that pass
    never returns to a point already marked broken: this is how a point marked
    by a mover too old to read it gets its state back once the movers are
    upgraded. Nothing changes until the job has read the data. Returns as soon
    as the job is queued; the job id is what to watch with
    ``openstack backup job show``.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("point", metavar="<point>", help="point id")
        return parser

    def take_action(self, parsed_args):
        return base.show(
            self.app_client.point_verify(parsed_args.point), parsed_args)


class DeletePoint(base.FerryCommand):
    """Delete one or more backup points.

    The point lands in the repository's soft-delete grace rather than going
    away, and an operator can reach into it until the grace elapses. A lock
    never refuses this: the point leaves your backups and your usage at once,
    and the storage still erases it no earlier than its lock date, never
    sooner. A point a legal hold still holds is refused, as is one whose
    policy is mandatory when the caller is a tenant.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("point", metavar="<point>", nargs="+",
                            help="point id")
        return parser

    def take_action(self, parsed_args):
        for point in parsed_args.point:
            self.app_client.point_delete(point)


class ShowPointMetrics(base.FerryShowOne):
    """Show what a backup cost: bytes read, bytes stored, and where the
    time went.

    An operator token additionally gets the repository-wide figures, each
    labelled with the scope it was computed in. A project token does not:
    those numbers move with what other projects have stored, so there is no
    per-project equivalent to report.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("point", metavar="<point>", help="point id")
        base.add_scope_argument(parser)
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.point_metrics(
            parsed_args.point, scope=parsed_args.scope), parsed_args)


class ShowPointDocument(base.FerryShowOne):
    """Show a point's recorded resource metadata.

    This is what a restore rebuilds from (flavor, networks, volume layout), so
    it is also the answer to "what exactly would come back".

    The document is read out of the repository rather than the database, which
    is why ``--repository`` is required: it is also what lets a cloud read the
    document of a point it has never seen.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("point", metavar="<point>", help="point id")
        parser.add_argument("--repository", metavar="<repository>",
                            required=True,
                            help="repository holding the point, by name or id")
        parser.add_argument("--domain", metavar="<domain>",
                            help="dedup domain, when it is not the default")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.point_document(
            parsed_args.point, parsed_args.repository, parsed_args.domain), parsed_args)
