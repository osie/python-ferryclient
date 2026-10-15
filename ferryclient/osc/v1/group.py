# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""``openstack backup group ...``: protection groups and failover."""

from ferryclient.osc.v1 import base

COLUMNS = ("id", "name", "role", "state", "custody", "custody_epoch",
           "active_run_id", "member_count", "created_at")
RUN_COLUMNS = ("id", "operation", "mode", "state", "phase", "started_at",
               "finished_at")
MIRROR_COLUMNS = ("member_instance_id", "pool", "image", "global_id", "role",
                  "state", "mirror_state", "peer_site", "peer_state",
                  "last_complete_at", "lag_seconds", "split_brain", "error")
RECOVER_MODES = ("planned", "unplanned")
RECOVERY_POINTS = ("aligned", "newest")
ROLES = ("primary", "recovery")


class ListGroup(base.FerryLister):
    """List protection groups."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's groups (operator; needs a "
                                 "system-scoped token)")
        parser.add_argument("--role", metavar="<role>", choices=ROLES,
                            help="only groups created here (primary) or only "
                                 "recoveries of another region's groups "
                                 "(recovery)")
        return parser

    def take_action(self, parsed_args):
        groups = self.app_client.group_list(
            limit=parsed_args.limit, project_id=parsed_args.project_id,
            role=parsed_args.role)
        groups = [dict(g, member_count=len(g.get("members") or []))
                  for g in groups]
        return COLUMNS, base.rows(groups, COLUMNS, parsed_args)


class ShowGroup(base.FerryShowOne):
    """Show a protection group."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.group_show(parsed_args.group), parsed_args)


