from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from .bedrock_adapter import BedrockAdapterError, generate_bedrock_conversation_orchestration
from .config import RuntimeConfig
from .durable_runner import create_durable_run, read_durable_run
from .session_store import add_conversation_turn, get_session, llm_session_context, update_working_memory
from .site_intent import parse_site_intent
from .tools import trace_step


_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "waiting_for_clarification",
    "waiting_for_location_confirmation",
    "waiting_for_approval",
}

_FOLLOW_UP_PHRASES = {
    "what do you mean",
    "what does that mean",
    "explain",
    "explain that",
    "why",
    "why is that",
    "what next",
    "what should i do",
}

_QUESTION_PREFIXES = {
    "what",
    "why",
    "how",
    "where",
    "when",
    "who",
    "which",
    "can",
    "could",
    "should",
    "would",
    "is",
    "are",
    "do",
    "does",
}

_STATUS_PHRASES = {
    "status",
    "where are we",
    "what is happening",
    "is it done",
    "are you done",
}

_CONFIRMATION_PHRASES = {"yes", "ok", "okay", "confirm", "confirmed", "looks right", "this is correct"}
_REJECTION_PHRASES = {
    "no",
    "not this site",
    "wrong site",
    "this is wrong",
    "not the right site",
    "that is not right",
    "that is wrong",
    "different site",
}
_START_OVER_PHRASES = {
    "start again",
    "start over",
    "new site",
    "reset",
    "clear this",
}
_GREETING_PHRASES = {
    "hello",
    "hi",
    "hey",
    "hiya",
    "good morning",
    "good afternoon",
    "good evening",
}
_HELP_PHRASES = {
    "help",
    "how does this work",
    "what can you do",
    "what do you need",
}
_TOOL_PROMISE_RE = re.compile(
    r"\b(?:let me|i(?:'|’)?m|i am|i(?:'|’)?ll|i will|i can(?: now)?|i(?:'|’)?d like to)\b"
    r".{0,48}\b"
    r"(?:gather|fetch|look\s*up|check|search|run|start|collect|find|review|assess|prepare|investigate|analy[sz]e|compile|generate)"
    r"(?:ing)?\b",
    re.IGNORECASE,
)


def handle_conversation_message(
    *,
    session_id: str,
    message: str,
    uploaded_file_ids: list[str],
    use_bedrock: bool,
    config: RuntimeConfig,
) -> dict[str, Any]:
    session = get_session(session_id, config)
    cleaned = " ".join(message.split())
    memory = session.setdefault("workingMemory", {})
    add_conversation_turn(
        session_id,
        role="user",
        text=cleaned,
        metadata={"routeInput": True},
        config=config,
    )

    intent = parse_site_intent(cleaned)
    deterministic_route = _classify_message(cleaned, memory, intent)
    orchestration = _maybe_orchestrate_conversation(
        session=session,
        message=cleaned,
        intent=intent,
        deterministic_route=deterministic_route,
        config=config,
    )
    route = _validated_route(orchestration, deterministic_route, memory, intent)
    if route in {"conversation", "greeting", "help"}:
        return _orchestrated_conversation_response(session_id, route, orchestration, memory, intent, config)
    if route == "status":
        return _status_response(session_id, memory, intent, config)
    if route == "follow_up":
        return _memory_response(session_id, cleaned, memory, intent, config, orchestration=orchestration)
    if route == "confirm_by_chat":
        return _confirm_by_chat_response(session_id, memory, config)
    if route == "reject_location":
        return _reject_location_response(session_id, cleaned, memory, config)
    if route == "start_over_without_site":
        return _start_over_response(session_id, cleaned, memory, config)

    previous_active_run_id = memory.get("activeRunId")
    conversation_state = _conversation_state(orchestration, intent, route, tools_started=True)
    result = create_durable_run(
        session_id=session_id,
        message=cleaned,
        uploaded_file_ids=uploaded_file_ids,
        use_bedrock=use_bedrock,
        auto_start=True,
        config=config,
    )
    assistant_text = _assistant_text_from_run(result)
    add_conversation_turn(
        session_id,
        role="assistant",
        text=assistant_text,
        metadata={
            "route": "start_run",
            "conversationOrchestrator": _orchestration_metadata(orchestration),
            "conversationState": conversation_state,
            "runId": result.get("runId"),
            "runStatus": result.get("status"),
            "siteIntent": {
                "hasLocationEvidence": intent.get("hasLocationEvidence"),
                "namedSiteHint": intent.get("namedSiteHint"),
                "vagueLocationHint": intent.get("vagueLocationHint"),
                "unsafeIntent": intent.get("unsafeIntent"),
            },
        },
        config=config,
    )
    result_payload = result.get("result") or {}
    update_fields: dict[str, Any] = {
        "activeRunId": result.get("runId"),
        "latestRunStatus": result.get("status"),
        "pendingUserAction": _pending_action(result),
        "latestLocationResolution": (result.get("locationResolution") or result_payload.get("locationResolution")),
        "latestReviewSummary": _latest_review_summary(result),
        "latestRoute": route,
    }
    if route in {"location_correction", "start_over_with_site"}:
        update_fields["previousRunId"] = previous_active_run_id
        update_fields["correctionReason"] = route
    update_working_memory(
        session_id,
        config,
        **update_fields,
    )
    return {
        "action": "started_run",
        "route": route if route != "new_run" else "new_or_guarded_run",
        "assistantMessage": assistant_text,
        "conversationState": conversation_state,
        "run": result,
        "runtime": _runtime_contract(config, "lambda-adapter-active"),
    }


