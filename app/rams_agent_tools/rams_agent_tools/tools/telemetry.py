from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


AWS_TRACE_MAPPING = {
    "resolve_location": "CloudWatch span: tool.resolve_location",
    "load_geospatial_features": "CloudWatch span: tool.load_geospatial_features",
    "build_scene_config": "CloudWatch span: tool.build_scene_config",
    "load_planning_context": "CloudWatch span: tool.load_planning_context",
    "extract_hazard_notes": "Bedrock/CloudWatch span: tool.extract_hazard_notes",
    "ingest_material_references": "CloudWatch span: tool.ingest_material_references",
    "search_open_web_signals": "CloudWatch span: tool.search_open_web_signals",
    "create_annotations": "CloudWatch span: tool.create_annotations",
    "generate_site_brief": "Bedrock/CloudWatch span: tool.generate_site_brief",
    "plan_subagent_workflow": "Bedrock/CloudWatch span: supervisor.plan_subagent_workflow",
    "reason_over_evidence": "Bedrock/CloudWatch span: supervisor.reason_over_evidence",
    "generate_bedrock_briefing": "Bedrock/CloudWatch span: tool.generate_bedrock_briefing",
    "safety_gate": "Guardrails/CloudWatch span: tool.safety_gate",
}


def trace_step(
    name: str,
    status: str,
    summary: str,
    output: dict[str, Any],
    *,
    source_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    fallback_reason: str | None = None,
    duration_ms: int = 0,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"trace-{name}",
        "name": name,
        "type": "tool",
        "status": status,
        "summary": summary,
        "timestamp": timestamp,
        "startedAt": timestamp,
        "endedAt": timestamp,
        "durationMs": duration_ms,
        "sourceIds": source_ids or [],
        "evidenceIds": evidence_ids or [],
        "fallbackReason": fallback_reason,
        "awsMapping": {
            "service": "future AWS observability",
            "spanName": AWS_TRACE_MAPPING.get(name, f"CloudWatch span: tool.{name}"),
        },
        "output": output,
    }
