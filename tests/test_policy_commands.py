# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
import json
import pathlib
import types

import pytest

from ferryclient import exceptions
from ferryclient.osc.v1 import hold
from ferryclient.osc.v1 import misc
from ferryclient.osc.v1 import plan
from ferryclient.osc.v1 import point
from ferryclient.osc.v1 import policy
from ferryclient.osc.v1 import repository
from ferryclient.osc.v1 import restore
from ferryclient.osc.v1 import vault
from ferryclient.v1 import client as v1_client

POLICY_ID = "11111111-1111-4111-8111-111111111111"
PLAN_ID = "22222222-2222-4222-8222-222222222222"
OTHER_POLICY_ID = "55555555-5555-4555-8555-555555555555"
REPO_ID = "66666666-6666-4666-8666-666666666666"
VAULT_ID = "77777777-7777-4777-8777-777777777777"
POINT_ID = "88888888-8888-4888-8888-888888888888"
SITE_ID = "99999999-9999-4999-8999-999999999999"
LOCAL_SITE_ID = "aaaaaaaa-0000-4000-8000-000000000001"

RETIRED_PLAN_FIELDS = ("schedule", "jitter", "window_start", "window_end",
                       "intent", "placement_pin")

RETIRED_PLAN_FLAGS = ("--schedule", "--jitter", "--window-start",
                      "--window-end", "--daily", "--weekly",
                      "--monthly", "--yearly", "--immutable",
                      "--instant-restore-within", "--rpo-target",
                      "--placement-pin")


class FakeClient:
    def __init__(self):
        self.calls = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def named(self, name):
        return [(a, k) for n, a, k in self.calls if n == name]

    def one(self, name):
        calls = self.named(name)
        assert len(calls) == 1, f"{name} not called once: {self.calls}"
        return calls[0]

    def policy_find(self, ref):
        self._record("policy_find", ref)
        return POLICY_ID

    def plan_find(self, ref):
        self._record("plan_find", ref)
        return PLAN_ID

    def vault_find(self, ref):
        self._record("vault_find", ref)
        return VAULT_ID

    def vault_list(self, **filters):
        self._record("vault_list", **filters)
        return [{"id": VAULT_ID, "name": "Immutable", "immutable": True,
                 "sentence": "A backup taken here by hand is kept from a day "
                             "to 90 days."}]

    def vault_show(self, ref):
        self._record("vault_show", ref)
        return {"id": VAULT_ID, "name": "Immutable"}

    def repository_find(self, ref):
        self._record("repository_find", ref)
        return "repo-" + ref

    def site_find(self, ref):
        self._record("site_find", ref)
        return "site-" + ref

    def policy_list(self, **filters):
        self._record("policy_list", **filters)
        return [{"id": POLICY_ID, "name": "gold", "state": "active",
                 "mandatory": True, "sentence": "every hour; kept two days"}]

    def policy_show(self, ref, **params):
        self._record("policy_show", ref, **params)
        return {"id": POLICY_ID, "name": "gold"}

    def policy_create(self, body):
        self._record("policy_create", body)
        return {"id": POLICY_ID, "name": body.get("name")}

    def policy_update(self, ref, body, apply_to_existing=False):
        self._record("policy_update", ref, body,
                     apply_to_existing=apply_to_existing)

    def policy_assign(self, ref, body, remove=False):
        self._record("policy_assign", ref, body, remove=remove)
        return {"id": POLICY_ID, "name": "gold"}

    def policy_deprecate(self, ref):
        self._record("policy_deprecate", ref)
        return {"id": POLICY_ID, "state": "deprecated"}

    def policy_retire(self, ref, successor=None):
        self._record("policy_retire", ref, successor=successor)
        return {"id": POLICY_ID, "state": "retired"}

    def plan_list(self, **filters):
        self._record("plan_list", **filters)
        return [{"id": PLAN_ID, "name": "nightly", "enabled": True,
                 "resource_kind": "volume",
                 "next_run_at": "2026-09-13T02:00:00Z",
                 "unsatisfied": ["backup_repository_gone"],
                 "policy": {"id": POLICY_ID, "name": "gold",
                            "sentence": "every hour"}}]

    def plan_create(self, body):
        self._record("plan_create", body)
        return {"id": PLAN_ID}

    def plan_update(self, ref, body):
        self._record("plan_update", ref, body)

    def plan_restore(self, ref):
        self._record("plan_restore", ref)
        return {"id": PLAN_ID, "deleted_at": None}

    def plan_missed_ticks(self, ref, **filters):
        self._record("plan_missed_ticks", ref, **filters)
        return [{"scheduled_for": "2026-09-12T02:00:00Z",
                 "deadline": "2026-09-12T04:00:00Z",
                 "reason": "start_within_elapsed",
                 "recorded_at": "2026-09-12T04:00:01Z"}]

    def point_create(self, body):
        self._record("point_create", body)
        return {"point_id": "point", "job_id": "job"}

    def point_verify(self, point_id):
        self._record("point_verify", point_id)
        return {"id": "job", "kind": "verify", "state": "pending",
                "point_id": point_id}

    def restore_create(self, body):
        self._record("restore_create", body)
        return {"id": "restore", "job_id": "job"}

    def attachment_create(self, body):
        self._record("attachment_create", body)
        return {"id": "attachment", "job_id": "job"}

    def repository_register(self, body):
        self._record("repository_register", body)
        return {"id": "repo", "name": body.get("name")}

    def repository_update(self, ref, body):
        self._record("repository_update", ref, body)

    def legal_hold_create(self, body):
        self._record("legal_hold_create", body)
        return {"id": "hold", "active": True}

    def legal_hold_list(self, **filters):
        self._record("legal_hold_list", **filters)
        return [{"id": "hold", "scope": "plan", "target_id": PLAN_ID,
                 "reason": "litigation", "active": True}]

    def legal_hold_delete(self, hold_id):
        self._record("legal_hold_delete", hold_id)

    def coverage(self, **params):
        self._record("coverage", **params)
        return {"generated_at": "2026-09-12T00:00:00Z", "projects": []}

    def retention_simulate(self, body):
        self._record("retention_simulate", body)
        return {"policy_id": POLICY_ID, "kept": 3, "expired": 1}


