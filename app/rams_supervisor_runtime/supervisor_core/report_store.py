from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol


class DynamoTable(Protocol):
    def put_item(self, *, Item: dict[str, Any]) -> Any:  # noqa: N803 - boto3 API casing
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


def build_report_store_item(output: dict[str, Any]) -> dict[str, Any]:
    case_id = _text(output.get("caseId"))
    if not case_id:
        raise ReportStoreError("caseId is required before writing a report store item.")

    run = output.get("run") if isinstance(output.get("run"), dict) else {}
    report = output.get("structuredReport") if isinstance(output.get("structuredReport"), dict) else {}
    safety = run.get("safety") if isinstance(run.get("safety"), dict) else {}
    location = run.get("location") if isinstance(run.get("location"), dict) else {}
    briefing = run.get("briefing") if isinstance(run.get("briefing"), dict) else {}

    item = {
        "caseId": case_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "reportId": _text(report.get("reportId")) or _text(run.get("runId")),
        "reportStatus": _text(output.get("reportStatus")) or _text(report.get("status")) or "unknown",
        "workflowMode": _text(output.get("workflowMode")) or _text(report.get("workflowMode")) or "unknown",
        "siteLabel": _text(location.get("label")) or _report_site_label(report),
        "safetyLevel": _text(safety.get("level")) or _report_safety_level(report),
        "reviewGateStatus": _report_review_gate_status(report),
        "evidenceCount": len(run.get("evidence") or []),
        "traceCount": len(run.get("trace") or []),
        "structuredReport": report,
        "runSummary": {
            "runId": _text(run.get("runId")),
            "runtime": run.get("runtime") if isinstance(run.get("runtime"), dict) else {},
            "location": location,
            "briefingHeadline": _text(briefing.get("headline")),
        },
    }
    return _dynamo_safe(item)


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


def _dynamo_safe(value: Any) -> Any:
    return json.loads(json.dumps(value), parse_float=Decimal)


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


def _report_review_gate_status(report: dict[str, Any]) -> str | None:
    review_gate = report.get("reviewGate") if isinstance(report.get("reviewGate"), dict) else {}
    return _text(review_gate.get("status"))
