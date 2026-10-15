import pathlib
import types

import pytest

from ferryclient.osc.v1 import group
from ferryclient.osc.v1 import recovery
from ferryclient.osc.v1 import standby
from ferryclient.v1 import client as v1_client

GROUP_ID = "11111111-1111-4111-8111-111111111111"
BUBBLE_ID = "44444444-4444-4444-8444-444444444444"
REPO_ID = "66666666-6666-4666-8666-666666666666"
BINDING_ID = "9a2b1c4d-0000-4000-8000-000000000001"
PROFILE_ID = "9c2b1c4d-0000-4000-8000-000000000001"
STANDBY_ID = "9b2b1c4d-0000-4000-8000-000000000001"
POINT_ID = "88888888-8888-4888-8888-888888888888"
POLICY_ID = "55555555-5555-4555-8555-555555555555"
SITE_ID = "a7c1e2d3-4b5f-4a6e-8d7c-9b0a1f2e3d4c"


class FakeClient:
    def __init__(self, responses):
        self.calls = []
        self.responses = responses

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.responses.get(name, {})
        return call

    def named(self, name):
        return [(a, k) for n, a, k in self.calls if n == name]

    def one(self, name):
        calls = self.named(name)
        assert len(calls) == 1, f"{name} not called once: {self.calls}"
        return calls[0]


def run(cls, argv, **responses):
    client = FakeClient(responses)
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = cls(app=app, app_args=None)
    parsed = cmd.get_parser("openstack test").parse_args(argv)
    return client, cmd.take_action(parsed)


DR_ENABLED = {"dr": True}
DR_REASON = ("Failover is not enabled on this cloud: no release, recover, "
             "test, resync or retire can start here.")
RUN_ID = "77777777-7777-4777-8777-777777777777"
JOB_ID = "33333333-3333-4333-8333-333333333333"
ACCEPTED = {"run": {"id": RUN_ID, "operation": "recover", "state": "pending"},
            "job_id": JOB_ID}


def test_release_sends_its_reason_and_override():
    client, _ = run(group.ReleaseGroup, [GROUP_ID], capabilities=DR_ENABLED)
    args, kwargs = client.one("group_release")
    assert args == (GROUP_ID,)
    assert kwargs == {"reason": None, "override_recovery_readiness": False,
                      "dry_run": False}

    client, (columns, values) = run(
        group.ReleaseGroup,
        ["--reason", "moving to cloud-b", "--override-recovery-readiness",
         GROUP_ID],
        capabilities=DR_ENABLED, group_release=ACCEPTED)
    assert client.one("group_release")[1] == {
        "reason": "moving to cloud-b", "override_recovery_readiness": True,
        "dry_run": False}
    shown = dict(zip(columns, values))
    assert shown["id"] == RUN_ID and shown["job_id"] == JOB_ID


def test_recover_needs_a_known_mode():
    for argv in ([GROUP_ID], ["--mode", "test", GROUP_ID],
                 ["--mode", "PLANNED", GROUP_ID], ["--mode", "force", GROUP_ID]):
        with pytest.raises(SystemExit):
            run(group.RecoverGroup, argv, capabilities=DR_ENABLED)


def test_planned_recover_sends_its_mode_and_wait():
    client, _ = run(group.RecoverGroup,
                    ["--mode", "planned", "--wait-for-release", "15m",
                     "--reason", "maintenance", GROUP_ID],
                    capabilities=DR_ENABLED)
    args, kwargs = client.one("group_recover")
    assert args == (GROUP_ID, "planned")
    assert kwargs == {"confirm": False, "reason": "maintenance",
                      "wait_for_release": "15m", "recovery_point": None,
                      "max_point_age": None, "overwrite_diverged": False,
                      "dry_run": False}


def test_a_failback_over_diverged_originals_says_so_and_only_when_planned():
    client, _ = run(group.RecoverGroup,
                    ["--mode", "planned", "--overwrite-diverged", GROUP_ID],
                    capabilities=DR_ENABLED)
    args, kwargs = client.one("group_recover")
    assert args == (GROUP_ID, "planned")
    assert kwargs["overwrite_diverged"] is True
    with pytest.raises(SystemExit):
        run(group.RecoverGroup,
            ["--mode", "unplanned", "--confirm", "--overwrite-diverged",
             GROUP_ID], capabilities=DR_ENABLED)


def test_unplanned_recover_sends_its_recovery_point_and_age():
    client, (columns, values) = run(
        group.RecoverGroup,
        ["--mode", "unplanned", "--confirm-primary-may-be-serving-writes",
         "--recovery-point", "newest", "--max-point-age", "2h",
         "--reason", "region down", GROUP_ID],
        capabilities=DR_ENABLED, group_recover=ACCEPTED)
    args, kwargs = client.one("group_recover")
    assert args == (GROUP_ID, "unplanned")
    assert kwargs == {"confirm": True, "reason": "region down",
                      "wait_for_release": None, "recovery_point": "newest",
                      "max_point_age": "2h", "overwrite_diverged": False,
                      "dry_run": False}
    shown = dict(zip(columns, values))
    assert shown["id"] == RUN_ID and shown["job_id"] == JOB_ID