def run(cls, argv):
    client = FakeClient()
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = cls(app=app, app_args=None)
    parsed = cmd.get_parser("openstack test").parse_args(argv)
    return client, cmd.take_action(parsed)


FULL_POLICY = [
    "gold",
    "--description", "hourly, a month of dailies",
    "--visibility", "assigned",
    "--mandatory",
    "--every", "1h",
    "--at", "02:00",
    "--window-start", "22:00",
    "--window-end", "06:00",
    "--jitter", "30m",
    "--start-within", "2h",
    "--keep-all", "48h",
    "--keep-daily", "30",
    "--keep-weekly", "12",
    "--keep-monthly", "12",
    "--keep-yearly", "7",
    "--anchor", "week=sunday",
    "--anchor", "month=first",
    "--anchor", "year=january",
    "--backup-repository", "s3-frankfurt",
    "--instant-tier", "ceph-tier-fra",
    "--instant-within", "168h",
    "--copy-repository", "s3-bucharest",
    "--copy-keep", "daily=7",
    "--copy-keep", "monthly=12",
    "--recovery-site", "cloud-b",
    "--recovery-rung", "warm",
    "--transport", "repository",
    "--rpo-target", "1h",
    "--rto-target", "30m",
    "--test-every", "720h",
    "--verify-every", "720h",
]


def test_policy_create_sends_the_whole_spec():
    client, _ = run(policy.CreatePolicy, FULL_POLICY)
    (args, _kwargs) = client.one("policy_create")
    assert args[0] == {
        "name": "gold",
        "description": "hourly, a month of dailies",
        "visibility": "assigned",
        "mandatory": True,
        "spec": {
            "schedule": {"every": "1h", "at": "02:00",
                         "window_start": "22:00", "window_end": "06:00",
                         "jitter": "30m", "start_within": "2h"},
            "keep": {"all": "48h", "daily": 30, "weekly": 12, "monthly": 12,
                     "yearly": 7,
                     "anchors": {"week": "sunday", "month": "first",
                                 "year": "january"}},
            "tiers": {
                "backup": {"repository_id": "repo-s3-frankfurt"},
                "instant": {"repository_id": "repo-ceph-tier-fra",
                            "within": "168h"},
                "copy": {"repository_id": "repo-s3-bucharest",
                         "keep": {"daily": 7, "monthly": 12}},
            },
            "recovery": {
                "site_id": "site-cloud-b",
                "rung": "warm", "transport": "repository",
                "rpo_target": "1h", "rto_target": "30m",
                "test": {"every": "720h"},
            },
            "verify": {"every": "720h"},
        },
    }


def test_policy_transport_reaches_the_recovery_section():
    client, _ = run(policy.CreatePolicy,
                    ["platinum", "--every", "1h", "--backup-repository",
                     "cold", "--recovery-rung", "hot",
                     "--transport", "rbd-mirror"])
    recovery = client.one("policy_create")[0][0]["spec"]["recovery"]
    assert recovery == {"rung": "hot", "transport": "rbd-mirror"}

    client, _ = run(policy.SetPolicy, ["gold", "--transport", "repository"])
    assert client.one("policy_update")[0][1] == {
        "spec": {"recovery": {"transport": "repository"}}}

    client, _ = run(policy.CreatePolicy,
                    ["bronze", "--every", "24h", "--backup-repository",
                     "cold", "--recovery-rung", "cold"])
    assert "transport" not in \
        client.one("policy_create")[0][0]["spec"]["recovery"]

    with pytest.raises(SystemExit):
        run(policy.CreatePolicy,
            ["gold", "--every", "1h", "--backup-repository", "cold",
             "--transport", "snapshot"])


def test_policy_test_failover_has_only_a_cadence():
    client, _ = run(policy.CreatePolicy,
                    ["gold", "--every", "1h", "--backup-repository", "cold",
                     "--test-every", "720h"])
    recovery = client.one("policy_create")[0][0]["spec"]["recovery"]
    assert recovery == {"test": {"every": "720h"}}
    for cls, argv in ((policy.CreatePolicy,
                       ["gold", "--every", "1h", "--backup-repository",
                        "cold"]),
                      (policy.SetPolicy, ["gold"])):
        with pytest.raises(SystemExit):
            run(cls, argv + ["--test-bubble-policy",
                             "44444444-4444-4444-8444-444444444444"])


def test_policy_create_durations_stay_strings_and_counts_stay_integers():
    client, _ = run(policy.CreatePolicy,
                    ["bronze", "--every", "24h", "--keep-all", "48h",
                     "--keep-daily", "7", "--backup-repository", "cold",
                     "--copy-repository", "far", "--copy-keep", "all=72h",
                     "--copy-keep", "daily=7", "--anchor", "week=0"])
    spec = client.one("policy_create")[0][0]["spec"]
    assert spec["schedule"]["every"] == "24h"
    assert spec["keep"]["all"] == "48h"
    assert spec["keep"]["daily"] == 7
    assert spec["keep"]["anchors"] == {"week": "0"}
    assert spec["tiers"]["copy"]["keep"] == {"all": "72h", "daily": 7}


