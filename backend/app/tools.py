from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .fixtures import load_json, load_text


def trace_step(name: str, status: str, summary: str, output: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output": output,
    }


def resolve_location(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    latitude = float(request.get("latitude", 52.2053))
    longitude = float(request.get("longitude", -1.6022))
    location = {
        "label": request.get("siteName") or "Demo rural field fixture",
        "latitude": latitude,
        "longitude": longitude,
        "authority": "Syntheticshire District Council",
        "coordinate_system": "WGS84",
        "confidence": "high" if request.get("latitude") and request.get("longitude") else "medium",
    }
    return location, trace_step(
        "resolve_location",
        "ok",
        "Resolved the submitted coordinate to the public-safe demo location fixture.",
        {"location": location},
    )


def load_geospatial_features(location: dict[str, Any], simulate_failure: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if simulate_failure:
        features = load_json("geospatial_features.json")["fallback_features"]
        return features, trace_step(
            "load_geospatial_features",
            "fallback",
            "Live 3D/map provider was unavailable; loaded local fallback geospatial fixture.",
            {"feature_count": len(features), "source": "fixtures/geospatial_features.json"},
        )

    features = load_json("geospatial_features.json")["features"]
    return features, trace_step(
        "load_geospatial_features",
        "ok",
        "Loaded mock geospatial features around the coordinate.",
        {"feature_count": len(features), "source": "fixtures/geospatial_features.json"},
    )


def build_scene_config(location: dict[str, Any], features: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    scene = {
        "provider": "cesium-local-fixture",
        "center": {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "heightMeters": 260,
        },
        "camera": {
            "headingDegrees": 25,
            "pitchDegrees": -42,
            "rangeMeters": 1800,
        },
        "terrain": "ellipsoid fallback",
        "featureCount": len(features),
        "note": "No Google Maps, Google Earth, or Cesium ion key is required for Demo1.",
    }
    return scene, trace_step(
        "build_scene_config",
        "ok",
        "Created a 3D scene configuration from the resolved coordinate and feature fixture.",
        {"scene": scene},
    )


def load_planning_context(include_planning_fixture: bool) -> tuple[str | None, dict[str, Any]]:
    if not include_planning_fixture:
        return None, trace_step(
            "load_planning_context",
            "warning",
            "Planning fixture was disabled; briefing will only use geospatial context.",
            {"source": None},
        )

    text = load_text("planning_report.txt")
    return text, trace_step(
        "load_planning_context",
        "ok",
        "Loaded synthetic planning-document fixture for hazard extraction.",
        {"source": "fixtures/planning_report.txt", "characters": len(text)},
    )


def extract_hazard_notes(planning_text: str | None, features: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hazards: list[dict[str, Any]] = []

    for feature in features:
        if feature["type"] in {"watercourse", "slope", "access_track", "bridge"}:
            hazards.append(
                {
                    "id": f"geo-{feature['id']}",
                    "title": feature["label"],
                    "category": feature["type"],
                    "source": "geospatial fixture",
                    "confidence": feature.get("confidence", "medium"),
                    "note": feature["risk_note"],
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
                        "confidence": "medium",
                        "note": note,
                    }
                )

    return hazards, trace_step(
        "extract_hazard_notes",
        "ok" if hazards else "warning",
        "Extracted hazard notes from deterministic rules over fixture data.",
        {"hazard_count": len(hazards)},
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
        lat_offset, lon_offset = offsets[index % len(offsets)]
        annotations.append(
            {
                "id": hazard["id"],
                "title": hazard["title"],
                "category": hazard["category"],
                "latitude": round(location["latitude"] + lat_offset, 6),
                "longitude": round(location["longitude"] + lon_offset, 6),
                "confidence": hazard["confidence"],
                "note": hazard["note"],
            }
        )

    return annotations, trace_step(
        "create_annotations",
        "ok",
        "Converted hazards into 3D map annotations with fixture offsets.",
        {"annotation_count": len(annotations)},
    )


def generate_site_brief(
    location: dict[str, Any],
    hazards: list[dict[str, Any]],
    planning_text: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    evidence = [
        {
            "id": "geo-fixture",
            "title": "Mock geospatial feature pack",
            "source": "fixtures/geospatial_features.json",
            "status": "mocked",
            "why_it_matters": "Provides watercourse, slope, access, bridge, and imagery-derived features for Demo1.",
        }
    ]
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

    limitations = [
        "Demo1 uses synthetic fixtures and must not be treated as certified RAMS.",
        "All hazards need competent human review and current source checks before site work.",
        "Imagery-derived or inferred features are labelled low confidence.",
    ]
    if not planning_text:
        limitations.append("Planning evidence was unavailable, so document-derived hazards may be missing.")

    briefing = {
        "site": location["label"],
        "headline": "Pre-visit 3D field briefing for early RAMS scoping.",
        "summary": [
            f"Coordinate resolved to {location['latitude']}, {location['longitude']} in the demo authority fixture.",
            f"{len(hazards)} candidate hazards were found from geospatial and planning fixtures.",
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
        "Generated a RAMS-style briefing with explicit limitations and evidence references.",
        {"evidence_count": len(evidence), "priority_checks": len(briefing["priority_checks"])},
    )


def safety_gate(request: dict[str, Any], briefing: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    user_text = " ".join(
        str(request.get(key, ""))
        for key in ("goal", "useCase", "additionalRequest")
    ).lower()
    blocked_terms = ["certified rams", "emergency route", "guarantee safe", "approve work", "replace competent"]
    blocked = any(term in user_text for term in blocked_terms)
    decision = {
        "allowed": not blocked,
        "level": "blocked" if blocked else "review_required",
        "message": (
            "Blocked: this demo cannot certify RAMS, approve work, or provide emergency guidance."
            if blocked
            else "Allowed as a non-certified pre-visit briefing that requires human review."
        ),
    }
    if blocked:
        briefing["headline"] = "Request blocked by safety gate."
        briefing["summary"] = [decision["message"]]
        briefing["priority_checks"] = []

    return decision, trace_step(
        "safety_gate",
        "blocked" if blocked else "ok",
        decision["message"],
        {"allowed": decision["allowed"], "level": decision["level"]},
    )


def architecture_snapshot(trace: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "ui", "label": "React/Vite UI", "boundary": "frontend"},
            {"id": "api", "label": "FastAPI run endpoint", "boundary": "backend"},
            {"id": "agent", "label": "3D-RAMS agent loop", "boundary": "backend"},
            {"id": "fixtures", "label": "Fixture data", "boundary": "mock data"},
            {"id": "aws", "label": "Future AWS path", "boundary": "production stretch"},
        ],
        "edges": [
            {"from": "ui", "to": "api", "label": "POST /api/run"},
            {"from": "api", "to": "agent", "label": "validated request"},
            {"from": "agent", "to": "fixtures", "label": "tool calls"},
            {"from": "agent", "to": "ui", "label": "scene, evidence, trace"},
            {"from": "agent", "to": "aws", "label": "Bedrock, DynamoDB, S3, CloudWatch later"},
        ],
        "currentTrace": [{"name": step["name"], "status": step["status"]} for step in trace],
        "realVsMocked": [
            {"component": "Agent workflow", "status": "real deterministic code"},
            {"component": "3D viewer", "status": "real local Cesium scene"},
            {"component": "Planning documents", "status": "synthetic fixture"},
            {"component": "Live Google 3D / Earth", "status": "not used in Demo1"},
            {"component": "AWS Bedrock / CloudWatch", "status": "designed, not required for Demo1"},
        ],
    }

