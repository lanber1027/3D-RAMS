from __future__ import annotations

import re
from typing import Any

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


def resolve_location_candidates(site_name: str, message: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve named-site-only prompts through source-labelled candidate tools.

    This MVP resolver is intentionally fixture-first. It does not invent coordinates
    from the LLM and does not run broad live search from the frontend.
    """

    normalized_site = _normalize(site_name)
    normalized_message = _normalize(message)
    matches = [
        _public_candidate(candidate)
        for candidate in _CACHED_CANDIDATES
        if any(term in normalized_site or term in normalized_message for term in candidate["matchTerms"])
    ][:3]
    status = "ok" if matches else "warning"
    resolution = {
        "siteName": site_name,
        "needsLocationConfirmation": bool(matches),
        "locationCandidates": matches,
        "confirmedLocation": None,
        "nextStage": "confirm_location" if matches else "provide_location_detail",
        "resolverMode": "fixture-first",
        "minimumEvidenceMet": bool(matches),
        "message": (
            "One or more source-labelled candidate locations were found and need user confirmation."
            if matches
            else "No reliable cached/public candidate was found. Ask the user for postcode, coordinates, nearest town/road, or local authority."
        ),
    }
    trace = trace_step(
        "resolve_location_candidates",
        status,
        "Searched allowlisted cached location candidates before starting the review workflow.",
        {
            "siteName": site_name,
            "resolverMode": "fixture-first",
            "candidateCount": len(matches),
            "candidateIds": [candidate["candidateId"] for candidate in matches],
            "nextStage": resolution["nextStage"],
            "sourcesUsed": sorted({candidate["source"] for candidate in matches}) if matches else [],
        },
        source_ids=["location-resolver-fixtures"] if matches else [],
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