def _classify_message(message: str, memory: dict[str, Any], intent: dict[str, Any]) -> str:
    lower = message.lower().strip(" ?.!")
    pending = memory.get("pendingUserAction")
    has_location_evidence = bool(intent.get("hasLocationEvidence"))
    has_site_signal = _has_site_signal(intent)
    if lower in _GREETING_PHRASES:
        return "greeting"
    if lower in _HELP_PHRASES:
        return "help"
    if lower in _STATUS_PHRASES or any(lower.startswith(f"{phrase} ") for phrase in _STATUS_PHRASES):
        return "status"
    if _starts_with_any(lower, _START_OVER_PHRASES):
        return "start_over_with_site" if has_site_signal else "start_over_without_site"
    if pending in {"confirm_or_correct_location", "provide_corrected_location"}:
        if has_location_evidence:
            return "location_correction"
        if pending == "confirm_or_correct_location" and lower in _CONFIRMATION_PHRASES:
            return "confirm_by_chat"
        if lower in _REJECTION_PHRASES or any(phrase in lower for phrase in _REJECTION_PHRASES):
            return "reject_location"
        if _looks_like_question(lower) and not has_location_evidence:
            return "follow_up"
        if _starts_with_any(lower, _FOLLOW_UP_PHRASES):
            return "follow_up"
        if not has_site_signal and not intent.get("unsafeIntent"):
            return "follow_up"
    elif pending and lower in _CONFIRMATION_PHRASES:
        return "follow_up"
    if _starts_with_any(lower, _FOLLOW_UP_PHRASES):
        return "follow_up"
    if _looks_like_question(lower) and memory.get("activeRunId") and not has_site_signal and not intent.get("unsafeIntent"):
        return "follow_up"
    return "new_run"


def _starts_with_any(lower: str, phrases: set[str]) -> bool:
    return lower in phrases or any(lower.startswith(f"{phrase} ") for phrase in phrases)


def _looks_like_question(lower: str) -> bool:
    if lower.endswith("?"):
        return True
    first = lower.split(" ", 1)[0] if lower else ""
    return first in _QUESTION_PREFIXES


def _maybe_orchestrate_conversation(
    *,
    session: dict[str, Any],
    message: str,
    intent: dict[str, Any],
    deterministic_route: str,
    config: RuntimeConfig,
) -> dict[str, Any] | None:
    if not config.bedrock_enabled:
        return None
    try:
        orchestration, metadata = generate_bedrock_conversation_orchestration(
            config=config,
            message=message,
            intent=intent,
            session_context=llm_session_context(session),
        )
        orchestration["metadata"] = metadata
        orchestration["fallbackRoute"] = deterministic_route
        return orchestration
    except (BedrockAdapterError, Exception) as exc:
        return {
            "route": deterministic_route,
            "assistantMessage": None,
            "shouldStartRun": deterministic_route in {"new_run", "location_correction", "start_over_with_site"},
            "pendingUserAction": None,
            "reason": f"Conversation orchestrator unavailable; deterministic route used. {exc}",
            "metadata": {"provider": "deterministic-fallback", "errorType": exc.__class__.__name__},
            "fallbackRoute": deterministic_route,
            "failed": True,
        }


