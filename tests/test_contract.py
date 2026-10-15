# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Every route this client calls must exist in the server's route contract.

This is the reason the client lives in the same repository as the service. The
contract file is generated from, and asserted against, the server's own router
and the Go CLI. Testing this client only against its own idea of the API is how
you ship a command that 404s on every call while its unit tests pass.
"""

import json
import pathlib
import re

import pytest

from ferryclient.v1 import client as v1_client

HERE = pathlib.Path(__file__).resolve().parent
CONTRACT = HERE / "route_contract.json"
if not CONTRACT.is_file():
    CONTRACT = HERE.parents[2] / "test" / "cli_contract.json"

# Paths are built with f-strings, so the literal source text is what gets
# compared. Turn every interpolation back into the contract's {id} placeholder.
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _contract_paths():
    if not CONTRACT.is_file():
        pytest.skip(f"route contract not found at {CONTRACT}")
    data = json.loads(CONTRACT.read_text())
    return {
        (route["method"].upper(), _PLACEHOLDER.sub("{id}", route["path"]))
        for route in data["routes"]
    }


def _client_calls():
    """Extract (method, path) pairs from the client's source.

    Reading the source rather than calling the methods keeps this test honest
    about routes that exist but are never exercised by another test.
    """
    source = pathlib.Path(v1_client.__file__).read_text()
    calls = set()

    # self.get("/v1/plans"), self.post(f"/v1/plans/{plan_id}", body), ...
    verb = re.compile(
        r"self\.(get|post|patch|delete)\(\s*f?\"(/v1/[^\"]*)\"")
    for method, path in verb.findall(source):
        calls.add((method.upper(), _PLACEHOLDER.sub("{id}", path)))

    # self.request("GET", "/v1/...")
    explicit = re.compile(
        r"self\.request\(\s*\"([A-Z]+)\",\s*f?\"(/v1/[^\"]*)\"")
    for method, path in explicit.findall(source):
        calls.add((method, _PLACEHOLDER.sub("{id}", path)))

    return calls


def test_every_client_route_is_in_the_contract():
    contract = _contract_paths()
    unknown = sorted(_client_calls() - contract)
    assert not unknown, (
        "these client calls are not in the server route contract, so they "
        "will 404: " + ", ".join(f"{m} {p}" for m, p in unknown))


def test_the_client_covers_the_manager_surface():
    """Report manager routes no command reaches yet.

    Not a failure: the contract also covers routes the Go CLI reaches by other
    means. It is here so that adding a route
    to the server shows up as a gap in this client rather than silently not
    existing.
    """
    if not CONTRACT.is_file():
        pytest.skip("route contract not found")
    data = json.loads(CONTRACT.read_text())
    manager = {
        (r["method"].upper(), _PLACEHOLDER.sub("{id}", r["path"]))
        for r in data["routes"] if r.get("surface") == "manager"
    }
    missing = sorted(manager - _client_calls())
    if missing:
        print("\nmanager routes this client does not implement yet:")
        for method, path in missing:
            print(f"  {method} {path}")
