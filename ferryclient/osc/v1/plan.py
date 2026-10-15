# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""``openstack backup plan ...``: which resources run under which policy."""

from ferryclient.osc.v1 import base

COLUMNS = ("id", "name", "enabled", "resource_kind", "policy",
           "next_run_at", "unsatisfied")

MISSED_TICK_COLUMNS = ("scheduled_for", "deadline", "reason", "recorded_at")

# argparse cannot tell "--exclude-disk ''" from "--exclude-disk was not given",
# and the two mean opposite things on an update: the first protects every disk
# again, the second leaves the selection alone. A sentinel default separates
# them.
UNSET_DISKS = object()

EXCLUDE_DISK_HELP = (
    "disks NOT to protect, comma-separated, as resource-id[:locator]. An "
    "instance covers its root disk and every attached volume; naming one here "
    "leaves it out of every backup, so restoring the instance will not bring "
    "it back and every point of this plan is partial"
)

POLICY_HELP = (
    "protection policy this plan runs under, by name or id. The policy carries "
    "the schedule, the retention ladder and the recovery objectives: they are "
    "the operator's to state and a plan names one"
)

CONSISTENCY_HELP = (
    "filesystem: freeze the guest before each backup. crash: do not. Omit to "
    "take this cloud's default. Not for buckets"
)


def _disk_selectors(value):
    """Parse ``id[:locator],id[:locator]`` into the wire form."""
    out = []
    for item in (value or "").split(","):
        item = item.strip()
        if not item:
            continue
        resource_id, _, locator = item.partition(":")
        resource_id = resource_id.strip()
        if not resource_id:
            raise SystemExit(f"--exclude-disk: {item!r} names no resource")
        selector = {"resource_id": resource_id}
        if locator.strip():
            selector["locator"] = locator.strip()
        out.append(selector)
    return out


def _named_policy(plans):
    out = []
    for plan in plans:
        row = dict(plan)
        policy = row.get("policy")
        if isinstance(policy, dict):
            row["policy"] = policy.get("name") or policy.get("id")
        out.append(row)
    return out


class ListPlan(base.FerryLister):
    """List protection plans."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--enabled", action="store_true", default=None,
                            help="only enabled plans")
        parser.add_argument("--resource-kind", metavar="<kind>",
                            help="volume, instance or bucket")
        parser.add_argument("--limit", type=int, help="maximum plans returned")
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's plans (operator; needs a "
                                 "system-scoped token)")
        return parser

    def take_action(self, parsed_args):
        plans = self.app_client.plan_list(
            enabled=parsed_args.enabled,
            resource_kind=parsed_args.resource_kind,
            limit=parsed_args.limit,
            project_id=parsed_args.project_id,
        )
        return COLUMNS, base.rows(_named_policy(plans), COLUMNS, parsed_args)


class ShowPlan(base.FerryShowOne):
    """Show a protection plan, its policy, and any refusals it carries."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("plan", metavar="<plan>",
                            help="plan, by name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.plan_show(parsed_args.plan), parsed_args)


