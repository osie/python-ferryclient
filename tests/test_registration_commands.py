import pathlib
import types

import pytest

from ferryclient import exceptions
from ferryclient.osc.v1 import group
from ferryclient.osc.v1 import recovery
from ferryclient.v1 import client as v1_client

GROUP_ID = "11111111-1111-4111-8111-111111111111"
GROUP_UID = "22222222-2222-4222-8222-222222222222"
REPO_ID = "66666666-6666-4666-8666-666666666666"
POLICY_ID = "55555555-5555-4555-8555-555555555555"
PROFILE_ID = "9c2b1c4d-0000-4000-8000-000000000001"
BUBBLE_ID = "44444444-4444-4444-8444-444444444444"
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

    def one(self, name):
        calls = [(a, k) for n, a, k in self.calls if n == name]
        assert len(calls) == 1, f"{name} not called once: {self.calls}"
        return calls[0]


def run(cls, argv, **responses):
    client = FakeClient(responses)
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = cls(app=app, app_args=None)
    parsed = cmd.get_parser("openstack test").parse_args(argv)
    return client, cmd.take_action(parsed)


def test_register_resolves_names_and_sends_the_registration():
    client, (columns, values) = run(
        group.RegisterGroup,
        [GROUP_UID, "--repository", "cold", "--origin-cloud", "cloud-a",
         "--target-project", "proj-b", "--target-domain", "dom-b",
         "--policy", "gold-back", "--name", "payments-dr",
         "--mapping-profile", "from-cloud-a", "--bubble-policy", BUBBLE_ID,
         "--test-every", "720h", "--standby-pool", "dr-standby",
         "--standby-site", "cloud-b", "--standby-prefix", "dr-",
         "--accept-gap", "network:net-1", "--accept-gap", "flavor:big",
         "--network-map", "prod=dr"],
        repository_find=REPO_ID, policy_find=POLICY_ID,
        recovery_profile_find=PROFILE_ID, site_find=SITE_ID,
        bubble_policy_find=BUBBLE_ID,
        group_register={"id": GROUP_ID, "role": "recovery",
                        "bindings": [{"source_resource_id": "db-01"}]})
    assert client.one("repository_find")[0] == ("cold",)
    assert client.one("policy_find")[0] == ("gold-back",)
    assert client.one("recovery_profile_find")[0] == ("from-cloud-a",)
    assert client.one("site_find")[0] == ("cloud-b",)
    assert client.one("bubble_policy_find")[0] == (BUBBLE_ID,)
    args, kwargs = client.one("group_register")
    assert args == (REPO_ID, GROUP_UID, "proj-b", POLICY_ID)
    assert kwargs == {
        "origin_cloud": "cloud-a", "name": "payments-dr",
        "target_domain_id": "dom-b", "mapping_profile_id": PROFILE_ID,
        "bubble_policy_id": BUBBLE_ID, "test_every": "720h",
        "standby_pool": "dr-standby", "standby_site_id": SITE_ID,
        "standby_prefix": "dr-",
        "accept_gaps": ["network:net-1", "flavor:big"],
        "network_map": {"prod": "dr"}}
    shown = dict(zip(columns, values))
    assert shown["id"] == GROUP_ID and shown["role"] == "recovery"
    assert "db-01" in shown["bindings"]


def test_register_needs_what_the_api_needs():
    for argv in ([GROUP_UID, "--target-project", "p", "--policy", "x"],
                 [GROUP_UID, "--repository", "r", "--policy", "x"],
                 [GROUP_UID, "--repository", "r", "--target-project", "p"],
                 ["--repository", "r", "--target-project", "p", "--policy", "x"]):
        with pytest.raises(SystemExit):
            run(group.RegisterGroup, argv)


