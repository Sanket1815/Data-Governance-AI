from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator

from catalog_access import AccessControlError, ColumnAccessControlClient, RestrictionLevel
from catalog_approvals import ApprovalNotFoundError, ApprovalNotPendingError, CatalogApprovalQueue
from catalog_audit import CatalogAuditLog
from catalog_client import CatalogClientError, CatalogEntryNotFoundError, DataplexCatalogClient, QualityRule
from config import get_settings
from dlp_scanner import DlpScanner
from lineage import get_pipeline_lineage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


def _get_catalog_client() -> DataplexCatalogClient:
    return DataplexCatalogClient(settings=get_settings())


def _get_dlp_scanner() -> DlpScanner:
    return DlpScanner(settings=get_settings())


def _get_audit_log() -> CatalogAuditLog:
    return CatalogAuditLog(settings=get_settings())


def _get_access_client() -> ColumnAccessControlClient:
    return ColumnAccessControlClient(settings=get_settings())


def _get_approval_queue() -> CatalogApprovalQueue:
    return CatalogApprovalQueue(settings=get_settings())


# ============================================================================
# Models
# ============================================================================


class CatalogTableSummary(BaseModel):
    display_name: str
    dataset: str
    table: str
    fully_qualified_name: str


class CatalogColumnSchema(BaseModel):
    name: str
    data_type: str
    mode: str


class GovernanceTag(BaseModel):
    data_owner: str = ""
    pii_level: Literal["NONE", "LOW", "HIGH"] = "NONE"
    retention_days: int = 0
    notes: str = ""


class LinkedGlossaryTerm(BaseModel):
    term_id: str
    term_display_name: str


class CatalogTableDetail(BaseModel):
    display_name: str
    dataset: str
    table: str
    fully_qualified_name: str
    columns: list[CatalogColumnSchema]
    table_tag: GovernanceTag | None = None
    column_tags: dict[str, GovernanceTag] = Field(default_factory=dict)
    table_glossary_link: LinkedGlossaryTerm | None = None
    column_glossary_links: dict[str, LinkedGlossaryTerm] = Field(default_factory=dict)


class TagUpsertRequest(BaseModel):
    column: str | None = None
    data_owner: str = ""
    pii_level: Literal["NONE", "LOW", "HIGH"] = "NONE"
    retention_days: int = 0
    notes: str = ""
    changed_by: str = Field(default="", max_length=100)


class GlossaryLinkRequest(BaseModel):
    column: str | None = None
    term_id: str = Field(..., min_length=1)
    term_display_name: str = Field(..., min_length=1)


class AuditEntryResponse(BaseModel):
    audit_id: str
    column_name: str | None
    action: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    changed_by: str
    changed_at: datetime


class AuditHistoryResponse(BaseModel):
    entries: list[AuditEntryResponse]


class TagUpsertResult(BaseModel):
    status: Literal["APPLIED", "PENDING_APPROVAL"]
    detail: CatalogTableDetail | None = None
    approval_id: str | None = None
    message: str = ""


class AccessRestrictionResponse(BaseModel):
    dataset: str
    table: str
    column: str
    level: RestrictionLevel | None
    readers: list[str] = Field(default_factory=list)


class ReaderGrantRequest(BaseModel):
    principal: str = Field(..., min_length=1, description='e.g. "user:name@example.com" or "group:team@example.com"')


class PendingApprovalResponse(BaseModel):
    approval_id: str
    dataset: str
    table_name: str
    column_name: str | None
    action: Literal["UPSERT", "DELETE"]
    proposed_data: dict[str, Any] | None
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    proposed_by: str
    proposed_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None


class ApprovalResolutionRequest(BaseModel):
    reviewed_by: str = Field(default="", max_length=100)


class GlossaryTermResponse(BaseModel):
    term_id: str
    display_name: str
    description: str


class GlossaryTermCreateRequest(BaseModel):
    term_id: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(..., min_length=1, max_length=200)
    description: str = ""


class PiiColumnFinding(BaseModel):
    column: str
    info_type_counts: dict[str, int]
    recommended_pii_level: Literal["NONE", "LOW", "HIGH"]


