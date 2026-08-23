from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery
from requests import Response
from requests.exceptions import HTTPError

from config import Settings, build_bigquery_client, build_credentials, get_settings

logger = logging.getLogger(__name__)

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_API_ROOT = "https://datacatalog.googleapis.com/v1"
_FINE_GRAINED_READER_ROLE = "roles/datacatalog.categoryFineGrainedReader"

RestrictionLevel = Literal["HIGH", "LOW"]
_TAG_DISPLAY_NAMES: dict[RestrictionLevel, str] = {"HIGH": "PII-HIGH", "LOW": "PII-LOW"}


class AccessControlError(Exception):
    pass


@dataclass(slots=True)
class ColumnRestriction:
    dataset: str
    table: str
    column: str
    level: RestrictionLevel | None


class ColumnAccessControlClient:
    """Applies *real*, BigQuery-enforced column-level access control via Data Catalog Policy Tags.

    This is a fundamentally different, higher-stakes mechanism than the governance "tags" elsewhere
    in this app (those are just metadata labels). A column bound to a policy tag becomes inaccessible
    to every principal — including project Owners — except those explicitly granted the fine-grained
    reader role on that specific tag. Every method here that creates a taxonomy grants this app's own
    service account reader access on both tags *before* anything is ever bound to a column, specifically
    so applying a restriction can never lock this app itself out — verified against the live API before
    this module was written: grant-then-restrict, in that order, confirmed to preserve access; the
    naive `policy_tags=None` clear is a no-op (silently ignored by the API) — clearing requires an
    explicit empty `PolicyTagList(names=[])`.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        credentials = build_credentials(self._settings)
        self._own_principal = (
            f"serviceAccount:{credentials.service_account_email}"
            if credentials is not None and hasattr(credentials, "service_account_email")
            else None
        )
        scoped_credentials = credentials.with_scopes([_CLOUD_PLATFORM_SCOPE]) if credentials else None
        self._session = AuthorizedSession(scoped_credentials) if scoped_credentials else AuthorizedSession(None)
        self._bq_client = build_bigquery_client(self._settings)
        self._project_id = self._settings.gcp_project_id
        self._location = self._settings.access_control_location
        self._tag_cache: dict[RestrictionLevel, str] | None = None

    # ---------------------------------------------------------------- plumbing

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response: Response = self._session.request(method, url, **kwargs)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            body = _safe_json(response)
            message = body.get("error", {}).get("message", response.text) if body else response.text
            raise AccessControlError(f"Data Catalog API error ({response.status_code}): {message}") from exc
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    # ---------------------------------------------------------------- taxonomy / tags (idempotent)

    def ensure_taxonomy_and_tags(self) -> dict[RestrictionLevel, str]:
        """Idempotently ensures the taxonomy + HIGH/LOW policy tags exist and this app can read both.

        Taxonomies/tags get server-generated numeric IDs (no user-assignable ID like other Dataplex
        resources here), so idempotency is a list-and-match-by-display-name, not a get-by-id.
        """
        if self._tag_cache is not None:
            return self._tag_cache

        taxonomy_name = self._find_or_create_taxonomy()
        tags = {level: self._find_or_create_tag(taxonomy_name, level) for level in ("HIGH", "LOW")}

        if self._own_principal:
            for tag_name in tags.values():
                self._ensure_reader(tag_name, self._own_principal)
        else:
            logger.warning("Could not determine this app's own service account principal — skipping self-grant.")

        self._tag_cache = tags
        return tags

    def _find_or_create_taxonomy(self) -> str:
        list_url = f"{_API_ROOT}/projects/{self._project_id}/locations/{self._location}/taxonomies"
        body = self._request("GET", list_url)
        for tax in body.get("taxonomies", []):
            if tax.get("displayName") == self._settings.access_control_taxonomy_name:
                return tax["name"]

        create_body = {
            "displayName": self._settings.access_control_taxonomy_name,
            "description": "Real, enforced column-level access control for HIGH/LOW PII columns.",
            "activatedPolicyTypes": ["FINE_GRAINED_ACCESS_CONTROL"],
        }
        created = self._request("POST", list_url, json=create_body)
        return created["name"]

    def _find_or_create_tag(self, taxonomy_name: str, level: RestrictionLevel) -> str:
        display_name = _TAG_DISPLAY_NAMES[level]
        list_url = f"{_API_ROOT}/{taxonomy_name}/policyTags"
        body = self._request("GET", list_url)
        for tag in body.get("policyTags", []):
            if tag.get("displayName") == display_name:
                return tag["name"]

        created = self._request(
            "POST", list_url, json={"displayName": display_name, "description": f"{level} sensitivity PII."}
        )
        return created["name"]

    def _ensure_reader(self, tag_resource: str, principal: str) -> None:
        readers = self._list_readers_raw(tag_resource)
        if principal in readers:
            return
        self._set_readers(tag_resource, readers + [principal])

    # ---------------------------------------------------------------- reader management

    def list_readers(self, level: RestrictionLevel) -> list[str]:
        tags = self.ensure_taxonomy_and_tags()
        return self._list_readers_raw(tags[level])

    def grant_reader(self, level: RestrictionLevel, principal: str) -> None:
        tags = self.ensure_taxonomy_and_tags()
        self._ensure_reader(tags[level], principal)

    def revoke_reader(self, level: RestrictionLevel, principal: str) -> None:
        tags = self.ensure_taxonomy_and_tags()
        tag_resource = tags[level]
        readers = self._list_readers_raw(tag_resource)
        if principal not in readers:
            return
        if self._own_principal and principal == self._own_principal:
            raise AccessControlError("Refusing to revoke this app's own service account — that would lock the app out.")
        self._set_readers(tag_resource, [r for r in readers if r != principal])

    def _list_readers_raw(self, tag_resource: str) -> list[str]:
        url = f"{_API_ROOT}/{tag_resource}:getIamPolicy"
        body = self._request("POST", url)
        for binding in body.get("bindings", []):
            if binding.get("role") == _FINE_GRAINED_READER_ROLE:
                return list(binding.get("members", []))
        return []

    def _set_readers(self, tag_resource: str, members: list[str]) -> None:
        url = f"{_API_ROOT}/{tag_resource}:setIamPolicy"
        policy = {"bindings": [{"role": _FINE_GRAINED_READER_ROLE, "members": members}]} if members else {"bindings": []}
        self._request("POST", url, json={"policy": policy})

    # ---------------------------------------------------------------- column binding

    def apply_restriction(self, dataset: str, table: str, column: str, level: RestrictionLevel) -> None:
        tags = self.ensure_taxonomy_and_tags()
        self._set_column_policy_tags(dataset, table, column, [tags[level]])

    def remove_restriction(self, dataset: str, table: str, column: str) -> None:
        self._set_column_policy_tags(dataset, table, column, [])

    def get_restriction(self, dataset: str, table: str, column: str) -> RestrictionLevel | None:
        tags = self.ensure_taxonomy_and_tags()
        table_ref = f"{self._project_id}.{dataset}.{table}"
        bq_table = self._bq_client.get_table(table_ref)
        for field in bq_table.schema:
            if field.name == column and field.policy_tags:
                current = set(field.policy_tags.names)
                for level, tag_name in tags.items():
                    if tag_name in current:
                        return level
        return None

    def _set_column_policy_tags(self, dataset: str, table: str, column: str, tag_names: list[str]) -> None:
        table_ref = f"{self._project_id}.{dataset}.{table}"
        bq_table = self._bq_client.get_table(table_ref)

        found = False
        new_schema = []
        for field in bq_table.schema:
            if field.name == column:
                found = True
                new_schema.append(
                    bigquery.SchemaField(
                        field.name,
                        field.field_type,
                        mode=field.mode,
                        description=field.description,
                        # An empty (not None) PolicyTagList is required to actually clear existing
                        # tags — `policy_tags=None` is silently dropped from the API request instead
                        # of clearing the field, confirmed against the live API.
                        policy_tags=bigquery.PolicyTagList(names=tag_names),
                    )
                )
            else:
                new_schema.append(field)

        if not found:
            raise AccessControlError(f"Column '{column}' not found on {dataset}.{table}")

        bq_table.schema = new_schema
        self._bq_client.update_table(bq_table, ["schema"])


def _safe_json(response: Response) -> dict[str, Any] | None:
    try:
        return response.json()
    except ValueError:
        return None
