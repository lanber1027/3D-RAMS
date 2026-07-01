from __future__ import annotations

from typing import Any

from ..config import RuntimeConfig
from .materials import sanitize_material_references


def normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    fixture_pack = request.get("fixturePack") or request.get("fixture_pack")
    agent_mode = str(request.get("agentMode") or request.get("agent_mode") or "llm-planner").strip().lower()
    case_id = request.get("caseId") or None
    materials = sanitize_material_references(request.get("materials"))
    upstream = request.get("agentcoreUpstream") if isinstance(request.get("agentcoreUpstream"), dict) else {}
    area_scope = request.get("areaScope") or upstream.get("areaScope")
    if case_id:
        for material in materials:
            material.setdefault("caseId", case_id)
    normalized = {
        "caseId": case_id,
        "siteName": request.get("siteName") or "Demo rural field fixture",
        "latitude": float(request.get("latitude", 52.2053)),
        "longitude": float(request.get("longitude", -1.6022)),
        "goal": request.get("goal") or "Pre-visit RAMS scoping pack",
        "includePlanningFixture": bool(request.get("includePlanningFixture", True)),
        "simulateMapFailure": bool(request.get("simulateMapFailure")),
        "useBedrock": bool(request.get("useBedrock", True)),
        "agentMode": agent_mode or "llm-planner",
        "fixturePack": str(fixture_pack).strip().lower() if fixture_pack else None,
        "additionalRequest": request.get("additionalRequest") or "",
        "materials": materials,
    }
    if isinstance(area_scope, dict) and area_scope:
        normalized["areaScope"] = _area_scope(area_scope)
    access_context = request.get("accessContext")
    if isinstance(access_context, dict):
        normalized["accessContext"] = access_context
    return normalized


def _area_scope(value: dict[str, Any]) -> dict[str, Any]:
    scope_type = str(value.get("type") or "radius").strip() or "radius"
    try:
        meters = int(float(value.get("meters", 0)))
    except (TypeError, ValueError):
        meters = 0
    return {"type": scope_type, "meters": meters} if meters > 0 else {"type": scope_type}


def source_register(
    include_planning_fixture: bool,
    simulate_map_failure: bool,
    bedrock_status: str,
    config: RuntimeConfig,
    fixture_pack: dict[str, Any] | None = None,
    planner_status: str = "deterministic",
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        {
            "id": "user-request",
            "label": "Submitted coordinate and options",
            "kind": "request",
            "status": "real",
            "origin": "Browser form payload",
            "trustBoundary": "User input",
            "awsMapping": "DynamoDB run record",
        },
    ]

    if fixture_pack:
        sources.extend(fixture_pack.get("sources", []))
        if simulate_map_failure:
            sources.append(
                {
                    "id": "geo-fallback",
                    "label": "Fallback geospatial fixture",
                    "kind": "geospatial_features",
                    "status": "fallback",
                    "origin": "fixtures/geospatial_features.json",
                    "trustBoundary": "Public-safe synthetic fixture",
                    "awsMapping": "S3 evidence object plus CloudWatch source metadata",
                }
            )
    else:
        sources.extend(
            [
                {
                    "id": "location-fixture",
                    "label": "Synthetic local authority fixture",
                    "kind": "location",
                    "status": "mocked",
                    "origin": "AgentCore deterministic defaults",
                    "trustBoundary": "Public-safe demo fixture",
                    "awsMapping": "DynamoDB site/session metadata",
                },
                {
                    "id": "geo-fallback" if simulate_map_failure else "geo-fixture",
                    "label": "Fallback geospatial fixture" if simulate_map_failure else "Mock geospatial feature pack",
                    "kind": "geospatial_features",
                    "status": "fallback" if simulate_map_failure else "mocked",
                    "origin": "fixtures/geospatial_features.json",
                    "trustBoundary": "Public-safe synthetic fixture",
                    "awsMapping": "S3 evidence object plus CloudWatch source metadata",
                },
            ]
        )

    sources.extend(
        [
            {
                "id": "cesium-local",
                "label": "Local Cesium scene configuration",
                "kind": "3d_scene",
                "status": "real",
                "origin": "Frontend CesiumJS with AgentCore scene config",
                "trustBoundary": "Browser rendering",
                "awsMapping": "CloudFront/static frontend plus AgentCore Runtime",
            },
            {
                "id": "bedrock-planner",
                "label": "Amazon Bedrock supervisor planner",
                "kind": "llm_planner",
                "status": planner_status,
                "origin": (
                    f"{config.bedrock_model_id} in {config.aws_region}"
                    if config.bedrock_enabled
                    else "Deterministic/mock planner unless ENABLE_BEDROCK=true and request uses Bedrock"
                ),
                "trustBoundary": "AWS account boundary when enabled",
                "awsMapping": "Amazon Bedrock InvokeModel for supervisor subagent planning",
            },
            {
                "id": "bedrock-briefing",
                "label": "Amazon Bedrock briefing adapter",
                "kind": "llm_adapter",
                "status": bedrock_status,
                "origin": (
                    f"{config.bedrock_model_id} in {config.aws_region}"
                    if config.bedrock_enabled
                    else "Disabled unless ENABLE_BEDROCK=true and request uses Bedrock"
                ),
                "trustBoundary": "AWS account boundary when enabled",
                "awsMapping": "Amazon Bedrock InvokeModel for one briefing step per run",
            },
        ]
    )

    if not fixture_pack:
        sources.append(
            {
                "id": "planning-fixture",
                "label": "Synthetic nearby planning report extract",
                "kind": "planning_document",
                "status": "mocked" if include_planning_fixture else "unavailable",
                "origin": "fixtures/planning_report.txt" if include_planning_fixture else "Disabled by tester",
                "trustBoundary": "Public-safe synthetic fixture",
                "awsMapping": "S3 evidence object and Bedrock extraction input",
            }
        )
    return sources
