from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any

from agentcore_client import invoke_runtime_json
from intake_coordinator import (
    build_confirmed_entry_payload,
    build_entry_turn,
    coordinate_intake,
    IntakeValidationError,
)
from llm_intake import deterministic_fallback_enabled, select_model_json
from supervisor_adapter import (
    AdapterValidationError,
    build_agentcore_invocation,
    build_delivery_payload,
    build_report_access_context,
)

try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
    from model.load import load_model
    from mcp_client.client import get_streamable_http_mcp_client
    from memory.session import get_memory_session_manager
    from strands import Agent, tool
    from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
except ImportError:
    BedrockAgentCoreApp = None
    Agent = None

    def tool(func):
        return func


if BedrockAgentCoreApp is not None:
    app = BedrockAgentCoreApp()
    log = app.logger
else:
    app = None
    log = None

DEFAULT_SYSTEM_PROMPT = """
You are the 3D-RAMS AgentVerse entry agent.

Provide a fast conversational intake experience for ASI:ONE users. Help the user clarify location,
area scope, goal, and supporting notes before a deeper 3D-RAMS supervisor run is launched.

Do not claim certified RAMS, emergency guidance, legal approval, work approval, or competent-person
replacement. If a deep site-review report is needed, explain that the AgentCore supervisor workflow
must produce the reviewed report data.

Do not reveal internal reasoning, chain-of-thought, scratchpad text, or <thinking> tags. Answer
directly and concisely. If the user is only testing connectivity, confirm that the AgentVerse to
AgentCore integration is working.
"""


tools = []
_INLINE_FUNCTION_NAMES = set()
_PENDING_INTAKES: dict[str, dict[str, Any]] = {}
_CONVERSATION_STATE: dict[str, dict[str, Any]] = {}


@tool
def add_numbers(a: int, b: int) -> int:
    """Return the sum of two numbers."""
    return a + b


if Agent is not None:
    tools.append(add_numbers)

if Agent is not None:
    entry_mcp_client = get_streamable_http_mcp_client()
    if entry_mcp_client:
        tools.append(entry_mcp_client)


def _make_conversation_manager() -> NullConversationManager:
    return NullConversationManager()


def agent_factory():
    cache: dict[str, Agent] = {}

    def get_or_create_agent(session_id: str, user_id: str) -> Agent:
        actor_id = user_id
        key = f"{session_id}/{actor_id}"
        if key not in cache:
            cache[key] = Agent(
                model=load_model(),
                session_manager=get_memory_session_manager(session_id, actor_id),
                conversation_manager=_make_conversation_manager(),
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                tools=tools,
                hooks=[],
            )
        return cache[key]

    return get_or_create_agent


get_or_create_agent = agent_factory()


