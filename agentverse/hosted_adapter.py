import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from agentcore_client import extract_json_body, extract_text_body, invoke_runtime_text
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)


AGENTCORE_RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")
ADAPTER_VERSION = "agentcore-agentverse-adapter-v3"
_PENDING_INTAKES = {}
CASE_REF_RE = re.compile(r"(?:^|\s)/case/(case_[A-Za-z0-9_-]+)\b")

agent = Agent()
chat = Protocol(spec=chat_protocol_spec)


def _now():
    return datetime.now(timezone.utc)


def _message_text(message: ChatMessage) -> str:
    parts = []
    for item in message.content:
        if getattr(item, "type", None) == "text" and getattr(item, "text", None):
            parts.append(item.text)
    return "\n".join(parts).strip()


def _session_id(sender: str, message: Optional[ChatMessage] = None) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"agentverse:{ADAPTER_VERSION}:3d-rams:{_session_seed(sender, message)}"))


def invoke_agentcore(prompt: str, sender: str, message: Optional[ChatMessage] = None) -> str:
    session_id = _session_id(sender, message)
    user_id = f"agentverse-{sender[-48:]}"
    case_id = _case_id_from_prompt(prompt)
    payload = _report_lookup_payload(case_id, session_id) if case_id else _entry_turn_payload(prompt, session_id)
    if payload["confirmedByUser"] and session_id in _PENDING_INTAKES:
        payload["intake"] = _PENDING_INTAKES[session_id]

    response_text = invoke_runtime_text(
        runtime_arn=AGENTCORE_RUNTIME_ARN,
        payload=payload,
        session_id=session_id,
        user_id=user_id,
        region=AWS_REGION,
        timeout=60,
    )
    _remember_pending_intake(session_id, response_text)
    reply = extract_text_body(response_text) or response_text
    return _append_full_report_link(reply, response_text, session_id)


def _session_seed(sender: str, message: Optional[ChatMessage]) -> str:
    for key in ("conversationId", "conversation_id", "sessionId", "session_id", "threadId", "thread_id"):
        value = _find_message_value(message, key)
        if value:
            return str(value)
    return sender


def _find_message_value(value, key: str):
    if value is None:
        return None
    if isinstance(value, dict):
        if value.get(key):
            return value[key]
        for child in value.values():
            found = _find_message_value(child, key)
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for child in value:
            found = _find_message_value(child, key)
            if found:
                return found
        return None
    if hasattr(value, key) and getattr(value, key):
        return getattr(value, key)
    if hasattr(value, "model_dump"):
        return _find_message_value(value.model_dump(), key)
    return None


def _entry_turn_payload(prompt: str, session_id: str) -> dict:
    return {
        "entryTurn": True,
        "caller": "agentverse",
        "conversationId": session_id,
        "entryAgentId": "@3d-rams",
        "confirmedByUser": _looks_like_confirmation(prompt),
        "message": prompt,
        "reportAccess": _report_access("", session_id),
        "runtimeOptions": {
            "fixturePack": "public-lambeth-thames",
            "useBedrock": True,
            "includePlanningFixture": True,
            "simulateMapFailure": False,
        },
    }


def _report_lookup_payload(case_id: str, session_id: str) -> dict:
    return {
        "operation": "getReport",
        "caller": "agentverse",
        "conversationId": session_id,
        "entryAgentId": "@3d-rams",
        "caseId": case_id,
        "confirmedByUser": False,
        "reportAccess": _report_access(case_id, session_id),
    }


def _report_access(case_id: str, session_id: str) -> dict:
    access = {
        "schemaVersion": "3d-rams.report-access.v1",
        "mode": "asi_session",
        "source": "AGENTVERSE",
        "sessionId": session_id,
    }
    if case_id:
        access["caseId"] = case_id
        access["authorizedCaseIds"] = [case_id]
    return access


def _case_id_from_prompt(prompt: str):
    match = CASE_REF_RE.search(prompt)
    return match.group(1) if match else None


def _append_full_report_link(reply: str, response_text: str, session_id: str) -> str:
    base_url = os.getenv("PUBLIC_FRONTEND_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return reply
    response = extract_json_body(response_text)
    output = response.get("output") if isinstance(response, dict) else {}
    case_id = output.get("caseId") if isinstance(output, dict) else None
    if not case_id:
        return reply
    url = f"{base_url}/case/{case_id}?{urlencode({'reportSessionId': session_id})}"
    if url in reply:
        return reply
    return f"{reply}\n\nFull report: {url}"


def _looks_like_confirmation(prompt: str) -> bool:
    normalized = re.sub(r"^(?:@\S+\s+)+", "", prompt.strip().lower())
    return bool(
        normalized in {"yes", "yes please", "confirm", "confirmed", "launch", "go", "go ahead"}
        or re.search(r"^(please\s+)?(confirm|confirmed|proceed|go ahead|launch)\b", normalized)
        or re.search(r"\b(confirm(ed)? and launch|please launch)\b", normalized)
    )


def _remember_pending_intake(session_id: str, response_text: str) -> None:
    response = extract_json_body(response_text)
    if response is None:
        return
    output = response.get("output") if isinstance(response, dict) else {}
    entry_agent = output.get("entryAgent") if isinstance(output, dict) else {}
    if not isinstance(entry_agent, dict):
        return
    if entry_agent.get("status") == "confirmation_required" and isinstance(entry_agent.get("intake"), dict):
        _PENDING_INTAKES[session_id] = entry_agent["intake"]
        return
    if output.get("caseId"):
        _PENDING_INTAKES.pop(session_id, None)


@chat.on_message(model=ChatMessage)
async def handle_chat_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(
            acknowledged_msg_id=msg.msg_id,
            timestamp=_now(),
        ),
    )

    prompt = _message_text(msg)
    if not prompt:
        reply = "Please send a text message."
    else:
        try:
            reply = invoke_agentcore(prompt, sender, msg)
        except Exception as exc:  # noqa: BLE001 - return a safe user-facing adapter failure.
            ctx.logger.exception("AgentCore invocation failed")
            detail = str(exc).strip()
            reply = f"AgentCore invocation failed: {type(exc).__name__}"
            if detail:
                reply = f"{reply}: {detail[:700]}"

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=_now(),
            msg_id=uuid.uuid4(),
            content=[TextContent(text=reply)],
        ),
    )


@chat.on_message(model=ChatAcknowledgement)
async def handle_chat_acknowledgement(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"Received chat acknowledgement from {sender}: {msg.acknowledged_msg_id}")


agent.include(chat)


if __name__ == "__main__":
    agent.run()
