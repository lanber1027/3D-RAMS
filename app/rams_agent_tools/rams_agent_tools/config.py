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


@dataclass(frozen=True)
class RuntimeConfig:
    bedrock_requested: bool
    bedrock_enabled: bool
    aws_profile: str | None
    aws_region: str
    bedrock_model_id: str
    bedrock_max_tokens: int
    bedrock_max_model_calls: int
    bedrock_temperature: float
    bedrock_mock_response: bool
    bedrock_simulate_failure: bool

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
            bedrock_max_model_calls=_env_int("BEDROCK_MAX_MODEL_CALLS", 2),
            bedrock_temperature=_env_float("BEDROCK_TEMPERATURE", 0.2),
            bedrock_mock_response=_env_bool("BEDROCK_MOCK_RESPONSE", False),
            bedrock_simulate_failure=_env_bool("BEDROCK_SIMULATE_FAILURE", False),
        )

    def public_runtime(self, *, status: str, fallback_reason: str | None = None) -> dict[str, object]:
        return {
            "briefingMode": status,
            "bedrockRequested": self.bedrock_requested,
            "bedrockEnabled": self.bedrock_enabled,
            "bedrockUsed": status in {"real", "mocked"},
            "awsRegion": self.aws_region,
            "modelId": self.bedrock_model_id if self.bedrock_enabled else None,
            "maxTokens": self.bedrock_max_tokens if self.bedrock_enabled else None,
            "maxModelCalls": self.bedrock_max_model_calls if self.bedrock_enabled else None,
            "temperature": self.bedrock_temperature if self.bedrock_enabled else None,
            "fallbackReason": fallback_reason,
        }
