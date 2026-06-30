from __future__ import annotations

import copy
import time
import uuid
from typing import Any, Literal

from fastapi import HTTPException

from .config import RuntimeConfig


RunStatus = Literal[
    "queued",
    "running",
    "waiting_for_clarification",
    "waiting_for_approval",
    "completed",
    "failed",
    "cancelled",
]

_RUNS: dict[str, dict[str, Any]] = {}


def create_run_record(
    *,
    session_id: str,
    message: str,
    uploaded_file_ids: list[str],
    use_bedrock: bool,
    config: RuntimeConfig,
) -> dict[str, Any]:
    now = _now_iso()
    expires_at = int(time.time()) + max(config.session_retention_days, 1) * 86400
    run = {
        "sessionId": session_id,
        "runId": f"run-{uuid.uuid4().hex[:16]}",
        "status": "queued",
        "currentStep": "queued",
        "modelCallsUsed": 0,
        "maxModelCalls": config.bedrock_max_model_calls,
        "tokenBudget": {
            "plannerOutputTokens": config.planner_output_tokens,
            "reasonerOutputTokens": config.reasoner_output_tokens,
            "compilerOutputTokens": config.compiler_output_tokens,
        },
        "maxToolCalls": config.durable_run_max_tool_calls,
        "steps": [],
        "toolResults": [],
        "partialUiState": _empty_ui_state(),
        "finalUiState": None,
        "safetyResult": None,
        "fallbackReason": None,
        "errorSummary": None,
        "cancelRequested": False,
        "request": {
            "message": message,
            "uploadedFileIds": uploaded_file_ids,
            "useBedrock": use_bedrock,
            "messageSummary": _summarise_message(message),
        },
        "result": None,
        "runtime": {
            "durableRunApi": True,
            "workerMode": "local-background-thread",
            "futureAwsWorker": "API Gateway/Lambda -> DynamoDB run store -> SQS -> worker Lambda",
            "bedrockEnabled": config.bedrock_enabled,
            "modelId": config.bedrock_model_id if config.bedrock_enabled else None,
            "awsRegion": config.aws_region,
            "temperature": config.bedrock_temperature if config.bedrock_enabled else None,
        },
        "createdAt": now,
        "updatedAt": now,
        "expiresAt": expires_at,
        "version": 1,
        "storageMode": "memory",
    }
    _RUNS[run["runId"]] = run
    return public_run(run)


def get_run_record(run_id: str) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found or expired.")
    return run


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(run)


def update_run(run_id: str, **updates: Any) -> dict[str, Any]:
    run = get_run_record(run_id)
    run.update(updates)
    run["updatedAt"] = _now_iso()
    run["version"] = int(run.get("version", 0)) + 1
    return public_run(run)


def append_step(
    run_id: str,
    *,
    name: str,
    status: str,
    summary: str,
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = get_run_record(run_id)
    step = {
        "id": f"run-step-{len(run['steps']) + 1:02d}",
        "name": name,
        "status": status,
        "summary": summary,
        "output": output or {},
        "timestamp": _now_iso(),
    }
    run["steps"].append(step)
    run["currentStep"] = name
    run["updatedAt"] = step["timestamp"]
    run["version"] = int(run.get("version", 0)) + 1
    return step


def append_tool_result(
    run_id: str,
    *,
    tool_name: str,
    status: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    run = get_run_record(run_id)
    result = {
        "toolName": tool_name,
        "status": status,
        "output": output,
        "timestamp": _now_iso(),
    }
    run["toolResults"].append(result)
    run["updatedAt"] = result["timestamp"]
    run["version"] = int(run.get("version", 0)) + 1
    return result


def request_cancel(run_id: str) -> dict[str, Any]:
    run = get_run_record(run_id)
    if run["status"] == "queued":
        append_step(
            run_id,
            name="cancel_run",
            status="cancelled",
            summary="Run was cancelled before execution started.",
            output={"cancelledBeforeFirstModelCall": True},
        )
        return update_run(
            run_id,
            status="cancelled",
            currentStep="cancelled",
            cancelRequested=True,
            errorSummary=None,
            fallbackReason="Run cancelled before worker execution.",
        )
    if run["status"] in {"running", "waiting_for_clarification", "waiting_for_approval"}:
        return update_run(run_id, cancelRequested=True)
    return public_run(run)


def is_cancel_requested(run_id: str) -> bool:
    return bool(get_run_record(run_id).get("cancelRequested"))


def clear_all_runs_for_tests() -> None:
    _RUNS.clear()


def _empty_ui_state() -> dict[str, Any]:
    return {
        "location": None,
        "scene": None,
        "annotations": [],
        "hazards": [],
        "evidence": [],
        "sources": [],
        "briefing": None,
        "safety": {
            "allowed": True,
            "level": "queued",
            "message": "Run has been queued.",
        },
        "trace": [],
        "architecture": None,
    }


def _summarise_message(message: str) -> str:
    return " ".join(message.split())[:180]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
