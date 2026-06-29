import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)


AGENTCORE_RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")
AWS_SERVICE = "bedrock-agentcore"
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


def _extract_text_from_agentcore_stream(raw_body: str) -> str:
    chunks = []
    for line in raw_body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line.removeprefix("data: "))
        except json.JSONDecodeError:
            continue

        if "error" in data:
            return f"{ADAPTER_VERSION}: AgentCore stream error: {json.dumps(data, ensure_ascii=False)}"

        event = data.get("event", data)
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            chunks.append(delta["text"])

    return "".join(chunks).strip() or f"{ADAPTER_VERSION}: no text response received from AgentCore."


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    region_key = _sign(date_key, region)
    service_key = _sign(region_key, service)
    return _sign(service_key, "aws4_request")


def _agentcore_url() -> tuple[str, str, str]:
    host = f"{AWS_SERVICE}.{AWS_REGION}.amazonaws.com"
    path = f"/runtimes/{quote(AGENTCORE_RUNTIME_ARN, safe='')}/invocations"
    return f"https://{host}{path}", host, path


def _signed_headers(
    method: str,
    path: str,
    host: str,
    payload: bytes,
    session_id: str,
    user_id: str,
) -> dict[str, str]:
    access_key = os.environ["AWS_ACCESS_KEY_ID"]
    secret_key = os.environ["AWS_SECRET_ACCESS_KEY"]
    session_token = os.environ.get("AWS_SESSION_TOKEN")

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "x-amzn-bedrock-agentcore-runtime-session-id": session_id,
        "x-amzn-bedrock-agentcore-runtime-user-id": user_id,
    }
    if session_token:
        headers["x-amz-security-token"] = session_token

    signed_header_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in signed_header_names)
    signed_headers = ";".join(signed_header_names)
    canonical_uri = quote(path, safe="/~")
    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    credential_scope = f"{date_stamp}/{AWS_REGION}/{AWS_SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _signature_key(secret_key, date_stamp, AWS_REGION, AWS_SERVICE)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def invoke_agentcore(prompt: str, sender: str) -> str:
    url, host, path = _agentcore_url()
    session_id = _session_id(sender)
    user_id = f"agentverse-{sender[-48:]}"
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    response = requests.post(
        url,
        data=payload,
        headers=_signed_headers("POST", path, host, payload, session_id, user_id),
        timeout=60,
    )
    if response.status_code >= 400:
        return f"AgentCore returned HTTP {response.status_code}: {response.text[:500]}"
    return _extract_text_from_agentcore_stream(response.text)


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
