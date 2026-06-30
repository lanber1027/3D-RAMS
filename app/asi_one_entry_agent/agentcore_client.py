from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


AWS_SERVICE = "bedrock-agentcore"


class AgentCoreInvokeError(RuntimeError):
    pass


def invoke_runtime_json(
    *,
    runtime_arn: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    user_id: str | None = None,
    region: str | None = None,
    timeout: int = 90,
) -> dict[str, Any]:
    raw = invoke_runtime_text(
        runtime_arn=runtime_arn,
        payload=payload,
        session_id=session_id,
        user_id=user_id,
        region=region,
        timeout=timeout,
    )
    parsed = extract_json_body(raw)
    if parsed is None:
        raise AgentCoreInvokeError("AgentCore response did not contain JSON.")
    return parsed


def invoke_runtime_text(
    *,
    runtime_arn: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    user_id: str | None = None,
    region: str | None = None,
    timeout: int = 90,
) -> str:
    if not runtime_arn:
        raise AgentCoreInvokeError("runtime_arn is required.")

    region = region or os.getenv("AWS_REGION", "eu-west-2")
    if os.getenv("AGENTCORE_CLIENT_TRANSPORT", "botocore").strip().lower() != "requests":
        botocore_body = _invoke_runtime_text_with_botocore(
            runtime_arn=runtime_arn,
            payload=payload,
            session_id=session_id,
            user_id=user_id,
            region=region,
        )
        if botocore_body is not None:
            return botocore_body

    try:
        import requests
    except ImportError as exc:
        raise AgentCoreInvokeError("requests is required to invoke AgentCore runtimes.") from exc

    url, host, path = agentcore_url(runtime_arn, region)
    body = json.dumps(payload).encode("utf-8")
    response = requests.post(
        url,
        data=body,
        headers=signed_headers(
            method="POST",
            path=path,
            host=host,
            payload=body,
            session_id=_runtime_session_id(session_id, runtime_arn),
            user_id=user_id or "3d-rams-cloud-proxy",
            region=region,
        ),
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise AgentCoreInvokeError(f"AgentCore returned HTTP {response.status_code}: {response.text[:500]}")
    return response.text


def _invoke_runtime_text_with_botocore(
    *,
    runtime_arn: str,
    payload: dict[str, Any],
    session_id: str | None,
    user_id: str | None,
    region: str,
) -> str | None:
    try:
        import botocore.session
        from botocore.exceptions import BotoCoreError, ClientError, UnknownServiceError
    except ImportError:
        return None

    body = json.dumps(payload).encode("utf-8")
    session = botocore.session.get_session()
    try:
        client = session.create_client(AWS_SERVICE, region_name=region)
    except UnknownServiceError:
        return None

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=_runtime_session_id(session_id, runtime_arn),
            runtimeUserId=user_id or "3d-rams-cloud-proxy",
            contentType="application/json",
            accept="application/json",
            payload=body,
        )
    except (BotoCoreError, ClientError) as exc:
        raise AgentCoreInvokeError(f"AgentCore botocore invoke failed: {exc}") from exc

    status_code = int(response.get("statusCode") or 200)
    response_body = response.get("response")
    if hasattr(response_body, "read"):
        response_body = response_body.read()
    if isinstance(response_body, bytes):
        text = response_body.decode("utf-8")
    else:
        text = str(response_body or "")
    if status_code >= 400:
        raise AgentCoreInvokeError(f"AgentCore returned HTTP {status_code}: {text[:500]}")
    return text


def agentcore_url(runtime_arn: str, region: str) -> tuple[str, str, str]:
    host = f"{AWS_SERVICE}.{region}.amazonaws.com"
    path = f"/runtimes/{quote(runtime_arn, safe='')}/invocations"
    return f"https://{host}{path}", host, path