def handle_invocation(
    payload: dict[str, Any] | None,
    *,
    supervisor_runtime_arn: str | None = None,
    invoke_runtime=invoke_runtime_json,
    model_json=None,
) -> dict[str, Any]:
    payload = _coerce_entry_payload(payload or {})
    try:
        if _is_report_lookup_payload(payload):
            return _handle_report_lookup(payload, supervisor_runtime_arn=supervisor_runtime_arn, invoke_runtime=invoke_runtime)

        if not _is_entry_turn_payload(payload):
            raise AdapterValidationError("Entry payload must include message, prompt, messages, or intake.")

        turn = build_entry_turn(payload)
        conversation_id = turn["conversationId"]
        conversation_route = None if isinstance(payload.get("intake"), dict) else _conversation_route(turn["message"], conversation_id)
        if conversation_route == "confirm_by_chat" and conversation_id in _PENDING_INTAKES and not _awaiting_location_correction(conversation_id):
            payload = {**payload, "confirmedByUser": True, "intake": _PENDING_INTAKES[conversation_id]}
        elif conversation_route == "location_correction":
            _PENDING_INTAKES.pop(conversation_id, None)
        elif conversation_route:
            return _conversation_route_output(payload, turn, conversation_route)

        if payload.get("confirmedByUser") is True and "intake" not in payload and conversation_id in _PENDING_INTAKES and not _awaiting_location_correction(conversation_id):
            payload = {**payload, "intake": _PENDING_INTAKES[turn["conversationId"]]}
        selected_model_json = select_model_json(payload, model_json)
        intake_started = time.perf_counter()
        intake_result = coordinate_intake(
            payload,
            model_json=selected_model_json,
            fallback_to_deterministic=selected_model_json is not None and deterministic_fallback_enabled(),
        )
        intake_latency_ms = round((time.perf_counter() - intake_started) * 1000)
        entry_observability = _entry_runtime_observability(
            payload,
            selected_model_json=selected_model_json,
            intake_result=intake_result,
            latency_ms=intake_latency_ms,
        )
        user_id = str(payload.get("userId") or "3d-rams-entry-agent")

        if intake_result["status"] != "launch_ready":
            if intake_result["status"] == "confirmation_required" and isinstance(intake_result.get("intake"), dict):
                _PENDING_INTAKES[conversation_id] = intake_result["intake"]
            _remember_intake_state(conversation_id, conversation_route or "intake", intake_result)
            return {
                "output": {
                    "caseId": intake_result.get("caseId"),
                    "delivery": None,
                    "run": None,
                    "structuredReport": None,
                    "reportStatus": "entry_pending",
                    "workflowMode": "entry_intake",
                    "assistantMessage": intake_result["assistantMessage"],
                    "entryAgent": {
                        "mode": _entry_agent_mode(intake_result),
                        "adapterVersion": "asi-one-entry-agent-v2",
                        "conversationId": conversation_id,
                        "route": conversation_route or "intake",
                        "boundedContext": _bounded_conversation_state(conversation_id),
                        "runtimeObservability": entry_observability,
                        **intake_result,
                    },
                }
            }

        confirmed_payload = build_confirmed_entry_payload(turn, intake_result)
        _PENDING_INTAKES.pop(conversation_id, None)

        runtime_arn = supervisor_runtime_arn or os.getenv("RAMS_SUPERVISOR_RUNTIME_ARN")
        if not runtime_arn:
            raise AdapterValidationError("RAMS_SUPERVISOR_RUNTIME_ARN is required for cloud supervisor handoff.")

        invocation = build_agentcore_invocation(confirmed_payload)
        agentcore_response = invoke_runtime(
            runtime_arn=runtime_arn,
            payload=invocation,
            session_id=_agentcore_session_id(conversation_id),
            user_id=user_id,
        )
        delivery = build_delivery_payload(agentcore_response, entry_payload=confirmed_payload)
        assistant_message = _delivery_assistant_message(delivery)
        output = agentcore_response.get("output") if isinstance(agentcore_response.get("output"), dict) else {}
        _remember_supervisor_state(conversation_id, conversation_route or "intake_launch", output, delivery)
        return {
            "output": {
                "caseId": output.get("caseId") or delivery.get("caseId") or confirmed_payload["caseId"],
                "delivery": delivery,
                "run": output.get("run"),
                "structuredReport": output.get("structuredReport"),
                "reportStatus": output.get("reportStatus") or delivery.get("status"),
                "workflowMode": output.get("workflowMode") or delivery.get("workflowMode"),
                "persistence": output.get("persistence"),
                "assistantMessage": assistant_message,
                "entryAgent": {
                    "mode": "cloud-supervisor-handoff",
                    "adapterVersion": "asi-one-entry-agent-v2",
                    "conversationId": conversation_id,
                    "route": conversation_route or "intake_launch",
                    "caseId": output.get("caseId") or delivery.get("caseId") or confirmed_payload["caseId"],
                    "status": "delivered",
                    "assistantMessage": assistant_message,
                    "boundedContext": _bounded_conversation_state(conversation_id),
                    "intakeMode": intake_result.get("intakeMode"),
                    "fallbackReason": intake_result.get("fallbackReason"),
                    "runtimeObservability": entry_observability,
                    "intake": intake_result["intake"],
                },
            }
        }
    except (AdapterValidationError, IntakeValidationError) as exc:
        return _blocked_entry_output(payload, str(exc))