def test_recover_refuses_an_unknown_recovery_point():
    with pytest.raises(SystemExit):
        run(group.RecoverGroup,
            ["--mode", "unplanned", "--confirm", "--recovery-point",
             "oldest", GROUP_ID], capabilities=DR_ENABLED)


PLAN = {"dry_run": True, "plan": {
    "operation": "recover", "rung": "cold", "recovery_point": "aligned",
    "members": [
        {"instance_id": "8f14e45f-ceea-467a-9a3f-1b2c3d4e5f60",
         "name": "db-01", "boot_order": 1,
         "health": {"type": "tcp", "port": 5432},
         "point_id": POINT_ID, "recovery_point_at": "2026-10-02T07:40:00Z"},
        {"instance_id": "9e25f56a-dffb-478b-8b4a-2c3d4e5f6a71",
         "boot_order": 2, "point_id": "6a2b1c4d-0000-4000-8000-000000000002",
         "recovery_point_at": "2026-10-02T07:44:00Z", "partial": True}],
    "oldest_at": "2026-10-02T07:40:00Z", "newest_at": "2026-10-02T07:44:00Z",
    "spread_seconds": 240}}


@pytest.mark.parametrize("cls, argv, call", [
    (group.RecoverGroup,
     ["--mode", "unplanned", "--confirm", "--dry-run", GROUP_ID],
     "group_recover"),
    (group.TestGroup, ["--dry-run", "--bubble-policy", BUBBLE_ID, GROUP_ID],
     "group_test"),
    (group.ReleaseGroup, ["--dry-run", GROUP_ID], "group_release"),
    (group.ResyncGroup, ["--confirm", "--dry-run", GROUP_ID], "group_resync"),
    (group.RetireGroup, ["--dry-run", GROUP_ID], "group_retire"),
], ids=["recover", "test", "release", "resync", "retire"])
def test_a_dry_run_shows_the_plan_member_by_member(cls, argv, call):
    client, (columns, values) = run(cls, argv, capabilities=DR_ENABLED,
                                    bubble_policy_find=BUBBLE_ID, **{call: PLAN})
    assert client.one(call)[1]["dry_run"] is True
    shown = dict(zip(columns, values))
    assert shown["dry_run"] is True
    assert shown["rung"] == "cold" and shown["spread_seconds"] == 240
    assert "id" not in shown and "job_id" not in shown
    lines = shown["members"].splitlines()
    assert lines == [
        f"1 db-01 (8f14e45f-ceea-467a-9a3f-1b2c3d4e5f60): point {POINT_ID} "
        "at 2026-10-02T07:40:00Z",
        "2 9e25f56a-dffb-478b-8b4a-2c3d4e5f6a71: point "
        "6a2b1c4d-0000-4000-8000-000000000002 at 2026-10-02T07:44:00Z "
        "(partial)"]


FAILBACK_PLAN = {"dry_run": True, "plan": {
    "operation": "recover", "mode": "planned", "direction": "failback",
    "rung": "cold", "recovery_point": "aligned",
    "members": [
        {"instance_id": "db", "boot_order": 1, "point_id": POINT_ID,
         "return_to_original": True, "delta": True,
         "divergence": [{"resource_id": "vol-a", "role": "root",
                         "checked": True, "diverged": False}]},
        {"instance_id": "app", "boot_order": 2, "point_id": POINT_ID,
         "return_to_original": True,
         "delta_reason": "the held point is in another repository",
         "divergence_unverifiable": "the original is not on Ceph"},
        {"instance_id": "web", "boot_order": 3, "point_id": POINT_ID,
         "rebuild": True}]}}


def test_a_failback_plan_says_where_each_member_goes():
    _, (columns, values) = run(group.RecoverGroup,
                               ["--mode", "planned", "--dry-run", GROUP_ID],
                               capabilities=DR_ENABLED,
                               group_recover=FAILBACK_PLAN)
    shown = dict(zip(columns, values))
    assert shown["direction"] == "failback"
    assert shown["members"].splitlines() == [
        f"1 db: point {POINT_ID}, returns to its original (changes only)",
        f"2 app: point {POINT_ID}, returns to its original (full copy: the "
        "held point is in another repository), not checked: the original is "
        "not on Ceph",
        f"3 web: point {POINT_ID}, rebuilt"]


def test_acknowledge_needs_its_confirmation_and_shows_the_new_epoch():
    client = FakeClient({"capabilities": DR_ENABLED})
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = group.AcknowledgeGroupSplitBrain(app=app, app_args=None)
    with pytest.raises(SystemExit):
        cmd.take_action(cmd.get_parser("openstack test").parse_args([GROUP_ID]))
    assert client.calls == []
    for flag in ("--confirm-other-region-discarded", "--confirm"):
        client, (columns, values) = run(
            group.AcknowledgeGroupSplitBrain,
            [flag, "--reason", "home survives", GROUP_ID],
            capabilities=DR_ENABLED,
            group_acknowledge={"group": {"id": GROUP_ID, "state": "protected",
                                         "custody": "active"},
                               "custody_epoch": 7, "record_run_id": RUN_ID})
        assert client.one("group_acknowledge") == (
            (GROUP_ID,), {"confirm": True, "reason": "home survives"})
        shown = dict(zip(columns, values))
        assert shown["state"] == "protected" and shown["custody_epoch"] == 7
        assert shown["record_run_id"] == RUN_ID