class PiiScanResponse(BaseModel):
    dataset: str
    table: str
    rows_scanned: int
    columns: list[PiiColumnFinding]


class DataProfileResponse(BaseModel):
    state: str
    rows_scanned: int | None = None
    fields: list[dict[str, Any]] = Field(default_factory=list)


class LineageEdgeResponse(BaseModel):
    source: str
    target: str
    description: str


class LineageResponse(BaseModel):
    nodes: list[dict[str, str]]
    edges: list[LineageEdgeResponse]


QualityDimension = Literal["COMPLETENESS", "UNIQUENESS", "VALIDITY", "ACCURACY", "CONSISTENCY", "TIMELINESS"]
QualityRuleType = Literal["non_null", "unique", "range", "regex", "set"]


class QualityRuleRequest(BaseModel):
    column: str = Field(..., min_length=1)
    dimension: QualityDimension
    rule_type: QualityRuleType
    threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    min_value: str | None = None
    max_value: str | None = None
    regex: str | None = None
    set_values: list[str] | None = None

    @model_validator(mode="after")
    def _require_type_specific_fields(self) -> "QualityRuleRequest":
        if self.rule_type == "range" and (self.min_value is None or self.max_value is None):
            raise ValueError("rule_type 'range' requires both min_value and max_value")
        if self.rule_type == "regex" and not self.regex:
            raise ValueError("rule_type 'regex' requires a regex pattern")
        if self.rule_type == "set" and not self.set_values:
            raise ValueError("rule_type 'set' requires a non-empty set_values list")
        return self


class QualityRuleResponse(QualityRuleRequest):
    index: int


class QualityRuleListResponse(BaseModel):
    rules: list[QualityRuleResponse]


class QualityRuleResultItem(BaseModel):
    column: str
    dimension: str
    passed: bool
    pass_ratio: float
    passed_count: int
    evaluated_count: int
    failing_rows_query: str | None = None


class QualityScanResponse(BaseModel):
    state: str
    passed: bool | None = None
    score: float | None = None
    row_count: int | None = None
    rules: list[QualityRuleResultItem] = Field(default_factory=list)


# ============================================================================
# Helpers
# ============================================================================


def _rules_to_response(rules: list[QualityRule]) -> QualityRuleListResponse:
    return QualityRuleListResponse(
        rules=[
            QualityRuleResponse(
                index=i,
                column=r.column,
                dimension=r.dimension,  # type: ignore[arg-type]
                rule_type=r.rule_type,  # type: ignore[arg-type]
                threshold=r.threshold,
                min_value=r.min_value,
                max_value=r.max_value,
                regex=r.regex,
                set_values=r.set_values,
            )
            for i, r in enumerate(rules)
        ]
    )


def _parse_governance_tags(entry: dict[str, Any], aspect_type_id: str) -> tuple[GovernanceTag | None, dict[str, GovernanceTag]]:
    table_tag: GovernanceTag | None = None
    column_tags: dict[str, GovernanceTag] = {}
    for key, aspect in entry.get("aspects", {}).items():
        suffix = key.split(".", 2)[-1] if "." in key else key
        if suffix == aspect_type_id:
            table_tag = GovernanceTag(**aspect.get("data", {}))
        elif suffix.startswith(f"{aspect_type_id}@Schema."):
            column = suffix.split("@Schema.", 1)[1]
            column_tags[column] = GovernanceTag(**aspect.get("data", {}))
    return table_tag, column_tags


def _parse_glossary_links(
    entry: dict[str, Any], aspect_type_id: str
) -> tuple[LinkedGlossaryTerm | None, dict[str, LinkedGlossaryTerm]]:
    table_link: LinkedGlossaryTerm | None = None
    column_links: dict[str, LinkedGlossaryTerm] = {}
    for key, aspect in entry.get("aspects", {}).items():
        suffix = key.split(".", 2)[-1] if "." in key else key
        if suffix == aspect_type_id:
            table_link = LinkedGlossaryTerm(**aspect.get("data", {}))
        elif suffix.startswith(f"{aspect_type_id}@Schema."):
            column = suffix.split("@Schema.", 1)[1]
            column_links[column] = LinkedGlossaryTerm(**aspect.get("data", {}))
    return table_link, column_links


