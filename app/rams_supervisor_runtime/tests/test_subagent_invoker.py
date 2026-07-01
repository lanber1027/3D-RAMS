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
from supervisor_core.subagent_invoker import AgentCoreHarnessInvoker, DirectSubagentInvoker  # noqa: E402


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
    def test_direct_material_invoker_returns_harness_envelope(self):
        result = DirectSubagentInvoker().invoke_material(
            [
                {
                    "materialId": "asio_material_site_access_plan",
                    "sourceSystem": "asio",
                    "type": "application/pdf",
                    "label": "Site access plan",
                    "caseId": "case_material_invoker_001",
                    "access": {
                        "mode": "asio_authorized_reference",
                        "expiresAt": "2099-01-01T00:00:00Z",
                    },
                }
            ],
            case_id="case_material_invoker_001",
            upstream_context={"source": "ASI_ONE"},
        )

        self.assertEqual(result["schemaVersion"], HARNESS_OUTPUT_SCHEMA_VERSION)
        self.assertEqual(result["subagent"]["name"], "material_subagent")
        self.assertEqual(result["subagent"]["harness"], "rams_material_harness")
        self.assertEqual(result["data"]["accepted"], 1)
        self.assertEqual(result["acceptedReferences"][0]["sourceId"], "material-asio-material-site-access-plan")
        self.assertTrue(result["evidence"])
        self.assertTrue(result["findings"])
        self.assertTrue(any(step["name"] == "ingest_material_references" for step in result["trace"]))

    def test_agentcore_material_invoker_uses_material_harness_arn(self):
        config = RuntimeConfig.from_env(request_bedrock=False)
        payload = harness_output(
            "material_subagent",
            "rams_material_harness",
            {
                "schemaVersion": "3d-rams.material-ingestion.v1",
                "status": "disabled",
                "mode": "deterministic-local-material-adapter",
                "received": 0,
                "accepted": 0,
                "skippedCount": 0,
                "acceptedReferences": [],
                "skipped": [],
                "sources": [],
                "evidence": [],
                "findings": [],
                "sourceIds": [],
                "evidenceIds": [],
            },
        )
        client = OneShotHarnessClient(payload)
        with EnvPatch(RAMS_MATERIAL_HARNESS_ARN="arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_material_harness-ABCDEFGHIJ"):
            invoker = AgentCoreHarnessInvoker(config=config, client=client)
            result = invoker.invoke_material(
                [
                    {
                        "materialId": "asio_material_site_access_plan",
                        "sourceSystem": "asio",
                        "type": "application/pdf",
                        "label": "Site access plan",
                        "access": {
                            "mode": "asio_authorized_reference",
                            "retrievalUrl": "https://materials.example.invalid/private.pdf?token=SHOULD_NOT_LEAK",
                            "token": "SHOULD_NOT_LEAK",
                        },
                    }
                ],
                case_id="case_material_invoker_002",
                upstream_context={"source": "ASI_ONE"},
            )

        self.assertEqual(result["subagent"]["name"], "material_subagent")
        self.assertEqual(
            client.calls[0]["harnessArn"],
            "arn:aws:bedrock-agentcore:eu-west-2:123456789012:harness/rams_material_harness-ABCDEFGHIJ",
        )
        first_prompt = json.dumps(client.calls[0]["messages"])
        self.assertNotIn("SHOULD_NOT_LEAK", first_prompt)
        self.assertNotIn("retrievalUrl", first_prompt)
        self.assertIn("retrieval", first_prompt)

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


if __name__ == "__main__":
    unittest.main()
