from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rams_agent_tools.config import RuntimeConfig
from rams_agent_tools.fixtures import load_fixture_pack
from rams_agent_tools.tools import (
    architecture_snapshot,
    harness_for_group,
    normalize_request,
    safety_gate,
    source_register,
    trace_step,
)

from .subagent_invoker import build_subagent_invoker
from .harness_contract import HARNESS_OUTPUT_SCHEMA_VERSION, harness_contract_summary, harness_data
from .planner import plan_subagent_workflow
from .reasoning import reason_over_evidence
from .review_loop import run_independent_review_loop
from .runtime_observability import runtime_observability


def run_site_briefing(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    upstream_context = request.get("agentcoreUpstream")
    request_summary = normalize_request(request)
    case_id = _case_id_for_request(request_summary, upstream_context)
    request_summary["caseId"] = case_id
    for key in ("_reviewDecision", "_reviewMaxRevisionAttempts"):
        if key in request:
            request_summary[key] = request[key]
    fixture_pack, fixture_pack_warning = load_fixture_pack(request_summary["fixturePack"])
    if fixture_pack:
        pack_location = fixture_pack["location"]
        request_summary["fixturePack"] = fixture_pack["name"]
        request_summary["siteName"] = pack_location["label"]
        request_summary["latitude"] = float(pack_location["latitude"])
        request_summary["longitude"] = float(pack_location["longitude"])

    config = RuntimeConfig.from_env(request_bedrock=request_summary["useBedrock"])
    subagents = build_subagent_invoker(config)
    trace: list[dict[str, Any]] = []
    subagent_outputs: list[dict[str, Any]] = []

    if fixture_pack_warning:
        trace.append(
            trace_step(
                "load_fixture_pack",
                "fallback",
                fixture_pack_warning["reason"],
                fixture_pack_warning,
                fallback_reason=fixture_pack_warning["reason"],
            )
        )

    planner_result = plan_subagent_workflow(config=config, request_summary=request_summary)
    subagent_plan = planner_result["plan"]
    trace.append(planner_result["trace"])

    initial_groups = subagent_plan["initialParallelGroups"]
    trace.append(
        trace_step(
            "dispatch_parallel_tool_groups",
            "ok",
            "Supervisor dispatched planner-selected initial Harness subagent groups in parallel.",
            {
                "mode": subagents.execution_mode,
                "groups": initial_groups,
                "harnesses": {
                    "geospatial_subagent": harness_for_group("geospatial_subagent"),
                    "planning_subagent": harness_for_group("planning_subagent"),
                    "material_subagent": harness_for_group("material_subagent"),
                },
                "plannerMode": planner_result["activeAgentMode"],
                "caseId": case_id,
            },
        )
    )
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="rams-initial-tools") as executor:
        geospatial_future = executor.submit(subagents.invoke_geospatial, request, fixture_pack=fixture_pack)
        planning_future = executor.submit(subagents.invoke_planning, request, fixture_pack=fixture_pack)
        material_future = executor.submit(
            subagents.invoke_material,
            request,
            case_id=case_id,
            upstream_context=upstream_context if isinstance(upstream_context, dict) else None,
        )

        geospatial_result = geospatial_future.result()
        planning_result = planning_future.result()
        material_subagent_result = material_future.result()

    subagent_outputs.extend([geospatial_result, planning_result, material_subagent_result])
    geospatial_data = harness_data(geospatial_result)
    planning_data = harness_data(planning_result)
    material_data = harness_data(material_subagent_result)
    location = geospatial_data["location"]
    features = geospatial_data["features"]
    scene = geospatial_data["scene"]
    planning_text = planning_data["planningText"]
    trace.extend(_trace_steps(geospatial_result.get("trace"), "geospatial_subagent"))
    trace.extend(_trace_steps(planning_result.get("trace"), "planning_subagent"))
    trace.extend(_trace_steps(material_subagent_result.get("trace"), "material_subagent"))
    material_result = _dict(material_data.get("materialIngestion"))
    material_findings = _dict_list(material_subagent_result.get("findings"), "material_subagent", "findings")
    material_evidence = _dict_list(material_subagent_result.get("evidence"), "material_subagent", "evidence")
    material_sources = _dict_list(material_subagent_result.get("references"), "material_subagent", "references")

    sequential_groups = subagent_plan["sequentialGroups"]
    evidence_groups = [
        group for group in sequential_groups if group in {"hazard_subagent", "open_web_subagent"}
    ] or ["hazard_subagent", "open_web_subagent"]
    trace.append(
        trace_step(
            "dispatch_parallel_evidence_synthesis",
            "ok",
            "Supervisor dispatched hazard extraction and optional open-web signals in parallel.",
            {
                "mode": subagents.execution_mode,
                "groups": evidence_groups,
                "harnesses": {
                    "hazard_subagent": harness_for_group("hazard_subagent"),
                    "open_web_subagent": harness_for_group("open_web_subagent"),
                },
                "plannerMode": planner_result["activeAgentMode"],
                "caseId": case_id,
            },
        )
    )
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="rams-evidence-tools") as executor:
        hazard_future = executor.submit(subagents.invoke_hazard, planning_text, features, fixture_pack=fixture_pack)
        open_web_future = executor.submit(
            subagents.invoke_open_web,
            location,
            request_summary,
            request_summary.get("areaScope"),
        )

        hazard_result = hazard_future.result()
        open_web_result = open_web_future.result()

    subagent_outputs.extend([hazard_result, open_web_result])
    hazard_data = harness_data(hazard_result)
    open_web_data = harness_data(open_web_result)
    hazards = _dict_list(hazard_data.get("hazards"), "hazard_subagent", "hazards")
    hazards.extend(material_findings)
    trace.extend(_trace_steps(hazard_result.get("trace"), "hazard_subagent"))
    trace.extend(_trace_steps(open_web_result.get("trace"), "open_web_subagent"))

    report_groups = subagent_plan["reportParallelGroups"]
    trace.append(
        trace_step(
            "dispatch_parallel_report_groups",
            "ok",
            "Supervisor dispatched planner-selected report-preparation Harness subagent groups in parallel after hazard extraction.",
            {
                "mode": subagents.execution_mode,
                "groups": report_groups,
                "upstreamSequentialGroups": sequential_groups,
                "harnesses": {
                    "annotation_subagent": harness_for_group("annotation_subagent"),
                    "briefing_subagent": harness_for_group("briefing_subagent"),
                },
                "plannerMode": planner_result["activeAgentMode"],
                "caseId": case_id,
            },
        )
    )
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="rams-report-tools") as executor:
        annotations_future = executor.submit(subagents.invoke_annotation, location, hazards)
        briefing_future = executor.submit(
            subagents.invoke_briefing,
            config,
            location,
            hazards,
            planning_text,
            fixture_pack=fixture_pack,
        )

        annotation_result = annotations_future.result()
        briefing_result = briefing_future.result()

    subagent_outputs.extend([annotation_result, briefing_result])
    annotation_data = harness_data(annotation_result)
    briefing_data = harness_data(briefing_result)
    annotations = _dict_list(annotation_data.get("annotations"), "annotation_subagent", "annotations")
    briefing = _briefing_payload(briefing_data.get("briefing"))
    _merge_material_briefing(briefing, {**material_result, "findings": material_findings})
    evidence = _evidence_items(briefing_data.get("evidence")) + material_evidence
    bedrock_status = briefing_data["bedrockStatus"]
    bedrock_fallback_reason = briefing_data["bedrockFallbackReason"]
    trace.extend(_trace_steps(annotation_result.get("trace"), "annotation_subagent"))
    trace.extend(_trace_steps(briefing_result.get("trace"), "briefing_subagent"))

    safety, safety_step = safety_gate(request, briefing)
    trace.append(safety_step)

    sources = source_register(
        include_planning_fixture=request_summary["includePlanningFixture"],
        simulate_map_failure=request_summary["simulateMapFailure"],
        bedrock_status=bedrock_status,
        config=config,
        fixture_pack=fixture_pack,
        planner_status=planner_result["plannerStatus"],
    )
    sources.extend(material_sources)
    external_signals = {"openWeb": _open_web_payload(open_web_data.get("openWeb"))}
    reasoning_result = reason_over_evidence(
        request=request_summary,
        location=location,
        hazards=hazards if safety["allowed"] else [],
        annotations=annotations if safety["allowed"] else [],
        briefing=briefing,
        evidence=evidence,
        sources=sources,
        safety=safety,
        external_signals=external_signals,
        material_ingestion=material_result,
    )
    reasoning = reasoning_result["reasoning"]
    trace.append(reasoning_result["trace"])

    runtime_fallback_reason = _runtime_fallback_reason(planner_result, bedrock_fallback_reason)
    runtime = config.public_runtime(status=bedrock_status, fallback_reason=runtime_fallback_reason)
    runtime["fixturePack"] = fixture_pack["name"] if fixture_pack else None
    runtime["fixturePackMode"] = "cached-public-fixture" if fixture_pack else "synthetic-default"
    runtime["liveApiCalls"] = bool(external_signals["openWeb"].get("liveCallAttempted"))
    runtime["subagentExecutionMode"] = subagents.execution_mode
    runtime["plannerMode"] = planner_result["plannerStatus"]
    runtime["activeAgentMode"] = planner_result["activeAgentMode"]
    runtime["modelCallCount"] = len(planner_result["modelCalls"])
    runtime["bedrockUsed"] = bedrock_status in {"real", "mocked"} or planner_result["plannerStatus"] in {"real", "mocked"}
    runtime["caseId"] = case_id
    runtime["materialIngestionStatus"] = material_result["status"]
    runtime["materialEvidenceCount"] = len(material_evidence)
    runtime["materialSkippedCount"] = len(material_result.get("skipped") or [])
    runtime["harnessOutputSchemaVersion"] = HARNESS_OUTPUT_SCHEMA_VERSION
    runtime["harnessContract"] = harness_contract_summary(subagent_outputs)
    trace = _correlate_trace(trace, case_id)

    run = {
        "runId": "demo1-local-run",
        "caseId": case_id,
        "upstream": upstream_context,
        "request": request_summary,
        "runtime": runtime,
        "llmPlan": subagent_plan,
        "subagentPlan": subagent_plan,
        "subagentOutputs": subagent_outputs,
        "modelCalls": planner_result["modelCalls"],
        "tokenUsage": planner_result["tokenUsage"],
        "fallback": planner_result["fallback"],
        "location": location,
        "scene": scene,
        "hazards": hazards if safety["allowed"] else [],
        "annotations": annotations if safety["allowed"] else [],
        "briefing": briefing,
        "evidence": evidence,
        "sources": sources,
        "reasoning": reasoning,
        "materialIngestion": _material_public_result(material_result),
        "externalSignals": external_signals,
        "safety": safety,
        "trace": trace,
    }
    runtime["runtimeObservability"] = runtime_observability(runtime, run)
    run_independent_review_loop(run, reviewer_mode=_reviewer_mode(subagents.execution_mode))
    run["trace"] = _correlate_trace(run["trace"], case_id)
    run["architecture"] = architecture_snapshot(run["trace"], request_summary, sources, evidence, safety, runtime)
    return run


