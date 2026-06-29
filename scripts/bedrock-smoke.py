from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.agent import run_site_briefing  # noqa: E402


def main() -> int:
    os.environ.setdefault("ENABLE_BEDROCK", "true")
    os.environ.setdefault("AWS_PROFILE", "3d-rams-dev")
    os.environ.setdefault("AWS_REGION", "eu-west-2")
    os.environ.setdefault("BEDROCK_MODEL_ID", "anthropic.claude-3-7-sonnet-20250219-v1:0")
    os.environ.setdefault("BEDROCK_MAX_TOKENS", "1200")
    os.environ.setdefault("BEDROCK_TEMPERATURE", "0.2")

    result = run_site_briefing({"useBedrock": True, "goal": "Bedrock smoke test briefing"})
    bedrock_step = next(step for step in result["trace"] if step["name"] == "generate_bedrock_briefing")
    print(json.dumps({
        "runtime": result["runtime"],
        "bedrockStepStatus": bedrock_step["status"],
        "bedrockStepOutput": bedrock_step["output"],
        "headline": result["briefing"]["headline"],
        "safety": result["safety"]["level"],
    }, indent=2))
    return 0 if bedrock_step["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
