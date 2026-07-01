from __future__ import annotations

import json
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

from agentcore_client import extract_text_body  # noqa: E402
from main import handle_invocation, invoke_local  # noqa: E402
from supervisor_core.agentcore_adapter import handle_invocation as invoke_supervisor_local  # noqa: E402
from supervisor_adapter import (  # noqa: E402
    AdapterValidationError,
    build_agentcore_invocation,
    build_delivery_payload,
)


def confirmed_entry_payload() -> dict:
    return {
        "caseId": "case_test_agentverse_001",
        "caller": "agentverse",
        "conversationId": "agentverse-session-id",
        "entryAgentId": "rams-entry-agent",
        "confirmedByUser": True,
        "reportAccess": {
            "schemaVersion": "3d-rams.report-access.v1",
            "mode": "asi_session",
            "caseId": "case_test_agentverse_001",
            "sessionId": "agentverse-session-id",
            "authorizedCaseIds": ["case_test_agentverse_001"],
        },
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
                    "materialId": "asio_material_site_access_plan",
                    "sourceSystem": "asio",
                    "type": "application/pdf",
                    "label": "User note",
                    "summary": "Client is considering an early feasibility walkover.",
                    "caseId": "case_test_agentverse_001",
                    "access": {"mode": "asio_authorized_reference", "expiresAt": "2099-01-01T00:00:00Z"},
                    "signedUrl": "https://example.invalid/private-download",
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
    def assert_user_readable_response(self, response: dict) -> str:
        text = extract_text_body(json.dumps(response))
        self.assertTrue(text.strip())
        self.assertFalse(text.lstrip().startswith("{"))
        self.assertNotIn('"entryAgent"', text)
        return text

    def test_rejects_unconfirmed_entry_payload(self):
        payload = confirmed_entry_payload()
        payload["confirmedByUser"] = False

        with self.assertRaisesRegex(AdapterValidationError, "confirmedByUser"):
            build_agentcore_invocation(payload)

    def test_rejects_payload_without_case_id(self):
        payload = confirmed_entry_payload()
        del payload["caseId"]

        with self.assertRaisesRegex(AdapterValidationError, "caseId"):
            build_agentcore_invocation(payload)

    def test_rejects_payload_without_area_scope(self):
        payload = confirmed_entry_payload()
        del payload["intake"]["areaScope"]

        with self.assertRaisesRegex(AdapterValidationError, "areaScope"):
            build_agentcore_invocation(payload)

    def test_maps_confirmed_entry_payload_to_agentcore_invocation(self):
        invocation = build_agentcore_invocation(confirmed_entry_payload())

        agent_input = invocation["input"]
        self.assertEqual(agent_input["caseId"], "case_test_agentverse_001")
        self.assertEqual(agent_input["siteName"], "Lambeth Thames public fixture")
        self.assertEqual(agent_input["latitude"], 51.4908)
        self.assertEqual(agent_input["longitude"], -0.1216)
        self.assertEqual(agent_input["fixturePack"], "public-lambeth-thames")
        self.assertFalse(agent_input["useBedrock"])
        self.assertEqual(agent_input["upstream"]["source"], "AGENTVERSE")
        self.assertEqual(agent_input["upstream"]["caseId"], "case_test_agentverse_001")
        self.assertTrue(agent_input["upstream"]["confirmedByUser"])
        self.assertEqual(agent_input["upstream"]["materialCount"], 1)
        self.assertEqual(agent_input["upstream"]["reportAccess"]["mode"], "asi_session")
        self.assertEqual(agent_input["upstream"]["reportAccess"]["caseId"], "case_test_agentverse_001")
        self.assertEqual(agent_input["upstream"]["reportAccess"]["sessionId"], "agentverse-session-id")
        self.assertEqual(agent_input["upstream"]["reportAccess"]["authorizedCaseIds"], ["case_test_agentverse_001"])
        self.assertEqual(agent_input["materials"][0]["materialId"], "asio_material_site_access_plan")
        self.assertEqual(agent_input["materials"][0]["caseId"], "case_test_agentverse_001")
        self.assertNotIn("signedUrl", agent_input["materials"][0])
        self.assertNotIn("early feasibility walkover", agent_input["additionalRequest"])

    def test_maps_agentcore_response_to_entry_delivery_payload(self):
        entry_payload = confirmed_entry_payload()
        invocation = build_agentcore_invocation(entry_payload)
        agentcore_response = invoke_local(invocation)
        self.assertEqual(
            agentcore_response["output"]["run"]["upstream"]["conversationId"],
            "agentverse-session-id",
        )
        self.assertEqual(agentcore_response["output"]["caseId"], "case_test_agentverse_001")
        self.assertEqual(agentcore_response["output"]["run"]["caseId"], "case_test_agentverse_001")
        self.assertEqual(agentcore_response["output"]["structuredReport"]["caseId"], "case_test_agentverse_001")

        delivery = build_delivery_payload(agentcore_response, entry_payload=entry_payload)

        self.assertEqual(delivery["caseId"], "case_test_agentverse_001")
        self.assertEqual(delivery["conversationId"], "agentverse-session-id")
        self.assertEqual(delivery["caseUrl"], "/case/case_test_agentverse_001")
        self.assertEqual(delivery["status"], "review_passed")
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
        self.assertEqual(calls[0]["payload"]["input"]["caseId"], "case_test_agentverse_001")
        self.assertEqual(calls[0]["payload"]["input"]["upstream"]["reportAccess"]["mode"], "asi_session")
        output = response["output"]
        self.assertEqual(output["caseId"], "case_test_agentverse_001")
        self.assertEqual(output["reportStatus"], "review_passed")
        self.assertEqual(output["workflowMode"], "cached_public_fixture")
        self.assertEqual(output["entryAgent"]["mode"], "cloud-supervisor-handoff")
        self.assertEqual(output["entryAgent"]["caseId"], "case_test_agentverse_001")
        self.assertTrue(output["structuredReport"]["visualization"]["annotations"])
        self.assertEqual(output["run"]["materialIngestion"]["accepted"], 1)
        self.assertIsNone(output["run"]["runtime"].get("localAsiOneSubstitute"))
        self.assertIn("Cached public-source review pack", self.assert_user_readable_response(response))

    def test_entry_intake_clarifies_without_location(self):
        response = handle_invocation(
            {"entryTurn": True, "message": "Can you help me?", "conversationId": "c1"},
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=lambda **_: self.fail("supervisor should not be invoked"),
        )

        entry = response["output"]["entryAgent"]
        self.assertEqual(response["output"]["reportStatus"], "entry_pending")
        self.assertEqual(entry["status"], "clarification_required")
        self.assertTrue(entry["clarifyingQuestions"])
        self.assertIn("Which site", self.assert_user_readable_response(response))

    def test_entry_uses_llm_model_json_for_intake_when_available(self):
        def fake_model_json(prompt):
            self.assertEqual(prompt["turn"]["conversationId"], "model-case-test")
            return {
                "status": "confirmation_required",
                "assistantMessage": "I found the site, radius, and purpose. Please confirm launch.",
                "confirmation": {"summary": "Confirm Model Parsed Site for a 1200m inspection review."},
                "intake": {
                    "locationText": "Model Parsed Site",
                    "locationCandidate": {"label": "Model Parsed Site", "lat": 51.5, "lng": -0.12, "confidence": 0.91},
                    "areaScope": {"type": "radius", "meters": 1200},
                    "userGoal": "inspection pre-review",
                    "userNotes": "Parsed by fake model.",
                    "materials": [],
                },
            }

        response = handle_invocation(
            {
                "entryTurn": True,
                "caller": "agentverse",
                "message": "Please inspect the site by the river with the plan I uploaded.",
                "conversationId": "model-case-test",
                "runtimeOptions": {"fixturePack": "public-lambeth-thames", "useBedrock": True},
            },
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=lambda **_: self.fail("supervisor should not be invoked before confirmation"),
            model_json=fake_model_json,
        )

        entry = response["output"]["entryAgent"]
        self.assertEqual(entry["status"], "confirmation_required")
        self.assertEqual(entry["mode"], "llm-first-intake")
        self.assertEqual(entry["intakeMode"], "llm")
        self.assertEqual(entry["intake"]["locationText"], "Model Parsed Site")
        self.assertIn("Model Parsed Site", self.assert_user_readable_response(response))

    def test_entry_raw_message_confirmation_then_launch(self):
        calls: list[dict] = []

        def fake_invoke_runtime(**kwargs):
            calls.append(kwargs)
            return invoke_supervisor_local(kwargs["payload"])

        first = handle_invocation(
            {
                "entryTurn": True,
                "caller": "frontend",
                "message": "I want to visit 8 Albert Embankment tomorrow for a survey for 2km",
                "conversationId": "frontend-case-test",
                "runtimeOptions": {"fixturePack": "public-lambeth-thames", "useBedrock": False},
            },
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=fake_invoke_runtime,
        )
        self.assertEqual(first["output"]["entryAgent"]["status"], "confirmation_required")
        self.assertEqual(calls, [])

        second = handle_invocation(
            {
                "entryTurn": True,
                "caller": "frontend",
                "message": "Confirm and launch",
                "conversationId": "frontend-case-test",
                "confirmedByUser": True,
                "runtimeOptions": {"fixturePack": "public-lambeth-thames", "useBedrock": False},
            },
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=fake_invoke_runtime,
        )

        self.assertEqual(len(calls), 1)
        self.assertTrue(second["output"]["caseId"].startswith("case_"))
        self.assertEqual(calls[0]["payload"]["input"]["upstream"]["source"], "FRONTEND")
        self.assertEqual(second["output"]["structuredReport"]["caseId"], second["output"]["caseId"])

    def test_entry_cloud_handoff_requires_supervisor_runtime_arn(self):
        response = handle_invocation(confirmed_entry_payload(), supervisor_runtime_arn="", invoke_runtime=lambda **_: {})

        output = response["output"]
        self.assertEqual(output["reportStatus"], "blocked")
        self.assertIn("assistantMessage", output)
        self.assertEqual(output["entryAgent"]["status"], "blocked")
        self.assertIn("RAMS_SUPERVISOR_RUNTIME_ARN", output["runtime"]["fallbackReason"])
        self.assertIn("could not launch", self.assert_user_readable_response(response))

    def test_entry_invalid_model_output_returns_structured_fallback_response(self):
        response = handle_invocation(
            {"entryTurn": True, "message": "8 Albert Embankment for 2km", "conversationId": "bad-model"},
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=lambda **_: self.fail("supervisor should not be invoked"),
            model_json=lambda _: "not json",
        )

        output = response["output"]
        self.assertEqual(output["reportStatus"], "entry_pending")
        self.assertEqual(output["entryAgent"]["mode"], "deterministic-fallback-intake")
        self.assertEqual(output["entryAgent"]["status"], "clarification_required")
        self.assertEqual(output["entryAgent"]["fallbackReason"], "invalid_model_json")

    def test_entry_report_lookup_forwards_to_supervisor_runtime(self):
        calls: list[dict] = []

        def fake_invoke_runtime(**kwargs):
            calls.append(kwargs)
            return {
                "output": {
                    "caseId": "case_test_agentverse_001",
                    "reportStatus": "not_found",
                    "workflowMode": "report_lookup",
                    "persistence": {
                        "mode": "dynamodb",
                        "status": "not_found",
                        "caseId": "case_test_agentverse_001",
                    },
                }
            }

        response = handle_invocation(
            {
                "frontendInvoke": True,
                "operation": "getReport",
                "caseId": "case_test_agentverse_001",
                "conversationId": "agentverse-session-id",
                "caller": "frontend",
            },
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=fake_invoke_runtime,
        )

        self.assertEqual(len(calls), 1)
        lookup_input = calls[0]["payload"]["input"]
        self.assertEqual(lookup_input["operation"], "getReport")
        self.assertEqual(lookup_input["caseId"], "case_test_agentverse_001")
        self.assertEqual(lookup_input["reportAccess"]["mode"], "asi_session")
        self.assertEqual(lookup_input["reportAccess"]["caseId"], "case_test_agentverse_001")
        self.assertEqual(lookup_input["reportAccess"]["sessionId"], "agentverse-session-id")
        self.assertEqual(lookup_input["reportAccess"]["authorizedCaseIds"], ["case_test_agentverse_001"])
        self.assertEqual(lookup_input["upstream"]["caseId"], "case_test_agentverse_001")
        self.assertEqual(lookup_input["upstream"]["conversationId"], "agentverse-session-id")
        self.assertEqual(lookup_input["upstream"]["source"], "FRONTEND")
        self.assertEqual(response["output"]["caseId"], "case_test_agentverse_001")
        self.assertEqual(response["output"]["workflowMode"], "report_lookup")
        self.assertEqual(response["output"]["entryAgent"]["mode"], "cloud-report-lookup")

    def test_entry_accepts_json_envelope_inside_prompt_for_cli_smoke(self):
        calls: list[dict] = []

        def fake_invoke_runtime(**kwargs):
            calls.append(kwargs)
            return invoke_supervisor_local(kwargs["payload"])

        response = handle_invocation(
            {"prompt": json.dumps(confirmed_entry_payload())},
            supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/supervisor-test",
            invoke_runtime=fake_invoke_runtime,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(response["output"]["caseId"], "case_test_agentverse_001")


if __name__ == "__main__":
    unittest.main()