class CreateGroup(base.FerryShowOne):
    """Create a protection group.

    A group is the unit of failover: its instances come back together and to
    a consistent moment, in the boot order given, which is what makes it
    different from a set of unrelated plans that happen to run at the same
    time.

    A group is created under a protection policy, and that policy's recovery
    section is the group's promise: the site it recovers to, the rung, and
    the recovery objectives. Every member must already be protected by a plan
    under that policy.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("name", metavar="<name>", help="group name")
        parser.add_argument("--policy", metavar="<policy>", dest="policy_id",
                            required=True,
                            help="protection policy, by name or id, whose "
                                 "recovery section is the group's promise. "
                                 "Every member must already be under a plan "
                                 "with this policy")
        parser.add_argument("--instance", metavar="<instance>",
                            action="append", dest="instances", required=True,
                            help="instance to include (repeatable). Boot "
                                 "order follows the order given, which is the "
                                 "order they come back in")
        parser.add_argument("--network-map", metavar="<from=to>",
                            action="append", dest="network_map",
                            help="network in the recovery region's point to "
                                 "network here, read only by a failback that "
                                 "rebuilds a member whose original is gone; a "
                                 "failover uses the registration's map "
                                 "(repeatable)")
        return parser

    def take_action(self, parsed_args):
        members = [
            {"instance_id": instance, "boot_order": order}
            for order, instance in enumerate(parsed_args.instances)
        ]
        body = {
            "name": parsed_args.name,
            "policy_id": self.app_client.policy_find(parsed_args.policy_id),
            "members": members,
        }
        if parsed_args.network_map:
            body["network_map"] = base.parse_properties(parsed_args.network_map)
        return base.show(self.app_client.group_create(body), parsed_args)


class RegisterGroup(base.FerryShowOne):
    """Register this region's recovery of another region's group (operator).

    The group's members, boot order and promise come from the group document
    its home wrote into a repository this region reads; ``openstack backup
    recovery group list`` shows the ones read so far. Registering binds every
    member to the target project, with a standby in ``--standby-pool`` when
    the group's policy promises the warm rung, and follows the document as
    members are added at home. A member already bound to another project is
    refused with ``binding_conflict``.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group_uid", metavar="<group-uid>",
                            help="the group's uid, as its home minted it")
        parser.add_argument("--repository", metavar="<repository>",
                            required=True,
                            help="repository the group's document was read "
                                 "from, by name or id")
        parser.add_argument("--origin-cloud", metavar="<cloud>",
                            help="cloud that wrote the document; refused if "
                                 "the document names another")
        parser.add_argument("--target-project", metavar="<project>",
                            required=True,
                            help="project here the group recovers into")
        parser.add_argument("--target-domain", metavar="<domain>",
                            help="domain of the target project; needed only "
                                 "when the service cannot look the project up")
        parser.add_argument("--policy", metavar="<policy>", dest="policy_id",
                            required=True,
                            help="this region's policy, by name or id, whose "
                                 "recovery site is the group's home")
        parser.add_argument("--name", metavar="<name>",
                            help="name here; defaults to the group's name")
        parser.add_argument("--mapping-profile", metavar="<profile>",
                            help="recovery profile, by name or id, that "
                                 "translates the home's flavors and networks")
        parser.add_argument("--bubble-policy", metavar="<bubble-policy>",
                            dest="bubble_policy_id",
                            help="bubble policy, by name or id, tests of the "
                                 "group run in")
        parser.add_argument("--test-every", metavar="<duration>",
                            help="test cadence, e.g. 720h; defaults to the "
                                 "cadence the group's policy promised")
        parser.add_argument("--standby-pool", metavar="<pool>",
                            help="pool the members' standbys live in; "
                                 "required for a warm group")
        parser.add_argument("--standby-site", metavar="<site>",
                            help="site the standbys live at, by name or id; "
                                 "defaults to this cloud's own")
        parser.add_argument("--standby-prefix", metavar="<prefix>",
                            help="prefix for the standbys' image names")
        parser.add_argument("--accept-gap", metavar="<element>",
                            action="append", dest="accept_gaps",
                            help="unresolved mapping element a recovery may "
                                 "leave unmapped, e.g. network:net-1 "
                                 "(repeatable)")
        parser.add_argument("--network-map", metavar="<from=to>",
                            action="append", dest="network_map",
                            help="home network to network here (repeatable)")
        return parser

    def take_action(self, parsed_args):
        if (parsed_args.standby_site or parsed_args.standby_prefix) and \
                not parsed_args.standby_pool:
            raise SystemExit("--standby-site and --standby-prefix need "
                             "--standby-pool; without a pool there is no "
                             "standby for them to describe")
        client = self.app_client
        profile = None
        if parsed_args.mapping_profile:
            profile = client.recovery_profile_find(parsed_args.mapping_profile)
        site = None
        if parsed_args.standby_site:
            site = client.site_find(parsed_args.standby_site)
        bubble_policy = None
        if parsed_args.bubble_policy_id:
            bubble_policy = client.bubble_policy_find(
                parsed_args.bubble_policy_id)
        return base.show(client.group_register(
            client.repository_find(parsed_args.repository),
            parsed_args.group_uid,
            parsed_args.target_project,
            client.policy_find(parsed_args.policy_id),
            origin_cloud=parsed_args.origin_cloud,
            name=parsed_args.name,
            target_domain_id=parsed_args.target_domain,
            mapping_profile_id=profile,
            bubble_policy_id=bubble_policy,
            test_every=parsed_args.test_every,
            standby_pool=parsed_args.standby_pool,
            standby_site_id=site,
            standby_prefix=parsed_args.standby_prefix,
            accept_gaps=parsed_args.accept_gaps,
            network_map=base.parse_properties(parsed_args.network_map,
                                              flag="--network-map")),
            parsed_args)


class ShowGroupReadiness(base.FerryShowOne):
    """Show whether a group could be recovered right now, member by member.

    Where the group recovers, what each member would recover to and what a
    recover would refuse. Where the group runs, what the recovery region last
    reported, and how old that report is.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.group_readiness(parsed_args.group),
                         parsed_args)


class ListGroupMirror(base.FerryLister):
    """List a hot group's mirrored disks as this region's cluster reads them.

    One row per disk: its role and status here, the peer cluster's status,
    the newest complete mirror snapshot, how far behind the RPO target it is,
    and whether either cluster reports split brain.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        return parser

    def take_action(self, parsed_args):
        mirror = self.app_client.group_mirror(parsed_args.group) or {}
        return MIRROR_COLUMNS, base.rows(mirror.get("images") or [],
                                         MIRROR_COLUMNS, parsed_args)


