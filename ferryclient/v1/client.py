# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""The Ferry v1 API client.

Thin on purpose. Ferry's API is small, versioned in the path, and answers a
consistent envelope, so there is nothing here worth hiding behind resource
objects: every method returns the decoded JSON. What this class does own is the
three things every caller would otherwise get subtly wrong: resolving the
endpoint, not doubling the ``/v1`` prefix, and turning a problem document into
a typed exception.
"""

import re
import urllib.parse

from keystoneauth1 import adapter
from keystoneauth1 import exceptions as ks_exceptions

from ferryclient import exceptions

DEFAULT_SERVICE_TYPE = "backup"
API_VERSION = "v1"

_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _looks_like_id(ref):
    return bool(_ID.match(str(ref or "")))


def _path_id(value):
    if value is None or str(value) == "":
        raise exceptions.BadRequest(
            status_code=400, code="validation_failed",
            detail="an id must not be empty")
    return urllib.parse.quote(str(value), safe="")


class Client:
    """Talks to one Ferry manager.

    :param session: an authenticated ``keystoneauth1`` session.
    :param service_type: catalog service type; Ferry registers ``backup``.
    :param interface: catalog interface: public, internal or admin.
    :param region_name: catalog region.
    :param endpoint_override: bypass the catalog entirely. Needed before Ferry
        is registered, and for a central manager, which is deliberately in no
        cloud's catalog and is reachable only by explicit endpoint.
    """

    def __init__(self, session, service_type=DEFAULT_SERVICE_TYPE,
                 interface="public", region_name=None, endpoint_override=None,
                 timeout=None, **kwargs):
        self.http = adapter.Adapter(
            session=session,
            service_type=service_type,
            interface=interface,
            region_name=region_name,
            endpoint_override=endpoint_override,
        )
        # keystoneauth1's Adapter takes no timeout: it is a per-request
        # argument, so it is held here and applied on each call.
        self._timeout = timeout
        self._base = None

    # -- plumbing ---------------------------------------------------------

    def _base_url(self):
        """The endpoint with any version suffix removed.

        Ferry's catalog entry points at ``/v1`` (that is what the deployment
        registers), but nothing guarantees it: an operator may register the
        bare root, and ``--os-backup-endpoint`` may be either. Paths in
        this client are always written the way the API contract writes them,
        as ``/v1/plans``, so the version is stripped here rather than being
        conditional at every call site.
        """
        if self._base is not None:
            return self._base
        try:
            endpoint = self.http.get_endpoint()
        except ks_exceptions.EndpointNotFound as exc:
            raise exceptions.EndpointNotFound(
                "no 'backup' endpoint found in the service catalog; "
                "the backup service may not be deployed in this region, or "
                "try --os-backup-endpoint"
            ) from exc
        if not endpoint:
            raise exceptions.EndpointNotFound(
                "the service catalog returned an empty 'backup' endpoint"
            )
        endpoint = endpoint.rstrip("/")
        if endpoint.endswith("/" + API_VERSION):
            endpoint = endpoint[: -(len(API_VERSION) + 1)]
        self._base = endpoint
        return self._base

    def request(self, method, path, body=None, params=None):
        resp = self.http.request(
            self._base_url() + path,
            method,
            json=body,
            params=params,
            headers={"Accept": "application/json"},
            timeout=self._timeout,
            raise_exc=False,
        )
        if resp.status_code >= 400:
            raise exceptions.from_response(resp)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def get(self, path, **params):
        # Drop unset filters rather than sending empty query values, which
        # Ferry's decoders would have to distinguish from "not given".
        params = {k: v for k, v in params.items() if v is not None}
        return self.request("GET", path, params=params or None)

    def post(self, path, body=None, **params):
        params = {k: v for k, v in params.items() if v is not None}
        return self.request("POST", path, body=body, params=params or None)

    def patch(self, path, body=None, **params):
        params = {k: v for k, v in params.items() if v is not None}
        return self.request("PATCH", path, body=body, params=params or None)

    def delete(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        if params:
            return self.request("DELETE", path, params=params)
        return self.request("DELETE", path)

    @staticmethod
    def items(payload):
        """Unwrap a list envelope.

        Ferry answers lists as ``{"items": [...], "limit": N}`` and returns a
        null ``items`` for an empty collection on some routes, which a caller
        iterating the result must not trip over.
        """
        if payload is None:
            return []
        if isinstance(payload, dict):
            return payload.get("items") or []
        return payload

    def list_all(self, path, **params):
        if params.get("limit") is not None or params.get("marker") is not None:
            return self.items(self.get(path, **params))
        out = []
        marker = None
        for _ in range(200):
            payload = self.get(path, marker=marker, **params)
            if not isinstance(payload, dict):
                return self.items(payload)
            out.extend(payload.get("items") or [])
            marker = payload.get("next_marker")
            if not marker:
                break
        return out

    # -- plans -------------------------------------------------------------

    def plan_list(self, **filters):
        return self.list_all("/v1/plans", **filters)

    def plan_create(self, body):
        return self.post("/v1/plans", body)

    def plan_show(self, plan_id):
        return self.get(f"/v1/plans/{self.plan_find(plan_id)}")

    def plan_update(self, plan_id, body):
        return self.patch(f"/v1/plans/{self.plan_find(plan_id)}", body)

    def plan_delete(self, plan_id):
        return self.delete(f"/v1/plans/{self.plan_find(plan_id)}")

    def plan_refusals(self, plan_id):
        return self.list_all(f"/v1/plans/{self.plan_find(plan_id)}/refusals")

    def plan_sla(self, plan_id):
        return self.get(f"/v1/plans/{self.plan_find(plan_id)}/sla")

    def plan_restore(self, plan_id):
        return self.post(f"/v1/plans/{self.plan_find(plan_id)}/undelete")

    def plan_missed_ticks(self, plan_id, **filters):
        return self.list_all(
            f"/v1/plans/{self.plan_find(plan_id)}/missed-ticks", **filters)

    def policy_list(self, **filters):
        return self.list_all("/v1/policies", **filters)

    def policy_create(self, body):
        return self.post("/v1/policies", body)

    def policy_find(self, ref):
        return self._find("policy", ref, self.policy_list)

    def policy_show(self, policy, **params):
        return self.get(f"/v1/policies/{self.policy_find(policy)}", **params)

    def policy_update(self, policy, body, apply_to_existing=False):
        return self.patch(
            f"/v1/policies/{self.policy_find(policy)}", body,
            apply_to_existing="true" if apply_to_existing else None)

    def policy_assign(self, policy, body, remove=False):
        return self.post(
            f"/v1/policies/{self.policy_find(policy)}/assign", body,
            remove="true" if remove else None)

    def policy_deprecate(self, policy):
        return self.post(f"/v1/policies/{self.policy_find(policy)}/deprecate")

    def policy_retire(self, policy, successor=None):
        return self.post(
            f"/v1/policies/{self.policy_find(policy)}/retire",
            successor=self.policy_find(successor) if successor else None)

    def policy_delete(self, policy):
        return self.delete(f"/v1/policies/{self.policy_find(policy)}")

    def vault_list(self, **filters):
        return self.list_all("/v1/vaults", **filters)

    def vault_find(self, ref):
        return self._find("vault", ref, self.vault_list)

    def vault_show(self, vault):
        return self.get(f"/v1/vaults/{self.vault_find(vault)}")

    def legal_hold_create(self, body):
        return self.post("/v1/legal-holds", body)

    def legal_hold_list(self, **filters):
        return self.list_all("/v1/legal-holds", **filters)

    def legal_hold_delete(self, hold_id):
        return self.delete(f"/v1/legal-holds/{_path_id(hold_id)}")

    def coverage(self, **params):
        return self.get("/v1/coverage", **params)

    # -- resources ---------------------------------------------------------

    def resource_list(self, **filters):
        return self.list_all("/v1/resources", **filters)

    # -- points ------------------------------------------------------------

    def point_list(self, **filters):
        return self.list_all("/v1/points", **filters)

    def point_create(self, body):
        return self.post("/v1/points", body)

    def point_show(self, point_id, **params):
        return self.get(f"/v1/points/{_path_id(point_id)}", **params)

    def point_delete(self, point_id):
        return self.delete(f"/v1/points/{_path_id(point_id)}")

    def point_metrics(self, point_id, **params):
        return self.get(f"/v1/points/{_path_id(point_id)}/metrics", **params)

    def point_verify(self, point_id):
        return self.post(f"/v1/points/{_path_id(point_id)}/verify")

    def point_document(self, point_id, repository, domain=None):
        # The repository is required: a point document is read out of the
        # object store, and the API will not guess which one.
        return self.get(f"/v1/points/{_path_id(point_id)}/document",
                        repository=repository, domain=domain)

    # -- retention ---------------------------------------------------------

    def retention_simulate(self, body):
        return self.post("/v1/retention/simulate", body)

    # -- restores ----------------------------------------------------------

    def restore_estimate(self, **params):
        return self.get("/v1/restores/estimate", **params)

    def restore_create(self, body):
        return self.post("/v1/restores", body)

    def restore_list(self, **filters):
        return self.list_all("/v1/restores", **filters)

    def restore_show(self, restore_id):
        return self.get(f"/v1/restores/{_path_id(restore_id)}")

    # -- attachments (instant restore) -------------------------------------

    def attachment_create(self, body):
        return self.post("/v1/attachments", body)

    def attachment_list(self, **filters):
        return self.list_all("/v1/attachments", **filters)

    def attachment_delete(self, attachment_id):
        return self.delete(f"/v1/attachments/{_path_id(attachment_id)}")

    # -- jobs --------------------------------------------------------------

    def job_list(self, **filters):
        return self.list_all("/v1/jobs", **filters)

    def job_show(self, job_id):
        return self.get(f"/v1/jobs/{_path_id(job_id)}")

    def job_cancel(self, job_id):
        return self.post(f"/v1/jobs/{_path_id(job_id)}/cancel")

    # -- protection groups and disaster recovery ---------------------------

    def group_list(self, **filters):
        return self.list_all("/v1/protection-groups", **filters)

    def group_find(self, ref):
        """Resolve a protection group name to its id."""
        return self._find("protection group", ref, self.group_list)

    def group_create(self, body):
        return self.post("/v1/protection-groups", body)

    def group_show(self, group_id):
        return self.get(f"/v1/protection-groups/{self.group_find(group_id)}")

    def group_delete(self, group_id, keep_resources=False):
        return self.delete(
            f"/v1/protection-groups/{self.group_find(group_id)}",
            keep_resources="true" if keep_resources else None)

    def group_register(self, repository_id, group_uid, target_project_id,
                       policy_id, origin_cloud=None, name=None,
                       target_domain_id=None, mapping_profile_id=None,
                       bubble_policy_id=None, test_every=None,
                       standby_pool=None, standby_site_id=None,
                       standby_prefix=None, accept_gaps=None,
                       network_map=None):
        recovery_of = {"repository_id": repository_id, "group_uid": group_uid}
        if origin_cloud:
            recovery_of["origin_cloud"] = origin_cloud
        body = {"recovery_of": recovery_of,
                "target_project_id": target_project_id,
                "policy_id": policy_id}
        body.update(self._dr_body(
            name=name, target_domain_id=target_domain_id,
            mapping_profile_id=mapping_profile_id,
            bubble_policy_id=bubble_policy_id, test_every=test_every,
            accept_gaps=accept_gaps or None,
            network_map=network_map or None) or {})
        if standby_pool:
            standby = {"pool": standby_pool}
            standby.update(self._dr_body(site_id=standby_site_id,
                                         prefix=standby_prefix) or {})
            body["standby"] = standby
        return self.post("/v1/protection-groups", body)

    def group_readiness(self, group_id):
        return self.get(
            f"/v1/protection-groups/{self.group_find(group_id)}/readiness")

    def group_mirror(self, group_id):
        return self.get(
            f"/v1/protection-groups/{self.group_find(group_id)}/mirror")

    def group_arm(self, group_id, expires_in=None):
        return self.post(
            f"/v1/protection-groups/{self.group_find(group_id)}/arm",
            self._dr_body(expires_in=expires_in))

    def group_disarm(self, group_id):
        return self.delete(
            f"/v1/protection-groups/{self.group_find(group_id)}/arm")

    def capabilities(self):
        return self.get("/v1/capabilities")

    def healthz(self):
        return self.request("GET", "/healthz")

    @staticmethod
    def _dr_body(**fields):
        body = {k: v for k, v in fields.items() if v not in (None, False, "")}
        return body or None

    def group_release(self, group_id, reason=None,
                      override_recovery_readiness=False, dry_run=False):
        return self.post(
            f"/v1/protection-groups/{self.group_find(group_id)}/release",
            self._dr_body(reason=reason,
                          override_recovery_readiness=override_recovery_readiness),
            dry_run="true" if dry_run else None)

    def group_recover(self, group_id, mode, confirm=False, reason=None,
                      wait_for_release=None, recovery_point=None,
                      max_point_age=None, overwrite_diverged=False,
                      dry_run=False):
        body = {"mode": mode}
        body.update(self._dr_body(
            confirm_primary_may_be_serving_writes=confirm, reason=reason,
            wait_for_release=wait_for_release, recovery_point=recovery_point,
            max_point_age=max_point_age,
            overwrite_diverged=overwrite_diverged) or {})
        return self.post(
            f"/v1/protection-groups/{self.group_find(group_id)}/recover",
            body, dry_run="true" if dry_run else None)

    def group_test(self, group_id, bubble_policy_id=None, reason=None,
                   dry_run=False):
        return self.post(
            f"/v1/protection-groups/{self.group_find(group_id)}/test",
            self._dr_body(bubble_policy_id=bubble_policy_id, reason=reason),
            dry_run="true" if dry_run else None)

    def bubble_policy_list(self, **filters):
        return self.list_all("/v1/bubble-policies", **filters)

    def bubble_policy_find(self, ref):
        return self._find("bubble policy", ref, self.bubble_policy_list)

    def bubble_policy_create(self, body):
        return self.post("/v1/bubble-policies", body)

    def bubble_policy_update(self, policy, body):
        return self.patch(
            f"/v1/bubble-policies/{self.bubble_policy_find(policy)}", body)

    def bubble_policy_delete(self, policy):
        return self.delete(
            f"/v1/bubble-policies/{self.bubble_policy_find(policy)}")

    def group_resync(self, group_id, confirm=False, reason=None,
                     skip_divergence_point=False, dry_run=False):
        return self.post(
            f"/v1/protection-groups/{self.group_find(group_id)}/resync",
            self._dr_body(confirm_discard_local_writes=confirm,
                          skip_divergence_point=skip_divergence_point,
                          reason=reason),
            dry_run="true" if dry_run else None)

    def group_retire(self, group_id, reason=None, dry_run=False):
        return self.post(
            f"/v1/protection-groups/{self.group_find(group_id)}/retire",
            self._dr_body(reason=reason),
            dry_run="true" if dry_run else None)

    def group_acknowledge(self, group_id, confirm=False, reason=None):
        gid = self.group_find(group_id)
        return self.post(
            f"/v1/protection-groups/{gid}/split-brain/acknowledge",
            self._dr_body(confirm_other_region_discarded=confirm,
                          reason=reason))

    def group_failback_bindings(self, group_id, reason=None, dry_run=False):
        gid = self.group_find(group_id)
        return self.post(
            f"/v1/protection-groups/{gid}/failback-bindings",
            self._dr_body(reason=reason),
            dry_run="true" if dry_run else None)

    def group_sla(self, group_id):
        return self.get(
            f"/v1/protection-groups/{self.group_find(group_id)}/sla")

    def group_runs(self, group_id, **filters):
        return self.list_all(
            f"/v1/protection-groups/{self.group_find(group_id)}/runs",
            **filters)

    def group_run(self, group_id, run_id, include=None):
        if include and not isinstance(include, str):
            include = ",".join(include)
        gid = self.group_find(group_id)
        return self.get(
            f"/v1/protection-groups/{gid}/runs/{_path_id(run_id)}",
            include=include or None)

    def run_cancel(self, group_id, run_id):
        gid = self.group_find(group_id)
        return self.post(
            f"/v1/protection-groups/{gid}/runs/{_path_id(run_id)}/cancel")

    def run_abort(self, group_id, run_id):
        gid = self.group_find(group_id)
        return self.post(
            f"/v1/protection-groups/{gid}/runs/{_path_id(run_id)}/abort")

    def run_resume(self, group_id, run_id):
        gid = self.group_find(group_id)
        return self.post(
            f"/v1/protection-groups/{gid}/runs/{_path_id(run_id)}/resume")

    def binding_list(self, **filters):
        return self.list_all("/v1/recovery-bindings", **filters)

    def binding_show(self, binding_id):
        return self.get(f"/v1/recovery-bindings/{_path_id(binding_id)}")

    def binding_create(self, body):
        return self.post("/v1/recovery-bindings", body)

    def binding_delete(self, binding_id):
        return self.delete(f"/v1/recovery-bindings/{_path_id(binding_id)}")

    def binding_dry_run(self, binding_id, body=None):
        return self.post(f"/v1/recovery-bindings/{_path_id(binding_id)}/dry-run", body)

    def recovery_profile_list(self):
        return self.list_all("/v1/recovery-profiles")

    def recovery_profile_create(self, body):
        return self.post("/v1/recovery-profiles", body)

    def recovery_profile_find(self, ref):
        return self._find("recovery profile", ref, self.recovery_profile_list)

    def recovery_profile_delete(self, profile):
        pid = self.recovery_profile_find(profile)
        return self.delete(f"/v1/recovery-profiles/{pid}")

    def standby_list(self, **filters):
        return self.list_all("/v1/standbys", **filters)

    def standby_show(self, standby_id):
        return self.get(f"/v1/standbys/{_path_id(standby_id)}")

    def standby_create(self, body):
        return self.post("/v1/standbys", body)

    def standby_delete(self, standby_id):
        return self.delete(f"/v1/standbys/{_path_id(standby_id)}")

    def standby_promote(self, standby_id, body=None):
        return self.post(f"/v1/standbys/{_path_id(standby_id)}/promote", body)

    # -- repositories (operator) -------------------------------------------

    def repository_list(self, **filters):
        return self.list_all("/v1/repositories", **filters)

    def repository_register(self, body):
        return self.post("/v1/repositories", body)

    def repository_find(self, ref):
        """Resolve a repository name to its id."""
        return self._find("repository", ref, self.repository_list)

    def _find(self, kind, ref, lister):
        """Resolve a name to an id, the way every OpenStack client does.

        Ferry's routes take ids. An operator has names, which are what the
        resource was created with and what every listing shows, so a client
        that passed them straight through answered 404 to the obvious thing to
        type. That is the client's job to smooth over, not the operator's to
        remember.

        An argument that already looks like a uuid is passed through untouched,
        so a resource genuinely named like one is still reachable by id.
        """
        if _looks_like_id(ref):
            return ref
        matches = [r.get("id") for r in lister() if r.get("name") == ref]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise exceptions.NotFound(
                status_code=404, code="not_found",
                detail=f'no {kind} named "{ref}"')
        # Names are not unique in Ferry, so an ambiguous one has to be an error
        # rather than a coin flip: picking the first would act on a resource the
        # operator did not name.
        raise exceptions.NotFound(
            status_code=409, code="conflict",
            detail=f'{len(matches)} {kind}s are named "{ref}"; use an id')

    def plan_find(self, ref):
        """Resolve a plan name to its id."""
        return self._find("plan", ref, self.plan_list)

    def repository_show(self, repository_id):
        rid = self.repository_find(repository_id)
        return self.get(f"/v1/repositories/{rid}")

    def repository_update(self, repository_id, body):
        rid = self.repository_find(repository_id)
        return self.patch(f"/v1/repositories/{rid}", body)

    def repository_delete(self, repository_id):
        rid = self.repository_find(repository_id)
        return self.delete(f"/v1/repositories/{rid}")

    def repository_usage(self, repository_id):
        rid = self.repository_find(repository_id)
        return self.get(f"/v1/repositories/{rid}/usage")

    def repository_health(self):
        return self.get("/v1/repositories/health")

    def repository_groups(self, repository_id, origin_cloud=None):
        rid = self.repository_find(repository_id)
        out = []
        marker = None
        for _ in range(200):
            payload = self.get(f"/v1/repositories/{rid}/inventory",
                               view="groups", origin_cloud=origin_cloud,
                               marker=marker) or {}
            out.extend(payload.get("groups") or [])
            marker = payload.get("next_marker")
            if not marker:
                break
        return out

    # -- movers (operator) -------------------------------------------------

    def mover_list(self, **filters):
        return self.list_all("/v1/movers", **filters)

    def site_list(self, **filters):
        return self.list_all("/v1/sites", **filters)

    def site_find(self, ref):
        return self._find("site", ref, self.site_list)

    # -- domain keys (operator) --------------------------------------------

    def key_fingerprints(self, repository_id):
        payload = self.get(f"/v1/repositories/{_path_id(repository_id)}/domain-keys")
        return payload.get("domain_keys") or []

    def key_export(self, repository_id, body):
        return self.post(
            f"/v1/repositories/{_path_id(repository_id)}/domain-keys/export", body)

    def key_import(self, repository_id, body):
        return self.post(
            f"/v1/repositories/{_path_id(repository_id)}/domain-keys/import", body)

    # -- usage -------------------------------------------------------------

    def usage(self, **params):
        return self.get("/v1/usage", **params)