def test_policy_create_needs_a_cadence_and_a_repository():
    with pytest.raises(SystemExit):
        run(policy.CreatePolicy, ["gold"])
    with pytest.raises(SystemExit):
        run(policy.CreatePolicy, ["gold", "--every", "1h"])
    with pytest.raises(SystemExit):
        run(policy.CreatePolicy,
            ["gold", "--every", "1h", "--cron", "0 2 * * *",
             "--backup-repository", "cold"])


def test_policy_set_sends_the_edit_and_the_apply_flag():
    client, _ = run(policy.SetPolicy,
                    ["gold", "--keep-all", "72h", "--keep-daily", "30",
                     "--apply-to-existing"])
    args, kwargs = client.one("policy_update")
    assert args[0] == "gold"
    assert args[1] == {"spec": {"keep": {"all": "72h", "daily": 30}}}
    assert kwargs["apply_to_existing"] is True


def test_policy_set_without_apply_leaves_existing_points_alone():
    client, _ = run(policy.SetPolicy, ["gold", "--not-mandatory"])
    args, kwargs = client.one("policy_update")
    assert args[1] == {"mandatory": False}
    assert kwargs["apply_to_existing"] is False


def test_policy_set_refuses_an_empty_edit():
    with pytest.raises(SystemExit):
        run(policy.SetPolicy, ["gold"])


def test_policy_assign_is_one_command_for_one_route():
    client, _ = run(policy.AssignPolicy,
                    ["gold", "--project", "b2f4", "--domain", "acme"])
    args, kwargs = client.one("policy_assign")
    assert args[1] == {"projects": ["b2f4"], "domains": ["acme"]}
    assert kwargs["remove"] is False

    client, _ = run(policy.AssignPolicy,
                    ["gold", "--project", "b2f4", "--remove"])
    assert client.one("policy_assign")[1]["remove"] is True


def test_policy_assign_needs_a_target():
    with pytest.raises(SystemExit):
        run(policy.AssignPolicy, ["gold"])


def test_policy_retire_resolves_a_successor_by_name():
    client, _ = run(policy.RetirePolicy, ["gold", "--successor", "platinum"])
    assert client.one("policy_retire")[1]["successor"] == "platinum"
    client, _ = run(policy.DeprecatePolicy, ["gold"])
    assert client.one("policy_deprecate")[0] == ("gold",)


def test_policy_list_withholds_what_a_tenant_may_not_see():
    for withheld in ("tiers", "spec", "assigned_to", "recovery",
                     "repository_id", "plan_count"):
        assert withheld not in policy.COLUMNS
    client, (columns, rows) = run(policy.ListPolicy,
                                  ["--state", "active", "--unsatisfied"])
    assert columns == policy.COLUMNS
    assert rows[0][columns.index("sentence")] == "every hour; kept two days"
    assert client.one("policy_list")[1]["unsatisfied"] == "true"


def test_policy_list_can_be_read_as_a_tenant_would_see_it():
    client, _ = run(policy.ListPolicy, ["--scope", "tenant"])
    assert client.one("policy_list")[1]["scope"] == "tenant"


def test_plan_create_names_a_policy_and_nothing_the_policy_owns():
    client, _ = run(plan.CreatePlan,
                    ["nightly", "--resource-kind", "volume",
                     "--resource", "vol-1", "--policy", "gold"])
    body = client.one("plan_create")[0][0]
    assert body == {"name": "nightly", "resource_kind": "volume",
                    "resource_ids": ["vol-1"], "policy_id": POLICY_ID}
    for field in RETIRED_PLAN_FIELDS:
        assert field not in body


def test_a_plan_states_its_own_consistency():
    client, _ = run(plan.CreatePlan,
                    ["nightly", "--resource-kind", "volume",
                     "--resource", "vol-1", "--policy", "gold",
                     "--consistency", "crash"])
    assert client.one("plan_create")[0][0]["consistency"] == "crash"
    client, _ = run(plan.SetPlan, ["nightly", "--consistency", "filesystem"])
    assert client.one("plan_update")[0][1] == {"consistency": "filesystem"}


def test_a_policy_takes_no_consistency():
    with pytest.raises(SystemExit):
        run(policy.CreatePolicy, FULL_POLICY + ["--consistency", "filesystem"])


def test_plan_create_refuses_every_retired_flag():
    for flag in RETIRED_PLAN_FLAGS:
        with pytest.raises(SystemExit):
            run(plan.CreatePlan,
                ["nightly", "--resource-kind", "volume", "--resource", "v",
                 "--policy", "gold", flag, "x"])


def test_plan_create_requires_a_policy():
    with pytest.raises(SystemExit):
        run(plan.CreatePlan,
            ["nightly", "--resource-kind", "volume", "--resource", "v"])


def test_plan_create_sends_labels_exclusions_and_a_coverage_acceptance():
    client, _ = run(plan.CreatePlan,
                    ["nightly", "--resource-kind", "instance",
                     "--resource", "inst-1", "--policy", "gold",
                     "--encryption", "barbican",
                     "--exclude-disk", "vol-9:scsi0",
                     "--label", "app=payments", "--label", "tier=1",
                     "--accept-partial-coverage", "sha256:abc"])
    body = client.one("plan_create")[0][0]
    assert body["labels"] == {"app": "payments", "tier": "1"}
    assert body["excluded_disks"] == [{"resource_id": "vol-9",
                                       "locator": "scsi0"}]
    assert body["partial_coverage"] == {"accept": True, "digest": "sha256:abc"}
    assert body["encryption"] == "barbican"


