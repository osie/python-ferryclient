# python-ferryclient

The `openstack backup` commands for [Ferry](https://osie.io/docs/ferry/), the
backup, restore and disaster recovery service for OpenStack.

## Install

```sh
pip install python-openstackclient python-ferryclient
```

The commands use the credentials you already use with `openstack` (a
`clouds.yaml` entry or `OS_*` variables) and find Ferry in your cloud's service
catalog. There is nothing else to configure.

## Quick start

Protect a server, back it up and restore it:

```sh
openstack backup policy list

openstack backup plan create web --resource-kind instance \
  --resource <server-id> --policy <policy>

openstack backup point create --plan web --wait
openstack backup point list --plan web

openstack backup restore create --point <point-id> --mode instance \
  --name web-restored --wait
```

A policy is a service level your cloud operator offers, with its own schedule
and retention. `policy list` shows the ones your project can choose.

## Common tasks

| Task | Command |
|---|---|
| Protect a server or a volume | `openstack backup plan create` |
| Freeze the guest's filesystems before each backup | `plan create --consistency filesystem` |
| Take a backup now | `openstack backup point create --plan <plan>` |
| Restore as a new server or volume | `openstack backup restore create --point <point-id> --mode instance` (or `volume`) |
| Recover files from a backup | `openstack backup attachment create --point <point-id> --instance <server-id>` |
| See why a resource is not protected | `openstack backup plan refusal list <plan>` |
| Follow the work behind a backup or a restore | `openstack backup job list` |

## For operators

| Task | Command |
|---|---|
| Offer a service level | `openstack backup policy create`, then `policy assign` |
| Register backup storage | `openstack backup repository create` |
| Keep a second copy of every backup | `openstack backup policy set <policy> --copy-repository <repository>` |
| Find what is not protected | `openstack backup coverage show` |
| Fail a group of servers over to another region | `openstack backup group create`, then `group release` and `group recover` |

## Documentation

- [Ferry documentation](https://osie.io/docs/ferry/)
- [CLI reference](https://osie.io/docs/ferry/cli-reference/): every command and option
- [Deploying Ferry](https://github.com/osie/ferry-backup): manifests for
  kolla-ansible, Helm and Juju

`openstack backup <command> --help` prints the same reference offline.

## Options

| Option | Environment variable | Meaning |
|---|---|---|
| `--os-backup-endpoint` | `OS_BACKUP_ENDPOINT` | Ferry's URL, instead of the one in the service catalog |
| `--os-backup-api-version` | `OS_BACKUP_API_VERSION` | API version, `1` by default |

When a command fails, it prints the error's code and a request id. Give the
request id to your cloud operator, who can find the request in Ferry's logs.

## Contributing and license

See [CONTRIBUTING.md](https://github.com/osie/python-ferryclient/blob/main/CONTRIBUTING.md).
Security issues go through
[SECURITY.md](https://github.com/osie/python-ferryclient/blob/main/SECURITY.md).
Licensed under the [Apache License 2.0](https://github.com/osie/python-ferryclient/blob/main/LICENSE).
