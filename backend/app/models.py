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