def test_plan_set_moves_the_plan_to_another_policy():
    client, _ = run(plan.SetPlan, ["nightly", "--policy", "platinum"])
    args = client.one("plan_update")[0]
    assert args[1] == {"policy_id": POLICY_ID}
    assert client.one("policy_find")[0] == ("platinum",)


def test_plan_set_refuses_every_retired_flag():
    for flag in RETIRED_PLAN_FLAGS:
        with pytest.raises(SystemExit):
            run(plan.SetPlan, ["nightly", flag, "x"])


def test_plan_list_shows_a_policy_name_rather_than_a_uuid():
    _client, (columns, rows) = run(plan.ListPlan, [])
    assert columns == plan.COLUMNS
    assert rows[0][columns.index("policy")] == "gold"
    assert rows[0][columns.index("unsatisfied")] == '["backup_repository_gone"]'
    assert "state" not in columns


def test_plan_restore_lifts_a_soft_delete():
    client, _ = run(plan.RestorePlan, [PLAN_ID])
    assert client.one("plan_restore")[0] == (PLAN_ID,)


def test_plan_missed_ticks_report_why_a_tick_never_ran():
    client, (columns, rows) = run(plan.ListPlanMissedTick,
                                  ["nightly", "--limit", "5"])
    assert columns == plan.MISSED_TICK_COLUMNS
    assert rows[0][columns.index("reason")] == "start_within_elapsed"
    assert client.one("plan_missed_ticks")[1]["limit"] == 5


def test_point_create_in_a_plan_sends_the_date_it_is_kept_until():
    client, _ = run(point.CreatePoint,
                    ["--plan", "nightly", "--keep-until", "2027-01-31T23:59:59Z"])
    body = client.one("point_create")[0][0]
    assert body == {"plan_id": PLAN_ID, "keep_until": "2027-01-31T23:59:59Z"}


def test_point_create_without_a_date_leaves_it_to_the_policy():
    client, _ = run(point.CreatePoint, ["--plan", "nightly"])
    body = client.one("point_create")[0][0]
    assert "keep" not in body and "keep_until" not in body


def test_point_create_into_a_vault_names_the_resource_and_vault():
    client, _ = run(point.CreatePoint,
                    ["--resource", "vol-9", "--resource-kind", "volume",
                     "--vault", "Immutable", "--consistency", "crash",
                     "--keep-until", "2027-01-31T23:59:59Z"])
    body = client.one("point_create")[0][0]
    assert body == {"resource_id": "vol-9", "resource_kind": "volume",
                    "vault_id": VAULT_ID, "consistency": "crash",
                    "keep_until": "2027-01-31T23:59:59Z"}


def test_point_create_until_deleted_sends_no_date():
    client, _ = run(point.CreatePoint,
                    ["--resource", "vol-9", "--resource-kind", "volume",
                     "--vault", "Standard", "--until-deleted"])
    body = client.one("point_create")[0][0]
    assert body["until_deleted"] is True and "keep_until" not in body


def test_point_create_by_policy_still_names_the_policy_for_one_release():
    client, _ = run(point.CreatePoint,
                    ["--resource", "vol-9", "--resource-kind", "volume",
                     "--policy", "gold"])
    body = client.one("point_create")[0][0]
    assert body["policy_id"] == POLICY_ID and "vault_id" not in body


def test_point_create_outside_a_plan_needs_its_kind_and_vault():
    with pytest.raises(SystemExit):
        run(point.CreatePoint, ["--resource", "vol-9", "--resource-kind", "volume"])


def test_a_date_and_until_deleted_are_not_both():
    with pytest.raises(SystemExit):
        run(point.CreatePoint,
            ["--resource", "vol-9", "--resource-kind", "volume",
             "--vault", "Standard", "--until-deleted",
             "--keep-until", "2027-01-31T23:59:59Z"])


def test_point_verify_queues_a_job_and_shows_it():
    client, (columns, values) = run(point.VerifyPoint, [POINT_ID])
    assert client.one("point_verify")[0] == (POINT_ID,)
    assert dict(zip(columns, values))["kind"] == "verify"


def test_point_verify_is_registered_as_a_command():
    pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert ('backup_point_verify = "ferryclient.osc.v1.point:VerifyPoint"'
            in pyproject.read_text())


def test_point_verify_needs_a_point():
    with pytest.raises(SystemExit):
        run(point.VerifyPoint, [])


def test_restore_create_sends_the_shape_of_a_restore_as_new():
    client, _ = run(restore.CreateRestore,
                    ["--point", POINT_ID, "--mode", "instance",
                     "--name", "web-restored", "--flavor", "m1.large",
                     "--networks", "net-a,net-b", "--networks", "net-c",
                     "--key-name", "ops",
                     "--security-groups", "default, web",
                     "--disks", "vol-1,vol-2"])
    assert client.one("restore_create")[0][0] == {
        "point_id": POINT_ID, "mode": "instance", "name": "web-restored",
        "flavor": "m1.large", "networks": ["net-a", "net-b", "net-c"],
        "key_name": "ops", "security_groups": ["default", "web"],
        "resource_ids": ["vol-1", "vol-2"]}


def test_restore_create_needs_a_point_and_defaults_to_a_new_volume():
    with pytest.raises(SystemExit):
        run(restore.CreateRestore, ["--mode", "volume"])
    client, _ = run(restore.CreateRestore, ["--point", POINT_ID])
    assert client.one("restore_create")[0][0] == {"point_id": POINT_ID,
                                                  "mode": "volume"}