def test_failback_bindings_say_which_exist_and_which_would_be_created():
    resp = {"dry_run": True, "from_cloud": "cloud-b", "epoch": 5,
            "bindings": [
                {"instance_id": "db", "existing": False,
                 "binding": {"source_resource_id": "dr-db"}},
                {"instance_id": "app", "existing": True,
                 "binding": {"id": BINDING_ID,
                             "source_resource_id": "dr-app"}}]}
    client, (columns, rows) = run(group.CreateGroupFailbackBindings,
                                  ["--dry-run", GROUP_ID],
                                  capabilities=DR_ENABLED,
                                  group_failback_bindings=resp)
    assert client.one("group_failback_bindings") == (
        (GROUP_ID,), {"reason": None, "dry_run": True})
    assert columns == group.FAILBACK_BINDING_COLUMNS
    assert [dict(zip(columns, r)) for r in rows] == [
        {"member": "db", "recovered_instance": "dr-db", "binding": "",
         "state": "would be created"},
        {"member": "app", "recovered_instance": "dr-app",
         "binding": BINDING_ID, "state": "already bound"}]


RUN_WITH_MEMBERS = {
    "id": RUN_ID, "operation": "recover", "state": "running",
    "measured": {"recovery_point_spread_seconds": 180},
    "members": [
        {"source_instance_id": "8f14e45f-ceea-467a-9a3f-1b2c3d4e5f60",
         "instance_id": "0d1e2f3a-4b5c-4d6e-8f7a-8b9c0d1e2f3a",
         "name": "db-01", "boot_order": 1, "state": "healthy",
         "booted_at": "2026-10-02T08:01:00Z",
         "healthy_at": "2026-10-02T08:03:00Z"},
        {"source_instance_id": "9e25f56a-dffb-478b-8b4a-2c3d4e5f6a71",
         "boot_order": 2, "state": "failed", "error": "port 80 closed"}]}


def test_a_run_shows_each_member_on_its_own_line():
    _, (columns, values) = run(group.ShowGroupRun, [GROUP_ID, RUN_ID],
                               group_run=RUN_WITH_MEMBERS)
    shown = dict(zip(columns, values))
    assert shown["members"].splitlines() == [
        "1 db-01 (8f14e45f-ceea-467a-9a3f-1b2c3d4e5f60): healthy, instance "
        "0d1e2f3a-4b5c-4d6e-8f7a-8b9c0d1e2f3a, booted 2026-10-02T08:01:00Z, "
        "healthy 2026-10-02T08:03:00Z",
        "2 9e25f56a-dffb-478b-8b4a-2c3d4e5f6a71: failed, error port 80 closed"]
    assert '"recovery_point_spread_seconds": 180' in shown["measured"]

    _, (columns, values) = run(group.ShowGroupRun,
                               ["-f", "json", GROUP_ID, RUN_ID],
                               group_run=RUN_WITH_MEMBERS)
    assert dict(zip(columns, values))["members"] == \
        RUN_WITH_MEMBERS["members"]


def test_a_dry_run_in_json_keeps_the_members_structured():
    client, (columns, values) = run(
        group.RecoverGroup,
        ["-f", "json", "--mode", "unplanned", "--confirm", "--dry-run",
         GROUP_ID],
        capabilities=DR_ENABLED, group_recover=PLAN)
    shown = dict(zip(columns, values))
    assert shown["members"] == PLAN["plan"]["members"]


def test_unplanned_recover_needs_the_acknowledgement_by_name():
    client = FakeClient({"capabilities": DR_ENABLED})
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = group.RecoverGroup(app=app, app_args=None)
    parsed = cmd.get_parser("openstack test").parse_args(
        ["--mode", "unplanned", GROUP_ID])
    with pytest.raises(SystemExit):
        cmd.take_action(parsed)
    assert client.calls == []
    for flag in ("--confirm-primary-may-be-serving-writes", "--confirm"):
        client, _ = run(group.RecoverGroup,
                        ["--mode", "unplanned", flag, GROUP_ID],
                        capabilities=DR_ENABLED)
        args, kwargs = client.one("group_recover")
        assert args == (GROUP_ID, "unplanned")
        assert kwargs["confirm"] is True


def test_test_names_its_bubble_and_reason():
    client, _ = run(group.TestGroup,
                    ["--bubble-policy", BUBBLE_ID, "--reason",
                     "quarterly drill", GROUP_ID],
                    capabilities=DR_ENABLED, bubble_policy_find=BUBBLE_ID)
    args, kwargs = client.one("group_test")
    assert args == (GROUP_ID,)
    assert kwargs == {"bubble_policy_id": BUBBLE_ID,
                      "reason": "quarterly drill", "dry_run": False}


def test_resync_needs_its_confirmation():
    client = FakeClient({"capabilities": DR_ENABLED})
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = group.ResyncGroup(app=app, app_args=None)
    with pytest.raises(SystemExit):
        cmd.take_action(cmd.get_parser("openstack test").parse_args([GROUP_ID]))
    assert client.calls == []
    for flag in ("--confirm-discard-local-writes", "--confirm"):
        client, _ = run(group.ResyncGroup, [flag, GROUP_ID],
                        capabilities=DR_ENABLED)
        assert client.one("group_resync") == (
            (GROUP_ID,), {"confirm": True, "reason": None,
                          "skip_divergence_point": False, "dry_run": False})
    client, _ = run(group.ResyncGroup,
                    ["--confirm", "--skip-divergence-point", GROUP_ID],
                    capabilities=DR_ENABLED)
    assert client.one("group_resync")[1]["skip_divergence_point"] is True


