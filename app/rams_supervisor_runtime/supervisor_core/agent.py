from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rams_agent_tools.config import RuntimeConfig
from rams_agent_tools.fixtures import load_fixture_pack
from rams_agent_tools.tools import (
    architecture_snapshot,
    harness_for_group,
    normalize_request,
    source_register,
    trace_step,
)

from .subagent_invoker import build_subagent_invoker
from .planner import plan_subagent_workflow
from .reasoning import reason_over_evidence


def run_site_briefing(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    upstream_context = request.get("agentcoreUpstream")
    request_summary = normalize_request(request)
    case_id = request_summary.get("caseId")
    if not case_id and isinstance(upstream_context, dict):
        case_id = upstream_context.get("caseId")
    request_summary["caseId"] = case_id
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
                },
                "plannerMode": planner_result["activeAgentMode"],
                "caseId": case_id,
            },
        )
    )
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="rams-initial-tools") as executor:
        geospatial_future = executor.submit(subagents.invoke_geospatial, request, fixture_pack=fixture_pack)
        planning_future = executor.submit(subagents.invoke_planning, request, fixture_pack=fixture_pack)

        geospatial_result = geospatial_future.result()
        planning_result = planning_future.result()

    location = geospatial_result["location"]
    features = geospatial_result["features"]
    scene = geospatial_result["scene"]
    planning_text = planning_result["planningText"]
    trace.extend(_trace_steps(geospatial_result.get("trace"), "geospatial_subagent"))
    trace.extend(_trace_steps(planning_result.get("trace"), "planning_subagent"))

    sequential_groups = subagent_plan["sequentialGroups"]
    hazard_result = subagents.invoke_hazard(planning_text, features, fixture_pack=fixture_pack)
    hazards = _dict_list(hazard_result.get("hazards"), "hazard_subagent", "hazards")
    trace.extend(_trace_steps(hazard_result.get("trace"), "hazard_subagent"))

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

    annotations = _dict_list(annotation_result.get("annotations"), "annotation_subagent", "annotations")
    briefing = _briefing_payload(briefing_result.get("briefing"))
    evidence = _evidence_items(briefing_result.get("evidence"))
    bedrock_status = briefing_result["bedrockStatus"]
    bedrock_fallback_reason = briefing_result["bedrockFallbackReason"]
    trace.extend(_trace_steps(annotation_result.get("trace"), "annotation_subagent"))
    trace.extend(_trace_steps(briefing_result.get("trace"), "briefing_subagent"))

    review_result = subagents.invoke_review(request, briefing)
    safety, safety_normalization_trace = _normalize_safety_payload(review_result.get("safety"))
    trace.extend(_trace_steps(review_result.get("trace"), "review_guardrail"))
    if safety_normalization_trace:
        trace.append(safety_normalization_trace)

    sources = source_register(
        include_planning_fixture=request_summary["includePlanningFixture"],
        simulate_map_failure=request_summary["simulateMapFailure"],
        bedrock_status=bedrock_status,
        config=config,
        fixture_pack=fixture_pack,
        planner_status=planner_result["plannerStatus"],
    )
    external_signals = {"openWeb": {"status": "not_configured", "items": []}}
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
    )
    reasoning = reasoning_result["reasoning"]
    trace.append(reasoning_result["trace"])

    runtime = config.public_runtime(status=bedrock_status, fallback_reason=bedrock_fallback_reason)
    runtime["fixturePack"] = fixture_pack["name"] if fixture_pack else None
    runtime["fixturePackMode"] = "cached-public-fixture" if fixture_pack else "synthetic-default"
    runtime["liveApiCalls"] = False
    runtime["subagentExecutionMode"] = subagents.execution_mode
    runtime["plannerMode"] = planner_result["plannerStatus"]
    runtime["activeAgentMode"] = planner_result["activeAgentMode"]
    runtime["modelCallCount"] = len(planner_result["modelCalls"])
    runtime["caseId"] = case_id

    return {
        "runId": "demo1-local-run",
        "caseId": case_id,
        "upstream": upstream_context,
        "request": request_summary,
        "runtime": runtime,
        "llmPlan": subagent_plan,
        "subagentPlan": subagent_plan,
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
        "externalSignals": external_signals,
        "safety": safety,
        "trace": trace,
        "architecture": architecture_snapshot(trace, request_summary, sources, evidence, safety, runtime),
    }


def _normalize_safety_payload(value: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if isinstance(value, dict):
        normalized = dict(value)
        if "allowed" in normalized:
            normalized["allowed"] = bool(normalized["allowed"])
            normalized.setdefault("level", "review_required" if normalized["allowed"] else "blocked")
            normalized.setdefault(
                "message",
                "Allowed as a non-certified pre-visit briefing that requires human review."
                if normalized["allowed"]
                else "Blocked by independent review.",
            )
            normalized.setdefault("triggeredRules", [])
            normalized.setdefault("triggeredSources", {})
            normalized.setdefault("requiresHumanReview", True)
            normalized.setdefault(
                "decisionId",
                "safety-harness-review-required" if normalized["allowed"] else "safety-harness-blocked",
            )
            return normalized, None

    raw_review = "" if value is None else str(value)
    lower = raw_review.lower()
    blocked = any(term in lower for term in ("block", "blocked", "reject", "rejected", "fail", "failed"))
    normalized = {
        "allowed": not blocked,
        "level": "blocked" if blocked else "review_required",
        "message": (
            "Blocked by independent review output."
            if blocked
            else "Allowed as a non-certified pre-visit briefing that requires human review."
        ),
        "triggeredRules": ["review_harness_text_block"] if blocked else [],
        "triggeredSources": {"reviewHarness": raw_review} if raw_review else {},
        "requiresHumanReview": True,
        "decisionId": "safety-harness-text-blocked" if blocked else "safety-harness-text-review-required",
        "rawReview": raw_review,
    }
    return normalized, trace_step(
        "normalize_review_safety",
        "blocked" if blocked else "fallback",
        "Supervisor normalized non-dict review Harness safety output.",
        {
            "allowed": normalized["allowed"],
            "level": normalized["level"],
            "rawReview": raw_review,
        },
        evidence_ids=["safety-policy"],
        fallback_reason="review_harness_returned_non_dict_safety",
    )


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


def _briefing_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = "" if value is None else str(value)
    return {
        "headline": "Harness briefing output normalized by supervisor.",
        "summary": [text] if text else [],
        "priority_checks": [],
    }


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