class ArmGroup(base.FerryShowOne):
    """Give this region a standing delegation to act in the group's project.

    A recover builds servers and volumes in the group's project, and a
    failback at home starts or rebuilds them there; both act through the
    delegation a member of the project gives here. A release, a resync, a
    retire and a test do not use it. Arming again replaces the previous
    delegation.

    Arm with a token scoped to the group's project, issued to a member of it.
    A system-scoped token is refused (403), and a token scoped to another
    project does not find the group (404). The alternative to arming is an
    operator granting this region's service user a role in the project;
    readiness says which of the two a run would use.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--expires-in", metavar="<duration>",
                            help="how long the delegation lasts, from 1h to "
                                 "8784h; 90 days when not given")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.group_arm(
            parsed_args.group, expires_in=parsed_args.expires_in), parsed_args)


class DisarmGroup(base.FerryCommand):
    """Withdraw the delegation a group was armed with."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        return parser

    def take_action(self, parsed_args):
        self.app_client.group_disarm(parsed_args.group)


class DeleteGroup(base.FerryCommand):
    """Delete one or more protection groups.

    A recovery registration whose runs built servers, volumes, ports or
    floating addresses here and kept them is refused while they are still
    held: retire it first, or fail it back and then retire it where the
    workload runs here. --keep-resources deletes it anyway and leaves them
    to the project as they are.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>", nargs="+",
                            help="group, by name or id")
        parser.add_argument("--keep-resources", action="store_true",
                            help="delete a recovery registration even though "
                                 "objects its runs built are still held, "
                                 "leaving them to the project (operator)")
        return parser

    def take_action(self, parsed_args):
        for group in parsed_args.group:
            self.app_client.group_delete(
                group, keep_resources=parsed_args.keep_resources)


def _require_dr(client):
    caps = client.capabilities() or {}
    if caps.get("dr") is not True:
        raise SystemExit(caps.get("dr_reason")
                         or "failover is not available on this cloud")


def _run_view(resp):
    if not isinstance(resp, dict) or "run" not in resp:
        return resp
    view = dict(resp.get("run") or {})
    if resp.get("job_id"):
        view["job_id"] = resp["job_id"]
    return view


def _plan_member_line(member):
    who = member.get("instance_id") or "-"
    if member.get("name"):
        who = f"{member['name']} ({who})"
    line = f"{member.get('boot_order', '-')} {who}: point " \
           f"{member.get('point_id') or '-'}"
    if member.get("recovery_point_at"):
        line += f" at {member['recovery_point_at']}"
    if member.get("partial"):
        line += " (partial)"
    if member.get("return_to_original"):
        line += ", returns to its original"
        if member.get("delta"):
            line += " (changes only)"
        elif member.get("delta_reason"):
            line += f" (full copy: {member['delta_reason']})"
    elif member.get("rebuild"):
        line += ", rebuilt"
    elif member.get("running_instance_id"):
        line += f", stops {member['running_instance_id']}"
    diverged = [d.get("resource_id") for d in member.get("divergence") or []
                if d.get("diverged")]
    if diverged:
        line += f", diverged: {', '.join(diverged)}"
    if member.get("divergence_unverifiable"):
        line += f", not checked: {member['divergence_unverifiable']}"
    return line


def _run_member_line(member):
    who = member.get("source_instance_id") or "-"
    if member.get("name"):
        who = f"{member['name']} ({who})"
    line = f"{member.get('boot_order', '-')} {who}: {member.get('state')}"
    for label, key in (("instance", "instance_id"), ("booted", "booted_at"),
                       ("healthy", "healthy_at"), ("error", "error")):
        if member.get(key):
            line += f", {label} {member[key]}"
    return line


def _run_show_view(run, parsed_args):
    if not isinstance(run, dict) or base.structured(parsed_args) \
            or not run.get("members"):
        return run
    return dict(run, members="\n".join(
        _run_member_line(m) for m in run["members"]))


def _plan_view(resp, parsed_args):
    plan = dict((resp or {}).get("plan") or {})
    plan["dry_run"] = True
    if not base.structured(parsed_args):
        plan["members"] = "\n".join(
            _plan_member_line(m) for m in plan.get("members") or [])
    return plan


def _run_or_plan(resp, parsed_args):
    if parsed_args.dry_run:
        return base.show(_plan_view(resp, parsed_args), parsed_args)
    return base.show(_run_view(resp), parsed_args)


class ReleaseGroup(base.FerryShowOne):
    """Release a protection group where it runs: stop it, take its last copy and hand it over.

    The members' plans pause, each instance is locked and stopped, a final
    point of each is taken and copied, and the release record the recovery
    region verifies is written. Until that record is written, a failure
    starts the instances again and resumes the plans.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--reason", metavar="<reason>",
                            help="why the group is released, recorded with "
                                 "the run")
        parser.add_argument("--override-recovery-readiness",
                            action="store_true",
                            help="release even without a fresh readiness "
                                 "report from the recovery region (operator)")
        parser.add_argument("--dry-run", action="store_true",
                            help="show what the release would stop and the "
                                 "recovery region's last report, and start "
                                 "nothing")
        return parser

    def take_action(self, parsed_args):
        _require_dr(self.app_client)
        return _run_or_plan(self.app_client.group_release(
            parsed_args.group, reason=parsed_args.reason,
            override_recovery_readiness=parsed_args.override_recovery_readiness,
            dry_run=parsed_args.dry_run), parsed_args)


