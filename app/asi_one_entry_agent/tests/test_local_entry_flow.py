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
for app_root in (ENTRY_APP_ROOT, SUPERVISOR_APP_ROOT, TOOLS_ROOT):
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

from local_entry_flow import run_local_asione_chat  # noqa: E402
from supervisor_core.agentcore_adapter import handle_invocation  # noqa: E402


LAUNCH_READY_PAYLOAD = {
    "localAsiOne": True,
    "sessionId": "local-test-session",
    "conversationId": "local-test-session",
    "message": (
        "Please prepare a pre-visit site review near 8 Albert Embankment, Lambeth "
        "within an 800 metre area for flood context, access, and public interface constraints."
    ),
    "runtimeOptions": {
        "fixturePack": "public-lambeth-thames",
        "useBedrock": False,
        "includePlanningFixture": True,
        "simulateMapFailure": False,
    },
}


class LocalAsiOneEntryFlowTests(unittest.TestCase):
    def test_clarifies_when_site_scope_and_goal_are_missing(self):
        response = run_local_asione_chat(
            {
                "localAsiOne": True,
                "sessionId": "local-test-session",
                "message": "Can you help me?",
                "confirmedByUser": True,
                "runtimeOptions": {"useBedrock": False},
            },
            supervisor_invoker=handle_invocation,
        )

        self.assertTrue(response["needsClarification"])
        self.assertIsNone(response["run"])
        self.assertEqual(response["runtime"]["supervisorRuntime"], "not-invoked")
        self.assertGreaterEqual(len(response["clarifyingQuestions"]), 3)
        self.assertEqual(response["trace"][0]["name"], "entry_intake_parse")

    def test_launch_ready_payload_can_stop_for_confirmation(self):
        payload = dict(LAUNCH_READY_PAYLOAD)
        payload["confirmedByUser"] = False

        response = run_local_asione_chat(payload, supervisor_invoker=handle_invocation)

        self.assertFalse(response["needsClarification"])
        self.assertTrue(response["needsConfirmation"])
        self.assertIsNone(response["run"])
        self.assertEqual(response["runtime"]["supervisorRuntime"], "awaiting-confirmation")
        self.assertIn("8 Albert Embankment", response["confirmation"]["summary"])

    def test_compact_kilometre_scope_is_launch_ready(self):
        response = run_local_asione_chat(
            {
                "localAsiOne": True,
                "sessionId": "local-test-session",
                "message": "I want to visit 8 Albert Embankment tomorrow for a survey for 2km",
                "confirmedByUser": False,
                "runtimeOptions": {"useBedrock": False},
            },
            supervisor_invoker=handle_invocation,
        )

        self.assertFalse(response["needsClarification"])
        self.assertTrue(response["needsConfirmation"])
        self.assertIn("2000m area", response["confirmation"]["summary"])

    def test_confirmed_payload_runs_entry_supervisor_delivery_flow(self):
        payload = dict(LAUNCH_READY_PAYLOAD)
        payload["confirmedByUser"] = True

        response = run_local_asione_chat(payload, supervisor_invoker=handle_invocation)

        self.assertFalse(response["needsClarification"])
        self.assertFalse(response["needsConfirmation"])
        self.assertIsNotNone(response["run"])
        self.assertEqual(response["delivery"]["status"], "passed_with_caveats")
        self.assertEqual(response["run"]["runtime"]["localAsiOneSubstitute"], True)
        trace_names = [step["name"] for step in response["run"]["trace"]]
        self.assertIn("entry_intake_parse", trace_names)
        self.assertIn("entry_agent_supervisor_handoff", trace_names)
        self.assertIn("plan_subagent_workflow", trace_names)
        self.assertIn("entry_agent_delivery_summary", trace_names)


if __name__ == "__main__":
    unittest.main()
