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
    os.environ.setdefault("BEDROCK_MAX_MODEL_CALLS", "4")

    result = run_site_briefing({
        "agentMode": "llm-planner",
        "useBedrock": True,
        "fixturePack": "public-lambeth-thames",
        "goal": "Bedrock smoke test LLM planner briefing",
    })
    plan_step = next(step for step in result["trace"] if step["name"] == "llm_planner_model_plan")
    synthesis_step = next((step for step in result["trace"] if step["name"] == "llm_planner_synthesis"), None)
    print(json.dumps({
        "runtime": result["runtime"],
        "plannerStepStatus": plan_step["status"],
        "plannerStepOutput": plan_step["output"],
        "synthesisStepStatus": synthesis_step["status"] if synthesis_step else None,
        "synthesisStepOutput": synthesis_step["output"] if synthesis_step else None,
        "llmPlan": result["llmPlan"],
        "llmToolCallCount": len(result["llmToolCalls"]),
        "modelCallCount": result["runtime"]["modelCallCount"],
        "headline": result["briefing"]["headline"],
        "safety": result["safety"]["level"],
    }, indent=2))
    return 0 if plan_step["status"] == "ok" and synthesis_step and synthesis_step["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
