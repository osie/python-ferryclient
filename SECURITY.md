# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately
through GitHub: open the repository's **Security** tab and choose **Report a
vulnerability**, or go to <https://github.com/osie/python-ferryclient/security/advisories/new>.

Include the version (`openstack backup version show`), what is affected and how
to reproduce it. We aim to acknowledge reports within three working days and
keep you informed until a fix is released. We credit reporters in the advisory
unless you ask us not to.

Vulnerabilities in Ferry itself or in its deployment manifests are welcome
through the same channel; we route them to the right place.

## Supported versions

Fixes are made in the latest release. Upgrade to it to receive them.

## What the client is responsible for

The client runs with the user's OpenStack credentials and handles the
passphrases that protect exported encryption keys, so these are in scope:

- a token, credential or passphrase written to output, a log or a file;
- a request sent to an endpoint other than the one the catalog or
  `--os-backup-endpoint` names;
- a passphrase read from somewhere other than the file, standard input or
  option it was given through.
