from __future__ import annotations

import json
import os
import time
from typing import Any

from .config import RuntimeConfig


class BedrockAdapterError(RuntimeError):
    pass


def bedrock_fallback_reason(exc: BaseException) -> str:
    code = _exception_code(exc).lower()
    text = f"{code} {exc.__class__.__name__} {exc}".lower()
    if "simulated bedrock failure" in text:
        return "bedrock_simulated_failure"
    if any(token in text for token in ("accessdenied", "access denied", "unauthorized", "forbidden")):
        return "bedrock_access_denied"
    if any(token in text for token in ("timeout", "timedout", "readtimeout", "connecttimeout")):
        return "bedrock_timeout"
    if any(token in text for token in ("throttl", "toomanyrequests", "rate exceeded", "servicequota")):
        return "bedrock_throttled"
    if "json" in text:
        return "invalid_model_json"
    if any(token in text for token in ("schema", "validation", "required")):
        return "schema_validation_failed"
    return "bedrock_unavailable"


def bedrock_error_output(exc: BaseException) -> dict[str, Any]:
    return {
        "fallbackReason": bedrock_fallback_reason(exc),
        "errorType": exc.__class__.__name__,
        "errorCode": _exception_code(exc) or None,
    }


def generate_bedrock_briefing(
    *,
    config: RuntimeConfig,
    location: dict[str, Any],
    hazards: list[dict[str, Any]],
    deterministic_briefing: dict[str, Any],
    evidence: list[dict[str, Any]],
    planning_available: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.bedrock_simulate_failure:
        raise BedrockAdapterError("Simulated Bedrock failure requested by BEDROCK_SIMULATE_FAILURE.")

    started = time.perf_counter()
    if config.bedrock_mock_response:
        briefing = _mock_bedrock_briefing(deterministic_briefing, hazards, planning_available)
        return briefing, _metadata(config, started, "bedrock-mock")

    try:
        import boto3
    except ImportError as exc:
        raise BedrockAdapterError("boto3 is not installed in the AgentCore runtime environment.") from exc

    session_kwargs = {}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile
    session = boto3.Session(**session_kwargs)
    client = session.client("bedrock-runtime", region_name=config.aws_region)

    response = client.invoke_model(
        modelId=config.bedrock_model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(_anthropic_payload(config, location, hazards, deterministic_briefing, evidence, planning_available)),
    )
    body = json.loads(response["body"].read())
    text = "".join(
        item.get("text", "")
        for item in body.get("content", [])
        if item.get("type") == "text"
    )
    parsed = _extract_json_object(text)
    briefing = _normalise_briefing(parsed, deterministic_briefing)
    return briefing, _metadata(config, started, "bedrock")


def generate_bedrock_subagent_plan(
    *,
    config: RuntimeConfig,
    request_summary: dict[str, Any],
    subagent_schemas: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.bedrock_simulate_failure:
        raise BedrockAdapterError("Simulated Bedrock failure requested by BEDROCK_SIMULATE_FAILURE.")
    if config.bedrock_max_model_calls < 1:
        raise BedrockAdapterError("Bedrock model call budget is zero.")

    started = time.perf_counter()
    if config.bedrock_mock_response:
        scenario = os.getenv("BEDROCK_MOCK_PLANNER_SCENARIO", "").strip().lower()
        plan = _mock_bedrock_subagent_plan(scenario)
        return plan, _metadata(config, started, "bedrock-mock", phase="planner-plan", model_call_count=1)

    response_text = _invoke_bedrock_json(
        config,
        {
            "task": "Plan the bounded 3D-RAMS AgentCore Harness subagent workflow for a site review pack.",
            "safety_boundary": (
                "Use only the supplied subagent ids. Do not request shell, file, URL, network, or code execution. "
                "The final pack is for human review only and is not certified RAMS, emergency guidance, or work approval."
            ),
            "required_json_schema": {
                "rationale": "short string",
                "initial_parallel_groups": ["geospatial_subagent", "planning_subagent", "material_subagent"],
                "sequential_groups": ["hazard_subagent", "open_web_subagent", "review_guardrail"],
                "report_parallel_groups": ["annotation_subagent", "briefing_subagent"],
                "required_evidence": ["short strings"],
                "missing_inputs": ["short strings"],
            },
            "request": request_summary,
            "allowed_subagents": subagent_schemas,
            "planner_policy": {
                "planner_is_required": True,
                "subagents_are_bounded": True,
                "supervisor_may_normalise_invalid_or_missing_groups": True,
            },
        },
    )
    plan = _normalise_subagent_plan(_extract_json_object(response_text))
    return plan, _metadata(config, started, "bedrock", phase="planner-plan", model_call_count=1)


def generate_bedrock_material_extraction(
    *,
    config: RuntimeConfig,
    material_id: str,
    label: str,
    content_type: str,
    text: str | None = None,
    document_bytes: bytes | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.bedrock_simulate_failure:
        raise BedrockAdapterError("Simulated Bedrock failure requested by BEDROCK_SIMULATE_FAILURE.")
    if config.bedrock_max_model_calls < 1:
        raise BedrockAdapterError("Bedrock model call budget is zero.")

    started = time.perf_counter()
    if config.bedrock_mock_response:
        extraction = _mock_material_extraction(label=label, content_type=content_type, text=text, document_bytes=document_bytes)
        return extraction, _metadata(
            config,
            started,
            "bedrock-mock",
            phase="material-extraction",
            model_id=config.material_extraction_model_id,
            max_tokens=config.material_extraction_max_tokens,
        )

    content = _material_converse_content(
        material_id=material_id,
        label=label,
        content_type=content_type,
        text=text,
        document_bytes=document_bytes,
    )
    try:
        import boto3
    except ImportError as exc:
        raise BedrockAdapterError("boto3 is not installed in the AgentCore runtime environment.") from exc

    session_kwargs = {}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile
    session = boto3.Session(**session_kwargs)
    client = session.client("bedrock-runtime", region_name=config.aws_region)
    response = client.converse(
        modelId=config.material_extraction_model_id,
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": config.material_extraction_max_tokens, "temperature": 0.0},
    )
    response_text = "".join(
        block.get("text", "")
        for block in response.get("output", {}).get("message", {}).get("content", [])
        if isinstance(block, dict)
    )
    extraction = _normalise_material_extraction(_extract_json_object(response_text), label=label)
    return extraction, _metadata(
        config,
        started,
        "bedrock",
        phase="material-extraction",
        model_id=config.material_extraction_model_id,
        max_tokens=config.material_extraction_max_tokens,
    )


def _material_converse_content(
    *,
    material_id: str,
    label: str,
    content_type: str,
    text: str | None,
    document_bytes: bytes | None,
) -> list[dict[str, Any]]:
    prompt = {
        "task": "Extract bounded material evidence for a draft 3D-RAMS human-review pack.",
        "material": {"materialId": material_id, "label": label, "contentType": content_type},
        "safety_boundary": (
            "Return evidence only. Do not certify RAMS, approve work, provide emergency guidance, "
            "or quote long private document passages."
        ),
        "required_json_schema": {
            "summary": "one short sentence",
            "confidence": "high | medium | low | unknown",
            "observations": [
                {
                    "title": "short observation title",
                    "category": "access | buried_services | planning | environment | hazard | other",
                    "description": "bounded observation, no long quotes",
                    "citation_anchor": "page/section/paragraph hint if available",
                    "confidence": "high | medium | low | unknown",
                }
            ],
            "limitations": ["short strings"],
        },
        "limits": {"max_observations": 5, "max_description_chars": 240},
    }
    content: list[dict[str, Any]] = []
    if content_type == "application/pdf" and document_bytes is not None:
        content.append({"document": {"format": "pdf", "name": _document_name(material_id, label), "source": {"bytes": document_bytes}}})
    if content_type in {"text/plain", "text/markdown"} and text:
        content.append({"text": f"Authorized material text for extraction:\n\n{text}"})
    content.append({"text": "Return only valid JSON.\n\n" + json.dumps(prompt, ensure_ascii=True)})
    return content


def _document_name(material_id: str, label: str) -> str:
    name = "".join(ch if ch.isalnum() else "-" for ch in (label or material_id).lower()).strip("-")
    return (name or "material")[:80]


def _anthropic_payload(
    config: RuntimeConfig,
    location: dict[str, Any],
    hazards: list[dict[str, Any]],
    deterministic_briefing: dict[str, Any],
    evidence: list[dict[str, Any]],
    planning_available: bool,
) -> dict[str, Any]:
    prompt = {
        "task": "Create a concise pre-visit review briefing from structured site evidence.",
        "safety_boundary": (
            "Do not certify RAMS, approve work, provide emergency instructions, or replace a competent person. "
            "Output is for human review only."
        ),
        "required_json_schema": {
            "headline": "string",
            "summary": ["3 short strings"],
            "priority_checks": ["up to 5 short strings"],
            "before_site_visit": ["3 short strings"],
            "limitations": ["3 to 5 short strings"],
        },
        "site": {
            "label": location.get("label"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "authority": location.get("authority"),
        },
        "hazards": hazards[:8],
        "evidence": evidence,
        "planning_available": planning_available,
        "deterministic_fallback": deterministic_briefing,
    }
    return {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": config.bedrock_max_tokens,
        "temperature": config.bedrock_temperature,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Return only valid JSON matching required_json_schema. "
                            "Keep every statement evidence-backed and review-required.\n\n"
                            + json.dumps(prompt, ensure_ascii=True)
                        ),
                    }
                ],
            }
        ],
    }


