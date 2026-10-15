# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
from ferryclient.osc.v1 import base

COLUMNS = ("id", "name", "state", "mandatory", "sentence")

CALENDAR_TIERS = ("daily", "weekly", "monthly", "yearly")
STATES = ("active", "deprecated", "retired")


def _count_or_duration(value):
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def _ladder_pairs(flag, values):
    return {key: _count_or_duration(value)
            for key, value in base.parse_properties(values, flag).items()}


def _schedule(args):
    out = {}
    for key, value in (
        ("every", args.every),
        ("cron", args.cron),
        ("at", args.at),
        ("window_start", args.window_start),
        ("window_end", args.window_end),
        ("jitter", args.jitter),
        ("start_within", args.start_within),
    ):
        if value:
            out[key] = value
    return out


def _keep(args):
    out = {}
    if args.keep_all:
        out["all"] = args.keep_all
    for tier in CALENDAR_TIERS:
        value = getattr(args, "keep_" + tier)
        if value is not None:
            out[tier] = value
    anchors = base.parse_properties(args.anchor, "--anchor")
    if anchors:
        out["anchors"] = anchors
    return out


def _tiers(args, find_repository):
    out = {}
    if args.backup_repository:
        out["backup"] = {
            "repository_id": find_repository(args.backup_repository)}
    instant = {}
    if args.instant_tier:
        instant["repository_id"] = find_repository(args.instant_tier)
    if args.instant_within:
        instant["within"] = args.instant_within
    if instant:
        out["instant"] = instant
    copy = {}
    if args.copy_repository:
        copy["repository_id"] = find_repository(args.copy_repository)
    copy_keep = _ladder_pairs("--copy-keep", args.copy_keep)
    if copy_keep:
        copy["keep"] = copy_keep
    if copy:
        out["copy"] = copy
    return out


def _recovery(args, find_site):
    out = {}
    if args.recovery_site:
        out["site_id"] = find_site(args.recovery_site)
    for key, value in (
        ("rung", args.recovery_rung),
        ("transport", args.transport),
        ("rpo_target", args.rpo_target),
        ("rto_target", args.rto_target),
    ):
        if value:
            out[key] = value
    if args.test_every:
        out["test"] = {"every": args.test_every}
    return out


def _spec(args, client):
    spec = {}
    for key, block in (
        ("schedule", _schedule(args)),
        ("keep", _keep(args)),
        ("tiers", _tiers(args, client.repository_find)),
        ("recovery", _recovery(args, client.site_find)),
    ):
        if block:
            spec[key] = block
    if args.verify_every:
        spec["verify"] = {"every": args.verify_every}
    return spec


