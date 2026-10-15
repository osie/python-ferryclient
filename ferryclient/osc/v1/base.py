# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Shared helpers for the ``openstack backup ...`` commands."""

import json
import time

from osc_lib.command import command

from ferryclient import exceptions

TERMINAL_JOB_STATES = frozenset({"succeeded", "dead_letter", "cancelled"})


def wait_for_job(app_client, job_id, interval=3):
    if not job_id:
        return None
    while True:
        try:
            job = app_client.job_show(job_id)
        except exceptions.HTTPError as exc:
            if exc.status_code == 429 or exc.status_code >= 500:
                time.sleep(interval)
                continue
            raise
        state = job.get("state")
        exhausted = (state == "failed" and
                    job.get("attempts", 0) >= job.get("max_attempts", 0))
        if state in TERMINAL_JOB_STATES or exhausted:
            if state != "succeeded":
                detail = job.get("error") or state
                raise SystemExit(f"job {job_id} {state}: {detail}")
            return job
        time.sleep(interval)


class FerryCommand(command.Command):
    """Base that exposes the Ferry client the way osc-lib wires it."""

    @property
    def app_client(self):
        return self.app.client_manager.backup


class FerryLister(command.Lister, FerryCommand):
    pass


class FerryShowOne(command.ShowOne, FerryCommand):
    pass


# json and yaml can carry nested structures natively; the tabular formatters
# cannot and need a string.
STRUCTURED_FORMATS = frozenset({"json", "yaml"})


def structured(parsed_args):
    """Whether the chosen formatter can represent nested data itself."""
    return getattr(parsed_args, "formatter", None) in STRUCTURED_FORMATS


def flatten(value, raw=False):
    """Render a value for a table cell.

    Ferry returns nested objects on several views: a plan's intent and
    retention, a point's metrics, a restore's created resources. A dict
    rendered by ``str()`` is unreadable, so for the tabular formatters anything
    structured becomes compact JSON. Scalars are left alone: quoting them would
    break ``-f value`` piping, which is the whole point of that format.

    Under ``-f json`` and ``-f yaml`` the value is passed through untouched.
    Stringifying it there would emit JSON inside a JSON string, so
    ``| jq '.[].capabilities[]'`` would fail on what looks like an array and is
    really text.
    """
    if raw:
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def rows(items, columns, parsed_args=None):
    """Project a list of dicts onto a fixed column tuple.

    A missing key becomes an empty cell rather than an error: Ferry omits
    fields that do not apply, such as ``job_id`` on a restore that has not been
    dispatched or ``locked_until`` on a backup nothing holds, and a client that
    raised on those would be unusable exactly when it is most needed.
    """
    raw = structured(parsed_args)
    return [tuple(flatten(item.get(c), raw) for c in columns)
            for item in items]


def show(data, parsed_args=None):
    """Return (columns, values) for ShowOne over an arbitrary object.

    Every key is shown rather than a curated subset, because Ferry's views
    carry fields that only appear in interesting cases (a plan's refusals, a
    point's downgrade reason, a repository's warnings), and hiding them would
    hide precisely the thing the operator ran the command to find.
    """
    raw = structured(parsed_args)
    if not isinstance(data, dict):
        return ("value",), (flatten(data, raw),)
    keys = sorted(data)
    return tuple(keys), tuple(flatten(data[k], raw) for k in keys)


def add_scope_argument(parser):
    """Add ``--scope``, which only ever narrows.

    An operator token is served the operator rendering of a point: figures
    computed across the whole repository rather than within one project. There
    is no flag to widen (``tenant`` is the only value), because a parameter
    that could widen would be the authorisation.
    """
    parser.add_argument("--scope", metavar="<scope>", choices=["tenant"],
                        help="render as a tenant sees it, even with an "
                             "operator token: repository-global figures are "
                             "withheld")
    return parser


def parse_properties(pairs, flag="--property"):
    """Turn repeated ``--property k=v`` into a dict."""
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"{flag} expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def read_secret(inline, path):
    """Read a passphrase from a flag or a file, with ``-`` meaning stdin.

    A passphrase on the command line lands in the shell history and in the
    process table of every other user on the box, so the file form exists and
    is what the help text steers people towards. The inline form is kept
    because scripts in a CI runner have nowhere better to put it.
    """
    if path:
        if path == "-":
            import sys
            return sys.stdin.readline().rstrip("\n")
        with open(path, "r", encoding="utf-8") as handle:
            return handle.readline().rstrip("\n")
    return inline
