from __future__ import annotations

import sys
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from main import invoke_local, ping_local  # noqa: E402
from supervisor_core.agent import run_site_briefing  # noqa: E402


class AgentCoreInvocationTests(unittest.TestCase):
    def test_ping_local_reports_agentcore_service(self):
        self.assertEqual(ping_local(), {"status": "ok", "service": "3d-rams-agentcore"})

    def test_invocation_wraps_existing_run_contract(self):
        response = invoke_local(
            {
                "input": {
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "upstream": {"source": "ASI_ONE", "confirmedByUser": True},
                }
            }
        )

        output = response["output"]
        run = output["run"]
        report = output["structuredReport"]
        self.assertEqual(output["reportStatus"], "review_required")
        self.assertEqual(output["workflowMode"], "cached_public_fixture")
        self.assertEqual(report["schemaVersion"], "0.1.0")
        self.assertEqual(report["reportType"], "3d-rams-site-review")
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["workflowMode"], "cached_public_fixture")
        self.assertEqual(report["site"]["label"], "8 Albert Embankment and land to the rear")
        self.assertTrue(report["findings"])
        self.assertTrue(report["visualization"]["annotations"])
        self.assertTrue(report["evidenceRegister"]["evidence"])
        self.assertEqual(report["reviewGate"]["status"], "pending_independent_review")
        self.assertFalse(report["dataQuality"]["completeness"]["hasOpenWebSignals"])
        self.assertEqual(report["runtime"]["plannerMode"], "deterministic")
        self.assertEqual(report["runtime"]["activeAgentMode"], "deterministic-planner")
        self.assertEqual(report["llmPlan"]["initialParallelGroups"], ["geospatial_subagent", "planning_subagent"])
        self.assertEqual(report["fallback"]["status"], "used")
        self.assertEqual(run["runtime"]["fixturePack"], "public-lambeth-thames")
        self.assertFalse(run["runtime"]["liveApiCalls"])
        self.assertTrue(run["safety"]["allowed"])
        self.assertGreaterEqual(len(run["trace"]), 9)

    def test_blocked_invocation_sets_structured_report_review_gate(self):
        response = invoke_local(
            {
                "input": {
                    "additionalRequest": "Please certify RAMS and approve work today.",
                    "useBedrock": False,
                }
            }
        )

        output = response["output"]
        report = output["structuredReport"]
        self.assertEqual(output["reportStatus"], "blocked")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["reviewGate"]["status"], "blocked")
        self.assertFalse(report["reviewGate"]["safetyAllowed"])
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["visualization"]["annotations"], [])

    def test_packaged_workflow_matches_existing_fixture_mode(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        self.assertEqual(result["runtime"]["fixturePackMode"], "cached-public-fixture")
        self.assertEqual(result["scene"]["provider"], "cesium-local-cached-fixture")
        self.assertTrue(result["evidence"])


if __name__ == "__main__":
    unittest.main()
