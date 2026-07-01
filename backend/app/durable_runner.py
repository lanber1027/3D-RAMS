from __future__ import annotations

import time
from dataclasses import replace
from threading import Thread
from typing import Any

from .bedrock_adapter import (
    BedrockAdapterError,
    generate_bedrock_output_evaluation,
    generate_bedrock_planner_synthesis,
    generate_bedrock_risk_reasoning,
    generate_bedrock_tool_plan,
)
from .chat_agent import _agent_runtime_state, _compose_assistant_message, _parse_message_to_request, _upload_trace
from .config import RuntimeConfig
from .fixtures import load_fixture_pack
from .location_resolver import confirmed_location_to_request, public_candidate_by_id
from .run_store import (
    append_step,
    append_tool_result,
    create_run_record,
    get_run_record,
    is_cancel_requested,
    public_run,
    request_cancel,
    update_run,
)
from .session_store import add_run, get_session
from .tool_registry import ToolExecutionError, default_tool_sequence, execute_tool, tool_schemas
from .tools import architecture_snapshot, normalize_request, source_register, trace_step


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "waiting_for_clarification", "waiting_for_location_confirmation", "waiting_for_approval"}

_TOOL_ALIASES = {
    "fetch_geospatial_features": "load_geospatial_features",
    "build_scene": "build_scene_config",
    "load_planning_fixture": "load_planning_context",
    "generate_site_brief": "compile_review_pack",
}

_MAX_EVALUATION_LOOPS = 3
_FINAL_SAFETY_TOOL = "safety_gate"
_INITIAL_REQUIRED_TOOLS = [
    "resolve_location",
    "load_geospatial_features",
    "build_scene_config",
    "load_planning_context",
    "extract_hazard_notes",
    "rank_risks",
    "create_annotations",
    "compile_review_pack",
]


def create_durable_run(
    *,
    session_id: str,
    message: str,
    uploaded_file_ids: list[str],
    use_bedrock: bool,
    auto_start: bool,
    config: RuntimeConfig,
) -> dict[str, Any]:
    get_session(session_id, config)
    run = create_run_record(
        session_id=session_id,
        message=message,
        uploaded_file_ids=uploaded_file_ids,
        use_bedrock=use_bedrock,
        config=config,
    )
    if auto_start:
        if config.durable_run_process_inline:
            execute_durable_run(run["runId"], config)
        else:
            Thread(target=execute_durable_run, args=(run["runId"], config), daemon=True).start()
    return public_run(get_run_record(run["runId"]))


def read_durable_run(run_id: str) -> dict[str, Any]:
    return public_run(get_run_record(run_id))


def cancel_durable_run(run_id: str) -> dict[str, Any]:
    return request_cancel(run_id)


def confirm_location_for_run(run_id: str, candidate_id: str, config: RuntimeConfig) -> dict[str, Any]:
    run = get_run_record(run_id)
    if run["status"] != "waiting_for_location_confirmation":
        raise ToolExecutionError("Run is not waiting for location confirmation.")
    location_resolution = run.get("locationResolution") or {}
    candidate = public_candidate_by_id(candidate_id, location_resolution.get("locationCandidates", []))
    if not candidate:
        raise ToolExecutionError("Location candidate was not found for this run.")
    original_use_bedrock = bool(run["request"]["useBedrock"])
    if config.bedrock_requested != original_use_bedrock:
        config = replace(
            config,
            bedrock_requested=original_use_bedrock,
            bedrock_enabled=config.bedrock_enabled and original_use_bedrock,
        )
    append_step(
        run_id,
        name="location_confirmation",
        status="ok",
        summary="User confirmed a source-labelled candidate location before review tools started.",
        output={
            "candidateId": candidate.get("candidateId"),
            "name": candidate.get("name"),
            "confidence": candidate.get("confidence"),
            "source": candidate.get("source"),
            "dataMode": candidate.get("dataMode"),
        },
    )
    update_run(
        run_id,
        status="running",
        currentStep="location_confirmation",
        confirmedLocation=candidate,
        locationResolution={
            **location_resolution,
            "needsLocationConfirmation": False,
            "confirmedLocation": candidate,
            "nextStage": "run_review_workflow",
        },
    )
    execute_durable_run(run_id, config)
    return public_run(get_run_record(run_id))


def execute_durable_run(run_id: str, config: RuntimeConfig) -> None:
    started = time.perf_counter()
    deadline = started + config.durable_run_timeout_seconds
    run = get_run_record(run_id)
    if run["status"] in TERMINAL_STATUSES:
        return

    if is_cancel_requested(run_id):
        request_cancel(run_id)
        return

    update_run(run_id, status="running", currentStep="parse_request")
    append_step(run_id, name="parse_request", status="running", summary="Parsing natural-language request.")
    if run.get("confirmedLocation"):
        request = confirmed_location_to_request(
            run["confirmedLocation"],
            message=run["request"]["message"],
            use_bedrock=bool(run["request"]["useBedrock"]),
        )
        parse_trace = [
            trace_step(
                "parse_user_request",
                "ok",
                "Using the user-confirmed location candidate to start the review workflow.",
                {
                    "siteName": request.get("siteName"),
                    "confirmedLocation": run["confirmedLocation"].get("candidateId"),
                    "locationConfidence": run["confirmedLocation"].get("confidence"),
                    "source": run["confirmedLocation"].get("source"),
                    "nextStage": "run_review_workflow",
                },
                source_ids=[run["confirmedLocation"].get("source")] if run["confirmedLocation"].get("source") else [],
            )
        ]
        clarification: list[str] = []
        location_resolution = None
        safety_block = None
    else:
        request, parse_trace, clarification, location_resolution, safety_block = _parse_message_to_request(
            run["request"]["message"],
            run["request"]["uploadedFileIds"],
            bool(run["request"]["useBedrock"]),
        )
    _merge_trace(run_id, parse_trace)
    if safety_block:
        _finish_safety_blocked(run_id, safety_block, started, config)
        return
    if location_resolution:
        _finish_location_confirmation(run_id, location_resolution, clarification, started, config)
        return
    if clarification:
        _finish_clarification(run_id, clarification, started, config)
        return

    request_summary = normalize_request(request)
    fixture_pack, fixture_pack_warning = load_fixture_pack(request_summary["fixturePack"])
    if fixture_pack:
        pack_location = fixture_pack["location"]
        request_summary["fixturePack"] = fixture_pack["name"]
        request_summary["siteName"] = pack_location["label"]
        request_summary["latitude"] = float(pack_location["latitude"])
        request_summary["longitude"] = float(pack_location["longitude"])
        request["siteName"] = pack_location["label"]
        request["latitude"] = request_summary["latitude"]
        request["longitude"] = request_summary["longitude"]
        request["fixturePack"] = fixture_pack["name"]
    context: dict[str, Any] = {
        "request": request,
        "requestSummary": request_summary,
        "fixturePack": fixture_pack,
        "fixturePackWarning": fixture_pack_warning,
        "executedTools": [],
        "trace": parse_trace[:],
    }
    if fixture_pack_warning:
        fallback_step = trace_step(
            "load_fixture_pack",
            "fallback",
            fixture_pack_warning["reason"],
            fixture_pack_warning,
            fallback_reason=fixture_pack_warning["reason"],
        )
        context["trace"].append(fallback_step)
        _merge_trace(run_id, [fallback_step])

    try:
        _checkpoint(run_id, "planner", "running", "Selecting allowlisted tools for the durable run.", deadline=deadline)
        tool_plan = _plan_tools(run_id, request_summary, config)
        _checkpoint(
            run_id,
            "tool_loop",
            "running",
            "Executing allowlisted tools with a checkpoint after each result.",
            {"toolPlan": tool_plan},
            deadline=deadline,
        )
        _execute_tool_loop(run_id, tool_plan, context, config, deadline=deadline)
        _checkpoint(run_id, "risk_reasoner", "running", "Ranking risks and uncertainty from tool results.", deadline=deadline)
        reasoning = _reason_over_risks(run_id, context, config, deadline=deadline)
        context["reasoning"] = reasoning
        _checkpoint(run_id, "compiler", "running", "Compiling the final review pack from checkpointed state.", deadline=deadline)
        _compile_output(run_id, context, config, started, deadline=deadline)
    except _RunCancelled:
        _finish_cancelled(run_id, "Run cancelled during worker execution.")
    except _RunTimedOut as exc:
        _finish_failed(run_id, exc)
    except (BedrockAdapterError, ToolExecutionError, Exception) as exc:
        _finish_failed(run_id, exc)


