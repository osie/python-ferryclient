# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Resources, movers, usage, retention, domain keys and the client version."""

import ferryclient
from ferryclient.osc.v1 import base

RESOURCE_COLUMNS = ("id", "kind", "name", "protectable", "reason",
                    "size_bytes")
MOVER_COLUMNS = ("id", "site_id", "version", "alive", "running_jobs",
                 "max_parallel", "capabilities", "last_seen_at")
SITE_COLUMNS = ("id", "name", "local")
KEY_COLUMNS = ("domain", "fingerprint", "unreadable")


class ListResource(base.FerryLister):
    """List what can be protected, and what cannot.

    ``protectable`` false is the useful half: it comes with the reason, so a
    resource that will never be backed up says so here rather than by
    producing no points and no explanation.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--kind", metavar="<kind>",
                            help="volume, instance or bucket")
        parser.add_argument("--protectable", action="store_true", default=None,
                            help="only resources that can be protected")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's resources (operator; needs a "
                                 "system-scoped token)")
        return parser

    def take_action(self, parsed_args):
        resources = self.app_client.resource_list(
            kind=parsed_args.kind,
            protectable=parsed_args.protectable,
            limit=parsed_args.limit,
            project_id=parsed_args.project_id,
        )
        rows = [dict(r, reason=(r.get("refusal") or {}).get("reason"))
                for r in resources]
        return RESOURCE_COLUMNS, base.rows(rows, RESOURCE_COLUMNS, parsed_args)


class ListMover(base.FerryLister):
    """List data movers (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--limit", type=int)
        return parser

    def take_action(self, parsed_args):
        movers = self.app_client.mover_list(limit=parsed_args.limit)
        return MOVER_COLUMNS, base.rows(movers, MOVER_COLUMNS, parsed_args)


class ListSite(base.FerryLister):
    """List the sites a policy recovers at and a repository is reachable from.

    Every option that takes a site takes its name or its id; ``local`` marks
    this cloud's own.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--limit", type=int)
        return parser

    def take_action(self, parsed_args):
        sites = self.app_client.site_list(limit=parsed_args.limit)
        return SITE_COLUMNS, base.rows(sites, SITE_COLUMNS, parsed_args)


class ShowUsage(base.FerryShowOne):
    """Show what this project is storing.

    Anything the service cannot currently account for is reported as
    unavailable with a reason rather than as a zero, because a zero that means
    "not measured yet" is indistinguishable from a zero that means "nothing".
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's usage (operator; needs a "
                                 "system-scoped token)")
        base.add_scope_argument(parser)
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.usage(
            project_id=parsed_args.project_id,
            scope=parsed_args.scope), parsed_args)


class SimulateRetention(base.FerryShowOne):
    """Show what a policy edit would keep, expire, and fail to shorten.

    The subject is a POLICY, because the ladder is the operator's. State a
    candidate ladder to ask what changing it would do; state none to ask what
    tonight's expiry will do under the policy as it stands.

    The answer names what a lock still holds, which is what cannot be shortened
    at all however the ladder reads, and for an operator token it also carries
    the bytes the deletion would free. A project token gets the verdicts only:
    how much space comes back depends on what else the repository holds, which
    is not a tenant's question.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--policy", metavar="<policy>", required=True,
                            help="policy to simulate, by name or id")
        parser.add_argument("--plan", metavar="<plan>",
                            help="narrow the answer to one plan under the "
                                 "policy; the default is every plan under it")
        parser.add_argument("--keep-all", metavar="<duration>",
                            help="candidate floor every point lives for, "
                                 "e.g. 48h")
        parser.add_argument("--keep-daily", metavar="<count>", type=int)
        parser.add_argument("--keep-weekly", metavar="<count>", type=int)
        parser.add_argument("--keep-monthly", metavar="<count>", type=int)
        parser.add_argument("--keep-yearly", metavar="<count>", type=int)
        parser.add_argument("--anchor", metavar="<key=value>", action="append",
                            help="candidate period grid, repeatable: "
                                 "week=sunday, month=first|last, year=january")
        return parser

    def take_action(self, parsed_args):
        body = {"policy_id": self.app_client.policy_find(parsed_args.policy)}
        if parsed_args.plan:
            body["plan_id"] = self.app_client.plan_find(parsed_args.plan)
        keep = {}
        if parsed_args.keep_all:
            keep["all"] = parsed_args.keep_all
        for tier in ("daily", "weekly", "monthly", "yearly"):
            value = getattr(parsed_args, "keep_" + tier)
            if value is not None:
                keep[tier] = value
        anchors = base.parse_properties(parsed_args.anchor, "--anchor")
        if anchors:
            keep["anchors"] = anchors
        if keep:
            body["spec"] = {"keep": keep}
        return base.show(
            self.app_client.retention_simulate(body), parsed_args)


class ShowCoverage(base.FerryShowOne):
    """Show what this cloud is not protecting (operator).

    Governance is coverage, not just policy: resources under no plan, plans
    paused and for how long, plans on a deprecated policy, plans whose policy
    names storage it cannot use, ticks missed inside the reporting window,
    points the copy tier has not reached, points no lock holds, and policies
    below the operator's own floor. Each answer names the plans it is about, so
    the report is a worklist rather than a score.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="one project instead of every project in the "
                                 "cloud")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.coverage(
            project_id=parsed_args.project_id), parsed_args)


