from ferryclient.osc.v1 import base

COLUMNS = ("id", "name", "project_id", "network_cidrs", "strict",
           "jump_host", "max_duration", "permitted_checks",
           "isolation_canaries")
CHECKS = ("tcp", "http")


def _duration(nanoseconds):
    if isinstance(nanoseconds, bool) or not isinstance(nanoseconds, int):
        return nanoseconds
    hours, rest = divmod(nanoseconds // 1_000_000_000, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}h{minutes}m{seconds}s"


def _view(policy, parsed_args):
    if not isinstance(policy, dict) or base.structured(parsed_args):
        return policy
    return dict(policy, max_duration=_duration(policy.get("max_duration")))


def _add_fields(parser, create):
    parser.add_argument("--project", metavar="<project>", dest="project_id",
                        required=create,
                        help="operator project every bubble under this "
                             "policy is built in; never a tenant's")
    parser.add_argument("--network-cidr", metavar="<cidr>", action="append",
                        dest="network_cidrs", required=create,
                        help="range a bubble's networks are allocated from "
                             "(repeatable; given on set, replaces the list)")
    strict = parser.add_mutually_exclusive_group()
    strict.add_argument("--strict", action="store_const", const=True,
                        dest="strict",
                        help="forbid any router, external gateway or "
                             "floating IP on a bubble's networks (the "
                             "default for a new policy)")
    strict.add_argument("--no-strict", action="store_const", const=False,
                        dest="strict",
                        help="allow routers and floating IPs on a bubble's "
                             "networks")
    jump = parser.add_mutually_exclusive_group()
    jump.add_argument("--jump-host", action="store_const", const=True,
                      dest="jump_host",
                      help="build a jump host in each bubble, which runs "
                           "the health checks and tries the canaries (the "
                           "default for a new policy)")
    jump.add_argument("--no-jump-host", action="store_const", const=False,
                      dest="jump_host",
                      help="build no jump host")
    parser.add_argument("--jump-host-image", metavar="<image>",
                        help="image the jump host boots; the service's "
                             "probe image when not set")
    parser.add_argument("--jump-host-flavor", metavar="<flavor>",
                        help="flavor of the jump host; the service's probe "
                             "flavor when not set")
    parser.add_argument("--max-duration", metavar="<duration>",
                        help="how long a bubble may stand before it is torn "
                             "down, from 10m to 168h, e.g. 2h; 1h for a new "
                             "policy")
    parser.add_argument("--permitted-check", metavar="<check>",
                        action="append", dest="permitted_checks",
                        choices=CHECKS,
                        help="health check a test may run, tcp or http "
                             "(repeatable; given on set, replaces the list)")
    canaries = parser.add_mutually_exclusive_group()
    canaries.add_argument("--isolation-canary", metavar="<host:port>",
                          action="append", dest="isolation_canaries",
                          help="address a bubble must not reach; the jump "
                               "host tries it before any member boots "
                               "(repeatable; given on set, replaces the "
                               "list)")
    if not create:
        canaries.add_argument("--no-isolation-canary", action="store_const",
                              const=[], dest="isolation_canaries",
                              help="clear the isolation canaries")


def _body(parsed_args):
    body = {}
    for key in ("name", "project_id", "network_cidrs", "strict", "jump_host",
                "jump_host_image", "jump_host_flavor", "max_duration",
                "permitted_checks", "isolation_canaries"):
        value = getattr(parsed_args, key, None)
        if value is not None:
            body[key] = value
    return body


class ListBubblePolicy(base.FerryLister):
    """List the bubble policies a test failover can run under."""

    def take_action(self, parsed_args):
        policies = [_view(p, parsed_args)
                    for p in self.app_client.bubble_policy_list()]
        return COLUMNS, base.rows(policies, COLUMNS, parsed_args)


class CreateBubblePolicy(base.FerryShowOne):
    """Register a bubble policy: how a test's isolated bubble is built (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("name", metavar="<name>",
                            help="policy name, unique on this cloud")
        _add_fields(parser, create=True)
        return parser

    def take_action(self, parsed_args):
        return base.show(_view(self.app_client.bubble_policy_create(
            _body(parsed_args)), parsed_args), parsed_args)


class SetBubblePolicy(base.FerryShowOne):
    """Change a bubble policy; only the options given change (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("bubble_policy", metavar="<bubble-policy>",
                            help="bubble policy name or id")
        parser.add_argument("--name", metavar="<name>", help="new name")
        _add_fields(parser, create=False)
        return parser

    def take_action(self, parsed_args):
        body = _body(parsed_args)
        if not body:
            raise SystemExit("nothing to change; give at least one option")
        return base.show(_view(self.app_client.bubble_policy_update(
            parsed_args.bubble_policy, body), parsed_args), parsed_args)


class DeleteBubblePolicy(base.FerryCommand):
    """Delete bubble policies no registration names and no test ran under (operator)."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("bubble_policy", metavar="<bubble-policy>",
                            nargs="+", help="bubble policy name or id")
        return parser

    def take_action(self, parsed_args):
        for policy in parsed_args.bubble_policy:
            self.app_client.bubble_policy_delete(policy)
