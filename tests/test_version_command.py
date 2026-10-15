import types

import ferryclient
from ferryclient.osc.v1 import misc


class FakeClient:
    def __init__(self, healthz=None, healthz_error=None,
                 capabilities=None, capabilities_error=None):
        self._healthz = healthz
        self._healthz_error = healthz_error
        self._capabilities = capabilities
        self._capabilities_error = capabilities_error

    def healthz(self):
        if self._healthz_error is not None:
            raise self._healthz_error
        return self._healthz

    def capabilities(self):
        if self._capabilities_error is not None:
            raise self._capabilities_error
        return self._capabilities


def run(client):
    app = types.SimpleNamespace(
        client_manager=types.SimpleNamespace(backup=client))
    cmd = misc.ShowVersion(app=app, app_args=None)
    parsed = cmd.get_parser("openstack backup version show").parse_args([])
    columns, values = cmd.take_action(parsed)
    return dict(zip(columns, values))


def test_version_reports_the_client_version_even_offline():
    row = run(FakeClient(healthz_error=ConnectionError("no route to host"),
                         capabilities_error=ConnectionError("no route to host")))
    assert row["client"] == ferryclient.__version__
    assert "no route to host" in row["server_error"]
    assert "no route to host" in row["capabilities_error"]
    assert "server" not in row


def test_version_reports_the_server_and_capabilities_when_reachable():
    row = run(FakeClient(
        healthz={"status": "ok", "version": "0.15.0", "mode": "local"},
        capabilities={"protection": True, "policies": 3}))
    assert row["client"] == ferryclient.__version__
    assert row["server"] == "0.15.0"
    assert row["server_mode"] == "local"
    assert "policies" in row["capabilities"]
