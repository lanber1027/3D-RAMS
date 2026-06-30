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
    trace.extend(geospatial_result["trace"])
    trace.extend(planning_result["trace"])

    sequential_groups = subagent_plan["sequentialGroups"]
    hazard_result = subagents.invoke_hazard(planning_text, features, fixture_pack=fixture_pack)
    hazards = hazard_result["hazards"]
    trace.extend(hazard_result["trace"])

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

    annotations = annotation_result["annotations"]
    briefing = briefing_result["briefing"]
    evidence = briefing_result["evidence"]
    bedrock_status = briefing_result["bedrockStatus"]
    bedrock_fallback_reason = briefing_result["bedrockFallbackReason"]
    trace.extend(annotation_result["trace"])
    trace.extend(briefing_result["trace"])

    review_result = subagents.invoke_review(request, briefing)
    safety = review_result["safety"]
    trace.extend(review_result["trace"])

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