def _case_id_for_request(request_summary: dict[str, Any], upstream_context: Any) -> str:
    explicit = request_summary.get("caseId")
    if not explicit and isinstance(upstream_context, dict):
        explicit = upstream_context.get("caseId")
    if explicit:
        return str(explicit)

    seed = {
        "siteName": request_summary.get("siteName"),
        "latitude": request_summary.get("latitude"),
        "longitude": request_summary.get("longitude"),
        "goal": request_summary.get("goal"),
        "fixturePack": request_summary.get("fixturePack"),
        "additionalRequest": request_summary.get("additionalRequest"),
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"case_{digest[:12]}"


def _correlate_trace(trace: list[dict[str, Any]], case_id: str) -> list[dict[str, Any]]:
    correlated = []
    for step in trace:
        if not isinstance(step, dict):
            continue
        enriched = dict(step)
        enriched["caseId"] = case_id
        output = enriched.get("output")
        if isinstance(output, dict):
            output = dict(output)
            output.setdefault("caseId", case_id)
            enriched["output"] = output
        correlated.append(enriched)
    return correlated


def _runtime_fallback_reason(planner_result: dict[str, Any], briefing_reason: str | None) -> str | None:
    reasons = []
    planner_fallback = planner_result.get("fallback") if isinstance(planner_result.get("fallback"), dict) else {}
    planner_reason = planner_fallback.get("reason")
    if planner_result.get("plannerStatus") == "fallback" and planner_reason:
        reasons.append(str(planner_reason))
    if briefing_reason:
        reasons.append(str(briefing_reason))
    return "; ".join(dict.fromkeys(reasons)) or None


def _open_web_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "not_configured", "provider": "tavily", "items": [], "warnings": []}
    payload = dict(value)
    payload.setdefault("status", "not_configured")
    payload.setdefault("provider", "tavily")
    payload.setdefault("sourceBoundary", "non_authoritative_signal")
    payload.setdefault("items", [])
    payload.setdefault("warnings", [])
    payload.setdefault("liveCallAttempted", False)
    if not isinstance(payload.get("items"), list):
        payload["items"] = []
    if not isinstance(payload.get("warnings"), list):
        payload["warnings"] = []
    return payload


