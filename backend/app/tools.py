from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .bedrock_adapter import BedrockAdapterError, generate_bedrock_briefing
from .config import RuntimeConfig
from .fixtures import load_json, load_text
from .live_map_features import load_live_map_features


AWS_TRACE_MAPPING = {
    "resolve_location": "CloudWatch span: tool.resolve_location",
    "load_geospatial_features": "CloudWatch span: tool.load_geospatial_features",
    "build_scene_config": "CloudWatch span: tool.build_scene_config",
    "load_planning_context": "CloudWatch span: tool.load_planning_context",
    "extract_hazard_notes": "Bedrock/CloudWatch span: tool.extract_hazard_notes",
    "create_annotations": "CloudWatch span: tool.create_annotations",
    "generate_site_brief": "Bedrock/CloudWatch span: tool.generate_site_brief",
    "generate_bedrock_briefing": "Bedrock/CloudWatch span: tool.generate_bedrock_briefing",
    "llm_planner_model_plan": "Bedrock/CloudWatch span: planner.model_plan",
    "llm_planner_tool_call": "CloudWatch span: planner.tool_call",
    "llm_planner_synthesis": "Bedrock/CloudWatch span: planner.synthesis",
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


def normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    fixture_pack = request.get("fixturePack") or request.get("fixture_pack")
    use_bedrock = bool(request.get("useBedrock", True))
    raw_agent_mode = request.get("agentMode") or request.get("agent_mode")
    agent_mode = str(raw_agent_mode).strip().lower() if raw_agent_mode else (
        "llm-planner" if use_bedrock else "deterministic"
    )
    if agent_mode not in {"deterministic", "bedrock-briefing", "llm-planner"}:
        agent_mode = "deterministic"
    return {
        "siteName": request.get("siteName") or "Demo rural field fixture",
        "latitude": float(request.get("latitude", 52.2053)),
        "longitude": float(request.get("longitude", -1.6022)),
        "goal": request.get("goal") or "Pre-visit RAMS scoping pack",
        "includePlanningFixture": bool(request.get("includePlanningFixture", True)),
        "simulateMapFailure": bool(request.get("simulateMapFailure")),
        "useBedrock": use_bedrock,
        "agentMode": agent_mode,
        "fixturePack": str(fixture_pack).strip().lower() if fixture_pack else None,
        "additionalRequest": request.get("additionalRequest") or "",
    }


def source_register(
    include_planning_fixture: bool,
    simulate_map_failure: bool,
    bedrock_status: str,
    config: RuntimeConfig,
    fixture_pack: dict[str, Any] | None = None,
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
                    "origin": "backend deterministic defaults",
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
            "id": "planning-data-live",
            "label": "Planning Data API live constraints",
            "kind": "planning_designations",
            "status": "real" if config.enable_live_map_features else "future",
            "origin": config.planning_data_api_base,
            "trustBoundary": "Server-side public API adapter",
            "awsMapping": "Lambda/FastAPI outbound HTTPS plus CloudWatch source metadata",
        },
        {
            "id": "osm-live",
            "label": "OpenStreetMap / Overpass live features",
            "kind": "geospatial_features",
            "status": "real" if config.enable_live_map_features else "future",
            "origin": config.overpass_api_url,
            "trustBoundary": "Server-side public API adapter",
            "awsMapping": "Lambda/FastAPI outbound HTTPS plus CloudWatch source metadata",
        },
        {
            "id": "cesium-local",
            "label": "CesiumJS terrain, imagery, buildings, and overlays",
            "kind": "3d_scene",
            "status": "real",
            "origin": "Browser CesiumJS with backend scene/map feature config",
            "trustBoundary": "Browser rendering",
            "awsMapping": "CloudFront/static frontend plus App Runner/API Gateway backend",
        },
        {
            "id": "bedrock-briefing",
            "label": "Amazon Bedrock planner and synthesis adapter",
            "kind": "llm_adapter",
            "status": bedrock_status,
            "origin": (
                f"{config.bedrock_model_id} in {config.aws_region}"
                if config.bedrock_enabled
                else "Disabled unless ENABLE_BEDROCK=true and request uses Bedrock"
            ),
            "trustBoundary": "AWS account boundary when enabled",
            "awsMapping": "Amazon Bedrock InvokeModel for bounded planner and synthesis steps",
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
        sources.append(
            {
                "id": "provisional-from-user-description",
                "label": "Prompt-derived provisional risk profile",
                "kind": "risk_profile",
                "status": "provisional",
                "origin": "User-submitted site type and visit activity",
                "trustBoundary": "User input, not source evidence",
                "awsMapping": "DynamoDB run metadata plus CloudWatch trace",
            }
        )
    return sources


def resolve_location(
    request: dict[str, Any],
    fixture_pack: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if fixture_pack:
        pack_location = fixture_pack["location"]
        location = {
            "label": pack_location["label"],
            "latitude": float(pack_location["latitude"]),
            "longitude": float(pack_location["longitude"]),
            "authority": pack_location.get("authority", "Unknown public authority"),
            "coordinate_system": pack_location.get("coordinate_system", "WGS84"),
            "confidence": pack_location.get("confidence", "medium"),
            "fixturePack": fixture_pack["name"],
            "dataMode": "cached-public-fixture",
            "sourceIds": pack_location.get("source_ids", []),
        }
        return location, trace_step(
            "resolve_location",
            "ok",
            "Loaded cached public fixture-pack location metadata.",
            {"location": location, "fixturePack": fixture_pack["name"], "dataMode": "cached-public-fixture"},
            source_ids=["user-request", *pack_location.get("source_ids", [])],
        )

    latitude = float(request.get("latitude", 52.2053))
    longitude = float(request.get("longitude", -1.6022))
    confirmed_location = (request.get("locationResolution") or {}).get("confirmedLocation") or {}
    source_ids = confirmed_location.get("sourceIds") or []
    if confirmed_location.get("source") and confirmed_location.get("source") not in source_ids:
        source_ids = [*source_ids, confirmed_location["source"]]
    data_mode = confirmed_location.get("dataMode") or "synthetic-fixture"
    authority = (
        confirmed_location.get("countyOrAuthority")
        or confirmed_location.get("district")
        or confirmed_location.get("region")
        or "Syntheticshire District Council"
    )
    location = {
        "label": request.get("siteName") or "Demo rural field fixture",
        "latitude": latitude,
        "longitude": longitude,
        "authority": authority,
        "coordinate_system": "WGS84",
        "confidence": confirmed_location.get("confidence") or ("high" if request.get("latitude") and request.get("longitude") else "medium"),
        "dataMode": data_mode,
        "sourceIds": source_ids or ["location-fixture"],
        "locationContext": confirmed_location.get("locationContext"),
        "relativeLocation": confirmed_location.get("relativeLocation"),
    }
    return location, trace_step(
        "resolve_location",
        "ok",
        "Resolved the user-confirmed location candidate into the review workflow coordinate.",
        {"location": location, "dataMode": data_mode},
        source_ids=["user-request", *location["sourceIds"]],
    )


def load_geospatial_features(
    location: dict[str, Any],
    simulate_failure: bool = False,
    fixture_pack: dict[str, Any] | None = None,
    config: RuntimeConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_config = config or RuntimeConfig.from_env(request_bedrock=False)
    if simulate_failure:
        features = load_json("geospatial_features.json")["fallback_features"]
        _attach_feature_status(features, "fallback", "simulated-map-failure")
        return features, trace_step(
            "load_geospatial_features",
            "fallback",
            "Live 3D/map provider was unavailable; loaded local fallback geospatial fixture.",
            {"feature_count": len(features), "source": "fixtures/geospatial_features.json"},
            source_ids=["geo-fallback"],
            evidence_ids=["geo-fixture"],
            fallback_reason="Fallback used after simulated live map provider failure for demo testing.",
        )

    if active_config.enable_live_map_features:
        live_features, live_status = load_live_map_features(location, active_config)
        if live_features:
            _attach_feature_status(live_features, live_status["status"], "live-public-features")
            return live_features, trace_step(
                "load_geospatial_features",
                "ok" if live_status["status"] == "live" else "warning",
                "Loaded live public map features from server-side public data adapters.",
                {
                    "feature_count": len(live_features),
                    "dataMode": "live-public",
                    "liveFeatureStatus": live_status,
                    "sources": live_status["successfulSources"],
                },
                source_ids=["planning-data-live", "osm-live"],
                evidence_ids=["planning-data-live", "osm-live"],
                fallback_reason=None if live_status["status"] == "live" else "One or more live map providers failed; partial live features are shown.",
                duration_ms=live_status["latencyMs"],
            )
        if active_config.live_map_required:
            return [], trace_step(
                "load_geospatial_features",
                "failed",
                "Live map features were required but no live public features could be loaded.",
                {"feature_count": 0, "dataMode": "live-public", "liveFeatureStatus": live_status},
                source_ids=["planning-data-live", "osm-live"],
                fallback_reason="LIVE_MAP_REQUIRED=true and all live map providers failed.",
                duration_ms=live_status["latencyMs"],
            )

    if fixture_pack:
        geospatial = fixture_pack.get("geospatial", {})
        features = geospatial.get("features", [])
        _attach_feature_status(features, "cached-fallback", "cached-public-fixture")
        source_ids = geospatial.get("source_ids", [])
        evidence_ids = geospatial.get("evidence_ids", source_ids)
        return features, trace_step(
            "load_geospatial_features",
            "ok",
            "Loaded cached public geospatial feature pack without live API calls.",
            {
                "feature_count": len(features),
                "fixturePack": fixture_pack["name"],
                "dataMode": "cached-public-fixture",
                "sourceIds": source_ids,
            },
            source_ids=source_ids,
            evidence_ids=evidence_ids,
        )

    features = load_json("geospatial_features.json")["features"]
    _attach_feature_status(features, "synthetic-fallback", "synthetic-fixture")
    return features, trace_step(
        "load_geospatial_features",
        "ok",
        "Loaded mock geospatial features around the coordinate.",
        {"feature_count": len(features), "source": "fixtures/geospatial_features.json"},
        source_ids=["geo-fixture"],
        evidence_ids=["geo-fixture"],
    )


def build_scene_config(
    location: dict[str, Any],
    features: list[dict[str, Any]],
    fixture_pack: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    uses_geo_fallback = any(feature["id"].startswith("fallback") for feature in features)
    live_features = [feature for feature in features if feature.get("dataMode") == "live-public"]
    feature_status = _feature_status(features)
    scene_mode = (
        "live-cesium"
        if feature_status == "live"
        else "live-partial"
        if feature_status == "partial"
        else "cached-fallback"
        if fixture_pack
        else "synthetic-fallback"
    )
    geo_source_ids = (
        ["geo-fallback"]
        if uses_geo_fallback
        else (
            fixture_pack.get("geospatial", {}).get("source_ids", [])
            if fixture_pack
            else ["planning-data-live", "osm-live"]
            if live_features
            else ["geo-fixture"]
        )
    )
    scene = {
        "provider": "cesium-live-public" if live_features else "cesium-local-cached-fixture" if fixture_pack else "cesium-local-fixture",
        "mode": scene_mode,
        "providers": {
            "terrain": "cesium-ion-world-terrain",
            "imagery": "cesium-ion-world-imagery",
            "buildings": "cesium-osm-buildings",
            "liveFeatures": feature_status if live_features else "not-enabled",
        },
        "center": {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "heightMeters": 260,
        },
        "camera": {
            "headingDegrees": 25,
            "pitchDegrees": -42,
            "rangeMeters": 1800,
            "heightMeters": 1500,
        },
        "terrain": "cesium world terrain when VITE_CESIUM_ION_TOKEN is configured; ellipsoid fallback otherwise",
        "featureCount": len(features),
        "liveFeatureCount": len(live_features),
        "fixturePack": fixture_pack["name"] if fixture_pack else None,
        "dataMode": "live-public" if live_features else "cached-public-fixture" if fixture_pack else "synthetic-fixture",
        "note": "Live 3D MVP uses Cesium ion terrain/imagery/buildings when a browser token is configured. Live public features are fetched server-side when enabled.",
    }
    return scene, trace_step(
        "build_scene_config",
        "ok",
        "Created a 3D scene configuration from the resolved coordinate and available map features.",
        {"scene": scene},
        source_ids=[*location.get("sourceIds", ["location-fixture"]), *geo_source_ids],
    )


def _attach_feature_status(features: list[dict[str, Any]], status: str, mode: str) -> None:
    for feature in features:
        feature.setdefault("featureStatus", status)
        feature.setdefault("featureMode", mode)


def _feature_status(features: list[dict[str, Any]]) -> str:
    statuses = {feature.get("featureStatus") for feature in features if feature.get("featureStatus")}
    if "live" in statuses and "partial" not in statuses:
        return "live"
    if "live" in statuses or "partial" in statuses:
        return "partial"
    if "cached-fallback" in statuses:
        return "cached-fallback"
    if "fallback" in statuses:
        return "fallback"
    return "synthetic-fallback"


def load_planning_context(
    include_planning_fixture: bool,
    fixture_pack: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    if fixture_pack:
        planning = fixture_pack.get("planning", {})
        source_ids = planning.get("source_ids", [])
        if not include_planning_fixture:
            return None, trace_step(
                "load_planning_context",
                "warning",
                "Planning fixture was disabled; cached pack briefing will only use geospatial context.",
                {"source": None, "fixturePack": fixture_pack["name"], "dataMode": "cached-public-fixture"},
                source_ids=source_ids,
            )

        text = planning.get("text")
        if not text:
            return None, trace_step(
                "load_planning_context",
                "warning",
                "Cached fixture pack did not include planning text; briefing will only use geospatial context.",
                {"source": planning.get("file"), "fixturePack": fixture_pack["name"]},
                source_ids=source_ids,
                fallback_reason="Planning text was missing from the selected cached fixture pack.",
            )

        return text, trace_step(
            "load_planning_context",
            "ok",
            "Loaded cached public planning/context notes from fixture pack.",
            {
                "source": f"fixtures/{fixture_pack['name']}/{planning.get('file')}",
                "characters": len(text),
                "fixturePack": fixture_pack["name"],
                "dataMode": "cached-public-fixture",
            },
            source_ids=source_ids,
            evidence_ids=planning.get("evidence_ids", source_ids),
        )

    if not include_planning_fixture:
        return None, trace_step(
            "load_planning_context",
            "warning",
            "Planning fixture was disabled; briefing will only use geospatial context.",
            {"source": None},
            source_ids=["planning-fixture"],
        )

    text = load_text("planning_report.txt")
    return text, trace_step(
        "load_planning_context",
        "ok",
        "Loaded synthetic planning-document fixture for hazard extraction.",
        {"source": "fixtures/planning_report.txt", "characters": len(text)},
        source_ids=["planning-fixture"],
        evidence_ids=["planning-fixture"],
    )


def extract_hazard_notes(
    planning_text: str | None,
    features: list[dict[str, Any]],
    fixture_pack: dict[str, Any] | None = None,
    site_intent: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if fixture_pack:
        hazards = fixture_pack.get("hazards", [])
        source_ids = sorted({source_id for hazard in hazards for source_id in hazard.get("sourceIds", [])})
        evidence_ids = sorted({evidence_id for hazard in hazards for evidence_id in hazard.get("evidenceIds", [])})
        return hazards, trace_step(
            "extract_hazard_notes",
            "ok" if hazards else "warning",
            "Loaded cached public-source hazard notes from fixture pack.",
            {
                "hazard_count": len(hazards),
                "fixturePack": fixture_pack["name"],
                "dataMode": "cached-public-fixture",
            },
            source_ids=source_ids,
            evidence_ids=evidence_ids,
        )

    hazards: list[dict[str, Any]] = []
    feature_status = _feature_status(features)
    geo_source_id = (
        "planning-data-live"
        if any(feature.get("dataMode") == "live-public" and feature.get("layer") == "planning" for feature in features)
        else "osm-live"
        if any(feature.get("dataMode") == "live-public" for feature in features)
        else "geo-fallback"
        if any(feature["id"].startswith("fallback") for feature in features)
        else "geo-fixture"
    )

    for feature in features:
        if feature["type"] in {"watercourse", "slope", "access_track", "bridge", "building", "designation", "interface"}:
            hazards.append(
                {
                    "id": f"geo-{feature['id']}",
                    "title": feature["label"],
                    "category": feature["type"],
                    "source": feature.get("provider") or "geospatial fixture",
                    "sourceIds": feature.get("sourceIds") or [geo_source_id],
                    "evidenceIds": feature.get("evidenceIds") or ([geo_source_id] if feature.get("dataMode") == "live-public" else ["geo-fixture"]),
                    "confidence": feature.get("confidence", "medium"),
                    "note": feature["risk_note"],
                    "dataMode": feature.get("dataMode"),
                    "geometry": feature.get("geometry"),
                    "centroid": feature.get("centroid"),
                    "mapFeatureId": feature.get("id"),
                    "layer": feature.get("layer"),
                    "attribution": feature.get("attribution"),
                }
            )

    if planning_text:
        planning_hazards = [
            ("flood", "Flood Risk", "Planning fixture flags watercourse proximity and seasonal surface water risk."),
            ("noise", "Noise Control", "Planning fixture expects construction traffic and plant noise limits."),
            ("heritage", "Heritage Check", "Planning fixture flags a nearby non-designated heritage asset."),
            ("uxo", "UXO Screening", "Planning fixture recommends desktop UXO screening before intrusive works."),
        ]
        lowered = planning_text.lower()
        for keyword, title, note in planning_hazards:
            if keyword in lowered:
                hazards.append(
                    {
                        "id": f"planning-{keyword}",
                        "title": title,
                        "category": keyword,
                        "source": "synthetic planning fixture",
                        "sourceIds": ["planning-fixture"],
                        "evidenceIds": ["planning-fixture"],
                        "confidence": "medium",
                        "note": note,
                    }
                )

    prompt_hazards = _prompt_derived_hazards(site_intent)
    if prompt_hazards:
        hazards = prompt_hazards + hazards

    return hazards, trace_step(
        "extract_hazard_notes",
        "ok" if hazards else "warning",
        "Extracted hazard notes from fixture data and prompt-derived provisional risk profiles.",
        {
            "hazard_count": len(hazards),
            "live_feature_count": len([feature for feature in features if feature.get("dataMode") == "live-public"]),
            "featureStatus": feature_status,
            "provisional_count": len([hazard for hazard in hazards if hazard.get("dataMode") == "provisional-from-user-description"]),
        },
        source_ids=[geo_source_id, "planning-fixture", "provisional-from-user-description"],
        evidence_ids=["geo-fixture", "planning-fixture"] if planning_text else ["geo-fixture"],
    )


def create_annotations(location: dict[str, Any], hazards: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    offsets = [
        (0.0020, -0.0015),
        (-0.0015, 0.0017),
        (0.0012, 0.0022),
        (-0.0023, -0.0010),
        (0.0007, -0.0022),
        (-0.0004, 0.0026),
    ]
    annotations = []
    for index, hazard in enumerate(hazards[:8]):
        centroid = hazard.get("centroid") or {}
        has_real_position = centroid.get("latitude") is not None and centroid.get("longitude") is not None
        lat_offset, lon_offset = offsets[index % len(offsets)]
        annotations.append(
            {
                "id": hazard["id"],
                "title": hazard["title"],
                "category": hazard["category"],
                "latitude": round(float(centroid["latitude"]) if has_real_position else location["latitude"] + lat_offset, 6),
                "longitude": round(float(centroid["longitude"]) if has_real_position else location["longitude"] + lon_offset, 6),
                "confidence": hazard["confidence"],
                "note": hazard["note"],
                "sourceIds": hazard.get("sourceIds", []),
                "evidenceIds": hazard.get("evidenceIds", []),
                "geometry": hazard.get("geometry"),
                "mapFeatureId": hazard.get("mapFeatureId"),
                "layer": hazard.get("layer"),
                "positionMode": "feature-centroid" if has_real_position else "schematic-offset",
                "attribution": hazard.get("attribution"),
            }
        )

    return annotations, trace_step(
        "create_annotations",
        "ok",
        "Converted hazards into 3D map annotations using live feature centroids when available and schematic offsets otherwise.",
        {
            "annotation_count": len(annotations),
            "realPositionCount": len([annotation for annotation in annotations if annotation["positionMode"] == "feature-centroid"]),
            "schematicPositionCount": len([annotation for annotation in annotations if annotation["positionMode"] == "schematic-offset"]),
        },
        evidence_ids=[hazard["id"] for hazard in hazards[:8]],
    )


def generate_site_brief(
    location: dict[str, Any],
    hazards: list[dict[str, Any]],
    planning_text: str | None,
    fixture_pack: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if fixture_pack:
        evidence = fixture_pack.get("evidence", [])
        limitations = [
            "This cached pack is public-safe demo evidence and is not live, exhaustive, or operational advice.",
            "The briefing is not certified RAMS, not emergency guidance, and not work approval.",
            "All hazards need competent human review and current source checks before site work.",
            "Imagery-derived or inferred features are labelled low confidence.",
        ]
        if not planning_text:
            limitations.append("Planning/context notes were unavailable or disabled, so document-derived hazards may be missing.")

        briefing = {
            "site": location["label"],
            "headline": "Cached public-source review pack for early site scoping.",
            "summary": [
                f"Loaded fixture pack '{fixture_pack['name']}' with cached public-source metadata.",
                f"{len(hazards)} candidate hazards were found from cached geospatial and planning/context evidence.",
                "The output is a review pack. It is not certified RAMS and not work approval.",
            ],
            "priority_checks": [hazard["title"] for hazard in hazards[:5]],
            "before_site_visit": [
                "Check current official flood, planning, access, and highway sources before relying on this pack.",
                "Confirm river-edge, bridge, access, and public-realm constraints with a competent reviewer.",
                "Record source age and confidence before escalating any claim into a RAMS workflow.",
            ],
            "limitations": limitations,
            "fixturePack": fixture_pack["name"],
            "dataMode": "cached-public-fixture",
        }

        return briefing, evidence, trace_step(
            "generate_site_brief",
            "ok",
            "Generated deterministic briefing from cached fixture-pack evidence with explicit limitations.",
            {
                "mode": "deterministic",
                "fixturePack": fixture_pack["name"],
                "dataMode": "cached-public-fixture",
                "evidence_count": len(evidence),
                "priority_checks": len(briefing["priority_checks"]),
            },
            source_ids=sorted({source_id for item in evidence for source_id in item.get("sourceIds", [])}),
            evidence_ids=[item["id"] for item in evidence],
        )

    live_hazards = [hazard for hazard in hazards if hazard.get("dataMode") == "live-public"]
    evidence = []
    if live_hazards:
        evidence.append(
            {
                "id": "osm-live",
                "title": "Live OSM / Overpass nearby feature query",
                "source": "OpenStreetMap via Overpass API",
                "status": "real",
                "sourceIds": ["osm-live"],
                "why_it_matters": "Provides live nearby building, access, water, rail, power, and barrier features for 3D overlays.",
            }
        )
        evidence.append(
            {
                "id": "planning-data-live",
                "title": "Live Planning Data point constraints",
                "source": "planning.data.gov.uk/entity.json",
                "status": "real",
                "sourceIds": ["planning-data-live"],
                "why_it_matters": "Provides live planning/designation constraints intersecting the confirmed coordinate.",
            }
        )
    else:
        evidence.append(
            {
                "id": "geo-fixture",
                "title": "Mock geospatial feature pack",
                "source": "fixtures/geospatial_features.json",
                "status": "mocked",
                "why_it_matters": "Provides watercourse, slope, access, bridge, and imagery-derived features for Demo1.",
            }
        )
    if planning_text:
        evidence.append(
            {
                "id": "planning-fixture",
                "title": "Synthetic nearby planning report extract",
                "source": "fixtures/planning_report.txt",
                "status": "mocked",
                "why_it_matters": "Lets the agent demonstrate planning-document hazard extraction without scraping a live LPA portal.",
            }
        )
    if any(hazard.get("dataMode") == "provisional-from-user-description" for hazard in hazards):
        evidence.append(
            {
                "id": "provisional-from-user-description",
                "title": "Prompt-derived provisional risk profile",
                "source": "Submitted site type and visit activity",
                "status": "provisional",
                "why_it_matters": "Adds site/activity-specific review prompts before live evidence sources are connected.",
            }
        )

    limitations = [
        (
            "Live public feature lookups are incomplete and must not be treated as certified RAMS."
            if live_hazards
            else "Demo1 uses synthetic fixtures and must not be treated as certified RAMS."
        ),
        "Prompt-derived risks are provisional and are not evidence-backed site findings.",
        "All hazards need competent human review and current source checks before site work.",
        "Imagery-derived or inferred features are labelled low confidence.",
    ]
    if not planning_text:
        limitations.append("Planning evidence was unavailable, so document-derived hazards may be missing.")

    briefing = {
        "site": location["label"],
        "headline": "Pre-visit 3D field briefing for early RAMS scoping.",
        "summary": [
            f"Coordinate resolved to {location['latitude']}, {location['longitude']} with authority/context label: {location.get('authority', 'not available')}.",
            f"{len(hazards)} candidate hazards were found from {'live public map features' if live_hazards else 'geospatial and planning fixtures'}.",
            "The output is a review pack, not operational approval.",
        ],
        "priority_checks": [hazard["title"] for hazard in hazards[:5]],
        "before_site_visit": [
            "Verify access route, gate width, bridge limits, and parking area.",
            "Confirm flood risk and ground conditions with current official sources.",
            "Escalate heritage, UXO, ecology, or aggressive-animal concerns to competent reviewers.",
        ],
        "limitations": limitations,
    }

    return briefing, evidence, trace_step(
        "generate_site_brief",
        "ok",
        "Generated deterministic fallback briefing with explicit limitations and evidence references.",
        {
            "mode": "deterministic",
            "evidence_count": len(evidence),
            "priority_checks": len(briefing["priority_checks"]),
        },
        evidence_ids=[item["id"] for item in evidence],
    )


def apply_bedrock_briefing(
    config: RuntimeConfig,
    location: dict[str, Any],
    hazards: list[dict[str, Any]],
    briefing: dict[str, Any],
    evidence: list[dict[str, Any]],
    planning_text: str | None,
) -> tuple[dict[str, Any], dict[str, Any], str, str | None]:
    if not config.bedrock_requested:
        return briefing, trace_step(
            "generate_bedrock_briefing",
            "disabled",
            "Bedrock briefing was not requested for this run; deterministic briefing remains active.",
            {"mode": "deterministic", "requested": False},
            source_ids=["bedrock-briefing"],
            evidence_ids=[item["id"] for item in evidence],
        ), "disabled", "Bedrock was not requested."

    if not config.bedrock_enabled:
        return briefing, trace_step(
            "generate_bedrock_briefing",
            "disabled",
            "Bedrock briefing is disabled by environment; deterministic briefing remains active.",
            {
                "mode": "deterministic",
                "requested": True,
                "enabled": False,
                "modelId": None,
                "maxTokens": None,
                "temperature": None,
            },
            source_ids=["bedrock-briefing"],
            evidence_ids=[item["id"] for item in evidence],
            fallback_reason="Set ENABLE_BEDROCK=true with AWS credentials to use the live Bedrock path.",
        ), "disabled", "ENABLE_BEDROCK is not true."

    try:
        bedrock_briefing, metadata = generate_bedrock_briefing(
            config=config,
            location=location,
            hazards=hazards,
            deterministic_briefing=briefing,
            evidence=evidence,
            planning_available=planning_text is not None,
        )
    except (BedrockAdapterError, Exception) as exc:
        fallback_reason = f"Bedrock briefing failed; deterministic briefing used. Reason: {exc}"
        return briefing, trace_step(
            "generate_bedrock_briefing",
            "fallback",
            "Bedrock briefing failed; deterministic briefing remains active.",
            {
                "mode": "deterministic-fallback",
                "modelId": config.bedrock_model_id,
                "awsRegion": config.aws_region,
                "maxTokens": config.bedrock_max_tokens,
                "temperature": config.bedrock_temperature,
                "errorType": exc.__class__.__name__,
            },
            source_ids=["bedrock-briefing"],
            evidence_ids=[item["id"] for item in evidence],
            fallback_reason=fallback_reason,
        ), "fallback", fallback_reason

    bedrock_status = "mocked" if metadata.get("mode") == "bedrock-mock" else "real"
    return bedrock_briefing, trace_step(
        "generate_bedrock_briefing",
        "ok",
        "Generated one Bedrock-backed briefing from structured hazards and evidence.",
        metadata,
        source_ids=["bedrock-briefing"],
        evidence_ids=[item["id"] for item in evidence],
        duration_ms=int(metadata.get("latencyMs", 0)),
    ), bedrock_status, None


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_flatten_text(item))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(_flatten_text(item))
        return parts
    return []


def _find_unsupported_generated_claims(text: str, blocked_terms: list[str]) -> list[str]:
    normalized = " ".join(text.lower().split())
    matches: list[str] = []
    for term in blocked_terms:
        start = normalized.find(term)
        while start != -1:
            if not _is_negated_safety_boundary(normalized, start, term):
                matches.append(term)
                break
            start = normalized.find(term, start + len(term))
    return matches


def _is_negated_safety_boundary(text: str, claim_start: int, term: str) -> bool:
    prefix = text[max(0, claim_start - 90) : claim_start]
    claim = text[claim_start : claim_start + len(term)]
    boundary_text = f"{prefix}{claim}"
    safe_boundary_patterns = [
        f"cannot {term}",
        f"can't {term}",
        f"do not {term}",
        f"does not {term}",
        f"must not {term}",
        f"must not be treated as {term}",
        f"not {term}",
        f"not a {term}",
        f"not an {term}",
        f"not operational {term}",
        f"without {term}",
        "not a certified rams or work approval",
        "not certified rams, emergency guidance, or work approval",
    ]
    return any(pattern in boundary_text for pattern in safe_boundary_patterns)


def safety_gate(request: dict[str, Any], briefing: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    user_text = " ".join(
        str(request.get(key, ""))
        for key in ("goal", "useCase", "additionalRequest")
    ).lower()
    blocked_terms = [
        "certified rams",
        "certify rams",
        "emergency route",
        "emergency guidance",
        "guarantee safe",
        "approve work",
        "approved for work",
        "work approval",
        "replace competent",
    ]
    request_rules = [term for term in blocked_terms if term in user_text]
    generated_text = " ".join(_flatten_text(briefing))
    generated_rules = _find_unsupported_generated_claims(generated_text, blocked_terms)
    blocked = bool(request_rules or generated_rules)
    decision = {
        "allowed": not blocked,
        "level": "blocked" if blocked else "review_required",
        "message": (
            "Blocked: this demo cannot certify RAMS, approve work, or provide emergency guidance."
            if blocked
            else "Allowed as a non-certified pre-visit briefing that requires human review."
        ),
        "triggeredRules": sorted(set(request_rules + generated_rules)),
        "triggeredSources": {
            "request": request_rules,
            "generatedBriefing": generated_rules,
        },
        "requiresHumanReview": True,
        "decisionId": "safety-demo1-blocked" if blocked else "safety-demo1-review-required",
    }
    if blocked:
        briefing["headline"] = "Request blocked by safety gate."
        briefing["summary"] = [decision["message"]]
        briefing["priority_checks"] = []

    return decision, trace_step(
        "safety_gate",
        "blocked" if blocked else "ok",
        decision["message"],
        {
            "allowed": decision["allowed"],
            "level": decision["level"],
            "triggeredRules": decision["triggeredRules"],
            "triggeredSources": decision["triggeredSources"],
        },
        evidence_ids=["safety-policy"],
    )


def _prompt_derived_hazards(site_intent: dict[str, Any] | None) -> list[dict[str, Any]]:
    site_intent = site_intent or {}
    site_types = set(site_intent.get("siteTypes", []))
    activities = set(site_intent.get("activities", []))
    hazards: list[dict[str, Any]] = []
    confidence = "medium" if site_intent.get("coordinate") or site_intent.get("postcode") else "low"

    def add(key: str, title: str, category: str, note: str) -> None:
        hazards.append(
            {
                "id": f"prompt-{key}",
                "title": title,
                "category": category,
                "source": "user description",
                "sourceIds": ["provisional-from-user-description"],
                "evidenceIds": [],
                "confidence": confidence,
                "note": note,
                "dataMode": "provisional-from-user-description",
            }
        )

    if "solar" in site_types:
        add("pv-electrical", "PV electrical isolation and inverter boundary", "electrical", "Confirm isolation state, inverter/skid access, cable routes, and any energised-equipment boundaries.")
        add("pv-module-rows", "PV module row trip and access constraints", "access", "Review row spacing, low-level obstructions, cable trays, vegetation, and safe walking routes.")
    if "quarry" in site_types:
        add("quarry-edge", "Excavation edge and unstable ground", "ground", "Confirm exclusion zones, edge protection, loose faces, slope stability, and stop-work criteria.")
        add("quarry-plant", "Heavy plant and haul-road interface", "traffic", "Check plant movement, visibility, reversing controls, haul roads, and pedestrian segregation.")
    if {"substation", "bess"} & site_types:
        add("high-energy-assets", "High-energy asset access boundary", "electrical", "Confirm permits, isolation, arc-flash/electrical boundaries, emergency contacts, and competent supervision.")
    if "roof" in site_types:
        add("roof-work", "Work-at-height and fragile roof controls", "work_at_height", "Confirm access, edge protection, rooflights, weather limits, rescue plan, and load restrictions.")
    if "rural_field" in site_types:
        add("rural-field", "Rural access, livestock, and soft-ground controls", "access", "Check gates, livestock, parking, soft ground, remote communications, and lone-working arrangements.")
    if "drainage_slope" in activities:
        add("drainage-slope", "Drainage, slope, and slip conditions", "ground", "Review recent rain, ditches, culverts, gradient, unstable banks, and safe inspection positions.")
    if "access_track" in activities:
        add("access-track", "Access track, gate, bridge, and culvert constraints", "access", "Check track width, gate width, bridge limits, culvert condition, vehicle suitability, and turning areas.")
    if "delivery" in activities:
        add("delivery-interface", "Delivery, unloading, and lifting interface", "traffic", "Confirm delivery route, banksman need, unloading area, overhead lines, exclusion zones, and public interface.")
    if "inspection" in activities or "survey" in activities:
        add("walkover", "Walkover survey and lone-working controls", "survey", "Confirm communication, welfare, weather, route plan, emergency contact, and abort criteria.")
    return hazards[:8]


def architecture_snapshot(
    trace: list[dict[str, Any]],
    request_summary: dict[str, Any],
    sources: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    safety: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    return {
        "runOverview": {
            "siteName": request_summary["siteName"],
            "goal": request_summary["goal"],
            "coordinate": f"{request_summary['latitude']}, {request_summary['longitude']}",
            "fixturePack": request_summary.get("fixturePack") or "synthetic-default",
            "planningFixture": "enabled" if request_summary["includePlanningFixture"] else "disabled",
            "mapMode": (
                runtime.get("liveFeatureStatus", {}).get("status")
                if runtime.get("liveApiCalls")
                else "fallback"
                if request_summary["simulateMapFailure"]
                else "fixture"
            ),
            "briefingMode": runtime["briefingMode"],
            "safetyLevel": safety["level"],
        },
        "nodes": [
            {"id": "ui", "label": "React/Vite UI", "boundary": "frontend"},
            {"id": "api", "label": "FastAPI run endpoint", "boundary": "backend"},
            {"id": "agent", "label": "3D-RAMS agent loop", "boundary": "backend"},
            {"id": "fixtures", "label": "Fixture data", "boundary": "mock data"},
            {"id": "aws", "label": "Hosted AWS runtime", "boundary": "server-side"},
        ],
        "edges": [
            {"from": "ui", "to": "api", "label": "POST /api/run"},
            {"from": "api", "to": "agent", "label": "validated request"},
            {"from": "agent", "to": "fixtures", "label": "tool calls"},
            {"from": "agent", "to": "ui", "label": "scene, evidence, trace"},
            {"from": "agent", "to": "aws", "label": "Bedrock, DynamoDB, S3, CloudWatch when hosted"},
        ],
        "currentTrace": [
            {
                "id": step["id"],
                "name": step["name"],
                "status": step["status"],
                "summary": step["summary"],
                "durationMs": step["durationMs"],
                "sourceIds": step["sourceIds"],
                "evidenceIds": step["evidenceIds"],
                "fallbackReason": step["fallbackReason"],
                "output": step["output"],
            }
            for step in trace
        ],
        "sources": sources,
        "evidenceFlow": [
            {
                "id": item["id"],
                "title": item["title"],
                "status": item["status"],
                "feeds": ["annotations", "briefing", "trace"],
            }
            for item in evidence
        ],
        "safetyGate": {
            "allowed": safety["allowed"],
            "level": safety["level"],
            "message": safety["message"],
            "triggeredRules": safety["triggeredRules"],
            "requiresHumanReview": safety["requiresHumanReview"],
            "awsMapping": "Current local safety gate; future Bedrock Guardrails plus human approval queue",
        },
        "awsPath": [
            {"current": "Deterministic Python tool layer", "hosted": "Lambda/FastAPI executes allowlisted tools"},
            {"current": "Bedrock planner/synthesis when enabled", "hosted": "Server-side Bedrock Claude call capped per run"},
            {"current": "JSON trace in API response", "hosted": "CloudWatch structured logs plus UI trace"},
            {"current": "Evidence list in response", "hosted": "Private S3 upload targets and metadata"},
            {"current": "Session state", "hosted": "DynamoDB session/run metadata with TTL"},
            {"current": "Rule-based safety gate", "future": "Bedrock Guardrails plus human review"},
        ],
        "realVsMocked": [
            {"component": "Agent workflow", "status": "real deterministic code"},
            {
                "component": "Fixture pack",
                "status": (
                    f"cached public fixture: {runtime.get('fixturePack')}"
                    if runtime.get("fixturePack")
                    else "synthetic default fixtures"
                ),
            },
            {"component": "Bedrock planner/synthesis", "status": str(runtime["briefingMode"])},
            {
                "component": "3D viewer",
                "status": "real Cesium terrain/buildings when VITE_CESIUM_ION_TOKEN is configured",
            },
            {
                "component": "Live map features",
                "status": (
                    f"real live public APIs: {runtime.get('liveFeatureStatus', {}).get('status')}"
                    if runtime.get("liveApiCalls")
                    else "disabled or fallback"
                ),
            },
            {
                "component": "Planning documents",
                "status": "cached public-safe notes" if runtime.get("fixturePack") else "synthetic fixture",
            },
            {"component": "Live Google 3D / Earth", "status": "not used in Demo1"},
            {"component": "CloudWatch / S3 / DynamoDB", "status": "live in hosted MVP for logs, upload metadata, and session trace"},
            {"component": "Guardrails / AgentCore / Cognito", "status": "future production path"},
        ],
        "runtime": runtime,
    }
