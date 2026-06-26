from __future__ import annotations

from typing import Any

from .tools import (
    architecture_snapshot,
    build_scene_config,
    create_annotations,
    extract_hazard_notes,
    generate_site_brief,
    load_geospatial_features,
    load_planning_context,
    resolve_location,
    safety_gate,
)


def run_site_briefing(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
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

    safety, step = safety_gate(request, briefing)
    trace.append(step)

    return {
        "runId": "demo1-local-run",
        "location": location,
        "scene": scene,
        "annotations": annotations if safety["allowed"] else [],
        "briefing": briefing,
        "evidence": evidence,
        "safety": safety,
        "trace": trace,
        "architecture": architecture_snapshot(trace),
    }

