from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable

from rams_agent_tools.tools import trace_step

from supervisor_adapter import AdapterValidationError, build_agentcore_invocation, build_delivery_payload


SupervisorInvoker = Callable[[dict[str, Any]], dict[str, Any]]


def run_local_asione_chat(
    payload: dict[str, Any] | None,
    *,
    supervisor_invoker: SupervisorInvoker,
) -> dict[str, Any]:
    """Deterministic no-AWS ASI:ONE substitute for local Demo1 runs."""
    started = time.perf_counter()
    payload = payload or {}
    session_id = str(payload.get("sessionId") or "local-asione-session")
    conversation_id = str(payload.get("conversationId") or session_id)
    message = _message_from_payload(payload)
    runtime_options = _runtime_options(payload)
    run_id = f"local-entry-{uuid.uuid4().hex[:12]}"

    intake, intake_trace, clarifying_questions = _parse_intake(
        message=message,
        runtime_options=runtime_options,
    )
    if clarifying_questions:
        return _clarification_response(
            session_id=session_id,
            conversation_id=conversation_id,
            run_id=run_id,
            message=message,
            clarifying_questions=clarifying_questions,
            trace=intake_trace,
            started=started,
        )

    if payload.get("confirmedByUser") is not True:
        return _confirmation_response(
            session_id=session_id,
            conversation_id=conversation_id,
            run_id=run_id,
            message=message,
            intake=intake,
            trace=intake_trace,
            started=started,
        )

    entry_payload = {
        "conversationId": conversation_id,
        "entryAgentId": "local-asione-substitute",
        "confirmedByUser": True,
        "intake": intake,
        "runtimeOptions": runtime_options,
    }
    try:
        invocation = build_agentcore_invocation(entry_payload)
    except AdapterValidationError as exc:
        return _clarification_response(
            session_id=session_id,
            conversation_id=conversation_id,
            run_id=run_id,
            message=message,
            clarifying_questions=[str(exc)],
            trace=intake_trace,
            started=started,
        )

    handoff_trace = trace_step(
        "entry_agent_supervisor_handoff",
        "ok",
        "Local ASI:ONE substitute confirmed intake and invoked the supervisor runtime contract.",
        {
            "adapter": "asi_one_entry_agent.supervisor_adapter",
            "confirmedByUser": True,
            "runtimeOptions": sorted(runtime_options),
        },
        source_ids=["user-request"],
    )
    agentcore_response = supervisor_invoker(invocation)
    delivery = build_delivery_payload(agentcore_response, entry_payload=entry_payload)
    delivery_trace = trace_step(
        "entry_agent_delivery_summary",
        "ok",
        "Entry agent converted supervisor output into a user-facing delivery summary.",
        {
            "status": delivery["status"],
            "workflowMode": delivery["workflowMode"],
            "visualizationReady": delivery["deepReport"]["visualizationReady"],
        },
        source_ids=["user-request"],
    )

    output = _agentcore_output(agentcore_response)
    run = output.get("run") if isinstance(output.get("run"), dict) else None
    if run:
        combined_trace = intake_trace + [handoff_trace] + list(run.get("trace") or []) + [delivery_trace]
        run["trace"] = combined_trace
        run["runId"] = run_id
        run_runtime = run.setdefault("runtime", {})
        run_runtime["localAsiOneSubstitute"] = True
        run_runtime["entryAgentMode"] = "deterministic-local"
        _patch_architecture_trace(run, combined_trace)

    runtime = {
        "localAsiOneSubstitute": True,
        "entryAgentMode": "deterministic-local",
        "entryAdapter": "asi_one_entry_agent.supervisor_adapter",
        "supervisorRuntime": "local-direct",
        "latencyMs": int((time.perf_counter() - started) * 1000),
    }
    if run and isinstance(run.get("runtime"), dict):
        runtime.update(run["runtime"])

    return {
        "sessionId": session_id,
        "conversationId": conversation_id,
        "runId": run_id,
        "assistantMessage": _delivery_message(delivery),
        "needsClarification": False,
        "needsConfirmation": False,
        "clarifyingQuestions": [],
        "confirmation": {"confirmedByUser": True, "summary": _confirmation_summary(intake)},
        "entry": _entry_state(message, intake),
        "delivery": delivery,
        "uiState": _ui_state_from_run(run),
        "runtime": runtime,
        "trace": intake_trace + [handoff_trace, delivery_trace],
        "agentcoreOutput": output,
        "run": run,
    }


