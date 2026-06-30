from __future__ import annotations

import json
import os
import uuid
from typing import Any

from agentcore_client import invoke_runtime_json


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = _method(event)
    path = _path(event)
    if method == "OPTIONS":
        return _response({}, status=204)
    if method == "GET" and path.rstrip("/") == "/health":
        return _response({"status": "ok", "service": "3d-rams-agentcore-proxy"})
    if method != "POST" or path.rstrip("/") not in {"", "/invoke"}:
        return _response({"error": "not_found"}, status=404)

    try:
        payload = _json_body(event)
        runtime_arn = os.environ["AGENTCORE_RUNTIME_ARN"]
        conversation_id = str(payload.get("conversationId") or payload.get("sessionId") or "frontend-demo-session")
        agentcore_session_id = _agentcore_session_id(conversation_id)
        result = invoke_runtime_json(
            runtime_arn=runtime_arn,
            payload=_payload_with_agentcore_session(payload, agentcore_session_id),
            session_id=agentcore_session_id,
            user_id=os.getenv("AGENTCORE_PROXY_USER_ID", "3d-rams-frontend"),
            timeout=int(os.getenv("AGENTCORE_PROXY_TIMEOUT", "120")),
        )
        return _response(result)
    except Exception as exc:  # noqa: BLE001 - return clear proxy errors to the demo UI.
        return _response({"error": type(exc).__name__, "message": str(exc)}, status=502)


def _method(event: dict[str, Any]) -> str:
    return str(
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    ).upper()


def _path(event: dict[str, Any]) -> str:
    return str(
        event.get("rawPath")
        or event.get("path")
        or event.get("requestContext", {}).get("http", {}).get("path")
        or ""
    )


def _json_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("Proxy payload must be a JSON object.")
    return parsed


def _response(payload: dict[str, Any], *, status: int = 200) -> dict[str, Any]:
    headers = {
        "content-type": "application/json",
    }
    if os.getenv("AGENTCORE_PROXY_EMIT_CORS_HEADERS", "").lower() in {"1", "true", "yes"}:
        headers.update(
            {
                "access-control-allow-origin": os.getenv("AGENTCORE_PROXY_ALLOWED_ORIGIN", "*"),
                "access-control-allow-methods": "GET,POST,OPTIONS",
                "access-control-allow-headers": "content-type,authorization",
            }
        )

    return {
        "statusCode": status,
        "headers": headers,
        "body": "" if status == 204 else json.dumps(payload),
    }


def _agentcore_session_id(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"3d-rams-frontend-proxy:{seed}"))


def _payload_with_agentcore_session(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    if len(str(payload.get("conversationId") or "")) >= 33:
        return payload
    normalized = dict(payload)
    if payload.get("conversationId"):
        normalized["frontendConversationId"] = payload["conversationId"]
    normalized["conversationId"] = session_id
    return normalized