def _conversation_route(message: str, conversation_id: str) -> str | None:
    text = " ".join(str(message or "").strip().lower().split())
    if not text:
        return None
    has_site_evidence = _has_corrected_site_evidence(text)
    if _awaiting_location_correction(conversation_id) and has_site_evidence:
        return "location_correction"
    if _looks_like_start_over(text) and not has_site_evidence:
        return "start_over_without_site"
    if _looks_like_location_rejection(text) and not has_site_evidence:
        return "reject_location"
    if _looks_like_chat_confirmation(text):
        return "confirm_by_chat"
    if _looks_like_status(text):
        return "status"
    if _looks_like_greeting(text) and not has_site_evidence:
        return "greeting"
    if _looks_like_help(text) and not has_site_evidence:
        return "help"
    if _looks_like_follow_up(text) and not has_site_evidence:
        return "follow_up"
    return None


def _conversation_route_output(payload: dict[str, Any], turn: dict[str, Any], route: str) -> dict[str, Any]:
    conversation_id = turn["conversationId"]
    message = turn.get("message") or ""
    if route == "start_over_without_site":
        _PENDING_INTAKES.pop(conversation_id, None)
        _CONVERSATION_STATE.pop(conversation_id, None)
    if route == "reject_location":
        _PENDING_INTAKES.pop(conversation_id, None)

    assistant_message, pending_action = _conversation_message(conversation_id, route)
    state = _CONVERSATION_STATE.setdefault(conversation_id, {})
    state.update(
        {
            "pendingAction": pending_action,
            "recentRoute": route,
            "latestSafeUserSummary": _safe_summary(message),
            "latestSafeAssistantSummary": _safe_summary(assistant_message),
        }
    )
    bounded_context = _bounded_conversation_state(conversation_id)
    return {
        "output": {
            "caseId": state.get("activeCaseId"),
            "delivery": None,
            "run": None,
            "structuredReport": None,
            "reportStatus": "no_active_context" if route == "status" and not _has_active_context(state) else "entry_pending",
            "workflowMode": "entry_conversation",
            "assistantMessage": assistant_message,
            "entryAgent": {
                "mode": "guarded-conversation-router",
                "adapterVersion": "asi-one-entry-agent-v2",
                "conversationId": conversation_id,
                "route": route,
                "status": "conversation_routed",
                "pendingAction": pending_action,
                "assistantMessage": assistant_message,
                "boundedContext": bounded_context,
                "runtimeObservability": {
                    "schemaVersion": "3d-rams.runtime-observability.v1",
                    "modelPath": "entry-conversation-router",
                    "modelCallCount": 0,
                    "bedrockRequested": False,
                    "bedrockEnabled": False,
                    "bedrockUsed": False,
                    "activeAgentMode": "guarded-conversation-router",
                },
            },
        }
    }


def _conversation_message(conversation_id: str, route: str) -> tuple[str, str | None]:
    state = _CONVERSATION_STATE.get(conversation_id, {})
    pending = state.get("pendingAction")
    if route == "greeting":
        return (
            "Hi. Send the site, area or radius, and planned visit purpose, and I will prepare the intake for confirmation.",
            pending or "awaiting_intake_details",
        )
    if route == "help":
        return (
            "I can start a pre-visit 3D-RAMS review once you provide a site, review area, and visit purpose. I will ask for confirmation before launching the supervisor.",
            pending or "awaiting_intake_details",
        )
    if route == "status":
        if conversation_id in _PENDING_INTAKES and pending != "awaiting_location_correction":
            return (
                f"An intake is waiting for confirmation: {_safe_summary(_intake_summary(_PENDING_INTAKES[conversation_id]))}",
                "awaiting_confirmation",
            )
        if pending == "awaiting_location_correction":
            return (
                "I am waiting for corrected site evidence before launching anything. Send a postcode, coordinates, OS grid reference, or a clear site name with usable detail.",
                "awaiting_location_correction",
            )
        if _has_active_context(state):
            return (
                f"Latest supervisor context: case {state.get('activeCaseId')} is {state.get('activeRunStatus') or 'available'}.",
                None,
            )
        return ("I do not have an active intake or supervisor run in this conversation yet.", None)
    if route == "follow_up":
        if pending == "awaiting_location_correction":
            return (
                "I need corrected site evidence before I can continue: a postcode, coordinates, OS grid reference, or a clear site name with usable detail.",
                "awaiting_location_correction",
            )
        if conversation_id in _PENDING_INTAKES:
            return (
                f"I have a draft intake waiting for your confirmation: {_safe_summary(_intake_summary(_PENDING_INTAKES[conversation_id]))}",
                "awaiting_confirmation",
            )
        return (
            "I need enough public-safe site context to start: site evidence, review area or radius, and the planned visit purpose.",
            "awaiting_intake_details",
        )
    if route == "confirm_by_chat":
        if pending == "awaiting_location_correction":
            return (
                "I will not launch the previous intake after a location rejection. Send corrected site evidence first.",
                "awaiting_location_correction",
            )
        return ("There is no intake waiting for confirmation in this conversation yet.", "awaiting_intake_details")
    if route == "reject_location":
        return (
            "Understood. I will not launch that location. Send corrected site evidence, such as a postcode, coordinates, OS grid reference, or a clear site name with usable detail.",
            "awaiting_location_correction",
        )
    return (
        "Starting over. Send the site, area or radius, and planned visit purpose when you are ready.",
        "awaiting_intake_details",
    )