def _invoke_bedrock_json(config: RuntimeConfig, prompt: dict[str, Any]) -> str:
    try:
        import boto3
    except ImportError as exc:
        raise BedrockAdapterError("boto3 is not installed in the AgentCore runtime environment.") from exc

    session_kwargs = {}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile
    session = boto3.Session(**session_kwargs)
    client = session.client("bedrock-runtime", region_name=config.aws_region)

    response = client.invoke_model(
        modelId=config.bedrock_model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": config.bedrock_max_tokens,
                "temperature": config.bedrock_temperature,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Return only valid JSON.\n\n" + json.dumps(prompt, ensure_ascii=True),
                            }
                        ],
                    }
                ],
            }
        ),
    )
    body = json.loads(response["body"].read())
    return "".join(
        item.get("text", "")
        for item in body.get("content", [])
        if item.get("type") == "text"
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise BedrockAdapterError("Bedrock response did not contain a JSON object.")
    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise BedrockAdapterError("Bedrock response JSON could not be parsed.") from exc
    if not isinstance(parsed, dict):
        raise BedrockAdapterError("Bedrock response JSON was not an object.")
    return parsed


def _normalise_subagent_plan(parsed: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_subagent_plan()
    plan = {
        "rationale": _text(parsed.get("rationale"), defaults["rationale"]),
        "initial_parallel_groups": _subagent_list(
            parsed.get("initial_parallel_groups"),
            defaults["initial_parallel_groups"],
        ),
        "sequential_groups": _subagent_list(
            parsed.get("sequential_groups"),
            defaults["sequential_groups"],
        ),
        "report_parallel_groups": _subagent_list(
            parsed.get("report_parallel_groups"),
            defaults["report_parallel_groups"],
        ),
        "required_evidence": _list(
            parsed.get("required_evidence"),
            defaults["required_evidence"],
            8,
        ),
        "missing_inputs": _list(parsed.get("missing_inputs"), [], 6),
    }
    return _ensure_required_subagents(plan)


def _normalise_briefing(parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    briefing = dict(fallback)
    briefing["headline"] = _text(parsed.get("headline"), fallback["headline"])
    briefing["summary"] = _list(parsed.get("summary"), fallback["summary"], 3)
    briefing["priority_checks"] = _list(parsed.get("priority_checks"), fallback["priority_checks"], 5)
    briefing["before_site_visit"] = _list(parsed.get("before_site_visit"), fallback["before_site_visit"], 4)
    limitations = _list(parsed.get("limitations"), fallback["limitations"], 5)
    boundary = "Human review is required; this is not certified RAMS, emergency guidance, or work approval."
    if not any("certified" in item.lower() or "human review" in item.lower() for item in limitations):
        limitations.append(boundary)
    briefing["limitations"] = limitations[:5]
    briefing["generation_mode"] = "bedrock"
    return briefing


def _normalise_material_extraction(parsed: dict[str, Any], *, label: str) -> dict[str, Any]:
    observations = []
    for index, item in enumerate(parsed.get("observations") if isinstance(parsed.get("observations"), list) else []):
        if not isinstance(item, dict):
            continue
        description = _text(item.get("description"), "")
        if not description:
            continue
        citation_anchor = _text(item.get("citation_anchor") or item.get("citationAnchor"), "document evidence")
        observations.append(
            {
                "id": f"observation-{index + 1}",
                "title": _text(item.get("title"), f"Material observation {index + 1}")[:120],
                "category": _material_category(item.get("category")),
                "description": description[:240],
                "confidence": _confidence(item.get("confidence")),
                "citationAnchor": citation_anchor[:120],
            }
        )
        if len(observations) >= 5:
            break
    return {
        "status": "extracted" if observations else "no_relevant_content",
        "summary": _text(parsed.get("summary"), f"No RAMS-relevant observations were extracted from {label}.")[:300],
        "confidence": _confidence(parsed.get("confidence")),
        "limitations": _string_list(parsed.get("limitations"), ["Material extraction is bounded for demo review."])[:5],
        "observations": observations,
        "citations": [{"label": label, "locator": item["citationAnchor"]} for item in observations],
    }


def _mock_bedrock_subagent_plan(scenario: str) -> dict[str, Any]:
    plan = _default_subagent_plan()
    plan["rationale"] = "Mock Bedrock planner selected the standard bounded Harness subagent graph."
    if scenario == "missing-input":
        plan["missing_inputs"] = ["User should confirm the exact site boundary before operational use."]
    if scenario == "minimal":
        plan["report_parallel_groups"] = ["briefing_subagent"]
    return _ensure_required_subagents(plan)


def _mock_bedrock_briefing(
    fallback: dict[str, Any],
    hazards: list[dict[str, Any]],
    planning_available: bool,
) -> dict[str, Any]:
    briefing = dict(fallback)
    if os.getenv("BEDROCK_MOCK_UNSAFE_RESPONSE", "").strip().lower() in {"1", "true", "yes", "on"}:
        briefing["headline"] = "Certified RAMS briefing approved for work."
        briefing["summary"] = [
            "This Bedrock mock output says the site pack is certified RAMS.",
            "The work is approved for work without further competent review.",
            "Emergency guidance is ready for operational use.",
        ]
        briefing["priority_checks"] = []
        briefing["generation_mode"] = "bedrock-mock"
        return briefing

    briefing["headline"] = "Bedrock-style pre-visit review briefing for human approval."
    briefing["summary"] = [
        f"Model path reviewed {len(hazards)} structured hazard candidates from the current run.",
        "The briefing keeps source confidence and human review boundaries visible.",
        "This is a controlled review pack, not a certified RAMS or work approval.",
    ]
    if not planning_available:
        briefing["limitations"] = briefing["limitations"] + [
            "Bedrock mock noted missing planning evidence; document-derived risks remain incomplete."
        ]
    briefing["generation_mode"] = "bedrock-mock"
    return briefing


def _mock_material_extraction(
    *,
    label: str,
    content_type: str,
    text: str | None,
    document_bytes: bytes | None,
) -> dict[str, Any]:
    sample = (text or "").lower()
    if not sample and document_bytes:
        sample = "pdf material supplied"
    observations = []
    if any(token in sample for token in ("access", "route", "public realm", "pdf material")):
        observations.append(
            {
                "id": "observation-1",
                "title": "Material access constraint",
                "category": "access",
                "description": "Retrieved material indicates access assumptions should be checked before site attendance.",
                "confidence": "medium",
                "citationAnchor": "page/section hint unavailable in mock",
            }
        )
    if any(token in sample for token in ("service", "utility", "buried")):
        observations.append(
            {
                "id": "observation-2",
                "title": "Material utility check",
                "category": "buried_services",
                "description": "Retrieved material indicates utility or buried-service records need competent review.",
                "confidence": "low",
                "citationAnchor": "text section hint unavailable in mock",
            }
        )
    return {
        "status": "extracted" if observations else "no_relevant_content",
        "summary": (
            f"Mock Bedrock extraction reviewed a retrieved {content_type} material for bounded RAMS evidence."
            if observations
            else f"Mock Bedrock extraction found no RAMS-relevant content in {label}."
        ),
        "confidence": "medium" if observations else "low",
        "limitations": ["Mock extraction for local verification; use live Bedrock only with authorized public-safe material."],
        "observations": observations[:5],
        "citations": [{"label": label, "locator": item["citationAnchor"]} for item in observations[:5]],
    }


def _metadata(
    config: RuntimeConfig,
    started: float,
    mode: str,
    *,
    phase: str | None = None,
    model_call_count: int = 1,
    model_id: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "phase": phase,
        "modelId": model_id or config.bedrock_model_id,
        "awsRegion": config.aws_region,
        "maxTokens": max_tokens or config.bedrock_max_tokens,
        "maxModelCalls": config.bedrock_max_model_calls,
        "temperature": config.bedrock_temperature,
        "modelCallCount": model_call_count,
        "latencyMs": round((time.perf_counter() - started) * 1000),
    }


def _text(value: Any, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _list(value: Any, fallback: list[str], limit: int) -> list[str]:
    if not isinstance(value, list):
        return fallback[:limit]
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:limit] if items else fallback[:limit]


def _material_category(value: Any) -> str:
    category = str(value or "other").strip().lower()
    return category if category in {"access", "buried_services", "planning", "environment", "hazard", "other"} else "other"


def _confidence(value: Any) -> str:
    confidence = str(value or "unknown").strip().lower()
    return confidence if confidence in {"high", "medium", "low", "unknown"} else "unknown"


def _string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    items = [str(item).strip()[:180] for item in value if str(item).strip()]
    return items or fallback


def _subagent_list(value: Any, fallback: list[str]) -> list[str]:
    allowed = set(_all_required_subagents())
    if not isinstance(value, list):
        return list(fallback)
    items = []
    for item in value:
        name = str(item).strip()
        if name in allowed and name not in items:
            items.append(name)
    return items or list(fallback)


def _ensure_required_subagents(plan: dict[str, Any]) -> dict[str, Any]:
    initial = _subagent_list(plan.get("initial_parallel_groups"), ["geospatial_subagent", "planning_subagent", "material_subagent"])
    sequential = _subagent_list(plan.get("sequential_groups"), ["hazard_subagent", "open_web_subagent", "review_guardrail"])
    report = _subagent_list(plan.get("report_parallel_groups"), ["annotation_subagent", "briefing_subagent"])

    for group in ["geospatial_subagent", "planning_subagent", "material_subagent"]:
        if group not in initial:
            initial.append(group)
    if "hazard_subagent" not in sequential:
        sequential.insert(0, "hazard_subagent")
    if "open_web_subagent" not in sequential:
        insert_at = 1 if "hazard_subagent" in sequential else 0
        sequential.insert(insert_at, "open_web_subagent")
    if "review_guardrail" not in sequential:
        sequential.append("review_guardrail")
    for group in ["annotation_subagent", "briefing_subagent"]:
        if group not in report:
            report.append(group)

    plan["initial_parallel_groups"] = initial
    plan["sequential_groups"] = sequential
    plan["report_parallel_groups"] = report
    return plan


def _default_subagent_plan() -> dict[str, Any]:
    return {
        "rationale": "Use the standard 3D-RAMS bounded Harness workflow for a complete review pack.",
        "initial_parallel_groups": ["geospatial_subagent", "planning_subagent", "material_subagent"],
        "sequential_groups": ["hazard_subagent", "open_web_subagent", "review_guardrail"],
        "report_parallel_groups": ["annotation_subagent", "briefing_subagent"],
        "required_evidence": [
            "resolved location",
            "geospatial features",
            "planning context",
            "authorized material references",
            "candidate hazards",
            "open-web public signals",
            "3D annotations",
            "evidence-backed briefing",
            "independent review gate",
        ],
        "missing_inputs": [],
    }


def _all_required_subagents() -> list[str]:
    return [
        "geospatial_subagent",
        "planning_subagent",
        "material_subagent",
        "hazard_subagent",
        "open_web_subagent",
        "annotation_subagent",
        "briefing_subagent",
        "review_guardrail",
    ]


def _exception_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code") or "")
    return ""
