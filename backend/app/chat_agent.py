from __future__ import annotations

import re
import time
import uuid
from typing import Any

from .agent import run_site_briefing
from .config import RuntimeConfig
from .location_resolver import resolve_location_candidates
from .session_store import add_run, get_session
from .site_intent import parse_site_intent
from .tools import trace_step


def run_fieldbrief_chat(
    *,
    session_id: str,
    message: str,
    uploaded_file_ids: list[str],
    use_bedrock: bool,
    config: RuntimeConfig,
) -> dict[str, Any]:
    started = time.perf_counter()
    session = get_session(session_id, config)
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    agent_state = _agent_runtime_state()
    request, parse_trace, clarification, location_resolution, safety_block = _parse_message_to_request(message, uploaded_file_ids, use_bedrock)

    if safety_block:
        response = _safety_boundary_response(
            run_id=run_id,
            session=session,
            safety_block=safety_block,
            parse_trace=parse_trace,
            started=started,
            agent_state=agent_state,
        )
        _record_run(session_id, response, config)
        return response
    if location_resolution:
        response = _location_resolution_response(
            run_id=run_id,
            session=session,
            location_resolution=location_resolution,
            clarification=clarification,
            parse_trace=parse_trace,
            started=started,
            agent_state=agent_state,
        )
        _record_run(session_id, response, config)
        return response
    if clarification:
        response = _clarification_response(
            run_id=run_id,
            session=session,
            message=message,
            clarification=clarification,
            parse_trace=parse_trace,
            started=started,
            agent_state=agent_state,
        )
        _record_run(session_id, response, config)
        return response

    run = run_site_briefing(request)
    upload_trace = _upload_trace(session, uploaded_file_ids)
    full_trace = parse_trace + upload_trace + run["trace"]
    assistant_message = _compose_assistant_message(run, uploaded_file_ids, agent_state)
    run["trace"] = full_trace
    run["runId"] = run_id
    response = {
        "sessionId": session_id,
        "runId": run_id,
        "assistantMessage": assistant_message,
        "needsClarification": False,
        "clarifyingQuestions": [],
        "agent": agent_state,
        "uiState": {
            "location": run["location"],
            "scene": run["scene"],
            "annotations": run["annotations"],
            "hazards": run["hazards"],
            "evidence": run["evidence"],
            "sources": run["sources"],
            "briefing": run["briefing"],
            "safety": run["safety"],
            "trace": full_trace,
            "architecture": run["architecture"],
        },
        "runtime": {
            **run["runtime"],
            "hostedProductMode": True,
            "sessionTraceMode": session.get("storageMode", "memory"),
            "latencyMs": int((time.perf_counter() - started) * 1000),
        },
        "trace": full_trace,
        "evidence": run["evidence"],
        "scene": run["scene"],
        "annotations": run["annotations"],
        "briefing": run["briefing"],
        "safety": run["safety"],
        "fallback": run["fallback"],
        "modelCalls": run["modelCalls"],
        "tokenUsage": run["tokenUsage"],
    }
    _record_run(session_id, response, config)
    return response


