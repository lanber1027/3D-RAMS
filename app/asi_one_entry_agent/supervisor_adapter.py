from __future__ import annotations

import os
from typing import Any


ADAPTER_VERSION = "agentverse-agentcore-adapter-v0"
REPORT_ACCESS_SCHEMA_VERSION = "3d-rams.report-access.v1"


class AdapterValidationError(ValueError):
    """Raised when an entry-agent payload is not ready for AgentCore launch."""


def build_agentcore_invocation(entry_payload: dict[str, Any]) -> dict[str, Any]:
    payload = _require_mapping(entry_payload, "entry_payload")
    intake = _require_mapping(payload.get("intake"), "intake")
    runtime_options = payload.get("runtimeOptions") or {}
    if not isinstance(runtime_options, dict):
        raise AdapterValidationError("runtimeOptions must be an object when provided.")

    confirmed = payload.get("confirmedByUser")
    if confirmed is not True:
        raise AdapterValidationError("confirmedByUser must be true before invoking AgentCore.")

    case_id = _optional_text(payload.get("caseId"))
    if not case_id:
        raise AdapterValidationError("caseId is required before invoking AgentCore.")

    location_text = _optional_text(intake.get("locationText"))
    location_candidate = intake.get("locationCandidate") or {}
    if location_candidate and not isinstance(location_candidate, dict):
        raise AdapterValidationError("intake.locationCandidate must be an object when provided.")

    has_coordinate = location_candidate.get("lat") is not None and location_candidate.get("lng") is not None
    if not location_text and not has_coordinate:
        raise AdapterValidationError("intake requires locationText or locationCandidate lat/lng.")

    area_scope = intake.get("areaScope")
    if not isinstance(area_scope, dict) or not area_scope:
        raise AdapterValidationError("intake.areaScope is required before invoking AgentCore.")

    user_goal = _optional_text(intake.get("userGoal"))
    if not user_goal:
        raise AdapterValidationError("intake.userGoal is required before invoking AgentCore.")

    materials = intake.get("materials") or []
    if not isinstance(materials, list):
        raise AdapterValidationError("intake.materials must be a list when provided.")
    safe_materials = _safe_material_references(materials, case_id=case_id)
    identity_context = _identity_context(payload)

    report_access = build_report_access_context(payload, case_id)
    input_payload: dict[str, Any] = {
        "caseId": case_id,
        "siteName": _site_name(location_text, location_candidate),
        "goal": user_goal,
        "areaScope": area_scope,
        "additionalRequest": _additional_request(intake),
        "materials": safe_materials,
        "upstream": {
            "caseId": case_id,
            "source": _upstream_source(payload),
            "adapterVersion": ADAPTER_VERSION,
            "conversationId": _optional_text(payload.get("conversationId")),
            "entryAgentId": _optional_text(payload.get("entryAgentId")),
            "confirmedByUser": True,
            "areaScope": area_scope,
            "locationConfidence": location_candidate.get("confidence"),
            "materialCount": len(safe_materials),
            "reportAccess": report_access,
        },
    }
    if identity_context:
        input_payload["upstream"]["identity"] = identity_context

    if has_coordinate:
        input_payload["latitude"] = float(location_candidate["lat"])
        input_payload["longitude"] = float(location_candidate["lng"])
    if location_text:
        input_payload["locationText"] = location_text

    for key in ("fixturePack", "useBedrock", "includePlanningFixture", "simulateMapFailure"):
        if key in runtime_options:
            input_payload[key] = runtime_options[key]

    return {"input": input_payload}


