from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .tools import (
    build_scene_config,
    create_annotations,
    extract_hazard_notes,
    generate_site_brief,
    load_geospatial_features,
    load_planning_context,
    resolve_location,
    safety_gate,
    trace_step,
)


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    side_effect_level: str
    cost_estimate: str
    timeout_seconds: int
    retry_policy: str
    cacheable: bool
    requires_approval: bool
    safety_constraints: list[str]
    executor: Callable[[dict[str, Any]], dict[str, Any]]

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "sideEffectLevel": self.side_effect_level,
            "costEstimate": self.cost_estimate,
            "timeoutSeconds": self.timeout_seconds,
            "retryPolicy": self.retry_policy,
            "cacheable": self.cacheable,
            "requiresApproval": self.requires_approval,
            "safetyConstraints": self.safety_constraints,
        }


def tool_schemas() -> list[dict[str, Any]]:
    return [tool.public_schema() for tool in TOOL_REGISTRY.values()]


def execute_tool(name: str, context: dict[str, Any]) -> dict[str, Any]:
    tool = TOOL_REGISTRY.get(name)
    if not tool:
        raise ToolExecutionError(f"Tool '{name}' is not allowlisted.")
    return tool.executor(context)


def default_tool_sequence() -> list[str]:
    return [
        "resolve_location",
        "load_geospatial_features",
        "build_scene_config",
        "load_planning_context",
        "extract_hazard_notes",
        "rank_risks",
        "create_annotations",
        "compile_review_pack",
        "safety_gate",
    ]


def _resolve_location(context: dict[str, Any]) -> dict[str, Any]:
    location, trace = resolve_location(context["request"], fixture_pack=context.get("fixturePack"))
    context["location"] = location
    return {"location": location, "trace": trace}


def _load_geospatial_features(context: dict[str, Any]) -> dict[str, Any]:
    _require(context, "location", "load_geospatial_features")
    features, trace = load_geospatial_features(
        context["location"],
        simulate_failure=bool(context["requestSummary"]["simulateMapFailure"]),
        fixture_pack=context.get("fixturePack"),
    )
    context["features"] = features
    return {"features": features, "trace": trace}


def _build_scene_config(context: dict[str, Any]) -> dict[str, Any]:
    _require(context, "location", "build_scene_config")
    _require(context, "features", "build_scene_config")
    scene, trace = build_scene_config(context["location"], context["features"], fixture_pack=context.get("fixturePack"))
    context["scene"] = scene
    return {"scene": scene, "trace": trace}


def _load_planning_context(context: dict[str, Any]) -> dict[str, Any]:
    planning_text, trace = load_planning_context(
        include_planning_fixture=bool(context["requestSummary"]["includePlanningFixture"]),
        fixture_pack=context.get("fixturePack"),
    )
    context["planningText"] = planning_text
    return {"planningTextAvailable": planning_text is not None, "trace": trace}


def _extract_hazard_notes(context: dict[str, Any]) -> dict[str, Any]:
    _require(context, "features", "extract_hazard_notes")
    hazards, trace = extract_hazard_notes(
        context.get("planningText"),
        context["features"],
        fixture_pack=context.get("fixturePack"),
        site_intent=context["request"].get("siteIntent"),
    )
    context["hazards"] = hazards
    return {"hazards": hazards, "trace": trace}


def _rank_risks(context: dict[str, Any]) -> dict[str, Any]:
    _require(context, "hazards", "rank_risks")
    indexed_hazards = list(enumerate(context["hazards"]))
    ranked = [
        hazard
        for _, hazard in sorted(
            indexed_hazards,
            key=lambda item: (
                item[1].get("dataMode") != "provisional-from-user-description",
                item[1].get("confidence") == "low",
                item[0],
            ),
        )
    ]
    context["hazards"] = ranked
    return {
        "hazards": ranked,
        "trace": trace_step(
            "rank_risks",
            "ok",
            "Ranked risk candidates using deterministic source, confidence, and generated-profile ordering.",
            {"hazard_count": len(ranked), "mode": "deterministic-gate1", "provisionalFirst": True},
            evidence_ids=[hazard.get("id") for hazard in ranked if hazard.get("id")],
        ),
    }


def _create_annotations(context: dict[str, Any]) -> dict[str, Any]:
    _require(context, "location", "create_annotations")
    _require(context, "hazards", "create_annotations")
    annotations, trace = create_annotations(context["location"], context["hazards"])
    context["annotations"] = annotations
    return {"annotations": annotations, "trace": trace}


