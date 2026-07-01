from __future__ import annotations

from typing import Any

from .bedrock_adapter import (
    BedrockAdapterError,
    generate_bedrock_planner_synthesis,
    generate_bedrock_tool_plan,
)
from .config import RuntimeConfig
from .fixtures import load_fixture_pack
from .tools import (
    apply_bedrock_briefing,
    architecture_snapshot,
    build_scene_config,
    create_annotations,
    extract_hazard_notes,
    generate_site_brief,
    load_geospatial_features,
    load_planning_context,
    normalize_request,
    resolve_location,
    safety_gate,
    source_register,
    trace_step,
)


PLANNER_TOOL_SCHEMAS = [
    {
        "name": "resolve_location",
        "description": "Resolve the submitted coordinate or fixture pack into site metadata.",
        "parameters": {},
    },
    {
        "name": "fetch_geospatial_features",
        "description": "Load cached or synthetic geospatial features for the resolved site.",
        "parameters": {},
    },
    {
        "name": "build_scene",
        "description": "Build the local 3D scene configuration from location and features.",
        "parameters": {},
    },
    {
        "name": "load_planning_fixture",
        "description": "Load cached or synthetic planning/context notes when enabled.",
        "parameters": {},
    },
    {
        "name": "extract_hazard_notes",
        "description": "Extract candidate hazards from geospatial features and planning notes.",
        "parameters": {},
    },
    {
        "name": "create_annotations",
        "description": "Convert hazards into bounded 3D map annotations.",
        "parameters": {},
    },
    {
        "name": "generate_site_brief",
        "description": "Generate the deterministic evidence-backed briefing and source evidence list.",
        "parameters": {},
    },
]


class PlannerExecutionError(RuntimeError):
    def __init__(self, message: str, *, rejected_tool: str | None = None):
        super().__init__(message)
        self.rejected_tool = rejected_tool