def test_retire_sends_its_reason():
    client, _ = run(group.RetireGroup, ["--reason", "superseded", GROUP_ID],
                    capabilities=DR_ENABLED)
    assert client.one("group_retire") == ((GROUP_ID,),
                                          {"reason": "superseded",
                                           "dry_run": False})


OPERATIONS = (
    (group.ReleaseGroup, [GROUP_ID], "group_release"),
    (group.RecoverGroup, ["--mode", "planned", GROUP_ID], "group_recover"),
    (group.RecoverGroup, ["--mode", "unplanned", "--confirm", GROUP_ID],
     "group_recover"),
    (group.TestGroup, [GROUP_ID], "group_test"),
    (group.ResyncGroup, ["--confirm", GROUP_ID], "group_resync"),
    (group.RetireGroup, [GROUP_ID], "group_retire"),
    (group.AcknowledgeGroupSplitBrain, ["--confirm", GROUP_ID],
     "group_acknowledge"),
    (group.CreateGroupFailbackBindings, [GROUP_ID],
     "group_failback_bindings"),
)


@pytest.mark.parametrize("cls, argv, call", OPERATIONS,
                         ids=[f"{c.__name__}-{n}" for n, (c, _a, _m)
                              in enumerate(OPERATIONS)])
@pytest.mark.parametrize("caps, said", [
    ({"dr": False, "dr_reason": DR_REASON}, DR_REASON),
    ({"dr": False}, "failover is not available on this cloud"),
    ({}, "failover is not available on this cloud"),
])
def test_operations_stop_where_the_cloud_offers_none(cls, argv, call, caps,
                                                     said):
    client = FakeClient({"capabilities": caps})
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = cls(app=app, app_args=None)
    parsed = cmd.get_parser("openstack test").parse_args(argv)
    with pytest.raises(SystemExit) as stopped:
        cmd.take_action(parsed)
    assert str(stopped.value) == said
    assert client.named(call) == []


def test_the_failover_command_is_gone():
    assert not hasattr(group, "FailoverGroup")
    pyproject = (pathlib.Path(__file__).resolve().parents[1]
                 / "pyproject.toml").read_text()
    assert "failover" not in pyproject.lower().split("[project.entry-points")[1]


def test_runs_are_listed_shown_and_steered():
    client, (columns, rows) = run(
        group.ListGroupRun, ["--limit", "5", GROUP_ID],
        group_runs=[{"id": RUN_ID, "operation": "test", "state": "running",
                     "phase": "bubble"}])
    assert client.one("group_runs") == ((GROUP_ID,), {"limit": 5})
    assert rows[0][columns.index("operation")] == "test"
    assert rows[0][columns.index("phase")] == "bubble"

    client, _ = run(group.ShowGroupRun, [GROUP_ID, RUN_ID],
                    group_run={"id": RUN_ID})
    assert client.one("group_run") == ((GROUP_ID, RUN_ID), {"include": None})
    client, _ = run(group.ShowGroupRun,
                    ["--actions", "--resources", GROUP_ID, RUN_ID],
                    group_run={"id": RUN_ID})
    assert client.one("group_run")[1] == {"include": ["actions", "resources"]}

    for cls, call in ((group.CancelGroupRun, "run_cancel"),
                      (group.AbortGroupRun, "run_abort"),
                      (group.ResumeGroupRun, "run_resume")):
        client, (columns, values) = run(cls, [GROUP_ID, RUN_ID],
                                        **{call: ACCEPTED})
        assert client.one(call) == ((GROUP_ID, RUN_ID), {})
        assert dict(zip(columns, values))["job_id"] == JOB_ID


def test_group_sla_reads_the_groups_own_route():
    client, _ = run(group.ShowGroupSLA, [GROUP_ID], group_sla={"group_id": GROUP_ID})
    assert client.one("group_sla") == ((GROUP_ID,), {})


REMOVED_GROUP_FIELDS = ("rpo_target", "rto_target", "dr_site_id",
                        "primary_site_id", "transport", "floating_pool")


def test_group_create_names_its_policy_and_its_members_in_boot_order():
    client, _ = run(group.CreateGroup,
                    ["payments", "--policy", "gold", "--instance", "db",
                     "--instance", "app",
                     "--network-map", "prod-net=dr-net"],
                    policy_find=POLICY_ID, group_create={"id": GROUP_ID})
    assert client.one("policy_find")[0] == ("gold",)
    body = client.one("group_create")[0][0]
    assert body == {
        "name": "payments", "policy_id": POLICY_ID,
        "members": [{"instance_id": "db", "boot_order": 0},
                    {"instance_id": "app", "boot_order": 1}],
        "network_map": {"prod-net": "dr-net"}}
    for field in REMOVED_GROUP_FIELDS:
        assert field not in body
    with pytest.raises(SystemExit):
        run(group.CreateGroup,
            ["payments", "--policy", "gold", "--instance", "db",
             "--test-network-map", "prod-net=bubble-net"],
            policy_find=POLICY_ID)


