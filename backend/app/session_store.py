from __future__ import annotations

import re
import time
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from .config import RuntimeConfig


_SESSIONS: dict[str, dict[str, Any]] = {}
_MAX_TURNS = 12
_MAX_TURN_TEXT = 1200
_MAX_LLM_CONTEXT_TURNS = 6
_MAX_LLM_CONTEXT_STRING = 160
_SENSITIVE_CONTEXT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"https?://",
        r"\baccess\s*code\b",
        r"\b(access|api|secret|private|session|run)[\s_-]?(token|key|code|id)\b",
        r"\bsession-[a-z0-9-]{8,}\b",
        r"\brun-[a-z0-9-]{8,}\b",
        r"\b3drams-[a-z0-9-]{8,}\b",
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"\b[0-9a-f]{24,}\b",
    )
]


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


def llm_session_context(session: dict[str, Any]) -> dict[str, Any]:
    """Return bounded, public-safe session context for model prompts."""
    memory = session.get("workingMemory", _default_working_memory())
    confirmed_location = memory.get("confirmedLocation") or {}
    latest_location_resolution = memory.get("latestLocationResolution") or {}
    recent_turns = []
    for turn in session.get("conversationTurns", [])[-_MAX_LLM_CONTEXT_TURNS:]:
        metadata = turn.get("metadata") or {}
        route = metadata.get("route") or ("user_input" if metadata.get("routeInput") else None)
        recent_turns.append(
            {
                "role": turn.get("role"),
                "summary": _turn_summary(turn.get("role"), turn.get("text", "")),
                "route": route,
            }
        )
    return {
        "contextType": "bounded-session-summary",
        "privacyBoundary": "No raw turn text, access codes, upload URLs, raw files, session ids, or run ids are included.",
        "recentTurns": recent_turns,
        "workingMemory": {
            "pendingUserAction": memory.get("pendingUserAction"),
            "latestRunStatus": memory.get("latestRunStatus"),
            "latestSafetyLevel": memory.get("latestSafetyLevel"),
            "latestBriefingMode": memory.get("latestBriefingMode"),
            "latestRoute": memory.get("latestRoute"),
            "confirmedLocation": _location_summary(confirmed_location),
            "latestLocationResolution": _location_resolution_summary(latest_location_resolution),
            "latestReviewSummary": _review_summary(memory.get("latestReviewSummary")),
        },
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


def _turn_summary(role: Any, text: Any) -> dict[str, Any]:
    if role == "user":
        try:
            from .site_intent import parse_site_intent

            intent = parse_site_intent(str(text))
            coordinate = intent.get("coordinate")
            return {
                "kind": "user_site_intent",
                "siteName": _safe_context_string(intent.get("siteName")),
                "hasCoordinate": coordinate is not None,
                "coordinate": {"latitude": coordinate[0], "longitude": coordinate[1]} if coordinate else None,
                "postcode": _safe_context_string(intent.get("postcode"), max_length=12),
                "outcode": _safe_context_string(intent.get("outcode"), max_length=8),
                "nearestTown": _safe_context_string(intent.get("nearestTown")),
                "siteTypes": [_safe_context_string(item, max_length=40) for item in intent.get("siteTypes", [])],
                "activities": [_safe_context_string(item, max_length=40) for item in intent.get("activities", [])],
                "visitDate": _safe_context_string(intent.get("visitDate"), max_length=40),
                "unsafeIntent": intent.get("unsafeIntent"),
                "knownPublicFixture": intent.get("knownPublicFixture"),
            }
        except Exception:
            return {"kind": "user_message", "summaryUnavailable": True}
    return {
        "kind": "assistant_message",
        "containsClarificationQuestion": "?" in str(text),
    }


def _location_summary(location: Any) -> dict[str, Any] | None:
    if not isinstance(location, dict) or not location:
        return None
    return {
        "name": _safe_context_string(location.get("name") or location.get("label")),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "source": _safe_context_string(location.get("source"), max_length=60),
        "confidence": _safe_context_string(location.get("confidence"), max_length=40),
        "dataMode": _safe_context_string(location.get("dataMode"), max_length=40),
    }


def _location_resolution_summary(location_resolution: Any) -> dict[str, Any] | None:
    if not isinstance(location_resolution, dict) or not location_resolution:
        return None
    candidates = location_resolution.get("locationCandidates") or []
    return {
        "siteName": _safe_context_string(location_resolution.get("siteName")),
        "needsLocationConfirmation": location_resolution.get("needsLocationConfirmation"),
        "nextStage": _safe_context_string(location_resolution.get("nextStage"), max_length=60),
        "candidateCount": len(candidates) if isinstance(candidates, list) else 0,
    }


def _review_summary(review: Any) -> dict[str, Any] | None:
    if not isinstance(review, dict) or not review:
        return None
    return {
        "status": _safe_context_string(review.get("status"), max_length=60),
        "headline": _safe_context_string(review.get("headline")),
        "generationMode": _safe_context_string(review.get("generationMode"), max_length=60),
    }


def _safe_context_string(value: Any, *, max_length: int = _MAX_LLM_CONTEXT_STRING) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if any(pattern.search(text) for pattern in _SENSITIVE_CONTEXT_PATTERNS):
        return None
    return text[:max_length]


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
        table.put_item(Item=_to_dynamodb_item(session))
        return True
    except Exception:
        return False


def _to_dynamodb_item(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _to_dynamodb_item(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_dynamodb_item(item) for item in value]
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def _read_dynamodb_session(session_id: str, config: RuntimeConfig) -> dict[str, Any] | None:
    if not config.dynamodb_session_table:
        return None
    try:
        import boto3

        resource = boto3.resource("dynamodb", region_name=config.aws_region)
        table = resource.Table(config.dynamodb_session_table)
        response = table.get_item(Key={"sessionId": session_id})
        item = response.get("Item")
        return _from_dynamodb_item(item) if isinstance(item, dict) else None
    except Exception:
        return None


def _from_dynamodb_item(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _from_dynamodb_item(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_dynamodb_item(item) for item in value]
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
