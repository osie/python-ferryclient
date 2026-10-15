import pytest

from ferryclient import exceptions
from ferryclient.v1 import client as v1_client


def _client_capturing_paths():
    client = object.__new__(v1_client.Client)
    calls = []

    def fake_request(method, path, body=None, params=None):
        calls.append((method, path))
        return {}

    client.request = fake_request
    return client, calls


@pytest.mark.parametrize("call,arg,want", [
    ("point_show", "../jobs", "/v1/points/..%2Fjobs"),
    ("point_delete", "../jobs", "/v1/points/..%2Fjobs"),
    ("job_show", "../repositories", "/v1/jobs/..%2Frepositories"),
    ("restore_show", "../plans", "/v1/restores/..%2Fplans"),
    ("binding_show", "../jobs", "/v1/recovery-bindings/..%2Fjobs"),
    ("standby_show", "../jobs", "/v1/standbys/..%2Fjobs"),
    ("attachment_delete", "../jobs", "/v1/attachments/..%2Fjobs"),
])
def test_single_id_commands_escape_a_traversal_id(call, arg, want):
    client, calls = _client_capturing_paths()
    getattr(client, call)(arg)
    assert calls[-1][1] == want


def test_group_show_passes_a_uuid_through_without_a_lookup():
    client, calls = _client_capturing_paths()
    group_id = "11111111-1111-4111-8111-111111111111"
    client.group_show(group_id)
    assert calls == [("GET", f"/v1/protection-groups/{group_id}")]


def test_group_show_refuses_an_unresolvable_reference():
    client, calls = _client_capturing_paths()
    with pytest.raises(exceptions.NotFound):
        client.group_show("../jobs")
    assert calls == [("GET", "/v1/protection-groups")]


def test_group_run_escapes_the_run_id():
    client, calls = _client_capturing_paths()
    group_id = "11111111-1111-4111-8111-111111111111"
    client.group_run(group_id, "../../../jobs")
    assert calls[-1][1] == (
        f"/v1/protection-groups/{group_id}/runs/..%2F..%2F..%2Fjobs")


def test_run_cancel_escapes_the_run_id():
    client, calls = _client_capturing_paths()
    group_id = "11111111-1111-4111-8111-111111111111"
    client.run_cancel(group_id, "../jobs")
    assert calls[-1][1] == (
        f"/v1/protection-groups/{group_id}/runs/..%2Fjobs/cancel")


def test_key_fingerprints_escapes_the_repository():
    client, calls = _client_capturing_paths()
    client.key_fingerprints("../jobs")
    assert calls[-1][1] == "/v1/repositories/..%2Fjobs/domain-keys"


def test_an_empty_id_is_refused_before_any_request():
    client, calls = _client_capturing_paths()
    with pytest.raises(exceptions.BadRequest):
        client.point_show("")
    assert calls == []


def test_a_query_param_is_not_path_escaped():
    client, calls = _client_capturing_paths()
    client.point_document("p1", repository="../x")
    assert calls[-1][1] == "/v1/points/p1/document"