def _schema_fields(entry: dict[str, Any]) -> list[CatalogColumnSchema]:
    for key, aspect in entry.get("aspects", {}).items():
        if key.endswith(".schema"):
            return [
                CatalogColumnSchema(name=f["name"], data_type=f.get("dataType", "UNKNOWN"), mode=f.get("mode", ""))
                for f in aspect.get("data", {}).get("fields", [])
            ]
    return []


# ============================================================================
# Routes: browse / search
# ============================================================================


@router.get("/tables", response_model=list[CatalogTableSummary])
async def list_tables(dataset: str = "healthcare_insurance") -> list[CatalogTableSummary]:
    client = _get_catalog_client()
    try:
        entries = await run_in_threadpool(client.list_bigquery_entries, dataset)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    summaries = []
    for entry in entries:
        source = entry.get("entrySource", {})
        table_name = entry["name"].rsplit("/tables/", 1)[-1]
        summaries.append(
            CatalogTableSummary(
                display_name=source.get("displayName", table_name),
                dataset=dataset,
                table=table_name,
                fully_qualified_name=entry.get("fullyQualifiedName", ""),
            )
        )
    return sorted(summaries, key=lambda s: s.table)


@router.get("/search", response_model=list[CatalogTableSummary])
async def search_catalog(q: str) -> list[CatalogTableSummary]:
    if not q.strip():
        return []
    client = _get_catalog_client()
    try:
        results = await run_in_threadpool(client.search_entries, q)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    summaries = []
    for entry in results:
        source = entry.get("entrySource", {})
        resource = source.get("resource", "")
        if "/tables/" not in resource:
            continue
        dataset = resource.split("/datasets/", 1)[-1].split("/tables/")[0]
        table_name = resource.rsplit("/tables/", 1)[-1]
        summaries.append(
            CatalogTableSummary(
                display_name=source.get("displayName", table_name),
                dataset=dataset,
                table=table_name,
                fully_qualified_name=entry.get("fullyQualifiedName", ""),
            )
        )
    return summaries


@router.get("/tables/{dataset}/{table}", response_model=CatalogTableDetail)
async def get_table_detail(dataset: str, table: str) -> CatalogTableDetail:
    client = _get_catalog_client()
    try:
        entry = await run_in_threadpool(client.get_table_entry, dataset, table)
        aspect_type_id = await run_in_threadpool(client.ensure_governance_aspect_type)
        link_aspect_type_id = await run_in_threadpool(client.ensure_glossary_link_aspect_type)
    except CatalogEntryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    table_tag, column_tags = _parse_governance_tags(entry, aspect_type_id)
    table_link, column_links = _parse_glossary_links(entry, link_aspect_type_id)
    return CatalogTableDetail(
        display_name=entry.get("entrySource", {}).get("displayName", table),
        dataset=dataset,
        table=table,
        fully_qualified_name=entry.get("fullyQualifiedName", ""),
        columns=_schema_fields(entry),
        table_tag=table_tag,
        column_tags=column_tags,
        table_glossary_link=table_link,
        column_glossary_links=column_links,
    )


# ============================================================================
# Routes: governance tags
# ============================================================================


def _touches_high_pii(old_tag: GovernanceTag | None, new_pii_level: str | None) -> bool:
    """HIGH is the one tier with real, BigQuery-enforced consequences (see catalog_access.py) — both
    setting AND removing/downgrading it are gated behind approval, since un-restricting a column is
    just as consequential as restricting one."""
    was_high = old_tag is not None and old_tag.pii_level == "HIGH"
    will_be_high = new_pii_level == "HIGH"
    return was_high or will_be_high


