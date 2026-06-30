import os
import uuid
from datetime import datetime, timezone

from agentcore_client import invoke_runtime_text
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)


AGENTCORE_RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")
ADAPTER_VERSION = "agentcore-agentverse-adapter-v2"

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


def _session_id(sender: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"agentverse:{ADAPTER_VERSION}:3d-rams:{sender}"))


def invoke_agentcore(prompt: str, sender: str) -> str:
    session_id = _session_id(sender)
    user_id = f"agentverse-{sender[-48:]}"
    return invoke_runtime_text(
        runtime_arn=AGENTCORE_RUNTIME_ARN,
        payload={"prompt": prompt},
        session_id=session_id,
        user_id=user_id,
        region=AWS_REGION,
        timeout=60,
    )


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
            reply = invoke_agentcore(prompt, sender)
        except Exception as exc:  # noqa: BLE001 - return a safe user-facing adapter failure.
            ctx.logger.exception("AgentCore invocation failed")
            reply = f"AgentCore invocation failed: {type(exc).__name__}"

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
