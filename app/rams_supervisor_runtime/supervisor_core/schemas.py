from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str = Field(description="Service status.")
    service: str = Field(description="Service identifier.")


class SiteBriefRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    siteName: str | None = Field(
        default=None,
        max_length=160,
        description="Optional site label shown in the briefing and architecture visualizer.",
    )
    latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        description="Site latitude in decimal degrees. Defaults to the demo fixture coordinate when omitted.",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180,
        description="Site longitude in decimal degrees. Defaults to the demo fixture coordinate when omitted.",
    )
    goal: str | None = Field(
        default=None,
        max_length=240,
        description="User goal for the pre-visit briefing.",
    )
    fixturePack: str | None = Field(
        default=None,
        max_length=80,
        validation_alias=AliasChoices("fixturePack", "fixture_pack"),
        description="Optional cached fixture pack id, for example public-lambeth-thames.",
    )
    includePlanningFixture: bool = Field(
        default=True,
        description="Whether cached/synthetic planning context should be included.",
    )
    simulateMapFailure: bool = Field(
        default=False,
        description="Whether to force geospatial fallback behavior for demo testing.",
    )
    useBedrock: bool = Field(
        default=True,
        description="Whether the run requests the optional Bedrock briefing path. Environment config still controls whether Bedrock is actually used.",
    )
    agentMode: str = Field(
        default="llm-planner",
        max_length=80,
        description="Requested supervisor mode. Planner phase is always present; Bedrock availability controls whether it is LLM-backed or deterministic.",
    )
    additionalRequest: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional additional user instruction. Unsafe RAMS/work-approval claims are blocked by the safety gate.",
    )

    def to_agent_request(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class Coordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    coordinateSystem: str = Field(default="WGS84")


class ReportIntake(BaseModel):
    siteName: str | None = None
    goal: str | None = None
    fixturePack: str | None = None
    includePlanningFixture: bool
    simulateMapFailure: bool
    useBedrock: bool
    agentMode: str
    additionalRequest: str | None = None
    upstream: dict[str, Any] | None = None


class ReportSite(BaseModel):
    label: str
    coordinate: Coordinate
    authority: str | None = None
    confidence: str | None = None
    dataMode: str | None = None
    sourceIds: list[str] = Field(default_factory=list)


class ReportRuntime(BaseModel):
    briefingMode: str
    fixturePack: str | None = None
    fixturePackMode: str
    liveApiCalls: bool
    fallbackReason: str | None = None
    awsRegion: str | None = None
    modelId: str | None = None
    plannerMode: str | None = None
    activeAgentMode: str | None = None
    modelCallCount: int = 0
    subagentExecutionMode: str | None = None


class ExecutiveSummary(BaseModel):
    title: str
    headline: str
    summary: list[str] = Field(default_factory=list)
    priorityChecks: list[str] = Field(default_factory=list)
    beforeSiteVisit: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    safetyMessage: str


class ReportReference(BaseModel):
    sourceIds: list[str] = Field(default_factory=list)
    evidenceIds: list[str] = Field(default_factory=list)
    traceIds: list[str] = Field(default_factory=list)


class ReportFinding(BaseModel):
    id: str
    title: str
    category: str
    confidence: str
    note: str
    references: ReportReference = Field(default_factory=ReportReference)
    annotationId: str | None = None


class ReportSection(BaseModel):
    id: str
    title: str
    status: Literal["ready", "warning", "blocked"]
    body: list[str] = Field(default_factory=list)
    references: ReportReference = Field(default_factory=ReportReference)


class EvidenceRegister(BaseModel):
    sources: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class VisualizationPayload(BaseModel):
    scene: dict[str, Any]
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class ReviewGate(BaseModel):
    status: Literal["blocked", "pending_independent_review", "passed"]
    safetyAllowed: bool
    safetyLevel: str
    requiresHumanReview: bool
    message: str
    triggeredRules: list[str] = Field(default_factory=list)
    reviewerNotes: list[str] = Field(default_factory=list)


class DataQuality(BaseModel):
    dataMode: str
    completeness: dict[str, bool]
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExternalSignals(BaseModel):
    openWeb: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "not_configured",
            "items": [],
        }
    )


class StructuredReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: str = Field(default="0.1.0")
    reportType: Literal["3d-rams-site-review"] = "3d-rams-site-review"
    reportId: str
    status: Literal["blocked", "review_required", "review_passed"]
    workflowMode: str
    intake: ReportIntake
    site: ReportSite
    runtime: ReportRuntime
    executiveSummary: ExecutiveSummary
    sections: list[ReportSection]
    findings: list[ReportFinding]
    visualization: VisualizationPayload
    evidenceRegister: EvidenceRegister
    reviewGate: ReviewGate
    dataQuality: DataQuality
    externalSignals: ExternalSignals = Field(default_factory=ExternalSignals)
    llmPlan: dict[str, Any] = Field(default_factory=dict)
    modelCalls: list[dict[str, Any]] = Field(default_factory=list)
    tokenUsage: dict[str, Any] | None = None
    fallback: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    architecture: dict[str, Any] | None = None