def _parse_message_to_request(
    message: str,
    uploaded_file_ids: list[str],
    use_bedrock: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], dict[str, Any] | None, dict[str, Any] | None]:
    intent = parse_site_intent(message)
    coordinate = intent["coordinate"]
    known_lambeth = intent["knownPublicFixture"]
    named_site_hint = intent["namedSiteHint"]
    site_label = intent["siteName"]
    unsafe_intent = intent["unsafeIntent"]
    vague_location_hint = bool(intent.get("vagueLocationHint"))
    site_visit_intent = bool(intent.get("siteVisitIntent"))
    if unsafe_intent:
        trace = [
            trace_step(
                "chat_parse_user_request",
                "blocked",
                "Detected certification, approval, or emergency intent before treating the prompt as a site request.",
                {
                    "siteName": None,
                    "unsafeIntent": True,
                    "triggeredRules": intent["unsafeTerms"],
                    "clarificationRequired": False,
                    "messageSummary": intent["messageSummary"],
                },
                evidence_ids=["safety-policy"],
            )
        ]
        return {}, trace, [], None, {
            "message": "I cannot certify RAMS, approve work, or provide emergency guidance. Provide a real site and visit activity if you want a non-certified pre-visit review pack for human review.",
            "triggeredRules": intent["unsafeTerms"],
        }
    postcode = intent.get("postcode")
    outcode = intent.get("outcode")
    postcode_needs_confirmation = bool((postcode or outcode) and not known_lambeth)
    coordinate_needs_confirmation = bool(coordinate and not known_lambeth)
    location_evidence_needs_confirmation = coordinate_needs_confirmation or postcode_needs_confirmation
    unresolved_named_site = bool(
        (site_label or vague_location_hint) and not coordinate and not known_lambeth and (named_site_hint or vague_location_hint)
    )
    has_site_signal = coordinate is not None or postcode or outcode or known_lambeth or named_site_hint or vague_location_hint
    trace_status = "warning" if location_evidence_needs_confirmation or unresolved_named_site or not has_site_signal else "ok"
    site_label = site_label or _location_hint_label(intent) or postcode or outcode or "User-supplied location"
    trace = [
        trace_step(
            "chat_parse_user_request",
            trace_status,
            (
                "Found a coordinate that requires user confirmation before running tools."
                if coordinate_needs_confirmation
                else "Found a postcode/outcode that requires user confirmation before running tools."
                if postcode_needs_confirmation
                else "Found a named site but no coordinate or approved fixture; asking for location evidence before running tools."
                if unresolved_named_site
                else "Parsed the natural-language site visit request into an agent run envelope."
            ),
            {
                "hasCoordinate": coordinate is not None,
                "postcode": intent.get("postcode"),
                "outcode": intent.get("outcode"),
                "nearestTown": intent.get("nearestTown"),
                "areaHint": intent.get("areaHint"),
                "placeHint": intent.get("placeHint"),
                "siteTypes": intent.get("siteTypes", []),
                "activities": intent.get("activities", []),
                "unsafeIntent": unsafe_intent,
                "knownPublicFixture": known_lambeth,
                "namedSiteHint": named_site_hint,
                "vagueLocationHint": vague_location_hint,
                "siteVisitIntent": site_visit_intent,
                "siteName": site_label,
                "siteResolution": (
                    "coordinate-confirmation"
                    if coordinate_needs_confirmation
                    else "postcode-confirmation"
                    if postcode_needs_confirmation
                    else "unresolved" if unresolved_named_site else ("fixture" if known_lambeth else "missing")
                ),
                "fixturePackSelected": "public-lambeth-thames" if known_lambeth else None,
                "clarificationRequired": location_evidence_needs_confirmation or unresolved_named_site or not has_site_signal,
                "uploadedFileIds": uploaded_file_ids,
                "messageSummary": _summarise_message(message),
            },
        )
    ]
    if not has_site_signal:
        return {}, trace, [
            "Which site should I assess? Please provide a site name, address, or coordinate.",
            "What is the planned visit activity, for example survey, inspection, delivery, or maintenance?",
        ], None, None
    if location_evidence_needs_confirmation or unresolved_named_site:
        location_resolution, resolver_trace = resolve_location_candidates(site_label, message, intent=intent)
        trace.append(resolver_trace)
        if coordinate_needs_confirmation and location_resolution["locationCandidates"]:
            clarification = [
                f"I found a user-supplied coordinate for '{site_label}', but I need you to confirm it is the intended site before generating a review pack.",
                "Confirm the candidate card, or provide a corrected postcode, latitude/longitude, OS grid reference, nearest road/town, or public evidence.",
            ]
        elif postcode_needs_confirmation and location_resolution["locationCandidates"]:
            clarification = [
                f"I found a postcode/outcode candidate for '{site_label}', but I need you to confirm it is the intended site before generating a review pack.",
                "Confirm the candidate card, or provide a corrected postcode, latitude/longitude, OS grid reference, nearest road/town, or public evidence.",
            ]
        else:
            clarification = [
                f"I found the site name '{site_label}', but I need a confirmed location before generating a review pack.",
                _targeted_location_question(intent),
            ]
        if not location_resolution["locationCandidates"]:
            clarification.append("No reliable cached/public candidate was found for this site name. I can only show provisional, non-site-specific risk prompts until location evidence is provided.")
        return {}, trace, clarification, location_resolution, None

    request: dict[str, Any] = {
        "siteName": site_label,
        "goal": "Hosted pre-visit RAMS-style review pack",
        "fixturePack": "public-lambeth-thames" if known_lambeth else None,
        "includePlanningFixture": True,
        "simulateMapFailure": False,
        "useBedrock": use_bedrock,
        "agentMode": "llm-planner" if use_bedrock else "deterministic",
        "additionalRequest": message,
        "siteIntent": intent,
    }
    if coordinate:
        request["latitude"] = coordinate[0]
        request["longitude"] = coordinate[1]
        request["fixturePack"] = None
    return request, trace, [], None, None