async def _apply_tag_upsert(dataset: str, table: str, column: str | None, tag_data: dict[str, Any]) -> None:
    client = _get_catalog_client()
    access_client = _get_access_client()
    try:
        await run_in_threadpool(client.upsert_governance_aspect, dataset, table, column, tag_data)
        if column:
            level = tag_data.get("pii_level")
            if level == "HIGH":
                await run_in_threadpool(access_client.apply_restriction, dataset, table, column, "HIGH")
            else:
                await run_in_threadpool(access_client.remove_restriction, dataset, table, column)
    except (CatalogClientError, AccessControlError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


async def _apply_tag_delete(dataset: str, table: str, column: str | None) -> None:
    client = _get_catalog_client()
    access_client = _get_access_client()
    try:
        await run_in_threadpool(client.remove_governance_aspect, dataset, table, column)
        if column:
            await run_in_threadpool(access_client.remove_restriction, dataset, table, column)
    except (CatalogClientError, AccessControlError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.put("/tables/{dataset}/{table}/tags", response_model=TagUpsertResult)
async def upsert_tag(dataset: str, table: str, request: TagUpsertRequest) -> TagUpsertResult:
    audit = _get_audit_log()

    before = await get_table_detail(dataset, table)
    old_tag = before.column_tags.get(request.column) if request.column else before.table_tag
    new_tag_data = {
        "data_owner": request.data_owner,
        "pii_level": request.pii_level,
        "retention_days": request.retention_days,
        "notes": request.notes,
    }

    if request.column and _touches_high_pii(old_tag, request.pii_level):
        approvals = _get_approval_queue()
        approval_id = await run_in_threadpool(
            approvals.propose, dataset, table, request.column, "UPSERT", new_tag_data, request.changed_by
        )
        return TagUpsertResult(
            status="PENDING_APPROVAL",
            approval_id=approval_id,
            message="This change sets or removes a HIGH-PII restriction and needs a second approval before it's applied.",
        )

    await _apply_tag_upsert(dataset, table, request.column, new_tag_data)
    await run_in_threadpool(
        audit.record,
        dataset,
        table,
        request.column,
        "UPSERT",
        old_tag.model_dump() if old_tag else None,
        new_tag_data,
        request.changed_by,
    )
    return TagUpsertResult(status="APPLIED", detail=await get_table_detail(dataset, table))


@router.delete("/tables/{dataset}/{table}/tags", response_model=TagUpsertResult)
async def delete_tag(dataset: str, table: str, column: str | None = None, changed_by: str = "") -> TagUpsertResult:
    audit = _get_audit_log()

    before = await get_table_detail(dataset, table)
    old_tag = before.column_tags.get(column) if column else before.table_tag

    if column and _touches_high_pii(old_tag, None):
        approvals = _get_approval_queue()
        approval_id = await run_in_threadpool(approvals.propose, dataset, table, column, "DELETE", None, changed_by)
        return TagUpsertResult(
            status="PENDING_APPROVAL",
            approval_id=approval_id,
            message="Removing this HIGH-PII tag lifts a real access restriction and needs a second approval.",
        )

    await _apply_tag_delete(dataset, table, column)
    if old_tag is not None:
        await run_in_threadpool(audit.record, dataset, table, column, "DELETE", old_tag.model_dump(), None, changed_by)
    return TagUpsertResult(status="APPLIED", detail=await get_table_detail(dataset, table))


@router.get("/tables/{dataset}/{table}/tags/history", response_model=AuditHistoryResponse)
async def get_tag_history(dataset: str, table: str, limit: int = 50) -> AuditHistoryResponse:
    audit = _get_audit_log()
    try:
        entries = await run_in_threadpool(audit.list_for_table, dataset, table, limit)
    except Exception as exc:  # noqa: BLE001 - surface BigQuery failures as a clean 502
        logger.exception("Failed to load audit history for %s.%s", dataset, table)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to load history: {exc}") from exc
    return AuditHistoryResponse(
        entries=[
            AuditEntryResponse(
                audit_id=e.audit_id,
                column_name=e.column_name,
                action=e.action,
                old_value=e.old_value,
                new_value=e.new_value,
                changed_by=e.changed_by,
                changed_at=e.changed_at,
            )
            for e in entries
        ]
    )


# ============================================================================
# Routes: glossary term links
# ============================================================================


@router.put("/tables/{dataset}/{table}/glossary-link", response_model=CatalogTableDetail)
async def link_glossary_term(dataset: str, table: str, request: GlossaryLinkRequest) -> CatalogTableDetail:
    client = _get_catalog_client()
    try:
        await run_in_threadpool(
            client.link_glossary_term, dataset, table, request.column, request.term_id, request.term_display_name
        )
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return await get_table_detail(dataset, table)


@router.delete("/tables/{dataset}/{table}/glossary-link", response_model=CatalogTableDetail)
async def unlink_glossary_term(dataset: str, table: str, column: str | None = None) -> CatalogTableDetail:
    client = _get_catalog_client()
    try:
        await run_in_threadpool(client.unlink_glossary_term, dataset, table, column)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return await get_table_detail(dataset, table)


# ============================================================================
# Routes: business glossary
# ============================================================================


@router.get("/glossary", response_model=list[GlossaryTermResponse])
async def list_glossary_terms() -> list[GlossaryTermResponse]:
    client = _get_catalog_client()
    try:
        terms = await run_in_threadpool(client.list_terms)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [GlossaryTermResponse(term_id=t.term_id, display_name=t.display_name, description=t.description) for t in terms]


@router.post("/glossary", response_model=GlossaryTermResponse, status_code=status.HTTP_201_CREATED)
async def create_glossary_term(request: GlossaryTermCreateRequest) -> GlossaryTermResponse:
    client = _get_catalog_client()
    try:
        term = await run_in_threadpool(client.create_term, request.term_id, request.display_name, request.description)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GlossaryTermResponse(term_id=term.term_id, display_name=term.display_name, description=term.description)


@router.delete("/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(term_id: str) -> None:
    client = _get_catalog_client()
    try:
        await run_in_threadpool(client.delete_term, term_id)
    except CatalogEntryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


# ============================================================================
# Routes: PII detection (Cloud DLP)
# ============================================================================


@router.post("/tables/{dataset}/{table}/pii-scan", response_model=PiiScanResponse)
async def scan_table_for_pii(dataset: str, table: str, sample_size: int = 200) -> PiiScanResponse:
    scanner = _get_dlp_scanner()
    try:
        result = await run_in_threadpool(scanner.scan_table, dataset, table, sample_size)
    except Exception as exc:  # noqa: BLE001 - surface DLP/BigQuery failures as a clean 502
        logger.exception("PII scan failed for %s.%s", dataset, table)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"PII scan failed: {exc}") from exc

    return PiiScanResponse(
        dataset=result.dataset,
        table=result.table,
        rows_scanned=result.rows_scanned,
        columns=[
            PiiColumnFinding(
                column=c.column, info_type_counts=c.info_type_counts, recommended_pii_level=c.recommended_pii_level
            )
            for c in result.columns
        ],
    )


# ============================================================================
# Routes: data quality (Dataplex Datascans)
# ============================================================================


@router.post("/tables/{dataset}/{table}/profile", status_code=status.HTTP_202_ACCEPTED)
async def trigger_profile_scan(dataset: str, table: str) -> dict[str, str]:
    client = _get_catalog_client()
    try:
        job_id = await run_in_threadpool(client.run_profile_scan, dataset, table)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "RUNNING"}


@router.get("/tables/{dataset}/{table}/profile", response_model=DataProfileResponse)
async def get_profile_result(dataset: str, table: str) -> DataProfileResponse:
    client = _get_catalog_client()
    try:
        result = await run_in_threadpool(client.get_latest_profile_result, dataset, table)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if result is None:
        return DataProfileResponse(state="NOT_RUN")

    state = result.get("state", "UNKNOWN")
    profile = result.get("dataProfileResult", {}).get("profile", {})
    fields = profile.get("fields", [])
    row_count = result.get("dataProfileResult", {}).get("rowCount")
    return DataProfileResponse(state=state, rows_scanned=int(row_count) if row_count else None, fields=fields)


# ============================================================================
# Routes: data quality rules (validation, not just profiling)
# ============================================================================


@router.get("/tables/{dataset}/{table}/quality/rules", response_model=QualityRuleListResponse)
async def list_quality_rules(dataset: str, table: str) -> QualityRuleListResponse:
    client = _get_catalog_client()
    try:
        rules = await run_in_threadpool(client.get_quality_rules, dataset, table)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _rules_to_response(rules)


@router.post("/tables/{dataset}/{table}/quality/rules", response_model=QualityRuleListResponse, status_code=status.HTTP_201_CREATED)
async def add_quality_rule(dataset: str, table: str, request: QualityRuleRequest) -> QualityRuleListResponse:
    client = _get_catalog_client()
    rule = QualityRule(
        column=request.column,
        dimension=request.dimension,
        rule_type=request.rule_type,
        threshold=request.threshold,
        min_value=request.min_value,
        max_value=request.max_value,
        regex=request.regex,
        set_values=request.set_values,
    )
    try:
        rules = await run_in_threadpool(client.add_quality_rule, dataset, table, rule)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _rules_to_response(rules)


@router.delete("/tables/{dataset}/{table}/quality/rules/{index}", response_model=QualityRuleListResponse)
async def delete_quality_rule(dataset: str, table: str, index: int) -> QualityRuleListResponse:
    client = _get_catalog_client()
    try:
        rules = await run_in_threadpool(client.delete_quality_rule, dataset, table, index)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _rules_to_response(rules)


@router.post("/tables/{dataset}/{table}/quality/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_quality_scan(dataset: str, table: str) -> dict[str, str]:
    client = _get_catalog_client()
    try:
        rules = await run_in_threadpool(client.get_quality_rules, dataset, table)
        if not rules:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No quality rules defined for this table yet — add at least one rule first.",
            )
        job_id = await run_in_threadpool(client.run_quality_scan, dataset, table)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "RUNNING"}