def _validated_route(
    orchestration: dict[str, Any] | None,
    deterministic_route: str,
    memory: dict[str, Any],
    intent: dict[str, Any],
) -> str:
    if not orchestration:
        return deterministic_route

    route = str(orchestration.get("route") or deterministic_route).strip().lower().replace("-", "_")
    pending = memory.get("pendingUserAction")
    has_location_evidence = bool(intent.get("hasLocationEvidence"))
    has_site_signal = _has_site_signal(intent)
    conversation_state = _conversation_state(orchestration, intent, route, tools_started=False)
    state_intent = conversation_state.get("intent")

    if deterministic_route in {
        "status",
        "confirm_by_chat",
        "reject_location",
        "location_correction",
        "start_over_without_site",
        "start_over_with_site",
    }:
        return deterministic_route
    if pending in {"confirm_or_correct_location", "provide_corrected_location"}:
        if route in {"greeting", "help", "conversation", "follow_up"} and not has_location_evidence:
            return "follow_up"
        if not has_site_signal and not intent.get("unsafeIntent"):
            return "follow_up"
    if intent.get("unsafeIntent"):
        if orchestration.get("shouldStartRun") is False:
            return "conversation"
        return "new_run"
    if (
        orchestration.get("shouldStartRun") is False
        and route in {"conversation", "greeting", "help", "follow_up", "status"}
        and not intent.get("namedSiteHint")
        and not has_location_evidence
    ):
        return route
    if (
        state_intent == "location_discovery"
        and intent.get("vagueLocationHint")
        and orchestration.get("shouldStartRun") is not False
    ):
        return "new_run"
    if has_site_signal and deterministic_route in {"new_run", "location_correction", "start_over_with_site"}:
        return deterministic_route
    if route in {"new_run", "location_correction", "start_over_with_site"}:
        if has_site_signal or intent.get("unsafeIntent"):
            return "new_run" if route != "location_correction" else "location_correction"
        return "conversation"
    if not has_site_signal and not intent.get("unsafeIntent"):
        return route if route in {"conversation", "greeting", "help", "follow_up", "status"} else "conversation"
    if route in {"conversation", "greeting", "help", "follow_up", "status"}:
        return route
    return deterministic_route


def _has_site_signal(intent: dict[str, Any]) -> bool:
    return bool(
        intent.get("namedSiteHint")
        or intent.get("hasLocationEvidence")
        or intent.get("vagueLocationHint")
    )


def _orchestrated_conversation_response(
    session_id: str,
    route: str,
    orchestration: dict[str, Any] | None,
    memory: dict[str, Any],
    intent: dict[str, Any],
    config: RuntimeConfig,
) -> dict[str, Any]:
    text = (
        (orchestration or {}).get("assistantMessage")
        or _deterministic_conversation_copy(route, memory)
    )
    pending_action = (orchestration or {}).get("pendingUserAction")
    memory_for_sanitize = dict(memory)
    if _is_known_pending_action(pending_action):
        memory_for_sanitize["pendingUserAction"] = pending_action
    text = _sanitize_assistant_copy(text, route=route, memory=memory_for_sanitize, intent=intent, tools_started=False)
    observability = _conversation_observability(route, orchestration, intent, memory, tools_started=False)
    conversation_state = _conversation_state(orchestration, intent, route, tools_started=False)
    add_conversation_turn(
        session_id,
        role="assistant",
        text=text,
        metadata={
            "route": route,
            "conversationOrchestrator": _orchestration_metadata(orchestration),
            "observability": observability,
            "conversationState": conversation_state,
        },
        config=config,
    )
    update_fields: dict[str, Any] = {"latestRoute": route}
    if _is_known_pending_action(pending_action):
        update_fields["pendingUserAction"] = pending_action
    update_working_memory(session_id, config, **update_fields)
    return {
        "action": "answered_from_memory",
        "route": route,
        "assistantMessage": text,
        "conversationState": conversation_state,
        "observability": observability,
        "trace": _conversation_trace(route, orchestration, intent, memory, observability),
        "modelCalls": _conversation_model_calls(orchestration),
        "runtime": _runtime_contract(
            config,
            "bedrock-conversation-orchestrator" if orchestration and not orchestration.get("failed") else "lambda-adapter-active",
        ),
    }