def _parse_intake(
    *,
    message: str,
    runtime_options: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    lower = message.lower()
    coordinate = _extract_coordinate(message)
    known_lambeth = any(term in lower for term in ["lambeth", "albert embankment", "thames", "8 albert"])
    farm_like = "farm" in lower or "field" in lower
    location_phrase = bool(re.search(r"\b(near|at|around|within|in|address|coordinate|landmark)\b", lower))
    site_label = _extract_site_label(message)
    has_site_signal = coordinate is not None or known_lambeth or farm_like or (location_phrase and bool(site_label))
    has_scope_signal = bool(re.search(r"\b(radius|metre|meter|m\b|km|area|boundary|near|around|within)\b", lower))
    has_goal_signal = bool(
        re.search(
            r"\b(risk|rams|review|survey|inspection|visit|access|planning|flood|hazard|constraint|brief)\b",
            lower,
        )
    )

    trace = [
        trace_step(
            "entry_intake_parse",
            "ok" if has_site_signal and has_scope_signal and has_goal_signal else "warning",
            "Local ASI:ONE substitute parsed the user message into entry-agent intake fields.",
            {
                "hasCoordinate": coordinate is not None,
                "knownPublicFixture": known_lambeth,
                "farmLikeName": farm_like,
                "locationPhrase": location_phrase,
                "hasScopeSignal": has_scope_signal,
                "hasGoalSignal": has_goal_signal,
                "messageSummary": _summarise_message(message),
            },
            source_ids=["user-request"],
        )
    ]

    questions = []
    if not has_site_signal:
        questions.append("Which site should I assess? Please provide a site name, nearby landmark, address, or coordinate.")
    if not has_scope_signal:
        questions.append("What area should I cover around the site, for example a radius or boundary?")
    if not has_goal_signal:
        questions.append("What is the planned visit goal, for example inspection, survey, access review, or planning context?")
    if questions:
        return {}, trace, questions

    location_candidate: dict[str, Any] = {}
    location_text = site_label or message
    fixture_pack = runtime_options.get("fixturePack")
    if coordinate:
        location_candidate = {
            "label": location_text,
            "lat": coordinate[0],
            "lng": coordinate[1],
            "confidence": 0.86,
        }
        fixture_pack = None
    elif known_lambeth:
        location_text = "near 8 Albert Embankment, Lambeth"
        location_candidate = {
            "label": "8 Albert Embankment and land to the rear",
            "lat": 51.492099,
            "lng": -0.118712,
            "confidence": 0.82,
        }
        fixture_pack = fixture_pack or "public-lambeth-thames"

    intake = {
        "locationText": location_text,
        "locationCandidate": location_candidate,
        "areaScope": _area_scope(message),
        "userGoal": _goal_from_message(message),
        "userNotes": message,
        "materials": _materials(runtime_options),
    }
    if fixture_pack:
        runtime_options["fixturePack"] = fixture_pack
    return intake, trace, []


def _clarification_response(
    *,
    session_id: str,
    conversation_id: str,
    run_id: str,
    message: str,
    clarifying_questions: list[str],
    trace: list[dict[str, Any]],
    started: float,
) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "conversationId": conversation_id,
        "runId": run_id,
        "assistantMessage": "I need a little more information before I can launch the 3D-RAMS supervisor.",
        "needsClarification": True,
        "needsConfirmation": False,
        "clarifyingQuestions": clarifying_questions,
        "confirmation": None,
        "entry": _entry_state(message, {}),
        "delivery": None,
        "uiState": _empty_ui_state(trace),
        "runtime": {
            "localAsiOneSubstitute": True,
            "entryAgentMode": "deterministic-local",
            "supervisorRuntime": "not-invoked",
            "briefingMode": "not-run",
            "latencyMs": int((time.perf_counter() - started) * 1000),
        },
        "trace": trace,
        "agentcoreOutput": None,
        "run": None,
    }