def run_site_briefing(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    request_summary = normalize_request(request)
    fixture_pack, fixture_pack_warning = load_fixture_pack(request_summary["fixturePack"])
    if fixture_pack:
        pack_location = fixture_pack["location"]
        request_summary["fixturePack"] = fixture_pack["name"]
        request_summary["siteName"] = pack_location["label"]
        request_summary["latitude"] = float(pack_location["latitude"])
        request_summary["longitude"] = float(pack_location["longitude"])

    request_bedrock = request_summary["useBedrock"] and request_summary["agentMode"] != "deterministic"
    config = RuntimeConfig.from_env(request_bedrock=request_bedrock)
    if request_summary["agentMode"] == "llm-planner":
        return _run_llm_planner_response(request, request_summary, fixture_pack, fixture_pack_warning, config)

    return _run_deterministic_response(
        request,
        request_summary,
        fixture_pack,
        fixture_pack_warning,
        config,
        apply_bedrock=request_summary["agentMode"] == "bedrock-briefing",
    )


def _run_deterministic_response(
    request: dict[str, Any],
    request_summary: dict[str, Any],
    fixture_pack: dict[str, Any] | None,
    fixture_pack_warning: dict[str, Any] | None,
    config: RuntimeConfig,
    *,
    apply_bedrock: bool,
    initial_trace: list[dict[str, Any]] | None = None,
    forced_bedrock_status: str | None = None,
    forced_fallback_reason: str | None = None,
    active_agent_mode: str | None = None,
    model_call_count: int = 0,
) -> dict[str, Any]:
    trace: list[dict[str, Any]] = list(initial_trace or [])
    if fixture_pack_warning:
        trace.append(
            trace_step(
                "load_fixture_pack",
                "fallback",
                fixture_pack_warning["reason"],
                fixture_pack_warning,
                fallback_reason=fixture_pack_warning["reason"],
            )
        )

    state = _run_core_tool_chain(request, request_summary, fixture_pack, trace, config)
    briefing = state["briefing"]
    evidence = state["evidence"]
    planning_text = state["planning_text"]
    location = state["location"]
    hazards = state["hazards"]

    if apply_bedrock:
        briefing, step, bedrock_status, bedrock_fallback_reason = apply_bedrock_briefing(
            config,
            location,
            hazards,
            briefing,
            evidence,
            planning_text,
        )
        trace.append(step)
    else:
        bedrock_status = forced_bedrock_status or "deterministic"
        bedrock_fallback_reason = forced_fallback_reason
        if forced_bedrock_status is None:
            trace.append(
                trace_step(
                    "generate_bedrock_briefing",
                    "disabled",
                    "Agent mode skipped Bedrock briefing; deterministic briefing remains active.",
                    {"mode": "deterministic", "agentMode": request_summary["agentMode"]},
                    source_ids=["bedrock-briefing"],
                    evidence_ids=[item["id"] for item in evidence],
                    fallback_reason="Agent mode deterministic does not call Bedrock.",
                )
            )

    safety, step = safety_gate(request, briefing)
    trace.append(step)
    return _build_response(
        request_summary,
        config,
        trace,
        location,
        state["scene"],
        state["map_features"],
        state["live_feature_status"],
        hazards,
        state["annotations"],
        briefing,
        evidence,
        safety,
        bedrock_status,
        bedrock_fallback_reason,
        fixture_pack,
        active_agent_mode=active_agent_mode or request_summary["agentMode"],
        model_call_count=model_call_count,
    )


def _run_core_tool_chain(
    request: dict[str, Any],
    request_summary: dict[str, Any],
    fixture_pack: dict[str, Any] | None,
    trace: list[dict[str, Any]],
    config: RuntimeConfig,
) -> dict[str, Any]:
    location, step = resolve_location(request, fixture_pack=fixture_pack)
    trace.append(step)

    features, step = load_geospatial_features(
        location,
        simulate_failure=bool(request.get("simulateMapFailure")),
        fixture_pack=fixture_pack,
        config=config,
    )
    trace.append(step)
    live_feature_status = step.get("output", {}).get("liveFeatureStatus") or {
        "status": "disabled",
        "successfulSources": [],
        "failedSources": [],
        "featureCount": len(features),
        "mode": "cached-or-synthetic",
    }

    scene, step = build_scene_config(location, features, fixture_pack=fixture_pack)
    trace.append(step)

    planning_text, step = load_planning_context(
        include_planning_fixture=bool(request.get("includePlanningFixture", True)),
        fixture_pack=fixture_pack,
    )
    trace.append(step)

    hazards, step = extract_hazard_notes(
        planning_text,
        features,
        fixture_pack=fixture_pack,
        site_intent=request.get("siteIntent"),
    )
    trace.append(step)

    annotations, step = create_annotations(location, hazards)
    trace.append(step)

    briefing, evidence, step = generate_site_brief(location, hazards, planning_text, fixture_pack=fixture_pack)
    trace.append(step)
    return {
        "location": location,
        "features": features,
        "map_features": features,
        "live_feature_status": live_feature_status,
        "scene": scene,
        "planning_text": planning_text,
        "hazards": hazards,
        "annotations": annotations,
        "briefing": briefing,
        "evidence": evidence,
    }


def _run_llm_planner_response(
    request: dict[str, Any],
    request_summary: dict[str, Any],
    fixture_pack: dict[str, Any] | None,
    fixture_pack_warning: dict[str, Any] | None,
    config: RuntimeConfig,
) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    model_call_count = 0

    if not config.bedrock_requested:
        fallback_reason = "LLM planner was requested but Bedrock was not requested; deterministic agent loop used."
        trace.append(_planner_fallback_step(fallback_reason, model_call_count))
        return _run_deterministic_response(
            request,
            request_summary,
            fixture_pack,
            fixture_pack_warning,
            config,
            apply_bedrock=False,
            initial_trace=trace,
            forced_bedrock_status="fallback",
            forced_fallback_reason=fallback_reason,
            active_agent_mode="deterministic-fallback",
            model_call_count=model_call_count,
        )

    if not config.bedrock_enabled:
        fallback_reason = "LLM planner requested but ENABLE_BEDROCK is not true; deterministic agent loop used."
        trace.append(_planner_fallback_step(fallback_reason, model_call_count))
        return _run_deterministic_response(
            request,
            request_summary,
            fixture_pack,
            fixture_pack_warning,
            config,
            apply_bedrock=False,
            initial_trace=trace,
            forced_bedrock_status="fallback",
            forced_fallback_reason=fallback_reason,
            active_agent_mode="deterministic-fallback",
            model_call_count=model_call_count,
        )

    if fixture_pack_warning:
        trace.append(
            trace_step(
                "load_fixture_pack",
                "fallback",
                fixture_pack_warning["reason"],
                fixture_pack_warning,
                fallback_reason=fixture_pack_warning["reason"],
            )
        )

    try:
        model_call_count += 1
        plan, metadata = generate_bedrock_tool_plan(
            config=config,
            request_summary=request_summary,
            tool_schemas=PLANNER_TOOL_SCHEMAS,
        )
        tool_calls = plan["tool_calls"]
        trace.append(
            trace_step(
                "llm_planner_model_plan",
                "ok",
                "Bedrock planner selected bounded local tools from the allowlist.",
                {
                    **metadata,
                    "rationale": plan["rationale"],
                    "toolCalls": tool_calls,
                    "allowedTools": [schema["name"] for schema in PLANNER_TOOL_SCHEMAS],
                },
                source_ids=["bedrock-briefing"],
                duration_ms=int(metadata.get("latencyMs", 0)),
            )
        )
        state = _execute_planner_tool_calls(request, request_summary, fixture_pack, tool_calls, trace, config)
        model_call_count += 1
        briefing, synth_metadata = generate_bedrock_planner_synthesis(
            config=config,
            location=state["location"],
            hazards=state["hazards"],
            deterministic_briefing=state["briefing"],
            evidence=state["evidence"],
            planning_available=state["planning_text"] is not None,
            executed_tools=state["executed_tools"],
        )
        trace.append(
            trace_step(
                "llm_planner_synthesis",
                "ok",
                "Bedrock planner synthesized a briefing from bounded local tool outputs.",
                {
                    **synth_metadata,
                    "executedTools": state["executed_tools"],
                    "generationMode": briefing.get("generation_mode"),
                },
                source_ids=["bedrock-briefing"],
                evidence_ids=[item["id"] for item in state["evidence"]],
                duration_ms=int(synth_metadata.get("latencyMs", 0)),
            )
        )
    except (PlannerExecutionError, BedrockAdapterError, Exception) as exc:
        fallback_reason = f"LLM planner failed; deterministic agent loop used. Reason: {exc}"
        output: dict[str, Any] = {
            "mode": "deterministic-fallback",
            "errorType": exc.__class__.__name__,
            "modelCallCount": model_call_count,
            "maxModelCalls": config.bedrock_max_model_calls,
        }
        rejected_tool = getattr(exc, "rejected_tool", None)
        if rejected_tool:
            output["rejectedTool"] = rejected_tool
        trace.append(
            trace_step(
                "llm_planner_model_plan",
                "fallback",
                "LLM planner could not complete safely; deterministic fallback remains active.",
                output,
                source_ids=["bedrock-briefing"],
                fallback_reason=fallback_reason,
            )
        )
        return _run_deterministic_response(
            request,
            request_summary,
            fixture_pack,
            fixture_pack_warning=None,
            config=config,
            apply_bedrock=False,
            initial_trace=trace,
            forced_bedrock_status="fallback",
            forced_fallback_reason=fallback_reason,
            active_agent_mode="deterministic-fallback",
            model_call_count=model_call_count,
        )

    bedrock_status = "mocked" if synth_metadata.get("mode") == "bedrock-mock" else "real"
    safety, step = safety_gate(request, briefing)
    trace.append(step)
    return _build_response(
        request_summary,
        config,
        trace,
        state["location"],
        state["scene"],
        state.get("map_features", []),
        state.get("live_feature_status", {}),
        state["hazards"],
        state["annotations"],
        briefing,
        state["evidence"],
        safety,
        bedrock_status,
        None,
        fixture_pack,
        active_agent_mode="llm-planner",
        model_call_count=model_call_count,
    )


def _execute_planner_tool_calls(
    request: dict[str, Any],
    request_summary: dict[str, Any],
    fixture_pack: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    config: RuntimeConfig,
) -> dict[str, Any]:
    state: dict[str, Any] = {"executed_tools": []}
    allowlist = {schema["name"] for schema in PLANNER_TOOL_SCHEMAS}
    for call in tool_calls[:8]:
        name = str(call.get("name", "")).strip()
        if name not in allowlist:
            raise PlannerExecutionError(
                f"Planner requested disallowed tool '{name}'.",
                rejected_tool=name,
            )
        trace.append(
            trace_step(
                "llm_planner_tool_call",
                "ok",
                f"Planner tool request accepted for allowlisted local tool: {name}.",
                {
                    "toolName": name,
                    "argumentsIgnored": bool(call.get("arguments")),
                    "allowlisted": True,
                },
                source_ids=["bedrock-briefing"],
            )
        )
        _run_planner_tool(name, request, request_summary, fixture_pack, state, trace, config)
        state["executed_tools"].append(name)

    required = {"location", "features", "scene", "planning_text", "hazards", "annotations", "briefing", "evidence"}
    missing = sorted(required.difference(state))
    if missing:
        raise PlannerExecutionError(f"Planner did not complete required local tools: {', '.join(missing)}.")
    return state


def _run_planner_tool(
    name: str,
    request: dict[str, Any],
    request_summary: dict[str, Any],
    fixture_pack: dict[str, Any] | None,
    state: dict[str, Any],
    trace: list[dict[str, Any]],
    config: RuntimeConfig,
) -> None:
    if name == "resolve_location":
        location, step = resolve_location(request, fixture_pack=fixture_pack)
        state["location"] = location
    elif name == "fetch_geospatial_features":
        _require_state(state, "location", name)
        features, step = load_geospatial_features(
            state["location"],
            simulate_failure=bool(request_summary["simulateMapFailure"]),
            fixture_pack=fixture_pack,
            config=config,
        )
        state["features"] = features
        state["map_features"] = features
        state["live_feature_status"] = step.get("output", {}).get("liveFeatureStatus") or {}
    elif name == "build_scene":
        _require_state(state, "location", name)
        _require_state(state, "features", name)
        scene, step = build_scene_config(state["location"], state["features"], fixture_pack=fixture_pack)
        state["scene"] = scene
    elif name == "load_planning_fixture":
        planning_text, step = load_planning_context(
            include_planning_fixture=bool(request_summary["includePlanningFixture"]),
            fixture_pack=fixture_pack,
        )
        state["planning_text"] = planning_text
    elif name == "extract_hazard_notes":
        _require_state(state, "features", name)
        _require_state(state, "planning_text", name)
        hazards, step = extract_hazard_notes(state["planning_text"], state["features"], fixture_pack=fixture_pack)
        state["hazards"] = hazards
    elif name == "create_annotations":
        _require_state(state, "location", name)
        _require_state(state, "hazards", name)
        annotations, step = create_annotations(state["location"], state["hazards"])
        state["annotations"] = annotations
    elif name == "generate_site_brief":
        _require_state(state, "location", name)
        _require_state(state, "hazards", name)
        _require_state(state, "planning_text", name)
        briefing, evidence, step = generate_site_brief(
            state["location"],
            state["hazards"],
            state["planning_text"],
            fixture_pack=fixture_pack,
        )
        state["briefing"] = briefing
        state["evidence"] = evidence
    else:
        raise PlannerExecutionError(f"Planner requested disallowed tool '{name}'.", rejected_tool=name)
    trace.append(step)


def _require_state(state: dict[str, Any], key: str, tool_name: str) -> None:
    if key not in state:
        raise PlannerExecutionError(f"Planner tool '{tool_name}' ran before required state '{key}' existed.")


def _planner_fallback_step(reason: str, model_call_count: int) -> dict[str, Any]:
    return trace_step(
        "llm_planner_model_plan",
        "fallback",
        "LLM planner unavailable; deterministic fallback remains active.",
        {"mode": "deterministic-fallback", "modelCallCount": model_call_count},
        source_ids=["bedrock-briefing"],
        fallback_reason=reason,
    )


def _build_response(
    request_summary: dict[str, Any],
    config: RuntimeConfig,
    trace: list[dict[str, Any]],
    location: dict[str, Any],
    scene: dict[str, Any],
    map_features: list[dict[str, Any]],
    live_feature_status: dict[str, Any],
    hazards: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    briefing: dict[str, Any],
    evidence: list[dict[str, Any]],
    safety: dict[str, Any],
    bedrock_status: str,
    bedrock_fallback_reason: str | None,
    fixture_pack: dict[str, Any] | None,
    *,
    active_agent_mode: str,
    model_call_count: int,
) -> dict[str, Any]:
    sources = source_register(
        include_planning_fixture=request_summary["includePlanningFixture"],
        simulate_map_failure=request_summary["simulateMapFailure"],
        bedrock_status=bedrock_status,
        config=config,
        fixture_pack=fixture_pack,
    )
    runtime = config.public_runtime(status=bedrock_status, fallback_reason=bedrock_fallback_reason)
    runtime["agentMode"] = request_summary["agentMode"]
    runtime["activeAgentMode"] = active_agent_mode
    runtime["modelCallCount"] = model_call_count
    runtime["plannerToolSchemas"] = PLANNER_TOOL_SCHEMAS if request_summary["agentMode"] == "llm-planner" else []
    runtime["fixturePack"] = fixture_pack["name"] if fixture_pack else None
    runtime["fixturePackMode"] = "cached-public-fixture" if fixture_pack else "synthetic-default"
    runtime["liveApiCalls"] = bool(live_feature_status.get("successfulSources"))
    runtime["liveFeatureStatus"] = live_feature_status
    llm_plan = _llm_plan_payload(trace)
    llm_tool_calls = _llm_tool_call_payload(trace)
    model_calls = _model_call_payload(trace)
    fallback = _fallback_payload(trace, bedrock_fallback_reason)
    token_usage = _token_usage_payload(trace)

    return {
        "runId": "demo1-local-run",
        "request": request_summary,
        "runtime": runtime,
        "llmPlan": llm_plan,
        "llmToolCalls": llm_tool_calls,
        "modelCalls": model_calls,
        "tokenUsage": token_usage,
        "fallback": fallback,
        "location": location,
        "scene": scene,
        "mapFeatures": map_features,
        "liveFeatureStatus": live_feature_status,
        "hazards": hazards if safety["allowed"] else [],
        "annotations": annotations if safety["allowed"] else [],
        "briefing": briefing,
        "evidence": evidence,
        "sources": sources,
        "safety": safety,
        "trace": trace,
        "architecture": architecture_snapshot(trace, request_summary, sources, evidence, safety, runtime),
    }


def _llm_plan_payload(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    plan_step = next((step for step in trace if step["name"] == "llm_planner_model_plan"), None)
    if not plan_step:
        return None
    output = plan_step.get("output", {})
    return {
        "status": plan_step["status"],
        "rationale": output.get("rationale") or plan_step["summary"],
        "toolCalls": output.get("toolCalls", []),
        "allowedTools": output.get("allowedTools", []),
        "fallbackReason": plan_step.get("fallbackReason"),
    }


def _llm_tool_call_payload(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for step in trace:
        if step["name"] == "llm_planner_tool_call":
            output = step.get("output", {})
            calls.append(
                {
                    "id": step["id"],
                    "name": output.get("toolName"),
                    "status": step["status"],
                    "summary": step["summary"],
                    "allowlisted": output.get("allowlisted", False),
                    "argumentsIgnored": output.get("argumentsIgnored", False),
                }
            )
    return calls


def _model_call_payload(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for step in trace:
        if step["name"] in {"llm_planner_model_plan", "llm_planner_synthesis", "generate_bedrock_briefing"}:
            output = step.get("output", {})
            if output.get("modelId"):
                calls.append(
                    {
                        "id": step["id"],
                        "phase": output.get("phase") or step["name"],
                        "status": step["status"],
                        "summary": step["summary"],
                        "modelId": output.get("modelId"),
                        "awsRegion": output.get("awsRegion"),
                        "latencyMs": output.get("latencyMs", step.get("durationMs")),
                        "modelCallCount": output.get("modelCallCount"),
                        "maxModelCalls": output.get("maxModelCalls"),
                    }
                )
    return calls


def _fallback_payload(trace: list[dict[str, Any]], runtime_fallback_reason: str | None) -> dict[str, Any]:
    fallback_step = next(
        (step for step in trace if step.get("fallbackReason") or step["status"] == "fallback"),
        None,
    )
    if fallback_step:
        return {
            "status": fallback_step["status"],
            "trigger": fallback_step["name"],
            "reason": fallback_step.get("fallbackReason") or runtime_fallback_reason,
        }
    return {
        "status": "available",
        "trigger": None,
        "reason": "Deterministic fallback remains available if the LLM path is disabled, rejected, or fails.",
    }


def _token_usage_payload(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    usage = [step.get("output", {}).get("tokenUsage") for step in trace if step.get("output", {}).get("tokenUsage")]
    if not usage:
        return None
    return {
        "inputTokens": sum(int(item.get("inputTokens", 0)) for item in usage),
        "outputTokens": sum(int(item.get("outputTokens", 0)) for item in usage),
        "totalTokens": sum(int(item.get("totalTokens", 0)) for item in usage),
    }