def test_register_refuses_a_standby_without_a_pool():
    client = FakeClient({})
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = group.RegisterGroup(app=app, app_args=None)
    for flag, value in (("--standby-site", SITE_ID), ("--standby-prefix", "dr-")):
        parsed = cmd.get_parser("openstack test").parse_args(
            [GROUP_UID, "--repository", "cold", "--target-project", "p",
             "--policy", "gold", flag, value])
        with pytest.raises(SystemExit):
            cmd.take_action(parsed)
    assert client.calls == []


def test_register_leaves_out_what_was_not_given():
    client, _ = run(group.RegisterGroup,
                    [GROUP_UID, "--repository", REPO_ID, "--target-project",
                     "proj-b", "--policy", POLICY_ID],
                    repository_find=REPO_ID, policy_find=POLICY_ID)
    assert not [c for c in client.calls if c[0] == "recovery_profile_find"]
    assert not [c for c in client.calls if c[0] == "site_find"]
    _args, kwargs = client.one("group_register")
    assert kwargs["mapping_profile_id"] is None
    assert kwargs["standby_site_id"] is None
    assert kwargs["network_map"] == {} and "test_network_map" not in kwargs
    assert kwargs["accept_gaps"] is None and kwargs["standby_pool"] is None


def test_group_list_filters_by_role_and_shows_it():
    client, (columns, rows) = run(
        group.ListGroup, ["--role", "recovery"],
        group_list=[{"id": GROUP_ID, "name": "payments", "role": "recovery",
                     "members": [{"instance_id": "a"}]}])
    assert client.one("group_list")[1] == {"limit": None, "project_id": None,
                                           "role": "recovery"}
    assert dict(zip(columns, rows[0]))["role"] == "recovery"
    with pytest.raises(SystemExit):
        run(group.ListGroup, ["--role", "secondary"])


def test_readiness_arm_and_disarm():
    client, (columns, values) = run(
        group.ShowGroupReadiness, [GROUP_ID],
        group_readiness={"group_id": GROUP_ID, "ready": False,
                         "issues": [{"code": "binding_conflict"}]})
    assert client.one("group_readiness") == ((GROUP_ID,), {})
    shown = dict(zip(columns, values))
    assert shown["ready"] is False and "binding_conflict" in shown["issues"]

    client, (columns, values) = run(
        group.ArmGroup, ["--expires-in", "2160h", GROUP_ID],
        group_arm={"id": GROUP_ID, "armed": True})
    assert client.one("group_arm") == ((GROUP_ID,), {"expires_in": "2160h"})
    assert dict(zip(columns, values))["armed"] is True
    client, _ = run(group.ArmGroup, [GROUP_ID])
    assert client.one("group_arm") == ((GROUP_ID,), {"expires_in": None})

    client, result = run(group.DisarmGroup, [GROUP_ID])
    assert client.one("group_disarm") == ((GROUP_ID,), {})
    assert result is None


def test_mirror_lists_each_mirrored_disk_of_a_hot_group():
    client, (columns, rows) = run(
        group.ListGroupMirror, [GROUP_ID],
        group_mirror={"group_id": GROUP_ID, "rung": "hot",
                      "worst_lag_seconds": 1500, "split_brain": True,
                      "images": [
                          {"global_id": "g-a", "member_instance_id": "db-01",
                           "pool": "volumes", "image": "volume-a",
                           "role": "primary", "state": "ok",
                           "peer_site": "charmed", "lag_seconds": 240,
                           "split_brain": False},
                          {"global_id": "g-b", "member_instance_id": "app-01",
                           "pool": "volumes", "image": "volume-b",
                           "role": "primary", "state": "split_brain",
                           "lag_seconds": 1500, "split_brain": True,
                           "error": "both regions hold a primary copy"}]})
    assert client.one("group_mirror") == ((GROUP_ID,), {})
    first, second = (dict(zip(columns, r)) for r in rows)
    assert first["global_id"] == "g-a" and first["peer_site"] == "charmed"
    assert first["mirror_state"] == "" and first["lag_seconds"] == 240
    assert second["state"] == "split_brain" and second["split_brain"] is True

    client, (columns, rows) = run(group.ListGroupMirror, [GROUP_ID],
                                  group_mirror={"group_id": GROUP_ID})
    assert rows == []


