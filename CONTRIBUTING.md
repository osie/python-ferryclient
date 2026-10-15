# Contributing

Thank you for helping. Bug reports, fixes and clearer help text are all welcome.

## How this repository is maintained

The client is developed alongside Ferry itself and exported here with each Ferry
release, so each release of the client carries the version of the Ferry release
it was built with. A pull
request is reviewed here as usual; once accepted, it is applied to the
development tree and arrives back in this repository with the next export, under
your authorship. The pull request is closed with a link to the release that
carries it.

## Reporting a bug

Open an issue. The most useful things to include:

- the output of `openstack backup version show`, which prints the client's
  version and, when the service is reachable, the server's;
- the command you ran, what happened, and what you expected;
- the error as printed, with its code and request id. The request id is what
  lets an operator find the request in the service's log.

Security issues go through [SECURITY.md](SECURITY.md), never a public issue.

## Making a change

You need Python 3.9 or later.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
python -m pytest
```

Some things to keep in mind:

- **Help text is documentation.** The
  [CLI reference](https://osie.io/docs/ferry/cli-reference/) is generated from
  the commands' own parsers, so a command's description and its options' help
  are what readers see there. Write them for the person running the command.
- **A new command is an entry point.** Add it to `pyproject.toml` under
  `openstack.backup.v1`, named `backup_<noun>_<verb>`.
- **No credentials, hostnames or addresses from a real cloud**, in code,
  examples or tests. Use `example.com`, the documentation address ranges and
  obviously fake values.

## Commits and sign-off

Write commit messages that say what changed and why. Sign off each commit to
certify the [Developer Certificate of Origin](https://developercertificate.org/):

```sh
git commit -s
```

By contributing you agree that your contribution is licensed under the
[Apache License, Version 2.0](LICENSE).