def _confirmation_response(
    *,
    session_id: str,
    conversation_id: str,
    run_id: str,
    message: str,
    intake: dict[str, Any],
    trace: list[dict[str, Any]],
    started: float,
) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "conversationId": conversation_id,
        "runId": run_id,
        "assistantMessage": "I have enough information. Please confirm that I should launch the supervisor run.",
        "needsClarification": False,
        "needsConfirmation": True,
        "clarifyingQuestions": [],
        "confirmation": {"confirmedByUser": False, "summary": _confirmation_summary(intake)},
        "entry": _entry_state(message, intake),
        "delivery": None,
        "uiState": _empty_ui_state(trace),
        "runtime": {
            "localAsiOneSubstitute": True,
            "entryAgentMode": "deterministic-local",
            "supervisorRuntime": "awaiting-confirmation",
            "briefingMode": "not-run",
            "latencyMs": int((time.perf_counter() - started) * 1000),
        },
        "trace": trace,
        "agentcoreOutput": None,
        "run": None,
    }


def _runtime_options(payload: dict[str, Any]) -> dict[str, Any]:
    options = dict(payload.get("runtimeOptions") or {})
    options.setdefault("useBedrock", bool(options.get("useBedrock", True)))
    options.setdefault("includePlanningFixture", bool(options.get("includePlanningFixture", True)))
    options.setdefault("simulateMapFailure", bool(options.get("simulateMapFailure", False)))
    return options


def _message_from_payload(payload: dict[str, Any]) -> str:
    message = payload.get("message") or payload.get("prompt") or ""
    if isinstance(message, list):
        text_parts = []
        for item in message:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("text"):
                    text_parts.append(str(content["text"]))
        message = " ".join(text_parts)
    return str(message).strip()


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
    if not cleaned:
        return ""
    if any(term in cleaned.lower() for term in ["help", "not sure", "what can you"]):
        return ""
    return cleaned[:90]


def _area_scope(message: str) -> dict[str, Any]:
    match = re.search(r"(\d{2,5})\s*(m|metre|meter|metres|meters)\b", message.lower())
    if match:
        return {"type": "radius", "meters": int(match.group(1))}
    return {"type": "radius", "meters": 800}


def _goal_from_message(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    return cleaned[:220] if cleaned else "pre-visit site risk and planning context"


def _materials(runtime_options: dict[str, Any]) -> list[dict[str, Any]]:
    materials = runtime_options.get("materials") or []
    return materials if isinstance(materials, list) else []


def _summarise_message(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    return cleaned[:160]


def _confirmation_summary(intake: dict[str, Any]) -> str:
    if not intake:
        return "No confirmed intake yet."
    scope = intake.get("areaScope") or {}
    meters = scope.get("meters", "unknown")
    return f"{intake.get('locationText')} | {meters}m area | {intake.get('userGoal')}"


def _delivery_message(delivery: dict[str, Any]) -> str:
    summary = delivery["customerSummary"]
    checks = "; ".join(summary.get("priorityChecks", [])[:3])
    return (
        f"{summary['headline']} Top checks: {checks}. "
        f"{summary['safetyMessage']}"
    ).strip()


def _entry_state(message: str, intake: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "local-asione-substitute",
        "entryAgent": "asi_one_entry_agent",
        "messageSummary": _summarise_message(message),
        "intake": intake,
    }


def _empty_ui_state(trace: list[dict[str, Any]]) -> dict[str, Any]:
    return {
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
            "message": "Supervisor was not invoked because entry intake is incomplete or unconfirmed.",
        },
        "trace": trace,
        "architecture": None,
    }


def _ui_state_from_run(run: dict[str, Any] | None) -> dict[str, Any]:
    if not run:
        return _empty_ui_state([])
    return {
        "location": run.get("location"),
        "scene": run.get("scene"),
        "annotations": run.get("annotations") or [],
        "hazards": run.get("hazards") or [],
        "evidence": run.get("evidence") or [],
        "sources": run.get("sources") or [],
        "briefing": run.get("briefing"),
        "safety": run.get("safety"),
        "trace": run.get("trace") or [],
        "architecture": run.get("architecture"),
    }


def _agentcore_output(agentcore_response: dict[str, Any]) -> dict[str, Any]:
    output = agentcore_response.get("output")
    return output if isinstance(output, dict) else {}


def _patch_architecture_trace(run: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    architecture = run.get("architecture")
    if isinstance(architecture, dict) and isinstance(architecture.get("currentTrace"), list):
        architecture["currentTrace"] = trace
