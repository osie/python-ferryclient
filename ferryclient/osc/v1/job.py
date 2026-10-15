# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""``openstack backup job ...``: the work behind a point or a restore."""

from ferryclient.osc.v1 import base

COLUMNS = ("id", "kind", "state", "point_id", "mover_id", "attempts",
           "created_at", "updated_at")


class ListJob(base.FerryLister):
    """List jobs."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("--state", metavar="<state>",
                            help="only jobs in this state")
        parser.add_argument("--kind", metavar="<kind>",
                            help="backup, restore, verify, gc or tiering")
        parser.add_argument("--point", metavar="<point>", dest="point_id")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--project", metavar="<project>",
                            dest="project_id",
                            help="another project's jobs (operator; needs a "
                                 "system-scoped token)")
        return parser

    def take_action(self, parsed_args):
        jobs = self.app_client.job_list(
            state=parsed_args.state,
            kind=parsed_args.kind,
            point_id=parsed_args.point_id,
            limit=parsed_args.limit,
            project_id=parsed_args.project_id,
        )
        return COLUMNS, base.rows(jobs, COLUMNS, parsed_args)


class ShowJob(base.FerryShowOne):
    """Show a job, with its phase timings when it has produced any.

    The timings are the useful part: total duration says little, while the
    breakdown distinguishes "add movers" from "add bandwidth" from "add CPU".
    """

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("job", metavar="<job>", help="job id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.job_show(parsed_args.job), parsed_args)


class CancelJob(base.FerryCommand):
    """Cancel one or more jobs."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("job", metavar="<job>", nargs="+", help="job id")
        return parser

    def take_action(self, parsed_args):
        for job in parsed_args.job:
            self.app_client.job_cancel(job)