def test_recovery_group_list_reads_a_repositorys_group_documents():
    client, (columns, rows) = run(
        recovery.ListRecoveryGroup, ["cold", "--origin-cloud", "cloud-a"],
        repository_groups=[{"group_uid": GROUP_UID, "name": "payments",
                            "origin_cloud": "cloud-a", "rung": "warm",
                            "member_count": 3, "version": 4,
                            "registered_as": GROUP_ID}])
    assert client.one("repository_groups") == (("cold",),
                                               {"origin_cloud": "cloud-a"})
    row = dict(zip(columns, rows[0]))
    assert row["group_uid"] == GROUP_UID and row["registered_as"] == GROUP_ID
    assert row["member_count"] == 3 and row["version"] == 4


def test_the_registration_commands_are_registered():
    root = pathlib.Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    entry_points = (root / "python_ferryclient.egg-info"
                    / "entry_points.txt").read_text()
    for name, target in (
        ("backup_group_register", "group:RegisterGroup"),
        ("backup_group_readiness_show", "group:ShowGroupReadiness"),
        ("backup_group_mirror_list", "group:ListGroupMirror"),
        ("backup_group_arm", "group:ArmGroup"),
        ("backup_group_disarm", "group:DisarmGroup"),
        ("backup_recovery_group_list", "recovery:ListRecoveryGroup"),
    ):
        assert f'{name} = "ferryclient.osc.v1.{target}"' in pyproject
        assert f"{name} = ferryclient.osc.v1.{target}" in entry_points


class RecordingClient(v1_client.Client):
    def __init__(self, pages=None):
        self.sent = []
        self.pages = list(pages or [])
        self._timeout = None
        self._base = ""

    def request(self, method, path, body=None, params=None):
        self.sent.append((method, path, body, params))
        if path.endswith("/inventory") and self.pages:
            return self.pages.pop(0)
        if method == "GET" and path == "/v1/protection-groups":
            return {"items": [
                {"id": GROUP_ID, "name": "payments-prod"},
                {"id": "33333333-3333-4333-8333-333333333333",
                 "name": "dup"},
                {"id": "77777777-7777-4777-8777-777777777777",
                 "name": "dup"},
            ]}
        return None

    def last(self):
        return self.sent[-1]


def test_a_group_is_named_and_the_api_is_sent_its_id():
    client = RecordingClient()
    assert client.group_find("payments-prod") == GROUP_ID
    assert client.last()[:2] == ("GET", "/v1/protection-groups")

    client.sent.clear()
    assert client.group_find(GROUP_ID) == GROUP_ID
    assert client.sent == []

    with pytest.raises(exceptions.NotFound) as unknown:
        client.group_find("nowhere")
    assert unknown.value.status_code == 404
    assert '"nowhere"' in unknown.value.detail

    with pytest.raises(exceptions.NotFound) as ambiguous:
        client.group_find("dup")
    assert ambiguous.value.status_code == 409
    assert "use an id" in ambiguous.value.detail

    client.sent.clear()
    client.group_show("payments-prod")
    assert client.last()[:2] == ("GET", f"/v1/protection-groups/{GROUP_ID}")

    client.sent.clear()
    client.group_run("payments-prod", "run-1")
    assert client.last()[:2] == (
        "GET", f"/v1/protection-groups/{GROUP_ID}/runs/run-1")