def _add_spec_options(parser, required):
    note = "" if required else (
        ": an update sends the spec WHOLE, so restate the schedule, the "
        "ladder and the tiers you want kept, not only what changes")

    schedule = parser.add_argument_group("schedule" + note)
    cadence = schedule.add_mutually_exclusive_group(required=required)
    cadence.add_argument("--every", metavar="<duration>",
                         help="cadence, 15m to 168h, e.g. 1h. A cadence under "
                              "a day must divide one evenly")
    cadence.add_argument("--cron", metavar="<expr>",
                         help="cron expression, for a cadence no interval "
                              "describes, e.g. '0 2 * * 1-5'")
    schedule.add_argument("--at", metavar="<HH:MM>",
                          help="phase for a cadence of a day or longer, "
                               "site-local")
    schedule.add_argument("--window-start", metavar="<HH:MM>",
                          help="earliest time a tick may run")
    schedule.add_argument("--window-end", metavar="<HH:MM>",
                          help="latest time a tick may run")
    schedule.add_argument("--jitter", metavar="<duration>",
                          help="random spread so every plan under this policy "
                               "does not fire at once, e.g. 30m")
    schedule.add_argument("--start-within", metavar="<duration>",
                          help="a tick that has not started by then is "
                               "recorded as missed, not queued behind the next "
                               "one, e.g. 2h")

    keep = parser.add_argument_group("retention ladder" + note)
    keep.add_argument("--keep-all", metavar="<duration>",
                      help="how long every point lives, e.g. 48h. A duration "
                           "rather than a count, because the repository's lock "
                           "needs a date")
    for tier in CALENDAR_TIERS:
        keep.add_argument("--keep-" + tier, metavar="<count>", type=int,
                          help=f"{tier} points to keep: the first point "
                               f"committed in each anchored period wins the "
                               f"{tier} role and lives this many periods")
    keep.add_argument("--anchor", metavar="<key=value>", action="append",
                      help="period grid, repeatable: week=sunday, "
                           "month=first|last, year=january")

    tiers = parser.add_argument_group("tiers (where the bytes land)" + note)
    tiers.add_argument("--backup-repository", metavar="<repository>",
                       required=required,
                       help="chunk repository every point is written to. Its "
                            "retention contract is the floor this policy's "
                            "ladder must clear")
    tiers.add_argument("--instant-tier", metavar="<repository>",
                       help="rbd tier that keeps recent points restorable by "
                            "clone")
    tiers.add_argument("--instant-within", metavar="<duration>",
                       help="how long a point stays on the instant tier, "
                            "e.g. 168h")
    tiers.add_argument("--copy-repository", metavar="<repository>",
                       help="second chunk repository every committed point is "
                            "copied to")
    tiers.add_argument("--copy-keep", metavar="<tier=value>", action="append",
                       help="ladder for the copy, repeatable: all=<duration>, "
                            "daily=7, monthly=12")

    recovery = parser.add_argument_group("recovery" + note)
    recovery.add_argument("--recovery-site", metavar="<site>",
                          help="site the recovery promise is made about, by "
                               "name or id (openstack backup site list)")
    recovery.add_argument("--recovery-rung", metavar="<rung>",
                          choices=["cold", "warm", "hot"],
                          help="cold: the copy is readable there. warm: a "
                               "standby per resource. hot: a mirror "
                               "relationship")
    recovery.add_argument("--transport", metavar="<transport>",
                          choices=["rbd-mirror", "repository"],
                          help="how the recoverable copy reaches the site: "
                               "rbd-mirror for hot, repository for cold and "
                               "warm; the rung's own when omitted")
    recovery.add_argument("--rpo-target", metavar="<duration>",
                          help="recovery point objective. A cold or warm rung "
                               "cannot promise less than the cadence")
    recovery.add_argument("--rto-target", metavar="<duration>",
                          help="recovery time objective, e.g. 30m")
    recovery.add_argument("--test-every", metavar="<duration>",
                          help="cadence of test failovers into the bubble, "
                               "e.g. 720h")

    parser.add_argument("--verify-every", metavar="<duration>",
                        help="cadence of verification of the newest point of "
                             "each plan, e.g. 720h. Manual backups are the "
                             "vault's terms, not the policy's")
    return parser


class ListPolicy(base.FerryLister):
    """List protection policies.

    A tenant is served the policies their project may name, as sentences. An
    operator is served all of them; ``policy show`` is where the spec is.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--state", metavar="<state>", choices=list(STATES),
                            help="active, deprecated or retired")
        parser.add_argument("--unsatisfied", action="store_true", default=None,
                            help="only policies naming something they cannot "
                                 "use")
        parser.add_argument("--limit", type=int,
                            help="maximum policies returned")
        base.add_scope_argument(parser)
        return parser

    def take_action(self, parsed_args):
        policies = self.app_client.policy_list(
            state=parsed_args.state,
            unsatisfied="true" if parsed_args.unsatisfied else None,
            limit=parsed_args.limit,
            scope=parsed_args.scope,
        )
        return COLUMNS, base.rows(policies, COLUMNS, parsed_args)


class ShowPolicy(base.FerryShowOne):
    """Show a protection policy, its sentence and anything it cannot satisfy."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("policy", metavar="<policy>",
                            help="policy name or id")
        base.add_scope_argument(parser)
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.policy_show(
            parsed_args.policy, scope=parsed_args.scope), parsed_args)


