# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
from ferryclient.osc.v1 import base

COLUMNS = ("id", "name", "immutable", "sentence")


class ListVault(base.FerryLister):
    """List the vaults a manual backup may be kept in.

    A tenant is served the vaults offered to their project; an operator is
    served every vault, with the repository behind it.
    """

    def take_action(self, parsed_args):
        return COLUMNS, base.rows(self.app_client.vault_list(), COLUMNS,
                                  parsed_args)


class ShowVault(base.FerryShowOne):
    """Show a vault and the terms of a manual backup kept there."""

    def get_parser(self, prog_name):
        parser = super().get_parser(prog_name)
        parser.add_argument("vault", metavar="<vault>",
                            help="vault name or id")
        return parser

    def take_action(self, parsed_args):
        return base.show(self.app_client.vault_show(parsed_args.vault),
                         parsed_args)