def test_restore_create_restores_a_bucket_into_a_new_one():
    client, _ = run(restore.CreateRestore,
                    ["--point", POINT_ID, "--mode", "bucket",
                     "--name", "logs-restored", "--tier", "chunk"])
    assert client.one("restore_create")[0][0] == {
        "point_id": POINT_ID, "mode": "bucket", "name": "logs-restored",
        "tier": "chunk"}


def test_restore_create_refuses_a_mode_or_tier_the_api_does_not_have():
    for argv in (["--mode", "cross_cloud"], ["--mode", "attach"],
                 ["--tier", "ceph"]):
        with pytest.raises(SystemExit):
            run(restore.CreateRestore, ["--point", POINT_ID] + argv)


def test_restore_create_no_longer_targets_another_cloud():
    with pytest.raises(SystemExit):
        run(restore.CreateRestore,
            ["--point", POINT_ID, "--target-cloud", "cloud-b"])


def test_restore_create_names_a_recovery_profile_and_what_it_confirms():
    client, _ = run(restore.CreateRestore,
                    ["--point", POINT_ID, "--mapping-profile", "a-to-b",
                     "--confirm-unresolved", "network:net-1",
                     "--confirm-unresolved", "key_pair"])
    body = client.one("restore_create")[0][0]
    assert body["mapping_profile"] == "a-to-b"
    assert body["confirm_unresolved"] == ["network:net-1", "key_pair"]
    assert "target_cloud" not in body


def test_attachment_create_attaches_for_four_hours_by_default():
    client, _ = run(restore.CreateAttachment,
                    ["--point", POINT_ID, "--instance", "inst-1"])
    assert client.one("attachment_create")[0][0] == {
        "point_id": POINT_ID, "target_instance_id": "inst-1",
        "expires_in": "4h"}


def test_attachment_create_picks_one_disk_and_a_ttl():
    client, _ = run(restore.CreateAttachment,
                    ["--point", POINT_ID, "--instance", "inst-1",
                     "--disk", "vol-2", "--device", "/dev/vdc",
                     "--ttl", "30m"])
    assert client.one("attachment_create")[0][0] == {
        "point_id": POINT_ID, "target_instance_id": "inst-1",
        "resource_id": "vol-2", "device": "/dev/vdc", "expires_in": "30m"}


def test_attachment_create_needs_an_instance_and_is_always_read_only():
    with pytest.raises(SystemExit):
        run(restore.CreateAttachment, ["--point", POINT_ID])
    with pytest.raises(SystemExit):
        run(restore.CreateAttachment,
            ["--point", POINT_ID, "--instance", "inst-1", "--read-only"])


def _response(status, body=None, text=None, headers=None):
    def decode():
        if body is None:
            raise ValueError("not json")
        return body
    return types.SimpleNamespace(
        status_code=status, headers=headers or {}, json=decode,
        text=text if text is not None else json.dumps(body))


def test_a_validation_error_says_which_field_and_why():
    exc = exceptions.from_response(_response(422, {
        "type": "urn:ferry:error:validation_failed",
        "title": "request failed validation", "status": 422,
        "code": "validation_failed",
        "fields": {"name": "required",
                   "encryption": 'no key manager here; send "none"'}},
        headers={"X-Request-Id": "req-1"}))
    assert exc.fields == {"name": "required",
                          "encryption": 'no key manager here; send "none"'}
    assert str(exc).splitlines() == [
        "HTTP 422 (validation_failed) request failed validation "
        "[request-id: req-1]",
        '  encryption: no key manager here; send "none"',
        "  name: required",
    ]


def test_an_error_shows_its_title_and_its_detail():
    exc = exceptions.from_response(_response(409, {
        "title": "point is not restorable", "code": "point_not_restorable",
        "detail": "point is in state pending"}))
    assert isinstance(exc, exceptions.Conflict)
    assert str(exc) == ("HTTP 409 (point_not_restorable) point is not "
                        "restorable: point is in state pending")


def test_an_error_does_not_repeat_a_detail_that_is_its_title():
    exc = exceptions.from_response(_response(404, {
        "title": "no such point", "detail": "no such point",
        "code": "not_found"}))
    assert str(exc) == "HTTP 404 (not_found) no such point"


def test_a_body_that_is_not_a_problem_document_is_kept_as_the_detail():
    exc = exceptions.from_response(
        _response(502, text="<html>Bad Gateway</html>"))
    assert exc.fields == {}
    assert str(exc) == "HTTP 502 <html>Bad Gateway</html>"


def test_an_unavailable_service_says_when_to_retry():
    exc = exceptions.from_response(_response(503, {
        "title": "temporarily unavailable", "code": "service_unavailable",
        "detail": "Keystone did not answer in time; retry shortly"},
        headers={"Retry-After": "5", "X-Request-Id": "req-2"}))
    assert isinstance(exc, exceptions.ServiceUnavailable)
    assert exc.retry_after == 5
    assert str(exc) == (
        "HTTP 503 (service_unavailable) temporarily unavailable: Keystone "
        "did not answer in time; retry shortly (retry after 5s) "
        "[request-id: req-2]")


def test_an_error_without_retry_after_has_none():
    exc = exceptions.from_response(_response(503, {
        "code": "service_unavailable"}, headers={"Retry-After": "soon"}))
    assert exc.retry_after is None
    assert "retry after" not in str(exc)