def _location_resolution_response(
    *,
    run_id: str,
    session: dict[str, Any],
    location_resolution: dict[str, Any],
    clarification: list[str],
    parse_trace: list[dict[str, Any]],
    started: float,
    agent_state: dict[str, Any],
) -> dict[str, Any]:
    candidates = location_resolution.get("locationCandidates", [])
    provisional_risks = location_resolution.get("provisionalRisks", [])
    site_name = location_resolution.get("siteName")
    if candidates:
        assistant_message = (
            f"I found {len(candidates)} possible location for {site_name}. "
            "Please confirm the site before I run map, evidence, risk, or briefing tools."
        )
    else:
        assistant_message = (
            f"I could not find a reliable cached/public location candidate for {site_name}. "
            "Please provide a postcode, OS grid reference, latitude/longitude, nearest road/town, or local authority."
        )
    safety = {
        "allowed": True,
        "level": "needs_input",
        "message": "No site-specific briefing generated until the site location is confirmed.",
    }
    ui_state = {
        "location": None,
        "scene": None,
        "annotations": [],
        "hazards": provisional_risks,
        "evidence": [],
        "sources": [],
        "briefing": None,
        "safety": safety,
        "trace": parse_trace,
        "architecture": None,
        "locationResolution": location_resolution,
        "reviewMode": "provisional checklist pending location" if provisional_risks else "location pending",
    }
    return {
        "sessionId": session["sessionId"],
        "runId": run_id,
        "assistantMessage": assistant_message,
        "needsClarification": True,
        "needsLocationConfirmation": bool(candidates),
        "locationCandidates": candidates,
        "confirmedLocation": None,
        "nextStage": location_resolution.get("nextStage"),
        "clarifyingQuestions": clarification,
        "agent": agent_state,
        "uiState": ui_state,
        "runtime": {
            "hostedProductMode": True,
            "briefingMode": "not-run",
            "activeAgentMode": "location-resolution",
            "sessionTraceMode": session.get("storageMode", "memory"),
            "latencyMs": int((time.perf_counter() - started) * 1000),
        },
        "trace": parse_trace,
        "evidence": [],
        "scene": None,
        "annotations": [],
        "briefing": None,
        "safety": safety,
        "fallback": {"status": "available", "reason": "Agent can continue after location confirmation or extra location detail."},
        "modelCalls": [],
        "tokenUsage": None,
    }


