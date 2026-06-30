from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from .report_access import (
    authorize_report_lookup,
    build_report_access_binding,
)


class DynamoTable(Protocol):
    def put_item(self, *, Item: dict[str, Any]) -> Any:  # noqa: N803 - boto3 API casing
        ...

    def get_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:  # noqa: N803 - boto3 API casing
        ...


class ReportStoreError(RuntimeError):
    pass


def persist_report(
    output: dict[str, Any],
    *,
    table: DynamoTable | None = None,
    table_name: str | None = None,
) -> dict[str, Any]:
    resolved_table_name = table_name or os.getenv("RAMS_REPORT_STORE_TABLE")
    if not resolved_table_name and table is None:
        return {"mode": "disabled", "status": "skipped", "reason": "RAMS_REPORT_STORE_TABLE is not set."}

    try:
        item = build_report_store_item(output)
        dynamo_table = table or _dynamodb_table(str(resolved_table_name))
        dynamo_table.put_item(Item=item)
        return {
            "mode": "dynamodb",
            "status": "stored",
            "tableName": resolved_table_name,
            "caseId": item["caseId"],
            "updatedAt": item["updatedAt"],
        }
    except Exception as exc:  # noqa: BLE001 - persistence must not hide the report payload.
        return {
            "mode": "dynamodb",
            "status": "error",
            "tableName": resolved_table_name,
            "caseId": output.get("caseId"),
            "message": str(exc),
        }


def load_report(
    case_id: str,
    *,
    access_context: dict[str, Any] | None = None,
    table: DynamoTable | None = None,
    table_name: str | None = None,
    dev_access_allowed: bool | None = None,
) -> dict[str, Any]:
    resolved_table_name = table_name or os.getenv("RAMS_REPORT_STORE_TABLE")
    access_decision = authorize_report_lookup(
        case_id,
        access_context,
        dev_lookup_allowed=_dev_lookup_allowed(resolved_table_name, table, dev_access_allowed),
    )
    if access_decision["status"] != "authorized":
        return _access_denied_response(case_id, access_decision)

    if not resolved_table_name and table is None:
        return {
            "output": {
                "caseId": case_id,
                "reportStatus": "not_found",
                "workflowMode": "report_lookup",
                "reportAccess": access_decision,
                "persistence": {
                    "mode": "disabled",
                    "status": "skipped",
                    "reason": "RAMS_REPORT_STORE_TABLE is not set.",
                    "caseId": case_id,
                },
            }
        }

    try:
        dynamo_table = table or _dynamodb_table(str(resolved_table_name))
        response = dynamo_table.get_item(Key={"caseId": case_id})
        item = response.get("Item") if isinstance(response, dict) else None
        if not isinstance(item, dict):
            return {
                "output": {
                    "caseId": case_id,
                    "reportStatus": "not_found",
                    "workflowMode": "report_lookup",
                    "reportAccess": access_decision,
                    "persistence": {
                        "mode": "dynamodb",
                        "status": "not_found",
                        "tableName": resolved_table_name,
                        "caseId": case_id,
                    },
                }
            }
        binding_decision = authorize_report_lookup(
            case_id,
            access_context,
            stored_binding=item.get("reportAccessBinding") if isinstance(item, dict) else None,
            dev_lookup_allowed=_dev_lookup_allowed(resolved_table_name, table, dev_access_allowed),
        )
        if binding_decision["status"] != "authorized":
            return _access_denied_response(case_id, binding_decision)

        return _json_safe(
            {
                "output": {
                    "caseId": case_id,
                    "reportStatus": item.get("reportStatus") or "unknown",
                    "workflowMode": item.get("workflowMode") or "report_lookup",
                    "structuredReport": item.get("structuredReport"),
                    "run": item.get("run"),
                    "reportAccess": binding_decision,
                    "reviewGate": item.get("reviewGate"),
                    "reviewMetadata": item.get("reviewMetadata"),
                    "evidenceSummary": item.get("evidenceSummary"),
                    "materialEvidenceSummary": item.get("materialEvidenceSummary"),
                    "citationMetadata": item.get("citationMetadata"),
                    "traceSummary": item.get("traceSummary"),
                    "persistence": {
                        "mode": "dynamodb",
                        "status": "loaded",
                        "tableName": resolved_table_name,
                        "caseId": case_id,
                        "updatedAt": item.get("updatedAt"),
                    },
                }
            }
        )
    except Exception as exc:  # noqa: BLE001 - lookup errors should be visible to the caller.
        return {
            "output": {
                "caseId": case_id,
                "reportStatus": "lookup_error",
                "workflowMode": "report_lookup",
                "reportAccess": access_decision,
                "persistence": {
                    "mode": "dynamodb",
                    "status": "error",
                    "tableName": resolved_table_name,
                    "caseId": case_id,
                    "message": str(exc),
                },
            }
        }