class CreatePolicy(base.FerryShowOne):
    """Write a protection policy (operator).

    Everything a tenant used to type into a plan (the schedule, the retention,
    the recovery objectives) is stated here once, by the party that
    provisioned the capacity for it.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("name", metavar="<name>", help="policy name")
        parser.add_argument("--description", metavar="<text>",
                            help="what this service level is for")
        parser.add_argument("--visibility", metavar="<visibility>",
                            choices=["public", "assigned"],
                            help="public: any project may name it. assigned: "
                                 "only the domains and projects it is assigned "
                                 "to")
        parser.add_argument("--mandatory", action="store_true",
                            help="a tenant may not pause or delete a plan "
                                 "under this policy, nor move it to a weaker "
                                 "one")
        _add_spec_options(parser, required=True)
        return parser

    def take_action(self, parsed_args):
        body = {"name": parsed_args.name,
                "spec": _spec(parsed_args, self.app_client)}
        if parsed_args.description:
            body["description"] = parsed_args.description
        if parsed_args.visibility:
            body["visibility"] = parsed_args.visibility
        if parsed_args.mandatory:
            body["mandatory"] = True
        return base.show(self.app_client.policy_create(body), parsed_args)


class SetPolicy(base.FerryCommand):
    """Edit a protection policy (operator).

    An edit applies forward: every point already written keeps its expiry and
    its lock. ``--apply-to-existing`` re-derives the expiry of every unlocked
    point under the policy, and shortening one is a separately granted action.
    Run ``openstack backup retention simulate`` first to see what it frees.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("policy", metavar="<policy>",
                            help="policy name or id")
        parser.add_argument("--name", metavar="<name>")
        parser.add_argument("--description", metavar="<text>")
        parser.add_argument("--visibility", metavar="<visibility>",
                            choices=["public", "assigned"])
        mandatory = parser.add_mutually_exclusive_group()
        mandatory.add_argument("--mandatory", dest="mandatory",
                               action="store_true", default=None)
        mandatory.add_argument("--not-mandatory", dest="mandatory",
                               action="store_false", default=None)
        parser.add_argument("--apply-to-existing", action="store_true",
                            help="re-derive the expiry of every unlocked point "
                                 "already under this policy, not only the ones "
                                 "written from now on")
        _add_spec_options(parser, required=False)
        return parser

    def take_action(self, parsed_args):
        body = {}
        for key, value in (
            ("name", parsed_args.name),
            ("description", parsed_args.description),
            ("visibility", parsed_args.visibility),
            ("mandatory", parsed_args.mandatory),
        ):
            if value is not None:
                body[key] = value
        spec = _spec(parsed_args, self.app_client)
        if spec:
            body["spec"] = spec
        if not body:
            raise SystemExit("nothing to change: pass at least one option")
        self.app_client.policy_update(
            parsed_args.policy, body,
            apply_to_existing=parsed_args.apply_to_existing)


class AssignPolicy(base.FerryShowOne):
    """Offer a policy to domains and projects, or withdraw it (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("policy", metavar="<policy>",
                            help="policy name or id")
        parser.add_argument("--project", metavar="<project>",
                            action="append", dest="projects",
                            help="project id (repeatable)")
        parser.add_argument("--domain", metavar="<domain>",
                            action="append", dest="domains",
                            help="domain id; every project in it may name the "
                                 "policy (repeatable)")
        parser.add_argument("--remove", action="store_true",
                            help="withdraw the assignment instead of adding "
                                 "it. Plans already under the policy keep "
                                 "running")
        return parser

    def take_action(self, parsed_args):
        body = {}
        if parsed_args.projects:
            body["projects"] = parsed_args.projects
        if parsed_args.domains:
            body["domains"] = parsed_args.domains
        if not body:
            raise SystemExit(
                "name at least one --project or --domain to assign")
        return base.show(self.app_client.policy_assign(
            parsed_args.policy, body, remove=parsed_args.remove), parsed_args)


class DeprecatePolicy(base.FerryShowOne):
    """Deprecate a policy: no new plan may name it, existing plans run on."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("policy", metavar="<policy>",
                            help="policy name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(
            self.app_client.policy_deprecate(parsed_args.policy), parsed_args)


class RetirePolicy(base.FerryShowOne):
    """Retire a policy, moving every plan under it to a successor.

    Retiring needs either no plans at all or a successor that is not weaker:
    a shorter ``keep all``, an unlocked repository where the old one was
    locked, or a lower recovery rung is refused by name. Points keep their
    dates through the move.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("policy", metavar="<policy>",
                            help="policy name or id")
        parser.add_argument("--successor", metavar="<policy>",
                            help="policy every plan is moved to, by name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.policy_retire(
            parsed_args.policy, successor=parsed_args.successor), parsed_args)


class DeletePolicy(base.FerryCommand):
    """Delete a policy no plan has ever named (operator).

    Deleting is for a draft, not for a policy in service: one with a live plan
    under it, or with a plan still inside its delete grace, is refused and
    named. Retire it onto a successor instead.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("policy", metavar="<policy>", nargs="+",
                            help="policy name or id")
        return parser

    def take_action(self, parsed_args):
        for policy in parsed_args.policy:
            self.app_client.policy_delete(policy)
