from __future__ import annotations

SUPERVISOR_HARNESS_SUBAGENTS = {
    "geospatial_subagent": {
        "harness": "rams_geospatial_harness",
        "phase": "initial_parallel_research",
        "dependsOn": [],
    },
    "planning_subagent": {
        "harness": "rams_planning_harness",
        "phase": "initial_parallel_research",
        "dependsOn": [],
    },
    "material_subagent": {
        "harness": "rams_material_harness",
        "phase": "initial_parallel_research",
        "dependsOn": [],
    },
    "hazard_subagent": {
        "harness": "rams_hazard_harness",
        "phase": "evidence_synthesis",
        "dependsOn": ["geospatial_subagent", "planning_subagent", "material_subagent"],
    },
    "open_web_subagent": {
        "harness": "rams_open_web_harness",
        "phase": "parallel_evidence_synthesis",
        "dependsOn": ["geospatial_subagent", "planning_subagent"],
    },
    "annotation_subagent": {
        "harness": "rams_annotation_harness",
        "phase": "parallel_report_preparation",
        "dependsOn": ["geospatial_subagent", "hazard_subagent"],
    },
    "briefing_subagent": {
        "harness": "rams_briefing_harness",
        "phase": "parallel_report_preparation",
        "dependsOn": ["geospatial_subagent", "planning_subagent", "hazard_subagent"],
    },
    "review_guardrail": {
        "harness": "rams_review_harness",
        "phase": "independent_review_gate",
        "dependsOn": ["annotation_subagent", "briefing_subagent"],
    },
}

SUPERVISOR_TOOL_GROUPS = {
    "intake": [
        "normalize_request",
        "source_register",
    ],
    "geospatial_subagent": [
        "resolve_location",
        "load_geospatial_features",
        "build_scene_config",
    ],
    "planning_subagent": [
        "load_planning_context",
    ],
    "hazard_subagent": [
        "extract_hazard_notes",
    ],
    "material_subagent": [
        "ingest_material_references",
    ],
    "material_ingestion": [
        "ingest_material_references",
    ],
    "open_web_subagent": [
        "search_open_web_signals",
    ],
    "annotation_subagent": [
        "create_annotations",
    ],
    "briefing_subagent": [
        "generate_site_brief",
        "apply_bedrock_briefing",
    ],
    "review_guardrail": [
        "safety_gate",
        "architecture_snapshot",
    ],
}


def tools_for_group(group: str) -> list[str]:
    return list(SUPERVISOR_TOOL_GROUPS.get(group, []))


def harness_for_group(group: str) -> str | None:
    subagent = SUPERVISOR_HARNESS_SUBAGENTS.get(group)
    if not subagent:
        return None
    return str(subagent["harness"])
