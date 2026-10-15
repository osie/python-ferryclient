==================
python-ferryclient
==================

An OpenStackClient plugin for Ferry, a backup, recovery and disaster-recovery
service for OpenStack. It adds ``openstack backup ...`` and nothing else: the
commands resolve the service from the cloud's own catalog under service type
``backup``, and authenticate with the same token as every other ``openstack``
command.

Ferry is documented at `osie.io/docs/ferry <https://osie.io/docs/ferry/>`_,
where the `CLI reference <https://osie.io/docs/ferry/cli-reference/>`_ lists
every command and option, and deployed with the manifests in
`ferry-backup <https://github.com/osie/ferry-backup>`_.

Install
=======

::

    pip install python-ferryclient

The plugin is discovered through entry points, so there is nothing to
configure. ``openstack backup plan list`` works as soon as both this package
and ``python-openstackclient`` are in the same environment and the cloud has a
``backup`` endpoint in its catalog.

Usage
=====

Backups are driven by plans, and a plan runs under a *policy*. The policy is
the operator's: it carries the schedule, the retention ladder and the recovery
objectives. A tenant never types a schedule or a retention count. They read the
catalogue of what their project may name, and name one. Whether a guest is
frozen before each backup is the plan's own ``--consistency``::

    openstack backup policy list

    openstack backup plan create nightly \
        --resource-kind instance --resource <server-id> \
        --policy gold --consistency filesystem

    openstack backup plan list
    openstack backup plan refusal list <plan>

Each policy lists with the sentence that describes it, such as "Every day
between 21:00 and 05:00. Each backup is kept for 7 days, one a month for 6
months.", which is the whole of a tenant's interface to it. Every clause is
derived, and the two
that matter most, whether a backup can be deleted and where it can be
recovered, are true because of what the operator registered rather than because
anyone asserted them.

``refusal list`` is worth knowing about early: it reports what a plan will not
protect and why, so a resource that will never be backed up says so there
rather than by quietly producing nothing. ``plan missed tick list`` is its
counterpart in time: a tick that could not start inside the policy's
``start_within`` is recorded as missed rather than queued behind the next one.

Backups themselves are points::

    openstack backup point list --plan <plan>
    openstack backup point create --plan <plan>
    openstack backup point create --plan <plan> --keep-until 2027-01-31T23:59:59Z
    openstack backup point create --resource <volume> --resource-kind volume \
        --vault Immutable --keep-until 2027-01-31T23:59:59Z
    openstack backup point create --resource <volume> --resource-kind volume \
        --vault Standard --until-deleted
    openstack backup point metrics show <point>
    openstack backup point verify <point>

A manual backup is kept until ``--keep-until``, within the terms of the vault it
lands in (``openstack backup vault list``). In a plan it may be left out and the
backup is kept as long as the plan's scheduled ones. Without ``--plan`` it backs
up one server or volume into the vault named (in its plan, when the plan's
backups are kept there), and a date, or ``--until-deleted`` where the vault
offers it, is required.

Restoring::

    openstack backup restore estimate --point <point>
    openstack backup restore create --point <point> --mode volume --name recovered
    openstack backup restore create --point <point> --mode instance \
        --flavor m1.large --networks <network> --disks <volume>
    openstack backup restore show <restore>
    openstack backup attachment create --point <point> --instance <server> \
        --disk <volume> --ttl 2h

``volume`` and ``instance`` create a new resource, and only they take a
different shape: ``--disks`` for either, ``--flavor``, ``--networks``,
``--key-name`` and ``--security-groups`` for ``instance``. ``bucket`` restores
an object namespace into a new bucket. ``in_place`` overwrites an existing
resource and destroys whatever is currently there, so it is never a default.
An attachment presents one disk read-only to a running instance and cleans
itself up after ``--ttl`` (four hours unless stated).

Operator commands
=================

Policies are the service levels this cloud sells, and writing one is an
operator action::

    openstack backup policy create gold \
        --every 1h --at 02:00 --window-start 22:00 --window-end 06:00 \
        --jitter 30m --start-within 2h \
        --keep-all 48h --keep-daily 30 --keep-weekly 12 --keep-monthly 12 \
        --keep-yearly 7 --anchor week=sunday \
        --backup-repository s3-frankfurt \
        --instant-tier ceph-tier-fra --instant-within 168h \
        --recovery-site cloud-b --recovery-rung warm \
        --transport repository --rto-target 30m

    openstack backup policy assign gold --project <project-id>
    openstack backup policy show gold --scope tenant
    openstack backup policy set gold --keep-all 72h --apply-to-existing
    openstack backup policy deprecate gold
    openstack backup policy retire gold --successor platinum
    openstack backup policy delete draft-bronze

