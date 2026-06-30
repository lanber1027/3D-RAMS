from __future__ import annotations

import json
import os
import uuid
from typing import Any

from agentcore_client import invoke_runtime_json
from supervisor_adapter import AdapterValidationError, build_agentcore_invocation, build_delivery_payload

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
) -> dict[str, Any]:
    payload = payload or {}
    if _is_report_lookup_payload(payload):
        return _handle_report_lookup(payload, supervisor_runtime_arn=supervisor_runtime_arn, invoke_runtime=invoke_runtime)

    if not _is_structured_frontend_payload(payload):
        raise AdapterValidationError("Structured entry payload must include frontendInvoke or intake.")

    runtime_arn = supervisor_runtime_arn or os.getenv("RAMS_SUPERVISOR_RUNTIME_ARN")
    if not runtime_arn:
        raise AdapterValidationError("RAMS_SUPERVISOR_RUNTIME_ARN is required for cloud supervisor handoff.")

    invocation = build_agentcore_invocation(payload)
    conversation_id = str(payload.get("conversationId") or payload.get("sessionId") or "3d-rams-entry-session")
    user_id = str(payload.get("userId") or "3d-rams-entry-agent")
    agentcore_response = invoke_runtime(
        runtime_arn=runtime_arn,
        payload=invocation,
        session_id=_agentcore_session_id(conversation_id),
        user_id=user_id,
    )
    delivery = build_delivery_payload(agentcore_response, entry_payload=payload)
    output = agentcore_response.get("output") if isinstance(agentcore_response.get("output"), dict) else {}
    return {
        "output": {
            "caseId": output.get("caseId") or delivery.get("caseId"),
            "delivery": delivery,
            "run": output.get("run"),
            "structuredReport": output.get("structuredReport"),
            "reportStatus": output.get("reportStatus") or delivery.get("status"),
            "workflowMode": output.get("workflowMode") or delivery.get("workflowMode"),
            "persistence": output.get("persistence"),
            "entryAgent": {
                "mode": "cloud-supervisor-handoff",
                "adapterVersion": "asi-one-entry-agent-v1",
                "conversationId": conversation_id,
                "caseId": output.get("caseId") or delivery.get("caseId"),
            },
        }
    }


def invoke_local(
    payload: dict[str, Any] | None = None,
    *,
    supervisor_invoker=None,
) -> dict[str, Any]:
    if payload and not _is_structured_frontend_payload(payload) and "input" in payload:
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


if app is not None:

    @app.entrypoint
    async def invoke(payload: dict[str, Any], context: Any):
        log.info("Invoking 3D-RAMS AgentVerse entry runtime.")

        if _is_structured_frontend_payload(payload) or _is_report_lookup_payload(payload):
            result = handle_invocation(payload)
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


def _is_structured_frontend_payload(payload: dict[str, Any]) -> bool:
    return bool(payload.get("frontendInvoke") or payload.get("intake"))


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
    response = invoke_runtime(
        runtime_arn=runtime_arn,
        payload={"input": {"operation": "getReport", "caseId": case_id}},
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


def _text_delta_event(text: str) -> dict[str, Any]:
    return {"event": {"contentBlockDelta": {"delta": {"text": text}}}}


def _agentcore_session_id(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"3d-rams-entry-agent:{seed}"))


if __name__ == "__main__":
    if app is None:
        raise RuntimeError("bedrock-agentcore and Strands dependencies are required to run the entry runtime server.")
    app.run()
