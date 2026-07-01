from __future__ import annotations

from typing import Any

from rams_agent_tools.bedrock_adapter import BedrockAdapterError, bedrock_error_output, generate_bedrock_subagent_plan
from rams_agent_tools.config import RuntimeConfig
from rams_agent_tools.tools import SUPERVISOR_HARNESS_SUBAGENTS, tools_for_group, trace_step


def plan_subagent_workflow(
    *,
    config: RuntimeConfig,
    request_summary: dict[str, Any],
) -> dict[str, Any]:
    """Always produce a bounded supervisor plan before subagent execution."""
    if config.bedrock_requested and config.bedrock_enabled:
        try:
            plan, metadata = generate_bedrock_subagent_plan(
                config=config,
                request_summary=request_summary,
                subagent_schemas=_subagent_schemas(),
            )
        except (BedrockAdapterError, Exception) as exc:
            error_output = bedrock_error_output(exc)
            return _deterministic_result(
                request_summary=request_summary,
                status="fallback",
                active_agent_mode="deterministic-planner-fallback",
                fallback_reason=str(error_output["fallbackReason"]),
                error_output=error_output,
            )

        planner_status = "mocked" if metadata.get("mode") == "bedrock-mock" else "real"
        active_agent_mode = "llm-planner-mock" if planner_status == "mocked" else "llm-planner"
        normalised_plan = _normalise_plan(plan)
        model_call = _model_call(metadata, planner_status)
        return {
            "plan": normalised_plan,
            "trace": trace_step(
                "plan_subagent_workflow",
                "ok",
                "Supervisor planner produced a bounded Harness subagent execution plan.",
                {
                    "mode": metadata.get("mode"),
                    "plannerStatus": planner_status,
                    "activeAgentMode": active_agent_mode,
                    "modelId": metadata.get("modelId"),
                    "awsRegion": metadata.get("awsRegion"),
                    "modelCallCount": metadata.get("modelCallCount", 1),
                    "plan": normalised_plan,
                },
                source_ids=["bedrock-planner"],
                duration_ms=int(metadata.get("latencyMs", 0)),
            ),
            "plannerStatus": planner_status,
            "activeAgentMode": active_agent_mode,
            "modelCalls": [model_call],
            "tokenUsage": None,
            "fallback": {"status": "not_used", "reason": None},
        }

    reason = (
        "Bedrock planner was not requested for this run; deterministic Harness planner was used."
        if not config.bedrock_requested
        else "ENABLE_BEDROCK is not true; deterministic Harness planner was used."
    )
    return _deterministic_result(
        request_summary=request_summary,
        status="deterministic",
        active_agent_mode="deterministic-planner",
        fallback_reason=reason,
    )


def _deterministic_result(
    *,
    request_summary: dict[str, Any],
    status: str,
    active_agent_mode: str,
    fallback_reason: str,
    error_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = _normalise_plan(_default_plan())
    output: dict[str, Any] = {
        "mode": "deterministic",
        "plannerStatus": status,
        "activeAgentMode": active_agent_mode,
        "requestedAgentMode": request_summary.get("agentMode"),
        "plan": plan,
    }
    if error_output:
        output.update(error_output)
    trace_status = "fallback" if status == "fallback" else "ok"
    return {
        "plan": plan,
        "trace": trace_step(
            "plan_subagent_workflow",
            trace_status,
            "Supervisor planner produced the deterministic bounded Harness subagent plan.",
            output,
            source_ids=["bedrock-planner"],
            fallback_reason=fallback_reason,
        ),
        "plannerStatus": status,
        "activeAgentMode": active_agent_mode,
        "modelCalls": [],
        "tokenUsage": None,
        "fallback": {
            "status": "used",
            "reason": fallback_reason,
        },
    }


def _subagent_schemas() -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for name, spec in SUPERVISOR_HARNESS_SUBAGENTS.items():
        schemas.append(
            {
                "name": name,
                "harness": spec["harness"],
                "phase": spec["phase"],
                "dependsOn": spec["dependsOn"],
                "tools": tools_for_group(name),
            }
        )
    return schemas


def _normalise_plan(plan: dict[str, Any]) -> dict[str, Any]:
    default = _default_plan()
    return {
        "rationale": _text(plan.get("rationale"), default["rationale"]),
        "initialParallelGroups": _groups(plan.get("initial_parallel_groups"), default["initialParallelGroups"]),
        "sequentialGroups": _groups(plan.get("sequential_groups"), default["sequentialGroups"]),
        "reportParallelGroups": _groups(plan.get("report_parallel_groups"), default["reportParallelGroups"]),
        "requiredEvidence": _strings(plan.get("required_evidence"), default["requiredEvidence"]),
        "missingInputs": _strings(plan.get("missing_inputs"), []),
        "subagents": _subagent_schemas(),
    }


def _default_plan() -> dict[str, Any]:
    return {
        "rationale": "Use the standard 3D-RAMS bounded Harness workflow for a complete review pack.",
        "initialParallelGroups": ["geospatial_subagent", "planning_subagent"],
        "sequentialGroups": ["material_subagent", "hazard_subagent", "open_web_subagent", "review_guardrail"],
        "reportParallelGroups": ["annotation_subagent", "briefing_subagent"],
        "requiredEvidence": [
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
        "missingInputs": [],
    }


def _groups(value: Any, fallback: list[str]) -> list[str]:
    allowed = set(SUPERVISOR_HARNESS_SUBAGENTS)
    if not isinstance(value, list):
        return list(fallback)
    groups = []
    for item in value:
        name = str(item).strip()
        if name in allowed and name not in groups:
            groups.append(name)
    return groups or list(fallback)


def _strings(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    items = [str(item).strip() for item in value if str(item).strip()]
    return items or list(fallback)


def _text(value: Any, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _model_call(metadata: dict[str, Any], planner_status: str) -> dict[str, Any]:
    return {
        "id": "model-call-planner-1",
        "phase": "planner-plan",
        "status": planner_status,
        "provider": "amazon-bedrock",
        "modelId": metadata.get("modelId"),
        "awsRegion": metadata.get("awsRegion"),
        "latencyMs": metadata.get("latencyMs"),
        "maxTokens": metadata.get("maxTokens"),
        "temperature": metadata.get("temperature"),
    }