def _trace_steps(value: Any, source: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    normalized: list[dict[str, Any]] = []
    required = {"id", "name", "status", "summary", "durationMs", "sourceIds", "evidenceIds", "fallbackReason", "output"}
    for index, item in enumerate(items):
        if isinstance(item, dict) and required.issubset(item.keys()):
            normalized.append(item)
            continue
        normalized.append(
            trace_step(
                "normalize_subagent_trace",
                "fallback",
                "Supervisor normalized non-standard Harness trace output.",
                {
                    "source": source,
                    "index": index,
                    "rawTrace": str(item)[:500],
                },
                fallback_reason="harness_returned_non_standard_trace",
            )
        )
    return normalized


def _dict_list(value: Any, source: str, field: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _briefing_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = "" if value is None else str(value)
    return {
        "headline": "Harness briefing output normalized by supervisor.",
        "summary": [text] if text else [],
        "priority_checks": [],
    }


def _merge_material_briefing(briefing: dict[str, Any], material_result: dict[str, Any]) -> None:
    accepted = material_result.get("acceptedReferences") if isinstance(material_result, dict) else []
    skipped = material_result.get("skipped") if isinstance(material_result, dict) else []
    if not accepted and not skipped:
        return

    briefing.setdefault("summary", [])
    briefing.setdefault("limitations", [])
    briefing.setdefault("priority_checks", [])
    if accepted:
        briefing["summary"].append(
            f"{len(accepted)} authorized material reference(s) produced safe evidence summaries for human review."
        )
        for finding in _dict_list(material_result.get("findings"), "material_ingestion", "findings")[:3]:
            title = str(finding.get("title") or "").strip()
            if title:
                briefing["priority_checks"].append(f"Review material-derived observation: {title}.")
        briefing["limitations"].append(
            "Material-derived output uses ASI/ASI:ONE-authorized summaries or fixtures; raw private material content is not stored in the report."
        )
    if skipped:
        briefing["limitations"].append(
            f"{len(skipped)} material reference(s) were skipped because access, expiry, type, size, or retrieval checks failed."
        )


def _material_public_result(material_result: dict[str, Any]) -> dict[str, Any]:
    public_keys = {
        "schemaVersion",
        "referenceSchemaVersion",
        "status",
        "mode",
        "caseId",
        "upstreamSource",
        "received",
        "accepted",
        "skippedCount",
        "references",
        "acceptedReferences",
        "skipped",
        "citations",
        "extractions",
        "sourceIds",
        "evidenceIds",
    }
    return {key: value for key, value in material_result.items() if key in public_keys}


def _evidence_items(value: Any) -> list[dict[str, Any]]:
    def complete(item: dict[str, Any], index: int) -> dict[str, Any]:
        normalized = dict(item)
        normalized.setdefault("id", f"evidence-harness-normalized-{index + 1}")
        normalized.setdefault("title", "Harness evidence output normalized by supervisor")
        normalized.setdefault("status", "fallback")
        return normalized

    if isinstance(value, list):
        items = [complete(item, index) for index, item in enumerate(value) if isinstance(item, dict)]
        if items:
            return items
    if isinstance(value, dict):
        return [complete(value, 0)]
    text = "" if value is None else str(value)
    return [
        {
            "id": "evidence-harness-normalized",
            "title": "Harness evidence output normalized by supervisor",
            "status": "fallback",
            "summary": text,
        }
    ]


def _reviewer_mode(execution_mode: str) -> str:
    return "harness" if execution_mode == "agentcore-harness" else "deterministic"