def _plan_tools(run_id: str, request_summary: dict[str, Any], config: RuntimeConfig) -> list[str]:
    if _consume_model_call(run_id, config, phase="planner"):
        try:
            phase_config = replace(config, bedrock_max_tokens=config.planner_output_tokens)
            plan, metadata = generate_bedrock_tool_plan(
                config=phase_config,
                request_summary=request_summary,
                tool_schemas=tool_schemas(),
            )
            requested = [_normalise_tool_name(str(call.get("name", ""))) for call in plan.get("tool_calls", [])]
            validation = _validate_tool_plan(requested)
            if not validation["valid"]:
                append_step(
                    run_id,
                    name="planner_invalid_plan",
                    status="fallback",
                    summary="Planner returned an unsafe or incomplete tool order; default allowlisted sequence will be used.",
                    output={"requestedTools": requested, "planIssues": validation["issues"]},
                )
                update_run(run_id, fallbackReason=f"Planner tool plan rejected: {'; '.join(validation['issues'])}.")
                return _initial_tool_sequence()
            append_step(
                run_id,
                name="planner_model_call",
                status="ok",
                summary="Planner selected allowlisted tools for the durable run.",
                output={
                    **metadata,
                    "rationale": plan.get("rationale"),
                    "requestedTools": requested,
                    "phaseTokenBudget": config.planner_output_tokens,
                },
            )
            return _initial_tool_sequence(requested)
        except BedrockAdapterError:
            raise
        except Exception as exc:
            append_step(
                run_id,
                name="planner_model_call",
                status="fallback",
                summary="Planner model call failed; default deterministic tool sequence will be used.",
                output={"errorType": exc.__class__.__name__},
            )
            update_run(run_id, fallbackReason=f"Planner model call failed: {exc}")
            return _initial_tool_sequence()

    append_step(
        run_id,
        name="planner_model_call",
        status="fallback",
        summary="Bedrock planner is disabled or model-call budget is zero; default tool sequence will be used.",
        output={"bedrockEnabled": config.bedrock_enabled, "modelCallsUsed": get_run_record(run_id)["modelCallsUsed"]},
    )
    return _initial_tool_sequence()


def _execute_tool_loop(
    run_id: str,
    tool_plan: list[str],
    context: dict[str, Any],
    config: RuntimeConfig,
    *,
    deadline: float,
) -> None:
    for index, raw_name in enumerate(tool_plan):
        tool_name = _normalise_tool_name(raw_name)
        _execute_single_tool(run_id, tool_name, context, config, deadline=deadline, tool_index=index + 1)


def _execute_single_tool(
    run_id: str,
    tool_name: str,
    context: dict[str, Any],
    config: RuntimeConfig,
    *,
    deadline: float,
    tool_index: int | None = None,
    retry_loop: int | None = None,
) -> dict[str, Any]:
    _raise_if_stopped(run_id, deadline)
    run = get_run_record(run_id)
    if len(run.get("toolResults", [])) >= config.durable_run_max_tool_calls:
        append_step(
            run_id,
            name="max_tool_calls",
            status="failed",
            summary="Durable run stopped because the maximum tool-call count was reached.",
            output={"maxToolCalls": config.durable_run_max_tool_calls},
        )
        raise ToolExecutionError("Maximum tool-call count reached.")
    step_output: dict[str, Any] = {"toolName": tool_name}
    if tool_index is not None:
        step_output["toolIndex"] = tool_index
    if retry_loop is not None:
        step_output["evaluationLoop"] = retry_loop
    append_step(
        run_id,
        name=f"tool:{tool_name}",
        status="running",
        summary=f"Executing allowlisted tool {tool_name}.",
        output=step_output,
    )
    result = execute_tool(tool_name, context)
    context["executedTools"].append(tool_name)
    if tool_name == "compile_review_pack":
        context["deterministicBriefing"] = dict(context.get("briefing") or {})
        context["deterministicEvidence"] = list(context.get("evidence") or [])
    trace = result.get("trace")
    if trace:
        context["trace"].append(trace)
        _merge_trace(run_id, [trace])
    append_tool_result(
        run_id,
        tool_name=tool_name,
        status="ok",
        output=_public_tool_output(tool_name, result),
    )
    update_run(
        run_id,
        currentStep=f"tool:{tool_name}",
        partialUiState=_partial_ui_state(context),
    )
    return result


