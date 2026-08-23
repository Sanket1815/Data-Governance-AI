from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from google.auth.transport.requests import AuthorizedSession
from requests import Response
from requests.exceptions import HTTPError

from config import Settings, build_credentials, get_settings

logger = logging.getLogger(__name__)

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_API_ROOT = "https://dataplex.googleapis.com/v1"

# The one custom Aspect Type this app owns and writes governance metadata through — the
# Dataplex-native replacement for the legacy Data Catalog "Tag Template" concept.
GOVERNANCE_METADATA_TEMPLATE: dict[str, Any] = {
    "name": "governance",
    "type": "record",
    "recordFields": [
        {"name": "data_owner", "type": "string", "index": 1, "annotations": {"displayName": "Data Owner"}},
        {
            "name": "pii_level",
            "type": "enum",
            "index": 2,
            "annotations": {"displayName": "PII Level"},
            "enumValues": [
                {"name": "NONE", "index": 1},
                {"name": "LOW", "index": 2},
                {"name": "HIGH", "index": 3},
            ],
        },
        {"name": "retention_days", "type": "int", "index": 3, "annotations": {"displayName": "Retention (days)"}},
        {"name": "notes", "type": "string", "index": 4, "annotations": {"displayName": "Notes"}},
    ],
}

# Attempting to link a glossary term to a BigQuery-sourced entry via Dataplex's native
# EntryLinks API (entryLinkType "definition") returns a 400 "invalid for the specified
# Entry Link Type" for BigQuery targets — a current product-side limitation, not a request
# bug (confirmed via the raw REST error, independent of path/entry-group variations tried).
# This aspect type is the fallback: the same proven mechanism as the governance tag, just
# storing a reference to a glossary term instead of owner/PII metadata.
GLOSSARY_LINK_METADATA_TEMPLATE: dict[str, Any] = {
    "name": "glossary_link",
    "type": "record",
    "recordFields": [
        {"name": "term_id", "type": "string", "index": 1, "annotations": {"displayName": "Term ID"}},
        {"name": "term_display_name", "type": "string", "index": 2, "annotations": {"displayName": "Term"}},
    ],
}


class CatalogClientError(Exception):
    pass


class CatalogEntryNotFoundError(CatalogClientError):
    pass


@dataclass(slots=True)
class GlossaryTerm:
    term_id: str
    display_name: str
    description: str
    name: str


@dataclass(slots=True)
class AspectData:
    aspect_type_id: str
    data: dict[str, Any]


@dataclass(slots=True)
class CatalogEntry:
    display_name: str
    fully_qualified_name: str
    entry_resource: str
    system: str
    schema_fields: list[dict[str, Any]] = field(default_factory=list)
    aspects: dict[str, AspectData] = field(default_factory=dict)


# Maps our simplified rule_type string to the DataQualityRule "expectation" field it produces.
_QUALITY_RULE_BUILDERS = {
    "non_null": lambda r: {"nonNullExpectation": {}},
    "unique": lambda r: {"uniquenessExpectation": {}},
    "range": lambda r: {
        "rangeExpectation": {"minValue": str(r.min_value), "maxValue": str(r.max_value)}
    },
    "regex": lambda r: {"regexExpectation": {"regex": r.regex}},
    "set": lambda r: {"setExpectation": {"values": r.set_values or []}},
}


