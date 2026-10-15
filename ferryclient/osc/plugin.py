# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""python-openstackclient plugin hooks.

The contract implemented here is documented upstream at
https://docs.openstack.org/python-openstackclient/latest/contributor/plugins.html

``API_NAME`` does three jobs at once: it is the attribute the client manager
exposes (``client_manager.backup``), the entry point group commands are loaded
from (``openstack.backup.v1``), and the stem of the global options
(``--os-backup-api-version``). It matches the catalog service type so the two
never have to be explained separately.
"""

import logging
import os

from osc_lib import utils

LOG = logging.getLogger(__name__)

DEFAULT_API_VERSION = "1"

API_NAME = "backup"
API_VERSION_OPTION = "os_backup_api_version"
API_VERSIONS = {
    "1": "ferryclient.v1.client.Client",
}


def _endpoint_override(instance):
    """Find --os-backup-endpoint, whatever osc-lib called it today.

    Plugin-defined global options are merged into the cloud config by
    openstacksdk, which strips the ``os_`` prefix for keys it recognises and
    keeps the argparse dest for those it does not. Both spellings are tried,
    then the environment, which is the one path that cannot move.
    """
    options = getattr(instance, "_cli_options", None)
    config = getattr(options, "config", None) or {}
    for key in ("backup_endpoint", "os_backup_endpoint"):
        value = config.get(key)
        if value:
            return value
    return os.environ.get("OS_BACKUP_ENDPOINT") or None


def make_client(instance):
    """Return a client for the version osc-lib resolved."""
    version = instance._api_version[API_NAME]
    client_class = utils.get_client_class(API_NAME, version, API_VERSIONS)
    LOG.debug("instantiating backup client: %s", client_class)

    endpoint_override = _endpoint_override(instance)
    if endpoint_override:
        LOG.debug("bypassing the catalog: %s", endpoint_override)

    return client_class(
        session=instance.session,
        service_type=API_NAME,
        interface=instance.interface,
        region_name=instance.region_name,
        endpoint_override=endpoint_override,
    )


def build_option_parser(parser):
    """Add the global options to ``openstack``."""
    parser.add_argument(
        "--os-backup-api-version",
        metavar="<backup-api-version>",
        default=utils.env("OS_BACKUP_API_VERSION",
                          default=DEFAULT_API_VERSION),
        help="Backup API version, default=%s (Env: OS_BACKUP_API_VERSION)"
             % DEFAULT_API_VERSION,
    )
    # Bypasses the catalog. Two real uses: before the service has been
    # registered, and for a central multi-cloud manager, which is deliberately
    # in no cloud's catalog and cannot be reached any other way.
    parser.add_argument(
        "--os-backup-endpoint",
        metavar="<backup-endpoint>",
        default=utils.env("OS_BACKUP_ENDPOINT"),
        help="Backup API base URL, bypassing the service catalog "
             "(Env: OS_BACKUP_ENDPOINT)",
    )
    return parser