Durations are Go duration strings (``168h``, ``30m``) on the way in. An edit
applies forward: points already written keep the expiry they were given when
they committed, and ``--apply-to-existing`` is the explicit instruction to
re-derive them. When that would shorten anything, it needs ``policy:shorten``
and says what a lock refuses to shorten at all. ``openstack backup retention
simulate --policy gold --keep-all 72h`` answers that before the edit does.
``--scope tenant`` renders a policy the way the tenant who bought it sees it,
which is the one thing an operator cannot otherwise check before assigning.
``--recovery-site`` takes a site's name or its id; ``openstack backup site
list`` shows both.

Repositories are where backups are stored, and they carry the retention
contract every policy writing there inherits::

    openstack backup repository list
    openstack backup repository create cold --kind chunk --site site-a \
        --driver s3 --endpoint https://s3.example.net --bucket ferry \
        --lock-mode compliance --lock-min-retention 720h \
        --soft-delete-grace 336h
    openstack backup repository set cold --lock-min-retention 1440h
    openstack backup repository usage show cold
    openstack backup repository create cold-replica --kind chunk \
        --site cloud-b --driver s3 --endpoint https://s3.cloud-b.example.net \
        --bucket ferry-replica --replica-of cold
    openstack backup repository set cold --reachable-from-site cloud-b

A policy that recovers at another site needs a repository that site can read:
one local to it or registered as reachable from it, or a replica of the one the
policy writes to that is. Either line above satisfies a policy writing to
``cold`` and recovering at ``cloud-b``.
``--reachable-from-site`` states the whole list on ``set``;
``--clear-reachable-from-sites`` and ``--clear-replica-of`` remove them.

Immutability is an attribute of the repository, not a checkbox on a plan: a
policy whose ladder is shorter than the floor is refused with the floor named,
rather than quietly clamped. Registering a contract without
``--lock-changeable-until`` leaves it correctable for three days, because a
registration is where typos live; after that the floor only increases, the mode
is fixed and the block cannot be removed.

A legal hold is the one retention control that is neither policy nor lock::

    openstack backup legal hold create --project <project-id> \
        --reason 'litigation 2026-41'
    openstack backup legal hold list
    openstack backup legal hold delete <hold>

And coverage is the report that says what this cloud is not protecting:
resources under no plan, plans paused, plans on a deprecated policy, plans
whose policy names storage it cannot use, missed ticks, points the copy tier has
not reached, points no lock holds::

    openstack backup coverage show
    openstack backup plan restore <plan>

    openstack backup mover list
    openstack backup usage show

``plan restore`` lifts a tenant's delete while the repository's soft-delete
grace still holds it.

Disaster recovery works on groups, which fail over together to a consistent
moment. A group is created under a policy, whose recovery section is the
group's promise, and every member must already be protected by a plan under
that policy::

    openstack backup group create payments --policy gold --instance <instance>
    openstack backup group sla show <group>

A failover is two calls in two regions: a release where the group runs, which
stops it and hands over its last copy, and a recover where it is going::

    openstack backup group release <group> --reason "moving to cloud-b"
    openstack backup group recover <group> --mode planned
    openstack backup group test <group> --bubble-policy <bubble-policy>

``recover`` needs ``--mode``. ``--mode unplanned`` recovers without a release
and is refused unless ``--confirm-primary-may-be-serving-writes`` is given,
because recovering while the other region still takes writes splits the data in
two. ``--recovery-point aligned``, the default, brings every member back to the
newest instant they all hold a point for; ``newest`` takes each member's own
newest point. ``--max-point-age`` refuses the recover when any member's point
is older than that. ``--dry-run``, on ``release``, ``recover``, ``test``,
``resync`` and ``retire``, shows the plan member by member, with the point
each recovers to and the spread between them, and starts nothing::

    openstack backup group recover <group> --mode unplanned \
        --confirm-primary-may-be-serving-writes --max-point-age 2h --dry-run
    openstack backup group test <group> --dry-run

A release needs the recovery region to have reported itself ready;
``--override-recovery-readiness`` (operator) releases without that. Until the
release record is written, a failed release starts the instances again.