def _remember_intake_state(conversation_id: str, route: str, intake_result: dict[str, Any]) -> None:
    state = _CONVERSATION_STATE.setdefault(conversation_id, {})
    pending_action = "awaiting_confirmation" if intake_result.get("status") == "confirmation_required" else "awaiting_intake_details"
    state.update(
        {
            "pendingAction": pending_action,
            "recentRoute": route,
            "latestSafeAssistantSummary": _safe_summary(intake_result.get("assistantMessage")),
        }
    )
    if isinstance(intake_result.get("intake"), dict):
        state["publicSafeLocationSummary"] = _safe_summary(_location_summary(intake_result["intake"]))


def _remember_supervisor_state(
    conversation_id: str,
    route: str,
    output: dict[str, Any],
    delivery: dict[str, Any],
) -> None:
    state = _CONVERSATION_STATE.setdefault(conversation_id, {})
    state.update(
        {
            "pendingAction": None,
            "recentRoute": route,
            "activeCaseId": output.get("caseId") or delivery.get("caseId"),
            "activeRunStatus": output.get("reportStatus") or delivery.get("status"),
            "activeWorkflowMode": output.get("workflowMode") or delivery.get("workflowMode"),
            "latestSafeAssistantSummary": _safe_summary(_delivery_assistant_message(delivery)),
        }
    )


def _bounded_conversation_state(conversation_id: str) -> dict[str, Any]:
    state = _CONVERSATION_STATE.get(conversation_id, {})
    allowed = (
        "pendingAction",
        "recentRoute",
        "latestSafeAssistantSummary",
        "latestSafeUserSummary",
        "activeCaseId",
        "activeRunStatus",
        "activeWorkflowMode",
        "publicSafeLocationSummary",
    )
    return {key: state[key] for key in allowed if state.get(key)}


def _awaiting_location_correction(conversation_id: str) -> bool:
    return _CONVERSATION_STATE.get(conversation_id, {}).get("pendingAction") == "awaiting_location_correction"


def _has_active_context(state: dict[str, Any]) -> bool:
    return bool(state.get("activeCaseId") or state.get("activeRunStatus"))


def _looks_like_chat_confirmation(text: str) -> bool:
    return bool(
        text in {"yes", "yes please", "confirm", "confirmed", "launch", "go", "go ahead"}
        or re.search(r"^(please\s+)?(confirm|confirmed|proceed|go ahead|launch)\b", text)
        or re.search(r"\b(confirm(ed)? and launch|please launch)\b", text)
    )


def _looks_like_status(text: str) -> bool:
    return bool(re.search(r"\b(status|progress|where are we|what.*happening|active run|current run)\b", text))


def _looks_like_greeting(text: str) -> bool:
    return text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}


def _looks_like_help(text: str) -> bool:
    return bool(text in {"help", "help me"} or re.search(r"\b(how does this work|what can you do|can you help)\b", text))


def _looks_like_follow_up(text: str) -> bool:
    return bool(re.search(r"\b(what do you mean|explain|what next|what else|why|how so)\b", text))