def signed_headers(
    *,
    method: str,
    path: str,
    host: str,
    payload: bytes,
    session_id: str,
    user_id: str,
    region: str,
) -> dict[str, str]:
    credentials = _credentials()
    access_key = credentials["access_key"]
    secret_key = credentials["secret_key"]
    session_token = credentials.get("token")

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
    signed_header_list = ";".join(signed_header_names)
    canonical_uri = quote(path, safe="/~")
    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            "",
            canonical_headers,
            signed_header_list,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/{AWS_SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _signature_key(secret_key, date_stamp, region, AWS_SERVICE)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_header_list}, Signature={signature}"
    )
    return headers


def extract_json_body(raw_body: str) -> dict[str, Any] | None:
    direct = _json_object(raw_body)
    if direct is not None:
        return direct
    text = _stream_text_body(raw_body)
    if not text:
        return None
    return _json_object(text)


def extract_text_body(raw_body: str) -> str:
    direct = _json_object(raw_body)
    if direct is not None:
        return _text_from_json(direct)

    text = _stream_text_body(raw_body)
    parsed = _json_object(text) if text else None
    if parsed is not None:
        return _text_from_json(parsed)
    return text


def _stream_text_body(raw_body: str) -> str:
    chunks: list[str] = []
    for line in raw_body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line.removeprefix("data: "))
        except json.JSONDecodeError:
            continue
        if "error" in data:
            raise AgentCoreInvokeError(f"AgentCore stream error: {json.dumps(data, ensure_ascii=False)}")
        event = data.get("event", data)
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            chunks.append(str(delta["text"]))
    return "".join(chunks).strip()


def _json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return _python_dict_repr(value)
    if isinstance(parsed, str):
        return _json_object(parsed) or _python_dict_repr(parsed)
    return parsed if isinstance(parsed, dict) else None


def _python_dict_repr(value: str) -> dict[str, Any] | None:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _text_from_json(payload: dict[str, Any]) -> str:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    entry_agent = output.get("entryAgent") if isinstance(output.get("entryAgent"), dict) else {}
    delivery = output.get("delivery") if isinstance(output.get("delivery"), dict) else {}
    summary = delivery.get("customerSummary") if isinstance(delivery.get("customerSummary"), dict) else {}
    if output.get("assistantMessage"):
        return str(output["assistantMessage"])
    if summary.get("headline"):
        return str(summary["headline"])
    if entry_agent.get("assistantMessage"):
        return _entry_agent_message(entry_agent)
    if output:
        return json.dumps(output, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


def _entry_agent_message(entry_agent: dict[str, Any]) -> str:
    message = str(entry_agent["assistantMessage"])
    questions = entry_agent.get("clarifyingQuestions")
    if not isinstance(questions, list) or not questions:
        return message
    question_lines = [f"- {question}" for question in questions if question]
    if not question_lines:
        return message
    return f"{message}\n\n" + "\n".join(question_lines)


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    region_key = _sign(date_key, region)
    service_key = _sign(region_key, service)
    return _sign(service_key, "aws4_request")


def _session_id(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"3d-rams-agentcore:{seed}"))


def _runtime_session_id(value: str | None, fallback_seed: str) -> str:
    raw = str(value or "").strip()
    sanitized = re.sub(r"[^A-Za-z0-9-]+", "-", raw).strip("-")
    if len(sanitized) >= 33:
        return sanitized[:128]
    prefix = sanitized or "3d-rams-agentcore-session"
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"3d-rams-agentcore-session:{fallback_seed}:{raw}").hex
    return f"{prefix}-{suffix}"[:128]


def _credentials() -> dict[str, str | None]:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        return {
            "access_key": access_key,
            "secret_key": secret_key,
            "token": os.environ.get("AWS_SESSION_TOKEN"),
        }

    try:
        import botocore.session
    except ImportError as exc:
        raise AgentCoreInvokeError(
            "AWS credentials are required for AgentCore signing. Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY "
            "or run inside an AWS runtime with botocore credentials."
        ) from exc

    session = botocore.session.get_session()
    resolved = session.get_credentials()
    if not resolved:
        raise AgentCoreInvokeError("Could not resolve AWS credentials for AgentCore signing.")
    frozen = resolved.get_frozen_credentials()
    return {
        "access_key": frozen.access_key,
        "secret_key": frozen.secret_key,
        "token": frozen.token,
    }