def test_group_create_needs_a_policy():
    with pytest.raises(SystemExit):
        run(group.CreateGroup, ["payments", "--instance", "db"])


def test_group_create_no_longer_takes_the_policys_options():
    for argv in (["--rpo-target", "1h"], ["--rto-target", "30m"],
                 ["--floating-pool", "public"]):
        with pytest.raises(SystemExit):
            run(group.CreateGroup,
                ["payments", "--policy", "gold", "--instance", "db"] + argv,
                policy_find=POLICY_ID)


def test_group_runs_show_their_operation_and_groups_their_custody():
    assert "operation" in group.RUN_COLUMNS and "kind" not in group.RUN_COLUMNS
    _client, (columns, rows) = run(
        group.ListGroup, [],
        group_list=[{"id": GROUP_ID, "name": "payments", "state": "protected",
                     "custody": "active", "custody_epoch": 3,
                     "active_run_id": RUN_ID,
                     "members": [{"instance_id": "a"}, {"instance_id": "b"}]}])
    row = dict(zip(columns, rows[0]))
    assert row["member_count"] == 2
    assert row["custody"] == "active" and row["custody_epoch"] == 3
    assert row["active_run_id"] == RUN_ID


BINDING = {"id": BINDING_ID, "repository_id": REPO_ID, "origin_cloud": "cloud-a",
           "source_resource_id": "vol-1", "target_project_id": "proj-b",
           "standby_pool": "ferry-standby", "points_adopted": 4}


def test_binding_create_resolves_the_repository_and_sends_the_assertion():
    client, (columns, values) = run(
        recovery.CreateRecoveryBinding,
        ["--repository", "cold", "--origin-cloud", "cloud-a",
         "--source-project", "proj-a", "--resource", "vol-1",
         "--target-project", "proj-b", "--standby-pool", "ferry-standby",
         "--standby-prefix", "dr-"],
        repository_find=REPO_ID, binding_create=BINDING)
    assert client.one("repository_find")[0] == ("cold",)
    assert client.one("binding_create")[0][0] == {
        "repository_id": REPO_ID, "origin_cloud": "cloud-a",
        "source_project": "proj-a", "source_resource_id": "vol-1",
        "target_project_id": "proj-b", "standby_pool": "ferry-standby",
        "standby_prefix": "dr-"}
    assert dict(zip(columns, values))["rung"] == "warm"
    assert not [c for c in client.calls if c[0] == "site_find"]


def test_binding_create_resolves_the_standby_site_by_name():
    client, _ = run(
        recovery.CreateRecoveryBinding,
        ["--repository", REPO_ID, "--origin-cloud", "cloud-a",
         "--resource", "vol-1", "--target-project", "proj-b",
         "--standby-pool", "ferry-standby", "--standby-site", "cloud-b"],
        repository_find=REPO_ID, site_find=SITE_ID, binding_create=BINDING)
    assert client.one("site_find")[0] == ("cloud-b",)
    assert client.one("binding_create")[0][0]["standby_site_id"] == SITE_ID


def test_binding_create_refuses_what_the_api_would():
    with pytest.raises(SystemExit):
        run(recovery.CreateRecoveryBinding,
            ["--repository", "cold", "--origin-cloud", "cloud-a",
             "--resource", "vol-1"])
    with pytest.raises(SystemExit):
        run(recovery.CreateRecoveryBinding,
            ["--repository", "cold", "--origin-cloud", "cloud-a",
             "--resource", "vol-1", "--target-project", "proj-b",
             "--standby-prefix", "dr-"], repository_find=REPO_ID)


def test_binding_list_filters_and_shows_the_rung():
    client, (columns, rows) = run(
        recovery.ListRecoveryBinding,
        ["--repository", "cold", "--origin-cloud", "cloud-a",
         "--target-project", "proj-b"],
        repository_find=REPO_ID,
        binding_list=[BINDING, {"id": "b2", "origin_cloud": "cloud-a"}])
    assert client.one("binding_list")[1] == {
        "repository_id": REPO_ID, "origin_cloud": "cloud-a",
        "target_project_id": "proj-b"}
    assert [r[columns.index("rung")] for r in rows] == ["warm", "cold"]

    client, _ = run(recovery.ListRecoveryBinding, [], binding_list=[])
    assert client.one("binding_list")[1] == {
        "repository_id": None, "origin_cloud": None,
        "target_project_id": None}
    assert not client.named("repository_find")


def test_binding_show_and_delete():
    client, (columns, values) = run(recovery.ShowRecoveryBinding,
                                    [BINDING_ID], binding_show=BINDING)
    assert client.one("binding_show")[0] == (BINDING_ID,)
    assert dict(zip(columns, values))["points_adopted"] == 4

    client, _ = run(recovery.DeleteRecoveryBinding, [BINDING_ID, "b2"])
    assert [a for a, _k in client.named("binding_delete")] == \
        [(BINDING_ID,), ("b2",)]