def _reason_over_risks(
    run_id: str,
    context: dict[str, Any],
    config: RuntimeConfig,
    *,
    deadline: float,
) -> dict[str, Any]:
    _raise_if_stopped(run_id, deadline)
    if _consume_model_call(run_id, config, phase="reasoner"):
        try:
            phase_config = replace(config, bedrock_max_tokens=config.reasoner_output_tokens)
            reasoning, metadata = generate_bedrock_risk_reasoning(
                config=phase_config,
                location=context.get("location", {}),
                hazards=context.get("hazards", []),
                evidence=context.get("evidence", []),
                executed_tools=context.get("executedTools", []),
            )
            append_step(
                run_id,
                name="reasoner_model_call",
                status="ok",
                summary="Risk reasoner ranked hazards and uncertainty from tool outputs.",
                output={**metadata, "reasoning": reasoning, "phaseTokenBudget": config.reasoner_output_tokens},
            )
            return reasoning
        except BedrockAdapterError:
            raise
        except Exception as exc:
            append_step(
                run_id,
                name="reasoner_model_call",
                status="fallback",
                summary="Risk reasoner model call failed; deterministic reasoning remains active.",
                output={"errorType": exc.__class__.__name__},
            )
            update_run(run_id, fallbackReason=f"Reasoner model call failed: {exc}")

    reasoning = {
        "ranked_risks": [
            {
                "title": hazard.get("title"),
                "reason": hazard.get("note"),
                "confidence": hazard.get("confidence", "medium"),
                "evidence_ids": hazard.get("evidenceIds", []),
            }
            for hazard in context.get("hazards", [])[:5]
        ],
        "uncertainties": [
            "Live source freshness is not guaranteed in the cached fixture path.",
            "Human review is required before any RAMS or work-planning use.",
        ],
        "approval_required": True,
    }
    append_step(
        run_id,
        name="reasoner_model_call",
        status="fallback",
        summary="Reasoner used deterministic ranking because live/model budget was unavailable.",
        output={"reasoning": reasoning, "mode": "deterministic-gate1"},
    )
    return reasoning


def _compile_output(
    run_id: str,
    context: dict[str, Any],
    config: RuntimeConfig,
    started: float,
    *,
    deadline: float,
) -> None:
    _raise_if_stopped(run_id, deadline)
    if _consume_model_call(run_id, config, phase="compiler"):
        try:
            phase_config = replace(config, bedrock_max_tokens=config.compiler_output_tokens)
            briefing, metadata = generate_bedrock_planner_synthesis(
                config=phase_config,
                location=context["location"],
                hazards=context["hazards"],
                deterministic_briefing=context["briefing"],
                evidence=context["evidence"],
                planning_available=context.get("planningText") is not None,
                executed_tools=context["executedTools"],
            )
            context["briefing"] = briefing
            append_step(
                run_id,
                name="compiler_model_call",
                status="ok",
                summary="Compiler produced final user-facing review pack from checkpointed tool outputs.",
                output={**metadata, "phaseTokenBudget": config.compiler_output_tokens},
            )
        except BedrockAdapterError:
            raise
        except Exception as exc:
            append_step(
                run_id,
                name="compiler_model_call",
                status="fallback",
                summary="Compiler model call failed; deterministic review pack remains active.",
                output={"errorType": exc.__class__.__name__},
            )
            update_run(run_id, fallbackReason=f"Compiler model call failed: {exc}")

    evaluation = _run_output_evaluation_loop(run_id, context, config, deadline=deadline)

    _raise_if_stopped(run_id, deadline)
    final_safety = _execute_single_tool(run_id, _FINAL_SAFETY_TOOL, context, config, deadline=deadline)
    safety = context["safety"]
    if not safety["allowed"]:
        run = get_run_record(run_id)
        run["toolResults"][-1]["status"] = "blocked"
        run["toolResults"][-1]["output"] = {"safety": safety}

    _raise_if_stopped(run_id, deadline)
    run = get_run_record(run_id)
    trace = context["trace"]
    safety = context.get("safety")
    if safety is None:
        raise ToolExecutionError("safety_gate did not run before final compilation.")
    sources = source_register(
        include_planning_fixture=context["requestSummary"]["includePlanningFixture"],
        simulate_map_failure=context["requestSummary"]["simulateMapFailure"],
        bedrock_status=_briefing_mode(run, config),
        config=config,
        fixture_pack=context.get("fixturePack"),
    )
    runtime = config.public_runtime(status=_briefing_mode(run, config), fallback_reason=run.get("fallbackReason"))
    runtime.update(
        {
            "hostedProductMode": True,
            "durableRunApi": True,
            "activeAgentMode": "durable-tool-loop",
            "modelCallCount": run["modelCallsUsed"],
            "fixturePack": context["fixturePack"]["name"] if context.get("fixturePack") else None,
            "fixturePackMode": "cached-public-fixture" if context.get("fixturePack") else "synthetic-default",
            "sessionTraceMode": "memory",
            "liveApiCalls": bool(context.get("liveFeatureStatus", {}).get("successfulSources")),
            "liveFeatureStatus": context.get("liveFeatureStatus", {}),
            "evaluationStopReason": evaluation["evaluationStopReason"],
            "evaluationLoopCount": evaluation["loopCount"],
            "evaluationPassed": evaluation["passed"],
            "latencyMs": int((time.perf_counter() - started) * 1000),
        }
    )
    architecture = architecture_snapshot(
        trace,
        context["requestSummary"],
        sources,
        context["evidence"],
        safety,
        runtime,
    )
    ui_state = {
        "location": context["location"],
        "scene": context["scene"],
        "mapFeatures": context.get("mapFeatures", context.get("features", [])),
        "liveFeatureStatus": context.get("liveFeatureStatus", {}),
        "annotations": context["annotations"] if safety["allowed"] else [],
        "hazards": context["hazards"] if safety["allowed"] else [],
        "evidence": context["evidence"],
        "sources": sources,
        "briefing": context["briefing"],
        "safety": safety,
        "trace": trace,
        "architecture": architecture,
        "reasoning": context.get("reasoning"),
        "evaluation": evaluation,
    }
    result = {
        "sessionId": run["sessionId"],
        "runId": run_id,
        "assistantMessage": _compose_assistant_message(
            {
                "briefing": context["briefing"],
                "safety": safety,
                "location": context["location"],
            },
            run["request"]["uploadedFileIds"],
            _agent_runtime_state(),
        ),
        "needsClarification": False,
        "clarifyingQuestions": [],
        "agent": _agent_runtime_state(),
        "uiState": ui_state,
        "runtime": runtime,
        "trace": trace,
        "evidence": context["evidence"],
        "scene": context["scene"],
        "mapFeatures": ui_state["mapFeatures"],
        "liveFeatureStatus": ui_state["liveFeatureStatus"],
        "annotations": ui_state["annotations"],
        "briefing": context["briefing"],
        "safety": safety,
        "evaluation": evaluation,
        "evaluationStopReason": evaluation["evaluationStopReason"],
        "fallback": {
            "status": "available" if not run.get("fallbackReason") else "fallback",
            "trigger": None,
            "reason": run.get("fallbackReason")
            or "Deterministic fallback remains available if the model/tool path fails.",
        },
        "modelCalls": _model_call_payload(run),
        "tokenUsage": _token_usage_payload(run),
    }
    update_run(
        run_id,
        status="completed",
        currentStep="completed",
        partialUiState=ui_state,
        finalUiState=ui_state,
        safetyResult=safety,
        result=result,
        runtime=runtime,
    )
    _record_session_run_summary(run_id, result, config)


