# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""``openstack backup repository ...``: where backups are stored (operator)."""

from ferryclient.osc.v1 import base

COLUMNS = ("id", "name", "kind", "site_id", "local", "driver",
           "credentials_sealed", "warnings")

LOCK_FLAGS = ("--lock-mode", "--lock-min-retention", "--lock-max-retention",
              "--lock-changeable-until")


def _add_lock_options(parser):
    lock = parser.add_argument_group(
        "retention contract (the lock is the repository's)")
    lock.add_argument("--lock-mode", metavar="<mode>",
                      choices=["compliance", "governance"],
                      help="compliance: nothing deletes an object before its "
                           "retain-until date. governance: an operator with "
                           "bypass can, which a tenant is told in so many "
                           "words. Stating a mode is what makes this "
                           "repository locked")
    lock.add_argument("--lock-min-retention", metavar="<duration>",
                      help="the floor every object written here is held for, "
                           "e.g. 720h. A policy whose ladder is shorter than "
                           "this is refused, not clamped")
    lock.add_argument("--lock-max-retention", metavar="<duration>",
                      help="optional ceiling; omit or 0 for none")
    lock.add_argument("--lock-changeable-until", metavar="<RFC3339>",
                      help="how long the contract stays correctable. Default "
                           "on registration is three days out, because a "
                           "registration is where typos live; after it the "
                           "floor only increases and the block cannot be "
                           "removed")
    lock.add_argument("--soft-delete-grace", metavar="<duration>",
                      help="how long a point or plan a tenant deletes stays "
                           "reachable by an operator, e.g. 336h. 0 means "
                           "delete means delete")
    return lock


def _add_reach_options(parser):
    reach = parser.add_argument_group(
        "where it is readable (what a cross-site recovery reads)")
    reach.add_argument("--reachable-from-site", metavar="<site>",
                       action="append", dest="reachable_from_sites",
                       help="a site that can read this repository, by name or "
                            "id; repeat for each")
    reach.add_argument("--replica-of", metavar="<repository>",
                       help="the repository this one is a near-replica of, "
                            "by name or id")
    return reach


def _reach_body(parsed_args, client):
    body = {}
    if parsed_args.reachable_from_sites:
        body["reachable_from_sites"] = [
            client.site_find(site) for site in parsed_args.reachable_from_sites]
    if parsed_args.replica_of:
        body["replica_of"] = client.repository_find(parsed_args.replica_of)
    return body


def _lock_body(parsed_args):
    lock = {}
    for key, value in (
        ("mode", parsed_args.lock_mode),
        ("min_retention", parsed_args.lock_min_retention),
        ("max_retention", parsed_args.lock_max_retention),
        ("changeable_until", parsed_args.lock_changeable_until),
    ):
        if value:
            lock[key] = value
    return lock


class ListRepository(base.FerryLister):
    """List repositories."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--kind", metavar="<kind>",
                            choices=["chunk", "rbd"],
                            help="chunk or rbd")
        parser.add_argument("--limit", type=int)
        return parser

    def take_action(self, parsed_args):
        repositories = [
            r for r in self.app_client.repository_list(limit=parsed_args.limit)
            if not parsed_args.kind or r.get("kind") == parsed_args.kind
        ]
        return COLUMNS, base.rows(repositories, COLUMNS, parsed_args)


class ShowRepository(base.FerryShowOne):
    """Show a repository and any warnings."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository>",
                            help="repository name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(
            self.app_client.repository_show(parsed_args.repository), parsed_args)