class ListDomainKey(base.FerryLister):
    """Show which dedup domains this cloud can decrypt (operator).

    A fingerprint is a MAC of the key, so comparing or publishing one reveals
    nothing about it. Run this on both clouds before a cross-cloud restore
    rather than during one.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--repository", metavar="<repository>",
                            required=True, help="repository name or id")
        parser.add_argument("--domain", metavar="<domain>",
                            help="show only this dedup domain")
        return parser

    def take_action(self, parsed_args):
        keys = [
            k for k in self.app_client.key_fingerprints(parsed_args.repository)
            if not parsed_args.domain or k.get("domain") == parsed_args.domain
        ]
        return KEY_COLUMNS, base.rows(keys, KEY_COLUMNS, parsed_args)


class ExportDomainKey(base.FerryShowOne):
    """Export a dedup domain's key for another cloud (operator).

    The envelope holds no plaintext key, so it is safe to move through a
    ticket or an object store, but the passphrase must travel separately, or
    the two together are simply the key. Every export is audited.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--repository", metavar="<repository>",
                            required=True, help="repository name or id")
        parser.add_argument("--domain", metavar="<domain>", required=True)
        parser.add_argument("--passphrase-file", metavar="<path>",
                            help="file holding the passphrase, or - for stdin")
        parser.add_argument("--passphrase", metavar="<passphrase>",
                            help="passphrase inline; prefer "
                                 "--passphrase-file, which keeps it out of "
                                 "the shell history and the process table")
        return parser

    def take_action(self, parsed_args):
        passphrase = base.read_secret(parsed_args.passphrase,
                                      parsed_args.passphrase_file)
        if not passphrase:
            raise SystemExit(
                "a passphrase is required: --passphrase-file or --passphrase")
        return base.show(self.app_client.key_export(
            parsed_args.repository,
            {"domain": parsed_args.domain, "passphrase": passphrase}), parsed_args)


class ImportDomainKey(base.FerryShowOne):
    """Import a dedup domain's key exported from another cloud (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--repository", metavar="<repository>",
                            required=True, help="repository name or id")
        parser.add_argument("--domain", metavar="<domain>", required=True)
        parser.add_argument("--envelope-file", metavar="<path>",
                            required=True,
                            help="the exported envelope, as JSON")
        parser.add_argument("--passphrase-file", metavar="<path>",
                            help="file holding the passphrase, or - for stdin")
        parser.add_argument("--passphrase", metavar="<passphrase>")
        return parser

    def take_action(self, parsed_args):
        import json

        passphrase = base.read_secret(parsed_args.passphrase,
                                      parsed_args.passphrase_file)
        if not passphrase:
            raise SystemExit(
                "a passphrase is required: --passphrase-file or --passphrase")
        with open(parsed_args.envelope_file, "r", encoding="utf-8") as handle:
            envelope = json.load(handle)
        return base.show(self.app_client.key_import(
            parsed_args.repository,
            {"domain": parsed_args.domain, "passphrase": passphrase,
             "envelope": envelope}), parsed_args)


class ShowVersion(base.FerryShowOne):
    """Show this client's version, and the cloud's if reachable."""

    def take_action(self, parsed_args):
        data = {"client": ferryclient.__version__}
        try:
            health = self.app_client.healthz()
        except Exception as exc:
            data["server_error"] = str(exc)
        else:
            if isinstance(health, dict):
                if health.get("version"):
                    data["server"] = health["version"]
                if health.get("mode"):
                    data["server_mode"] = health["mode"]
        try:
            data["capabilities"] = self.app_client.capabilities()
        except Exception as exc:
            data["capabilities_error"] = str(exc)
        return base.show(data, parsed_args)