@router.get("/tables/{dataset}/{table}/quality/result", response_model=QualityScanResponse)
async def get_quality_result(dataset: str, table: str) -> QualityScanResponse:
    client = _get_catalog_client()
    try:
        result = await run_in_threadpool(client.get_latest_quality_result, dataset, table)
    except CatalogClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if result is None:
        return QualityScanResponse(state="NOT_RUN")

    state = result.get("state", "UNKNOWN")
    dq = result.get("dataQualityResult", {})
    row_count = dq.get("rowCount")
    rule_results = [
        QualityRuleResultItem(
            column=r.get("rule", {}).get("column", ""),
            dimension=r.get("rule", {}).get("dimension", ""),
            passed=r.get("passed", False),
            pass_ratio=r.get("passRatio", 0.0),
            passed_count=int(r.get("passedCount", 0)),
            evaluated_count=int(r.get("evaluatedCount", 0)),
            failing_rows_query=r.get("failingRowsQuery"),
        )
        for r in dq.get("rules", [])
    ]
    return QualityScanResponse(
        state=state,
        passed=dq.get("passed"),
        score=dq.get("score"),
        row_count=int(row_count) if row_count else None,
        rules=rule_results,
    )


# ============================================================================
# Routes: lineage
# ============================================================================


@router.get("/lineage", response_model=LineageResponse)
async def get_lineage() -> LineageResponse:
    graph = get_pipeline_lineage()
    return LineageResponse(
        nodes=graph["nodes"],
        edges=[LineageEdgeResponse(**e) for e in graph["edges"]],
    )


