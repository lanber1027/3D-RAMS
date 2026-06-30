from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from rams_agent_tools.tools import safety_gate, trace_step

MAX_REVISION_ATTEMPTS = 2
REVIEW_INPUT_SCHEMA = "3d-rams.review-input.v1"
REVIEW_OUTPUT_SCHEMA = "3d-rams.review-output.v1"

ReviewFn = Callable[[dict[str, Any]], dict[str, Any]]


def run_independent_review_loop(
    *,
    run: dict[str, Any],
    draft_report: dict[str, Any],
    reviewer: ReviewFn | None = None,
    max_revision_attempts: int = MAX_REVISION_ATTEMPTS,
) -> dict[str, Any]:
    report = deepcopy(draft_report)
    case_id = str(report.get("caseId") or run.get("caseId") or "")
    review_outputs: list[dict[str, Any]] = []
    review_trace: list[dict[str, Any]] = []
    revision_count = 0
    review_fn = reviewer or deterministic_review

    while True:
        review_input = build_review_input(run=run, structured_report=report)
        review = _normalize_review_output(review_fn(review_input))
        review["trace"] = _correlate_trace(_trace_list(review.get("trace")), case_id)
        review_outputs.append(review)
        review_trace.extend(review["trace"])

        if review["decision"] != "revise":
            break
        if revision_count >= max_revision_attempts:
            review = _max_revision_review_required(review, revision_count, max_revision_attempts)
            review_outputs[-1] = review
            review_trace.extend(_trace_list(review.get("trace")))
            break

        revision_count += 1
        report, revision_step = _revise_report(report, review, revision_count)
        review_trace.extend(_correlate_trace([revision_step], case_id))

    review_gate = _review_gate(review, run.get("safety"), revision_count, max_revision_attempts)
    report["reviewGate"] = review_gate
    report["status"] = review_gate["status"]
    report["trace"] = _correlate_trace(_trace_list(run.get("trace")) + review_trace, case_id)

    if review_gate["status"] == "blocked":
        report["findings"] = []
        report.setdefault("visualization", {})["annotations"] = []

    run["trace"] = report["trace"]
    run["reviewGate"] = review_gate
    run["review"] = {
        "schemaVersion": REVIEW_OUTPUT_SCHEMA,
        "revisionCount": revision_count,
        "maxRevisionAttempts": max_revision_attempts,
        "outputs": review_outputs,
    }

    return {
        "reportStatus": review_gate["status"],
        "structuredReport": report,
        "run": run,
    }


def build_review_input(*, run: dict[str, Any], structured_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": REVIEW_INPUT_SCHEMA,
        "caseId": structured_report.get("caseId") or run.get("caseId"),
        "intake": structured_report.get("intake") or {},
        "structuredReport": structured_report,
        "reasoning": structured_report.get("reasoning") or run.get("reasoning") or {},
        "evidenceRegister": structured_report.get("evidenceRegister") or {},
        "traceSummary": [_trace_summary(step) for step in _trace_list(run.get("trace"))],
        "safetyBoundary": {
            "nonCertifiedRams": True,
            "requiresHumanReview": True,
        },
    }


def deterministic_review(review_input: dict[str, Any]) -> dict[str, Any]:
    report = _dict(review_input.get("structuredReport"))
    safety, safety_step = safety_gate(_dict(review_input.get("intake")), report)
    trace = [safety_step]

    if not safety.get("allowed"):
        return _review_output(
            decision="block",
            status="blocked",
            summary="Independent review blocked the draft report at the safety boundary.",
            issues=[
                {
                    "id": "safety-boundary",
                    "severity": "blocking",
                    "message": safety.get("message") or "Safety boundary blocked the draft report.",
                    "affects": ["structuredReport"],
                    "requiredAction": "remove_finding",
                }
            ],
            trace=trace,
        )

    unsupported = _unsupported_finding_issues(report)
    if unsupported:
        return _review_output(
            decision="revise",
            status="warning",
            summary="Independent review requested revision for unsupported findings.",
            issues=unsupported,
            required_revisions=[issue["message"] for issue in unsupported],
            trace=trace,
        )

    caveats = _review_caveats(report)
    if caveats:
        return _review_output(
            decision="pass_with_caveats",
            status="warning",
            summary="Independent review passed the report with caveats visible to the user.",
            caveats=caveats,
            trace=trace,
        )

    return _review_output(
        decision="pass",
        status="ok",
        summary="Independent review passed the report.",
        trace=trace,
    )


