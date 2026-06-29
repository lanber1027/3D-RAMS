from __future__ import annotations

from typing import Any

from .config import RuntimeConfig
from .tools import (
    apply_bedrock_briefing,
    architecture_snapshot,
    build_scene_config,
    create_annotations,
    extract_hazard_notes,
    generate_site_brief,
    load_geospatial_features,
    load_planning_context,
    normalize_request,
    resolve_location,
    safety_gate,
    source_register,
)


def run_site_briefing(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    request_summary = normalize_request(request)
    config = RuntimeConfig.from_env(request_bedrock=request_summary["useBedrock"])
    trace: list[dict[str, Any]] = []

    location, step = resolve_location(request)
    trace.append(step)

    features, step = load_geospatial_features(
        location,
        simulate_failure=bool(request.get("simulateMapFailure")),
    )
    trace.append(step)

    scene, step = build_scene_config(location, features)
    trace.append(step)

    planning_text, step = load_planning_context(
        include_planning_fixture=bool(request.get("includePlanningFixture", True)),
    )
    trace.append(step)

    hazards, step = extract_hazard_notes(planning_text, features)
    trace.append(step)

    annotations, step = create_annotations(location, hazards)
    trace.append(step)

    briefing, evidence, step = generate_site_brief(location, hazards, planning_text)
    trace.append(step)

    briefing, step, bedrock_status, bedrock_fallback_reason = apply_bedrock_briefing(
        config,
        location,
        hazards,
        briefing,
        evidence,
        planning_text,
    )
    trace.append(step)

    safety, step = safety_gate(request, briefing)
    trace.append(step)

    sources = source_register(
        include_planning_fixture=request_summary["includePlanningFixture"],
        simulate_map_failure=request_summary["simulateMapFailure"],
        bedrock_status=bedrock_status,
        config=config,
    )
    runtime = config.public_runtime(status=bedrock_status, fallback_reason=bedrock_fallback_reason)

    return {
        "runId": "demo1-local-run",
        "request": request_summary,
        "runtime": runtime,
        "location": location,
        "scene": scene,
        "annotations": annotations if safety["allowed"] else [],
        "briefing": briefing,
        "evidence": evidence,
        "sources": sources,
        "safety": safety,
        "trace": trace,
        "architecture": architecture_snapshot(trace, request_summary, sources, evidence, safety, runtime),
    }