def _looks_like_location_rejection(text: str) -> bool:
    return bool(
        re.search(r"\b(wrong|incorrect|not right|not that|different)\s+(site|location|address|place)\b", text)
        or re.search(r"\b(no|nah|nope),?\s+(wrong|incorrect|not that|different)\b", text)
        or re.search(r"\bthat'?s\s+(wrong|incorrect|not the right)\b", text)
    )


def _looks_like_start_over(text: str) -> bool:
    return bool(re.search(r"\b(start over|restart|reset|clear this|new intake)\b", text))


def _has_corrected_site_evidence(text: str) -> bool:
    return bool(
        re.search(r"-?\d{1,2}(?:\.\d+)?\s*,\s*-?\d{1,3}(?:\.\d+)?", text)
        or re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", text, re.I)
        or re.search(r"\b[A-Z]{2}\s*\d{3,5}\s*\d{3,5}\b", text, re.I)
        or re.search(r"\b\d+\s+[a-z][a-z\s'-]{2,}\s+(street|road|lane|avenue|drive|way|place|embankment)\b", text)
        or re.search(r"\b(near|at|use|site is|location is)\s+[a-z0-9][a-z0-9\s,'-]{5,}", text)
    )


def _safe_summary(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"https?://\S+", "[redacted-url]", text, flags=re.I)
    text = re.sub(
        r"\b(access[-_\s]?code|identity[-_\s]?token|bearer[-_\s]?token|session[-_\s]?secret|signed[-_\s]?url|token)\b\s*[:=]?\s*\S+",
        r"\1 [redacted]",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[redacted-email]", text)
    return text[:limit]


def _intake_summary(intake: dict[str, Any]) -> str:
    return f"{_location_summary(intake)}, {intake.get('areaScope', {}).get('meters')}m radius, {intake.get('userGoal') or 'pre-visit review'}"


def _location_summary(intake: dict[str, Any]) -> str:
    return str(intake.get("locationText") or intake.get("locationCandidate", {}).get("label") or "selected site")


def _blocked_entry_output(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    runtime_options = payload.get("runtimeOptions") if isinstance(payload.get("runtimeOptions"), dict) else {}
    conversation_id = str(payload.get("conversationId") or payload.get("sessionId") or "frontend-demo-session")
    assistant_message = "I could not launch the supervisor workflow because the entry payload failed validation."
    return {
        "output": {
            "caseId": payload.get("caseId"),
            "delivery": None,
            "run": None,
            "structuredReport": None,
            "reportStatus": "blocked",
            "workflowMode": "entry_intake",
            "assistantMessage": assistant_message,
            "runtime": {
                "bedrockRequested": bool(runtime_options.get("useBedrock", True)),
                "bedrockEnabled": False,
                "bedrockUsed": False,
                "activeAgentMode": "entry-blocked",
                "fallbackReason": reason,
                "runtimeObservability": _blocked_entry_observability(runtime_options, reason),
            },
            "entryAgent": {
                "mode": "intake-coordinator",
                "adapterVersion": "asi-one-entry-agent-v2",
                "conversationId": conversation_id,
                "status": "blocked",
                "assistantMessage": assistant_message,
                "fallbackReason": reason,
                "runtimeObservability": _blocked_entry_observability(runtime_options, reason),
                "intake": None,
            },
        }
    }


def invoke_local(
    payload: dict[str, Any] | None = None,
    *,
    supervisor_invoker=None,
) -> dict[str, Any]:
    if payload and not _is_entry_turn_payload(payload) and "input" in payload:
        from supervisor_core.agentcore_adapter import handle_invocation as supervisor_handle_invocation

        return supervisor_handle_invocation(payload)

    if supervisor_invoker is None:
        from supervisor_core.agentcore_adapter import handle_invocation as supervisor_invoker

        def local_invoke_runtime(**kwargs):
            return supervisor_invoker(kwargs["payload"])

    else:
        def local_invoke_runtime(**kwargs):
            return supervisor_invoker(kwargs["payload"])

    return handle_invocation(
        payload,
        supervisor_runtime_arn="local-test-supervisor-runtime",
        invoke_runtime=local_invoke_runtime,
    )


def _extract_prompt(payload: dict[str, Any]):
    """Accept harness-style messages[], tool_results[], or plain prompt string payloads."""
    if "messages" in payload:
        return payload["messages"]
    if "tool_results" in payload:
        return [
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": tool_result["toolUseId"],
                            "status": tool_result.get("status", "success"),
                            "content": tool_result.get("content", []),
                        }
                    }
                    for tool_result in payload["tool_results"]
                ],
            }
        ]
    return payload.get("prompt", "")


