from __future__ import annotations

import json
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
from supervisor_core.harness_contract import HARNESS_OUTPUT_SCHEMA_VERSION  # noqa: E402
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
                                "delta": {"toolUse": {"input": '{"includePlanningFixture":false}'}},
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
                                "text": json.dumps(
                                    harness_output(
                                        "planning_subagent",
                                        "rams_planning_harness",
                                        {"planningText": "Reviewed cached planning context."},
                                    )
                                )
                            },
                        }
                    },
                    {"contentBlockStop": {"contentBlockIndex": 0}},
                    {"messageStop": {"stopReason": "end_turn"}},
                ]
            )
        }


class OneShotHarnessClient:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def invoke_harness(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "stream": iter(
                [
                    {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
                    {
                        "contentBlockDelta": {
                            "contentBlockIndex": 0,
                            "delta": {"text": json.dumps(self.payload)},
                        }
                    },
                    {"contentBlockStop": {"contentBlockIndex": 0}},
                    {"messageStop": {"stopReason": "end_turn"}},
                ]
            )
        }


class FailingHarnessClient:
    def invoke_harness(self, **kwargs):
        raise TimeoutError("bedrock-agentcore invoke_harness timeout")


def harness_output(group: str, harness: str, data: dict[str, Any], **updates: Any) -> dict[str, Any]:
    payload = {
        "schemaVersion": HARNESS_OUTPUT_SCHEMA_VERSION,
        "subagent": {"name": group, "harness": harness, "phase": "unit_test"},
        "status": "ok",
        "summary": "Harness returned a valid test envelope.",
        "data": data,
        "evidence": [],
        "findings": [],
        "trace": [],
        "references": [],
        "warnings": [],
        "errors": [],
        "metadata": {"mode": "fixture", "caseId": "case_test", "generatedAt": "2026-06-30T00:00:00Z"},
    }
    payload.update(updates)
    return payload


class AgentCoreHarnessInvokerTests(unittest.TestCase):
    def test_invoke_harness_runs_inline_tool_loop_and_returns_json(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        client = FakeHarnessClient()
        with EnvPatch(RAMS_PLANNING_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_planning({}, fixture_pack=None)

        self.assertEqual(result["schemaVersion"], HARNESS_OUTPUT_SCHEMA_VERSION)
        self.assertEqual(result["data"]["planningText"], "Reviewed cached planning context.")
        self.assertEqual(result["planningText"], "Reviewed cached planning context.")
        self.assertFalse(
            any(step.get("name") == "agentcore_harness_schema_fallback" for step in result.get("trace", []))
        )
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(
            client.calls[0]["harnessArn"],
            "arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ",
        )
        tool_result = client.calls[1]["messages"][-1]["content"][0]["toolResult"]
        self.assertEqual(tool_result["toolUseId"], "tool-1")
        self.assertEqual(tool_result["status"], "success")
        self.assertIn("planningText", tool_result["content"][0]["json"])

    def test_missing_schema_version_uses_fallback_trace(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        client = OneShotHarnessClient({"planningText": "Old unversioned output.", "trace": []})
        with EnvPatch(RAMS_PLANNING_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_planning({"includePlanningFixture": False}, fixture_pack=None)

        fallback_step = result["trace"][-1]
        self.assertEqual(fallback_step["name"], "agentcore_harness_schema_fallback")
        self.assertEqual(fallback_step["fallbackReason"], "agentcore_harness_output_contract_invalid")
        self.assertTrue(any("schemaVersion" in item for item in result["metadata"]["contractValidationIssues"]))

    def test_malformed_trace_uses_fallback_trace(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        payload = harness_output(
            "planning_subagent",
            "rams_planning_harness",
            {"planningText": "Reviewed cached planning context."},
            trace=[{"name": "broken"}],
        )
        client = OneShotHarnessClient(payload)
        with EnvPatch(RAMS_PLANNING_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_planning({"includePlanningFixture": False}, fixture_pack=None)

        fallback_step = result["trace"][-1]
        self.assertEqual(fallback_step["name"], "agentcore_harness_schema_fallback")
        self.assertTrue(any("trace[0]" in item for item in result["metadata"]["contractValidationIssues"]))

    def test_malformed_review_safety_uses_fallback(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        payload = harness_output(
            "review_guardrail",
            "rams_review_harness",
            {"safety": "looks fine"},
        )
        client = OneShotHarnessClient(payload)
        with EnvPatch(RAMS_REVIEW_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_review_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_review({}, {"headline": "Safe non-certified briefing."})

        self.assertIsInstance(result["data"]["safety"], dict)
        self.assertTrue(result["data"]["safety"]["allowed"])
        fallback_step = result["trace"][-1]
        self.assertTrue(any("data.safety" in item for item in result["metadata"]["contractValidationIssues"]))

    def test_missing_domain_key_uses_fallback(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        payload = harness_output("planning_subagent", "rams_planning_harness", {"notes": "No planningText key."})
        client = OneShotHarnessClient(payload)
        with EnvPatch(RAMS_PLANNING_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_planning({"includePlanningFixture": False}, fixture_pack=None)

        fallback_step = result["trace"][-1]
        self.assertEqual(fallback_step["name"], "agentcore_harness_schema_fallback")
        self.assertTrue(any("planningText" in item for item in result["metadata"]["contractValidationIssues"]))

    def test_invoke_harness_failure_uses_direct_fallback(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        with EnvPatch(RAMS_PLANNING_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_planning_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=FailingHarnessClient())
            result = invoker.invoke_planning({}, fixture_pack={"name": "public-lambeth-thames"})

        self.assertIn("planningText", result["data"])
        fallback_step = next(step for step in result["trace"] if step["name"] == "agentcore_harness_failure_fallback")
        self.assertEqual(fallback_step["status"], "fallback")
        self.assertEqual(fallback_step["fallbackReason"], "bedrock_timeout")

    def test_invoke_material_harness_returns_safe_ingestion_payload(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        payload = harness_output(
            "material_subagent",
            "rams_material_harness",
            {
                "materialIngestion": {
                    "schemaVersion": "3d-rams.material-ingestion.v1",
                    "status": "ok",
                    "accepted": 1,
                    "skippedCount": 0,
                    "sourceIds": ["material-asio-material-site-access-plan"],
                    "evidenceIds": ["ev-material-asio-material-site-access-plan"],
                }
            },
            evidence=[{"id": "ev-material-asio-material-site-access-plan", "summary": "Safe bounded summary."}],
        )
        client = OneShotHarnessClient(payload)
        with EnvPatch(RAMS_MATERIAL_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_material_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_material(
                {"materials": [{"materialId": "asio_material_site_access_plan"}]},
                case_id="case_test",
                upstream_context={"source": "asi_one"},
            )

        self.assertEqual(result["schemaVersion"], HARNESS_OUTPUT_SCHEMA_VERSION)
        self.assertEqual(result["data"]["materialIngestion"]["accepted"], 1)
        self.assertEqual(result["materialIngestion"]["sourceIds"], ["material-asio-material-site-access-plan"])
        self.assertEqual(result["evidence"][0]["id"], "ev-material-asio-material-site-access-plan")


if __name__ == "__main__":
    unittest.main()
