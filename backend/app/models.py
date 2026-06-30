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
    agentMode: Literal["deterministic", "bedrock-briefing", "llm-planner"] | None = Field(
        default=None,
        validation_alias=AliasChoices("agentMode", "agent_mode"),
        description="Agent execution mode: deterministic, bedrock-briefing, or llm-planner.",
    )
    additionalRequest: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional additional user instruction. Unsafe RAMS/work-approval claims are blocked by the safety gate.",
    )

    def to_agent_request(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class SessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accessCode: str | None = Field(
        default=None,
        max_length=256,
        description="Shared tester access code. The backend validates it before any model call.",
    )
    testerAlias: str | None = Field(
        default=None,
        max_length=80,
        description="Optional tester alias for evaluation tracing. Do not put private data here.",
    )


class UploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sessionId: str = Field(min_length=8, max_length=80)
    filename: str = Field(min_length=1, max_length=180)
    contentType: Literal["application/pdf", "image/png", "image/jpeg"] = Field(
        description="Allowed hosted MVP evidence upload type.",
    )
    sizeBytes: int | None = Field(default=None, ge=0, le=10_000_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sessionId: str = Field(min_length=8, max_length=80)
    message: str = Field(min_length=1, max_length=3000)
    uploadedFileIds: list[str] = Field(default_factory=list, max_length=8)
    useBedrock: bool = Field(default=True)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sessionId: str = Field(min_length=8, max_length=80)
    message: str = Field(min_length=1, max_length=3000)
    uploadedFileIds: list[str] = Field(default_factory=list, max_length=8)
    useBedrock: bool = Field(default=True)
    autoStart: bool = Field(
        default=True,
        description="When false, the run remains queued until a future worker/resume action starts it.",
    )


class SessionResponse(BaseModel):
    sessionId: str
    testerAlias: str | None
    accessLabel: str
    runtime: dict[str, Any]