def test_vault_list_shows_what_a_tenant_may_choose():
    client, (columns, rows) = run(vault.ListVault, [])
    assert columns == ("id", "name", "immutable", "sentence")
    assert list(rows)[0][1] == "Immutable"


def test_vault_show_finds_it_by_name():
    client, _ = run(vault.ShowVault, ["Immutable"])
    assert client.one("vault_show")[0][0] == "Immutable"


def test_repository_create_registers_a_contract_not_a_flag():
    client, _ = run(repository.CreateRepository,
                    ["cold", "--kind", "chunk", "--site", "site-a",
                     "--driver", "s3", "--bucket", "ferry",
                     "--lock-mode", "compliance",
                     "--lock-min-retention", "720h",
                     "--lock-max-retention", "0",
                     "--lock-changeable-until", "2026-09-15T00:00:00Z",
                     "--soft-delete-grace", "336h"])
    body = client.one("repository_register")[0][0]
    assert body["object_lock"] == {
        "mode": "compliance", "min_retention": "720h",
        "max_retention": "0",
        "changeable_until": "2026-09-15T00:00:00Z"}
    assert body["soft_delete_grace"] == "336h"


def test_repository_create_no_longer_takes_a_lock_boolean():
    with pytest.raises(SystemExit):
        run(repository.CreateRepository,
            ["cold", "--kind", "chunk", "--site", "site-a", "--object-lock"])


def test_repository_create_refuses_a_contract_on_an_rbd_tier():
    with pytest.raises(SystemExit):
        run(repository.CreateRepository,
            ["fast", "--kind", "rbd", "--site", "site-a", "--pool", "ferry",
             "--lock-mode", "compliance", "--lock-min-retention", "720h"])


def test_repository_set_writes_the_contract_against_a_named_repository():
    client, _ = run(repository.SetRepository,
                    ["cold", "--lock-min-retention", "1440h"])
    args = client.one("repository_update")[0]
    assert args[0] == "cold"
    assert args[1] == {"object_lock": {"min_retention": "1440h"}}


def test_repository_create_names_where_it_is_readable():
    client, _ = run(repository.CreateRepository,
                    ["cold-replica", "--kind", "chunk", "--site", "site-b",
                     "--bucket", "ferry",
                     "--reachable-from-site", "cloud-b",
                     "--reachable-from-site", "cloud-a",
                     "--replica-of", "cold"])
    body = client.one("repository_register")[0][0]
    assert body["reachable_from_sites"] == ["site-cloud-b", "site-cloud-a"]
    assert body["replica_of"] == "repo-cold"

    client, _ = run(repository.CreateRepository,
                    ["plain", "--kind", "chunk", "--site", "site-b"])
    body = client.one("repository_register")[0][0]
    assert "reachable_from_sites" not in body and "replica_of" not in body


def test_repository_set_replaces_and_clears_where_it_is_readable():
    client, _ = run(repository.SetRepository,
                    ["cold-replica", "--reachable-from-site", "cloud-b",
                     "--replica-of", "cold"])
    assert client.one("repository_update")[0][1] == {
        "reachable_from_sites": ["site-cloud-b"], "replica_of": "repo-cold"}

    client, _ = run(repository.SetRepository,
                    ["cold-replica", "--clear-reachable-from-sites",
                     "--clear-replica-of"])
    assert client.one("repository_update")[0][1] == {
        "reachable_from_sites": [], "replica_of": ""}

    for argv in (["--clear-reachable-from-sites",
                  "--reachable-from-site", "cloud-a"],
                 ["--clear-replica-of", "--replica-of", "cold"]):
        with pytest.raises(SystemExit):
            run(repository.SetRepository, ["cold-replica"] + argv)


def test_repository_create_and_set_say_the_environment_supplies_the_key():
    client, _ = run(repository.CreateRepository,
                    ["theirs", "--kind", "chunk", "--site", "site-b",
                     "--driver", "s3", "--bucket", "ferry-repo",
                     "--environment-credentials"])
    body = client.one("repository_register")[0][0]
    assert body["environment_credentials"] is True
    assert "access_key" not in body

    client, _ = run(repository.CreateRepository,
                    ["theirs", "--kind", "chunk", "--site", "site-b",
                     "--driver", "s3", "--bucket", "ferry-repo"])
    assert "environment_credentials" not in client.one(
        "repository_register")[0][0]

    client, _ = run(repository.SetRepository,
                    ["theirs", "--endpoint", "http://10.10.10.11:6780",
                     "--environment-credentials"])
    assert client.one("repository_update")[0][1] == {
        "endpoint": "http://10.10.10.11:6780",
        "environment_credentials": True}

    with pytest.raises(SystemExit):
        run(repository.SetRepository, ["theirs", "--environment-credentials"])


def test_repository_set_will_not_both_state_and_clear_a_contract():
    with pytest.raises(SystemExit):
        run(repository.SetRepository,
            ["cold", "--clear-object-lock", "--lock-mode", "governance"])
    client, _ = run(repository.SetRepository,
                    ["cold", "--clear-object-lock"])
    assert client.one("repository_update")[0][1] == {"clear_object_lock": True}


def test_legal_hold_create_names_its_scope():
    client, _ = run(hold.CreateLegalHold,
                    ["--plan", "nightly", "--reason", "litigation"])
    assert client.one("legal_hold_create")[0][0] == {
        "scope": "plan", "target_id": PLAN_ID, "reason": "litigation"}

    client, _ = run(hold.CreateLegalHold,
                    ["--project", "b2f4", "--reason", "audit"])
    assert client.one("legal_hold_create")[0][0]["scope"] == "project"


