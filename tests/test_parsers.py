# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Every command must be able to build its own parser.

An option that collides with one cliff already defines aborts argparse while it
is *constructing* the parser, so the command fails before it has looked at a
single argument and no amount of testing its logic catches it. `backup
repository create` shipped in exactly that state: cliff's shell formatter
registers a global --prefix, so the command answered

    argument <prefix>: Cannot resolve conflicting option string, all names conflict

to everything, including --help.

This walks the entry points and builds each parser the way cliff does.
"""

import argparse

import pytest
from cliff.command import Command

try:  # pragma: no cover - the metadata layout differs across Pythons
    from importlib.metadata import entry_points
except ImportError:  # pragma: no cover
    from importlib_metadata import entry_points


def ferry_commands():
    """Yield (name, class) for every command this client registers."""
    eps = entry_points()
    selected = eps.select(group="openstack.backup.v1") if hasattr(eps, "select") \
        else eps.get("openstack.backup.v1", [])
    for ep in selected:
        yield ep.name, ep.load()


COMMANDS = list(ferry_commands())


def test_the_client_registers_commands():
    # A guard on the guard: an empty entry-point group would make every
    # assertion below vacuous, and the package not being installed looks
    # exactly like that.
    assert COMMANDS, "no openstack.backup.v1 entry points found; is the client installed?"


@pytest.mark.parametrize("name,cls", COMMANDS, ids=[n for n, _ in COMMANDS])
def test_parser_builds(name, cls):
    """The parser must construct, with cliff's own global options present.

    Building it bare would miss the whole class of defect: the collision only
    happens once the formatter options are on the parser too.
    """
    cmd = cls(app=None, app_args=None)
    parser = cmd.get_parser("openstack " + name)
    assert isinstance(parser, argparse.ArgumentParser)


@pytest.mark.parametrize("name,cls", COMMANDS, ids=[n for n, _ in COMMANDS])
def test_help_renders(name, cls):
    """--help must render. It is the first thing an operator runs."""
    cmd = cls(app=None, app_args=None)
    text = cmd.get_parser("openstack " + name).format_help()
    assert text