def _safety_boundary_response(
    *,
    run_id: str,
    session: dict[str, Any],
    safety_block: dict[str, Any],
    parse_trace: list[dict[str, Any]],
    started: float,
    agent_state: dict[str, Any],
) -> dict[str, Any]:
    safety = {
        "allowed": False,
        "level": "blocked",
        "message": safety_block["message"],
        "triggeredRules": safety_block.get("triggeredRules", []),
        "requiresHumanReview": True,
    }
    ui_state = {
        "location": None,
        "scene": None,
        "annotations": [],
        "hazards": [],
        "evidence": [],
        "sources": [],
        "briefing": {
            "headline": "Request blocked by safety boundary.",
            "summary": [safety_block["message"]],
            "priority_checks": [],
            "before_site_visit": [],
            "limitations": ["3D-RAMS cannot certify RAMS, approve work, or provide emergency guidance."],
        },
        "safety": safety,
        "trace": parse_trace,
        "architecture": None,
        "locationResolution": None,
        "reviewMode": "safety blocked",
    }
    return {
        "sessionId": session["sessionId"],
        "runId": run_id,
        "assistantMessage": safety_block["message"],
        "needsClarification": False,
        "clarifyingQuestions": [],
        "agent": agent_state,
        "uiState": ui_state,
        "runtime": {
            "hostedProductMode": True,
            "briefingMode": "not-run",
            "activeAgentMode": "safety-gate",
            "sessionTraceMode": session.get("storageMode", "memory"),
            "latencyMs": int((time.perf_counter() - started) * 1000),
        },
        "trace": parse_trace,
        "evidence": [],
        "scene": None,
        "annotations": [],
        "briefing": ui_state["briefing"],
        "safety": safety,
        "fallback": {"status": "blocked", "reason": safety_block["message"]},
        "modelCalls": [],
        "tokenUsage": None,
    }


def _clarification_response(
    *,
    run_id: str,
    session: dict[str, Any],
    message: str,
    clarification: list[str],
    parse_trace: list[dict[str, Any]],
    started: float,
    agent_state: dict[str, Any],
) -> dict[str, Any]:
    site_name = None
    if parse_trace:
        site_name = parse_trace[0].get("output", {}).get("siteName")
    site_context = f" for {site_name}" if site_name else ""
    return {
        "sessionId": session["sessionId"],
        "runId": run_id,
        "assistantMessage": (
            f"I can prepare a pre-visit RAMS-style review pack{site_context}, but I need a trusted location first. "
            "Please answer the questions below so I can run the location, evidence, map, and safety tools."
        ),
        "needsClarification": True,
        "clarifyingQuestions": clarification,
        "agent": agent_state,
        "uiState": {
            "location": None,
            "scene": None,
            "annotations": [],
            "hazards": [],
            "evidence": [],
            "sources": [],
            "briefing": None,
            "safety": {
                "allowed": True,
                "level": "needs_input",
                "message": "No briefing generated until a site is supplied.",
            },
            "trace": parse_trace,
            "architecture": None,
            "locationResolution": None,
        },
        "runtime": {
            "hostedProductMode": True,
            "briefingMode": "not-run",
            "activeAgentMode": "clarification",
            "sessionTraceMode": session.get("storageMode", "memory"),
            "latencyMs": int((time.perf_counter() - started) * 1000),
        },
        "trace": parse_trace,
        "evidence": [],
        "scene": None,
        "annotations": [],
        "briefing": None,
        "safety": {
            "allowed": True,
            "level": "needs_input",
            "message": "No briefing generated until a site is supplied.",
        },
        "fallback": {"status": "available", "reason": "Agent can rerun after clarification."},
        "modelCalls": [],
        "tokenUsage": None,
    }


def _compose_assistant_message(run: dict[str, Any], uploaded_file_ids: list[str], agent_state: dict[str, Any]) -> str:
    briefing = run["briefing"]
    safety = run["safety"]
    location = run["location"]
    upload_note = (
        f" I also registered {len(uploaded_file_ids)} uploaded evidence item(s) for review."
        if uploaded_file_ids
        else ""
    )
    if not safety["allowed"]:
        return (
            "I cannot certify RAMS, approve work, or provide emergency instructions. "
            f"I did keep the safety boundary visible for {location['label']}."
        )
    checks = "; ".join(briefing.get("priority_checks", [])[:3])
    return (
        f"I prepared a RAMS-style pre-visit review pack for {location['label']}. "
        f"Top checks: {checks}. {upload_note} "
        f"The output is for human review only and was produced through the {agent_state['orchestrator']}."
    ).strip()


