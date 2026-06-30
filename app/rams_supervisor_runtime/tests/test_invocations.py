from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from main import invoke_local, ping_local  # noqa: E402
from supervisor_core.agent import run_site_briefing  # noqa: E402
from supervisor_core.report_store import persist_report  # noqa: E402


class AgentCoreInvocationTests(unittest.TestCase):
    def test_ping_local_reports_agentcore_service(self):
        self.assertEqual(ping_local(), {"status": "ok", "service": "3d-rams-agentcore"})

    def test_invocation_wraps_existing_run_contract(self):
        response = invoke_local(
            {
                "input": {
                    "caseId": "case_supervisor_test_001",
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "upstream": {"source": "ASI_ONE", "confirmedByUser": True},
                }
            }
        )

        output = response["output"]
        run = output["run"]
        report = output["structuredReport"]
        self.assertEqual(output["caseId"], "case_supervisor_test_001")
        self.assertEqual(run["caseId"], "case_supervisor_test_001")
        self.assertEqual(run["request"]["caseId"], "case_supervisor_test_001")
        self.assertEqual(report["caseId"], "case_supervisor_test_001")
        self.assertEqual(report["intake"]["caseId"], "case_supervisor_test_001")
        self.assertEqual(output["persistence"]["mode"], "disabled")
        self.assertEqual(output["persistence"]["status"], "skipped")
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
        self.assertIn("reasoning", report)
        self.assertEqual(report["reasoning"]["mode"], "deterministic")
        self.assertTrue(report["reviewGate"]["reviewerNotes"])
        section_statuses = {section["id"]: section["status"] for section in report["sections"]}
        self.assertEqual(section_statuses["open-web-signals"], "warning")
        self.assertTrue(report["findings"][0]["rationale"])
        self.assertFalse(report["dataQuality"]["completeness"]["hasOpenWebSignals"])
        self.assertTrue(any("Open-web signals" in gap for gap in report["dataQuality"]["gaps"]))
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
        self.assertEqual(report["reasoning"]["conflicts"][0]["id"], "safety-boundary")
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["visualization"]["annotations"], [])

    def test_packaged_workflow_matches_existing_fixture_mode(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        self.assertEqual(result["runtime"]["fixturePackMode"], "cached-public-fixture")
        self.assertEqual(result["scene"]["provider"], "cesium-local-cached-fixture")
        self.assertTrue(result["evidence"])

    def test_local_asione_envelope_routes_through_entry_and_supervisor(self):
        response = invoke_local(
            {
                "localAsiOne": True,
                "sessionId": "local-demo-session",
                "conversationId": "local-demo-session",
                "message": (
                    "Please prepare a pre-visit site review near 8 Albert Embankment, Lambeth "
                    "within an 800 metre area for flood context, access, and public interface constraints."
                ),
                "confirmedByUser": True,
                "runtimeOptions": {
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "includePlanningFixture": True,
                    "simulateMapFailure": False,
                },
            }
        )

        output = response["output"]
        entry = output["localAsiOne"]
        run = output["run"]
        self.assertFalse(entry["needsClarification"])
        self.assertFalse(entry["needsConfirmation"])
        self.assertEqual(output["reportStatus"], "review_required")
        self.assertEqual(output["persistence"]["mode"], "disabled")
        self.assertEqual(entry["delivery"]["workflowMode"], "cached_public_fixture")
        self.assertEqual(run["runtime"]["localAsiOneSubstitute"], True)
        self.assertEqual(run["runtime"]["entryAgentMode"], "deterministic-local")
        trace_names = [step["name"] for step in run["trace"]]
        self.assertLess(trace_names.index("entry_agent_supervisor_handoff"), trace_names.index("plan_subagent_workflow"))
        self.assertEqual(trace_names[-1], "entry_agent_delivery_summary")

    def test_local_asione_envelope_clarifies_before_supervisor(self):
        response = invoke_local(
            {
                "localAsiOne": True,
                "sessionId": "local-demo-session",
                "message": "Can you help me?",
                "confirmedByUser": True,
                "runtimeOptions": {"useBedrock": False},
            }
        )

        output = response["output"]
        entry = output["localAsiOne"]
        self.assertEqual(output["reportStatus"], "entry_pending")
        self.assertTrue(entry["needsClarification"])
        self.assertIsNone(output["run"])
        self.assertEqual(entry["runtime"]["supervisorRuntime"], "not-invoked")

    def test_report_store_writes_dynamodb_item_when_table_is_configured(self):
        response = invoke_local(
            {
                "input": {
                    "caseId": "case_store_test_001",
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                }
            }
        )
        output = response["output"]
        writes: list[dict] = []

        class FakeTable:
            def put_item(self, *, Item):
                writes.append(Item)

        with patch.dict("os.environ", {"RAMS_REPORT_STORE_TABLE": "rams-report-store-test"}):
            persistence = persist_report(output, table=FakeTable())

        self.assertEqual(persistence["mode"], "dynamodb")
        self.assertEqual(persistence["status"], "stored")
        self.assertEqual(persistence["tableName"], "rams-report-store-test")
        self.assertEqual(persistence["caseId"], "case_store_test_001")
        self.assertEqual(len(writes), 1)
        item = writes[0]
        self.assertEqual(item["caseId"], "case_store_test_001")
        self.assertEqual(item["reportStatus"], "review_required")
        self.assertEqual(item["workflowMode"], "cached_public_fixture")
        self.assertEqual(item["structuredReport"]["caseId"], "case_store_test_001")
        self.assertEqual(item["runSummary"]["runtime"]["fixturePack"], "public-lambeth-thames")


if __name__ == "__main__":
    unittest.main()
