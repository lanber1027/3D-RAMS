from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Protocol

from rams_agent_tools.config import RuntimeConfig
from rams_agent_tools.fixtures import load_fixture_pack
from rams_agent_tools.tools import (
    apply_bedrock_briefing,
    architecture_snapshot,
    build_scene_config,
    create_annotations,
    extract_hazard_notes,
    generate_site_brief,
    harness_for_group,
    load_geospatial_features,
    load_planning_context,
    resolve_location,
    safety_gate,
    trace_step,
)


class SubagentInvoker(Protocol):
    execution_mode: str

    def invoke_geospatial(
        self,
        request: dict[str, Any],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ...

    def invoke_planning(
        self,
        request: dict[str, Any],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ...

    def invoke_hazard(
        self,
        planning_text: str | None,
        features: list[dict[str, Any]],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ...

    def invoke_annotation(
        self,
        location: dict[str, Any],
        hazards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...

    def invoke_briefing(
        self,
        config: RuntimeConfig,
        location: dict[str, Any],
        hazards: list[dict[str, Any]],
        planning_text: str | None,
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ...

    def invoke_review(
        self,
        request: dict[str, Any],
        briefing: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class DirectSubagentInvoker:
    execution_mode = "direct-local-harness-adapter"

    def invoke_geospatial(
        self,
        request: dict[str, Any],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []

        location, step = resolve_location(request, fixture_pack=fixture_pack)
        trace.append(step)

        features, step = load_geospatial_features(
            location,
            simulate_failure=bool(request.get("simulateMapFailure")),
            fixture_pack=fixture_pack,
        )
        trace.append(step)

        scene, step = build_scene_config(location, features, fixture_pack=fixture_pack)
        trace.append(step)

        return {"location": location, "features": features, "scene": scene, "trace": trace}

    def invoke_planning(
        self,
        request: dict[str, Any],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        planning_text, step = load_planning_context(
            include_planning_fixture=bool(request.get("includePlanningFixture", True)),
            fixture_pack=fixture_pack,
        )
        return {"planningText": planning_text, "trace": [step]}

    def invoke_hazard(
        self,
        planning_text: str | None,
        features: list[dict[str, Any]],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        hazards, step = extract_hazard_notes(planning_text, features, fixture_pack=fixture_pack)
        return {"hazards": hazards, "trace": [step]}

    def invoke_annotation(
        self,
        location: dict[str, Any],
        hazards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        annotations, step = create_annotations(location, hazards)
        return {"annotations": annotations, "trace": [step]}

    def invoke_briefing(
        self,
        config: RuntimeConfig,
        location: dict[str, Any],
        hazards: list[dict[str, Any]],
        planning_text: str | None,
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []

        briefing, evidence, step = generate_site_brief(location, hazards, planning_text, fixture_pack=fixture_pack)
        trace.append(step)

        briefing, step, bedrock_status, bedrock_fallback_reason = apply_bedrock_briefing(
            config,
            location,
            hazards,
            briefing,
            evidence,
            planning_text,
        )
        trace.append(step)

        return {
            "briefing": briefing,
            "evidence": evidence,
            "trace": trace,
            "bedrockStatus": bedrock_status,
            "bedrockFallbackReason": bedrock_fallback_reason,
        }

    def invoke_review(
        self,
        request: dict[str, Any],
        briefing: dict[str, Any],
    ) -> dict[str, Any]:
        safety, step = safety_gate(request, briefing)
        return {"safety": safety, "trace": [step]}


class AgentCoreHarnessInvoker:
    execution_mode = "agentcore-harness"

    def __init__(self, *, config: RuntimeConfig, client: Any | None = None) -> None:
        self.config = config
        self.client = client or _agentcore_client(config)
        self.harness_arns = _load_harness_arns()

    def invoke_geospatial(
        self,
        request: dict[str, Any],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._invoke_json(
            "geospatial_subagent",
            {
                "task": "Resolve location, load geospatial features, and build scene config. Return JSON only.",
                "request": request,
                "fixturePack": _fixture_pack_name(fixture_pack),
                "requiredKeys": ["location", "features", "scene", "trace"],
            },
        )

    def invoke_planning(
        self,
        request: dict[str, Any],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._invoke_json(
            "planning_subagent",
            {
                "task": "Load planning context for the confirmed site review. Return JSON only.",
                "includePlanningFixture": bool(request.get("includePlanningFixture", True)),
                "fixturePack": _fixture_pack_name(fixture_pack),
                "requiredKeys": ["planningText", "trace"],
            },
        )

    def invoke_hazard(
        self,
        planning_text: str | None,
        features: list[dict[str, Any]],
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._invoke_json(
            "hazard_subagent",
            {
                "task": "Extract evidence-linked hazard notes from planning text and geospatial features. Return JSON only.",
                "planningText": planning_text,
                "features": features,
                "fixturePack": _fixture_pack_name(fixture_pack),
                "requiredKeys": ["hazards", "trace"],
            },
        )

    def invoke_annotation(
        self,
        location: dict[str, Any],
        hazards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._invoke_json(
            "annotation_subagent",
            {
                "task": "Create frontend-ready 3D annotations from resolved hazards. Return JSON only.",
                "location": location,
                "hazards": hazards,
                "requiredKeys": ["annotations", "trace"],
            },
        )

    def invoke_briefing(
        self,
        config: RuntimeConfig,
        location: dict[str, Any],
        hazards: list[dict[str, Any]],
        planning_text: str | None,
        *,
        fixture_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._invoke_json(
            "briefing_subagent",
            {
                "task": "Generate evidence-backed briefing, evidence, and optional Bedrock drafting status. Return JSON only.",
                "location": location,
                "hazards": hazards,
                "planningText": planning_text,
                "fixturePack": _fixture_pack_name(fixture_pack),
                "useBedrock": config.bedrock_requested,
                "requiredKeys": ["briefing", "evidence", "bedrockStatus", "bedrockFallbackReason", "trace"],
            },
        )

    def invoke_review(
        self,
        request: dict[str, Any],
        briefing: dict[str, Any],
    ) -> dict[str, Any]:
        return self._invoke_json(
            "review_guardrail",
            {
                "task": "Run independent safety/review gate on the briefing. Return JSON only.",
                "request": request,
                "briefing": briefing,
                "requiredKeys": ["safety", "trace"],
            },
        )

    def _invoke_json(self, group: str, payload: dict[str, Any]) -> dict[str, Any]:
        harness_name = harness_for_group(group)
        if not harness_name:
            raise RuntimeError(f"No Harness is registered for subagent group '{group}'.")

        harness_arn = self.harness_arns.get(harness_name)
        if not harness_arn:
            raise RuntimeError(
                f"Missing ARN for Harness '{harness_name}'. Set RAMS_HARNESS_ARNS or "
                f"{_harness_arn_env_name(harness_name)} before using RAMS_SUBAGENT_EXECUTION_MODE=agentcore_harness."
            )

        messages = [_user_json_message(payload)]
        runtime_session_id = _runtime_session_id(group)

        for _ in range(8):
            response = self.client.invoke_harness(
                harnessArn=harness_arn,
                qualifier=os.getenv("RAMS_HARNESS_QUALIFIER", "DEFAULT"),
                runtimeSessionId=runtime_session_id,
                runtimeUserId=os.getenv("RAMS_HARNESS_RUNTIME_USER_ID", "3d-rams-supervisor"),
                messages=messages,
            )
            parsed = _parse_harness_stream(response["stream"])
            if parsed["toolUses"]:
                messages.append({"role": "assistant", "content": parsed["assistantContent"]})
                messages.append(_tool_result_message(parsed["toolUses"]))
                continue
            result = _extract_json_object(parsed["text"])
            missing_keys = _missing_required_keys(result, payload)
            if missing_keys:
                return self._fallback_json(group, payload, missing_keys=missing_keys, raw_result=result)
            return result

        raise RuntimeError(f"Harness '{harness_name}' exceeded local tool-loop limit.")

    def _fallback_json(
        self,
        group: str,
        payload: dict[str, Any],
        *,
        missing_keys: list[str],
        raw_result: dict[str, Any],
    ) -> dict[str, Any]:
        fixture_pack = _load_tool_fixture_pack(payload.get("fixturePack"))
        direct = DirectSubagentInvoker()

        if group == "geospatial_subagent":
            result = direct.invoke_geospatial(_dict(payload.get("request")), fixture_pack=fixture_pack)
        elif group == "planning_subagent":
            result = direct.invoke_planning(
                {"includePlanningFixture": bool(payload.get("includePlanningFixture", True))},
                fixture_pack=fixture_pack,
            )
        elif group == "hazard_subagent":
            result = direct.invoke_hazard(
                payload.get("planningText"),
                _list(payload.get("features")),
                fixture_pack=fixture_pack,
            )
        elif group == "annotation_subagent":
            result = direct.invoke_annotation(_dict(payload.get("location")), _list(payload.get("hazards")))
        elif group == "briefing_subagent":
            result = direct.invoke_briefing(
                self.config,
                _dict(payload.get("location")),
                _list(payload.get("hazards")),
                payload.get("planningText"),
                fixture_pack=fixture_pack,
            )
        elif group == "review_guardrail":
            result = direct.invoke_review(_dict(payload.get("request")), _dict(payload.get("briefing")))
        else:
            raise RuntimeError(f"Cannot build fallback result for Harness subagent group '{group}'.")

        result.setdefault("trace", [])
        result["trace"].append(
            trace_step(
                "agentcore_harness_schema_fallback",
                "fallback",
                "Supervisor used deterministic tool fallback because Harness output missed required keys.",
                {
                    "group": group,
                    "missingKeys": missing_keys,
                    "rawResultKeys": sorted(raw_result.keys()),
                },
                fallback_reason="agentcore_harness_missing_required_keys",
            )
        )
        return result


def build_subagent_invoker(config: RuntimeConfig) -> SubagentInvoker:
    mode = os.getenv("RAMS_SUBAGENT_EXECUTION_MODE", "direct").strip().lower()
    if mode in {"direct", "local", "fixture", "fixture_first"}:
        return DirectSubagentInvoker()
    if mode in {"agentcore_harness", "harness", "aws"}:
        return AgentCoreHarnessInvoker(config=config)
    raise RuntimeError(f"Unsupported RAMS_SUBAGENT_EXECUTION_MODE '{mode}'.")


def _agentcore_client(config: RuntimeConfig) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required for RAMS_SUBAGENT_EXECUTION_MODE=agentcore_harness. "
            "Use the AgentCore runtime environment or install runtime dependencies."
        ) from exc

    return boto3.Session(
        profile_name=config.aws_profile,
        region_name=config.aws_region,
    ).client("bedrock-agentcore", region_name=config.aws_region)


def _load_harness_arns() -> dict[str, str]:
    raw = os.getenv("RAMS_HARNESS_ARNS")
    mapping: dict[str, str] = {}
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("RAMS_HARNESS_ARNS must be a JSON object mapping Harness names to ARNs.")
        mapping.update({str(key): str(value) for key, value in parsed.items() if value})

    for group, spec in {
        "rams_geospatial_harness": "RAMS_GEOSPATIAL_HARNESS_ARN",
        "rams_planning_harness": "RAMS_PLANNING_HARNESS_ARN",
        "rams_hazard_harness": "RAMS_HAZARD_HARNESS_ARN",
        "rams_annotation_harness": "RAMS_ANNOTATION_HARNESS_ARN",
        "rams_briefing_harness": "RAMS_BRIEFING_HARNESS_ARN",
        "rams_review_harness": "RAMS_REVIEW_HARNESS_ARN",
    }.items():
        value = os.getenv(spec) or os.getenv(_harness_arn_env_name(group))
        if value:
            mapping[group] = value
    return mapping


def _harness_arn_env_name(harness_name: str) -> str:
    sanitized = re.sub(r"[^A-Z0-9]+", "_", harness_name.upper())
    return f"RAMS_HARNESS_ARN_{sanitized}"


def _fixture_pack_name(fixture_pack: dict[str, Any] | None) -> str | None:
    if not fixture_pack:
        return None
    return str(fixture_pack.get("name") or "") or None


def _user_json_message(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {
                "text": (
                    "You are a 3D-RAMS Harness subagent. Use your configured tools as needed, "
                    "then return one JSON object matching requiredKeys. Payload:\n"
                    f"{json.dumps(payload, sort_keys=True)}"
                )
            }
        ],
    }


def _runtime_session_id(group: str) -> str:
    return f"rams-{group}-{uuid.uuid4().hex}"


def _parse_harness_stream(stream: Any) -> dict[str, Any]:
    text_parts: list[str] = []
    assistant_content: list[dict[str, Any]] = []
    blocks: dict[int, dict[str, Any]] = {}

    for event in stream:
        if "contentBlockStart" in event:
            start_event = event["contentBlockStart"]
            index = int(start_event["contentBlockIndex"])
            start = start_event.get("start", {})
            if "toolUse" in start:
                tool_use = dict(start["toolUse"])
                tool_use.setdefault("input", "")
                blocks[index] = {"toolUse": tool_use}
            else:
                blocks[index] = {"text": ""}
        elif "contentBlockDelta" in event:
            delta_event = event["contentBlockDelta"]
            index = int(delta_event["contentBlockIndex"])
            delta = delta_event.get("delta", {})
            block = blocks.setdefault(index, {"text": ""})
            if "text" in delta:
                block["text"] = str(block.get("text", "")) + str(delta["text"])
            if "toolUse" in delta:
                tool_use = block.setdefault("toolUse", {})
                tool_use["input"] = str(tool_use.get("input", "")) + str(delta["toolUse"].get("input", ""))

    tool_uses: list[dict[str, Any]] = []
    for index in sorted(blocks):
        block = blocks[index]
        if "toolUse" in block:
            tool_use = dict(block["toolUse"])
            raw_input = tool_use.get("input") or {}
            if isinstance(raw_input, str):
                tool_use["input"] = json.loads(raw_input or "{}")
            assistant_content.append({"toolUse": tool_use})
            tool_uses.append(tool_use)
        else:
            text = str(block.get("text", ""))
            assistant_content.append({"text": text})
            text_parts.append(text)

    return {
        "text": "".join(text_parts),
        "assistantContent": assistant_content,
        "toolUses": tool_uses,
    }


def _tool_result_message(tool_uses: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": tool_use["toolUseId"],
                    "status": "success",
                    "type": tool_use.get("type", "tool_use"),
                    "content": [{"json": _execute_inline_tool(tool_use["name"], tool_use.get("input") or {})}],
                }
            }
            for tool_use in tool_uses
        ],
    }


def _execute_inline_tool(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    fixture_pack = _load_tool_fixture_pack(payload.get("fixturePack"))

    if name == "resolve_location":
        location, step = resolve_location(_dict(payload.get("request")), fixture_pack=fixture_pack)
        return {"location": location, "trace": [step]}
    if name == "load_geospatial_features":
        features, step = load_geospatial_features(
            _dict(payload.get("location")),
            simulate_failure=bool(payload.get("simulateFailure")),
            fixture_pack=fixture_pack,
        )
        return {"features": features, "trace": [step]}
    if name == "build_scene_config":
        scene, step = build_scene_config(
            _dict(payload.get("location")),
            _list(payload.get("features")),
            fixture_pack=fixture_pack,
        )
        return {"scene": scene, "trace": [step]}
    if name == "load_planning_context":
        planning_text, step = load_planning_context(
            include_planning_fixture=bool(payload.get("includePlanningFixture", True)),
            fixture_pack=fixture_pack,
        )
        return {"planningText": planning_text, "trace": [step]}
    if name == "extract_hazard_notes":
        hazards, step = extract_hazard_notes(
            payload.get("planningText"),
            _list(payload.get("features")),
            fixture_pack=fixture_pack,
        )
        return {"hazards": hazards, "trace": [step]}
    if name == "create_annotations":
        annotations, step = create_annotations(_dict(payload.get("location")), _list(payload.get("hazards")))
        return {"annotations": annotations, "trace": [step]}
    if name == "generate_site_brief":
        briefing, evidence, step = generate_site_brief(
            _dict(payload.get("location")),
            _list(payload.get("hazards")),
            payload.get("planningText"),
            fixture_pack=fixture_pack,
        )
        return {"briefing": briefing, "evidence": evidence, "trace": [step]}
    if name == "apply_bedrock_briefing":
        config = RuntimeConfig.from_env(request_bedrock=bool(payload.get("useBedrock")))
        briefing, step, status, fallback_reason = apply_bedrock_briefing(
            config,
            _dict(payload.get("location")),
            _list(payload.get("hazards")),
            _dict(payload.get("briefing")),
            _list(payload.get("evidence")),
            payload.get("planningText"),
        )
        return {
            "briefing": briefing,
            "bedrockStatus": status,
            "bedrockFallbackReason": fallback_reason,
            "trace": [step],
        }
    if name == "safety_gate":
        safety, step = safety_gate(_dict(payload.get("request")), _dict(payload.get("briefing")))
        return {"safety": safety, "trace": [step]}
    if name == "architecture_snapshot":
        return {
            "architecture": architecture_snapshot(
                _list(payload.get("trace")),
                _dict(payload.get("request")),
                _list(payload.get("sources")),
                _list(payload.get("evidence")),
                _dict(payload.get("safety")),
                _dict(payload.get("runtime")),
            )
        }
    raise RuntimeError(f"Unsupported Harness inline tool '{name}'.")


def _load_tool_fixture_pack(name: Any) -> dict[str, Any] | None:
    if not name:
        return None
    pack, _warning = load_fixture_pack(str(name))
    return pack


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise RuntimeError(f"Harness response did not contain JSON: {text[:500]}")
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("Harness response JSON must be an object.")
    return parsed


def _missing_required_keys(result: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    required = payload.get("requiredKeys")
    if not isinstance(required, list):
        return []
    return [str(key) for key in required if str(key) not in result]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []
