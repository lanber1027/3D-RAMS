from __future__ import annotations

from typing import Any

from .schemas import (
    Coordinate,
    DataQuality,
    EvidenceRegister,
    ExecutiveSummary,
    ReportFinding,
    ReportIntake,
    ReportReference,
    ReportRuntime,
    ReportSection,
    ReportSite,
    ReviewGate,
    StructuredReport,
    VisualizationPayload,
)


def build_structured_report(
    run: dict[str, Any],
    report_status: str,
    workflow_mode: str,
) -> dict[str, Any]:
    briefing = _dict(run.get("briefing"))
    location = _dict(run.get("location"))
    request = _dict(run.get("request"))
    runtime = _dict(run.get("runtime"))
    safety = _dict(run.get("safety"))
    trace = _list(run.get("trace"))
    reasoning = _dict(run.get("reasoning"))

    report = StructuredReport(
        reportId=str(run.get("runId") or "unknown-run"),
        caseId=run.get("caseId") or request.get("caseId"),
        status=_report_status(report_status),
        workflowMode=workflow_mode,
        intake=_build_intake(run, request),
        site=_build_site(location),
        runtime=_build_runtime(runtime),
        executiveSummary=_build_summary(briefing, location, safety),
        sections=_build_sections(run, briefing, trace, reasoning),
        findings=_build_findings(run),
        visualization=VisualizationPayload(
            scene=_dict(run.get("scene")),
            annotations=_list(run.get("annotations")),
        ),
        evidenceRegister=EvidenceRegister(
            sources=_list(run.get("sources")),
            evidence=_list(run.get("evidence")),
        ),
        reviewGate=_build_review_gate(run, safety, reasoning),
        dataQuality=_build_data_quality(run, runtime, trace, briefing, reasoning),
        externalSignals=_dict(run.get("externalSignals")),
        materialIngestion=_dict(run.get("materialIngestion")),
        trace=trace,
        reasoning=reasoning,
        llmPlan=_dict(run.get("llmPlan")),
        modelCalls=_list(run.get("modelCalls")),
        tokenUsage=_dict(run.get("tokenUsage")) or None,
        fallback=_dict(run.get("fallback")),
        architecture=_dict(run.get("architecture")) or None,
    )
    return report.model_dump(mode="json", exclude_none=True)


def _build_intake(run: dict[str, Any], request: dict[str, Any]) -> ReportIntake:
    return ReportIntake(
        caseId=request.get("caseId") or run.get("caseId"),
        siteName=request.get("siteName"),
        goal=request.get("goal"),
        fixturePack=request.get("fixturePack"),
        materials=_list(request.get("materials")),
        includePlanningFixture=bool(request.get("includePlanningFixture")),
        simulateMapFailure=bool(request.get("simulateMapFailure")),
        useBedrock=bool(request.get("useBedrock")),
        agentMode=str(request.get("agentMode") or "llm-planner"),
        additionalRequest=request.get("additionalRequest"),
        upstream=_dict(run.get("upstream")) or None,
    )


def _build_site(location: dict[str, Any]) -> ReportSite:
    return ReportSite(
        label=str(location.get("label") or "Unknown site"),
        coordinate=Coordinate(
            latitude=float(location.get("latitude", 0.0)),
            longitude=float(location.get("longitude", 0.0)),
            coordinateSystem=str(location.get("coordinate_system") or "WGS84"),
        ),
        authority=location.get("authority"),
        confidence=location.get("confidence"),
        dataMode=location.get("dataMode"),
        sourceIds=_string_list(location.get("sourceIds")),
    )


def _build_runtime(runtime: dict[str, Any]) -> ReportRuntime:
    return ReportRuntime(
        briefingMode=str(runtime.get("briefingMode") or "unknown"),
        bedrockRequested=bool(runtime.get("bedrockRequested")),
        bedrockEnabled=bool(runtime.get("bedrockEnabled")),
        bedrockUsed=bool(runtime.get("bedrockUsed")),
        fixturePack=runtime.get("fixturePack"),
        fixturePackMode=str(runtime.get("fixturePackMode") or "unknown"),
        liveApiCalls=bool(runtime.get("liveApiCalls")),
        fallbackReason=runtime.get("fallbackReason"),
        awsRegion=runtime.get("awsRegion"),
        modelId=runtime.get("modelId"),
        plannerMode=runtime.get("plannerMode"),
        activeAgentMode=runtime.get("activeAgentMode"),
        modelCallCount=int(runtime.get("modelCallCount") or 0),
        subagentExecutionMode=runtime.get("subagentExecutionMode"),
        caseId=runtime.get("caseId"),
        materialIngestionStatus=runtime.get("materialIngestionStatus"),
        materialEvidenceCount=int(runtime.get("materialEvidenceCount") or 0),
        materialSkippedCount=int(runtime.get("materialSkippedCount") or 0),
        harnessOutputSchemaVersion=runtime.get("harnessOutputSchemaVersion"),
        harnessContract=_dict(runtime.get("harnessContract")),
    )


def _build_summary(
    briefing: dict[str, Any],
    location: dict[str, Any],
    safety: dict[str, Any],
) -> ExecutiveSummary:
    return ExecutiveSummary(
        title=str(briefing.get("site") or location.get("label") or "3D-RAMS review pack"),
        headline=str(briefing.get("headline") or "Review pack generated."),
        summary=_string_list(briefing.get("summary")),
        priorityChecks=_string_list(briefing.get("priority_checks")),
        beforeSiteVisit=_string_list(briefing.get("before_site_visit")),
        limitations=_string_list(briefing.get("limitations")),
        safetyMessage=str(safety.get("message") or "Safety gate result unavailable."),
    )


def _build_sections(
    run: dict[str, Any],
    briefing: dict[str, Any],
    trace: list[dict[str, Any]],
    reasoning: dict[str, Any],
) -> list[ReportSection]:
    trace_refs = {step.get("name"): str(step.get("id")) for step in trace if step.get("name") and step.get("id")}
    sources = _list(run.get("sources"))
    evidence = _list(run.get("evidence"))
    hazards = _list(run.get("hazards"))
    annotations = _list(run.get("annotations"))
    safety = _dict(run.get("safety"))
    material_ingestion = _dict(run.get("materialIngestion"))
    material_source_ids = _string_list(material_ingestion.get("sourceIds"))
    material_evidence_ids = _string_list(material_ingestion.get("evidenceIds"))

    return [
        ReportSection(
            id="location-context",
            title="Location Context",
            status=_section_status(reasoning, "location-context", "ready"),
            body=[_site_sentence(run)],
            references=ReportReference(traceIds=_present([trace_refs.get("resolve_location")])),
        ),
        ReportSection(
            id="spatial-context",
            title="Spatial And 3D Context",
            status=_section_status(reasoning, "spatial-context", "ready" if annotations else "warning"),
            body=[f"{len(annotations)} map annotations are available for frontend visualization."],
            references=ReportReference(traceIds=_present([trace_refs.get("load_geospatial_features"), trace_refs.get("build_scene_config")])),
        ),
        ReportSection(
            id="planning-context",
            title="Planning And Public Context",
            status=_section_status(
                reasoning,
                "planning-context",
                "ready" if _has_available_source(sources, "planning") else "warning",
            ),
            body=_planning_body(briefing),
            references=ReportReference(
                sourceIds=[item["id"] for item in sources if "planning" in str(item.get("id", ""))],
                traceIds=_present([trace_refs.get("load_planning_context")]),
            ),
        ),
        ReportSection(
            id="candidate-findings",
            title="Candidate Findings",
            status=_section_status(reasoning, "candidate-findings", "ready" if hazards else "warning"),
            body=[f"{len(hazards)} candidate findings were extracted for human review."],
            references=ReportReference(
                evidenceIds=[item["id"] for item in evidence],
                traceIds=_present([trace_refs.get("extract_hazard_notes"), trace_refs.get("create_annotations")]),
            ),
        ),
        ReportSection(
            id="user-materials",
            title="User Materials",
            status=_section_status(
                reasoning,
                "user-materials",
                "ready" if material_ingestion.get("accepted") else "warning",
            ),
            body=[_material_body(material_ingestion)],
            references=ReportReference(
                sourceIds=material_source_ids,
                evidenceIds=material_evidence_ids,
                traceIds=_present([trace_refs.get("ingest_material_references")]),
            ),
        ),
        ReportSection(
            id="open-web-signals",
            title="Open-Web Signals",
            status=_section_status(reasoning, "open-web-signals", "warning"),
            body=[_open_web_body(run)],
            references=ReportReference(),
        ),
        ReportSection(
            id="review-boundary",
            title="Review Boundary",
            status=_section_status(reasoning, "review-boundary", "ready" if safety.get("allowed") else "blocked"),
            body=[str(safety.get("message") or "Safety gate result unavailable.")],
            references=ReportReference(traceIds=_present([trace_refs.get("safety_gate")])),
        ),
    ]