class CreatePlan(base.FerryShowOne):
    """Create a protection plan.

    A plan says what to protect, under which policy, with which key. It states
    no schedule and no retention: ``openstack backup policy list`` is the
    catalogue of what the operator offers, and the plan names one of them.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("name", metavar="<name>", help="plan name")
        parser.add_argument("--resource-kind", metavar="<kind>", required=True,
                            help="volume, instance or bucket")
        parser.add_argument("--resource", metavar="<id>", action="append",
                            dest="resource_ids", default=[], required=True,
                            help="resource to protect (repeatable)")
        parser.add_argument("--policy", metavar="<policy>", required=True,
                            help=POLICY_HELP)
        # There is deliberately no flag here for naming the storage namespace
        # this plan writes into. That namespace is derived, and a tenant
        # choosing it is a tenant configuring the operator's storage. The
        # encryption choice is the whole of what a tenant decides.
        parser.add_argument("--encryption", metavar="<mode>",
                            choices=["barbican", "none"],
                            help="barbican: this workload gets a key of its "
                                 "own and its storage is kept apart from every "
                                 "other workload's. none: stored unencrypted, "
                                 "sharing storage with other unencrypted "
                                 "workloads. Omit to keep the existing "
                                 "behaviour")
        parser.add_argument("--consistency", metavar="<level>",
                            choices=["crash", "filesystem"],
                            help=CONSISTENCY_HELP)
        parser.add_argument("--exclude-disk", metavar="<id[:locator]>",
                            dest="exclude_disks", help=EXCLUDE_DISK_HELP)
        parser.add_argument("--label", metavar="<key=value>", action="append",
                            dest="labels",
                            help="advisory label, repeatable. Copied onto every "
                                 "point this plan writes and frozen there, so "
                                 "an operator deciding what to recover can see "
                                 "what it was for")
        parser.add_argument("--accept-partial-coverage", metavar="<digest>",
                            help="accept an account of a workload the "
                                 "service can protect only in part, by the "
                                 "digest the 409 or 'resource list' reported. "
                                 "Without it a partial workload is refused")
        return parser

    def take_action(self, parsed_args):
        body = {
            "name": parsed_args.name,
            "resource_kind": parsed_args.resource_kind,
            "resource_ids": parsed_args.resource_ids,
            "policy_id": self.app_client.policy_find(parsed_args.policy),
        }
        if parsed_args.encryption:
            body["encryption"] = parsed_args.encryption
        if parsed_args.consistency:
            body["consistency"] = parsed_args.consistency
        if parsed_args.exclude_disks:
            body["excluded_disks"] = _disk_selectors(parsed_args.exclude_disks)
        labels = base.parse_properties(parsed_args.labels, "--label")
        if labels:
            body["labels"] = labels
        if parsed_args.accept_partial_coverage:
            body["partial_coverage"] = {
                "accept": True,
                "digest": parsed_args.accept_partial_coverage,
            }
        return base.show(self.app_client.plan_create(body), parsed_args)


class SetPlan(base.FerryCommand):
    """Update a protection plan.

    What a tenant may change is what only a tenant knows: the name, the
    resources, the disks to leave out, whether it is running, and which of the
    policies their project may name it runs under. A move to a weaker policy,
    and any move at all off a mandatory one, is an operator's call.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("plan", metavar="<plan>",
                            help="plan, by name or id")
        parser.add_argument("--name", metavar="<name>")
        enabled = parser.add_mutually_exclusive_group()
        enabled.add_argument("--enable", dest="enabled", action="store_true",
                             default=None)
        enabled.add_argument("--disable", dest="enabled", action="store_false",
                             default=None,
                             help="stop taking backups. Refused for a tenant "
                                  "when the policy is mandatory")
        parser.add_argument("--policy", metavar="<policy>", help=POLICY_HELP)
        parser.add_argument("--consistency", metavar="<level>",
                            choices=["crash", "filesystem"],
                            help=CONSISTENCY_HELP)
        parser.add_argument("--resource", metavar="<id>", action="append",
                            dest="resource_ids",
                            help="replace the protected resource list "
                                 "(repeatable)")
        parser.add_argument("--exclude-disk", metavar="<id[:locator]>",
                            dest="exclude_disks", default=UNSET_DISKS,
                            help="replace the excluded-disk list. " +
                                 EXCLUDE_DISK_HELP +
                                 ". Pass an empty value to protect every disk "
                                 "again")
        parser.add_argument("--accept-partial-coverage", metavar="<digest>",
                            help="accept the partial-coverage account of the "
                                 "new resource set; meaningless without "
                                 "--resource")
        return parser

    def take_action(self, parsed_args):
        body = {}
        for key, value in (
            ("name", parsed_args.name),
            ("enabled", parsed_args.enabled),
            ("consistency", parsed_args.consistency),
            ("resource_ids", parsed_args.resource_ids),
        ):
            if value is not None:
                body[key] = value
        if parsed_args.policy:
            body["policy_id"] = self.app_client.policy_find(parsed_args.policy)
        # An empty string means protect every disk again, so it is sent; the sentinel keeps the current selection.
        if parsed_args.exclude_disks is not UNSET_DISKS:
            body["excluded_disks"] = _disk_selectors(parsed_args.exclude_disks)
        if parsed_args.accept_partial_coverage:
            body["partial_coverage"] = {
                "accept": True,
                "digest": parsed_args.accept_partial_coverage,
            }
        if not body:
            raise SystemExit("nothing to change: pass at least one option")
        self.app_client.plan_update(parsed_args.plan, body)


class DeletePlan(base.FerryCommand):
    """Delete one or more protection plans.

    The plan lands in the repository's soft-delete grace rather than going
    away: hidden from the listing, restorable by an operator until the grace
    elapses. A plan under a mandatory policy is refused.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("plan", metavar="<plan>", nargs="+",
                            help="plan, by name or id")
        return parser

    def take_action(self, parsed_args):
        for plan in parsed_args.plan:
            self.app_client.plan_delete(plan)


class RestorePlan(base.FerryShowOne):
    """Lift a plan's soft delete (operator).

    What it recovers is the plan and everything still inside its grace. A plan
    whose grace has elapsed is gone, and this reports that rather than
    pretending otherwise.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("plan", metavar="<plan>",
                            help="plan, by name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(
            self.app_client.plan_restore(parsed_args.plan), parsed_args)


class ListPlanRefusal(base.FerryLister):
    """List what a plan will not protect, and why.

    Reported on the plan itself rather than only at creation, because a
    degradation such as fast-diff becoming unavailable is worth seeing every
    time the plan is read.
    """

    columns = ("resource_id", "resource_kind", "reason", "detail")

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("plan", metavar="<plan>",
                            help="plan, by name or id")
        return parser

    def take_action(self, parsed_args):
        refusals = self.app_client.plan_refusals(parsed_args.plan)
        return self.columns, base.rows(refusals, self.columns, parsed_args)


class ListPlanMissedTick(base.FerryLister):
    """List the scheduled instants of a plan that produced no backup.

    A tick that cannot start inside the policy's ``start_within`` is missed,
    not queued: a plan six hours behind must not run two backups back to back
    into a production cluster. The reason says whether that was the window, a
    policy that no longer exists, one that is retired, or one naming storage it
    cannot use.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("plan", metavar="<plan>",
                            help="plan, by name or id")
        parser.add_argument("--limit", type=int,
                            help="maximum missed ticks returned")
        return parser

    def take_action(self, parsed_args):
        ticks = self.app_client.plan_missed_ticks(parsed_args.plan,
                                                  limit=parsed_args.limit)
        return MISSED_TICK_COLUMNS, base.rows(ticks, MISSED_TICK_COLUMNS,
                                              parsed_args)


class ShowPlanSLA(base.FerryShowOne):
    """Show a plan's protection SLA: what the policy promised against what it did."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("plan", metavar="<plan>",
                            help="plan, by name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.plan_sla(parsed_args.plan), parsed_args)