class RecoverGroup(base.FerryShowOne):
    """Recover a protection group here, planned after a release or unplanned without one.

    At the group's home a planned recover is the failback: each member
    returns to its original instance, copying only what changed where it
    can, and the recover refuses if an original was written after it was
    released. --overwrite-diverged (operator) comes home anyway: each
    diverged original is stopped, kept as a divergence point, and written
    over in full. An unplanned recover at home takes the originals back as
    they are.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--mode", metavar="<mode>", choices=RECOVER_MODES,
                            required=True,
                            help="planned, after a release the recovery "
                                 "region can verify, or unplanned (operator)")
        parser.add_argument("--confirm-primary-may-be-serving-writes",
                            "--confirm", action="store_true", dest="confirm",
                            help="acknowledge that the other region may "
                                 "still be serving writes; required for "
                                 "--mode unplanned")
        parser.add_argument("--wait-for-release", metavar="<duration>",
                            help="planned only: wait up to this long, at most "
                                 "30m, for the release to be verifiable")
        parser.add_argument("--recovery-point", metavar="<choice>",
                            choices=RECOVERY_POINTS,
                            help="aligned, the default: every member at the "
                                 "newest instant they all hold a point for; "
                                 "newest: each member's own newest point")
        parser.add_argument("--max-point-age", metavar="<duration>",
                            help="refuse the recover if any member's recovery "
                                 "point is older than this, e.g. 2h")
        parser.add_argument("--overwrite-diverged", action="store_true",
                            help="planned failback only (operator): come home "
                                 "over originals that diverged, keeping what "
                                 "each holds as a divergence point first")
        parser.add_argument("--dry-run", action="store_true",
                            help="show the plan, member by member, with the "
                                 "point each recovers to, and start nothing")
        parser.add_argument("--reason", metavar="<reason>",
                            help="why the group is recovered, recorded with "
                                 "the run")
        return parser

    def take_action(self, parsed_args):
        if parsed_args.mode == "unplanned" and not parsed_args.confirm:
            raise SystemExit(
                "an unplanned recover needs "
                "--confirm-primary-may-be-serving-writes: the other region "
                "may still be serving writes, and recovering here while it "
                "is would split the data in two")
        if parsed_args.overwrite_diverged and parsed_args.mode != "planned":
            raise SystemExit(
                "--overwrite-diverged applies only to a planned failback at "
                "the group's home")
        _require_dr(self.app_client)
        resp = self.app_client.group_recover(
            parsed_args.group, parsed_args.mode, confirm=parsed_args.confirm,
            reason=parsed_args.reason,
            wait_for_release=parsed_args.wait_for_release,
            recovery_point=parsed_args.recovery_point,
            max_point_age=parsed_args.max_point_age,
            overwrite_diverged=parsed_args.overwrite_diverged,
            dry_run=parsed_args.dry_run)
        return _run_or_plan(resp, parsed_args)


class TestGroup(base.FerryShowOne):
    """Test a protection group's recovery in an isolated bubble, then tear it down."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--bubble-policy", metavar="<bubble-policy>",
                            dest="bubble_policy_id",
                            help="bubble policy, by name or id, the test runs "
                                 "inside; defaults to the one the group's "
                                 "registration names, and a test with neither "
                                 "is refused")
        parser.add_argument("--dry-run", action="store_true",
                            help="show the plan, member by member, with the "
                                 "bubble it would be built under, and start "
                                 "nothing")
        parser.add_argument("--reason", metavar="<reason>",
                            help="why the test is run, recorded with the run")
        return parser

    def take_action(self, parsed_args):
        _require_dr(self.app_client)
        bubble_policy = None
        if parsed_args.bubble_policy_id:
            bubble_policy = self.app_client.bubble_policy_find(
                parsed_args.bubble_policy_id)
        resp = self.app_client.group_test(
            parsed_args.group, bubble_policy_id=bubble_policy,
            reason=parsed_args.reason, dry_run=parsed_args.dry_run)
        return _run_or_plan(resp, parsed_args)