def build_report_store_item(output: dict[str, Any]) -> dict[str, Any]:
    case_id = _text(output.get("caseId"))
    if not case_id:
        raise ReportStoreError("caseId is required before writing a report store item.")

    run = output.get("run") if isinstance(output.get("run"), dict) else {}
    report = output.get("structuredReport") if isinstance(output.get("structuredReport"), dict) else {}
    stored_run = _storage_safe_payload(run)
    stored_report = _storage_safe_payload(report)
    review_metadata = _review_metadata(case_id, report)
    safety = run.get("safety") if isinstance(run.get("safety"), dict) else {}
    location = run.get("location") if isinstance(run.get("location"), dict) else {}
    briefing = run.get("briefing") if isinstance(run.get("briefing"), dict) else {}
    material_ingestion = run.get("materialIngestion") if isinstance(run.get("materialIngestion"), dict) else {}

    item = {
        "schemaVersion": "3d-rams.report-store.v1",
        "recordType": "case-correlated-report-evidence",
        "caseId": case_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "reportId": _text(report.get("reportId")) or _text(run.get("runId")),
        "reportStatus": _text(output.get("reportStatus")) or _text(report.get("status")) or "unknown",
        "workflowMode": _text(output.get("workflowMode")) or _text(report.get("workflowMode")) or "unknown",
        "authorizationBinding": build_authorization_binding(output),
        "siteLabel": _text(location.get("label")) or _report_site_label(report),
        "safetyLevel": _text(safety.get("level")) or _report_safety_level(report),
        "reviewGateStatus": review_metadata.get("status"),
        "reviewDecision": review_metadata.get("decision"),
        "reviewerMode": review_metadata.get("reviewerMode"),
        "reviewRevisionCount": review_metadata.get("revisionCount"),
        "reviewGate": review_metadata,
        "reviewMetadata": review_metadata,
        "evidenceCount": len(run.get("evidence") or []),
        "materialReferenceCount": int(material_ingestion.get("received") or 0),
        "materialEvidenceCount": int(material_ingestion.get("accepted") or 0),
        "materialSkippedCount": int(material_ingestion.get("skippedCount") or 0),
        "materialIngestion": material_ingestion,
        "traceCount": len(run.get("trace") or []),
        "entryIntakeSummary": _entry_intake_summary(run, report),
        "evidenceSummary": _evidence_summary(run, report),
        "materialEvidenceSummary": _material_evidence_summary(run, report),
        "citationMetadata": _citation_metadata(run, report),
        "traceSummary": _trace_summary(run),
        "retention": _retention_metadata(),
        "redaction": {
            "rawPrivateMaterialPersisted": False,
            "rawAsiIdentityTokensPersisted": False,
            "signedMaterialUrlsPersisted": False,
            "notes": [
                "Persisted material data is limited to bounded references, summaries, and citations.",
                "caseId is a correlation id and not an authorization token.",
            ],
        },
        "structuredReport": stored_report,
        "run": stored_run,
        "runSummary": {
            "runId": _text(run.get("runId")),
            "runtime": run.get("runtime") if isinstance(run.get("runtime"), dict) else {},
            "location": location,
            "briefingHeadline": _text(briefing.get("headline")),
        },
    }
    report_access_binding = build_report_access_binding(output)
    if report_access_binding:
        item["reportAccessBinding"] = report_access_binding
    return _dynamo_safe(item)


