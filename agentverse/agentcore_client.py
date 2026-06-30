from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from urllib import error, request


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
    url, host, path = agentcore_url(runtime_arn, region)
    body = json.dumps(payload).encode("utf-8")
    headers = signed_headers(
        method="POST",
        path=path,
        host=host,
        payload=body,
        session_id=session_id or _session_id(runtime_arn),
        user_id=user_id or "3d-rams-cloud-proxy",
        region=region,
    )
    return _post_text(url=url, body=body, headers=headers, timeout=timeout)


def agentcore_url(runtime_arn: str, region: str) -> tuple[str, str, str]:
    host = f"{AWS_SERVICE}.{region}.amazonaws.com"
    path = f"/runtimes/{quote(runtime_arn, safe='')}/invocations"
    return f"https://{host}{path}", host, path


def _post_text(*, url: str, body: bytes, headers: dict[str, str], timeout: int) -> str:
    try:
        import requests
    except ImportError:
        return _post_text_urllib(url=url, body=body, headers=headers, timeout=timeout)

    response = requests.post(url, data=body, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise AgentCoreInvokeError(f"AgentCore returned HTTP {response.status_code}: {response.text[:500]}")
    return response.text


def _post_text_urllib(*, url: str, body: bytes, headers: dict[str, str], timeout: int) -> str:
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise AgentCoreInvokeError(f"AgentCore returned HTTP {exc.code}: {text[:500]}") from exc


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
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise AgentCoreInvokeError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required for AgentCore signing.")
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
    text = extract_text_body(raw_body)
    if not text:
        return None
    return _json_object(text)


def extract_text_body(raw_body: str) -> str:
    direct = _json_object(raw_body)
    if direct is not None:
        return _text_from_json(direct)

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
        return None
    return parsed if isinstance(parsed, dict) else None


def _text_from_json(payload: dict[str, Any]) -> str:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    delivery = output.get("delivery") if isinstance(output.get("delivery"), dict) else {}
    summary = delivery.get("customerSummary") if isinstance(delivery.get("customerSummary"), dict) else {}
    if output.get("assistantMessage"):
        return str(output["assistantMessage"])
    if summary.get("headline"):
        return str(summary["headline"])
    if output:
        return json.dumps(output, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    region_key = _sign(date_key, region)
    service_key = _sign(region_key, service)
    return _sign(service_key, "aws4_request")


def _session_id(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"3d-rams-agentcore:{seed}"))