def _compile_review_pack(context: dict[str, Any]) -> dict[str, Any]:
    _require(context, "location", "compile_review_pack")
    _require(context, "hazards", "compile_review_pack")
    briefing, evidence, trace = generate_site_brief(
        context["location"],
        context["hazards"],
        context.get("planningText"),
        fixture_pack=context.get("fixturePack"),
    )
    context["briefing"] = briefing
    context["evidence"] = evidence
    return {"briefing": briefing, "evidence": evidence, "trace": trace}


def _safety_gate(context: dict[str, Any]) -> dict[str, Any]:
    _require(context, "briefing", "safety_gate")
    safety, trace = safety_gate(context["request"], context["briefing"])
    context["safety"] = safety
    return {"safety": safety, "trace": trace}


def _require(context: dict[str, Any], key: str, tool_name: str) -> None:
    if key not in context:
        raise ToolExecutionError(f"Tool '{tool_name}' requires missing context field '{key}'.")


def _schema(fields: dict[str, str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": fields or {}, "additionalProperties": False}


_COMMON_SAFETY = [
    "No shell, code execution, or arbitrary URL fetching.",
    "No certified RAMS, emergency guidance, or approval-to-work claims.",
    "Outputs must remain inspectable and suitable for human review.",
]


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "resolve_location": ToolDefinition(
        "resolve_location",
        "Resolve the submitted site request or fixture pack into site metadata.",
        _schema(),
        _schema({"location": "object"}),
        "read-only",
        "low",
        3,
        "no retry",
        True,
        False,
        _COMMON_SAFETY,
        _resolve_location,
    ),
    "load_geospatial_features": ToolDefinition(
        "load_geospatial_features",
        "Load cached or synthetic geospatial features for the resolved site.",
        _schema(),
        _schema({"features": "array"}),
        "read-only",
        "low",
        5,
        "one retry when future live adapter is used",
        True,
        False,
        _COMMON_SAFETY,
        _load_geospatial_features,
    ),
    "build_scene_config": ToolDefinition(
        "build_scene_config",
        "Build the 3D scene configuration from location and features.",
        _schema(),
        _schema({"scene": "object"}),
        "none",
        "low",
        3,
        "no retry",
        True,
        False,
        _COMMON_SAFETY,
        _build_scene_config,
    ),
    "load_planning_context": ToolDefinition(
        "load_planning_context",
        "Load cached or synthetic planning/context notes.",
        _schema(),
        _schema({"planningTextAvailable": "boolean"}),
        "read-only",
        "low",
        5,
        "one retry when future live adapter is used",
        True,
        False,
        _COMMON_SAFETY,
        _load_planning_context,
    ),
    "extract_hazard_notes": ToolDefinition(
        "extract_hazard_notes",
        "Extract candidate hazard notes from planning and geospatial context.",
        _schema(),
        _schema({"hazards": "array"}),
        "none",
        "low",
        5,
        "no retry",
        True,
        False,
        _COMMON_SAFETY,
        _extract_hazard_notes,
    ),
    "rank_risks": ToolDefinition(
        "rank_risks",
        "Rank candidate risks and preserve evidence/confidence labels.",
        _schema(),
        _schema({"hazards": "array"}),
        "none",
        "low",
        3,
        "no retry",
        True,
        False,
        _COMMON_SAFETY,
        _rank_risks,
    ),
    "create_annotations": ToolDefinition(
        "create_annotations",
        "Convert risk candidates into 3D map annotations.",
        _schema(),
        _schema({"annotations": "array"}),
        "none",
        "low",
        3,
        "no retry",
        True,
        False,
        _COMMON_SAFETY,
        _create_annotations,
    ),
    "compile_review_pack": ToolDefinition(
        "compile_review_pack",
        "Compile an evidence-backed pre-visit review pack.",
        _schema(),
        _schema({"briefing": "object", "evidence": "array"}),
        "none",
        "low",
        5,
        "no retry",
        True,
        False,
        _COMMON_SAFETY,
        _compile_review_pack,
    ),
    "safety_gate": ToolDefinition(
        "safety_gate",
        "Apply hard safety boundary before returning output to the user.",
        _schema(),
        _schema({"safety": "object"}),
        "none",
        "low",
        3,
        "no retry",
        False,
        True,
        _COMMON_SAFETY,
        _safety_gate,
    ),
}