def test_binding_dry_run_sends_the_question(tmp_path):
    client, _ = run(recovery.DryRunRecoveryBinding,
                    ["--point", POINT_ID, "--profile", "from-cloud-a",
                     "--confirm-unresolved", "network:net-1",
                     "--confirm-unresolved", "key_pair", BINDING_ID],
                    binding_dry_run={"committable": True})
    args, _ = client.one("binding_dry_run")
    assert args == (BINDING_ID, {"point_id": POINT_ID, "profile": "from-cloud-a",
                                 "confirm_unresolved": ["network:net-1",
                                                        "key_pair"]})

    client, _ = run(recovery.DryRunRecoveryBinding, [BINDING_ID])
    assert client.one("binding_dry_run")[0] == (BINDING_ID, None)

    profile = tmp_path / "profile.yaml"
    profile.write_text("network_map:\n  prod-net: dr-net\n")
    client, _ = run(recovery.DryRunRecoveryBinding,
                    ["--profile-file", str(profile), BINDING_ID])
    assert client.one("binding_dry_run")[0][1] == {
        "mapping_profile": {"network_map": {"prod-net": "dr-net"}}}

    with pytest.raises(SystemExit):
        run(recovery.DryRunRecoveryBinding,
            ["--profile", "x", "--profile-file", str(profile), BINDING_ID])


def test_recovery_profile_create_sends_the_maps_and_the_switches():
    client, _ = run(recovery.CreateRecoveryProfile,
                    ["from-cloud-a", "--origin-cloud", "cloud-a",
                     "--flavor-map", "m1.large=dr.large",
                     "--network-map", "prod-net=dr-net",
                     "--network-map", "mgmt=dr-mgmt",
                     "--volume-type-map", "ssd=dr-ssd",
                     "--floating-pool", "public",
                     "--flavor-fallback-by-spec", "--import-keypair"],
                    recovery_profile_create={"id": PROFILE_ID})
    assert client.one("recovery_profile_create")[0][0] == {
        "name": "from-cloud-a", "origin_cloud": "cloud-a",
        "flavor_map": {"m1.large": "dr.large"},
        "network_map": {"prod-net": "dr-net", "mgmt": "dr-mgmt"},
        "volume_type_map": {"ssd": "dr-ssd"},
        "floating_pool": "public",
        "flavor_fallback_by_spec": True, "import_keypair": True}


def test_recovery_profile_create_needs_only_a_name():
    client, _ = run(recovery.CreateRecoveryProfile, ["house"])
    assert client.one("recovery_profile_create")[0][0] == {"name": "house"}
    with pytest.raises(SystemExit):
        run(recovery.CreateRecoveryProfile, ["house", "--network-map", "x"])


def test_recovery_profile_list_and_delete():
    client, (columns, rows) = run(
        recovery.ListRecoveryProfile, [],
        recovery_profile_list=[{"id": PROFILE_ID, "name": "from-cloud-a",
                                "origin_cloud": "cloud-a"}])
    assert columns == recovery.PROFILE_COLUMNS
    assert rows[0][columns.index("name")] == "from-cloud-a"

    client, _ = run(recovery.DeleteRecoveryProfile, ["from-cloud-a", PROFILE_ID])
    assert [a for a, _k in client.named("recovery_profile_delete")] == \
        [("from-cloud-a",), (PROFILE_ID,)]


def test_standby_create_sends_the_registration():
    client, _ = run(standby.CreateStandby,
                    ["--project", "proj-b", "--domain", "acme",
                     "--resource", "vol-1", "--pool", "ferry-standby",
                     "--image-prefix", "dr-", "--site", "cloud-b",
                     "--group", GROUP_ID],
                    site_find=SITE_ID, group_find=GROUP_ID,
                    standby_create={"id": STANDBY_ID})
    assert client.one("site_find")[0] == ("cloud-b",)
    assert client.one("group_find")[0] == (GROUP_ID,)
    assert client.one("standby_create")[0][0] == {
        "project_id": "proj-b", "domain_id": "acme",
        "resource_id": "vol-1", "target_pool": "ferry-standby",
        "target_prefix": "dr-", "site_id": SITE_ID, "group_id": GROUP_ID}
    with pytest.raises(SystemExit):
        run(standby.CreateStandby, ["--resource", "vol-1"])
    with pytest.raises(SystemExit):
        run(standby.CreateStandby,
            ["--resource", "vol-1", "--pool", "ferry-standby"])


def test_standby_list_names_a_project():
    client, _ = run(standby.ListStandby, ["--project", "proj-b"],
                    standby_list=[])
    assert client.one("standby_list")[1] == {"project_id": "proj-b"}


def test_standby_list_show_delete_and_promote():
    _client, (columns, rows) = run(
        standby.ListStandby, [],
        standby_list=[{"id": STANDBY_ID, "resource_id": "vol-1",
                       "state": "degraded",
                       "applied_snap": "ferry-applied-p1"}])
    assert rows[0][columns.index("state")] == "degraded"
    assert rows[0][columns.index("applied_snap")] == "ferry-applied-p1"

    client, _ = run(standby.ShowStandby, [STANDBY_ID],
                    standby_show={"id": STANDBY_ID})
    assert client.one("standby_show")[0] == (STANDBY_ID,)

    client, _ = run(standby.DeleteStandby, [STANDBY_ID, "s2"])
    assert [a for a, _k in client.named("standby_delete")] == \
        [(STANDBY_ID,), ("s2",)]

    client, _ = run(standby.PromoteStandby,
                    ["--volume-type", "ssd", "--name-prefix", "recovered-",
                     STANDBY_ID],
                    standby_promote={"standby_id": STANDBY_ID, "volumes": []})
    assert client.one("standby_promote")[0] == (
        STANDBY_ID, {"volume_type": "ssd", "name_prefix": "recovered-"})

    client, _ = run(standby.PromoteStandby, [STANDBY_ID])
    assert client.one("standby_promote")[0] == (STANDBY_ID, None)