def _upload_trace(session: dict[str, Any], uploaded_file_ids: list[str]) -> list[dict[str, Any]]:
    uploads = {
        upload.get("uploadId"): upload
        for upload in session.get("uploads", [])
    }
    steps = []
    for upload_id in uploaded_file_ids:
        upload = uploads.get(upload_id)
        steps.append(
            trace_step(
                "register_uploaded_evidence",
                "ok" if upload else "warning",
                "Registered uploaded PDF/image evidence metadata for the hosted agent run.",
                {
                    "uploadId": upload_id,
                    "displayName": upload.get("displayName") if upload else None,
                    "contentType": upload.get("contentType") if upload else None,
                    "status": upload.get("status") if upload else "missing",
                },
                source_ids=["uploaded-evidence"],
            )
        )
    return steps


def _record_run(session_id: str, response: dict[str, Any], config: RuntimeConfig) -> None:
    summary = {
        "runId": response["runId"],
        "needsClarification": response["needsClarification"],
        "safetyLevel": response["safety"]["level"],
        "briefingMode": response["runtime"].get("briefingMode"),
        "activeAgentMode": response["runtime"].get("activeAgentMode"),
        "latencyMs": response["runtime"].get("latencyMs"),
        "modelCallCount": len(response.get("modelCalls", [])),
        "fallbackStatus": response.get("fallback", {}).get("status"),
    }
    add_run(session_id, summary, config)


def _agent_runtime_state() -> dict[str, Any]:
    try:
        import strands  # noqa: F401

        status = "available"
    except Exception:
        status = "adapter-fallback"
    return {
        "orchestrator": "FieldBrief Agent Orchestrator",
        "framework": "Strands-ready adapter",
        "strandsStatus": status,
        "toolPolicy": "allowlisted hosted tools only",
        "hiddenReasoning": "not exposed",
    }


def _extract_coordinate(message: str) -> tuple[float, float] | None:
    match = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", message)
    if not match:
        return None
    latitude = float(match.group(1))
    longitude = float(match.group(2))
    if -90 <= latitude <= 90 and -180 <= longitude <= 180:
        return latitude, longitude
    return None


def _extract_site_label(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    extraction_patterns = [
        r"\bsite visit at\s+(.+?)(?:\s+tomorrow\b|\s+today\b|\s+for\b|\s+please\b|[.,]|$)",
        r"\bvisit\s+(.+?)(?:\s+tomorrow\b|\s+today\b|\s+for\b|\s+please\b|[.,]|$)",
        r"\bat\s+(.+?)(?:\s+tomorrow\b|\s+today\b|\s+for\b|\s+please\b|[.,]|$)",
    ]
    for pattern in extraction_patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            label = match.group(1).strip(" ,.;:")
            if label:
                return label[:90] if len(label) <= 90 else label[:87].rstrip() + "..."
    if len(cleaned) <= 90:
        return cleaned
    return cleaned[:87].rstrip() + "..."


def _summarise_message(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    return cleaned[:160]


def _targeted_location_question(intent: dict[str, Any]) -> str:
    clues = []
    if intent.get("placeHint") and intent.get("areaHint"):
        clues.append(f"{intent['placeHint']} in {intent['areaHint']}")
    elif intent.get("placeHint"):
        clues.append(str(intent["placeHint"]))
    elif intent.get("areaHint"):
        clues.append(f"in {intent['areaHint']}")
    if intent.get("nearestTown"):
        clues.append(f"near {intent['nearestTown']}")
    if intent.get("outcode"):
        clues.append(f"postcode area {intent['outcode']}")
    if intent.get("localAuthority"):
        clues.append(f"local authority {intent['localAuthority']}")
    clue_text = f" I captured the clue(s): {', '.join(clues)}." if clues else ""
    return (
        "Please confirm one of the candidate cards, or provide a full postcode, OS grid reference, "
        f"latitude/longitude, nearest road/town, or local authority.{clue_text}"
    )


def _location_hint_label(intent: dict[str, Any]) -> str | None:
    place = intent.get("placeHint")
    area = intent.get("areaHint") or intent.get("nearestTown")
    if place and area:
        return f"{place} near {area}"
    if place:
        return f"{place} location"
    if area:
        return f"location near {area}"
    return None