def _deterministic_conversation_copy(route: str, memory: dict[str, Any]) -> str:
    if route == "greeting":
        return (
            "Hi. Give me a UK postcode or latitude/longitude, plus the planned visit activity, "
            "and I will prepare a RAMS-style pre-visit review pack for human review."
        )
    if route == "help":
        return (
            "Send a UK postcode or latitude/longitude, the site type if known, and the planned activity "
            "such as survey, inspection, delivery, or maintenance."
        )
    if memory.get("pendingUserAction"):
        return _pending_action_copy(memory["pendingUserAction"])
    return "Tell me the site postcode or latitude/longitude, plus the planned visit activity, and I can prepare a pre-visit review pack for human review."


def _orchestration_metadata(orchestration: dict[str, Any] | None) -> dict[str, Any] | None:
    if not orchestration:
        return None
    metadata = orchestration.get("metadata") or {}
    return {
        "route": orchestration.get("route"),
        "shouldStartRun": orchestration.get("shouldStartRun"),
        "reason": orchestration.get("reason"),
        "provider": metadata.get("provider"),
        "phase": metadata.get("phase"),
        "modelCallCount": metadata.get("modelCallCount"),
        "fallbackRoute": orchestration.get("fallbackRoute"),
        "failed": orchestration.get("failed", False),
    }


def _looks_like_correction(lower: str) -> bool:
    return any(
        marker in lower
        for marker in [
            "corrected",
            "correction",
            "actually",
            "i meant",
            "use ",
            "try ",
            "instead",
            "the postcode is",
            "the coordinate is",
            "coordinates are",
            "lat",
            "latitude",
            "longitude",
        ]
    )


def _status_response(session_id: str, memory: dict[str, Any], intent: dict[str, Any], config: RuntimeConfig) -> dict[str, Any]:
    run = _safe_read_run(memory.get("activeRunId"))
    if run:
        status = run.get("status")
        current_step = run.get("currentStep")
        text = f"The current run is {status} at `{current_step}`."
        if status == "waiting_for_location_confirmation":
            text += " I am waiting for you to confirm or correct the candidate location before review tools run."
        elif status == "waiting_for_clarification":
            text += " I need the missing site or visit detail before I can run tools."
        elif status == "completed":
            text += " The latest review pack is ready in the panels."
        add_conversation_turn(
            session_id,
            role="assistant",
            text=text,
            metadata={"route": "status", "runId": run.get("runId"), "runStatus": status},
            config=config,
        )
        update_working_memory(session_id, config, latestRunStatus=status)
        tools_started = status in {"queued", "running", "completed"}
        observability = _conversation_observability("status", None, intent, memory, tools_started=tools_started)
        conversation_state = _conversation_state(None, intent, "status", tools_started=tools_started)
        if tools_started:
            observability["phase"] = f"run_{status}"
            observability["noToolReason"] = None
        return {
            "action": "answered_from_memory",
            "route": "status",
            "assistantMessage": text,
            "run": run,
            "conversationState": conversation_state,
            "observability": observability,
            "trace": _conversation_trace("status", None, intent, memory, observability),
            "modelCalls": [],
            "runtime": _runtime_contract(config, "lambda-adapter-active"),
        }
    text = "I do not have an active run in this session yet. Send a site visit request with a postcode or latitude/longitude to begin."
    add_conversation_turn(session_id, role="assistant", text=text, metadata={"route": "status"}, config=config)
    observability = _conversation_observability("status", None, intent, memory, tools_started=False)
    conversation_state = _conversation_state(None, intent, "status", tools_started=False)
    return {
        "action": "answered_from_memory",
        "route": "status",
        "assistantMessage": text,
        "conversationState": conversation_state,
        "observability": observability,
        "trace": _conversation_trace("status", None, intent, memory, observability),
        "modelCalls": [],
        "runtime": _runtime_contract(config, "lambda-adapter-active"),
    }