@dataclass(slots=True)
class QualityRule:
    column: str
    dimension: str  # COMPLETENESS | UNIQUENESS | VALIDITY | ACCURACY | CONSISTENCY | TIMELINESS
    rule_type: str  # non_null | unique | range | regex | set
    threshold: float = 1.0
    min_value: str | None = None
    max_value: str | None = None
    regex: str | None = None
    set_values: list[str] | None = None

    def to_api_rule(self) -> dict[str, Any]:
        builder = _QUALITY_RULE_BUILDERS.get(self.rule_type)
        if builder is None:
            raise CatalogClientError(f"Unknown quality rule_type: {self.rule_type}")
        rule: dict[str, Any] = {"column": self.column, "dimension": self.dimension, "threshold": self.threshold}
        rule.update(builder(self))
        return rule

    @classmethod
    def from_api_rule(cls, rule: dict[str, Any]) -> "QualityRule":
        column = rule.get("column", "")
        dimension = rule.get("dimension", "")
        threshold = float(rule.get("threshold", 1.0))
        if "nonNullExpectation" in rule:
            return cls(column, dimension, "non_null", threshold)
        if "uniquenessExpectation" in rule:
            return cls(column, dimension, "unique", threshold)
        if "rangeExpectation" in rule:
            r = rule["rangeExpectation"]
            return cls(column, dimension, "range", threshold, min_value=r.get("minValue"), max_value=r.get("maxValue"))
        if "regexExpectation" in rule:
            return cls(column, dimension, "regex", threshold, regex=rule["regexExpectation"].get("regex"))
        if "setExpectation" in rule:
            return cls(column, dimension, "set", threshold, set_values=rule["setExpectation"].get("values", []))
        return cls(column, dimension, "unknown", threshold)


def _bq_table_resource(project_id: str, dataset: str, table: str) -> str:
    return f"bigquery.googleapis.com/projects/{project_id}/datasets/{dataset}/tables/{table}"