# ============================================================================
# Routes: real column-level access control (BigQuery Policy Tags)
# ============================================================================


@router.get("/tables/{dataset}/{table}/access/{column}", response_model=AccessRestrictionResponse)
async def get_column_access(dataset: str, table: str, column: str) -> AccessRestrictionResponse:
    access_client = _get_access_client()
    try:
        level = await run_in_threadpool(access_client.get_restriction, dataset, table, column)
        readers = await run_in_threadpool(access_client.list_readers, level) if level else []
    except AccessControlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return AccessRestrictionResponse(dataset=dataset, table=table, column=column, level=level, readers=readers)


@router.post("/tables/{dataset}/{table}/access/{column}/readers", response_model=AccessRestrictionResponse)
async def grant_column_reader(dataset: str, table: str, column: str, request: ReaderGrantRequest) -> AccessRestrictionResponse:
    access_client = _get_access_client()
    try:
        level = await run_in_threadpool(access_client.get_restriction, dataset, table, column)
        if level is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This column has no active restriction — there's nothing to grant reader access to.",
            )
        await run_in_threadpool(access_client.grant_reader, level, request.principal)
        readers = await run_in_threadpool(access_client.list_readers, level)
    except AccessControlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return AccessRestrictionResponse(dataset=dataset, table=table, column=column, level=level, readers=readers)