def _run_output_evaluation_loop(
    run_id: str,
    context: dict[str, Any],
    config: RuntimeConfig,
    *,
    deadline: float,
) -> dict[str, Any]:
    last_evaluation: dict[str, Any] | None = None
    for loop in range(1, _MAX_EVALUATION_LOOPS + 1):
        _raise_if_stopped(run_id, deadline)
        evaluation = _evaluate_output_quality(context, loop=loop)
        evaluation = _maybe_run_llm_evaluator(run_id, context, config, evaluation)
        last_evaluation = evaluation
        context["evaluation"] = evaluation
        status = "ok" if evaluation["passed"] else "warning"
        summary = (
            "Output evaluation passed deterministic grounding, relevance, completeness, and safety checks."
            if evaluation["passed"]
            else "Output evaluation found weak grounding, relevance, completeness, or safety and may retry tools."
        )
        append_step(
            run_id,
            name="output_evaluation",
            status=status,
            summary=summary,
            output=evaluation,
        )
        eval_trace = trace_step(
            "evaluate_output_quality",
            status,
            summary,
            evaluation,
            evidence_ids=[item.get("id") for item in context.get("evidence", []) if item.get("id")],
        )
        context["trace"].append(eval_trace)
        _merge_trace(run_id, [eval_trace])
        update_run(run_id, partialUiState=_partial_ui_state(context))

        if evaluation["passed"]:
            evaluation["evaluationStopReason"] = "passed" if loop == 1 else "passed_after_retry"
            context["evaluation"] = evaluation
            update_run(run_id, partialUiState=_partial_ui_state(context))
            return evaluation

        if loop >= _MAX_EVALUATION_LOOPS:
            evaluation["evaluationStopReason"] = "max_evaluation_loops"
            _apply_safer_deterministic_briefing(context, reason="Evaluation remained below quality threshold after maximum loops.")
            update_run(
                run_id,
                fallbackReason="Output evaluation reached max loops; returned deterministic safer briefing without unsupported evidence.",
                partialUiState=_partial_ui_state(context),
            )
            append_step(
                run_id,
                name="output_evaluation_stop",
                status="fallback",
                summary="Evaluation stopped at the configured maximum loop count.",
                output={"evaluationStopReason": evaluation["evaluationStopReason"], "maxEvaluationLoops": _MAX_EVALUATION_LOOPS},
            )
            context["evaluation"] = evaluation
            return evaluation

        retry_tools = _retry_tools_for_evaluation(run_id, evaluation, context, config)
        if not retry_tools:
            evaluation["evaluationStopReason"] = "tool_budget_reached"
            _apply_safer_deterministic_briefing(context, reason="No retry tool budget remained after evaluation failure.")
            update_run(
                run_id,
                fallbackReason="Output evaluation failed and no retry tool budget remained; returned deterministic safer briefing.",
                partialUiState=_partial_ui_state(context),
            )
            append_step(
                run_id,
                name="output_evaluation_stop",
                status="fallback",
                summary="Evaluation stopped because the bounded tool-call budget left no retry room.",
                output={
                    "evaluationStopReason": evaluation["evaluationStopReason"],
                    "requestedRetryTools": evaluation.get("retryTools", []),
                    "maxToolCalls": config.durable_run_max_tool_calls,
                },
            )
            context["evaluation"] = evaluation
            return evaluation

        append_step(
            run_id,
            name="output_improvement_loop",
            status="running",
            summary="Retrying bounded tools selected by the output evaluator.",
            output={"evaluationLoop": loop, "retryTools": retry_tools},
        )
        for tool_name in retry_tools:
            _execute_single_tool(run_id, tool_name, context, config, deadline=deadline, retry_loop=loop)

    fallback = last_evaluation or _evaluate_output_quality(context, loop=_MAX_EVALUATION_LOOPS)
    fallback["evaluationStopReason"] = "max_evaluation_loops"
    context["evaluation"] = fallback
    return fallback