def test_the_new_commands_are_registered():
    pyproject = (pathlib.Path(__file__).resolve().parents[1]
                 / "pyproject.toml").read_text()
    for name, target in (
        ("backup_recovery_binding_list", "recovery:ListRecoveryBinding"),
        ("backup_recovery_binding_show", "recovery:ShowRecoveryBinding"),
        ("backup_recovery_binding_create", "recovery:CreateRecoveryBinding"),
        ("backup_recovery_binding_delete", "recovery:DeleteRecoveryBinding"),
        ("backup_recovery_binding_dry_run", "recovery:DryRunRecoveryBinding"),
        ("backup_recovery_profile_list", "recovery:ListRecoveryProfile"),
        ("backup_recovery_profile_create", "recovery:CreateRecoveryProfile"),
        ("backup_recovery_profile_delete", "recovery:DeleteRecoveryProfile"),
        ("backup_standby_list", "standby:ListStandby"),
        ("backup_standby_show", "standby:ShowStandby"),
        ("backup_standby_create", "standby:CreateStandby"),
        ("backup_standby_delete", "standby:DeleteStandby"),
        ("backup_standby_promote", "standby:PromoteStandby"),
        ("backup_group_release", "group:ReleaseGroup"),
        ("backup_group_recover", "group:RecoverGroup"),
        ("backup_group_test", "group:TestGroup"),
        ("backup_group_resync", "group:ResyncGroup"),
        ("backup_group_retire", "group:RetireGroup"),
        ("backup_group_split_brain_acknowledge",
         "group:AcknowledgeGroupSplitBrain"),
        ("backup_group_failback_bindings_create",
         "group:CreateGroupFailbackBindings"),
        ("backup_group_sla_show", "group:ShowGroupSLA"),
        ("backup_group_run_list", "group:ListGroupRun"),
        ("backup_group_run_show", "group:ShowGroupRun"),
        ("backup_group_run_cancel", "group:CancelGroupRun"),
        ("backup_group_run_abort", "group:AbortGroupRun"),
        ("backup_group_run_resume", "group:ResumeGroupRun"),
    ):
        assert f'{name} = "ferryclient.osc.v1.{target}"' in pyproject


class RecordingClient(v1_client.Client):
    def __init__(self):
        self.sent = []
        self._timeout = None
        self._base = ""

    def request(self, method, path, body=None, params=None):
        self.sent.append((method, path, body, params))
        if method == "GET" and path == "/v1/recovery-bindings":
            return {"items": [{"id": BINDING_ID}], "limit": 50, "total": 1}
        if method == "GET" and path == "/v1/recovery-profiles":
            return {"items": [{"id": PROFILE_ID, "name": "from-cloud-a"}],
                    "limit": 50, "total": 1}
        if method == "GET" and path == "/v1/standbys":
            return {"items": [{"id": STANDBY_ID}], "limit": 50, "total": 1}
        return None

    def last(self):
        return self.sent[-1]


def test_a_registration_is_deleted_keeping_its_resources_only_when_asked():
    client = RecordingClient()
    base = f"/v1/protection-groups/{GROUP_ID}"
    client.group_delete(GROUP_ID)
    assert client.last() == ("DELETE", base, None, None)
    client.group_delete(GROUP_ID, keep_resources=True)
    assert client.last() == ("DELETE", base, None, {"keep_resources": "true"})


