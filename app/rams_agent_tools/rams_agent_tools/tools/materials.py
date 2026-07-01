from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Any

from ..bedrock_adapter import BedrockAdapterError, generate_bedrock_material_extraction
from ..config import RuntimeConfig
from .telemetry import trace_step


MATERIAL_REFERENCE_SCHEMA_VERSION = "3d-rams.material-reference.v1"
MATERIAL_INGESTION_SCHEMA_VERSION = "3d-rams.material-ingestion.v1"
MAX_MATERIAL_BYTES = 10 * 1024 * 1024
MAX_TEXT_MATERIAL_CHARS = 24000
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
    config: RuntimeConfig | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate ASIO-owned material references and return safe evidence summaries.

    This local adapter deliberately does not fetch raw private files. It proves the
    contract with deterministic fixture extracts and safe pre-extracted summaries.
    """
    reference_items = [item for item in materials if isinstance(item, dict)] if isinstance(materials, list) else []
    safe_references = [_sanitize_reference(item, index) for index, item in enumerate(reference_items)]
    current_time = now or datetime.now(timezone.utc)
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    extractions: list[dict[str, Any]] = []

    for index, reference in enumerate(safe_references):
        raw_reference = reference_items[index]
        skip_reason = _skip_reason(reference, case_id=case_id, now=current_time)
        if skip_reason:
            skipped.append(_skipped_material(reference, skip_reason))
            continue

        extracted = _safe_extract(reference)
        if extracted is None:
            extracted, skip_reason = _extract_retrieved_material(reference, raw_reference, config=config)
            if extracted is None:
                skipped.append(_skipped_material(reference, skip_reason or "extraction_skipped"))
                continue

        source_id = f"material-{_slug(reference['materialId'])}"
        evidence_id = f"ev-{source_id}"
        material_citations = _citations(reference, source_id, extracted)
        citations.extend(material_citations)
        extractions.append(_public_extraction(reference, source_id, evidence_id, extracted, material_citations))

        source = {
            "id": source_id,
            "label": reference["label"],
            "kind": "asio_material_reference",
            "status": extracted["status"],
            "origin": _origin(reference, extracted),
            "trustBoundary": "ASI/ASI:ONE material storage and authorization",
            "awsMapping": _aws_mapping(extracted),
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
            "extraction": {
                "status": extracted["status"],
                "confidence": extracted["confidence"],
                "limitations": extracted.get("limitations", []),
            },
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
                    "citationAnchor": observation.get("citationAnchor"),
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
                "confidence": extracted["confidence"],
                "limitations": extracted.get("limitations", []),
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
        "extractions": extractions,
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
                "extractionStatuses": [item["status"] for item in extractions],
                "materialExtractionModelId": config.material_extraction_model_id if config else None,
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
        return "unsupported_format"

    size_bytes = reference.get("sizeBytes")
    if isinstance(size_bytes, int) and size_bytes > MAX_MATERIAL_BYTES:
        return "oversized"

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


def _safe_extract(reference: dict[str, Any]) -> dict[str, Any] | None:
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


def _extract_retrieved_material(
    reference: dict[str, Any],
    raw_reference: dict[str, Any],
    *,
    config: RuntimeConfig | None,
) -> tuple[dict[str, Any] | None, str | None]:
    material_type = str(reference.get("type") or "").lower()
    if material_type not in {"application/pdf", "text/plain", "text/markdown"}:
        return None, "unsupported_format"

    payload, payload_error = _retrieved_payload(raw_reference, material_type)
    if payload_error:
        return None, payload_error
    if payload is None:
        return None, "extraction_skipped"
    if config is None or not config.bedrock_enabled:
        return None, "model_not_configured"

    try:
        extraction, metadata = generate_bedrock_material_extraction(
            config=config,
            material_id=reference["materialId"],
            label=reference["label"],
            content_type=material_type,
            text=payload.get("text"),
            document_bytes=payload.get("bytes"),
        )
    except (BedrockAdapterError, Exception):
        return None, "extraction_failed"

    observations = extraction.get("observations") if isinstance(extraction.get("observations"), list) else []
    return {
        "status": str(extraction.get("status") or ("extracted" if observations else "no_relevant_content")),
        "retrievalMode": "bedrock-material-extraction",
        "summary": _text(extraction.get("summary")) or "Material extraction completed with no summary.",
        "confidence": _confidence(extraction.get("confidence")),
        "observations": [_material_observation(item, index) for index, item in enumerate(observations) if isinstance(item, dict)],
        "citations": extraction.get("citations") if isinstance(extraction.get("citations"), list) else [],
        "limitations": _string_list(extraction.get("limitations")),
        "model": {
            "provider": "amazon-bedrock",
            "modelId": metadata.get("modelId"),
            "awsRegion": metadata.get("awsRegion"),
            "mode": metadata.get("mode"),
            "maxTokens": metadata.get("maxTokens"),
        },
    }, None


def _retrieved_payload(raw_reference: dict[str, Any], material_type: str) -> tuple[dict[str, Any] | None, str | None]:
    retrieved = raw_reference.get("retrieved") if isinstance(raw_reference.get("retrieved"), dict) else {}
    for key in ("retrievedMaterial", "retrieved_material"):
        if isinstance(raw_reference.get(key), dict):
            retrieved = raw_reference[key]
            break

    if material_type in {"text/plain", "text/markdown"}:
        text = _first_text(
            retrieved.get("text"),
            retrieved.get("markdown"),
            retrieved.get("contentText"),
            raw_reference.get("text"),
            raw_reference.get("markdown"),
            raw_reference.get("contentText"),
            raw_reference.get("rawContent"),
        )
        if text:
            return {"text": text[:MAX_TEXT_MATERIAL_CHARS]}, None

    data = _first_bytes(
        retrieved.get("bytes"),
        retrieved.get("contentBytes"),
        raw_reference.get("bytes"),
        raw_reference.get("contentBytes"),
    )
    if data is None:
        encoded = _first_text(
            retrieved.get("bytesBase64"),
            retrieved.get("contentBase64"),
            retrieved.get("contentBytesBase64"),
            raw_reference.get("bytesBase64"),
            raw_reference.get("contentBase64"),
            raw_reference.get("contentBytesBase64"),
        )
        if encoded:
            try:
                data = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                return None, "extraction_failed"
    if data is not None:
        if len(data) > MAX_MATERIAL_BYTES:
            return None, "oversized"
        return {"bytes": data}, None
    return None, None


def _material_observation(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": _text(item.get("id")) or f"observation-{index + 1}",
        "title": (_text(item.get("title")) or f"Material observation {index + 1}")[:120],
        "category": _category(item.get("category")),
        "description": (_text(item.get("description")) or "Material observation extracted for human review.")[:240],
        "confidence": _confidence(item.get("confidence")),
        "citationAnchor": (_text(item.get("citationAnchor") or item.get("citation_anchor")) or "material evidence")[:120],
    }


def _public_extraction(
    reference: dict[str, Any],
    source_id: str,
    evidence_id: str,
    extracted: dict[str, Any],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "materialId": reference["materialId"],
        "label": reference["label"],
        "sourceId": source_id,
        "evidenceId": evidence_id,
        "status": extracted["status"],
        "retrievalMode": extracted["retrievalMode"],
        "summary": extracted["summary"],
        "confidence": extracted["confidence"],
        "observations": extracted.get("observations", []),
        "citations": citations,
        "limitations": extracted.get("limitations", []),
        "model": extracted.get("model"),
        "rawContentStored": False,
    }


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
    if extracted["retrievalMode"] == "bedrock-material-extraction":
        model = extracted.get("model") if isinstance(extracted.get("model"), dict) else {}
        return f"Authorized retrieved material extracted through Amazon Bedrock {model.get('modelId') or 'material model'}"
    return "ASI-owned authorized material reference with safe pre-extracted summary"


def _aws_mapping(extracted: dict[str, Any]) -> str:
    if extracted.get("retrievalMode") == "bedrock-material-extraction":
        return "Amazon Bedrock Converse material extraction plus CloudWatch source metadata"
    return "Future AgentCore material retrieval adapter plus CloudWatch source metadata"


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


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _first_bytes(*values: Any) -> bytes | None:
    for value in values:
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
    return None


def _confidence(value: Any) -> str:
    confidence = str(value or "unknown").strip().lower()
    return confidence if confidence in {"high", "medium", "low", "unknown"} else "unknown"


def _category(value: Any) -> str:
    category = str(value or "other").strip().lower()
    return category if category in {"access", "buried_services", "planning", "environment", "hazard", "other"} else "other"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:180] for item in value if str(item).strip()][:5]


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
