from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from main import invoke_local, ping_local  # noqa: E402
from supervisor_core.agent import run_site_briefing  # noqa: E402
from supervisor_core.harness_contract import HARNESS_OUTPUT_SCHEMA_VERSION  # noqa: E402
from supervisor_core.report_store import build_report_store_item, load_report, persist_report  # noqa: E402


def report_access(
    case_id: str,
    *,
    subject_id: str = "asi-user-1",
    session_id: str = "asi-session-1",
    mode: str = "asi_identity",
    expires_at: str | None = None,
) -> dict:
    access = {
        "schemaVersion": "3d-rams.report-access.v1",
        "mode": mode,
        "caseId": case_id,
        "authorizedCaseIds": [case_id],
        "source": "ASI_ONE",
    }
    if subject_id:
        access["subjectId"] = subject_id
    if session_id:
        access["sessionId"] = session_id
    if expires_at:
        access["expiresAt"] = expires_at
    return access


def dev_report_access(case_id: str) -> dict:
    return {
        "schemaVersion": "3d-rams.report-access.v1",
        "mode": "dev_local",
        "caseId": case_id,
        "authorizedCaseIds": [case_id],
        "sessionId": "local-dev-session",
    }


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
                    "upstream": {"source": "ASI_ONE", "caseId": "case_supervisor_test_001", "confirmedByUser": True},
                }
            }
        )

        output = response["output"]
        run = output["run"]
        report = output["structuredReport"]
        self.assertEqual(output["caseId"], "case_supervisor_test_001")
        self.assertEqual(run["caseId"], "case_supervisor_test_001")
        self.assertEqual(run["request"]["caseId"], "case_supervisor_test_001")
        self.assertEqual(run["runtime"]["caseId"], "case_supervisor_test_001")
        self.assertEqual(report["caseId"], "case_supervisor_test_001")
        self.assertEqual(report["intake"]["caseId"], "case_supervisor_test_001")
        self.assertTrue(all(step["caseId"] == "case_supervisor_test_001" for step in run["trace"]))
        self.assertTrue(all(step["output"]["caseId"] == "case_supervisor_test_001" for step in run["trace"] if isinstance(step.get("output"), dict)))
        self.assertEqual(output["persistence"]["mode"], "disabled")
        self.assertEqual(output["persistence"]["status"], "skipped")
        self.assertEqual(output["reportStatus"], "review_passed")
        self.assertEqual(output["workflowMode"], "cached_public_fixture")
        self.assertEqual(report["schemaVersion"], "0.1.0")
        self.assertEqual(report["reportType"], "3d-rams-site-review")
        self.assertEqual(report["status"], "review_passed")
        self.assertEqual(report["workflowMode"], "cached_public_fixture")
        self.assertEqual(report["site"]["label"], "8 Albert Embankment and land to the rear")
        self.assertTrue(report["findings"])
        self.assertTrue(report["visualization"]["annotations"])
        self.assertTrue(report["evidenceRegister"]["evidence"])
        self.assertEqual(output["reviewMetadata"]["status"], "passed_with_caveats")
        self.assertEqual(output["reviewGate"]["status"], "passed_with_caveats")
        self.assertEqual(report["reviewGate"]["status"], "passed_with_caveats")
        self.assertEqual(report["reviewGate"]["decision"], "pass_with_caveats")
        self.assertEqual(report["reviewGate"]["revisionCount"], 0)
        self.assertIn("reasoning", report)
        self.assertEqual(report["reasoning"]["mode"], "deterministic")
        self.assertTrue(report["reviewGate"]["reviewerNotes"])
        section_statuses = {section["id"]: section["status"] for section in report["sections"]}
        self.assertEqual(section_statuses["open-web-signals"], "warning")
        self.assertTrue(report["findings"][0]["rationale"])
        self.assertFalse(report["dataQuality"]["completeness"]["hasOpenWebSignals"])
        self.assertTrue(report["dataQuality"]["completeness"]["harnessOutputsContractCompliant"])
        self.assertTrue(any("Open-web signals" in gap for gap in report["dataQuality"]["gaps"]))
        self.assertEqual(report["runtime"]["plannerMode"], "deterministic")
        self.assertEqual(report["runtime"]["activeAgentMode"], "deterministic-planner")
        self.assertEqual(report["runtime"]["harnessOutputSchemaVersion"], HARNESS_OUTPUT_SCHEMA_VERSION)
        self.assertTrue(report["runtime"]["harnessContract"]["contractCompliant"])
        self.assertFalse(report["runtime"]["bedrockRequested"])
        self.assertFalse(report["runtime"]["bedrockEnabled"])
        self.assertFalse(report["runtime"]["bedrockUsed"])
        self.assertEqual(report["llmPlan"]["initialParallelGroups"], ["geospatial_subagent", "planning_subagent"])
        self.assertEqual(report["fallback"]["status"], "used")
        self.assertEqual(run["runtime"]["fixturePack"], "public-lambeth-thames")
        self.assertFalse(run["runtime"]["liveApiCalls"])
        self.assertTrue(run["safety"]["allowed"])
        self.assertGreaterEqual(len(run["trace"]), 9)

    def test_invocation_structured_report_includes_material_citations(self):
        response = invoke_local(
            {
                "input": {
                    "caseId": "case_material_report_001",
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "materials": [
                        {
                            "materialId": "asio_material_site_access_plan",
                            "sourceSystem": "asio",
                            "type": "application/pdf",
                            "label": "Site access plan",
                            "summary": "Uploaded by the ASI user for this case.",
                            "caseId": "case_material_report_001",
                            "access": {
                                "mode": "asio_authorized_reference",
                                "expiresAt": "2099-01-01T00:00:00Z",
                            },
                        }
                    ],
                }
            }
        )

        output = response["output"]
        run = output["run"]
        report = output["structuredReport"]
        self.assertEqual(run["materialIngestion"]["accepted"], 1)
        self.assertEqual(report["materialIngestion"]["accepted"], 1)
        self.assertTrue(report["dataQuality"]["completeness"]["hasMaterialEvidence"])
        section_statuses = {section["id"]: section["status"] for section in report["sections"]}
        self.assertEqual(section_statuses["user-materials"], "ready")

        material_evidence = [
            item for item in report["evidenceRegister"]["evidence"]
            if item["id"] == "ev-material-asio-material-site-access-plan"
        ]
        self.assertEqual(len(material_evidence), 1)
        self.assertTrue(material_evidence[0]["citations"])
        self.assertFalse(material_evidence[0]["citations"][0]["rawContentStored"])
        self.assertTrue(any(finding["id"].startswith("material-asio-material-site-access-plan") for finding in report["findings"]))

    def test_invocation_structured_report_includes_mock_open_web_signals(self):
        secret = "dummy-report-tavily-secret"
        mock_results = json.dumps(
            {
                "results": [
                    {
                        "title": f"Public access article {secret}",
                        "url": "https://news.example.org/3d-rams-public-access",
                        "content": f"Public article snippet with {secret} scrubbed.",
                        "score": 0.77,
                        "published_date": "2026-06-20",
                    }
                ]
            }
        )
        with patch.dict(
            "os.environ",
            {
                "TAVILY_MOCK_RESPONSE": "true",
                "TAVILY_API_KEY": secret,
                "TAVILY_MOCK_RESULTS_JSON": mock_results,
            },
        ):
            response = invoke_local(
                {
                    "input": {
                        "caseId": "case_open_web_report_001",
                        "fixturePack": "public-lambeth-thames",
                        "useBedrock": False,
                        "areaScope": {"type": "radius", "meters": 25},
                    }
                }
            )

        output = response["output"]
        run = output["run"]
        report = output["structuredReport"]
        section_statuses = {section["id"]: section["status"] for section in report["sections"]}

        self.assertEqual(run["externalSignals"]["openWeb"]["status"], "ok")
        self.assertEqual(report["externalSignals"]["openWeb"]["status"], "ok")
        self.assertTrue(report["dataQuality"]["completeness"]["hasOpenWebSignals"])
        self.assertEqual(section_statuses["open-web-signals"], "ready")
        self.assertFalse(run["runtime"]["liveApiCalls"])
        serialized = json.dumps(output)
        self.assertNotIn(secret, serialized)
        self.assertIn("[redacted]", serialized)

    def test_bedrock_fallback_reason_reaches_structured_report_data_quality(self):
        with patch.dict(
            "os.environ",
            {
                "ENABLE_BEDROCK": "true",
                "BEDROCK_SIMULATE_FAILURE": "true",
            },
        ):
            response = invoke_local({"input": {"fixturePack": "public-lambeth-thames", "useBedrock": True}})

        report = response["output"]["structuredReport"]
        self.assertIn("bedrock_simulated_failure", report["runtime"]["fallbackReason"])
        self.assertFalse(report["runtime"]["bedrockUsed"])
        self.assertIn("bedrock_simulated_failure", report["dataQuality"]["gaps"])

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

        self.assertRegex(result["caseId"], r"^case_[0-9a-f]{12}$")
        self.assertEqual(result["request"]["caseId"], result["caseId"])
        self.assertEqual(result["runtime"]["caseId"], result["caseId"])
        self.assertTrue(all(step["caseId"] == result["caseId"] for step in result["trace"]))
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
        self.assertEqual(output["reportStatus"], "review_passed")
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
                    "upstream": {
                        "source": "ASI_ONE",
                        "caseId": "case_store_test_001",
                        "confirmedByUser": True,
                        "reportAccess": report_access("case_store_test_001"),
                    },
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
        self.assertEqual(item["reportStatus"], "review_passed")
        self.assertEqual(item["workflowMode"], "cached_public_fixture")
        self.assertEqual(item["schemaVersion"], "3d-rams.report-store.v1")
        self.assertEqual(item["recordType"], "case-correlated-report-evidence")
        self.assertEqual(item["authorizationBinding"]["mode"], "local_dev_unbound")
        self.assertFalse(item["authorizationBinding"]["requiredForLookup"])
        self.assertEqual(item["structuredReport"]["caseId"], "case_store_test_001")
        self.assertEqual(item["run"]["caseId"], "case_store_test_001")
        self.assertEqual(item["run"]["upstream"]["reportAccess"]["status"], "redacted")
        self.assertEqual(item["runSummary"]["runtime"]["fixturePack"], "public-lambeth-thames")
        self.assertEqual(item["reportAccessBinding"]["caseId"], "case_store_test_001")
        self.assertEqual(item["reportAccessBinding"]["mode"], "asi_identity")
        self.assertIn("subjectIdHash", item["reportAccessBinding"])
        self.assertIn("sessionIdHash", item["reportAccessBinding"])
        self.assertNotIn("subjectId", item["reportAccessBinding"])
        self.assertNotIn("sessionId", item["reportAccessBinding"])
        self.assertTrue(item["evidenceSummary"])
        self.assertTrue(item["citationMetadata"]["sources"])
        self.assertTrue(item["traceSummary"])
        self.assertEqual(item["traceSummary"][0]["caseId"], "case_store_test_001")
        self.assertFalse(item["redaction"]["rawPrivateMaterialPersisted"])

    def test_report_store_omits_large_internal_run_fields(self):
        response = invoke_local(
            {
                "input": {
                    "caseId": "case_store_bounded_001",
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "upstream": {
                        "source": "ASI_ONE",
                        "caseId": "case_store_bounded_001",
                        "confirmedByUser": True,
                        "reportAccess": report_access("case_store_bounded_001"),
                    },
                }
            }
        )
        output = response["output"]
        output["run"]["subagentOutputs"] = {"large": "x" * 500_000}
        output["run"]["reviewInput"] = {"large": "x" * 500_000}
        writes: list[dict] = []

        class WriteTable:
            def put_item(self, *, Item):
                writes.append(Item)

        persistence = persist_report(output, table=WriteTable())

        self.assertEqual(persistence["status"], "stored")
        item = writes[0]
        self.assertEqual(item["caseId"], "case_store_bounded_001")
        self.assertIn("location", item["run"])
        self.assertIn("trace", item["run"])
        self.assertNotIn("subagentOutputs", item["run"])
        self.assertNotIn("reviewInput", item["run"])

    def test_report_lookup_returns_stored_report_payload(self):
        access = report_access("case_lookup_test_001")
        response = invoke_local(
            {
                "input": {
                    "caseId": "case_lookup_test_001",
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "upstream": {
                        "source": "ASI_ONE",
                        "caseId": "case_lookup_test_001",
                        "confirmedByUser": True,
                        "reportAccess": access,
                    },
                }
            }
        )
        output = response["output"]
        item = {}

        class WriteTable:
            def put_item(self, *, Item):
                item.update(Item)

        class FakeTable:
            def get_item(self, *, Key):
                assert Key == {"caseId": "case_lookup_test_001"}
                return {"Item": item}

        persist_report(output, table=WriteTable())

        lookup = load_report("case_lookup_test_001", access_context=access, table=FakeTable())
        lookup_output = lookup["output"]

        self.assertEqual(lookup_output["caseId"], "case_lookup_test_001")
        self.assertEqual(lookup_output["reportStatus"], "review_passed")
        self.assertEqual(lookup_output["persistence"]["status"], "loaded")
        self.assertEqual(lookup_output["reportAccess"]["status"], "authorized")
        self.assertEqual(lookup_output["reportAccess"]["reason"], "case_binding_authorized")
        self.assertEqual(lookup_output["structuredReport"]["caseId"], "case_lookup_test_001")
        self.assertEqual(lookup_output["run"]["caseId"], "case_lookup_test_001")
        self.assertEqual(lookup_output["run"]["upstream"]["reportAccess"]["status"], "redacted")
        self.assertTrue(lookup_output["evidenceSummary"])
        self.assertTrue(lookup_output["citationMetadata"]["sources"])

    def test_report_store_persists_review_metadata_variants(self):
        variants = [
            (
                "pass",
                {
                    "status": "passed",
                    "decision": "pass",
                    "reviewerMode": "deterministic",
                    "revisionCount": 0,
                    "issues": [],
                    "caveats": [],
                    "safetyAllowed": True,
                    "safetyLevel": "allowed",
                    "requiresHumanReview": True,
                    "message": "Review passed with no blocking issues.",
                },
                "review_passed",
            ),
            (
                "pass_with_caveats",
                {
                    "status": "passed_with_caveats",
                    "decision": "pass_with_caveats",
                    "reviewer": {"name": "review_guardrail", "mode": "harness"},
                    "revisionCount": 0,
                    "issues": [{"id": "planning-freshness", "severity": "low", "message": "Planning source freshness needs human confirmation."}],
                    "caveats": ["Confirm planning source freshness before site work."],
                    "safetyAllowed": True,
                    "safetyLevel": "allowed",
                    "requiresHumanReview": True,
                    "message": "Review passed with caveats.",
                },
                "review_passed",
            ),
            (
                "revise_to_final",
                {
                    "status": "passed",
                    "decision": "pass",
                    "reviewerMode": "deterministic",
                    "revisionCount": 1,
                    "issues": [{"id": "unsupported-finding", "severity": "medium", "message": "Unsupported finding was removed."}],
                    "caveats": ["One supervisor revision was applied before final delivery."],
                    "safetyAllowed": True,
                    "safetyLevel": "allowed",
                    "requiresHumanReview": True,
                    "message": "Review passed after bounded revision.",
                },
                "review_passed",
            ),
            (
                "blocked",
                {
                    "status": "blocked",
                    "decision": "block",
                    "reviewerMode": "deterministic",
                    "revisionCount": 0,
                    "issues": [{"id": "approval-to-work", "severity": "blocking", "message": "Approval-to-work claim is not allowed."}],
                    "caveats": [],
                    "safetyAllowed": False,
                    "safetyLevel": "blocked",
                    "requiresHumanReview": True,
                    "message": "Review blocked normal report delivery.",
                },
                "blocked",
            ),
        ]

        for slug, review_gate, report_status in variants:
            with self.subTest(slug=slug):
                case_id = f"case_review_{slug}"
                access = report_access(case_id)
                item = build_report_store_item(
                    {
                        "caseId": case_id,
                        "reportStatus": report_status,
                        "workflowMode": "cached_public_fixture",
                        "structuredReport": {
                            "caseId": case_id,
                            "status": report_status,
                            "reviewGate": review_gate,
                        },
                        "run": {"caseId": case_id, "upstream": {"reportAccess": access}},
                    }
                )

                class FakeTable:
                    def get_item(self, *, Key):
                        assert Key == {"caseId": case_id}
                        return {"Item": item}

                lookup = load_report(case_id, access_context=access, table=FakeTable())
                stored_review = item["reviewMetadata"]
                loaded_review = lookup["output"]["reviewMetadata"]

                self.assertEqual(item["reviewGate"], stored_review)
                self.assertEqual(lookup["output"]["reviewGate"], loaded_review)
                self.assertEqual(stored_review["status"], review_gate["status"])
                self.assertEqual(stored_review["decision"], review_gate["decision"])
                self.assertEqual(stored_review["issues"], review_gate["issues"])
                self.assertEqual(stored_review["caveats"], review_gate["caveats"])
                self.assertEqual(stored_review["revisionCount"], review_gate["revisionCount"])
                self.assertEqual(stored_review["reviewerMode"], review_gate.get("reviewerMode") or review_gate["reviewer"]["mode"])
                self.assertEqual(loaded_review["status"], review_gate["status"])
                self.assertEqual(loaded_review["decision"], review_gate["decision"])
                self.assertEqual(loaded_review["revisionCount"], review_gate["revisionCount"])
                self.assertEqual(lookup["output"]["structuredReport"]["reviewGate"]["status"], review_gate["status"])

    def test_report_lookup_denies_without_access_context(self):
        outer = self

        class FakeTable:
            def get_item(self, *, Key):
                outer.fail("lookup should be denied before reading report storage")

        lookup = load_report("case_lookup_test_001", table=FakeTable())

        output = lookup["output"]
        self.assertEqual(output["reportStatus"], "access_denied")
        self.assertEqual(output["reportAccess"]["reason"], "missing_report_access_context")
        self.assertNotIn("run", output)
        self.assertNotIn("structuredReport", output)

    def test_report_lookup_denies_wrong_user_binding(self):
        case_id = "case_wrong_user_lookup_test_001"
        stored_access = report_access(case_id, subject_id="asi-user-owner", session_id="asi-session-owner")
        wrong_access = report_access(case_id, subject_id="asi-user-other", session_id="asi-session-owner")
        item = build_report_store_item(
            {
                "caseId": case_id,
                "reportStatus": "review_required",
                "workflowMode": "cached_public_fixture",
                "structuredReport": {"caseId": case_id},
                "run": {"caseId": case_id, "upstream": {"reportAccess": stored_access}},
            }
        )

        class FakeTable:
            def get_item(self, *, Key):
                assert Key == {"caseId": case_id}
                return {"Item": item}

        lookup = load_report(case_id, access_context=wrong_access, table=FakeTable())

        output = lookup["output"]
        self.assertEqual(output["reportStatus"], "access_denied")
        self.assertEqual(output["reportAccess"]["reason"], "report_subject_mismatch")
        self.assertNotIn("run", output)

    def test_report_lookup_denies_expired_binding(self):
        case_id = "case_expired_lookup_test_001"
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        stored_access = report_access(case_id, expires_at=expired_at)
        fresh_access = report_access(case_id)
        item = build_report_store_item(
            {
                "caseId": case_id,
                "reportStatus": "review_required",
                "workflowMode": "cached_public_fixture",
                "structuredReport": {"caseId": case_id},
                "run": {"caseId": case_id, "upstream": {"reportAccess": stored_access}},
            }
        )

        class FakeTable:
            def get_item(self, *, Key):
                assert Key == {"caseId": case_id}
                return {"Item": item}

        lookup = load_report(case_id, access_context=fresh_access, table=FakeTable())

        output = lookup["output"]
        self.assertEqual(output["reportStatus"], "access_denied")
        self.assertEqual(output["reportAccess"]["reason"], "report_access_binding_expired")
        self.assertNotIn("structuredReport", output)

    def test_bound_report_lookup_requires_matching_authorized_context(self):
        access = report_access("case_bound_lookup_001", mode="asi_session", subject_id="", session_id="agentverse-session-id")
        response = invoke_local(
            {
                "input": {
                    "caseId": "case_bound_lookup_001",
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "materials": [
                        {
                            "materialId": "asio_material_001",
                            "sourceSystem": "asio",
                            "type": "application/pdf",
                            "label": "Site access plan",
                            "summary": "Authorized ASI material reference for this case.",
                            "access": {
                                "mode": "asio_authorized_reference",
                                "expiresAt": "2026-06-30T18:00:00Z",
                                "status": "not_retrieved",
                            },
                            "signedUrl": "https://example.invalid/private-download",
                        }
                    ],
                    "upstream": {
                        "source": "AGENTVERSE",
                        "caseId": "case_bound_lookup_001",
                        "conversationId": "agentverse-session-id",
                        "entryAgentId": "@3d-rams",
                        "confirmedByUser": True,
                        "materialCount": 1,
                        "reportAccess": access,
                    },
                }
            }
        )
        output = response["output"]
        item = {}

        class WriteTable:
            def put_item(self, *, Item):
                item.update(Item)

        class FakeTable:
            def get_item(self, *, Key):
                assert Key == {"caseId": "case_bound_lookup_001"}
                return {"Item": item}

        persist_report(output, table=WriteTable())

        self.assertEqual(item["authorizationBinding"]["mode"], "asi_identity_bound")
        self.assertTrue(item["authorizationBinding"]["requiredForLookup"])
        self.assertEqual(item["authorizationBinding"]["conversationId"], "agentverse-session-id")
        self.assertEqual(item["reportAccessBinding"]["mode"], "asi_session")
        self.assertIn("sessionIdHash", item["reportAccessBinding"])
        self.assertEqual(item["materialEvidenceSummary"]["status"], "references_recorded")
        self.assertEqual(item["materialEvidenceSummary"]["items"][0]["materialId"], "asio_material_001")
        self.assertNotIn("signedUrl", item["materialEvidenceSummary"]["items"][0])
        self.assertNotIn("signedUrl", item["run"]["request"]["materials"][0])

        denied = load_report("case_bound_lookup_001", table=FakeTable())
        self.assertEqual(denied["output"]["reportStatus"], "access_denied")
        self.assertEqual(denied["output"]["reportAccess"]["reason"], "missing_report_access_context")
        self.assertNotIn("run", denied["output"])

        wrong_access = report_access("case_bound_lookup_001", mode="asi_session", subject_id="", session_id="different-session")
        wrong_context = load_report(
            "case_bound_lookup_001",
            table=FakeTable(),
            access_context=wrong_access,
        )
        self.assertEqual(wrong_context["output"]["reportStatus"], "access_denied")
        self.assertEqual(wrong_context["output"]["reportAccess"]["reason"], "report_session_mismatch")

        authorized = load_report(
            "case_bound_lookup_001",
            table=FakeTable(),
            access_context=access,
        )
        self.assertEqual(authorized["output"]["reportStatus"], "review_passed")
        self.assertEqual(authorized["output"]["reportAccess"]["status"], "authorized")
        self.assertEqual(authorized["output"]["materialEvidenceSummary"]["items"][0]["materialId"], "asio_material_001")

    def test_report_lookup_returns_json_safe_dynamodb_numbers(self):
        case_id = "case_decimal_lookup_test_001"
        access = report_access(case_id, mode="asi_session", subject_id="", session_id="asi-session-decimal")
        item = build_report_store_item(
            {
                "caseId": case_id,
                "reportStatus": "review_required",
                "workflowMode": "cached_public_fixture",
                "structuredReport": {"caseId": case_id},
                "run": {"caseId": case_id, "upstream": {"reportAccess": access}},
            }
        )
        item["structuredReport"]["riskScore"] = Decimal("4.5")
        item["run"]["traceCount"] = Decimal("11")

        class FakeTable:
            def get_item(self, *, Key):
                assert Key == {"caseId": case_id}
                return {"Item": item}

        lookup = load_report(case_id, access_context=access, table=FakeTable())

        self.assertEqual(lookup["output"]["structuredReport"]["riskScore"], 4.5)
        self.assertEqual(lookup["output"]["run"]["traceCount"], 11)

    def test_report_lookup_without_table_returns_not_found_contract(self):
        response = invoke_local(
            {
                "input": {
                    "operation": "getReport",
                    "caseId": "case_missing_local",
                    "reportAccess": dev_report_access("case_missing_local"),
                }
            }
        )

        output = response["output"]

        self.assertEqual(output["caseId"], "case_missing_local")
        self.assertEqual(output["reportStatus"], "not_found")
        self.assertEqual(output["workflowMode"], "report_lookup")
        self.assertEqual(output["reportAccess"]["status"], "authorized")
        self.assertEqual(output["persistence"]["mode"], "disabled")


if __name__ == "__main__":
    unittest.main()
