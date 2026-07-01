from __future__ import annotations

import math
import re
from typing import Any

import httpx

from .geoapify_resolver import resolve_geoapify_candidates
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

_UK_ANCHORS: list[dict[str, float | str]] = [
    {"name": "London", "latitude": 51.5074, "longitude": -0.1278},
    {"name": "Manchester", "latitude": 53.4808, "longitude": -2.2426},
    {"name": "Birmingham", "latitude": 52.4862, "longitude": -1.8904},
    {"name": "Leeds", "latitude": 53.8008, "longitude": -1.5491},
    {"name": "Liverpool", "latitude": 53.4084, "longitude": -2.9916},
    {"name": "Newcastle", "latitude": 54.9783, "longitude": -1.6178},
    {"name": "Edinburgh", "latitude": 55.9533, "longitude": -3.1883},
    {"name": "Glasgow", "latitude": 55.8642, "longitude": -4.2518},
    {"name": "Cardiff", "latitude": 51.4816, "longitude": -3.1791},
    {"name": "Bristol", "latitude": 51.4545, "longitude": -2.5879},
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
    coordinate_candidate, coordinate_trace = _coordinate_candidate(site_name, intent)
    matches = [
        _public_candidate(candidate)
        for candidate in _CACHED_CANDIDATES
        if any(term in normalized_site or term in normalized_message for term in candidate["matchTerms"])
    ][:3]
    if coordinate_candidate:
        matches = [coordinate_candidate]
    sources_used = sorted({candidate["source"] for candidate in matches}) if matches else []
    postcode_candidate, postcode_trace = _postcode_candidate(site_name, intent)
    if postcode_candidate and not coordinate_candidate:
        matches = [postcode_candidate, *matches][:3]
        sources_used = sorted({candidate["source"] for candidate in matches})
    geoapify_trace = None
    skip_geoapify_for_vague_hint = bool(intent.get("vagueLocationHint") and not intent.get("namedSiteHint"))
    if not postcode_candidate and not matches and skip_geoapify_for_vague_hint:
        geoapify_trace = {
            "status": "skipped",
            "source": "geoapify/geocode/search",
            "reason": "Vague place/area hints require user-provided postcode, coordinate, specific site name, or public evidence before live candidate lookup.",
        }
    elif not postcode_candidate and not matches:
        geoapify_candidates, geoapify_trace = resolve_geoapify_candidates(site_name, intent)
        if geoapify_candidates:
            matches = geoapify_candidates[:3]
            sources_used = sorted({candidate["source"] for candidate in matches})
    status = "ok" if matches else "warning"
    resolution = {
        "siteName": site_name,
        "intent": {
            "postcode": intent.get("postcode"),
            "outcode": intent.get("outcode"),
            "nearestTown": intent.get("nearestTown"),
            "areaHint": intent.get("areaHint"),
            "placeHint": intent.get("placeHint"),
            "localAuthority": intent.get("localAuthority"),
            "siteTypes": intent.get("siteTypes", []),
            "activities": intent.get("activities", []),
            "coordinate": intent.get("coordinate"),
        },
        "needsLocationConfirmation": bool(matches),
        "locationCandidates": matches,
        "confirmedLocation": None,
        "nextStage": "confirm_location" if matches else "provide_location_detail",
        "resolverMode": "coordinate-postcode-confirmation-plus-fixtures",
        "minimumEvidenceMet": bool(matches),
        "message": (
            "One or more source-labelled candidate locations were found and need user confirmation."
            if matches
            else "No reliable cached/public candidate was found. Ask the user for postcode, coordinates, nearest town/road, or local authority."
        ),
        "provisionalRisks": provisional_risks(intent),
    }
    trace_status = status
    if coordinate_trace:
        trace_status = coordinate_trace.get("status", status)
    if postcode_trace:
        trace_status = postcode_trace.get("status", status)
    if geoapify_trace and geoapify_trace.get("status") in {"ok", "warning"}:
        trace_status = geoapify_trace["status"]
    trace = trace_step(
        "resolve_location_candidates",
        trace_status,
        "Searched allowlisted cached, postcode, and optional Geoapify candidate tools before starting the review workflow.",
        {
            "siteName": site_name,
            "resolverMode": resolution["resolverMode"],
            "candidateCount": len(matches),
            "candidateIds": [candidate["candidateId"] for candidate in matches],
            "nextStage": resolution["nextStage"],
            "sourcesUsed": sources_used,
            "coordinateLookup": coordinate_trace,
            "postcodeLookup": postcode_trace,
            "geoapifyLookup": geoapify_trace,
            "nearestTown": intent.get("nearestTown"),
            "areaHint": intent.get("areaHint"),
            "placeHint": intent.get("placeHint"),
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
            "locationContext": candidate.get("locationContext"),
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
        location_context = _build_location_context(
            latitude=float(latitude),
            longitude=float(longitude),
            submitted_type="postcode" if postcode else "outcode",
            submitted_value=str(area),
            intent=intent,
            postcode_result=result,
        )
        return {
            "candidateId": f"candidate-postcodes-io-{re.sub(r'[^A-Za-z0-9]+', '-', str(area)).strip('-').lower()}",
            "name": site_name,
            "nearestTown": intent.get("nearestTown") or result.get("admin_ward") or result.get("parish"),
            "nearestRoad": None,
            "countyOrAuthority": result.get("admin_district") or result.get("admin_county") or intent.get("localAuthority"),
            "postcodeArea": result.get("outcode") or outcode or (postcode.split()[0] if postcode else None),
            "ward": result.get("admin_ward"),
            "parish": result.get("parish"),
            "region": result.get("region"),
            "country": result.get("country"),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "confidence": "medium" if postcode else "low",
            "source": source_label,
            "dataMode": "source-labelled-location",
            "reason": "Postcode/outcode lookup gives an approximate location candidate. Confirm before review tools run.",
            "locationContext": location_context,
            "relativeLocation": location_context["relativeLocation"],
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


def _coordinate_candidate(site_name: str, intent: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    coordinate = intent.get("coordinate")
    if not coordinate:
        return None, None
    latitude = float(coordinate[0])
    longitude = float(coordinate[1])
    reverse_result, reverse_trace = _reverse_postcode_context(latitude, longitude)
    location_context = _build_location_context(
        latitude=latitude,
        longitude=longitude,
        submitted_type="coordinate",
        submitted_value=f"{_format_coordinate(latitude)}, {_format_coordinate(longitude)}",
        intent=intent,
        postcode_result=reverse_result,
    )
    source_ids = ["user-supplied-coordinate"]
    if reverse_trace.get("status") == "ok":
        source_ids.append("postcodes.io/nearest")
    candidate_id = re.sub(
        r"[^A-Za-z0-9]+",
        "-",
        f"coordinate-{_format_coordinate(latitude)}-{_format_coordinate(longitude)}",
    ).strip("-").lower()
    candidate = {
        "candidateId": f"candidate-{candidate_id}",
        "name": site_name or "User-supplied coordinate",
        "nearestTown": intent.get("nearestTown") or location_context.get("nearestTown"),
        "nearestRoad": None,
        "countyOrAuthority": location_context.get("district") or location_context.get("county") or intent.get("localAuthority"),
        "postcodeArea": location_context.get("postcodeArea"),
        "ward": location_context.get("ward"),
        "parish": location_context.get("parish"),
        "region": location_context.get("region"),
        "country": location_context.get("country"),
        "latitude": latitude,
        "longitude": longitude,
        "confidence": "medium",
        "source": "user-supplied-coordinate",
        "sourceIds": source_ids,
        "dataMode": "source-labelled-coordinate",
        "reason": "The user supplied this coordinate. Confirm it is the intended site before review tools run.",
        "locationContext": location_context,
        "relativeLocation": location_context["relativeLocation"],
        "fixturePack": None,
        "intent": intent,
    }
    trace = {
        **reverse_trace,
        "source": "user-supplied-coordinate",
        "reversePostcodeSource": reverse_trace.get("source"),
        "coordinate": {"latitude": latitude, "longitude": longitude},
        "relativeLocation": location_context["relativeLocation"],
    }
    return candidate, trace


def _reverse_postcode_context(latitude: float, longitude: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        response = httpx.get(
            "https://api.postcodes.io/postcodes",
            params={"lat": latitude, "lon": longitude, "limit": 1},
            headers={"User-Agent": "3D-RAMS-hackathon-demo/0.1"},
            timeout=3.0,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("result") or []
        if not results:
            return None, {"status": "warning", "source": "postcodes.io/nearest", "reason": "No nearest postcode context returned."}
        result = results[0] or {}
        return result, {
            "status": "ok",
            "source": "postcodes.io/nearest",
            "postcode": result.get("postcode"),
            "outcode": result.get("outcode"),
        }
    except Exception as exc:
        return None, {
            "status": "warning",
            "source": "postcodes.io/nearest",
            "reason": f"Reverse lookup unavailable: {exc.__class__.__name__}",
        }


def _build_location_context(
    *,
    latitude: float,
    longitude: float,
    submitted_type: str,
    submitted_value: str,
    intent: dict[str, Any],
    postcode_result: dict[str, Any] | None,
) -> dict[str, Any]:
    postcode_result = postcode_result or {}
    nearest_anchor = _nearest_anchor(latitude, longitude)
    nearest_town = intent.get("nearestTown") or postcode_result.get("admin_ward") or postcode_result.get("parish")
    district = postcode_result.get("admin_district") or intent.get("localAuthority")
    county = postcode_result.get("admin_county")
    region = postcode_result.get("region")
    postcode = postcode_result.get("postcode")
    outcode = postcode_result.get("outcode") or intent.get("outcode")
    summary_parts = []
    if nearest_town:
        summary_parts.append(f"near {nearest_town}")
    if district:
        summary_parts.append(f"in {district}")
    if county and county != district:
        summary_parts.append(f"{county}")
    if region:
        summary_parts.append(f"{region}")
    summary_parts.append(nearest_anchor["phrase"])
    return {
        "submittedLocation": {"type": submitted_type, "value": submitted_value},
        "coordinate": {"latitude": latitude, "longitude": longitude},
        "nearestTown": nearest_town,
        "ward": postcode_result.get("admin_ward"),
        "parish": postcode_result.get("parish"),
        "district": district,
        "county": county,
        "region": region,
        "country": postcode_result.get("country"),
        "postcode": postcode,
        "postcodeArea": outcode,
        "nearestAnchor": nearest_anchor,
        "relativeLocation": nearest_anchor["phrase"],
        "summary": ", ".join(part for part in summary_parts if part),
        "sourceLabels": [submitted_type, *(["postcodes.io"] if postcode_result else [])],
    }


def _nearest_anchor(latitude: float, longitude: float) -> dict[str, Any]:
    ranked = sorted(
        (
            (
                _haversine_km(latitude, longitude, float(anchor["latitude"]), float(anchor["longitude"])),
                anchor,
            )
            for anchor in _UK_ANCHORS
        ),
        key=lambda item: item[0],
    )
    distance_km, anchor = ranked[0]
    bearing = _bearing_degrees(float(anchor["latitude"]), float(anchor["longitude"]), latitude, longitude)
    direction = _bearing_to_cardinal(bearing)
    city = str(anchor["name"])
    rounded_distance = int(round(distance_km))
    return {
        "city": city,
        "distanceKm": rounded_distance,
        "bearingDegrees": round(bearing, 1),
        "direction": direction,
        "phrase": f"about {rounded_distance} km {direction} of {city}",
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _bearing_to_cardinal(bearing: float) -> str:
    directions = [
        "north",
        "north-east",
        "east",
        "south-east",
        "south",
        "south-west",
        "west",
        "north-west",
    ]
    return directions[int((bearing + 22.5) // 45) % 8]


def _format_coordinate(value: float) -> str:
    formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    return formatted if formatted != "-0" else "0"


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
