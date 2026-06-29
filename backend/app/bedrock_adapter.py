from __future__ import annotations

import json
import os
import time
from typing import Any

from .config import RuntimeConfig


class BedrockAdapterError(RuntimeError):
    pass


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
        raise BedrockAdapterError("boto3 is not installed in the backend environment.") from exc

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


def _metadata(config: RuntimeConfig, started: float, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "modelId": config.bedrock_model_id,
        "awsRegion": config.aws_region,
        "maxTokens": config.bedrock_max_tokens,
        "temperature": config.bedrock_temperature,
        "latencyMs": round((time.perf_counter() - started) * 1000),
    }


def _text(value: Any, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _list(value: Any, fallback: list[str], limit: int) -> list[str]:
    if not isinstance(value, list):
        return fallback[:limit]
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:limit] if items else fallback[:limit]
