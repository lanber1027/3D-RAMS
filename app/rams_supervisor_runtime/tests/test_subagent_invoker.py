from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rams_agent_tools.config import RuntimeConfig  # noqa: E402
from supervisor_core.subagent_invoker import AgentCoreHarnessInvoker  # noqa: E402


class EnvPatch:
    def __init__(self, **updates: str | None):
        self.updates = updates
        self.previous: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self.updates.items():
            self.previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeHarnessClient:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def invoke_harness(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {
                "stream": iter(
                    [
                        {
                            "contentBlockStart": {
                                "contentBlockIndex": 0,
                                "start": {
                                    "toolUse": {
                                        "name": "load_planning_context",
                                        "toolUseId": "tool-1",
                                    }
                                },
                            }
                        },
                        {
                            "contentBlockDelta": {
                                "contentBlockIndex": 0,
                                "delta": {
                                    "toolUse": {
                                        "input": '{"fixturePack":"public-lambeth-thames","includePlanningFixture":true}'
                                    }
                                },
                            }
                        },
                        {"contentBlockStop": {"contentBlockIndex": 0}},
                        {"messageStop": {"stopReason": "tool_use"}},
                    ]
                )
            }
        return {
            "stream": iter(
                [
                    {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
                    {
                        "contentBlockDelta": {
                            "contentBlockIndex": 0,
                            "delta": {
                                "text": '{"planningText":"Reviewed cached planning context.","trace":[]}'
                            },
                        }
                    },
                    {"contentBlockStop": {"contentBlockIndex": 0}},
                    {"messageStop": {"stopReason": "end_turn"}},
                ]
            )
        }


class AgentCoreHarnessInvokerTests(unittest.TestCase):
    def test_invoke_harness_runs_inline_tool_loop_and_returns_json(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        client = FakeHarnessClient()
        with EnvPatch(RAMS_PLANNING_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_planning({}, fixture_pack={"name": "public-lambeth-thames"})

        self.assertEqual(result["planningText"], "Reviewed cached planning context.")
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(
            client.calls[0]["harnessArn"],
            "arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ",
        )
        tool_result = client.calls[1]["messages"][-1]["content"][0]["toolResult"]
        self.assertEqual(tool_result["toolUseId"], "tool-1")
        self.assertEqual(tool_result["status"], "success")
        self.assertIn("planningText", tool_result["content"][0]["json"])


if __name__ == "__main__":
    unittest.main()
