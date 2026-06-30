from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rams_agent_tools.tools import SUPERVISOR_HARNESS_SUBAGENTS, harness_for_group


HARNESS_OUTPUT_SCHEMA_VERSION = "3d-rams.harness-output.v1"

HARNESS_OUTPUT_STATUSES = {"ok", "warning", "fallback", "blocked"}
HARNESS_TRACE_STATUSES = {"ok", "warning", "fallback", "blocked", "disabled"}

DOMAIN_DATA_KEYS = {
    "geospatial_subagent": ["location", "features", "scene"],
    "planning_subagent": ["planningText"],
    "hazard_subagent": ["hazards"],
    "annotation_subagent": ["annotations"],
    "briefing_subagent": ["briefing", "evidence", "bedrockStatus", "bedrockFallbackReason"],
    "review_guardrail": ["safety"],
}


def build_harness_output(
    group: str,
    *,
    status: str,
    summary: str,
    data: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    trace: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
    warnings: list[Any] | None = None,
    errors: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    subagent = SUPERVISOR_HARNESS_SUBAGENTS.get(group, {})
    now = datetime.now(timezone.utc).isoformat()
    envelope_metadata = {
        "caseId": None,
        "fixturePack": None,
        "mode": "fixture",
        "generatedAt": now,
    }
    if metadata:
        envelope_metadata.update(metadata)
    envelope_metadata.setdefault("generatedAt", now)

    return {
        "schemaVersion": HARNESS_OUTPUT_SCHEMA_VERSION,
        "subagent": {
            "name": group,
            "harness": str(subagent.get("harness") or harness_for_group(group) or ""),
            "phase": str(subagent.get("phase") or ""),
        },
        "status": status if status in HARNESS_OUTPUT_STATUSES else "warning",
        "summary": summary,
        "data": data,
        "evidence": evidence or [],
        "findings": findings or [],
        "trace": trace or [],
        "references": references or [],
        "warnings": warnings or [],
        "errors": errors or [],
        "metadata": envelope_metadata,
    }


def validate_harness_output(
    value: Any,
    *,
    expected_group: str | None = None,
    required_data_keys: list[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    if not isinstance(value, dict):
        return ["Harness output must be a JSON object."]

    if value.get("schemaVersion") != HARNESS_OUTPUT_SCHEMA_VERSION:
        issues.append(f"schemaVersion must be {HARNESS_OUTPUT_SCHEMA_VERSION}.")

    subagent = _dict(value.get("subagent"))
    if not subagent:
        issues.append("subagent must be an object.")
    else:
        if not isinstance(subagent.get("name"), str) or not subagent.get("name"):
            issues.append("subagent.name must be a non-empty string.")
        if not isinstance(subagent.get("harness"), str) or not subagent.get("harness"):
            issues.append("subagent.harness must be a non-empty string.")
        if not isinstance(subagent.get("phase"), str) or not subagent.get("phase"):
            issues.append("subagent.phase must be a non-empty string.")
        if expected_group and subagent.get("name") != expected_group:
            issues.append(f"subagent.name must be {expected_group}.")
        expected_harness = harness_for_group(expected_group or "")
        if expected_harness and subagent.get("harness") != expected_harness:
            issues.append(f"subagent.harness must be {expected_harness}.")

    if value.get("status") not in HARNESS_OUTPUT_STATUSES:
        issues.append("status must be one of ok, warning, fallback, blocked.")
    if not isinstance(value.get("summary"), str) or not value.get("summary"):
        issues.append("summary must be a non-empty string.")

    data = _dict(value.get("data"))
    if not data:
        issues.append("data must be an object.")
    keys = required_data_keys if required_data_keys is not None else DOMAIN_DATA_KEYS.get(expected_group or "", [])
    missing_data_keys = [key for key in keys if key not in data]
    if missing_data_keys:
        issues.append(f"data missing required keys: {', '.join(missing_data_keys)}.")
    if expected_group == "review_guardrail":
        safety = data.get("safety")
        if not isinstance(safety, dict):
            issues.append("data.safety must be an object.")
        elif not isinstance(safety.get("allowed"), bool):
            issues.append("data.safety.allowed must be a boolean.")

    for field in ("evidence", "findings", "trace", "references", "warnings", "errors"):
        if not isinstance(value.get(field), list):
            issues.append(f"{field} must be a list.")

    for index, item in enumerate(value.get("evidence") or []):
        if not isinstance(item, dict):
            issues.append(f"evidence[{index}] must be an object.")
    for index, item in enumerate(value.get("findings") or []):
        issues.extend(_finding_issues(item, index))
    for index, item in enumerate(value.get("trace") or []):
        issues.extend(_trace_issues(item, index))
    for index, item in enumerate(value.get("references") or []):
        if not isinstance(item, dict):
            issues.append(f"references[{index}] must be an object.")

    metadata = _dict(value.get("metadata"))
    if not metadata:
        issues.append("metadata must be an object.")
    else:
        if "caseId" not in metadata:
            issues.append("metadata.caseId must be present.")
        if not isinstance(metadata.get("mode"), str) or not metadata.get("mode"):
            issues.append("metadata.mode must be a non-empty string.")
        if not isinstance(metadata.get("generatedAt"), str) or not metadata.get("generatedAt"):
            issues.append("metadata.generatedAt must be a non-empty ISO-8601 string.")

    return issues


def harness_data(envelope: dict[str, Any]) -> dict[str, Any]:
    return _dict(envelope.get("data"))


def harness_fallback_issues(envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for envelope in envelopes:
        metadata = _dict(envelope.get("metadata"))
        validation_issues = metadata.get("contractValidationIssues")
        if not validation_issues:
            continue
        issues.append(
            {
                "subagent": _dict(envelope.get("subagent")).get("name"),
                "harness": _dict(envelope.get("subagent")).get("harness"),
                "issues": [str(item) for item in validation_issues],
            }
        )
    return issues


def harness_contract_summary(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    fallback_issues = harness_fallback_issues(envelopes)
    return {
        "schemaVersion": HARNESS_OUTPUT_SCHEMA_VERSION,
        "requiredSubagents": list(DOMAIN_DATA_KEYS.keys()),
        "observedSubagents": [
            str(_dict(envelope.get("subagent")).get("name") or "unknown")
            for envelope in envelopes
        ],
        "contractCompliant": not fallback_issues,
        "fallbackCount": len(fallback_issues),
        "issues": fallback_issues,
    }


def finding_from_hazard(hazard: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(hazard.get("id") or "unknown-finding"),
        "title": str(hazard.get("title") or hazard.get("id") or "Unknown finding"),
        "category": str(hazard.get("category") or "other"),
        "description": str(hazard.get("description") or hazard.get("note") or ""),
        "confidence": str(hazard.get("confidence") or "unknown"),
        "sourceIds": _strings(hazard.get("sourceIds")),
        "evidenceIds": _strings(hazard.get("evidenceIds")),
        "traceIds": _strings(hazard.get("traceIds")),
        "humanReviewRequired": bool(hazard.get("humanReviewRequired", True)),
    }


def _trace_issues(item: Any, index: int) -> list[str]:
    if not isinstance(item, dict):
        return [f"trace[{index}] must be an object."]
    issues: list[str] = []
    for field in ("id", "name", "summary", "startedAt", "endedAt"):
        if not isinstance(item.get(field), str) or not item.get(field):
            issues.append(f"trace[{index}].{field} must be a non-empty string.")
    if item.get("status") not in HARNESS_TRACE_STATUSES:
        issues.append(f"trace[{index}].status must be a valid trace status.")
    if not isinstance(item.get("durationMs"), int):
        issues.append(f"trace[{index}].durationMs must be an integer.")
    for field in ("sourceIds", "evidenceIds"):
        if not isinstance(item.get(field), list):
            issues.append(f"trace[{index}].{field} must be a list.")
    return issues


def _finding_issues(item: Any, index: int) -> list[str]:
    if not isinstance(item, dict):
        return [f"findings[{index}] must be an object."]
    issues: list[str] = []
    for field in ("id", "title", "category", "description", "confidence"):
        if not isinstance(item.get(field), str):
            issues.append(f"findings[{index}].{field} must be a string.")
    for field in ("sourceIds", "evidenceIds", "traceIds"):
        if not isinstance(item.get(field), list):
            issues.append(f"findings[{index}].{field} must be a list.")
    if not isinstance(item.get("humanReviewRequired"), bool):
        issues.append(f"findings[{index}].humanReviewRequired must be a boolean.")
    return issues


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