def build_report_access_context(
    payload: dict[str, Any],
    case_id: str,
    *,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    explicit = payload.get("reportAccess") or payload.get("reportAccessContext") or payload.get("accessContext") or {}
    if explicit and not isinstance(explicit, dict):
        raise AdapterValidationError("reportAccess must be an object when provided.")

    access = _copy_access_fields(explicit)
    source = _upstream_source(payload)
    access["schemaVersion"] = access.get("schemaVersion") or REPORT_ACCESS_SCHEMA_VERSION
    access["caseId"] = case_id
    access["source"] = access.get("source") or source
    access["mode"] = _optional_text(access.get("mode")) or _default_report_access_mode(source)

    authorized_cases = access.get("authorizedCaseIds")
    if not isinstance(authorized_cases, list):
        authorized_cases = []
    authorized_cases = [str(item) for item in authorized_cases if str(item).strip()]
    if case_id not in authorized_cases:
        authorized_cases.append(case_id)
    access["authorizedCaseIds"] = authorized_cases

    if not access.get("sessionId"):
        access["sessionId"] = _optional_text(conversation_id or payload.get("conversationId") or payload.get("sessionId"))
    if not access.get("subjectId") and user_id and user_id != "3d-rams-entry-agent":
        access["subjectId"] = user_id

    return {key: value for key, value in access.items() if value not in (None, "", [])}


def build_delivery_payload(
    agentcore_response: dict[str, Any],
    *,
    entry_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = _require_mapping(agentcore_response, "agentcore_response")
    output = _require_mapping(response.get("output"), "output")
    run = _require_mapping(output.get("run"), "output.run")
    briefing = run.get("briefing") if isinstance(run.get("briefing"), dict) else {}
    safety = run.get("safety") if isinstance(run.get("safety"), dict) else {}
    location = run.get("location") if isinstance(run.get("location"), dict) else {}
    source_entry = entry_payload or {}
    conversation_id = source_entry.get("conversationId") if isinstance(source_entry, dict) else None
    case_id = _optional_text(output.get("caseId") or run.get("caseId") or source_entry.get("caseId"))

    return {
        "caseId": case_id,
        "caseUrl": _case_url(case_id),
        "conversationId": _optional_text(conversation_id),
        "status": output.get("reportStatus") or safety.get("level") or "unknown",
        "workflowMode": output.get("workflowMode") or "unknown",
        "customerSummary": {
            "title": briefing.get("site") or location.get("label") or "3D-RAMS review pack",
            "headline": briefing.get("headline") or "Review pack generated.",
            "summary": _string_list(briefing.get("summary")),
            "priorityChecks": _string_list(briefing.get("priority_checks")),
            "safetyMessage": safety.get("message") or "Human review is required before use.",
        },
        "deepReport": {
            "kind": "agentcore_run_payload",
            "caseId": case_id,
            "casePath": f"/case/{case_id}" if case_id else None,
            "runId": run.get("runId"),
            "evidenceCount": len(run.get("evidence") or []),
            "traceCount": len(run.get("trace") or []),
            "visualizationReady": bool(run.get("scene") and run.get("architecture")),
        },
        "safetyReminder": safety.get("message") or "Human review is required before use.",
        "agentcoreOutput": output,
    }


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdapterValidationError(f"{label} must be an object.")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _site_name(location_text: str | None, location_candidate: dict[str, Any]) -> str:
    label = _optional_text(location_candidate.get("label"))
    if label:
        return label
    if location_text:
        return location_text
    return "Confirmed AgentVerse intake location"


def _additional_request(intake: dict[str, Any]) -> str:
    parts: list[str] = []
    user_notes = _optional_text(intake.get("userNotes"))
    if user_notes:
        parts.append(user_notes)

    return "\n".join(parts)


def _safe_material_references(materials: list[Any], *, case_id: str) -> list[dict[str, Any]]:
    allowed = {
        "materialId",
        "id",
        "sourceSystem",
        "type",
        "label",
        "summary",
        "caseId",
        "sizeBytes",
        "sourceIds",
        "evidenceIds",
    }
    safe = []
    for item in materials:
        if not isinstance(item, dict):
            continue
        material = {key: item.get(key) for key in allowed if key in item}
        material.setdefault("caseId", case_id)
        access = item.get("access") if isinstance(item.get("access"), dict) else {}
        material["access"] = {
            "mode": access.get("mode") or "reference_only",
            "expiresAt": access.get("expiresAt"),
            "status": access.get("status") or "not_retrieved",
            "sessionId": access.get("sessionId"),
        }
        retrieval = _safe_material_retrieval_descriptor(access)
        if retrieval:
            material["access"]["retrieval"] = retrieval
        safe.append({key: value for key, value in material.items() if value not in (None, "", [])})
    return safe


def _safe_material_retrieval_descriptor(access: dict[str, Any]) -> dict[str, Any]:
    if access.get("retrievalUrl") or access.get("retrieval_url"):
        return {"method": "retrieval_url", "provided": True}
    if access.get("apiHandle") or access.get("api_handle"):
        return {"method": "api_handle", "provided": True}
    return {}


def _identity_context(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("identity") or payload.get("authorizationContext") or {}
    if not isinstance(source, dict):
        return {}
    allowed = {
        "subjectRef",
        "organizationRef",
        "sessionRef",
        "issuer",
        "authMode",
    }
    return {key: source[key] for key in allowed if source.get(key)}


def _upstream_source(payload: dict[str, Any]) -> str:
    caller = str(payload.get("caller") or "").strip().lower()
    if payload.get("frontendInvoke"):
        return "FRONTEND"
    if caller == "frontend":
        return "FRONTEND"
    if caller == "agentverse":
        return "AGENTVERSE"
    if caller in {"local-asione", "local_asione", "local"}:
        return "LOCAL_ASIONE_DEV"
    return "ASI_ONE_ENTRY_AGENT"


def _default_report_access_mode(source: str) -> str:
    return "dev_local" if source == "LOCAL_ASIONE_DEV" else "asi_session"


def _copy_access_fields(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schemaVersion",
        "mode",
        "caseId",
        "subjectId",
        "sessionId",
        "authorizedCaseIds",
        "expiresAt",
        "source",
    }
    return {key: value[key] for key in allowed if key in value}


def _case_url(case_id: str | None) -> str | None:
    if not case_id:
        return None
    base_url = os.getenv("PUBLIC_FRONTEND_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return f"/case/{case_id}"
    return f"{base_url}/case/{case_id}"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