def test_the_registration_routes():
    client = RecordingClient()
    base = f"/v1/protection-groups/{GROUP_ID}"

    client.group_register(REPO_ID, GROUP_UID, "proj-b", POLICY_ID)
    assert client.last() == ("POST", "/v1/protection-groups", {
        "recovery_of": {"repository_id": REPO_ID, "group_uid": GROUP_UID},
        "target_project_id": "proj-b", "policy_id": POLICY_ID}, None)

    client.group_register(
        REPO_ID, GROUP_UID, "proj-b", POLICY_ID, origin_cloud="cloud-a",
        name="payments-dr", target_domain_id="dom-b",
        mapping_profile_id=PROFILE_ID, bubble_policy_id=BUBBLE_ID,
        test_every="720h", standby_pool="dr-standby", standby_site_id=SITE_ID,
        standby_prefix="dr-", accept_gaps=["network:net-1"],
        network_map={"prod": "dr"})
    assert client.last() == ("POST", "/v1/protection-groups", {
        "recovery_of": {"repository_id": REPO_ID, "group_uid": GROUP_UID,
                        "origin_cloud": "cloud-a"},
        "target_project_id": "proj-b", "policy_id": POLICY_ID,
        "name": "payments-dr", "target_domain_id": "dom-b",
        "mapping_profile_id": PROFILE_ID, "bubble_policy_id": BUBBLE_ID,
        "test_every": "720h", "accept_gaps": ["network:net-1"],
        "network_map": {"prod": "dr"},
        "standby": {"pool": "dr-standby", "site_id": SITE_ID,
                    "prefix": "dr-"}}, None)

    client.group_register(REPO_ID, GROUP_UID, "proj-b", POLICY_ID,
                          standby_pool="dr-standby", network_map={},
                          accept_gaps=[])
    assert client.last()[2] == {
        "recovery_of": {"repository_id": REPO_ID, "group_uid": GROUP_UID},
        "target_project_id": "proj-b", "policy_id": POLICY_ID,
        "standby": {"pool": "dr-standby"}}

    client.group_readiness(GROUP_ID)
    assert client.last() == ("GET", f"{base}/readiness", None, None)
    client.group_mirror(GROUP_ID)
    assert client.last() == ("GET", f"{base}/mirror", None, None)
    client.group_arm(GROUP_ID)
    assert client.last() == ("POST", f"{base}/arm", None, None)
    client.group_arm(GROUP_ID, expires_in="2160h")
    assert client.last() == ("POST", f"{base}/arm", {"expires_in": "2160h"},
                             None)
    client.group_disarm(GROUP_ID)
    assert client.last() == ("DELETE", f"{base}/arm", None, None)
    client.group_list(role="recovery", include="readiness")
    assert client.last() == ("GET", "/v1/protection-groups", None,
                             {"role": "recovery", "include": "readiness"})


def test_the_group_inventory_pages_through_every_document():
    client = RecordingClient(pages=[
        {"repository": "cold", "entries": [],
         "groups": [{"group_uid": "a"}], "next_marker": "m1"},
        {"repository": "cold", "entries": [], "groups": [{"group_uid": "b"}]},
    ])
    groups = client.repository_groups(REPO_ID, origin_cloud="cloud-a")
    assert [g["group_uid"] for g in groups] == ["a", "b"]
    path = f"/v1/repositories/{REPO_ID}/inventory"
    assert client.sent == [
        ("GET", path, None, {"view": "groups", "origin_cloud": "cloud-a"}),
        ("GET", path, None, {"view": "groups", "origin_cloud": "cloud-a",
                             "marker": "m1"}),
    ]


def _help(cls, dest):
    parser = cls(app=None, app_args=None).get_parser("openstack test")
    return next(a.help for a in parser._actions if a.dest == dest)


def test_a_test_without_a_bubble_policy_is_said_to_be_refused():
    text = _help(group.TestGroup, "bubble_policy_id")
    assert "registration names" in text and "refused" in text


def test_the_home_network_map_is_said_to_serve_only_a_failback_rebuild():
    text = _help(group.CreateGroup, "network_map")
    assert "failback that rebuilds" in text
    assert "failover uses the registration's map" in text


def test_arming_is_not_said_to_cover_a_release():
    doc = " ".join(group.ArmGroup.__doc__.split())
    assert "release stops" not in doc
    assert "A release, a resync, a retire and a test do not use it" in doc
