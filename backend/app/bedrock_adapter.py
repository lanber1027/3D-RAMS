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


def generate_bedrock_tool_plan(
    *,
    config: RuntimeConfig,
    request_summary: dict[str, Any],
    tool_schemas: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.bedrock_simulate_failure:
        raise BedrockAdapterError("Simulated Bedrock failure requested by BEDROCK_SIMULATE_FAILURE.")
    if config.bedrock_max_model_calls < 1:
        raise BedrockAdapterError("Bedrock model call budget is zero.")

    started = time.perf_counter()
    if config.bedrock_mock_response:
        scenario = os.getenv("BEDROCK_MOCK_PLANNER_SCENARIO", "").strip().lower()
        plan = _mock_bedrock_tool_plan(scenario)
        return plan, _metadata(config, started, "bedrock-mock", phase="planner-plan", model_call_count=1)

    response_text = _invoke_bedrock_json(
        config,
        {
            "task": "Plan bounded local tool calls for a 3D-RAMS pre-visit review pack.",
            "safety_boundary": (
                "Use only the supplied tool names. Do not request shell, file, URL, network, or code execution. "
                "The final pack is for human review only."
            ),
            "required_json_schema": {
                "rationale": "short string",
                "tool_calls": [
                    {
                        "name": "one allowed tool name",
                        "arguments": "object, usually empty",
                    }
                ],
            },
            "request": request_summary,
            "allowed_tools": tool_schemas,
            "max_tool_calls": 8,
        },
    )
    plan = _normalise_plan(_extract_json_object(response_text))
    return plan, _metadata(config, started, "bedrock", phase="planner-plan", model_call_count=1)


def generate_bedrock_planner_synthesis(
    *,
    config: RuntimeConfig,
    location: dict[str, Any],
    hazards: list[dict[str, Any]],
    deterministic_briefing: dict[str, Any],
    evidence: list[dict[str, Any]],
    planning_available: bool,
    executed_tools: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.bedrock_simulate_failure:
        raise BedrockAdapterError("Simulated Bedrock failure requested by BEDROCK_SIMULATE_FAILURE.")
    if config.bedrock_max_model_calls < 2:
        raise BedrockAdapterError("Bedrock model call budget is below the planner+synthesis minimum.")

    started = time.perf_counter()
    if config.bedrock_mock_response:
        briefing = _mock_bedrock_planner_synthesis(deterministic_briefing, hazards, planning_available, executed_tools)
        return briefing, _metadata(config, started, "bedrock-mock", phase="planner-synthesis", model_call_count=1)

    response_text = _invoke_bedrock_json(
        config,
        {
            "task": "Synthesize a concise review briefing from bounded local tool outputs.",
            "safety_boundary": (
                "Do not certify RAMS, approve work, provide emergency instructions, or replace a competent person. "
                "Output is for human review only. In generated fields, avoid the words certify, certified, approve, "
                "approved, approval, emergency guidance, and work approval except when quoting the required safety boundary."
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
            "executed_tools": executed_tools,
            "deterministic_fallback": deterministic_briefing,
        },
    )
    briefing = _normalise_briefing(_extract_json_object(response_text), deterministic_briefing)
    briefing["generation_mode"] = "llm-planner"
    return briefing, _metadata(config, started, "bedrock", phase="planner-synthesis", model_call_count=1)


def generate_bedrock_risk_reasoning(
    *,
    config: RuntimeConfig,
    location: dict[str, Any],
    hazards: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    executed_tools: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.bedrock_simulate_failure:
        raise BedrockAdapterError("Simulated Bedrock failure requested by BEDROCK_SIMULATE_FAILURE.")
    if config.bedrock_max_model_calls < 2:
        raise BedrockAdapterError("Bedrock model call budget is below the planner+reasoner minimum.")

    started = time.perf_counter()
    if config.bedrock_mock_response:
        reasoning = _mock_bedrock_risk_reasoning(hazards, evidence, executed_tools)
        return reasoning, _metadata(config, started, "bedrock-mock", phase="risk-reasoner", model_call_count=1)

    response_text = _invoke_bedrock_json(
        config,
        {
            "task": "Rank site visit risks and identify uncertainty from bounded tool outputs.",
            "safety_boundary": (
                "This is not certified RAMS, emergency guidance, or work approval. "
                "Every risk statement must stay evidence-backed and human-review required."
            ),
            "required_json_schema": {
                "ranked_risks": [
                    {
                        "title": "string",
                        "reason": "string",
                        "confidence": "high|medium|low",
                        "evidence_ids": ["string"],
                    }
                ],
                "uncertainties": ["string"],
                "approval_required": "boolean",
            },
            "site": {
                "label": location.get("label"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "authority": location.get("authority"),
            },
            "hazards": hazards[:8],
            "evidence": evidence,
            "executed_tools": executed_tools,
        },
    )
    reasoning = _normalise_reasoning(_extract_json_object(response_text), hazards, evidence)
    return reasoning, _metadata(config, started, "bedrock", phase="risk-reasoner", model_call_count=1)


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
            "Output is for human review only. In generated fields, avoid the words certify, certified, approve, "
            "approved, approval, emergency guidance, and work approval except when quoting the required safety boundary."
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


def _normalise_plan(parsed: dict[str, Any]) -> dict[str, Any]:
    raw_calls = parsed.get("tool_calls")
    if not isinstance(raw_calls, list):
        raise BedrockAdapterError("Planner response did not include a tool_calls list.")
    tool_calls: list[dict[str, Any]] = []
    for raw_call in raw_calls[:8]:
        if not isinstance(raw_call, dict):
            continue
        name = raw_call.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        arguments = raw_call.get("arguments")
        tool_calls.append(
            {
                "name": name.strip(),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    if not tool_calls:
        raise BedrockAdapterError("Planner response did not include executable tool calls.")
    return {
        "rationale": _text(parsed.get("rationale"), "Planner selected the bounded local review workflow."),
        "tool_calls": tool_calls,
    }


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


def _mock_bedrock_tool_plan(scenario: str) -> dict[str, Any]:
    if scenario == "invalid-tool":
        return {
            "rationale": "Mock planner intentionally requested a disallowed tool for fallback testing.",
            "tool_calls": [
                {"name": "run_shell", "arguments": {"command": "curl http://example.com"}},
                {"name": "resolve_location", "arguments": {}},
            ],
        }
    if scenario == "bad-order":
        return {
            "rationale": "Mock planner intentionally returned allowlisted tools in an invalid order.",
            "tool_calls": [
                {"name": "extract_hazard_notes", "arguments": {}},
                {"name": "resolve_location", "arguments": {}},
                {"name": "load_geospatial_features", "arguments": {}},
                {"name": "build_scene_config", "arguments": {}},
                {"name": "load_planning_context", "arguments": {}},
                {"name": "rank_risks", "arguments": {}},
                {"name": "create_annotations", "arguments": {}},
                {"name": "compile_review_pack", "arguments": {}},
            ],
        }
    if scenario == "v2-valid":
        return {
            "rationale": "Mock planner selected the v2 durable runtime tool chain.",
            "tool_calls": [
                {"name": "resolve_location", "arguments": {}},
                {"name": "load_geospatial_features", "arguments": {}},
                {"name": "build_scene_config", "arguments": {}},
                {"name": "load_planning_context", "arguments": {}},
                {"name": "extract_hazard_notes", "arguments": {}},
                {"name": "rank_risks", "arguments": {}},
                {"name": "create_annotations", "arguments": {}},
                {"name": "compile_review_pack", "arguments": {}},
            ],
        }

    return {
        "rationale": "Mock planner selected the bounded local 3D-RAMS tool chain.",
        "tool_calls": [
            {"name": "resolve_location", "arguments": {}},
            {"name": "fetch_geospatial_features", "arguments": {}},
            {"name": "build_scene", "arguments": {}},
            {"name": "load_planning_fixture", "arguments": {}},
            {"name": "extract_hazard_notes", "arguments": {}},
            {"name": "create_annotations", "arguments": {}},
            {"name": "generate_site_brief", "arguments": {}},
        ],
    }


def _mock_bedrock_planner_synthesis(
    fallback: dict[str, Any],
    hazards: list[dict[str, Any]],
    planning_available: bool,
    executed_tools: list[str],
) -> dict[str, Any]:
    briefing = dict(fallback)
    if os.getenv("BEDROCK_MOCK_PLANNER_UNSAFE_RESPONSE", "").strip().lower() in {"1", "true", "yes", "on"}:
        briefing["headline"] = "Certified RAMS briefing approved for work."
        briefing["summary"] = [
            "The LLM planner has certified RAMS for the selected site.",
            "The pack is approved for work without further human review.",
            "Emergency guidance can now be used operationally.",
        ]
        briefing["priority_checks"] = []
        briefing["generation_mode"] = "llm-planner-mock"
        return briefing

    briefing["headline"] = "LLM-planned review pack for human approval."
    briefing["summary"] = [
        f"Planner path executed {len(executed_tools)} allowlisted local tools over the current site evidence.",
        f"The synthesis reviewed {len(hazards)} candidate hazards and kept source confidence visible.",
        "This remains a controlled review pack, not a certified RAMS or work approval.",
    ]
    if not planning_available:
        briefing["limitations"] = briefing["limitations"] + [
            "Planner synthesis noted missing planning evidence; document-derived risks remain incomplete."
        ]
    briefing["generation_mode"] = "llm-planner-mock"
    return briefing


def _mock_bedrock_risk_reasoning(
    hazards: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    executed_tools: list[str],
) -> dict[str, Any]:
    return {
        "ranked_risks": [
            {
                "title": hazard.get("title", "Risk candidate"),
                "reason": hazard.get("note", "Review this risk candidate against current source evidence."),
                "confidence": hazard.get("confidence", "medium"),
                "evidence_ids": hazard.get("evidenceIds", []),
            }
            for hazard in hazards[:5]
        ],
        "uncertainties": [
            "Live source freshness is not guaranteed in the cached fixture path.",
            "Human review is required before any RAMS or work-planning use.",
        ],
        "approval_required": True,
        "executed_tools": executed_tools,
        "evidence_count": len(evidence),
    }


def _normalise_reasoning(
    parsed: dict[str, Any],
    hazards: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_risks = parsed.get("ranked_risks")
    ranked: list[dict[str, Any]] = []
    if isinstance(raw_risks, list):
        for item in raw_risks[:6]:
            if not isinstance(item, dict):
                continue
            ranked.append(
                {
                    "title": _text(item.get("title"), "Risk candidate"),
                    "reason": _text(item.get("reason"), "Review this risk candidate against current source evidence."),
                    "confidence": _text(item.get("confidence"), "medium"),
                    "evidence_ids": _list(item.get("evidence_ids"), [], 5),
                }
            )
    if not ranked:
        ranked = [
            {
                "title": hazard.get("title", "Risk candidate"),
                "reason": hazard.get("note", "Review this risk candidate against current source evidence."),
                "confidence": hazard.get("confidence", "medium"),
                "evidence_ids": hazard.get("evidenceIds", []),
            }
            for hazard in hazards[:5]
        ]
    return {
        "ranked_risks": ranked,
        "uncertainties": _list(
            parsed.get("uncertainties"),
            [
                "Source freshness and completeness must be reviewed by a competent person.",
                "This output is not certified RAMS, emergency guidance, or work approval.",
            ],
            5,
        ),
        "approval_required": bool(parsed.get("approval_required", True)),
        "evidence_count": len(evidence),
    }


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
        "temperature": config.bedrock_temperature,
        "modelCallCount": model_call_count,
        "maxModelCalls": config.bedrock_max_model_calls,
        "latencyMs": round((time.perf_counter() - started) * 1000),
    }


def _text(value: Any, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _list(value: Any, fallback: list[str], limit: int) -> list[str]:
    if not isinstance(value, list):
        return fallback[:limit]
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:limit] if items else fallback[:limit]