class ResyncGroup(base.FerryShowOne):
    """Discard this region's divergence after backing it up (operator).

    The members are locked and stopped, what they wrote since the other
    region recovered the group is kept as a backup labelled with the point it
    diverged from, and this region becomes standby under the other region's
    custody.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--confirm-discard-local-writes", "--confirm",
                            action="store_true", dest="confirm",
                            help="acknowledge that the writes made here since "
                                 "the other region took over are discarded; "
                                 "required")
        parser.add_argument("--skip-divergence-point", action="store_true",
                            help="stop the members without first backing up "
                                 "what diverged here")
        parser.add_argument("--dry-run", action="store_true",
                            help="show which members diverged and the other "
                                 "region's record, and start nothing")
        parser.add_argument("--reason", metavar="<reason>",
                            help="why the group is resynced, recorded with "
                                 "the run")
        return parser

    def take_action(self, parsed_args):
        if not parsed_args.confirm:
            raise SystemExit(
                "a resync needs --confirm-discard-local-writes: it stops this "
                "region's guests and discards what they wrote after the other "
                "region took over")
        _require_dr(self.app_client)
        return _run_or_plan(self.app_client.group_resync(
            parsed_args.group, confirm=True, reason=parsed_args.reason,
            skip_divergence_point=parsed_args.skip_divergence_point,
            dry_run=parsed_args.dry_run), parsed_args)


class RetireGroup(base.FerryShowOne):
    """Remove what a superseded recovery left in this region.

    The stopped servers are deleted and their volumes unmanaged, not
    deleted: the data stays in the storage pool and leaves the cloud's
    inventory. The ports and floating IPs the recovery created are deleted.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--dry-run", action="store_true",
                            help="show what would be removed and start "
                                 "nothing")
        parser.add_argument("--reason", metavar="<reason>",
                            help="why the group is retired, recorded with "
                                 "the run")
        return parser

    def take_action(self, parsed_args):
        _require_dr(self.app_client)
        return _run_or_plan(self.app_client.group_retire(
            parsed_args.group, reason=parsed_args.reason,
            dry_run=parsed_args.dry_run), parsed_args)