def test_legal_hold_create_needs_one_scope_and_a_reason():
    with pytest.raises(SystemExit):
        run(hold.CreateLegalHold, ["--reason", "litigation"])
    with pytest.raises(SystemExit):
        run(hold.CreateLegalHold, ["--plan", "nightly"])
    with pytest.raises(SystemExit):
        run(hold.CreateLegalHold,
            ["--plan", "nightly", "--point", "p", "--reason", "x"])


def test_legal_hold_list_is_what_is_still_held_unless_asked_otherwise():
    client, (columns, rows) = run(hold.ListLegalHold, [])
    assert columns == hold.COLUMNS
    assert rows[0][columns.index("active")] is True
    assert client.one("legal_hold_list")[1]["active"] is None

    client, _ = run(hold.ListLegalHold, ["--include-lifted"])
    assert client.one("legal_hold_list")[1]["active"] == "false"

    client, _ = run(hold.ListLegalHold, ["--scope", "plan"])
    assert client.one("legal_hold_list")[1]["hold_scope"] == "plan"
    assert "scope" not in client.one("legal_hold_list")[1]


def test_legal_hold_delete_lifts_each_named_hold():
    client, _ = run(hold.DeleteLegalHold, ["h1", "h2"])
    assert [a for a, _k in client.named("legal_hold_delete")] == \
        [("h1",), ("h2",)]


def test_retention_simulate_is_a_policy_edit():
    client, _ = run(misc.SimulateRetention,
                    ["--policy", "gold", "--plan", "nightly",
                     "--keep-all", "72h", "--keep-monthly", "12",
                     "--anchor", "month=last"])
    body = client.one("retention_simulate")[0][0]
    assert body == {"policy_id": POLICY_ID, "plan_id": PLAN_ID,
                    "spec": {"keep": {"all": "72h", "monthly": 12,
                                      "anchors": {"month": "last"}}}}
    assert "retention" not in body


def test_retention_simulate_without_a_candidate_asks_about_tonight():
    client, _ = run(misc.SimulateRetention, ["--policy", "gold"])
    assert client.one("retention_simulate")[0][0] == {"policy_id": POLICY_ID}


def test_retention_simulate_no_longer_takes_a_plan_as_its_subject():
    with pytest.raises(SystemExit):
        run(misc.SimulateRetention, ["--plan", "nightly"])
    with pytest.raises(SystemExit):
        run(misc.SimulateRetention, ["--policy", "gold", "--keep-last", "7"])


def test_coverage_show_is_one_report_for_the_cloud_or_one_project():
    client, _ = run(misc.ShowCoverage, [])
    assert client.one("coverage")[1] == {"project_id": None}
    client, _ = run(misc.ShowCoverage, ["--project", "b2f4"])
    assert client.one("coverage")[1] == {"project_id": "b2f4"}


class RecordingClient(v1_client.Client):
    def __init__(self):
        self.sent = []
        self._timeout = None
        self._base = ""

    def request(self, method, path, body=None, params=None):
        self.sent.append((method, path, body, params))
        if method == "GET" and path == "/v1/policies":
            return {"items": [{"id": POLICY_ID, "name": "gold"},
                              {"id": OTHER_POLICY_ID, "name": "platinum"}]}
        if method == "GET" and path == "/v1/repositories":
            return {"items": [{"id": REPO_ID, "name": "cold"}]}
        if method == "GET" and path == "/v1/plans":
            return {"items": [{"id": PLAN_ID, "name": "nightly"}]}
        if method == "GET" and path == "/v1/sites":
            return {"items": [
                {"id": LOCAL_SITE_ID, "name": "cloud-a", "local": True},
                {"id": SITE_ID, "name": "cloud-b", "local": False},
                {"id": "aaaaaaaa-0000-4000-8000-000000000003", "name": "dup"},
                {"id": "aaaaaaaa-0000-4000-8000-000000000004", "name": "dup"},
            ]}
        return {}

    def last(self):
        return self.sent[-1]


def test_a_site_is_named_and_the_api_is_sent_its_id():
    client = RecordingClient()
    assert client.site_find("cloud-b") == SITE_ID
    assert client.last()[:2] == ("GET", "/v1/sites")

    client.sent.clear()
    assert client.site_find(LOCAL_SITE_ID) == LOCAL_SITE_ID
    assert client.sent == []

    with pytest.raises(exceptions.NotFound) as unknown:
        client.site_find("nowhere")
    assert unknown.value.status_code == 404
    assert '"nowhere"' in unknown.value.detail

    with pytest.raises(exceptions.NotFound) as ambiguous:
        client.site_find("dup")
    assert ambiguous.value.status_code == 409
    assert "use an id" in ambiguous.value.detail


def test_site_list_shows_every_site_and_which_is_local():
    client = RecordingClient()
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = misc.ListSite(app=app, app_args=None)
    columns, rows = cmd.take_action(
        cmd.get_parser("openstack backup site list").parse_args([]))
    assert columns == ("id", "name", "local")
    assert (SITE_ID, "cloud-b", False) in rows
    assert (LOCAL_SITE_ID, "cloud-a", True) in rows
    assert client.last() == ("GET", "/v1/sites", None, None)

    cmd.take_action(cmd.get_parser("openstack backup site list")
                    .parse_args(["--limit", "1"]))
    assert client.last() == ("GET", "/v1/sites", None, {"limit": 1})