def _evaluate_output_quality(context: dict[str, Any], *, loop: int) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    retry_tools: list[str] = []
    scores = {"grounding": 1.0, "relevance": 1.0, "completeness": 1.0, "safety": 1.0}

    executed = set(context.get("executedTools", []))
    missing_tools = [tool for tool in _INITIAL_REQUIRED_TOOLS if tool not in executed]
    if missing_tools:
        scores["completeness"] = 0.0
        issues.append({"code": "missing_required_tools", "message": "Required review tools did not all run.", "tools": missing_tools})
        retry_tools.extend(missing_tools)

    location = context.get("location") or {}
    scene = context.get("scene") or {}
    hazards = list(context.get("hazards") or [])
    annotations = list(context.get("annotations") or [])
    evidence = list(context.get("evidence") or [])
    briefing = context.get("briefing") or {}
    evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
    hazard_titles = {str(hazard.get("title")) for hazard in hazards if hazard.get("title")}

    if not location or not scene or not isinstance(briefing, dict) or not briefing:
        scores["completeness"] = min(scores["completeness"], 0.25)
        issues.append({"code": "missing_core_output", "message": "Location, scene, or briefing output is missing."})
        retry_tools.extend(["resolve_location", "load_geospatial_features", "build_scene_config", "compile_review_pack"])

    if not hazards:
        scores["completeness"] = min(scores["completeness"], 0.4)
        issues.append({"code": "missing_hazards", "message": "No hazard candidates were available for review."})
        retry_tools.extend(["extract_hazard_notes", "rank_risks", "create_annotations", "compile_review_pack"])

    if not annotations and hazards:
        scores["completeness"] = min(scores["completeness"], 0.6)
        issues.append({"code": "missing_annotations", "message": "Hazards were found but map annotations are missing."})
        retry_tools.append("create_annotations")

    invalid_hazard_refs = _invalid_hazard_evidence_refs(hazards, evidence_ids)
    if invalid_hazard_refs:
        scores["grounding"] = 0.0
        issues.append(
            {
                "code": "invalid_hazard_evidence",
                "message": "One or more non-provisional hazards lack valid evidence references.",
                "hazardIds": invalid_hazard_refs,
            }
        )
        if evidence_ids:
            retry_tools.extend(["extract_hazard_notes", "rank_risks", "create_annotations", "compile_review_pack"])
        else:
            retry_tools.append("compile_review_pack")

    if not evidence and any(_requires_site_evidence(hazard) for hazard in hazards):
        scores["grounding"] = 0.0
        issues.append({"code": "missing_evidence_register", "message": "Site-evidence hazards exist but the evidence register is empty."})
        retry_tools.append("compile_review_pack")

    priority_checks = _string_list(briefing.get("priority_checks"))
    unsupported_checks = [item for item in priority_checks if item not in hazard_titles]
    if unsupported_checks:
        scores["grounding"] = 0.0
        issues.append(
            {
                "code": "unsupported_priority_checks",
                "message": "Briefing priority checks must be grounded in current hazard titles.",
                "unsupportedChecks": unsupported_checks,
            }
        )
        retry_tools.append("compile_review_pack")

    site_label = str(location.get("label") or "")
    if site_label and briefing.get("site") and str(briefing.get("site")) != site_label:
        scores["relevance"] = 0.0
        issues.append({"code": "site_mismatch", "message": "Briefing site label does not match the resolved location."})
        retry_tools.append("compile_review_pack")

    required_briefing_sections = ["headline", "summary", "priority_checks", "before_site_visit", "limitations"]
    missing_sections = [section for section in required_briefing_sections if not briefing.get(section)]
    if missing_sections:
        scores["completeness"] = min(scores["completeness"], 0.5)
        issues.append({"code": "missing_briefing_sections", "message": "Briefing is missing required review sections.", "sections": missing_sections})
        retry_tools.append("compile_review_pack")

    unsafe_terms = _unsupported_safety_claims(briefing)
    if unsafe_terms:
        scores["safety"] = 0.0
        issues.append({"code": "unsafe_generated_claim", "message": "Briefing contains unsupported safety or approval claims.", "terms": unsafe_terms})

    retry_tools = _dedupe_tools(_expand_retry_dependencies(retry_tools))
    passed = all(score >= 0.75 for score in scores.values()) and not issues
    return {
        "loop": loop,
        "loopCount": loop,
        "passed": passed,
        "scores": scores,
        "issues": issues,
        "missingTools": missing_tools,
        "retryTools": retry_tools,
        "maxEvaluationLoops": _MAX_EVALUATION_LOOPS,
        "evaluationStopReason": "pending",
        "llmEvaluator": {"used": False, "reason": "not_attempted"},
    }


