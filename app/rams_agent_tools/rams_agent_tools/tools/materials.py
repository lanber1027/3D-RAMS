from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .telemetry import trace_step


MATERIAL_REFERENCE_SCHEMA_VERSION = "3d-rams.material-reference.v1"
MATERIAL_INGESTION_SCHEMA_VERSION = "3d-rams.material-ingestion.v1"
MAX_MATERIAL_BYTES = 10 * 1024 * 1024
MATERIAL_FETCH_TIMEOUT_SECONDS = 5
ASI_MATERIAL_API_BASE_URL_ENV = "RAMS_ASI_MATERIAL_API_BASE_URL"
ASI_MATERIAL_API_BEARER_TOKEN_ENV = "RAMS_ASI_MATERIAL_API_BEARER_TOKEN"
ALLOWED_MATERIAL_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/markdown",
    "text/plain",
}
AUTHORIZED_ACCESS_MODES = {
    "asio_authorized_reference",
    "fixture_authorized_reference",
    "fieldbrief_mock_reference",
}

SAFE_FIXTURE_EXTRACTS: dict[str, dict[str, Any]] = {
    "asio_material_site_access_plan": {
        "summary": (
            "Fixture extraction from an ASI-owned site access plan flags constrained public-realm access, "
            "stopping/loading checks, and river-edge context for human review."
        ),
        "confidence": "medium",
        "citations": [
            {"label": "Site access plan", "locator": "safe fixture extract"},
        ],
        "observations": [
            {
                "id": "access-plan-public-realm",
                "title": "Material access-plan review",
                "category": "access",
                "description": (
                    "Authorized material summary indicates access and public-interface assumptions should be checked "
                    "before any site visit planning."
                ),
                "confidence": "medium",
            }
        ],
    },
    "asio_material_services_note": {
        "summary": (
            "Fixture extraction from an ASI-owned services note flags urban utility-density assumptions that require "
            "current statutory checks before intrusive work."
        ),
        "confidence": "low",
        "citations": [
            {"label": "Services note", "locator": "safe fixture extract"},
        ],
        "observations": [
            {
                "id": "services-note-utility-check",
                "title": "Material services-note review",
                "category": "buried_services",
                "description": (
                    "Authorized material summary raises a utility-records check as evidence support for human review."
                ),
                "confidence": "low",
            }
        ],
    },
}


def sanitize_material_references(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_sanitize_reference(item, index) for index, item in enumerate(value) if isinstance(item, dict)]


