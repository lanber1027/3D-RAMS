from __future__ import annotations

import sys
import unittest
from pathlib import Path


ENTRY_APP_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_APP_ROOT = ENTRY_APP_ROOT.parent / "rams_supervisor_runtime"
TOOLS_ROOT = ENTRY_APP_ROOT.parent / "rams_agent_tools"
for app_root in (ENTRY_APP_ROOT, SUPERVISOR_APP_ROOT, TOOLS_ROOT):
    if str(app_root) in sys.path:
        sys.path.remove(str(app_root))
for app_root in (TOOLS_ROOT, SUPERVISOR_APP_ROOT, ENTRY_APP_ROOT):
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

from main import handle_invocation, invoke_local  # noqa: E402
from supervisor_core.agentcore_adapter import handle_invocation as invoke_supervisor_local  # noqa: E402
from supervisor_adapter import (  # noqa: E402
    AdapterValidationError,
    build_agentcore_invocation,
    build_delivery_payload,
)


def confirmed_entry_payload() -> dict:
    return {
        "conversationId": "agentverse-session-id",
        "entryAgentId": "rams-entry-agent",
        "confirmedByUser": True,
        "intake": {
            "locationText": "near 8 Albert Embankment, Lambeth",
            "locationCandidate": {
                "label": "Lambeth Thames public fixture",
                "lat": 51.4908,
                "lng": -0.1216,
                "confidence": 0.82,
            },
            "areaScope": {"type": "radius", "meters": 800},
            "userGoal": "pre-visit site risk and planning context",
            "userNotes": "Focus on flood context, access, and public interface constraints.",
            "materials": [
                {
                    "type": "note",
                    "label": "User note",
                    "summary": "Client is considering an early feasibility walkover.",
                }
            ],
        },
        "runtimeOptions": {
            "fixturePack": "public-lambeth-thames",
            "useBedrock": False,
            "includePlanningFixture": True,
            "simulateMapFailure": False,
        },
    }


class AgentVerseAdapterTests(unittest.TestCase):
    def test_rejects_unconfirmed_entry_payload(self):
        payload = confirmed_entry_payload()
        payload["confirmedByUser"] = False

        with self.assertRaisesRegex(AdapterValidationError, "confirmedByUser"):
            build_agentcore_invocation(payload)

    def test_rejects_payload_without_area_scope(self):
        payload = confirmed_entry_payload()
        del payload["intake"]["areaScope"]

        with self.assertRaisesRegex(AdapterValidationError, "areaScope"):
            build_agentcore_invocation(payload)

    def test_maps_confirmed_entry_payload_to_agentcore_invocation(self):
        invocation = build_agentcore_invocation(confirmed_entry_payload())

        agent_input = invocation["input"]
        self.assertEqual(agent_input["siteName"], "Lambeth Thames public fixture")
        self.assertEqual(agent_input["latitude"], 51.4908)
        self.assertEqual(agent_input["longitude"], -0.1216)
        self.assertEqual(agent_input["fixturePack"], "public-lambeth-thames")
        self.assertFalse(agent_input["useBedrock"])
        self.assertEqual(agent_input["upstream"]["source"], "AGENTVERSE")
        self.assertTrue(agent_input["upstream"]["confirmedByUser"])
        self.assertEqual(agent_input["upstream"]["materialCount"], 1)

    def test_maps_agentcore_response_to_entry_delivery_payload(self):
        entry_payload = confirmed_entry_payload()
        invocation = build_agentcore_invocation(entry_payload)
        agentcore_response = invoke_local(invocation)
        self.assertEqual(
            agentcore_response["output"]["run"]["upstream"]["conversationId"],
            "agentverse-session-id",
        )

        delivery = build_delivery_payload(agentcore_response, entry_payload=entry_payload)

        self.assertEqual(delivery["conversationId"], "agentverse-session-id")
        self.assertEqual(delivery["status"], "review_required")
        self.assertEqual(delivery["workflowMode"], "cached_public_fixture")
        self.assertEqual(delivery["customerSummary"]["title"], "8 Albert Embankment and land to the rear")
        self.assertTrue(delivery["customerSummary"]["summary"])
        self.assertTrue(delivery["deepReport"]["visualizationReady"])
        self.assertGreaterEqual(delivery["deepReport"]["evidenceCount"], 1)
        self.assertGreaterEqual(delivery["deepReport"]["traceCount"], 9)

    def test_entry_cloud_handoff_invokes_supervisor_runtime(self):
        calls: list[dict] = []

        def fake_invoke_runtime(**kwargs):
            calls.append(kwargs)
            return invoke_supervisor_local(kwargs["payload"])

        response = handle_invocation(
            confirmed_entry_payload(),
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=fake_invoke_runtime,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["runtime_arn"], "arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test")
        self.assertEqual(calls[0]["payload"]["input"]["upstream"]["source"], "AGENTVERSE")
        output = response["output"]
        self.assertEqual(output["reportStatus"], "review_required")
        self.assertEqual(output["workflowMode"], "cached_public_fixture")
        self.assertEqual(output["entryAgent"]["mode"], "cloud-supervisor-handoff")
        self.assertTrue(output["structuredReport"]["visualization"]["annotations"])
        self.assertIsNone(output["run"]["runtime"].get("localAsiOneSubstitute"))

    def test_entry_cloud_handoff_requires_supervisor_runtime_arn(self):
        with self.assertRaisesRegex(AdapterValidationError, "RAMS_SUPERVISOR_RUNTIME_ARN"):
            handle_invocation(confirmed_entry_payload(), supervisor_runtime_arn="", invoke_runtime=lambda **_: {})


if __name__ == "__main__":
    unittest.main()
