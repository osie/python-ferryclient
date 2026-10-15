# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
from ferryclient.osc.v1 import base

COLUMNS = ("id", "scope", "target_id", "reason", "placed_by", "placed_at",
           "active")


class CreateLegalHold(base.FerryShowOne):
    """Hold a point, a plan or a project beyond its retention (operator).

    Expiry skips what a hold covers whatever its expiry date says, so "keep
    everything about this project until the lawyers say otherwise" is one call
    rather than a policy edit. The same hand lifts it.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--point", metavar="<point>",
                           help="hold one backup, by id")
        scope.add_argument("--plan", metavar="<plan>",
                           help="hold every backup of a plan, by name or id")
        scope.add_argument("--project", metavar="<project>",
                           help="hold every backup in a project, by id")
        parser.add_argument("--reason", metavar="<text>", required=True,
                            help="recorded on the hold and in the audit log")
        return parser

    def take_action(self, parsed_args):
        if parsed_args.point:
            scope, target = "point", parsed_args.point
        elif parsed_args.plan:
            scope = "plan"
            target = self.app_client.plan_find(parsed_args.plan)
        else:
            scope, target = "project", parsed_args.project
        body = {"scope": scope, "target_id": target,
                "reason": parsed_args.reason}
        return base.show(self.app_client.legal_hold_create(body), parsed_args)


class ListLegalHold(base.FerryLister):
    """List legal holds (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--scope", metavar="<scope>",
                            choices=["point", "plan", "project"],
                            help="point, plan or project")
        parser.add_argument("--target", metavar="<id>", dest="target_id",
                            help="holds on this point, plan or project")
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="holds whose blast radius is this project")
        parser.add_argument("--include-lifted", action="store_true",
                            help="holds already lifted as well; the default is "
                                 "only what is still held")
        parser.add_argument("--limit", type=int,
                            help="maximum holds returned")
        return parser

    def take_action(self, parsed_args):
        holds = self.app_client.legal_hold_list(
            hold_scope=parsed_args.scope,
            target_id=parsed_args.target_id,
            project_id=parsed_args.project_id,
            active="false" if parsed_args.include_lifted else None,
            limit=parsed_args.limit,
        )
        return COLUMNS, base.rows(holds, COLUMNS, parsed_args)


class DeleteLegalHold(base.FerryCommand):
    """Lift one or more legal holds (operator).

    Lifting does not delete anything: the points go back to expiring on the
    dates their policy gave them, which for a held point may be immediately.
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("hold", metavar="<hold>", nargs="+",
                            help="legal hold id")
        return parser

    def take_action(self, parsed_args):
        for hold in parsed_args.hold:
            self.app_client.legal_hold_delete(hold)