def _memory_response(
    session_id: str,
    message: str,
    memory: dict[str, Any],
    intent: dict[str, Any],
    config: RuntimeConfig,
    *,
    orchestration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest = memory.get("latestAssistantMessage")
    pending = memory.get("pendingUserAction")
    if orchestration and orchestration.get("assistantMessage"):
        text = _sanitize_assistant_copy(
            orchestration["assistantMessage"],
            route="follow_up",
            memory=memory,
            intent=intent,
            tools_started=False,
        )
    elif latest:
        latest_safe = _sanitize_assistant_copy(
            latest,
            route="follow_up",
            memory=memory,
            intent=intent,
            tools_started=False,
        )
        text = (
            "I was referring to the previous step in this same session: "
            f"{latest_safe} "
            "If that is unclear, provide a corrected postcode/coordinate or ask me about a specific panel such as location, evidence, risk, trace, or safety."
        )
    elif pending:
        text = _pending_action_copy(pending)
    else:
        text = "I do not have enough prior context in memory yet. Please send the site location and planned visit activity."
    observability = _conversation_observability("follow_up", orchestration, intent, memory, tools_started=False)
    conversation_state = _conversation_state(orchestration, intent, "follow_up", tools_started=False)
    add_conversation_turn(
        session_id,
        role="assistant",
        text=text,
        metadata={
            "route": "follow_up",
            "followUpPrompt": message[:120],
            "conversationOrchestrator": _orchestration_metadata(orchestration),
            "conversationState": conversation_state,
            "observability": observability,
        },
        config=config,
    )
    return {
        "action": "answered_from_memory",
        "route": "follow_up",
        "assistantMessage": text,
        "conversationState": conversation_state,
        "observability": observability,
        "trace": _conversation_trace("follow_up", orchestration, intent, memory, observability),
        "modelCalls": _conversation_model_calls(orchestration),
        "runtime": _runtime_contract(config, "lambda-adapter-active"),
    }


def _pending_action_copy(action: Any) -> str:
    mapping = {
        "provide_site_location_and_activity": "Please provide a trusted site location, such as a UK postcode or latitude/longitude, plus the planned visit activity.",
        "provide_safe_site_visit_request": "I can help with a non-certified pre-visit review pack. Please provide a real site and visit activity without asking me to certify RAMS, approve work, or provide emergency guidance.",
        "confirm_or_correct_location": "Please confirm the candidate location card, or send a corrected postcode or latitude/longitude before review tools run.",
        "provide_corrected_location": "Please provide a corrected UK postcode, latitude/longitude, OS grid reference, nearest road/town, or public evidence for the intended site.",
        "provide_location_detail": "Please provide a trusted postcode, latitude/longitude, OS grid reference, nearest road/town, or public evidence before I prepare a site-specific pack.",
        "provide_new_site_request": "Send a new site request with a postcode or latitude/longitude and the planned visit activity.",
        "answer_clarifying_question": "Please answer the clarification question before I run map, evidence, risk, or briefing tools.",
        "wait_for_agent_run": "The backend is still running the current review workflow. You can ask for status if you want an update.",
    }
    return mapping.get(
        str(action),
        "I can help with site-visit preparation. Please provide a UK postcode or latitude/longitude and the planned visit activity.",
    )


def _sanitize_assistant_copy(
    text: str,
    *,
    route: str | None = None,
    memory: dict[str, Any] | None = None,
    intent: dict[str, Any] | None = None,
    tools_started: bool = False,
) -> str:
    scrubbed = str(text)
    for action in _known_pending_actions():
        if action in scrubbed:
            scrubbed = scrubbed.replace(action, _pending_action_copy(action))
    if re.search(r"\b(?:provide|confirm|answer|wait|start|reject)_[a-z0-9_]+\b", scrubbed):
        return "I can help with site-visit preparation. Please provide a UK postcode or latitude/longitude and the planned visit activity."
    if (intent or {}).get("unsafeIntent"):
        if not tools_started and _TOOL_PROMISE_RE.search(scrubbed):
            return (
                "I cannot certify RAMS, approve work, or provide emergency guidance. "
                "I have not started map, evidence, risk, or briefing tools for this unsafe request. "
                "I can only help with a non-certified pre-visit review pack for human review if you provide a safe site-visit request."
            )
        return scrubbed
    if not tools_started and _TOOL_PROMISE_RE.search(scrubbed):
        return _no_tool_started_copy(route or "conversation", memory or {}, intent or {})
    return scrubbed


def _no_tool_started_copy(route: str, memory: dict[str, Any], intent: dict[str, Any]) -> str:
    if memory.get("pendingUserAction"):
        return (
            "I have not started map, evidence, risk, or briefing tools yet. "
            f"{_pending_action_copy(memory['pendingUserAction'])}"
        )
    site_hint = intent.get("siteName") or intent.get("namedSiteHint")
    activity_hint = ", plus the planned visit activity" if not intent.get("activities") else ""
    if site_hint and not intent.get("hasLocationEvidence"):
        return (
            f"I can help with that site visit, but I have not started map, evidence, risk, or briefing tools yet. "
            f"Please provide a trusted UK postcode or latitude/longitude for {site_hint}{activity_hint}, "
            "or a specific public source for the intended location."
        )
    if route == "greeting":
        return "Hello. Tell me the site postcode or latitude/longitude and the planned visit activity, and I can prepare a pre-visit review pack."
    return "I can help with site-visit preparation. Please provide a trusted UK postcode or latitude/longitude and the planned visit activity before I run tools."


def _conversation_state(
    orchestration: dict[str, Any] | None,
    intent: dict[str, Any],
    route: str,
    *,
    tools_started: bool,
) -> dict[str, Any]:
    raw = (orchestration or {}).get("conversationState")
    state = raw if isinstance(raw, dict) else {}
    state_intent = str(state.get("intent") or _state_intent_from_route(route, intent, tools_started)).strip().lower().replace("-", "_")
    location_status = str(state.get("locationStatus") or _location_status_from_intent(intent, state_intent, tools_started)).strip().lower().replace("-", "_")
    known = state.get("knownDetails") if isinstance(state.get("knownDetails"), dict) else {}
    missing = state.get("missingDetails") if isinstance(state.get("missingDetails"), list) else []
    allowed_next_action = str(
        state.get("allowedNextAction") or _allowed_next_action_from_state(state_intent, location_status, tools_started)
    ).strip().lower().replace("-", "_")
    return {
        "intent": state_intent,
        "locationStatus": location_status,
        "knownDetails": {
            "placeHint": known.get("placeHint") or intent.get("placeHint"),
            "areaHint": known.get("areaHint") or intent.get("areaHint") or intent.get("nearestTown"),
            "activity": known.get("activity") or (", ".join(intent.get("activities", [])) if intent.get("activities") else None),
            "postcode": known.get("postcode") or intent.get("postcode") or intent.get("outcode"),
            "coordinate": known.get("coordinate") or _coordinate_text(intent.get("coordinate")),
            "siteName": known.get("siteName") or intent.get("siteName"),
        },
        "missingDetails": missing[:5] if missing else _missing_details_from_intent(intent, location_status),
        "allowedNextAction": allowed_next_action,
        "shouldStartRun": bool(state.get("shouldStartRun")) if "shouldStartRun" in state else tools_started,
    }


def _state_intent_from_route(route: str, intent: dict[str, Any], tools_started: bool) -> str:
    if intent.get("unsafeIntent"):
        return "unsafe"
    if intent.get("vagueLocationHint") and not intent.get("hasLocationEvidence"):
        return "location_discovery"
    if route == "status":
        return "status"
    if route in {"reject_location", "location_correction", "start_over_with_site"}:
        return "location_correction"
    if route == "confirm_by_chat":
        return "location_confirmation"
    if tools_started:
        return "ready_for_review"
    return "conversation"


def _location_status_from_intent(intent: dict[str, Any], state_intent: str, tools_started: bool) -> str:
    if intent.get("unsafeIntent"):
        return "unsafe"
    if intent.get("hasLocationEvidence") and tools_started:
        return "candidate_pending"
    if state_intent == "location_discovery":
        return "needs_evidence"
    if state_intent in {"location_correction", "location_confirmation"}:
        return "candidate_pending"
    if tools_started:
        return "candidate_pending"
    return "not_applicable"


def _allowed_next_action_from_state(state_intent: str, location_status: str, tools_started: bool) -> str:
    if state_intent == "unsafe":
        return "safety_refusal"
    if tools_started:
        return "start_guarded_run"
    if location_status in {"vague", "needs_evidence"} or state_intent == "location_discovery":
        return "ask_location_clarification"
    if state_intent == "location_correction":
        return "reject_location"
    return "answer"


def _missing_details_from_intent(intent: dict[str, Any], location_status: str) -> list[str]:
    if location_status not in {"vague", "needs_evidence"}:
        return []
    missing = ["trusted postcode or latitude/longitude"]
    if not intent.get("activities"):
        missing.append("planned visit activity")
    return missing


def _coordinate_text(coordinate: Any) -> str | None:
    if isinstance(coordinate, (list, tuple)) and len(coordinate) == 2:
        return f"{coordinate[0]}, {coordinate[1]}"
    return None


def _conversation_observability(
    route: str,
    orchestration: dict[str, Any] | None,
    intent: dict[str, Any],
    memory: dict[str, Any],
    *,
    tools_started: bool,
) -> dict[str, Any]:
    pending = memory.get("pendingUserAction") or (orchestration or {}).get("pendingUserAction")
    has_location_evidence = bool(intent.get("hasLocationEvidence"))
    has_site_signal = _has_site_signal(intent)
    if tools_started:
        reason = "Backend durable run accepted; tool trace is attached to the run."
        phase = "running_tools"
    elif pending:
        reason = f"Waiting for user action: {pending}."
        phase = "waiting_for_user"
    elif not has_location_evidence and has_site_signal:
        reason = "No tools started because the message has a site hint but no trusted postcode, coordinate, or confirmed candidate."
        phase = "waiting_for_location_evidence"
    elif not has_site_signal:
        reason = "No tools started because this was handled as conversation, greeting, help, status, or follow-up."
        phase = "conversation_only"
    else:
        reason = "No tools started for this guarded conversation turn."
        phase = "conversation_only"
    metadata = (orchestration or {}).get("metadata") or {}
    return {
        "phase": phase,
        "route": route,
        "toolsStarted": tools_started,
        "modelCalls": metadata.get("modelCallCount", 0),
        "modelPhase": metadata.get("phase"),
        "provider": metadata.get("provider"),
        "pendingUserAction": pending if _is_known_pending_action(pending) else None,
        "noToolReason": None if tools_started else reason,
        "hasLocationEvidence": has_location_evidence,
        "hasSiteSignal": has_site_signal,
    }


def _conversation_trace(
    route: str,
    orchestration: dict[str, Any] | None,
    intent: dict[str, Any],
    memory: dict[str, Any],
    observability: dict[str, Any],
) -> list[dict[str, Any]]:
    metadata = (orchestration or {}).get("metadata") or {}
    return [
        trace_step(
            "conversation_orchestrator",
            "ok" if orchestration and not orchestration.get("failed") else "fallback",
            "Classified the chat turn and decided whether a durable tool run should start.",
            output={
                "route": route,
                "toolsStarted": observability["toolsStarted"],
                "noToolReason": observability.get("noToolReason"),
                "pendingUserAction": observability.get("pendingUserAction"),
                "hasLocationEvidence": observability.get("hasLocationEvidence"),
                "hasSiteSignal": observability.get("hasSiteSignal"),
                "modelPhase": metadata.get("phase"),
                "modelCallCount": metadata.get("modelCallCount", 0),
                "orchestratorReason": (orchestration or {}).get("reason"),
                "activeRunId": memory.get("activeRunId"),
                "siteName": intent.get("siteName"),
                "placeHint": intent.get("placeHint"),
                "areaHint": intent.get("areaHint"),
                "vagueLocationHint": intent.get("vagueLocationHint"),
            },
            source_ids=["bedrock-conversation-orchestrator" if orchestration else "deterministic-router"],
        )
    ]


def _conversation_model_calls(orchestration: dict[str, Any] | None) -> list[dict[str, Any]]:
    metadata = (orchestration or {}).get("metadata") or {}
    count = metadata.get("modelCallCount", 0)
    if not count:
        return []
    return [
        {
            "phase": metadata.get("phase") or "conversation-orchestrator",
            "provider": metadata.get("provider") or "bedrock",
            "modelCallCount": count,
        }
    ]


def _is_known_pending_action(action: Any) -> bool:
    return str(action) in _known_pending_actions()


def _known_pending_actions() -> set[str]:
    return {
        "provide_site_location_and_activity",
        "provide_safe_site_visit_request",
        "confirm_or_correct_location",
        "provide_corrected_location",
        "provide_location_detail",
        "provide_new_site_request",
        "answer_clarifying_question",
        "wait_for_agent_run",
    }


def _confirm_by_chat_response(session_id: str, memory: dict[str, Any], config: RuntimeConfig) -> dict[str, Any]:
    text = (
        "I am still waiting for explicit location confirmation through the candidate card. "
        "Use `Confirm this site` to start map, evidence, risk, and briefing tools, or provide a corrected postcode/coordinate if the candidate is wrong."
    )
    add_conversation_turn(
        session_id,
        role="assistant",
        text=text,
        metadata={"route": "confirm_by_chat", "runId": memory.get("activeRunId")},
        config=config,
    )
    update_working_memory(session_id, config, pendingUserAction="confirm_or_correct_location", latestRoute="confirm_by_chat")
    return {
        "action": "answered_from_memory",
        "route": "confirm_by_chat",
        "assistantMessage": text,
        "runtime": _runtime_contract(config, "lambda-adapter-active"),
    }


def _reject_location_response(
    session_id: str,
    message: str,
    memory: dict[str, Any],
    config: RuntimeConfig,
) -> dict[str, Any]:
    text = (
        "Understood. I will not run the site-review tools for that candidate. "
        "Please provide a corrected UK postcode, latitude/longitude, OS grid reference, nearest road/town, or public evidence for the intended site."
    )
    add_conversation_turn(
        session_id,
        role="assistant",
        text=text,
        metadata={"route": "reject_location", "rejectionPrompt": message[:120], "runId": memory.get("activeRunId")},
        config=config,
    )
    update_working_memory(
        session_id,
        config,
        pendingUserAction="provide_corrected_location",
        latestRoute="reject_location",
        rejectedRunId=memory.get("activeRunId"),
    )
    return {
        "action": "answered_from_memory",
        "route": "reject_location",
        "assistantMessage": text,
        "runtime": _runtime_contract(config, "lambda-adapter-active"),
    }


def _start_over_response(session_id: str, message: str, memory: dict[str, Any], config: RuntimeConfig) -> dict[str, Any]:
    text = (
        "I can start a fresh site review. Send the new site request with a UK postcode, latitude/longitude, or a clear named site plus supporting location detail."
    )
    add_conversation_turn(
        session_id,
        role="assistant",
        text=text,
        metadata={"route": "start_over_without_site", "prompt": message[:120], "previousRunId": memory.get("activeRunId")},
        config=config,
    )
    update_working_memory(
        session_id,
        config,
        pendingUserAction="provide_new_site_request",
        latestRoute="start_over_without_site",
        previousRunId=memory.get("activeRunId"),
        activeRunId=None,
        latestRunStatus=None,
    )
    return {
        "action": "answered_from_memory",
        "route": "start_over_without_site",
        "assistantMessage": text,
        "runtime": _runtime_contract(config, "lambda-adapter-active"),
    }


def _safe_read_run(run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    try:
        return read_durable_run(run_id)
    except HTTPException:
        return None


def _assistant_text_from_run(run: dict[str, Any]) -> str:
    result = run.get("result") or {}
    if result.get("assistantMessage"):
        return result["assistantMessage"]
    status = run.get("status")
    current_step = run.get("currentStep")
    if status in {"queued", "running"}:
        return f"I have started the site review and am currently at `{current_step}`."
    return f"Run {status}: {current_step}."


def _pending_action(run: dict[str, Any]) -> str | None:
    status = run.get("status")
    if status == "waiting_for_location_confirmation":
        result_payload = run.get("result") or {}
        location_resolution = run.get("locationResolution") or result_payload.get("locationResolution") or {}
        if location_resolution.get("locationCandidates"):
            return "confirm_or_correct_location"
        return "provide_location_detail"
    if status == "waiting_for_clarification":
        return "answer_clarifying_question"
    if status in {"queued", "running"}:
        return "wait_for_agent_run"
    return None


def _latest_review_summary(run: dict[str, Any]) -> dict[str, Any] | None:
    result = run.get("result") or {}
    briefing = result.get("briefing") or result.get("uiState", {}).get("briefing")
    if not briefing:
        return None
    return {
        "headline": briefing.get("headline"),
        "generationMode": briefing.get("generation_mode") or briefing.get("generationMode"),
        "runId": run.get("runId"),
        "status": run.get("status"),
    }


def _runtime_contract(config: RuntimeConfig, status: str) -> dict[str, Any]:
    agentcore_configured = bool(config.agentcore_runtime_enabled and config.agentcore_runtime_arn)
    return {
        "agentRuntimeTarget": "agentcore" if agentcore_configured else "lambda",
        "agentRuntimeStatus": status,
        "adapter": "api-gateway-lambda-fastapi",
        "guardsFirst": True,
        "memoryMode": "bounded-session-working-memory",
        "bedrockEnabled": config.bedrock_enabled,
        "awsRegion": config.aws_region,
        "agentCoreRuntimeEnabled": config.agentcore_runtime_enabled,
        "agentCoreMemoryEnabled": config.agentcore_memory_enabled,
        "agentCoreStatus": "configured" if agentcore_configured else "not-enabled-lambda-adapter",
    }
