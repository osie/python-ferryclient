import pathlib
import types

import pytest

from ferryclient.osc.v1 import bubble
from ferryclient.v1 import client as v1_client

BUBBLE_ID = "44444444-4444-4444-8444-444444444444"
PROJECT_ID = "5b6c7d8e9f0a4b1c8d2e3f4a5b6c7d8e"
POLICY = {"id": BUBBLE_ID, "name": "dr-lab", "project_id": PROJECT_ID,
          "network_cidrs": ["10.250.0.0/16"], "strict": True,
          "jump_host": True, "max_duration": 5400000000000,
          "permitted_checks": ["tcp", "http"],
          "isolation_canaries": ["10.0.0.10:5432"],
          "created_at": "2026-10-03T09:00:00Z",
          "updated_at": "2026-10-03T09:00:00Z"}


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


def test_list_shows_the_duration_the_way_it_is_typed():
    client, (columns, rows) = run(bubble.ListBubblePolicy, [],
                                  bubble_policy_list=[POLICY])
    assert client.one("bubble_policy_list") == ((), {})
    row = dict(zip(columns, rows[0]))
    assert row["max_duration"] == "1h30m0s"
    assert row["project_id"] == PROJECT_ID
    assert row["isolation_canaries"] == '["10.0.0.10:5432"]'

    _, (columns, rows) = run(bubble.ListBubblePolicy, ["-f", "json"],
                             bubble_policy_list=[POLICY])
    assert dict(zip(columns, rows[0]))["max_duration"] == 5400000000000


def test_create_sends_only_what_it_was_given():
    client, (columns, values) = run(
        bubble.CreateBubblePolicy,
        ["dr-lab", "--project", PROJECT_ID, "--network-cidr", "10.250.0.0/16",
         "--network-cidr", "10.251.0.0/16"],
        bubble_policy_create=POLICY)
    assert client.one("bubble_policy_create") == ((
        {"name": "dr-lab", "project_id": PROJECT_ID,
         "network_cidrs": ["10.250.0.0/16", "10.251.0.0/16"]},), {})
    shown = dict(zip(columns, values))
    assert shown["id"] == BUBBLE_ID and shown["max_duration"] == "1h30m0s"


def test_create_sends_every_field():
    client, _ = run(
        bubble.CreateBubblePolicy,
        ["dr-lab", "--project", PROJECT_ID, "--network-cidr", "10.250.0.0/16",
         "--no-strict", "--jump-host", "--jump-host-image", "ferry-probe",
         "--jump-host-flavor", "m1.small", "--max-duration", "2h",
         "--permitted-check", "tcp", "--isolation-canary", "10.0.0.10:5432",
         "--isolation-canary", "db.prod.internal:443"],
        bubble_policy_create=POLICY)
    assert client.one("bubble_policy_create")[0][0] == {
        "name": "dr-lab", "project_id": PROJECT_ID,
        "network_cidrs": ["10.250.0.0/16"], "strict": False,
        "jump_host": True, "jump_host_image": "ferry-probe",
        "jump_host_flavor": "m1.small", "max_duration": "2h",
        "permitted_checks": ["tcp"],
        "isolation_canaries": ["10.0.0.10:5432", "db.prod.internal:443"]}


@pytest.mark.parametrize("argv", [
    ["dr-lab", "--network-cidr", "10.250.0.0/16"],
    ["dr-lab", "--project", PROJECT_ID],
    ["dr-lab", "--project", PROJECT_ID, "--network-cidr", "10.250.0.0/16",
     "--permitted-check", "icmp"],
    ["dr-lab", "--project", PROJECT_ID, "--network-cidr", "10.250.0.0/16",
     "--strict", "--no-strict"],
    ["dr-lab", "--project", PROJECT_ID, "--network-cidr", "10.250.0.0/16",
     "--no-isolation-canary"],
])
def test_create_refuses_what_it_cannot_send(argv):
    with pytest.raises(SystemExit):
        run(bubble.CreateBubblePolicy, argv)


def test_set_changes_only_the_options_given():
    client, _ = run(bubble.SetBubblePolicy,
                    ["--no-jump-host", "--no-isolation-canary",
                     "--max-duration", "168h", "dr-lab"],
                    bubble_policy_update=POLICY)
    assert client.one("bubble_policy_update") == ((
        "dr-lab", {"jump_host": False, "isolation_canaries": [],
                   "max_duration": "168h"}), {})

    client, _ = run(bubble.SetBubblePolicy,
                    ["--name", "dr-lab-2", "--permitted-check", "http",
                     BUBBLE_ID], bubble_policy_update=POLICY)
    assert client.one("bubble_policy_update") == ((
        BUBBLE_ID, {"name": "dr-lab-2", "permitted_checks": ["http"]}), {})


def test_set_with_nothing_to_change_sends_nothing():
    client = FakeClient({})
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = bubble.SetBubblePolicy(app=app, app_args=None)
    with pytest.raises(SystemExit):
        cmd.take_action(cmd.get_parser("openstack test").parse_args(
            [BUBBLE_ID]))
    assert client.calls == []


def test_delete_takes_several():
    client, _ = run(bubble.DeleteBubblePolicy, ["dr-lab", BUBBLE_ID])
    assert client.named("bubble_policy_delete") == [
        (("dr-lab",), {}), ((BUBBLE_ID,), {})]


class RecordingClient(v1_client.Client):
    def __init__(self):
        self.sent = []
        self._timeout = None
        self._base = ""

    def request(self, method, path, body=None, params=None):
        self.sent.append((method, path, body, params))
        if method == "GET" and path == "/v1/bubble-policies":
            return {"items": [{"id": BUBBLE_ID, "name": "dr-lab"}],
                    "limit": 50}
        return None

    def last(self):
        return self.sent[-1]


def test_the_bubble_policy_routes():
    client = RecordingClient()
    assert client.bubble_policy_list() == [{"id": BUBBLE_ID,
                                            "name": "dr-lab"}]
    assert client.last() == ("GET", "/v1/bubble-policies", None, None)

    client.bubble_policy_create({"name": "dr-lab"})
    assert client.last() == ("POST", "/v1/bubble-policies",
                             {"name": "dr-lab"}, None)

    client.bubble_policy_update("dr-lab", {"strict": False})
    assert client.last() == ("PATCH", f"/v1/bubble-policies/{BUBBLE_ID}",
                             {"strict": False}, None)

    client.sent = []
    client.bubble_policy_delete(BUBBLE_ID)
    assert client.sent == [("DELETE", f"/v1/bubble-policies/{BUBBLE_ID}",
                            None, None)]


def test_the_bubble_policy_commands_are_registered():
    root = pathlib.Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    entry_points = (root / "python_ferryclient.egg-info"
                    / "entry_points.txt").read_text()
    for name, target in (
        ("backup_bubble_policy_list", "bubble:ListBubblePolicy"),
        ("backup_bubble_policy_create", "bubble:CreateBubblePolicy"),
        ("backup_bubble_policy_set", "bubble:SetBubblePolicy"),
        ("backup_bubble_policy_delete", "bubble:DeleteBubblePolicy"),
    ):
        assert f'{name} = "ferryclient.osc.v1.{target}"' in pyproject
        assert f"{name} = ferryclient.osc.v1.{target}" in entry_points