def build_authorization_binding(output: dict[str, Any]) -> dict[str, Any]:
    run = output.get("run") if isinstance(output.get("run"), dict) else {}
    report = output.get("structuredReport") if isinstance(output.get("structuredReport"), dict) else {}
    case_id = _text(output.get("caseId")) or _text(run.get("caseId")) or _text(report.get("caseId"))
    upstream = _first_mapping(
        run.get("upstream"),
        _nested_mapping(report, "intake", "upstream"),
        output.get("upstream"),
    )
    request = run.get("request") if isinstance(run.get("request"), dict) else {}
    source = _text(upstream.get("source")) or _text(upstream.get("caller")) or "LOCAL_DIRECT"
    identity = upstream.get("identity") if isinstance(upstream.get("identity"), dict) else {}
    conversation_id = _text(upstream.get("conversationId")) or _text(upstream.get("sessionId")) or _text(identity.get("sessionRef"))
    entry_agent_id = _text(upstream.get("entryAgentId"))
    subject_ref = _identity_ref(upstream, "subjectRef", "subjectId", "userId", "asiSubject") or _identity_ref(
        identity, "subjectRef", "subjectId", "userId", "asiSubject"
    )
    organization_ref = _identity_ref(upstream, "organizationRef", "organizationId", "tenantId", "workspaceId") or _identity_ref(
        identity, "organizationRef", "organizationId", "tenantId", "workspaceId"
    )
    material_count = _int_or_none(upstream.get("materialCount"))
    if material_count is None:
        material_count = len(request.get("materials") or [])

    identity_bound = bool(conversation_id or subject_ref or organization_ref)
    return {
        "caseId": case_id,
        "mode": "asi_identity_bound" if identity_bound else "local_dev_unbound",
        "requiredForLookup": identity_bound,
        "source": source,
        "conversationId": conversation_id,
        "entryAgentId": entry_agent_id,
        "subjectRef": subject_ref,
        "organizationRef": organization_ref,
        "materialCount": material_count,
        "confirmedByUser": bool(upstream.get("confirmedByUser")) if upstream else None,
        "bindingStatus": "bound_to_entry_context" if identity_bound else "dev_unbound_record",
    }

def _dynamodb_table(table_name: str) -> DynamoTable:
    try:
        import boto3
    except ImportError as exc:
        raise ReportStoreError("boto3 is required when RAMS_REPORT_STORE_TABLE is set.") from exc

    session_kwargs: dict[str, str] = {}
    if os.getenv("AWS_PROFILE"):
        session_kwargs["profile_name"] = os.environ["AWS_PROFILE"]
    if os.getenv("AWS_REGION"):
        session_kwargs["region_name"] = os.environ["AWS_REGION"]
    session = boto3.Session(**session_kwargs)
    return session.resource("dynamodb").Table(table_name)


def _review_metadata(case_id: str, report: dict[str, Any]) -> dict[str, Any]:
    review_gate = report.get("reviewGate") if isinstance(report.get("reviewGate"), dict) else {}
    reviewer = review_gate.get("reviewer") if isinstance(review_gate.get("reviewer"), dict) else {}
    status = _text(review_gate.get("status")) or _text(report.get("status")) or "unknown"
    decision = _text(review_gate.get("decision")) or _decision_from_status(status)
    revision_count = _int_or_none(
        review_gate.get("revisionCount")
        if "revisionCount" in review_gate
        else review_gate.get("revision_count")
    )
    if revision_count is None:
        revision_count = len(review_gate.get("revisions") or [])

    metadata = {
        "schemaVersion": "3d-rams.review-metadata.v1",
        "caseId": case_id,
        "decision": decision,
        "status": status,
        "issues": _dict_list(review_gate.get("issues")),
        "caveats": _public_list(review_gate.get("caveats")),
        "revisionCount": revision_count,
        "reviewerMode": _text(review_gate.get("reviewerMode")) or _text(reviewer.get("mode")) or "deterministic",
        "requiresHumanReview": bool(review_gate.get("requiresHumanReview", True)),
        "safetyAllowed": bool(review_gate.get("safetyAllowed", False)),
        "safetyLevel": _text(review_gate.get("safetyLevel")),
        "message": _text(review_gate.get("message")),
    }
    reviewer_name = _text(reviewer.get("name")) or _text(review_gate.get("reviewerName"))
    if reviewer_name:
        metadata["reviewerName"] = reviewer_name
    return metadata


