from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .config import RuntimeConfig
from .durable_runner import create_durable_run, read_durable_run
from .session_store import add_conversation_turn, get_session, update_working_memory
from .site_intent import parse_site_intent


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

_STATUS_PHRASES = {
    "status",
    "where are we",
    "what is happening",
    "is it done",
    "are you done",
}


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

    route = _classify_message(cleaned, memory)
    if route == "status":
        return _status_response(session_id, memory, config)
    if route == "follow_up":
        return _memory_response(session_id, cleaned, memory, config)

    intent = parse_site_intent(cleaned)
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
            "runId": result.get("runId"),
            "runStatus": result.get("status"),
            "siteIntent": {
                "hasLocationEvidence": intent.get("hasLocationEvidence"),
                "namedSiteHint": intent.get("namedSiteHint"),
                "unsafeIntent": intent.get("unsafeIntent"),
            },
        },
        config=config,
    )
    update_working_memory(
        session_id,
        config,
        activeRunId=result.get("runId"),
        latestRunStatus=result.get("status"),
        pendingUserAction=_pending_action(result),
        latestLocationResolution=(result.get("locationResolution") or result.get("result", {}).get("locationResolution")),
        latestReviewSummary=_latest_review_summary(result),
    )
    return {
        "action": "started_run",
        "route": "new_or_guarded_run",
        "assistantMessage": assistant_text,
        "run": result,
        "runtime": _runtime_contract(config, "lambda-adapter-active"),
    }


def _classify_message(message: str, memory: dict[str, Any]) -> str:
    lower = message.lower().strip(" ?.!")
    if lower in _STATUS_PHRASES or any(lower.startswith(f"{phrase} ") for phrase in _STATUS_PHRASES):
        return "status"
    if lower in _FOLLOW_UP_PHRASES or any(lower.startswith(f"{phrase} ") for phrase in _FOLLOW_UP_PHRASES):
        return "follow_up"
    if memory.get("pendingUserAction") and lower in {"yes", "ok", "okay", "confirm", "confirmed"}:
        return "follow_up"
    return "new_run"


def _status_response(session_id: str, memory: dict[str, Any], config: RuntimeConfig) -> dict[str, Any]:
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
        return {
            "action": "answered_from_memory",
            "route": "status",
            "assistantMessage": text,
            "run": run,
            "runtime": _runtime_contract(config, "lambda-adapter-active"),
        }
    text = "I do not have an active run in this session yet. Send a site visit request with a postcode or latitude/longitude to begin."
    add_conversation_turn(session_id, role="assistant", text=text, metadata={"route": "status"}, config=config)
    return {"action": "answered_from_memory", "route": "status", "assistantMessage": text, "runtime": _runtime_contract(config, "lambda-adapter-active")}


def _memory_response(session_id: str, message: str, memory: dict[str, Any], config: RuntimeConfig) -> dict[str, Any]:
    latest = memory.get("latestAssistantMessage")
    pending = memory.get("pendingUserAction")
    if latest:
        text = (
            "I was referring to the previous step in this same session: "
            f"{latest} "
            "If that is unclear, provide a corrected postcode/coordinate or ask me about a specific panel such as location, evidence, risk, trace, or safety."
        )
    elif pending:
        text = f"I am waiting for: {pending}."
    else:
        text = "I do not have enough prior context in memory yet. Please send the site location and planned visit activity."
    add_conversation_turn(
        session_id,
        role="assistant",
        text=text,
        metadata={"route": "follow_up", "followUpPrompt": message[:120]},
        config=config,
    )
    return {
        "action": "answered_from_memory",
        "route": "follow_up",
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
        location_resolution = run.get("locationResolution") or run.get("result", {}).get("locationResolution") or {}
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
    return {
        "agentRuntimeTarget": "agentcore",
        "agentRuntimeStatus": status,
        "adapter": "api-gateway-lambda-fastapi",
        "guardsFirst": True,
        "memoryMode": "bounded-session-working-memory",
        "bedrockEnabled": config.bedrock_enabled,
        "awsRegion": config.aws_region,
    }