class CreateRepository(base.FerryShowOne):
    """Register a repository.

    Two kinds, and they are not interchangeable. ``chunk`` is deduplicated,
    encrypted object storage, the thing that holds backups. ``rbd`` is a tier
    of Ceph images used to make recent restores fast; it stores no chunks and
    takes none of the object-storage options.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("name", metavar="<name>", help="repository name")
        parser.add_argument("--kind", metavar="<kind>", required=True,
                            choices=["chunk", "rbd"],
                            help="chunk or rbd")
        parser.add_argument("--site", metavar="<site>", dest="site_name",
                            required=True,
                            help="the locality domain movers share with it")

        chunk = parser.add_argument_group("chunk repositories")
        chunk.add_argument("--driver", metavar="<driver>",
                           help="s3, rados or posix")
        chunk.add_argument("--endpoint", metavar="<url>")
        chunk.add_argument("--bucket", metavar="<bucket>")
        chunk.add_argument("--region", metavar="<region>")
        # NOT --prefix. cliff's shell formatter registers a global --prefix on
        # every command, so adding one here makes argparse refuse to build the
        # parser at all: the command aborts with "Cannot resolve conflicting
        # option string" before it has looked at a single argument.
        chunk.add_argument("--object-prefix", metavar="<prefix>", dest="prefix",
                           help="key prefix inside the bucket, or the "
                                "filesystem root for the posix driver")
        chunk.add_argument("--chunk-size", metavar="<bytes>", type=int)
        chunk.add_argument("--access-key", metavar="<key>")
        chunk.add_argument("--secret-key", metavar="<key>",
                           help="sealed by the key manager before storage; "
                                "never readable back through the API")
        chunk.add_argument("--environment-credentials", action="store_true",
                           help="a repository at another site is listed from "
                                "here before it is saved; this skips that, "
                                "because this cloud's own environment supplies "
                                "the credential")

        rbd = parser.add_argument_group("rbd tiers")
        rbd.add_argument("--ceph-conf", metavar="<path>")
        rbd.add_argument("--ceph-user", metavar="<user>")
        rbd.add_argument("--pool", metavar="<pool>")
        rbd.add_argument("--namespace", metavar="<namespace>")

        _add_reach_options(parser)
        _add_lock_options(parser)
        return parser

    def take_action(self, parsed_args):
        if parsed_args.kind == "rbd":
            rejected = [
                name for name, value in (
                    ("--driver", parsed_args.driver),
                    ("--bucket", parsed_args.bucket),
                    ("--endpoint", parsed_args.endpoint),
                    ("--chunk-size", parsed_args.chunk_size),
                    ("--access-key", parsed_args.access_key),
                    ("--lock-mode", parsed_args.lock_mode),
                    ("--lock-min-retention", parsed_args.lock_min_retention),
                    ("--lock-max-retention", parsed_args.lock_max_retention),
                    ("--lock-changeable-until",
                     parsed_args.lock_changeable_until),
                ) if value
            ]
            if rejected:
                # Refused here rather than dropped silently: an rbd tier that
                # appears to have taken a bucket is a repository the operator
                # believes is object-backed and is not.
                raise SystemExit(
                    "an rbd tier stores Ceph images, not objects; "
                    f"{', '.join(rejected)} does not apply to --kind rbd")

        body = {
            "name": parsed_args.name,
            "kind": parsed_args.kind,
            "site_name": parsed_args.site_name,
        }
        for key, value in (
            ("driver", parsed_args.driver),
            ("endpoint", parsed_args.endpoint),
            ("bucket", parsed_args.bucket),
            ("region", parsed_args.region),
            ("prefix", parsed_args.prefix),
            ("chunk_size", parsed_args.chunk_size),
            ("ceph_conf", parsed_args.ceph_conf),
            ("ceph_user", parsed_args.ceph_user),
            ("pool", parsed_args.pool),
            ("namespace", parsed_args.namespace),
            ("access_key", parsed_args.access_key),
            ("secret_key", parsed_args.secret_key),
        ):
            if value:
                body[key] = value
        body.update(_reach_body(parsed_args, self.app_client))
        lock = _lock_body(parsed_args)
        if lock:
            body["object_lock"] = lock
        if parsed_args.soft_delete_grace:
            body["soft_delete_grace"] = parsed_args.soft_delete_grace
        if parsed_args.environment_credentials:
            body["environment_credentials"] = True
        return base.show(self.app_client.repository_register(body), parsed_args)


class SetRepository(base.FerryCommand):
    """Update a repository, including its retention contract.

    Only the fields that can change without stranding data: an endpoint that
    moved, a rotated credential. What a repository IS (its driver, bucket and
    chunk size) describes where every object already written lives, so those
    are fixed at registration.

    The contract is the exception that has its own rules. Inside the grace
    anything about it may change, because a registration is where typos live.
    After the grace the floor only increases, the mode is fixed and the block
    cannot be removed, and each refusal names the grace date that has passed.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository>",
                            help="repository name or id")
        parser.add_argument("--endpoint", metavar="<url>")
        parser.add_argument("--region", metavar="<region>")
        parser.add_argument("--access-key", metavar="<key>")
        parser.add_argument("--secret-key", metavar="<key>")
        parser.add_argument("--environment-credentials", action="store_true",
                            help="do not list a repository at another site "
                                 "with new keys, endpoint or region before "
                                 "saving them")
        reach = _add_reach_options(parser)
        reach.add_argument("--clear-reachable-from-sites", action="store_true",
                           help="no other site can read this repository. "
                                "--reachable-from-site replaces the whole list")
        reach.add_argument("--clear-replica-of", action="store_true",
                           help="this repository is no longer a replica of "
                                "another")
        lock = _add_lock_options(parser)
        lock.add_argument("--clear-object-lock", action="store_true",
                          help="remove the retention contract entirely, which "
                               "only the grace permits")
        return parser

    def take_action(self, parsed_args):
        body = {}
        for key, value in (
            ("endpoint", parsed_args.endpoint),
            ("region", parsed_args.region),
            ("access_key", parsed_args.access_key),
            ("secret_key", parsed_args.secret_key),
            ("soft_delete_grace", parsed_args.soft_delete_grace),
        ):
            if value:
                body[key] = value
        if parsed_args.clear_reachable_from_sites and \
                parsed_args.reachable_from_sites:
            raise SystemExit(
                "--clear-reachable-from-sites empties the list; do not name "
                "a --reachable-from-site with it")
        if parsed_args.clear_replica_of and parsed_args.replica_of:
            raise SystemExit(
                "--clear-replica-of removes the replica relationship; do not "
                "name a --replica-of with it")
        if parsed_args.clear_reachable_from_sites:
            body["reachable_from_sites"] = []
        if parsed_args.clear_replica_of:
            body["replica_of"] = ""
        body.update(_reach_body(parsed_args, self.app_client))
        lock = _lock_body(parsed_args)
        if lock and parsed_args.clear_object_lock:
            raise SystemExit(
                "--clear-object-lock removes the contract; do not state "
                f"{', '.join(LOCK_FLAGS)} with it")
        if lock:
            body["object_lock"] = lock
        if parsed_args.clear_object_lock:
            body["clear_object_lock"] = True
        if not body:
            raise SystemExit("nothing to change: pass at least one option")
        if parsed_args.environment_credentials:
            body["environment_credentials"] = True
        self.app_client.repository_update(parsed_args.repository, body)


class DeleteRepository(base.FerryCommand):
    """Delete one or more repositories.

    A repository still holding an object under lock is refused: the contract
    outlives the registration that stated it.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository>", nargs="+")
        return parser

    def take_action(self, parsed_args):
        for repository in parsed_args.repository:
            self.app_client.repository_delete(repository)


class ShowRepositoryUsage(base.FerryShowOne):
    """Show what a repository is actually storing (operator).

    Repository-global: physical bytes, the cross-tenant dedup margin, sweep
    state and a row per tenant. None of it is scoped to one project, which is
    why it needs a system-scoped token. ``openstack backup usage`` is the
    tenant-facing question.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository>",
                            help="repository name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(
            self.app_client.repository_usage(parsed_args.repository), parsed_args)