class DataplexCatalogClient:
    """Thin wrapper over the Dataplex Catalog REST API.

    The `google-cloud-dataplex` client library models every request as hand-built protobuf
    messages (aspect data is a `Struct`, glossary term parents are easy to get subtly wrong),
    and every shape used here was verified directly against this project's real Dataplex
    instance via `gcloud ... --log-http` before being encoded — REST-with-verified-shapes is
    the more reliable path for this API surface than mirroring gcloud's own proto plumbing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        credentials = build_credentials(self._settings)
        if credentials is not None:
            credentials = credentials.with_scopes([_CLOUD_PLATFORM_SCOPE])
        self._session = AuthorizedSession(credentials) if credentials else AuthorizedSession(None)
        self._project_id = self._settings.gcp_project_id
        self._location = self._settings.dataplex_location
        self._entry_group = self._settings.dataplex_entry_group

    # ---------------------------------------------------------------- plumbing

    def _url(self, path: str, location: str | None = None) -> str:
        return f"{_API_ROOT}/projects/{self._project_id}/locations/{location or self._location}{path}"

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response: Response = self._session.request(method, url, **kwargs)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            body = _safe_json(response)
            message = body.get("error", {}).get("message", response.text) if body else response.text
            if response.status_code == 404:
                raise CatalogEntryNotFoundError(message) from exc
            raise CatalogClientError(f"Dataplex API error ({response.status_code}): {message}") from exc

        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def _request_lro(self, method: str, url: str, *, location: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Issues a request that may return a long-running Operation, and blocks until it resolves."""
        body = self._request(method, url, **kwargs)
        if "done" not in body:
            return body
        return self._await_operation(body["name"], location=location)

    def _await_operation(self, operation_name: str, *, location: str | None = None, timeout_s: float = 60.0) -> dict[str, Any]:
        url = f"{_API_ROOT}/{operation_name}"
        deadline = time.monotonic() + timeout_s
        while True:
            body = self._request("GET", url)
            if body.get("done"):
                if "error" in body:
                    raise CatalogClientError(f"Dataplex operation failed: {body['error']}")
                return body.get("response", {})
            if time.monotonic() > deadline:
                raise CatalogClientError(f"Timed out waiting for Dataplex operation {operation_name}")
            time.sleep(1.5)

    # ---------------------------------------------------------------- entries / search

    def search_entries(self, query: str, page_size: int = 50) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/projects/{self._project_id}/locations/global:searchEntries"
        body = self._request("POST", url, params={"query": query, "pageSize": page_size})
        return [r["dataplexEntry"] for r in body.get("results", []) if "dataplexEntry" in r]

    def list_bigquery_entries(self, dataset: str | None = None) -> list[dict[str, Any]]:
        url = self._url(f"/entryGroups/{self._entry_group}/entries")
        entries: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"pageSize": 200, **({"pageToken": page_token} if page_token else {})}
            body = self._request("GET", url, params=params)
            entries.extend(body.get("entries", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        if dataset:
            entries = [e for e in entries if f"/datasets/{dataset}/tables/" in e.get("name", "")]
        return entries

    def get_table_entry(self, dataset: str, table: str) -> dict[str, Any]:
        # The entry ID segment is a literal resource path containing slashes — Dataplex expects
        # it un-encoded in the URL path (verified against the live API), not percent-encoded.
        resource = _bq_table_resource(self._project_id, dataset, table)
        url = self._url(f"/entryGroups/{self._entry_group}/entries/{resource}") + "?view=ALL"
        return self._request("GET", url)

    # ---------------------------------------------------------------- aspects ("tags")

    def _ensure_aspect_type(self, aspect_type_id: str, display_name: str, template: dict[str, Any]) -> str:
        """Idempotently ensures a custom Aspect Type exists; returns its short ID."""
        url = self._url(f"/aspectTypes/{aspect_type_id}")
        try:
            self._request("GET", url)
            return aspect_type_id
        except CatalogEntryNotFoundError:
            pass

        create_url = self._url("/aspectTypes")
        self._request_lro(
            "POST",
            create_url,
            params={"aspectTypeId": aspect_type_id},
            json={"displayName": display_name, "metadataTemplate": template},
        )
        return aspect_type_id

    def ensure_governance_aspect_type(self) -> str:
        return self._ensure_aspect_type(
            self._settings.dataplex_governance_aspect_type_id, "Data Governance Tag", GOVERNANCE_METADATA_TEMPLATE
        )

    def ensure_glossary_link_aspect_type(self) -> str:
        return self._ensure_aspect_type(
            self._settings.dataplex_glossary_link_aspect_type_id, "Glossary Term Link", GLOSSARY_LINK_METADATA_TEMPLATE
        )

    def _upsert_aspect(
        self, dataset: str, table: str, column: str | None, aspect_type_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        aspect_key = f"{self._project_id}.{self._location}.{aspect_type_id}"
        path = f"Schema.{column}" if column else ""
        full_key = f"{aspect_key}@{path}" if path else aspect_key

        resource = _bq_table_resource(self._project_id, dataset, table)
        url = self._url(f"/entryGroups/{self._entry_group}/entries/{resource}")
        entry_name = f"projects/{self._project_id}/locations/{self._location}/entryGroups/{self._entry_group}/entries/{resource}"

        body = {"name": entry_name, "aspects": {full_key: {"data": data}}}
        return self._request(
            "PATCH",
            url,
            params={"updateMask": "aspects", "aspectKeys": full_key, "deleteMissingAspects": "false"},
            json=body,
        )

    def _remove_aspect(self, dataset: str, table: str, column: str | None, aspect_type_id: str) -> dict[str, Any]:
        path_suffix = f"@Schema.{column}" if column else ""

        entry = self.get_table_entry(dataset, table)
        # Dataplex normalizes the project prefix of a stored aspect key to the project *number*
        # once written, regardless of whether project ID or number was used to write it — so the
        # key we constructed for the upsert won't necessarily string-match what's now stored.
        # Discover the live key by suffix instead of reconstructing it, and use exactly that.
        matching_key = next(
            (key for key in entry.get("aspects", {}) if key.endswith(f".{aspect_type_id}{path_suffix}")),
            None,
        )
        if matching_key is None:
            return entry

        resource = _bq_table_resource(self._project_id, dataset, table)
        url = self._url(f"/entryGroups/{self._entry_group}/entries/{resource}")
        entry_name = f"projects/{self._project_id}/locations/{self._location}/entryGroups/{self._entry_group}/entries/{resource}"

        # deleteMissingAspects=true + an empty `aspects` map is how a targeted aspect key (via
        # aspectKeys) gets removed rather than replaced — verified against the live API.
        return self._request(
            "PATCH",
            url,
            params={"updateMask": "aspects", "aspectKeys": matching_key, "deleteMissingAspects": "true"},
            json={"name": entry_name, "aspects": {}},
        )

    def upsert_governance_aspect(
        self, dataset: str, table: str, column: str | None, data: dict[str, Any]
    ) -> dict[str, Any]:
        aspect_type_id = self.ensure_governance_aspect_type()
        return self._upsert_aspect(dataset, table, column, aspect_type_id, data)

    def remove_governance_aspect(self, dataset: str, table: str, column: str | None) -> dict[str, Any]:
        return self._remove_aspect(dataset, table, column, self._settings.dataplex_governance_aspect_type_id)

    # ---------------------------------------------------------------- glossary term links

    def link_glossary_term(
        self, dataset: str, table: str, column: str | None, term_id: str, term_display_name: str
    ) -> dict[str, Any]:
        aspect_type_id = self.ensure_glossary_link_aspect_type()
        return self._upsert_aspect(
            dataset, table, column, aspect_type_id, {"term_id": term_id, "term_display_name": term_display_name}
        )

    def unlink_glossary_term(self, dataset: str, table: str, column: str | None) -> dict[str, Any]:
        return self._remove_aspect(dataset, table, column, self._settings.dataplex_glossary_link_aspect_type_id)

    # ---------------------------------------------------------------- glossary

    def ensure_governance_glossary(self) -> str:
        glossary_id = self._settings.dataplex_glossary_id
        url = self._url(f"/glossaries/{glossary_id}")
        try:
            self._request("GET", url)
            return glossary_id
        except CatalogEntryNotFoundError:
            pass

        create_url = self._url("/glossaries")
        self._request_lro(
            "POST",
            create_url,
            params={"glossaryId": glossary_id},
            json={
                "displayName": "Data Governance Glossary",
                "description": "Business terms for the healthcare_insurance dataset.",
            },
        )
        return glossary_id

    def list_terms(self) -> list[GlossaryTerm]:
        glossary_id = self.ensure_governance_glossary()
        url = self._url(f"/glossaries/{glossary_id}/terms")
        body = self._request("GET", url)
        return [
            GlossaryTerm(
                term_id=t["name"].rsplit("/", 1)[-1],
                display_name=t.get("displayName", ""),
                description=t.get("description", ""),
                name=t["name"],
            )
            for t in body.get("terms", [])
        ]

    def create_term(self, term_id: str, display_name: str, description: str) -> GlossaryTerm:
        glossary_id = self.ensure_governance_glossary()
        parent = f"projects/{self._project_id}/locations/{self._location}/glossaries/{glossary_id}"
        url = self._url(f"/glossaries/{glossary_id}/terms")
        body = self._request(
            "POST",
            url,
            params={"termId": term_id},
            json={"parent": parent, "displayName": display_name, "description": description},
        )
        return GlossaryTerm(term_id=term_id, display_name=display_name, description=description, name=body["name"])

    def delete_term(self, term_id: str) -> None:
        glossary_id = self.ensure_governance_glossary()
        url = self._url(f"/glossaries/{glossary_id}/terms/{term_id}")
        self._request("DELETE", url)

    # ---------------------------------------------------------------- data profiling (Datascans)

    def ensure_profile_datascan(self, dataset: str, table: str) -> str:
        datascan_id = f"profile-{dataset}-{table}".replace("_", "-")[:63]
        location = self._settings.dataplex_datascan_location
        url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans/{datascan_id}"
        try:
            self._request("GET", url)
            return datascan_id
        except CatalogEntryNotFoundError:
            pass

        resource = f"//bigquery.googleapis.com/projects/{self._project_id}/datasets/{dataset}/tables/{table}"
        create_url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans"
        self._request_lro(
            "POST",
            create_url,
            location=location,
            params={"dataScanId": datascan_id},
            json={
                "displayName": f"{table} profile",
                "data": {"resource": resource},
                "dataProfileSpec": {},
                "executionSpec": {"trigger": {"onDemand": {}}},
            },
        )
        return datascan_id

    def run_profile_scan(self, dataset: str, table: str) -> str:
        datascan_id = self.ensure_profile_datascan(dataset, table)
        location = self._settings.dataplex_datascan_location
        url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans/{datascan_id}:run"
        body = self._request("POST", url)
        job_name = body.get("job", {}).get("name", "")
        return job_name.rsplit("/", 1)[-1]

    def get_latest_profile_result(self, dataset: str, table: str) -> dict[str, Any] | None:
        datascan_id = f"profile-{dataset}-{table}".replace("_", "-")[:63]
        return self._get_latest_job(datascan_id, self._settings.dataplex_datascan_location)

    def _get_latest_job(self, datascan_id: str, location: str) -> dict[str, Any] | None:
        jobs_url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans/{datascan_id}/jobs"
        try:
            jobs_body = self._request("GET", jobs_url)
        except CatalogEntryNotFoundError:
            return None

        jobs = sorted(jobs_body.get("dataScanJobs", []), key=lambda j: j.get("startTime", ""), reverse=True)
        if not jobs:
            return None

        latest = jobs[0]
        job_id = latest["name"].rsplit("/", 1)[-1]
        job_url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans/{datascan_id}/jobs/{job_id}"
        # DataScan job resources use view="FULL" — a different enum than Entries' view="ALL".
        # Verified separately against the live API; the two resource families are not consistent.
        return self._request("GET", job_url, params={"view": "FULL"})

    # ---------------------------------------------------------------- data quality (rules)

    def _quality_datascan_id(self, dataset: str, table: str) -> str:
        return f"quality-{dataset}-{table}".replace("_", "-")[:63]

    def get_quality_rules(self, dataset: str, table: str) -> list[QualityRule]:
        datascan_id = self._quality_datascan_id(dataset, table)
        location = self._settings.dataplex_datascan_location
        url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans/{datascan_id}"
        try:
            body = self._request("GET", url, params={"view": "FULL"})
        except CatalogEntryNotFoundError:
            return []
        return [QualityRule.from_api_rule(r) for r in body.get("dataQualitySpec", {}).get("rules", [])]

    def add_quality_rule(self, dataset: str, table: str, rule: QualityRule) -> list[QualityRule]:
        rules = self.get_quality_rules(dataset, table)
        rules.append(rule)
        self._save_quality_rules(dataset, table, rules)
        return rules

    def delete_quality_rule(self, dataset: str, table: str, index: int) -> list[QualityRule]:
        rules = self.get_quality_rules(dataset, table)
        if not 0 <= index < len(rules):
            raise CatalogClientError(f"No quality rule at index {index} for {dataset}.{table}")
        rules.pop(index)
        self._save_quality_rules(dataset, table, rules)
        return rules

    def _save_quality_rules(self, dataset: str, table: str, rules: list[QualityRule]) -> None:
        datascan_id = self._quality_datascan_id(dataset, table)
        location = self._settings.dataplex_datascan_location
        url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans/{datascan_id}"
        spec = {"dataQualitySpec": {"rules": [r.to_api_rule() for r in rules]}}

        exists = True
        try:
            self._request("GET", url)
        except CatalogEntryNotFoundError:
            exists = False

        if exists:
            self._request_lro(
                "PATCH", url, location=location, params={"updateMask": "dataQualitySpec"}, json=spec
            )
            return

        resource = f"//bigquery.googleapis.com/projects/{self._project_id}/datasets/{dataset}/tables/{table}"
        create_url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans"
        self._request_lro(
            "POST",
            create_url,
            location=location,
            params={"dataScanId": datascan_id},
            json={
                "displayName": f"{table} data quality",
                "data": {"resource": resource},
                "executionSpec": {"trigger": {"onDemand": {}}},
                **spec,
            },
        )

    def run_quality_scan(self, dataset: str, table: str) -> str:
        datascan_id = self._quality_datascan_id(dataset, table)
        location = self._settings.dataplex_datascan_location
        url = f"{_API_ROOT}/projects/{self._project_id}/locations/{location}/dataScans/{datascan_id}:run"
        body = self._request("POST", url)
        job_name = body.get("job", {}).get("name", "")
        return job_name.rsplit("/", 1)[-1]

    def get_latest_quality_result(self, dataset: str, table: str) -> dict[str, Any] | None:
        datascan_id = self._quality_datascan_id(dataset, table)
        return self._get_latest_job(datascan_id, self._settings.dataplex_datascan_location)


def _safe_json(response: Response) -> dict[str, Any] | None:
    try:
        return response.json()
    except ValueError:
        return None
