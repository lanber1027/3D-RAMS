from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import HTTPException

from .config import RuntimeConfig


_SESSIONS: dict[str, dict[str, Any]] = {}
_MAX_TURNS = 12
_MAX_TURN_TEXT = 1200


def create_session(*, tester_alias: str | None, access_label: str, config: RuntimeConfig) -> dict[str, Any]:
    now = _now_iso()
    expires_at = int(time.time()) + max(config.session_retention_days, 1) * 86400
    session = {
        "sessionId": f"session-{uuid.uuid4().hex[:16]}",
        "testerAlias": tester_alias,
        "accessLabel": access_label,
        "createdAt": now,
        "updatedAt": now,
        "expiresAt": expires_at,
        "runs": [],
        "uploads": [],
        "conversationTurns": [],
        "workingMemory": _default_working_memory(),
        "storageMode": "memory",
    }
    if config.dynamodb_session_table:
        session["storageMode"] = "dynamodb" if _write_dynamodb_session(session, config) else "memory-fallback"
    _SESSIONS[session["sessionId"]] = session
    return session


def get_session(session_id: str, config: RuntimeConfig | None = None) -> dict[str, Any]:
    session = _SESSIONS.get(session_id)
    if not session and config and config.dynamodb_session_table:
        session = _read_dynamodb_session(session_id, config)
        if session:
            _SESSIONS[session_id] = session
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    return session


def add_upload(session_id: str, upload: dict[str, Any], config: RuntimeConfig) -> None:
    session = get_session(session_id, config)
    session["uploads"].append(_stored_upload(upload))
    session["updatedAt"] = _now_iso()
    _persist_session(session, config)


def add_run(session_id: str, run_summary: dict[str, Any], config: RuntimeConfig) -> None:
    session = get_session(session_id, config)
    session["runs"].append(run_summary)
    memory = session.setdefault("workingMemory", _default_working_memory())
    memory["activeRunId"] = run_summary.get("runId") or memory.get("activeRunId")
    memory["latestRunStatus"] = run_summary.get("status") or memory.get("latestRunStatus")
    memory["latestSafetyLevel"] = run_summary.get("safetyLevel") or memory.get("latestSafetyLevel")
    memory["latestBriefingMode"] = run_summary.get("briefingMode") or memory.get("latestBriefingMode")
    session["updatedAt"] = _now_iso()
    _persist_session(session, config)


def add_conversation_turn(
    session_id: str,
    *,
    role: str,
    text: str,
    config: RuntimeConfig,
    metadata: dict[str, Any] | None = None,
) -> None:
    session = get_session(session_id, config)
    turns = session.setdefault("conversationTurns", [])
    turns.append(
        {
            "role": role,
            "text": _truncate(text),
            "metadata": _safe_metadata(metadata or {}),
            "timestamp": _now_iso(),
        }
    )
    del turns[:-_MAX_TURNS]
    memory = session.setdefault("workingMemory", _default_working_memory())
    if role == "assistant":
        memory["latestAssistantMessage"] = _truncate(text)
    elif role == "user":
        memory["latestUserMessage"] = _truncate(text)
    session["updatedAt"] = _now_iso()
    _persist_session(session, config)


def update_working_memory(session_id: str, config: RuntimeConfig, **updates: Any) -> dict[str, Any]:
    session = get_session(session_id, config)
    memory = session.setdefault("workingMemory", _default_working_memory())
    memory.update(_safe_metadata(updates))
    session["updatedAt"] = _now_iso()
    _persist_session(session, config)
    return memory


def public_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessionId": session["sessionId"],
        "testerAlias": session.get("testerAlias"),
        "accessLabel": session.get("accessLabel"),
        "createdAt": session.get("createdAt"),
        "updatedAt": session.get("updatedAt"),
        "expiresAt": session.get("expiresAt"),
        "runs": session.get("runs", []),
        "uploads": [_stored_upload(upload) for upload in session.get("uploads", [])],
        "conversationTurns": session.get("conversationTurns", []),
        "workingMemory": session.get("workingMemory", _default_working_memory()),
        "storageMode": session.get("storageMode", "memory"),
    }


def _stored_upload(upload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in upload.items()
        if key not in {"uploadUrl", "fields"}
    }


def _default_working_memory() -> dict[str, Any]:
    return {
        "runtimeTarget": "agentcore-ready",
        "runtimeStatus": "lambda-adapter-active",
        "activeRunId": None,
        "latestRunStatus": None,
        "latestAssistantMessage": None,
        "latestUserMessage": None,
        "pendingUserAction": None,
        "confirmedLocation": None,
        "latestLocationResolution": None,
        "latestReviewSummary": None,
        "latestSafetyLevel": None,
        "latestBriefingMode": None,
    }


def _truncate(text: str) -> str:
    return " ".join(str(text).split())[:_MAX_TURN_TEXT]


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked = {"accessCode", "accessToken", "token", "secret", "uploadUrl", "fields"}
    return {key: value for key, value in metadata.items() if key not in blocked}


def _persist_session(session: dict[str, Any], config: RuntimeConfig) -> None:
    if not config.dynamodb_session_table:
        return
    if _write_dynamodb_session(session, config):
        session["storageMode"] = "dynamodb"
    elif session.get("storageMode") == "dynamodb":
        session["storageMode"] = "memory-fallback"


def _write_dynamodb_session(session: dict[str, Any], config: RuntimeConfig) -> bool:
    """Write session trace to DynamoDB when configured; memory remains fallback."""
    if not config.dynamodb_session_table:
        return False
    try:
        import boto3

        resource = boto3.resource("dynamodb", region_name=config.aws_region)
        table = resource.Table(config.dynamodb_session_table)
        table.put_item(Item=session)
        return True
    except Exception:
        return False


def _read_dynamodb_session(session_id: str, config: RuntimeConfig) -> dict[str, Any] | None:
    if not config.dynamodb_session_table:
        return None
    try:
        import boto3

        resource = boto3.resource("dynamodb", region_name=config.aws_region)
        table = resource.Table(config.dynamodb_session_table)
        response = table.get_item(Key={"sessionId": session_id})
        item = response.get("Item")
        return item if isinstance(item, dict) else None
    except Exception:
        return None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