def _maybe_run_llm_evaluator(
    run_id: str,
    context: dict[str, Any],
    config: RuntimeConfig,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    if not config.bedrock_enabled:
        evaluation["llmEvaluator"] = {"used": False, "reason": "bedrock_disabled"}
        return evaluation
    run = get_run_record(run_id)
    if run["modelCallsUsed"] >= run["maxModelCalls"]:
        evaluation["llmEvaluator"] = {
            "used": False,
            "reason": "model_budget_exhausted",
            "modelCallsUsed": run["modelCallsUsed"],
            "maxModelCalls": run["maxModelCalls"],
        }
        return evaluation
    if not _consume_model_call(run_id, config, phase="output_evaluator"):
        evaluation["llmEvaluator"] = {"used": False, "reason": "model_budget_unavailable"}
        return evaluation
    try:
        llm_evaluation, metadata = generate_bedrock_output_evaluation(
            config=config,
            deterministic_evaluation=evaluation,
            location=context.get("location", {}),
            hazards=context.get("hazards", []),
            evidence=context.get("evidence", []),
            briefing=context.get("briefing", {}),
            executed_tools=context.get("executedTools", []),
        )
        append_step(
            run_id,
            name="output_evaluator_model_call",
            status="ok",
            summary="Optional model evaluator reviewed the deterministic quality gate output.",
            output={**metadata, "evaluation": llm_evaluation},
        )
        if not llm_evaluation.get("passed", True):
            evaluation["passed"] = False
            evaluation["issues"].append(
                {
                    "code": "llm_evaluator_issue",
                    "message": "Optional model evaluator reported additional quality concerns.",
                    "details": llm_evaluation.get("issues", []),
                }
            )
            evaluation["retryTools"] = _dedupe_tools(
                _expand_retry_dependencies([*evaluation.get("retryTools", []), *llm_evaluation.get("retryTools", [])])
            )
        evaluation["llmEvaluator"] = {"used": True, "result": llm_evaluation, "metadata": metadata}
    except Exception as exc:
        append_step(
            run_id,
            name="output_evaluator_model_call",
            status="fallback",
            summary="Optional model evaluator failed; deterministic quality gate remains authoritative.",
            output={"errorType": exc.__class__.__name__},
        )
        evaluation["llmEvaluator"] = {"used": False, "reason": f"model_evaluator_failed:{exc.__class__.__name__}"}
    return evaluation


def _retry_tools_for_evaluation(
    run_id: str,
    evaluation: dict[str, Any],
    context: dict[str, Any],
    config: RuntimeConfig,
) -> list[str]:
    requested = _dedupe_tools(evaluation.get("retryTools", []))
    if not requested:
        return []
    run = get_run_record(run_id)
    remaining = config.durable_run_max_tool_calls - len(run.get("toolResults", [])) - 1
    if remaining <= 0:
        return []
    runnable: list[str] = []
    available = set(context.get("executedTools", []))
    available.update(key for key in ("location", "features", "hazards", "briefing") if context.get(key))
    dependencies = {
        "resolve_location": set(),
        "load_geospatial_features": {"resolve_location", "location"},
        "build_scene_config": {"resolve_location", "load_geospatial_features", "location", "features"},
        "load_planning_context": set(),
        "extract_hazard_notes": {"load_geospatial_features", "features"},
        "rank_risks": {"extract_hazard_notes", "hazards"},
        "create_annotations": {"resolve_location", "rank_risks", "location", "hazards"},
        "compile_review_pack": {"resolve_location", "rank_risks", "load_planning_context", "location", "hazards"},
    }
    for tool_name in requested:
        if tool_name == _FINAL_SAFETY_TOOL:
            continue
        missing = dependencies.get(tool_name, set()).difference(available)
        if missing:
            continue
        runnable.append(tool_name)
        available.add(tool_name)
    return runnable[:remaining]


def _apply_safer_deterministic_briefing(context: dict[str, Any], *, reason: str) -> None:
    evidence_ids = {str(item.get("id")) for item in context.get("evidence", []) if item.get("id")}
    hazards = [
        hazard
        for hazard in context.get("hazards", [])
        if not _requires_site_evidence(hazard) or not _invalid_hazard_evidence_refs([hazard], evidence_ids)
    ]
    context["hazards"] = hazards
    context["annotations"] = [
        annotation
        for annotation in context.get("annotations", [])
        if annotation.get("id") in {hazard.get("id") for hazard in hazards}
    ]
    location = context.get("location") or {}
    context["briefing"] = {
        "site": location.get("label", "Resolved site"),
        "headline": "Evidence-limited review pack for human follow-up.",
        "summary": [
            "The agent could not verify enough grounding for the richer generated pack.",
            "Only explicitly labelled evidence and provisional review prompts are retained.",
            "No new site evidence is inferred in this fallback briefing.",
        ],
        "priority_checks": [str(hazard.get("title")) for hazard in hazards[:5] if hazard.get("title")],
        "before_site_visit": [
            "Re-check current official sources before using this pack for planning.",
            "Ask a competent reviewer to confirm missing or low-confidence evidence.",
            "Treat prompt-derived items as provisional review prompts, not site findings.",
        ],
        "limitations": [
            reason,
            "This output is not certified RAMS, emergency guidance, or work approval.",
            "Missing or low-confidence evidence is intentionally not filled in by the agent.",
        ],
        "generation_mode": "deterministic-safer-fallback",
    }


def _finish_clarification(
    run_id: str,
    clarification: list[str],
    started: float,
    config: RuntimeConfig,
) -> None:
    run = get_run_record(run_id)
    trace = [
        *run.get("steps", []),
        *list(run.get("partialUiState", {}).get("trace") or []),
    ]
    site_name = None
    for step in trace:
        if step.get("name") == "chat_parse_user_request":
            site_name = step.get("output", {}).get("siteName")
            break
    site_context = f" for {site_name}" if site_name else ""
    ui_state = {
        "location": None,
        "scene": None,
        "annotations": [],
        "hazards": [],
        "evidence": [],
        "sources": [],
        "briefing": None,
        "safety": {"allowed": True, "level": "needs_input", "message": "No briefing generated until a site is supplied."},
        "trace": trace,
        "architecture": None,
    }
    runtime = {
        "hostedProductMode": True,
        "durableRunApi": True,
        "briefingMode": "not-run",
        "activeAgentMode": "clarification",
        "modelCallCount": 0,
        "latencyMs": int((time.perf_counter() - started) * 1000),
    }
    result = {
        "sessionId": run["sessionId"],
        "runId": run_id,
        "assistantMessage": f"I can prepare a pre-visit review pack{site_context}, but I need a trusted location first.",
        "needsClarification": True,
        "clarifyingQuestions": clarification,
        "agent": _agent_runtime_state(),
        "uiState": ui_state,
        "runtime": runtime,
        "trace": trace,
        "evidence": [],
        "scene": None,
        "annotations": [],
        "briefing": None,
        "safety": ui_state["safety"],
        "fallback": {"status": "available", "reason": "Agent can rerun after clarification."},
        "modelCalls": [],
        "tokenUsage": None,
    }
    update_run(
        run_id,
        status="waiting_for_clarification",
        currentStep="waiting_for_clarification",
        partialUiState=ui_state,
        safetyResult=ui_state["safety"],
        result=result,
        runtime=runtime,
    )
    _record_session_run_summary(run_id, result, config)


def _finish_location_confirmation(
    run_id: str,
    location_resolution: dict[str, Any],
    clarification: list[str],
    started: float,
    config: RuntimeConfig,
) -> None:
    run = get_run_record(run_id)
    trace = [
        *run.get("steps", []),
        *list(run.get("partialUiState", {}).get("trace") or []),
    ]
    candidates = location_resolution.get("locationCandidates", [])
    site_name = location_resolution.get("siteName")
    if candidates:
        assistant_message = (
            f"I found {len(candidates)} possible location for {site_name}. "
            "Please confirm the site before I run map, evidence, risk, or briefing tools."
        )
        status = "waiting_for_location_confirmation"
    else:
        assistant_message = (
            f"I could not find a reliable cached/public location candidate for {site_name}. "
            "Please provide a postcode, OS grid reference, latitude/longitude, nearest road/town, or local authority."
        )
        status = "waiting_for_location_confirmation"
    safety = {"allowed": True, "level": "needs_input", "message": "No site-specific briefing generated until the site location is confirmed."}
    provisional_risks = location_resolution.get("provisionalRisks", [])
    ui_state = {
        "location": None,
        "scene": None,
        "annotations": [],
        "hazards": provisional_risks,
        "evidence": [],
        "sources": [],
        "briefing": None,
        "safety": safety,
        "trace": trace,
        "architecture": None,
        "locationResolution": location_resolution,
        "reviewMode": "provisional checklist pending location" if provisional_risks else "location pending",
    }
    runtime = {
        "hostedProductMode": True,
        "durableRunApi": True,
        "briefingMode": "not-run",
        "activeAgentMode": "location-resolution",
        "modelCallCount": 0,
        "latencyMs": int((time.perf_counter() - started) * 1000),
    }
    result = {
        "sessionId": run["sessionId"],
        "runId": run_id,
        "assistantMessage": assistant_message,
        "needsClarification": True,
        "needsLocationConfirmation": bool(candidates),
        "locationCandidates": candidates,
        "confirmedLocation": None,
        "nextStage": location_resolution.get("nextStage"),
        "clarifyingQuestions": clarification,
        "agent": _agent_runtime_state(),
        "uiState": ui_state,
        "runtime": runtime,
        "trace": trace,
        "evidence": [],
        "scene": None,
        "annotations": [],
        "briefing": None,
        "safety": safety,
        "fallback": {"status": "available", "reason": "Agent can continue after location confirmation or extra location detail."},
        "modelCalls": [],
        "tokenUsage": None,
    }
    update_run(
        run_id,
        status=status,
        currentStep="location_confirmation",
        partialUiState=ui_state,
        safetyResult=safety,
        result=result,
        runtime=runtime,
        locationResolution=location_resolution,
    )
    _record_session_run_summary(run_id, result, config)


def _finish_safety_blocked(
    run_id: str,
    safety_block: dict[str, Any],
    started: float,
    config: RuntimeConfig,
) -> None:
    run = get_run_record(run_id)
    trace = [
        *run.get("steps", []),
        *list(run.get("partialUiState", {}).get("trace") or []),
    ]
    safety = {
        "allowed": False,
        "level": "blocked",
        "message": safety_block["message"],
        "triggeredRules": safety_block.get("triggeredRules", []),
        "requiresHumanReview": True,
    }
    briefing = {
        "headline": "Request blocked by safety boundary.",
        "summary": [safety_block["message"]],
        "priority_checks": [],
        "before_site_visit": [],
        "limitations": ["3D-RAMS cannot certify RAMS, approve work, or provide emergency guidance."],
    }
    ui_state = {
        "location": None,
        "scene": None,
        "annotations": [],
        "hazards": [],
        "evidence": [],
        "sources": [],
        "briefing": briefing,
        "safety": safety,
        "trace": trace,
        "architecture": None,
        "locationResolution": None,
        "reviewMode": "safety blocked",
    }
    runtime = {
        "hostedProductMode": True,
        "durableRunApi": True,
        "briefingMode": "not-run",
        "activeAgentMode": "safety-gate",
        "modelCallCount": 0,
        "latencyMs": int((time.perf_counter() - started) * 1000),
    }
    result = {
        "sessionId": run["sessionId"],
        "runId": run_id,
        "assistantMessage": safety_block["message"],
        "needsClarification": False,
        "clarifyingQuestions": [],
        "agent": _agent_runtime_state(),
        "uiState": ui_state,
        "runtime": runtime,
        "trace": trace,
        "evidence": [],
        "scene": None,
        "annotations": [],
        "briefing": briefing,
        "safety": safety,
        "fallback": {"status": "blocked", "reason": safety_block["message"]},
        "modelCalls": [],
        "tokenUsage": None,
    }
    update_run(
        run_id,
        status="completed",
        currentStep="safety_gate",
        partialUiState=ui_state,
        finalUiState=ui_state,
        safetyResult=safety,
        result=result,
        runtime=runtime,
    )
    _record_session_run_summary(run_id, result, config)


def _finish_cancelled(run_id: str, reason: str) -> None:
    append_step(run_id, name="cancel_run", status="cancelled", summary=reason, output={})
    update_run(run_id, status="cancelled", currentStep="cancelled", fallbackReason=reason)


def _finish_failed(run_id: str, exc: Exception) -> None:
    append_step(
        run_id,
        name="run_failed",
        status="failed",
        summary="Durable run failed before a complete review pack was available.",
        output={"errorType": exc.__class__.__name__, "message": str(exc)[:240]},
    )
    update_run(
        run_id,
        status="failed",
        currentStep="failed",
        errorSummary={"type": exc.__class__.__name__, "message": str(exc)[:500]},
        fallbackReason="Use the existing /api/chat path or rerun after the failed tool/model issue is resolved.",
    )


def _checkpoint(
    run_id: str,
    name: str,
    status: str,
    summary: str,
    output: dict[str, Any] | None = None,
    *,
    deadline: float | None = None,
) -> None:
    _raise_if_stopped(run_id, deadline)
    append_step(run_id, name=name, status=status, summary=summary, output=output or {})
    update_run(run_id, status="running", currentStep=name)


def _consume_model_call(run_id: str, config: RuntimeConfig, *, phase: str) -> bool:
    run = get_run_record(run_id)
    if not config.bedrock_enabled:
        return False
    if run["modelCallsUsed"] >= run["maxModelCalls"]:
        append_step(
            run_id,
            name=f"{phase}_model_budget_exhausted",
            status="fallback",
            summary=f"{phase} did not call Bedrock because the model-call budget was exhausted.",
            output={"modelCallsUsed": run["modelCallsUsed"], "maxModelCalls": run["maxModelCalls"]},
        )
        return False
    update_run(run_id, modelCallsUsed=run["modelCallsUsed"] + 1)
    return True


def _merge_trace(run_id: str, trace: list[dict[str, Any]]) -> None:
    run = get_run_record(run_id)
    merged = list(run.get("partialUiState", {}).get("trace") or [])
    merged.extend(trace)
    partial = dict(run.get("partialUiState") or {})
    partial["trace"] = merged
    update_run(run_id, partialUiState=partial)


def _partial_ui_state(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "location": context.get("location"),
        "scene": context.get("scene"),
        "mapFeatures": context.get("mapFeatures", context.get("features", [])),
        "liveFeatureStatus": context.get("liveFeatureStatus", {}),
        "annotations": context.get("annotations", []),
        "hazards": context.get("hazards", []),
        "evidence": context.get("evidence", []),
        "sources": [],
        "briefing": context.get("briefing"),
        "safety": context.get("safety")
        or {
            "allowed": True,
            "level": "running",
            "message": "Run is still executing.",
        },
        "trace": context.get("trace", []),
        "architecture": None,
        "reasoning": context.get("reasoning"),
        "evaluation": context.get("evaluation"),
    }


def _public_tool_output(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "load_planning_context":
        return {"planningTextAvailable": bool(result.get("planningTextAvailable"))}
    public = {key: value for key, value in result.items() if key != "trace"}
    if "planningText" in public:
        public["planningText"] = "[redacted from run status]"
    return public


def _normalise_tool_name(name: str) -> str:
    return _TOOL_ALIASES.get(name.strip(), name.strip())


def _initial_tool_sequence(tools: list[str] | None = None) -> list[str]:
    sequence = tools or default_tool_sequence()
    return [tool for tool in (_normalise_tool_name(tool) for tool in sequence) if tool != _FINAL_SAFETY_TOOL]


def _invalid_hazard_evidence_refs(hazards: list[dict[str, Any]], evidence_ids: set[str]) -> list[str]:
    invalid: list[str] = []
    for hazard in hazards:
        if not _requires_site_evidence(hazard):
            continue
        refs = [str(ref) for ref in hazard.get("evidenceIds", []) if ref]
        if not refs or any(ref not in evidence_ids for ref in refs):
            invalid.append(str(hazard.get("id") or hazard.get("title") or "unknown-hazard"))
    return invalid


def _requires_site_evidence(hazard: dict[str, Any]) -> bool:
    return hazard.get("dataMode") != "provisional-from-user-description"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unsupported_safety_claims(briefing: dict[str, Any]) -> list[str]:
    text = " ".join(_flatten_text(briefing)).lower()
    unsafe_terms = [
        "certified rams",
        "certify rams",
        "emergency guidance",
        "approve work",
        "approved for work",
        "work approval",
        "guarantee safe",
    ]
    matches = []
    for term in unsafe_terms:
        start = text.find(term)
        while start != -1:
            if not _is_negated_quality_boundary(text, start, term):
                matches.append(term)
                break
            start = text.find(term, start + len(term))
    return sorted(set(matches))


def _is_negated_quality_boundary(text: str, claim_start: int, term: str) -> bool:
    prefix = text[max(0, claim_start - 90) : claim_start]
    claim = text[claim_start : claim_start + len(term)]
    suffix = text[claim_start + len(term) : claim_start + len(term) + 90]
    boundary_text = f"{prefix}{claim}{suffix}"
    safe_patterns = [
        f"cannot {term}",
        f"can't {term}",
        f"do not {term}",
        f"does not {term}",
        f"must not {term}",
        f"must not be treated as {term}",
        f"not {term}",
        f"not a {term}",
        f"not an {term}",
        f"not be treated as {term}",
        f"without {term}",
        "not a certified rams or work approval",
        "not certified rams, emergency guidance, or work approval",
    ]
    return any(pattern in boundary_text for pattern in safe_patterns)


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        flattened: list[str] = []
        for item in value.values():
            flattened.extend(_flatten_text(item))
        return flattened
    if isinstance(value, list):
        flattened = []
        for item in value:
            flattened.extend(_flatten_text(item))
        return flattened
    return []


def _expand_retry_dependencies(tools: list[str]) -> list[str]:
    expanded: list[str] = []
    for tool_name in tools:
        tool_name = _normalise_tool_name(tool_name)
        if tool_name == "load_geospatial_features":
            expanded.extend(["load_geospatial_features", "build_scene_config", "extract_hazard_notes", "rank_risks", "create_annotations", "compile_review_pack"])
        elif tool_name == "build_scene_config":
            expanded.extend(["build_scene_config", "compile_review_pack"])
        elif tool_name == "extract_hazard_notes":
            expanded.extend(["extract_hazard_notes", "rank_risks", "create_annotations", "compile_review_pack"])
        elif tool_name == "rank_risks":
            expanded.extend(["rank_risks", "create_annotations", "compile_review_pack"])
        elif tool_name == "create_annotations":
            expanded.append("create_annotations")
        elif tool_name == "compile_review_pack":
            expanded.append("compile_review_pack")
        elif tool_name in _INITIAL_REQUIRED_TOOLS:
            expanded.append(tool_name)
    return expanded


def _dedupe_tools(tools: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    allowed = set(_INITIAL_REQUIRED_TOOLS)
    for raw_name in tools:
        name = _normalise_tool_name(str(raw_name))
        if name in allowed and name not in seen:
            deduped.append(name)
            seen.add(name)
    return deduped


def _raise_if_stopped(run_id: str, deadline: float | None = None) -> None:
    if is_cancel_requested(run_id):
        raise _RunCancelled()
    if deadline is not None and time.perf_counter() > deadline:
        raise _RunTimedOut("Durable run exceeded configured runtime timeout.")


class _RunCancelled(RuntimeError):
    pass


class _RunTimedOut(RuntimeError):
    pass


def _validate_tool_plan(requested: list[str]) -> dict[str, Any]:
    if not requested:
        return {"valid": False, "issues": ["planner returned no tools"]}
    allowed = set(default_tool_sequence())
    invalid = [name for name in requested if name not in allowed]
    issues: list[str] = [f"disallowed tool '{name}'" for name in invalid]
    dependencies = {
        "load_geospatial_features": {"resolve_location"},
        "build_scene_config": {"resolve_location", "load_geospatial_features"},
        "load_planning_context": set(),
        "extract_hazard_notes": {"load_geospatial_features", "load_planning_context"},
        "rank_risks": {"extract_hazard_notes"},
        "create_annotations": {"resolve_location", "rank_risks"},
        "compile_review_pack": {"resolve_location", "rank_risks", "load_planning_context"},
        "safety_gate": {"compile_review_pack"},
    }
    seen: set[str] = set()
    for name in requested:
        missing = dependencies.get(name, set()).difference(seen)
        if missing:
            issues.append(f"tool '{name}' missing prior dependency: {', '.join(sorted(missing))}")
        seen.add(name)
    required = {"resolve_location", "load_geospatial_features", "build_scene_config", "load_planning_context", "extract_hazard_notes", "rank_risks", "create_annotations", "compile_review_pack"}
    missing_required = sorted(required.difference(requested))
    if missing_required:
        issues.append(f"missing required tool(s): {', '.join(missing_required)}")
    return {"valid": not issues, "issues": issues}


def _briefing_mode(run: dict[str, Any], config: RuntimeConfig) -> str:
    if run.get("modelCallsUsed", 0) > 0 and config.bedrock_enabled:
        return "real" if not config.bedrock_mock_response else "mocked"
    if run.get("fallbackReason"):
        return "fallback"
    return "deterministic"


def _model_call_payload(run: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for step in run.get("steps", []):
        if step["name"] in {"planner_model_call", "reasoner_model_call", "compiler_model_call", "output_evaluator_model_call"} and step["status"] == "ok":
            output = step.get("output", {})
            calls.append(
                {
                    "id": step["id"],
                    "phase": output.get("phase") or step["name"],
                    "status": step["status"],
                    "summary": step["summary"],
                    "modelId": output.get("modelId"),
                    "awsRegion": output.get("awsRegion"),
                    "latencyMs": output.get("latencyMs"),
                    "maxTokens": output.get("maxTokens"),
                    "phaseTokenBudget": output.get("phaseTokenBudget"),
                }
            )
    return calls


def _token_usage_payload(run: dict[str, Any]) -> dict[str, Any] | None:
    usage = [
        step.get("output", {}).get("tokenUsage")
        for step in run.get("steps", [])
        if step.get("output", {}).get("tokenUsage")
    ]
    if not usage:
        return None
    return {
        "inputTokens": sum(int(item.get("inputTokens", 0)) for item in usage),
        "outputTokens": sum(int(item.get("outputTokens", 0)) for item in usage),
        "totalTokens": sum(int(item.get("totalTokens", 0)) for item in usage),
    }


def _record_session_run_summary(run_id: str, result: dict[str, Any], config: RuntimeConfig) -> None:
    run = get_run_record(run_id)
    try:
        add_run(
            run["sessionId"],
            {
                "runId": run_id,
                "status": run["status"],
                "safetyLevel": result.get("safety", {}).get("level"),
                "briefingMode": result.get("runtime", {}).get("briefingMode"),
                "activeAgentMode": result.get("runtime", {}).get("activeAgentMode"),
                "latencyMs": result.get("runtime", {}).get("latencyMs"),
                "modelCallCount": run.get("modelCallsUsed", 0),
                "fallbackStatus": result.get("fallback", {}).get("status"),
            },
            config,
        )
    except Exception:
        return
