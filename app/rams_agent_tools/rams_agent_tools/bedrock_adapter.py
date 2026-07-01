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
                "initial_parallel_groups": ["geospatial_subagent", "planning_subagent"],
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


def _metadata(
    config: RuntimeConfig,
    started: float,
    mode: str,
    *,
    phase: str | None = None,
    model_call_count: int = 1,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "phase": phase,
        "modelId": config.bedrock_model_id,
        "awsRegion": config.aws_region,
        "maxTokens": config.bedrock_max_tokens,
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
    initial = _subagent_list(plan.get("initial_parallel_groups"), ["geospatial_subagent", "planning_subagent"])
    sequential = _subagent_list(plan.get("sequential_groups"), ["hazard_subagent", "open_web_subagent", "review_guardrail"])
    report = _subagent_list(plan.get("report_parallel_groups"), ["annotation_subagent", "briefing_subagent"])

    for group in ["geospatial_subagent", "planning_subagent"]:
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
        "initial_parallel_groups": ["geospatial_subagent", "planning_subagent"],
        "sequential_groups": ["hazard_subagent", "open_web_subagent", "review_guardrail"],
        "report_parallel_groups": ["annotation_subagent", "briefing_subagent"],
        "required_evidence": [
            "resolved location",
            "geospatial features",
            "planning context",
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