def _build_findings(run: dict[str, Any]) -> list[ReportFinding]:
    annotations_by_id = {item.get("id"): item for item in _list(run.get("annotations"))}
    assessments_by_id = {
        item.get("findingId"): item
        for item in _list(_dict(run.get("reasoning")).get("findingAssessments"))
    }
    findings = []
    for hazard in _list(run.get("hazards")):
        hazard_id = str(hazard.get("id") or "unknown-finding")
        annotation = annotations_by_id.get(hazard_id)
        assessment = _dict(assessments_by_id.get(hazard_id))
        findings.append(
            ReportFinding(
                id=hazard_id,
                title=str(hazard.get("title") or hazard_id),
                category=str(hazard.get("category") or "unspecified"),
                confidence=str(hazard.get("confidence") or "unknown"),
                note=str(hazard.get("note") or ""),
                references=ReportReference(
                    sourceIds=_string_list(hazard.get("sourceIds")),
                    evidenceIds=_string_list(hazard.get("evidenceIds")),
                ),
                annotationId=str(annotation.get("id")) if annotation else None,
                rationale=assessment.get("rationale"),
                humanReviewRequired=bool(assessment.get("humanReviewRequired", True)),
            )
        )
    return findings


def _build_review_gate(run: dict[str, Any], safety: dict[str, Any], reasoning: dict[str, Any]) -> ReviewGate:
    review_gate = _dict(run.get("reviewGate"))
    if review_gate:
        reviewer_notes = _string_list(review_gate.get("reviewerNotes"))
        reviewer_notes.extend(_string_list(reasoning.get("reviewQuestions")))
        return ReviewGate(
            status=_review_gate_status(review_gate.get("status")),
            decision=str(review_gate.get("decision") or "") or None,
            reviewer=_dict(review_gate.get("reviewer")) or None,
            safetyAllowed=bool(review_gate.get("safetyAllowed", safety.get("allowed"))),
            safetyLevel=str(review_gate.get("safetyLevel") or safety.get("level") or "unknown"),
            requiresHumanReview=bool(review_gate.get("requiresHumanReview", True)),
            message=str(review_gate.get("message") or safety.get("message") or "Review gate result unavailable."),
            triggeredRules=_string_list(review_gate.get("triggeredRules")) or _string_list(safety.get("triggeredRules")),
            reviewerNotes=_dedupe(reviewer_notes),
            issues=_list(review_gate.get("issues")),
            requiredRevisions=_list(review_gate.get("requiredRevisions")),
            caveats=_string_list(review_gate.get("caveats")),
            revisionCount=int(review_gate.get("revisionCount") or 0),
            attemptCount=int(review_gate.get("attemptCount") or 0),
        )

    allowed = bool(safety.get("allowed"))
    reviewer_notes = (
        ["Independent review agent has not been implemented in this prototype."]
        if allowed
        else ["Safety gate blocked this output before independent review."]
    )
    reviewer_notes.extend(_string_list(reasoning.get("reviewQuestions")))
    return ReviewGate(
        status="pending_independent_review" if allowed else "blocked",
        safetyAllowed=allowed,
        safetyLevel=str(safety.get("level") or "unknown"),
        requiresHumanReview=bool(safety.get("requiresHumanReview", True)),
        message=str(safety.get("message") or "Safety gate result unavailable."),
        decision="pending" if allowed else "block",
        reviewerMode=str(safety.get("reviewerMode") or "deterministic"),
        revisionCount=int(safety.get("revisionCount") or 0),
        issues=_list(safety.get("issues")),
        caveats=_string_list(safety.get("caveats")),
        triggeredRules=_string_list(safety.get("triggeredRules")),
        reviewerNotes=reviewer_notes,
    )


