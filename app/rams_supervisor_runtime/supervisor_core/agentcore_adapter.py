from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .agent import run_site_briefing
from .report_store import load_report, persist_report
from .structured_report import build_structured_report


def ping() -> dict[str, str]:
    return {"status": "ok", "service": "3d-rams-agentcore"}


def handle_invocation(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    if _is_local_asione_payload(payload):
        local_entry = _load_local_entry_flow()
        local_response = local_entry.run_local_asione_chat(
            payload,
            supervisor_invoker=_handle_supervisor_invocation,
        )
        run = local_response.get("run") if isinstance(local_response, dict) else None
        delivery = local_response.get("delivery") if isinstance(local_response, dict) else None
        agentcore_output = local_response.get("agentcoreOutput") if isinstance(local_response, dict) else None
        persistence = agentcore_output.get("persistence") if isinstance(agentcore_output, dict) else None
        structured_report = agentcore_output.get("structuredReport") if isinstance(agentcore_output, dict) else None
        review_metadata = _review_metadata(agentcore_output) if isinstance(agentcore_output, dict) else None
        return {
            "output": {
                "caseId": local_response.get("caseId") if isinstance(local_response, dict) else None,
                "localAsiOne": local_response,
                "delivery": delivery,
                "structuredReport": structured_report,
                "reviewGate": review_metadata,
                "reviewMetadata": review_metadata,
                "run": run,
                "persistence": persistence,
                "reportStatus": delivery.get("status") if isinstance(delivery, dict) else "entry_pending",
                "workflowMode": delivery.get("workflowMode") if isinstance(delivery, dict) else "entry_intake",
            }
        }
    return _handle_supervisor_invocation(payload)


def _handle_supervisor_invocation(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    request = _extract_request(payload)
    if _is_report_lookup_request(request):
        return load_report(str(request["caseId"]), access_context=_report_access_context(request))

    run = run_site_briefing(request)
    case_id = run.get("caseId") or request.get("caseId")
    report_status = _report_status(run)
    workflow_mode = _workflow_mode(run)
    structured_report = build_structured_report(run, report_status, workflow_mode)
    review_metadata = _review_metadata({"structuredReport": structured_report})
    output = {
        "caseId": case_id,
        "reportStatus": report_status,
        "workflowMode": workflow_mode,
        "structuredReport": structured_report,
        "reviewGate": review_metadata,
        "reviewMetadata": review_metadata,
        "run": run,
    }
    output["persistence"] = persist_report(output)
    return {
        "output": output
    }


def _is_local_asione_payload(payload: dict[str, Any]) -> bool:
    return bool(payload.get("localAsiOne") or payload.get("localAsiOneChat") or payload.get("entryMessage"))


def _review_metadata(output: dict[str, Any]) -> dict[str, Any] | None:
    report = output.get("structuredReport") if isinstance(output.get("structuredReport"), dict) else {}
    review_gate = report.get("reviewGate") if isinstance(report.get("reviewGate"), dict) else None
    return output.get("reviewMetadata") or output.get("reviewGate") or review_gate


def _load_local_entry_flow():
    entry_root = Path(__file__).resolve().parents[2] / "asi_one_entry_agent"
    tools_root = Path(__file__).resolve().parents[2] / "rams_agent_tools"
    for path in (entry_root, tools_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    import local_entry_flow

    return local_entry_flow


def _extract_request(payload: dict[str, Any]) -> dict[str, Any]:
    input_payload = payload.get("input", payload)
    if not isinstance(input_payload, dict):
        return {"additionalRequest": str(input_payload)}

    request = dict(input_payload)
    location_text = request.pop("locationText", None)
    upstream = request.pop("upstream", None)
    if location_text and not request.get("siteName"):
        request["siteName"] = str(location_text)
    if upstream:
        request["agentcoreUpstream"] = upstream
        if not request.get("caseId") and isinstance(upstream, dict) and upstream.get("caseId"):
            request["caseId"] = str(upstream["caseId"])
    return request


def _is_report_lookup_request(request: dict[str, Any]) -> bool:
    operation = str(request.get("operation") or request.get("action") or "").strip().lower()
    return operation in {"getreport", "get_report", "lookupreport", "lookup_report"} and bool(request.get("caseId"))


def _report_access_context(request: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("reportAccess", "reportAccessContext", "accessContext"):
        candidate = request.get(key)
        if isinstance(candidate, dict):
            return candidate

    upstream = request.get("agentcoreUpstream") or request.get("upstream")
    if isinstance(upstream, dict):
        candidate = upstream.get("reportAccess")
        if isinstance(candidate, dict):
            return candidate

    return None


def _workflow_mode(run: dict[str, Any]) -> str:
    fixture_mode = run.get("runtime", {}).get("fixturePackMode")
    if fixture_mode == "cached-public-fixture":
        return "cached_public_fixture"
    if fixture_mode == "synthetic-default":
        return "synthetic_fixture"
    return str(fixture_mode or "unknown")


def _report_status(run: dict[str, Any]) -> str:
    status = str(run.get("finalReportStatus") or "")
    if status in {"blocked", "review_required", "review_passed"}:
        return status
    review_gate = run.get("reviewGate") if isinstance(run.get("reviewGate"), dict) else {}
    gate_status = str(review_gate.get("status") or "")
    if gate_status == "blocked":
        return "blocked"
    if gate_status in {"passed", "passed_with_caveats"}:
        return "review_passed"
    return "review_required" if run["safety"]["allowed"] else "blocked"
