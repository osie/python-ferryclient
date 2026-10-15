import types

import pytest

from ferryclient.osc.v1 import base
from ferryclient.osc.v1 import point
from ferryclient.osc.v1 import restore


class FakeClient:
    def __init__(self, create_response, job_states):
        self._create_response = create_response
        self._job_states = list(job_states)
        self.job_calls = []

    def job_show(self, job_id):
        self.job_calls.append(job_id)
        state = self._job_states.pop(0) if len(self._job_states) > 1 else self._job_states[0]
        attempts = 3 if state == "failed" else 1
        return {"id": job_id, "state": state, "attempts": attempts, "max_attempts": 3}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            return self._create_response
        return call


def run(cls, client, argv):
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = cls(app=app, app_args=None)
    parsed = cmd.get_parser("openstack test").parse_args(argv)
    return cmd.take_action(parsed)


def test_restore_create_wait_polls_until_succeeded(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    client = FakeClient({"id": "r1", "job_id": "j1"}, ["running", "running", "succeeded"])
    run(restore.CreateRestore, client,
        ["--point", "p1", "--wait"])
    assert client.job_calls == ["j1", "j1", "j1"]


def test_restore_create_without_wait_does_not_poll():
    client = FakeClient({"id": "r1", "job_id": "j1"}, ["succeeded"])
    run(restore.CreateRestore, client, ["--point", "p1"])
    assert client.job_calls == []


def test_attachment_create_wait_raises_on_failure(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    client = FakeClient({"id": "a1", "job_id": "j1"}, ["failed", "failed", "failed"])
    with pytest.raises(SystemExit):
        run(restore.CreateAttachment, client,
            ["--point", "p1", "--instance", "i1", "--wait"])


def test_point_create_wait_follows_every_run(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    create_response = {
        "runs": [{"resource_id": "r1", "job_id": "j1"},
                 {"resource_id": "r2", "job_id": "j2"}]}
    client = FakeClient(create_response, ["succeeded"])
    run(point.CreatePoint, client, ["--plan", "p1", "--wait"])
    assert client.job_calls == ["j1", "j2"]
