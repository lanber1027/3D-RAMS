from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or default


@dataclass(frozen=True)
class RuntimeConfig:
    bedrock_requested: bool
    bedrock_enabled: bool
    aws_profile: str | None
    aws_region: str
    bedrock_model_id: str
    bedrock_max_tokens: int
    bedrock_temperature: float
    bedrock_max_model_calls: int
    durable_run_max_tool_calls: int
    durable_run_timeout_seconds: int
    durable_run_process_inline: bool
    planner_output_tokens: int
    reasoner_output_tokens: int
    compiler_output_tokens: int
    bedrock_mock_response: bool
    bedrock_simulate_failure: bool
    app_env: str
    allowed_origins: list[str]
    app_access_token_hash: str | None
    app_access_code_label: str
    s3_upload_bucket: str | None
    dynamodb_session_table: str | None
    upload_retention_days: int
    session_retention_days: int
    agentcore_runtime_enabled: bool
    agentcore_runtime_arn: str | None
    agentcore_memory_enabled: bool
    agentcore_memory_id: str | None
    enable_live_map_features: bool
    live_map_required: bool
    live_feature_radius_meters: int
    overpass_api_url: str
    planning_data_api_base: str

    @classmethod
    def from_env(cls, *, request_bedrock: bool = True) -> "RuntimeConfig":
        enabled = _env_bool("ENABLE_BEDROCK", False) and request_bedrock
        return cls(
            bedrock_requested=request_bedrock,
            bedrock_enabled=enabled,
            aws_profile=os.getenv("AWS_PROFILE") or None,
            aws_region=os.getenv("AWS_REGION", "eu-west-2"),
            bedrock_model_id=os.getenv(
                "BEDROCK_MODEL_ID",
                "anthropic.claude-3-7-sonnet-20250219-v1:0",
            ),
            bedrock_max_tokens=_env_int("BEDROCK_MAX_TOKENS", 1200),
            bedrock_temperature=_env_float("BEDROCK_TEMPERATURE", 0.2),
            bedrock_max_model_calls=min(max(_env_int("BEDROCK_MAX_MODEL_CALLS", 2), 0), 4),
            durable_run_max_tool_calls=min(max(_env_int("DURABLE_RUN_MAX_TOOL_CALLS", 12), 1), 20),
            durable_run_timeout_seconds=min(max(_env_int("DURABLE_RUN_TIMEOUT_SECONDS", 45), 5), 240),
            durable_run_process_inline=_env_bool("DURABLE_RUN_PROCESS_INLINE", False),
            planner_output_tokens=min(max(_env_int("BEDROCK_PLANNER_MAX_TOKENS", 900), 256), 3000),
            reasoner_output_tokens=min(max(_env_int("BEDROCK_REASONER_MAX_TOKENS", 1500), 256), 4000),
            compiler_output_tokens=min(max(_env_int("BEDROCK_COMPILER_MAX_TOKENS", 2200), 512), 5000),
            bedrock_mock_response=_env_bool("BEDROCK_MOCK_RESPONSE", False),
            bedrock_simulate_failure=_env_bool("BEDROCK_SIMULATE_FAILURE", False),
            app_env=os.getenv("APP_ENV", "local"),
            allowed_origins=_env_list(
                "ALLOWED_ORIGINS",
                ["http://localhost:5173", "http://127.0.0.1:5173"],
            ),
            app_access_token_hash=os.getenv("APP_ACCESS_TOKEN_HASH") or None,
            app_access_code_label=os.getenv("APP_ACCESS_CODE_LABEL", "local-dev"),
            s3_upload_bucket=os.getenv("S3_UPLOAD_BUCKET") or None,
            dynamodb_session_table=os.getenv("DYNAMODB_SESSION_TABLE") or None,
            upload_retention_days=_env_int("UPLOAD_RETENTION_DAYS", 7),
            session_retention_days=_env_int("SESSION_RETENTION_DAYS", 7),
            agentcore_runtime_enabled=_env_bool("ENABLE_AGENTCORE_RUNTIME", False),
            agentcore_runtime_arn=os.getenv("AGENTCORE_RUNTIME_ARN") or None,
            agentcore_memory_enabled=_env_bool("ENABLE_AGENTCORE_MEMORY", False),
            agentcore_memory_id=os.getenv("AGENTCORE_MEMORY_ID") or None,
            enable_live_map_features=_env_bool("ENABLE_LIVE_MAP_FEATURES", False),
            live_map_required=_env_bool("LIVE_MAP_REQUIRED", False),
            live_feature_radius_meters=min(max(_env_int("LIVE_FEATURE_RADIUS_METERS", 350), 50), 1200),
            overpass_api_url=os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter"),
            planning_data_api_base=os.getenv("PLANNING_DATA_API_BASE", "https://www.planning.data.gov.uk"),
        )

    def public_runtime(self, *, status: str, fallback_reason: str | None = None) -> dict[str, object]:
        return {
            "briefingMode": status,
            "bedrockRequested": self.bedrock_requested,
            "bedrockEnabled": self.bedrock_enabled,
            "awsRegion": self.aws_region,
            "modelId": self.bedrock_model_id if self.bedrock_enabled else None,
            "maxTokens": self.bedrock_max_tokens if self.bedrock_enabled else None,
            "temperature": self.bedrock_temperature if self.bedrock_enabled else None,
            "maxModelCalls": self.bedrock_max_model_calls,
            "phaseTokenBudgets": {
                "planner": self.planner_output_tokens,
                "reasoner": self.reasoner_output_tokens,
                "compiler": self.compiler_output_tokens,
            },
            "maxToolCalls": self.durable_run_max_tool_calls,
            "fallbackReason": fallback_reason,
            "agentCoreRuntimeEnabled": self.agentcore_runtime_enabled,
            "agentCoreMemoryEnabled": self.agentcore_memory_enabled,
            "agentCoreStatus": "configured" if self.agentcore_runtime_enabled and self.agentcore_runtime_arn else "agentcore-ready-lambda-adapter",
            "liveMapFeaturesEnabled": self.enable_live_map_features,
            "liveMapRequired": self.live_map_required,
            "liveFeatureRadiusMeters": self.live_feature_radius_meters,
        }