def test_a_policy_and_a_repository_resolve_their_sites_through_the_api():
    client = RecordingClient()
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = policy.CreatePolicy(app=app, app_args=None)
    cmd.take_action(cmd.get_parser("openstack backup policy create")
                    .parse_args(["gold", "--every", "1h",
                                 "--backup-repository", "cold",
                                 "--recovery-site", "cloud-b",
                                 "--recovery-rung", "warm"]))
    method, path, body, _ = client.last()
    assert (method, path) == ("POST", "/v1/policies")
    assert body["spec"]["recovery"]["site_id"] == SITE_ID
    assert body["spec"]["tiers"]["backup"]["repository_id"] == REPO_ID

    cmd = repository.SetRepository(app=app, app_args=None)
    cmd.take_action(cmd.get_parser("openstack backup repository set")
                    .parse_args(["cold", "--reachable-from-site", "cloud-b",
                                 "--reachable-from-site", LOCAL_SITE_ID,
                                 "--replica-of", "cold"]))
    method, path, body, _ = client.last()
    assert (method, path) == ("PATCH", f"/v1/repositories/{REPO_ID}")
    assert body == {"reachable_from_sites": [SITE_ID, LOCAL_SITE_ID],
                    "replica_of": REPO_ID}

    with pytest.raises(exceptions.NotFound):
        cmd.take_action(cmd.get_parser("openstack backup repository set")
                        .parse_args(["cold", "--reachable-from-site", "dup"]))
    assert client.last()[0] == "GET"


def test_apply_to_existing_is_a_query_parameter():
    client = RecordingClient()
    client.policy_update("gold", {"spec": {}}, apply_to_existing=True)
    assert client.last() == ("PATCH", f"/v1/policies/{POLICY_ID}",
                             {"spec": {}}, {"apply_to_existing": "true"})
    client.policy_update("gold", {"spec": {}})
    assert client.last()[3] is None


def test_assign_and_remove_are_one_route():
    client = RecordingClient()
    client.policy_assign("gold", {"projects": ["p"]}, remove=True)
    assert client.last() == ("POST", f"/v1/policies/{POLICY_ID}/assign",
                             {"projects": ["p"]}, {"remove": "true"})
    client.policy_assign("gold", {"projects": ["p"]})
    assert client.last()[3] is None


def test_retire_resolves_the_successor_to_an_id():
    client = RecordingClient()
    client.policy_retire("gold", successor="platinum")
    assert client.last() == ("POST", f"/v1/policies/{POLICY_ID}/retire",
                             None, {"successor": OTHER_POLICY_ID})


def test_a_policy_is_named_and_the_route_takes_an_id():
    client = RecordingClient()
    client.policy_show("gold")
    assert client.last()[:2] == ("GET", f"/v1/policies/{POLICY_ID}")
    client.policy_deprecate("gold")
    assert client.last()[:2] == ("POST", f"/v1/policies/{POLICY_ID}/deprecate")


def test_delete_resolves_a_name_and_takes_several():
    client = RecordingClient()
    client.policy_delete("gold")
    assert client.last()[:2] == ("DELETE", f"/v1/policies/{POLICY_ID}")
    client.policy_delete("platinum")
    assert client.last()[:2] == ("DELETE", f"/v1/policies/{OTHER_POLICY_ID}")


def test_a_repository_is_patched_and_deleted_by_name_too():
    client = RecordingClient()
    client.repository_update("cold", {"object_lock": {"min_retention": "1h"}})
    assert client.last()[:2] == ("PATCH", f"/v1/repositories/{REPO_ID}")
    client.repository_delete("cold")
    assert client.last()[:2] == ("DELETE", f"/v1/repositories/{REPO_ID}")


def test_coverage_and_holds_send_no_empty_filters():
    client = RecordingClient()
    client.coverage(project_id=None)
    assert client.last() == ("GET", "/v1/coverage", None, None)
    client.legal_hold_list(hold_scope=None, active=None, limit=None)
    assert client.last() == ("GET", "/v1/legal-holds", None, None)
    client.legal_hold_delete("hold-1")
    assert client.last()[:2] == ("DELETE", "/v1/legal-holds/hold-1")


def test_point_verify_posts_to_the_point():
    client = RecordingClient()
    client.point_verify(POINT_ID)
    assert client.last() == ("POST", f"/v1/points/{POINT_ID}/verify",
                             None, None)


def test_a_plan_is_restored_and_its_missed_ticks_listed_by_name():
    client = RecordingClient()
    client.plan_restore("nightly")
    assert client.last()[:2] == ("POST", f"/v1/plans/{PLAN_ID}/undelete")
    client.plan_missed_ticks("nightly", limit=5)
    assert client.last() == ("GET", f"/v1/plans/{PLAN_ID}/missed-ticks",
                             None, {"limit": 5})


class PagedClient(v1_client.Client):
    def __init__(self):
        self.sent = []
        self._timeout = None
        self._base = ""

    def request(self, method, path, body=None, params=None):
        self.sent.append(params)
        if (params or {}).get("marker") == "m1":
            return {"items": [{"id": "c"}], "limit": 2}
        return {"items": [{"id": "a"}, {"id": "b"}], "limit": 2,
                "next_marker": "m1"}


def test_a_list_reads_every_page():
    client = PagedClient()
    assert [p["id"] for p in client.plan_list(resource_kind="volume")] == \
        ["a", "b", "c"]
    assert client.sent == [{"resource_kind": "volume"},
                           {"resource_kind": "volume", "marker": "m1"}]


def test_a_list_with_a_limit_reads_one_page():
    client = PagedClient()
    assert len(client.plan_list(limit=2)) == 2
    assert client.sent == [{"limit": 2}]