def _unsupported_finding_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    for finding in _list(report.get("findings")):
        refs = _dict(finding.get("references"))
        if refs.get("sourceIds") or refs.get("evidenceIds"):
            continue
        finding_id = str(finding.get("id") or "unknown-finding")
        issues.append(
            {
                "id": f"unsupported-{finding_id}",
                "severity": "medium",
                "message": f"Finding '{finding_id}' lacks source or evidence references.",
                "affects": [f"findings.{finding_id}"],
                "requiredAction": "remove_finding",
            }
        )
    return issues


def _review_caveats(report: dict[str, Any]) -> list[str]:
    caveats: list[str] = []
    summary = _dict(report.get("executiveSummary"))
    caveats.extend(_strings(summary.get("limitations")))
    caveats.extend(_strings(_dict(report.get("dataQuality")).get("gaps")))
    if any(finding.get("humanReviewRequired", True) for finding in _list(report.get("findings"))):
        caveats.append("Candidate findings require competent human review before use.")
    return _dedupe(caveats)


def _revise_report(
    report: dict[str, Any],
    review: dict[str, Any],
    revision_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    revised = deepcopy(report)
    remove_ids = {
        affected.split(".", 1)[1]
        for issue in _list(review.get("issues"))
        if issue.get("requiredAction") == "remove_finding"
        for affected in _strings(issue.get("affects"))
        if affected.startswith("findings.")
    }
    if remove_ids:
        revised["findings"] = [
            finding for finding in _list(revised.get("findings")) if str(finding.get("id")) not in remove_ids
        ]
        annotations = _dict(revised.get("visualization")).get("annotations")
        if isinstance(annotations, list):
            revised["visualization"]["annotations"] = [
                item for item in annotations if not isinstance(item, dict) or str(item.get("id")) not in remove_ids
            ]

    caveats = [issue.get("message") for issue in _list(review.get("issues")) if issue.get("message")]
    _extend_report_list(revised, ["executiveSummary", "limitations"], caveats)
    _extend_report_list(revised, ["dataQuality", "gaps"], caveats)
    _extend_report_list(revised, ["dataQuality", "warnings"], [f"Supervisor revision {revision_count} applied review findings."])

    return revised, trace_step(
        "supervisor_revision_pass",
        "warning",
        "Supervisor revised the draft report using independent review findings.",
        {
            "revisionCount": revision_count,
            "removedFindings": sorted(remove_ids),
            "issueCount": len(_list(review.get("issues"))),
        },
        evidence_ids=["safety-policy"],
    )


def _review_output(
    *,
    decision: str,
    status: str,
    summary: str,
    issues: list[dict[str, Any]] | None = None,
    required_revisions: list[str] | None = None,
    caveats: list[str] | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": REVIEW_OUTPUT_SCHEMA,
        "reviewer": {
            "name": "review_guardrail",
            "mode": "deterministic",
        },
        "decision": decision,
        "status": status,
        "summary": summary,
        "issues": issues or [],
        "requiredRevisions": required_revisions or [],
        "caveats": caveats or [],
        "trace": (trace or [])
        + [
            trace_step(
                "independent_review_gate",
                "blocked" if decision == "block" else ("warning" if status == "warning" else "ok"),
                summary,
                {
                    "decision": decision,
                    "status": status,
                    "issueCount": len(issues or []),
                    "caveatCount": len(caveats or []),
                },
                evidence_ids=["safety-policy"],
            )
        ],
    }


def _normalize_review_output(value: dict[str, Any]) -> dict[str, Any]:
    review = dict(value)
    review.setdefault("schemaVersion", REVIEW_OUTPUT_SCHEMA)
    review.setdefault("reviewer", {"name": "review_guardrail", "mode": "deterministic"})
    review.setdefault("decision", "revise")
    review.setdefault("status", "warning")
    review.setdefault("summary", "Independent review returned an incomplete output.")
    review.setdefault("issues", [])
    review.setdefault("requiredRevisions", [])
    review.setdefault("caveats", [])
    review.setdefault("trace", [])
    return review


def _max_revision_review_required(review: dict[str, Any], revision_count: int, max_revision_attempts: int) -> dict[str, Any]:
    final = dict(review)
    final["decision"] = "revise"
    final["status"] = "blocked"
    final["summary"] = "Independent review still requested revision after the maximum supervisor revision attempts."
    final["caveats"] = _dedupe(
        _strings(final.get("caveats"))
        + ["Independent review requires human follow-up after maximum automated revision attempts."]
    )
    final["trace"] = _trace_list(final.get("trace")) + [
        trace_step(
            "independent_review_max_revisions",
            "blocked",
            final["summary"],
            {
                "revisionCount": revision_count,
                "maxRevisionAttempts": max_revision_attempts,
            },
            evidence_ids=["safety-policy"],
        )
    ]
    return final


def _review_gate(
    review: dict[str, Any],
    safety: Any,
    revision_count: int,
    max_revision_attempts: int,
) -> dict[str, Any]:
    safety_payload = _dict(safety)
    status = {
        "pass": "passed",
        "pass_with_caveats": "passed_with_caveats",
        "block": "blocked",
        "revise": "review_required",
    }.get(str(review.get("decision")), "review_required")
    return {
        "status": status,
        "decision": review.get("decision"),
        "safetyAllowed": bool(safety_payload.get("allowed", True)) and status != "blocked",
        "safetyLevel": str(safety_payload.get("level") or status),
        "requiresHumanReview": status != "passed",
        "message": str(review.get("summary") or "Independent review completed."),
        "triggeredRules": _strings(safety_payload.get("triggeredRules")),
        "reviewerNotes": _dedupe([str(review.get("summary") or "")] + _strings(review.get("caveats"))),
        "reviewer": _dict(review.get("reviewer")),
        "issues": _list(review.get("issues")),
        "requiredRevisions": _strings(review.get("requiredRevisions")),
        "caveats": _strings(review.get("caveats")),
        "revisionCount": revision_count,
        "maxRevisionAttempts": max_revision_attempts,
    }


def _trace_summary(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": step.get("id"),
        "name": step.get("name"),
        "status": step.get("status"),
        "summary": step.get("summary"),
        "sourceIds": step.get("sourceIds") or [],
        "evidenceIds": step.get("evidenceIds") or [],
    }


def _correlate_trace(trace: list[dict[str, Any]], case_id: str) -> list[dict[str, Any]]:
    if not case_id:
        return trace
    correlated = []
    for step in trace:
        if not isinstance(step, dict):
            continue
        enriched = dict(step)
        enriched["caseId"] = case_id
        output = enriched.get("output")
        if isinstance(output, dict):
            output = dict(output)
            output["caseId"] = case_id
            enriched["output"] = output
        correlated.append(enriched)
    return correlated


def _extend_report_list(report: dict[str, Any], path: list[str], values: list[str]) -> None:
    target = report
    for key in path[:-1]:
        target = target.setdefault(key, {})
    field = path[-1]
    existing = _strings(target.get(field))
    target[field] = _dedupe(existing + [str(value) for value in values if value])


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _trace_list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