def _build_data_quality(
    run: dict[str, Any],
    runtime: dict[str, Any],
    trace: list[dict[str, Any]],
    briefing: dict[str, Any],
    reasoning: dict[str, Any],
) -> DataQuality:
    warnings = [
        step["summary"]
        for step in trace
        if step.get("status") in {"warning", "fallback", "disabled"} and step.get("summary")
    ]
    gaps = _string_list(briefing.get("limitations"))
    gaps.extend(str(gap.get("message")) for gap in _list(reasoning.get("gaps")) if gap.get("message"))
    fallback_reasons = [str(step["fallbackReason"]) for step in trace if step.get("fallbackReason")]
    gaps.extend(fallback_reasons)
    harness_contract = _dict(runtime.get("harnessContract"))
    harness_issues = _list(harness_contract.get("issues"))
    if harness_issues:
        gaps.append("One or more Harness outputs required fallback normalization before supervisor consumption.")
    for issue in harness_issues:
        subagent = str(issue.get("subagent") or "unknown_subagent")
        for message in _string_list(issue.get("issues")):
            gaps.append(f"Harness output contract fallback for {subagent}: {message}")
    external_signals = _dict(run.get("externalSignals"))
    open_web = _dict(external_signals.get("openWeb"))
    material_ingestion = _dict(run.get("materialIngestion"))

    return DataQuality(
        dataMode=str(runtime.get("fixturePackMode") or "unknown"),
        completeness={
            "hasResolvedLocation": bool(run.get("location")),
            "hasScene": bool(run.get("scene")),
            "hasFindings": bool(run.get("hazards")),
            "hasAnnotations": bool(run.get("annotations")),
            "hasEvidence": bool(run.get("evidence")),
            "hasTrace": bool(trace),
            "hasOpenWebSignals": bool(open_web.get("items")),
            "hasMaterialEvidence": bool(material_ingestion.get("accepted")),
            "harnessOutputsContractCompliant": bool(harness_contract.get("contractCompliant", True)),
        },
        gaps=_dedupe(gaps),
        warnings=_dedupe(warnings),
    )


def _site_sentence(run: dict[str, Any]) -> str:
    location = _dict(run.get("location"))
    if not location:
        return "Location was not resolved."
    return (
        f"{location.get('label', 'Site')} resolved at "
        f"{location.get('latitude')}, {location.get('longitude')} "
        f"with {location.get('confidence', 'unknown')} confidence."
    )


def _planning_body(briefing: dict[str, Any]) -> list[str]:
    limitations = _string_list(briefing.get("limitations"))
    planning_limits = [item for item in limitations if "planning" in item.lower()]
    if planning_limits:
        return planning_limits
    return ["Planning and public-context evidence was considered where available."]


def _open_web_body(run: dict[str, Any]) -> str:
    open_web = _dict(_dict(run.get("externalSignals")).get("openWeb"))
    items = _list(open_web.get("items"))
    if items:
        return f"{len(items)} open-web signals are available as non-authoritative context."
    status = str(open_web.get("status") or "not_configured")
    return f"Open-web signals are {status}; no Tavily results are included in this report."


def _material_body(material_ingestion: dict[str, Any]) -> str:
    accepted = int(material_ingestion.get("accepted") or 0)
    skipped = int(material_ingestion.get("skippedCount") or 0)
    if accepted:
        return (
            f"{accepted} authorized material reference(s) produced safe summaries and citations; "
            "raw private material content is not stored in the report."
        )
    if skipped:
        return f"{skipped} material reference(s) were skipped with trace-visible access, expiry, type, or retrieval reasons."
    return "No ASI/ASI:ONE material references were supplied for this run."


def _section_status(reasoning: dict[str, Any], section_id: str, fallback: str) -> str:
    fit = _reasoning_fit(reasoning, section_id)
    status = str(fit.get("status") or "")
    if status == "supported":
        return "ready"
    if status in {"partial", "missing"}:
        return "warning"
    if status == "conflict":
        return "blocked"
    return fallback


def _reasoning_fit(reasoning: dict[str, Any], section_id: str) -> dict[str, Any]:
    for item in _list(reasoning.get("reportFit")):
        if item.get("sectionId") == section_id:
            return item
    return {}


def _has_available_source(sources: list[dict[str, Any]], token: str) -> bool:
    for source in sources:
        source_id = str(source.get("id") or "").lower()
        status = str(source.get("status") or "").lower()
        if token in source_id and status not in {"unavailable", "disabled"}:
            return True
    return False


def _report_status(value: str) -> str:
    if value in {"blocked", "review_required", "review_passed"}:
        return value
    return "review_required"


def _review_gate_status(value: Any) -> str:
    status = str(value or "")
    if status in {"blocked", "pending_independent_review", "passed", "passed_with_caveats", "review_required"}:
        return status
    return "review_required"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _present(values: list[str | None]) -> list[str]:
    return [value for value in values if value]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result