Coming home is the same two calls in the other direction. At the group's home,
bind the instances the other region recovered back to their members once, then
release there and recover planned here: each member returns to its original
instance, copying only what changed where it can, and the recover refuses if
an original was written after it was released::

    openstack backup group failback bindings create <group> --dry-run
    openstack backup group failback bindings create <group>

``test`` brings the group up in an isolated bubble and tears it down, so
the result is a real answer to "would this work". If both regions ran the
group, it is at split brain risk until one copy is chosen: ``resync``
(operator, with ``--confirm-discard-local-writes``) stops this region's copy,
keeps what it wrote as a backup and makes it standby, and ``split brain
acknowledge`` (system administrator, with
``--confirm-other-region-discarded``) keeps this region's copy and makes the
other region resync. ``retire`` removes what a superseded recovery left here:
its servers are deleted and their volumes unmanaged, never deleted. Each of
these reads the cloud's capabilities first and, while they say disaster
recovery is not available, stops with the reason they give and sends nothing.

Every one of them starts a run, which is watched and steered under the group::

    openstack backup group run list <group>
    openstack backup group run show <group> <run> --actions --resources
    openstack backup group run cancel <group> <run>
    openstack backup group run abort <group> <run>
    openstack backup group run resume <group> <run>

A run is cancelled only before its point of no return, and what it built is
torn down. After it, an operator may abort the run, which stops it and leaves
everything as it is, and a halted run is resumed where its journal left off.
``run show`` lists each member's state, the instance it became, when it booted
and when it was healthy, and the spread between the members' recovery points.

A test's bubble is built the way a bubble policy says (operator): in which
operator project, from which ranges, whether it may have a router, how long it
may stand, and which addresses its jump host must fail to reach before any
member boots::

    openstack backup bubble policy create dr-lab --project <project> \
        --network-cidr 10.250.0.0/16 --max-duration 2h \
        --isolation-canary 10.0.0.10:5432
    openstack backup bubble policy list
    openstack backup bubble policy set dr-lab --no-isolation-canary
    openstack backup bubble policy delete dr-lab

A policy a registration names, or that any test ran under, is kept and its
delete refused with ``bubble_policy_in_use``.

Recovering another cloud's backups is an operator's work on the cloud that
recovers them. A recovery binding claims one resource for a project here; a
recovery profile says how the other cloud's flavors and networks land here; a
standby is a warm copy kept current at the recovery site::

    openstack backup recovery profile create from-cloud-a --origin-cloud cloud-a \
        --flavor-map m1.large=dr.large --network-map prod-net=dr-net
    openstack backup recovery binding create --repository cold \
        --origin-cloud cloud-a --resource <volume> --target-project <project> \
        --standby-pool dr-standby
    openstack backup recovery binding dry run <binding> --profile from-cloud-a
    openstack backup standby list
    openstack backup standby promote <standby>

A protection group is recovered as a whole. Its home writes a group document
into the repositories its members are backed up to, and the recovery region
reads it from there; registering a recovery binds every member at once and
follows the document as members are added at home::

    openstack backup recovery group list cold
    openstack backup group register <group-uid> --repository cold \
        --target-project <project> --policy gold-back \
        --mapping-profile from-cloud-a --standby-pool dr-standby
    openstack backup group list --role recovery
    openstack backup group readiness show <group>

A member already bound to another project is refused with
``binding_conflict``. ``readiness show`` says, member by member, what a
recover here would use and what it would refuse; where the group runs, it
shows what the recovery region last reported and how old that report is.

A run acts in the group's project through a delegation a member of that
project gives this region, and arming is how it is given::

    openstack backup group arm <group> --expires-in 2160h
    openstack backup group disarm <group>

Options
=======

``--os-backup-api-version``
    API version. Default ``1``. Env: ``OS_BACKUP_API_VERSION``.

``--os-backup-endpoint``
    Base URL, bypassing the catalog. Env: ``OS_BACKUP_ENDPOINT``. Needed
    before the service has been registered.

Errors
======

The API reports failures as ``application/problem+json`` (`RFC 7807
<https://datatracker.ietf.org/doc/html/rfc7807>`_) with a stable machine
readable ``code`` and the request id the server logged. Both are surfaced::

    HTTP 409 (plan_resource_conflict) that resource is already in plan
    nightly [request-id: 1d11be481f08b016]

Branch on the code; the request id is what turns a user's report into a grep
against the service log.