def _decision_from_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"passed", "pass"}:
        return "pass"
    if normalized in {"passed_with_caveats", "pass_with_caveats"}:
        return "pass_with_caveats"
    if normalized in {"blocked", "block"}:
        return "block"
    if normalized in {"revise", "revision_required"}:
        return "revise"
    return "pending"


def _entry_intake_summary(run: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    request = run.get("request") if isinstance(run.get("request"), dict) else {}
    intake = report.get("intake") if isinstance(report.get("intake"), dict) else {}
    return {
        "caseId": _text(request.get("caseId")) or _text(intake.get("caseId")) or _text(run.get("caseId")),
        "siteName": _text(request.get("siteName")) or _text(intake.get("siteName")),
        "goal": _text(request.get("goal")) or _text(intake.get("goal")),
        "fixturePack": _text(request.get("fixturePack")) or _text(intake.get("fixturePack")),
        "materialCount": len(request.get("materials") or intake.get("materials") or []),
        "upstream": _first_mapping(run.get("upstream"), intake.get("upstream")),
    }


def _evidence_summary(run: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = run.get("evidence")
    if not isinstance(evidence, list):
        evidence = _nested_mapping(report, "evidenceRegister").get("evidence", [])
    summaries = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        summaries.append(
            {
                "id": _text(item.get("id")),
                "title": _text(item.get("title")),
                "status": _text(item.get("status")),
                "confidence": _text(item.get("confidence")),
                "sourceIds": _string_list(item.get("sourceIds")),
                "freshness": _text(item.get("freshness")),
                "summary": _text(item.get("summary")) or _text(item.get("why_it_matters")),
            }
        )
    return [summary for summary in summaries if summary.get("id")]


def _material_evidence_summary(run: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    request = run.get("request") if isinstance(run.get("request"), dict) else {}
    intake = report.get("intake") if isinstance(report.get("intake"), dict) else {}
    materials = request.get("materials") or intake.get("materials") or []
    items = []
    for material in materials if isinstance(materials, list) else []:
        if not isinstance(material, dict):
            continue
        access = material.get("access") if isinstance(material.get("access"), dict) else {}
        items.append(
            {
                "materialId": _text(material.get("materialId")) or _text(material.get("id")),
                "sourceSystem": _text(material.get("sourceSystem")),
                "type": _text(material.get("type")),
                "label": _text(material.get("label")),
                "summary": _text(material.get("summary")),
                "caseId": _text(material.get("caseId")) or _text(request.get("caseId")) or _text(run.get("caseId")),
                "access": {
                    "mode": _text(access.get("mode")) or "reference_only",
                    "expiresAt": _text(access.get("expiresAt")),
                    "status": _text(access.get("status")) or "not_retrieved",
                },
                "sourceIds": _string_list(material.get("sourceIds")),
                "evidenceIds": _string_list(material.get("evidenceIds")),
            }
        )
    return {
        "status": "references_recorded" if items else "not_provided",
        "items": [item for item in items if item.get("materialId") or item.get("label")],
        "rawMaterialContentPersisted": False,
    }


def _citation_metadata(run: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    sources = run.get("sources")
    if not isinstance(sources, list):
        sources = _nested_mapping(report, "evidenceRegister").get("sources", [])
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    sections = report.get("sections") if isinstance(report.get("sections"), list) else []
    return {
        "sources": [_source_citation(source) for source in sources if isinstance(source, dict)],
        "findings": [_referenced_citation(finding) for finding in findings if isinstance(finding, dict)],
        "sections": [_referenced_citation(section) for section in sections if isinstance(section, dict)],
    }


def _trace_summary(run: dict[str, Any]) -> list[dict[str, Any]]:
    case_id = _text(run.get("caseId"))
    trace = run.get("trace") if isinstance(run.get("trace"), list) else []
    summaries = []
    for step in trace:
        if not isinstance(step, dict):
            continue
        aws_mapping = step.get("awsMapping") if isinstance(step.get("awsMapping"), dict) else {}
        summaries.append(
            {
                "id": _text(step.get("id")),
                "name": _text(step.get("name")),
                "status": _text(step.get("status")),
                "caseId": _text(step.get("caseId")) or case_id,
                "sourceIds": _string_list(step.get("sourceIds")),
                "evidenceIds": _string_list(step.get("evidenceIds")),
                "fallbackReason": _text(step.get("fallbackReason")),
                "cloudWatchSpanName": _text(aws_mapping.get("spanName")),
            }
        )
    return [summary for summary in summaries if summary.get("id")]


def _retention_metadata() -> dict[str, Any]:
    ttl_days = _int_or_none(os.getenv("RAMS_REPORT_STORE_TTL_DAYS"))
    return {
        "policy": "case_report_evidence_summary",
        "ttlDays": ttl_days,
        "rawPrivateMaterialsStoredElsewhere": True,
        "reviewRequiredBeforeOperationalUse": True,
    }


def _source_citation(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(source.get("id")),
        "label": _text(source.get("label")),
        "kind": _text(source.get("kind")),
        "status": _text(source.get("status")),
        "origin": _text(source.get("origin")),
        "freshness": _text(source.get("freshness")) or _text(source.get("freshness_note")),
        "confidence": _text(source.get("confidence")),
        "attribution": _text(source.get("attribution")),
        "trustBoundary": _text(source.get("trustBoundary")),
    }


def _referenced_citation(item: dict[str, Any]) -> dict[str, Any]:
    references = item.get("references") if isinstance(item.get("references"), dict) else item
    return {
        "id": _text(item.get("id")),
        "title": _text(item.get("title")),
        "status": _text(item.get("status")),
        "sourceIds": _string_list(references.get("sourceIds")),
        "evidenceIds": _string_list(references.get("evidenceIds")),
        "traceIds": _string_list(references.get("traceIds")),
    }


def _identity_ref(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _text(mapping.get(key))
        if not value:
            continue
        if key.endswith("Ref"):
            return value
        return "sha256:" + hashlib.sha256(f"3d-rams:{value}".encode("utf-8")).hexdigest()
    return None


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _nested_mapping(value: Any, *path: str) -> dict[str, Any]:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _public_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, (str, int, float, bool, dict))]


def _dynamo_safe(value: Any) -> Any:
    return json.loads(json.dumps(value), parse_float=Decimal)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _storage_safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in {"reportAccess", "reportAccessContext", "accessContext"}:
                cleaned[key] = {
                    "status": "redacted",
                    "reason": "stored_as_hashed_report_access_binding",
                }
            else:
                cleaned[key] = _storage_safe_payload(item)
        return cleaned
    if isinstance(value, list):
        return [_storage_safe_payload(item) for item in value]
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _report_site_label(report: dict[str, Any]) -> str | None:
    site = report.get("site") if isinstance(report.get("site"), dict) else {}
    return _text(site.get("label"))


def _report_safety_level(report: dict[str, Any]) -> str | None:
    review_gate = report.get("reviewGate") if isinstance(report.get("reviewGate"), dict) else {}
    return _text(review_gate.get("safetyLevel"))


def _access_denied_response(case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": {
            "caseId": case_id,
            "reportStatus": "access_denied",
            "workflowMode": "report_lookup",
            "reportAccess": decision,
            "persistence": {
                "mode": "authorization",
                "status": "denied",
                "caseId": case_id,
                "reason": decision.get("reason"),
            },
        }
    }


def _dev_lookup_allowed(
    resolved_table_name: str | None,
    table: DynamoTable | None,
    explicit: bool | None,
) -> bool:
    if explicit is not None:
        return explicit
    if os.getenv("RAMS_ENABLE_DEV_REPORT_LOOKUP", "").strip().lower() == "true":
        return True
    return not resolved_table_name and table is None