def ingest_material_references(
    materials: Any,
    *,
    case_id: str | None,
    upstream_context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate ASIO-owned material references and return safe evidence summaries.

    This local adapter deliberately does not fetch raw private files. It proves the
    contract with deterministic fixture extracts and safe pre-extracted summaries.
    """
    reference_items = materials if isinstance(materials, list) else []
    reference_pairs = [
        (_sanitize_reference(item, index), item)
        for index, item in enumerate(reference_items)
        if isinstance(item, dict)
    ]
    safe_references = [reference for reference, _raw_reference in reference_pairs]
    current_time = now or datetime.now(timezone.utc)
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []

    for reference, raw_reference in reference_pairs:
        skip_reason = _skip_reason(reference, case_id=case_id, now=current_time)
        if skip_reason:
            skipped.append(_skipped_material(reference, skip_reason))
            continue

        extracted = _safe_extract(reference, raw_reference)
        if extracted and extracted.get("skipReason"):
            skipped.append(_skipped_material(reference, str(extracted["skipReason"])))
            continue
        if extracted is None:
            skipped.append(_skipped_material(reference, "retrieval_not_configured"))
            continue

        source_id = f"material-{_slug(reference['materialId'])}"
        evidence_id = f"ev-{source_id}"
        material_citations = _citations(reference, source_id, extracted)
        citations.extend(material_citations)

        source = {
            "id": source_id,
            "label": reference["label"],
            "kind": "asio_material_reference",
            "status": extracted["status"],
            "origin": _origin(reference, extracted),
            "trustBoundary": "ASI/ASI:ONE material storage and authorization",
            "awsMapping": "Future AgentCore material retrieval adapter plus CloudWatch source metadata",
            "material": _material_identity(reference),
        }
        sources.append(source)

        evidence_item = {
            "id": evidence_id,
            "title": f"Material-derived summary: {reference['label']}",
            "source": "ASI-owned material reference; raw material content is not stored in 3D-RAMS output",
            "status": extracted["status"],
            "sourceIds": [source_id],
            "freshness": _freshness(reference),
            "confidence": extracted["confidence"],
            "summary": extracted["summary"],
            "why_it_matters": extracted["summary"],
            "citations": material_citations,
            "material": _material_identity(reference),
        }
        evidence.append(evidence_item)

        for observation in extracted["observations"]:
            findings.append(
                {
                    "id": f"material-{_slug(reference['materialId'])}-{_slug(observation['id'])}",
                    "title": observation["title"],
                    "category": observation["category"],
                    "source": "authorized material reference",
                    "sourceIds": [source_id],
                    "evidenceIds": [evidence_id],
                    "confidence": observation["confidence"],
                    "note": observation["description"],
                    "humanReviewRequired": True,
                }
            )

        accepted.append(
            {
                "materialId": reference["materialId"],
                "label": reference["label"],
                "sourceSystem": reference["sourceSystem"],
                "type": reference["type"],
                "caseId": reference.get("caseId"),
                "sourceId": source_id,
                "evidenceId": evidence_id,
                "retrievalMode": extracted["retrievalMode"],
                "status": extracted["status"],
            }
        )

    status = _ingestion_status(received=len(safe_references), accepted=len(accepted), skipped=len(skipped))
    output = {
        "schemaVersion": MATERIAL_INGESTION_SCHEMA_VERSION,
        "referenceSchemaVersion": MATERIAL_REFERENCE_SCHEMA_VERSION,
        "status": status,
        "mode": "deterministic-local-material-adapter",
        "caseId": case_id,
        "upstreamSource": _safe_upstream_source(upstream_context),
        "received": len(safe_references),
        "accepted": len(accepted),
        "skippedCount": len(skipped),
        "references": safe_references,
        "acceptedReferences": accepted,
        "skipped": skipped,
        "citations": citations,
        "sourceIds": [item["id"] for item in sources],
        "evidenceIds": [item["id"] for item in evidence],
    }
    return {
        **output,
        "sources": sources,
        "evidence": evidence,
        "findings": findings,
        "trace": trace_step(
            "ingest_material_references",
            status,
            _trace_summary(status=status, accepted=len(accepted), skipped=len(skipped), received=len(safe_references)),
            {
                "schemaVersion": MATERIAL_INGESTION_SCHEMA_VERSION,
                "mode": output["mode"],
                "received": output["received"],
                "accepted": output["accepted"],
                "skippedCount": output["skippedCount"],
                "skipped": skipped,
                "citationCount": len(citations),
            },
            source_ids=output["sourceIds"],
            evidence_ids=output["evidenceIds"],
        ),
    }


def _sanitize_reference(material: dict[str, Any], index: int) -> dict[str, Any]:
    access = material.get("access") if isinstance(material.get("access"), dict) else {}
    material_id = _text(material.get("materialId") or material.get("id")) or f"material-{index + 1}"
    source_system = _text(material.get("sourceSystem") or material.get("source_system")) or "unknown"
    material_type = _text(material.get("type") or material.get("contentType") or material.get("content_type")) or "unknown"
    access_mode = _text(access.get("mode")) or _default_access_mode(source_system)
    sanitized = {
        "schemaVersion": MATERIAL_REFERENCE_SCHEMA_VERSION,
        "materialId": material_id[:120],
        "sourceSystem": source_system[:80],
        "type": material_type[:120],
        "label": (_text(material.get("label")) or f"Material {index + 1}")[:160],
        "summary": (_text(material.get("summary")) or "")[:500],
        "caseId": _text(material.get("caseId") or access.get("caseId")),
        "sizeBytes": _non_negative_int(material.get("sizeBytes") or material.get("size_bytes")),
        "access": {
            "mode": access_mode,
            "status": _text(access.get("status")),
            "expiresAt": _text(access.get("expiresAt") or access.get("expires_at")),
            "authorized": access.get("authorized") if isinstance(access.get("authorized"), bool) else None,
            "sessionId": _text(access.get("sessionId") or access.get("session_id")),
            "retrieval": _safe_retrieval_descriptor(access),
        },
    }
    return _drop_empty(sanitized)


def _safe_retrieval_descriptor(access: dict[str, Any]) -> dict[str, Any]:
    retrieval = access.get("retrieval") if isinstance(access.get("retrieval"), dict) else {}
    method = _text(retrieval.get("method"))
    if method in {"retrieval_url", "api_handle"} and retrieval.get("provided") is True:
        return {"method": method, "provided": True}
    if access.get("retrievalUrl") or access.get("retrieval_url"):
        return {"method": "retrieval_url", "provided": True}
    if access.get("apiHandle") or access.get("api_handle"):
        return {"method": "api_handle", "provided": True}
    return {}


def _skip_reason(reference: dict[str, Any], *, case_id: str | None, now: datetime) -> str | None:
    material_type = str(reference.get("type") or "").lower()
    if material_type not in ALLOWED_MATERIAL_TYPES:
        return "unsupported_type"

    size_bytes = reference.get("sizeBytes")
    if isinstance(size_bytes, int) and size_bytes > MAX_MATERIAL_BYTES:
        return "too_large"

    access = reference.get("access") if isinstance(reference.get("access"), dict) else {}
    access_status = str(access.get("status") or "").strip().lower()
    access_mode = str(access.get("mode") or "").strip().lower()
    if access_status in {"denied", "expired", "revoked", "unauthorized"}:
        return access_status
    if access.get("authorized") is False:
        return "denied"
    if access_mode in {"denied", "expired", "revoked", "unauthorized"}:
        return access_mode
    if access_mode not in AUTHORIZED_ACCESS_MODES:
        return "unsupported_access_mode"

    material_case_id = _text(reference.get("caseId"))
    if case_id and material_case_id and material_case_id != case_id:
        return "unauthorized_case_mismatch"
    if case_id and _is_asio_reference(reference) and not material_case_id and not access.get("sessionId"):
        return "missing_case_or_session_binding"

    expires_at = _text(access.get("expiresAt"))
    if expires_at:
        parsed_expiry = _parse_datetime(expires_at)
        if parsed_expiry is None:
            return "invalid_expiry"
        if parsed_expiry <= now:
            return "expired"
    return None


def _safe_extract(reference: dict[str, Any], raw_reference: dict[str, Any] | None = None) -> dict[str, Any] | None:
    fixture = SAFE_FIXTURE_EXTRACTS.get(str(reference.get("materialId") or ""))
    if fixture:
        return {
            "status": "authorized-material-fixture",
            "retrievalMode": "fixture-authorized-material",
            "summary": fixture["summary"],
            "confidence": fixture["confidence"],
            "observations": fixture["observations"],
            "citations": fixture.get("citations", []),
        }

    retrieved = _retrieve_material(reference, raw_reference or {})
    if retrieved:
        if retrieved["status"] != "retrieved":
            return {"skipReason": retrieved["status"]}
        return {
            "status": "retrieved",
            "retrievalMode": retrieved["mode"],
            "summary": (
                f"Retrieved authorized {retrieved['contentType']} material "
                f"({retrieved['sizeBytes']} byte(s)) for bounded material extraction; raw content is not stored."
            ),
            "confidence": "low",
            "observations": [],
            "citations": [{"label": reference["label"], "locator": "retrieved bounded material; raw content not stored"}],
        }

    summary = _text(reference.get("summary"))
    access = reference.get("access") if isinstance(reference.get("access"), dict) else {}
    access_mode = str(access.get("mode") or "")
    if summary and access_mode == "fieldbrief_mock_reference":
        return {
            "status": "mocked-material-summary",
            "retrievalMode": "fieldbrief-mock-summary",
            "summary": summary,
            "confidence": "low",
            "observations": [],
            "citations": [{"label": reference["label"], "locator": "local mock material summary"}],
        }
    if summary and access_mode == "asio_authorized_reference":
        return {
            "status": "authorized-material-summary",
            "retrievalMode": "asio-safe-summary",
            "summary": summary,
            "confidence": "low",
            "observations": [],
            "citations": [{"label": reference["label"], "locator": "ASI supplied safe summary"}],
        }
    return None


def _retrieve_material(reference: dict[str, Any], raw_reference: dict[str, Any]) -> dict[str, Any] | None:
    raw_access = raw_reference.get("access") if isinstance(raw_reference.get("access"), dict) else {}
    retrieval_url = _text(raw_access.get("retrievalUrl") or raw_access.get("retrieval_url"))
    api_handle = _text(raw_access.get("apiHandle") or raw_access.get("api_handle"))
    if retrieval_url:
        return _fetch_material_url(retrieval_url, reference, mode="retrieval_url")
    if api_handle:
        base_url = _text(os.getenv(ASI_MATERIAL_API_BASE_URL_ENV))
        bearer_token = _text(os.getenv(ASI_MATERIAL_API_BEARER_TOKEN_ENV))
        if not base_url or not bearer_token:
            return {"status": "retrieval_not_configured"}
        url = f"{base_url.rstrip('/')}/{urllib.parse.quote(api_handle, safe='')}"
        headers = {"Authorization": f"Bearer {bearer_token}"}
        case_id = _text(reference.get("caseId"))
        session_id = _text((reference.get("access") or {}).get("sessionId")) if isinstance(reference.get("access"), dict) else None
        if case_id:
            headers["X-3D-RAMS-Case-Id"] = case_id
        if session_id:
            headers["X-3D-RAMS-Session-Id"] = session_id
        return _fetch_material_url(url, reference, mode="api_handle", headers=headers)
    return None


def _fetch_material_url(
    url: str,
    reference: dict[str, Any],
    *,
    mode: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(request, timeout=MATERIAL_FETCH_TIMEOUT_SECONDS) as response:
            declared_length = _non_negative_int(response.headers.get("Content-Length"))
            if isinstance(declared_length, int) and declared_length > MAX_MATERIAL_BYTES:
                return {"status": "too_large"}
            content_type = _content_type(response.headers.get("Content-Type"), fallback=str(reference.get("type") or ""))
            if content_type not in ALLOWED_MATERIAL_TYPES:
                return {"status": "unsupported_type"}
            data = response.read(MAX_MATERIAL_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return {"status": _http_retrieval_status(exc.code)}
    except (OSError, ValueError, urllib.error.URLError):
        return {"status": "retrieval_failed"}

    if len(data) > MAX_MATERIAL_BYTES:
        return {"status": "too_large"}
    return {
        "status": "retrieved",
        "mode": mode,
        "contentType": content_type,
        "sizeBytes": len(data),
    }


def _content_type(value: str | None, *, fallback: str) -> str:
    content_type = _text(value)
    if not content_type:
        return fallback.lower()
    return content_type.split(";", 1)[0].strip().lower()


def _http_retrieval_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return "denied"
    if status_code == 410:
        return "expired"
    if status_code == 413:
        return "too_large"
    if status_code == 415:
        return "unsupported_type"
    return "retrieval_failed"


def _citations(reference: dict[str, Any], source_id: str, extracted: dict[str, Any]) -> list[dict[str, Any]]:
    citations = []
    for citation in extracted.get("citations", []):
        if not isinstance(citation, dict):
            continue
        citations.append(
            {
                "sourceId": source_id,
                "materialId": reference["materialId"],
                "label": _text(citation.get("label")) or reference["label"],
                "locator": _text(citation.get("locator")) or "safe material summary",
                "rawContentStored": False,
            }
        )
    if citations:
        return citations
    return [
        {
            "sourceId": source_id,
            "materialId": reference["materialId"],
            "label": reference["label"],
            "locator": "safe material summary",
            "rawContentStored": False,
        }
    ]


def _skipped_material(reference: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "materialId": reference.get("materialId"),
        "label": reference.get("label"),
        "sourceSystem": reference.get("sourceSystem"),
        "type": reference.get("type"),
        "caseId": reference.get("caseId"),
        "reason": reason,
    }


def _material_identity(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "materialId": reference["materialId"],
        "sourceSystem": reference["sourceSystem"],
        "type": reference["type"],
        "label": reference["label"],
        "caseId": reference.get("caseId"),
    }


def _origin(reference: dict[str, Any], extracted: dict[str, Any]) -> str:
    if extracted["retrievalMode"] == "fixture-authorized-material":
        return "Deterministic fixture extract for an ASI-owned material reference; no raw upload storage in 3D-RAMS"
    if extracted["retrievalMode"] == "fieldbrief-mock-summary":
        return "FieldBrief development/mock material reference; metadata-only local testing path"
    return "ASI-owned authorized material reference with safe pre-extracted summary"


def _freshness(reference: dict[str, Any]) -> str:
    access = reference.get("access") if isinstance(reference.get("access"), dict) else {}
    expires_at = _text(access.get("expiresAt"))
    if expires_at:
        return f"Material access expires at {expires_at}; verify authorization before reuse"
    return "Authorization freshness is controlled by ASI/ASI:ONE material access context"


def _ingestion_status(*, received: int, accepted: int, skipped: int) -> str:
    if received == 0:
        return "disabled"
    if accepted > 0 and skipped == 0:
        return "ok"
    if accepted > 0:
        return "warning"
    return "warning"


def _trace_summary(*, status: str, accepted: int, skipped: int, received: int) -> str:
    if status == "disabled":
        return "No ASI/ASI:ONE material references were supplied for this run."
    return (
        f"Material ingestion accepted {accepted} of {received} reference(s); "
        f"{skipped} skipped with safe trace reasons."
    )


def _default_access_mode(source_system: str) -> str:
    if source_system.lower() in {"fieldbrief-dev", "fieldbrief-local", "local", "fixture"}:
        return "fieldbrief_mock_reference"
    return "unknown"


def _is_asio_reference(reference: dict[str, Any]) -> bool:
    source_system = str(reference.get("sourceSystem") or "").lower()
    access = reference.get("access") if isinstance(reference.get("access"), dict) else {}
    return source_system in {"asio", "asi", "asi_one", "asi:one"} or access.get("mode") == "asio_authorized_reference"


def _safe_upstream_source(upstream_context: dict[str, Any] | None) -> str | None:
    if not isinstance(upstream_context, dict):
        return None
    return _text(upstream_context.get("source"))


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return (slug or "material")[:80]


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        output = {key: _drop_empty(item) for key, item in value.items()}
        return {key: item for key, item in output.items() if item is not None and item != {}}
    return value