def _coerce_entry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return payload
    try:
        parsed = json.loads(prompt)
    except json.JSONDecodeError:
        return payload
    if not isinstance(parsed, dict):
        return payload
    return {**payload, **parsed}


if app is not None:

    @app.entrypoint
    async def invoke(payload: dict[str, Any], context: Any):
        log.info("Invoking 3D-RAMS AgentVerse entry runtime.")

        coerced_payload = _coerce_entry_payload(payload)
        if _is_entry_turn_payload(coerced_payload) or _is_report_lookup_payload(coerced_payload):
            result = handle_invocation(coerced_payload)
            yield _text_delta_event(json.dumps(result))
            return

        session_id = getattr(context, "session_id", "default-session")
        user_id = getattr(context, "user_id", "default-user")
        agent = get_or_create_agent(session_id, user_id)
        prompt = _extract_prompt(payload)

        async for event in agent.stream_async(prompt):
            if not isinstance(event, dict) or "event" not in event:
                continue
            content_block_start = event["event"].get("contentBlockStart")
            if content_block_start is not None and not content_block_start.get("start"):
                continue
            yield event


def _is_entry_turn_payload(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("entryTurn")
        or payload.get("frontendInvoke")
        or payload.get("intake")
        or payload.get("message") is not None
        or payload.get("prompt") is not None
        or payload.get("messages") is not None
    )


def _is_report_lookup_payload(payload: dict[str, Any]) -> bool:
    operation = str(payload.get("operation") or payload.get("action") or "").strip().lower()
    return operation in {"getreport", "get_report", "lookupreport", "lookup_report"} and bool(payload.get("caseId"))


def _handle_report_lookup(
    payload: dict[str, Any],
    *,
    supervisor_runtime_arn: str | None = None,
    invoke_runtime=invoke_runtime_json,
) -> dict[str, Any]:
    runtime_arn = supervisor_runtime_arn or os.getenv("RAMS_SUPERVISOR_RUNTIME_ARN")
    if not runtime_arn:
        raise AdapterValidationError("RAMS_SUPERVISOR_RUNTIME_ARN is required for report lookup.")

    case_id = str(payload["caseId"])
    conversation_id = str(payload.get("conversationId") or payload.get("sessionId") or f"report-lookup-{case_id}")
    user_id = str(payload.get("userId") or "3d-rams-entry-agent")
    report_access = build_report_access_context(payload, case_id, conversation_id=conversation_id, user_id=user_id)
    response = invoke_runtime(
        runtime_arn=runtime_arn,
        payload={
            "input": {
                "operation": "getReport",
                "caseId": case_id,
                "reportAccess": report_access,
                "upstream": _lookup_upstream(payload, conversation_id),
            }
        },
        session_id=conversation_id,
        user_id=user_id,
    )
    output = response.get("output") if isinstance(response.get("output"), dict) else {}
    return {
        "output": {
            **output,
            "entryAgent": {
                "mode": "cloud-report-lookup",
                "adapterVersion": "asi-one-entry-agent-v1",
                "conversationId": conversation_id,
                "caseId": case_id,
            },
        }
    }