def test_the_dr_routes_live_under_the_group():
    client = RecordingClient()
    base = f"/v1/protection-groups/{GROUP_ID}"
    run_base = f"{base}/runs/{RUN_ID}"

    client.group_release(GROUP_ID)
    assert client.last() == ("POST", f"{base}/release", None, None)
    client.group_release(GROUP_ID, reason="moving",
                         override_recovery_readiness=True)
    assert client.last() == ("POST", f"{base}/release",
                             {"reason": "moving",
                              "override_recovery_readiness": True}, None)

    client.group_recover(GROUP_ID, "planned", wait_for_release="15m")
    assert client.last() == ("POST", f"{base}/recover",
                             {"mode": "planned", "wait_for_release": "15m"},
                             None)
    client.group_recover(GROUP_ID, "planned", overwrite_diverged=True)
    assert client.last() == ("POST", f"{base}/recover",
                             {"mode": "planned", "overwrite_diverged": True},
                             None)
    client.group_recover(GROUP_ID, "unplanned", confirm=True, reason="down")
    assert client.last() == ("POST", f"{base}/recover",
                             {"mode": "unplanned",
                              "confirm_primary_may_be_serving_writes": True,
                              "reason": "down"}, None)

    client.group_recover(GROUP_ID, "unplanned", confirm=True,
                         recovery_point="newest", max_point_age="2h",
                         dry_run=True)
    assert client.last() == ("POST", f"{base}/recover",
                             {"mode": "unplanned",
                              "confirm_primary_may_be_serving_writes": True,
                              "recovery_point": "newest",
                              "max_point_age": "2h"},
                             {"dry_run": "true"})

    client.group_test(GROUP_ID, bubble_policy_id=BUBBLE_ID)
    assert client.last() == ("POST", f"{base}/test",
                             {"bubble_policy_id": BUBBLE_ID}, None)
    client.group_test(GROUP_ID, reason="drill", dry_run=True)
    assert client.last() == ("POST", f"{base}/test", {"reason": "drill"},
                             {"dry_run": "true"})
    client.group_resync(GROUP_ID, confirm=True)
    assert client.last() == ("POST", f"{base}/resync",
                             {"confirm_discard_local_writes": True}, None)
    client.group_resync(GROUP_ID, confirm=True, skip_divergence_point=True,
                        dry_run=True)
    assert client.last() == ("POST", f"{base}/resync",
                             {"confirm_discard_local_writes": True,
                              "skip_divergence_point": True},
                             {"dry_run": "true"})
    client.group_retire(GROUP_ID, reason="superseded")
    assert client.last() == ("POST", f"{base}/retire",
                             {"reason": "superseded"}, None)
    client.group_retire(GROUP_ID, dry_run=True)
    assert client.last() == ("POST", f"{base}/retire", None,
                             {"dry_run": "true"})
    client.group_release(GROUP_ID, dry_run=True)
    assert client.last() == ("POST", f"{base}/release", None,
                             {"dry_run": "true"})
    client.group_acknowledge(GROUP_ID, confirm=True, reason="home survives")
    assert client.last() == ("POST", f"{base}/split-brain/acknowledge",
                             {"confirm_other_region_discarded": True,
                              "reason": "home survives"}, None)
    client.group_failback_bindings(GROUP_ID, dry_run=True)
    assert client.last() == ("POST", f"{base}/failback-bindings", None,
                             {"dry_run": "true"})

    client.group_sla(GROUP_ID)
    assert client.last() == ("GET", f"{base}/sla", None, None)
    client.group_runs(GROUP_ID, limit=5)
    assert client.last() == ("GET", f"{base}/runs", None, {"limit": 5})
    client.group_run(GROUP_ID, RUN_ID)
    assert client.last() == ("GET", run_base, None, None)
    client.group_run(GROUP_ID, RUN_ID, include=["actions", "resources"])
    assert client.last() == ("GET", run_base, None,
                             {"include": "actions,resources"})

    client.run_cancel(GROUP_ID, RUN_ID)
    assert client.last() == ("POST", f"{run_base}/cancel", None, None)
    client.run_abort(GROUP_ID, RUN_ID)
    assert client.last() == ("POST", f"{run_base}/abort", None, None)
    client.run_resume(GROUP_ID, RUN_ID)
    assert client.last() == ("POST", f"{run_base}/resume", None, None)

    source = pathlib.Path(v1_client.__file__).read_text()
    assert "dr-plans" not in source and "dr_failover" not in source


def test_the_recovery_lists_unwrap_the_page_envelope():
    client = RecordingClient()
    assert client.binding_list(origin_cloud="cloud-a", repository_id=None) == \
        [{"id": BINDING_ID}]
    assert client.last() == ("GET", "/v1/recovery-bindings", None,
                             {"origin_cloud": "cloud-a"})
    assert client.recovery_profile_list()[0]["name"] == "from-cloud-a"
    assert client.standby_list(project_id="proj-b") == [{"id": STANDBY_ID}]
    assert client.last() == ("GET", "/v1/standbys", None,
                             {"project_id": "proj-b"})


def test_a_recovery_profile_is_deleted_by_name():
    client = RecordingClient()
    client.recovery_profile_delete("from-cloud-a")
    assert client.last()[:2] == ("DELETE",
                                 f"/v1/recovery-profiles/{PROFILE_ID}")


def test_the_recovery_routes():
    client = RecordingClient()
    client.binding_create({"origin_cloud": "cloud-a"})
    assert client.last()[:3] == ("POST", "/v1/recovery-bindings",
                                 {"origin_cloud": "cloud-a"})
    client.binding_show(BINDING_ID)
    assert client.last()[:2] == ("GET", f"/v1/recovery-bindings/{BINDING_ID}")
    client.binding_delete(BINDING_ID)
    assert client.last()[:2] == ("DELETE",
                                 f"/v1/recovery-bindings/{BINDING_ID}")
    client.binding_dry_run(BINDING_ID)
    assert client.last() == (
        "POST", f"/v1/recovery-bindings/{BINDING_ID}/dry-run", None, None)
    client.recovery_profile_create({"name": "house"})
    assert client.last()[:2] == ("POST", "/v1/recovery-profiles")
    client.standby_create({"resource_id": "vol-1"})
    assert client.last()[:2] == ("POST", "/v1/standbys")
    client.standby_show(STANDBY_ID)
    assert client.last()[:2] == ("GET", f"/v1/standbys/{STANDBY_ID}")
    client.standby_delete(STANDBY_ID)
    assert client.last()[:2] == ("DELETE", f"/v1/standbys/{STANDBY_ID}")
    client.standby_promote(STANDBY_ID, {"volume_type": "ssd"})
    assert client.last() == ("POST", f"/v1/standbys/{STANDBY_ID}/promote",
                             {"volume_type": "ssd"}, None)
