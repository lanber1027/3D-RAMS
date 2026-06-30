from __future__ import annotations

import re
from typing import Any

import httpx

from .tools import trace_step


_CACHED_CANDIDATES: list[dict[str, Any]] = [
    {
        "candidateId": "candidate-greenacre-solar-demo",
        "matchTerms": ["greenacre farm", "greenacre solar farm"],
        "name": "Greenacre Solar Farm",
        "nearestTown": "Demo Town",
        "nearestRoad": "Demo access track",
        "countyOrAuthority": "Synthetic Demo Authority",
        "postcodeArea": "DEMO",
        "latitude": 52.12,
        "longitude": -1.42,
        "confidence": "medium",
        "source": "synthetic-demo-location-fixture",
        "dataMode": "synthetic-demo",
        "reason": "Synthetic cached candidate used to exercise the V3 confirmation loop without claiming live public evidence.",
        "fixturePack": None,
    }
]


def resolve_location_candidates(
    site_name: str,
    message: str,
    *,
    intent: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve named-site-only prompts through source-labelled candidate tools.

    This MVP resolver is intentionally fixture-first. It does not invent coordinates
    from the LLM and does not run broad live search from the frontend.
    """

    intent = intent or {}
    normalized_site = _normalize(site_name)
    normalized_message = _normalize(message)
    matches = [
        _public_candidate(candidate)
        for candidate in _CACHED_CANDIDATES
        if any(term in normalized_site or term in normalized_message for term in candidate["matchTerms"])
    ][:3]
    sources_used = sorted({candidate["source"] for candidate in matches}) if matches else []
    postcode_candidate, postcode_trace = _postcode_candidate(site_name, intent)
    if postcode_candidate:
        matches = [postcode_candidate, *matches][:3]
        sources_used = sorted({candidate["source"] for candidate in matches})
    status = "ok" if matches else "warning"
    resolution = {
        "siteName": site_name,
        "intent": {
            "postcode": intent.get("postcode"),
            "outcode": intent.get("outcode"),
            "nearestTown": intent.get("nearestTown"),
            "localAuthority": intent.get("localAuthority"),
            "siteTypes": intent.get("siteTypes", []),
            "activities": intent.get("activities", []),
        },
        "needsLocationConfirmation": bool(matches),
        "locationCandidates": matches,
        "confirmedLocation": None,
        "nextStage": "confirm_location" if matches else "provide_location_detail",
        "resolverMode": "fixture-first-plus-postcodes-io",
        "minimumEvidenceMet": bool(matches),
        "message": (
            "One or more source-labelled candidate locations were found and need user confirmation."
            if matches
            else "No reliable cached/public candidate was found. Ask the user for postcode, coordinates, nearest town/road, or local authority."
        ),
        "provisionalRisks": provisional_risks(intent),
    }
    trace_status = status if not postcode_trace else postcode_trace.get("status", status)
    trace = trace_step(
        "resolve_location_candidates",
        trace_status,
        "Searched allowlisted cached location candidates before starting the review workflow.",
        {
            "siteName": site_name,
            "resolverMode": resolution["resolverMode"],
            "candidateCount": len(matches),
            "candidateIds": [candidate["candidateId"] for candidate in matches],
            "nextStage": resolution["nextStage"],
            "sourcesUsed": sources_used,
            "postcodeLookup": postcode_trace,
            "nearestTown": intent.get("nearestTown"),
            "provisionalRiskCount": len(resolution["provisionalRisks"]),
        },
        source_ids=sources_used or ["location-resolver-fixtures"],
    )
    return resolution, trace


def public_candidate_by_id(candidate_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("candidateId") == candidate_id:
            return candidate
    return None


def confirmed_location_to_request(candidate: dict[str, Any], *, message: str, use_bedrock: bool) -> dict[str, Any]:
    request: dict[str, Any] = {
        "siteName": candidate.get("name"),
        "goal": "Hosted pre-visit RAMS-style review pack",
        "fixturePack": candidate.get("fixturePack"),
        "includePlanningFixture": True,
        "simulateMapFailure": False,
        "useBedrock": use_bedrock,
        "agentMode": "llm-planner" if use_bedrock else "deterministic",
        "additionalRequest": message,
        "siteIntent": candidate.get("intent") or {},
        "locationResolution": {
            "confirmedLocation": candidate,
            "source": candidate.get("source"),
            "confidence": candidate.get("confidence"),
            "dataMode": candidate.get("dataMode"),
        },
    }
    if candidate.get("latitude") is not None and candidate.get("longitude") is not None:
        request["latitude"] = float(candidate["latitude"])
        request["longitude"] = float(candidate["longitude"])
        if not candidate.get("fixturePack"):
            request["fixturePack"] = None
    return request


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if key != "matchTerms" and value is not None
    }


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _postcode_candidate(site_name: str, intent: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    postcode = intent.get("postcode")
    outcode = intent.get("outcode")
    if not postcode and not outcode:
        return None, None
    try:
        if postcode:
            url = f"https://api.postcodes.io/postcodes/{postcode.replace(' ', '')}"
        else:
            url = f"https://api.postcodes.io/outcodes/{outcode}"
        response = httpx.get(
            url,
            headers={"User-Agent": "3D-RAMS-hackathon-demo/0.1"},
            timeout=4.0,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") or {}
        latitude = result.get("latitude")
        longitude = result.get("longitude")
        if latitude is None or longitude is None:
            return None, {"status": "warning", "source": "postcodes.io", "reason": "No coordinate returned."}
        source_label = "postcodes.io/postcodes" if postcode else "postcodes.io/outcodes"
        area = postcode or outcode
        return {
            "candidateId": f"candidate-postcodes-io-{re.sub(r'[^A-Za-z0-9]+', '-', str(area)).strip('-').lower()}",
            "name": site_name,
            "nearestTown": intent.get("nearestTown") or result.get("admin_ward") or result.get("parish"),
            "nearestRoad": None,
            "countyOrAuthority": result.get("admin_district") or result.get("admin_county") or intent.get("localAuthority"),
            "postcodeArea": result.get("outcode") or outcode or (postcode.split()[0] if postcode else None),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "confidence": "medium" if postcode else "low",
            "source": source_label,
            "dataMode": "source-labelled-location",
            "reason": "Postcode/outcode lookup gives an approximate location candidate. Confirm before review tools run.",
            "fixturePack": None,
            "intent": intent,
        }, {"status": "ok", "source": source_label, "postcode": postcode, "outcode": outcode}
    except Exception as exc:
        return None, {
            "status": "warning",
            "source": "postcodes.io",
            "postcode": postcode,
            "outcode": outcode,
            "reason": f"Lookup failed: {exc.__class__.__name__}",
        }


def provisional_risks(intent: dict[str, Any] | None) -> list[dict[str, Any]]:
    intent = intent or {}
    site_types = set(intent.get("siteTypes", []))
    activities = set(intent.get("activities", []))
    risks: list[dict[str, Any]] = []

    def add(key: str, title: str, note: str) -> None:
        risks.append(
            {
                "id": f"provisional-{key}",
                "title": title,
                "category": key,
                "source": "user description",
                "sourceIds": ["provisional-from-user-description"],
                "evidenceIds": [],
                "confidence": "low",
                "note": note,
                "dataMode": "provisional-from-user-description",
            }
        )

    if "solar" in site_types:
        add("solar-electrical", "PV electrical isolation and inverter interface", "Confirm isolation boundaries, inverter/skid locations, and any energised equipment before access.")
        add("solar-glare", "Panel rows, trip edges, and low-level obstructions", "Expect repetitive rows, cable trays, and uneven ground around mounting structures.")
    if "quarry" in site_types:
        add("quarry-edge", "Excavation edge and unstable ground review", "Confirm exclusion zones, slope stability, loose faces, and edge protection before inspection.")
        add("quarry-traffic", "Heavy plant and haul-road interface", "Check traffic management, visibility, reversing areas, and separation from operating plant.")
    if {"substation", "bess"} & site_types:
        add("electrical", "High-energy electrical asset boundary", "Confirm access permissions, isolation state, arc-flash/electrical boundaries, and emergency contacts.")
    if "roof" in site_types:
        add("roof-access", "Work-at-height and fragile roof review", "Confirm edge protection, rooflights, access route, weather limits, and rescue plan.")
    if "rural_field" in site_types:
        add("rural-access", "Rural access, livestock, and ground condition review", "Check gates, livestock, soft ground, parking, and remote lone-working arrangements.")
    if "drainage_slope" in activities:
        add("slope-drainage", "Drainage, slope, and slip condition review", "Review gradient, wet ground, ditches, culverts, recent rain, and safe walking route.")
    if "access_track" in activities:
        add("track-access", "Access track, bridge, and turning constraint review", "Check track width, gate width, bridge limits, culverts, and vehicle turning areas.")
    if "delivery" in activities:
        add("delivery", "Delivery and lifting interface review", "Confirm banksman need, delivery route, unloading area, overhead lines, and pedestrian exclusion.")
    if "inspection" in activities or "survey" in activities:
        add("survey", "Survey walkover and lone-working controls", "Confirm communications, welfare, weather, route plan, and stop-work criteria.")
    if not risks:
        add("generic", "Generic pre-visit controls pending location", "Provide postcode, coordinates, or source evidence so this can become site-specific.")
    return risks[:8]