class AcknowledgeGroupSplitBrain(base.FerryShowOne):
    """Keep this region's copy after a split brain; the other region must resync (system administrator).

    Both regions ran the group. Acknowledging says this region's copy
    survives: the group here is protected again at a newer custody epoch, and
    the other region refuses to run its copy until a resync there. The
    opposite choice is a resync here.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--confirm-other-region-discarded", "--confirm",
                            action="store_true", dest="confirm",
                            help="acknowledge that the other region's copy, "
                                 "and what it wrote since it recovered, is "
                                 "the one discarded; required")
        parser.add_argument("--reason", metavar="<reason>",
                            help="why this region's copy is kept, recorded "
                                 "with the acknowledgement")
        return parser

    def take_action(self, parsed_args):
        if not parsed_args.confirm:
            raise SystemExit(
                "an acknowledgement needs --confirm-other-region-discarded: "
                "the other region's copy, and what it wrote since it "
                "recovered, is the one discarded")
        _require_dr(self.app_client)
        resp = self.app_client.group_acknowledge(
            parsed_args.group, confirm=True, reason=parsed_args.reason) or {}
        group = resp.get("group") or {}
        return base.show({"id": group.get("id"), "state": group.get("state"),
                          "custody": group.get("custody"),
                          "custody_epoch": resp.get("custody_epoch"),
                          "record_run_id": resp.get("record_run_id")},
                         parsed_args)


FAILBACK_BINDING_COLUMNS = ("member", "recovered_instance", "binding",
                            "state")


class CreateGroupFailbackBindings(base.FerryLister):
    """Bind the instances another region recovered back to this group's members (operator).

    Run at the group's home. Each instance named in the other region's
    recovery record is bound to the member it came from, in the group's
    project, so this region reads the points taken of it there. Existing
    bindings are left alone.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--dry-run", action="store_true",
                            help="show the bindings and create nothing")
        parser.add_argument("--reason", metavar="<reason>",
                            help="why the bindings are created, recorded "
                                 "with them")
        return parser

    def take_action(self, parsed_args):
        _require_dr(self.app_client)
        resp = self.app_client.group_failback_bindings(
            parsed_args.group, reason=parsed_args.reason,
            dry_run=parsed_args.dry_run) or {}
        rows = []
        for b in resp.get("bindings") or []:
            binding = b.get("binding") or {}
            state = "created"
            if b.get("existing"):
                state = "already bound"
            elif resp.get("dry_run"):
                state = "would be created"
            rows.append({"member": b.get("instance_id"),
                         "recovered_instance": binding.get(
                             "source_resource_id"),
                         "binding": binding.get("id"), "state": state})
        return FAILBACK_BINDING_COLUMNS, base.rows(
            rows, FAILBACK_BINDING_COLUMNS, parsed_args)


class ShowGroupSLA(base.FerryShowOne):
    """Show a group's recovery objectives against what it actually achieves."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.group_sla(parsed_args.group),
                         parsed_args)


class ListGroupRun(base.FerryLister):
    """List a group's runs: releases, recovers, tests, resyncs and retires."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("--limit", type=int)
        return parser

    def take_action(self, parsed_args):
        runs = self.app_client.group_runs(parsed_args.group,
                                          limit=parsed_args.limit)
        return RUN_COLUMNS, base.rows(runs, RUN_COLUMNS, parsed_args)


class ShowGroupRun(base.FerryShowOne):
    """Show one run, optionally with its journal and its ledger."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("run", metavar="<run>", help="run id")
        parser.add_argument("--actions", action="store_true",
                            help="include the run's journal of steps")
        parser.add_argument("--resources", action="store_true",
                            help="include the run's ledger of what it created")
        return parser

    def take_action(self, parsed_args):
        include = [name for name, wanted in (("actions", parsed_args.actions),
                                             ("resources", parsed_args.resources))
                   if wanted]
        return base.show(_run_show_view(
            self.app_client.group_run(parsed_args.group, parsed_args.run,
                                      include=include or None),
            parsed_args), parsed_args)


class CancelGroupRun(base.FerryShowOne):
    """Cancel a run before its point of no return; what it built is torn down."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("run", metavar="<run>", help="run id")
        return parser

    def take_action(self, parsed_args):
        return base.show(_run_view(self.app_client.run_cancel(
            parsed_args.group, parsed_args.run)), parsed_args)


class AbortGroupRun(base.FerryShowOne):
    """Stop a run past its point of no return, leaving everything as it is (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("run", metavar="<run>", help="run id")
        return parser

    def take_action(self, parsed_args):
        return base.show(_run_view(self.app_client.run_abort(
            parsed_args.group, parsed_args.run)), parsed_args)


class ResumeGroupRun(base.FerryShowOne):
    """Resume a halted run where its journal left off."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("group", metavar="<group>",
                            help="group, by name or id")
        parser.add_argument("run", metavar="<run>", help="run id")
        return parser

    def take_action(self, parsed_args):
        return base.show(_run_view(self.app_client.run_resume(
            parsed_args.group, parsed_args.run)), parsed_args)