@router.delete("/tables/{dataset}/{table}/access/{column}/readers", response_model=AccessRestrictionResponse)
async def revoke_column_reader(dataset: str, table: str, column: str, principal: str) -> AccessRestrictionResponse:
    access_client = _get_access_client()
    try:
        level = await run_in_threadpool(access_client.get_restriction, dataset, table, column)
        if level is not None:
            await run_in_threadpool(access_client.revoke_reader, level, principal)
        readers = await run_in_threadpool(access_client.list_readers, level) if level else []
    except AccessControlError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AccessRestrictionResponse(dataset=dataset, table=table, column=column, level=level, readers=readers)


# ============================================================================
# Routes: pending approvals (HIGH-PII change gate)
# ============================================================================


@router.get("/approvals", response_model=list[PendingApprovalResponse])
async def list_pending_approvals(dataset: str | None = None, table: str | None = None) -> list[PendingApprovalResponse]:
    queue = _get_approval_queue()
    approvals = await run_in_threadpool(queue.list_pending, dataset, table)
    return [
        PendingApprovalResponse(
            approval_id=a.approval_id,
            dataset=a.dataset,
            table_name=a.table_name,
            column_name=a.column_name,
            action=a.action,
            proposed_data=a.proposed_data,
            status=a.status,
            proposed_by=a.proposed_by,
            proposed_at=a.proposed_at,
            reviewed_by=a.reviewed_by,
            reviewed_at=a.reviewed_at,
        )
        for a in approvals
    ]


async def _resolve_approval(approval_id: str, decision: str, request: ApprovalResolutionRequest) -> PendingApprovalResponse:
    queue = _get_approval_queue()
    try:
        approval = await run_in_threadpool(queue.resolve, approval_id, decision, request.reviewed_by)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApprovalNotPendingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if decision == "APPROVED":
        audit = _get_audit_log()
        old_tag_entry = await get_table_detail(approval.dataset, approval.table_name)
        old_tag = old_tag_entry.column_tags.get(approval.column_name) if approval.column_name else None

        if approval.action == "UPSERT" and approval.proposed_data:
            await _apply_tag_upsert(approval.dataset, approval.table_name, approval.column_name, approval.proposed_data)
        elif approval.action == "DELETE":
            await _apply_tag_delete(approval.dataset, approval.table_name, approval.column_name)

        await run_in_threadpool(
            audit.record,
            approval.dataset,
            approval.table_name,
            approval.column_name,
            approval.action,
            old_tag.model_dump() if old_tag else None,
            approval.proposed_data,
            approval.reviewed_by or "unknown",
        )

    return PendingApprovalResponse(
        approval_id=approval.approval_id,
        dataset=approval.dataset,
        table_name=approval.table_name,
        column_name=approval.column_name,
        action=approval.action,
        proposed_data=approval.proposed_data,
        status=approval.status,
        proposed_by=approval.proposed_by,
        proposed_at=approval.proposed_at,
        reviewed_by=approval.reviewed_by,
        reviewed_at=approval.reviewed_at,
    )


@router.post("/approvals/{approval_id}/approve", response_model=PendingApprovalResponse)
async def approve_change(approval_id: str, request: ApprovalResolutionRequest) -> PendingApprovalResponse:
    return await _resolve_approval(approval_id, "APPROVED", request)


@router.post("/approvals/{approval_id}/reject", response_model=PendingApprovalResponse)
async def reject_change(approval_id: str, request: ApprovalResolutionRequest) -> PendingApprovalResponse:
    return await _resolve_approval(approval_id, "REJECTED", request)
