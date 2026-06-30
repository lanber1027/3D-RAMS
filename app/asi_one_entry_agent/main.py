from __future__ import annotations

import json
import os
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
        if payload.get("confirmedByUser") is True and "intake" not in payload and turn["conversationId"] in _PENDING_INTAKES:
            payload = {**payload, "intake": _PENDING_INTAKES[turn["conversationId"]]}
        selected_model_json = select_model_json(payload, model_json)
        intake_result = coordinate_intake(
            payload,
            model_json=selected_model_json,
            fallback_to_deterministic=selected_model_json is not None and deterministic_fallback_enabled(),
        )
        conversation_id = turn["conversationId"]
        user_id = str(payload.get("userId") or "3d-rams-entry-agent")

        if intake_result["status"] != "launch_ready":
            if intake_result["status"] == "confirmation_required" and isinstance(intake_result.get("intake"), dict):
                _PENDING_INTAKES[conversation_id] = intake_result["intake"]
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
                    "caseId": output.get("caseId") or delivery.get("caseId") or confirmed_payload["caseId"],
                    "status": "delivered",
                    "assistantMessage": assistant_message,
                    "intakeMode": intake_result.get("intakeMode"),
                    "fallbackReason": intake_result.get("fallbackReason"),
                    "intake": intake_result["intake"],
                },
            }
        }
    except (AdapterValidationError, IntakeValidationError) as exc:
        return _blocked_entry_output(payload, str(exc))


def _blocked_entry_output(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    runtime_options = payload.get("runtimeOptions") if isinstance(payload.get("runtimeOptions"), dict) else {}
    conversation_id = str(payload.get("conversationId") or payload.get("sessionId") or "frontend-demo-session")
    return {
        "output": {
            "caseId": payload.get("caseId"),
            "delivery": None,
            "run": None,
            "structuredReport": None,
            "reportStatus": "blocked",
            "workflowMode": "entry_intake",
            "runtime": {
                "bedrockRequested": bool(runtime_options.get("useBedrock", True)),
                "bedrockEnabled": False,
                "bedrockUsed": False,
                "activeAgentMode": "entry-blocked",
                "fallbackReason": reason,
            },
            "entryAgent": {
                "mode": "intake-coordinator",
                "adapterVersion": "asi-one-entry-agent-v2",
                "conversationId": conversation_id,
                "status": "blocked",
                "assistantMessage": "I could not launch the supervisor workflow because the entry payload failed validation.",
                "fallbackReason": reason,
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