def _lookup_upstream(payload: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    upstream = {
        "source": _lookup_source(payload),
        "caseId": str(payload.get("caseId")),
        "conversationId": conversation_id,
        "entryAgentId": str(payload.get("entryAgentId") or "@3d-rams"),
        "authorizationMode": "identity_bound_report_lookup",
    }
    identity = payload.get("identity") or payload.get("authorizationContext") or {}
    if isinstance(identity, dict):
        safe_identity = {
            key: identity[key]
            for key in ("subjectRef", "organizationRef", "sessionRef", "issuer", "authMode")
            if identity.get(key)
        }
        if safe_identity:
            upstream["identity"] = safe_identity
    return upstream


def _lookup_source(payload: dict[str, Any]) -> str:
    caller = str(payload.get("caller") or payload.get("source") or "").strip().lower()
    if caller == "frontend" or payload.get("frontendInvoke"):
        return "FRONTEND"
    if caller == "agentverse":
        return "AGENTVERSE"
    return "ASI_ONE_ENTRY_AGENT"
def _text_delta_event(text: str) -> dict[str, Any]:
    return {"event": {"contentBlockDelta": {"delta": {"text": text}}}}


def _agentcore_session_id(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"3d-rams-entry-agent:{seed}"))


def _entry_agent_mode(intake_result: dict[str, Any]) -> str:
    intake_mode = intake_result.get("intakeMode")
    if intake_mode == "llm":
        return "llm-first-intake"
    if intake_mode == "fallback":
        return "deterministic-fallback-intake"
    if intake_mode == "provided":
        return "provided-confirmed-intake"
    return "deterministic-intake"


def _entry_runtime_observability(
    payload: dict[str, Any],
    *,
    selected_model_json,
    intake_result: dict[str, Any],
    latency_ms: int,
) -> dict[str, Any]:
    runtime_options = payload.get("runtimeOptions") if isinstance(payload.get("runtimeOptions"), dict) else {}
    intake_mode = str(intake_result.get("intakeMode") or "unknown")
    uses_bedrock_model = getattr(selected_model_json, "__name__", "") == "bedrock_intake_model_json"
    summary = {
        "schemaVersion": "3d-rams.runtime-observability.v1",
        "modelPath": f"entry-{intake_mode}",
        "modelId": _entry_model_id() if uses_bedrock_model else None,
        "awsRegion": os.getenv("AWS_REGION", "eu-west-2") if uses_bedrock_model else None,
        "modelCallCount": 1 if selected_model_json is not None and intake_mode in {"llm", "fallback"} else 0,
        "latencyMs": latency_ms,
        "bedrockRequested": bool(runtime_options.get("useBedrock", True)),
        "bedrockEnabled": uses_bedrock_model,
        "bedrockUsed": uses_bedrock_model and intake_mode == "llm",
        "activeAgentMode": _entry_agent_mode(intake_result),
        "fallbackReason": intake_result.get("fallbackReason"),
    }
    return {key: value for key, value in summary.items() if value is not None}


def _blocked_entry_observability(runtime_options: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schemaVersion": "3d-rams.runtime-observability.v1",
        "modelPath": "entry-blocked",
        "modelCallCount": 0,
        "bedrockRequested": bool(runtime_options.get("useBedrock", True)),
        "bedrockEnabled": False,
        "bedrockUsed": False,
        "activeAgentMode": "entry-blocked",
        "fallbackReason": reason,
    }


def _entry_model_id() -> str:
    return os.getenv("ENTRY_INTAKE_MODEL_ID") or os.getenv("ENTRY_AGENT_MODEL_ID") or "amazon.nova-micro-v1:0"


def _delivery_assistant_message(delivery: dict[str, Any]) -> str:
    summary = delivery.get("customerSummary") if isinstance(delivery.get("customerSummary"), dict) else {}
    headline = str(summary.get("headline") or "Supervisor workflow completed.")
    priority_checks = summary.get("priorityChecks") if isinstance(summary.get("priorityChecks"), list) else []
    safety_message = str(summary.get("safetyMessage") or delivery.get("safetyReminder") or "Human review is required before use.")
    case_url = delivery.get("caseUrl")

    lines = [headline]
    if priority_checks:
        checks = "; ".join(str(item) for item in priority_checks[:4] if item)
        if checks:
            lines.append(f"Priority checks: {checks}.")
    lines.append(safety_message)
    if case_url:
        lines.append(f"Report reference: {case_url}")
    return "\n\n".join(lines)


if __name__ == "__main__":
    if app is None:
        raise RuntimeError("bedrock-agentcore and Strands dependencies are required to run the entry runtime server.")
    app.run()
