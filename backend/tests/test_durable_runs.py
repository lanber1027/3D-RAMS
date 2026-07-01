import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402
from app.run_store import clear_all_runs_for_tests  # noqa: E402


class EnvPatch:
    def __init__(self, **updates):
        self.updates = updates
        self.previous = {}

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


class DurableRunApiTests(unittest.TestCase):
    def setUp(self):
        clear_all_runs_for_tests()
        self.client = TestClient(app)

    def _session(self):
        return self.client.post("/api/session/start", json={"testerAlias": "qa-v3"}).json()

    def _run(self, session_id, message, **overrides):
        payload = {
            "sessionId": session_id,
            "message": message,
            "useBedrock": False,
            "autoStart": True,
        }
        payload.update(overrides)
        return self.client.post("/api/runs", json=payload)

    def test_durable_run_completes_and_can_be_read_back(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
            )

        self.assertEqual(response.status_code, 202)
        created = response.json()
        self.assertEqual(created["status"], "completed")
        self.assertTrue(created["runId"].startswith("run-"))
        self.assertEqual(created["finalUiState"]["safety"]["level"], "review_required")
        self.assertGreaterEqual(len(created["steps"]), 5)
        self.assertGreaterEqual(len(created["toolResults"]), 5)
        self.assertEqual(created["modelCallsUsed"], 0)
        self.assertEqual(created["result"]["evaluationStopReason"], "passed")
        self.assertTrue(created["result"]["evaluation"]["passed"])
        self.assertEqual(created["runtime"]["evaluationLoopCount"], 1)

        read_back = self.client.get(f"/api/runs/{created['runId']}")
        self.assertEqual(read_back.status_code, 200)
        self.assertEqual(read_back.json()["runId"], created["runId"])
        self.assertEqual(read_back.json()["status"], "completed")

    def test_durable_run_waits_for_clarification_without_site_signal(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(session["sessionId"], "Please prepare my pre-visit pack.")

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "waiting_for_clarification")
        self.assertTrue(result["result"]["needsClarification"])
        self.assertGreaterEqual(len(result["result"]["clarifyingQuestions"]), 1)
        self.assertEqual(result["modelCallsUsed"], 0)

    def test_durable_run_enters_location_resolution_for_unknown_named_site_without_coordinate(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit Bilsbrae Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "waiting_for_location_confirmation")
        self.assertTrue(result["result"]["needsClarification"])
        self.assertFalse(result["result"]["needsLocationConfirmation"])
        self.assertEqual(result["result"]["nextStage"], "provide_location_detail")
        self.assertEqual(result["result"]["locationCandidates"], [])
        self.assertIn("Bilsbrae Solar Farm", result["result"]["assistantMessage"])
        self.assertIsNone(result["result"]["scene"])
        self.assertEqual(result["result"]["evidence"], [])
        parse_step = next(step for step in result["result"]["trace"] if step["name"] == "chat_parse_user_request")
        self.assertEqual(parse_step["output"]["siteResolution"], "unresolved")
        self.assertIsNone(parse_step["output"]["fixturePackSelected"])
        resolver_step = next(step for step in result["result"]["trace"] if step["name"] == "resolve_location_candidates")
        self.assertEqual(resolver_step["status"], "warning")
        self.assertEqual(resolver_step["output"]["candidateCount"], 0)

    def test_durable_run_name_only_returns_provisional_checklist_without_review_tools(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit Foxglove Farm Solar Site near Hexham tomorrow for a PV module inspection and access track survey. Please prepare a pre-visit RAMS-style review pack.",
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "waiting_for_location_confirmation")
        self.assertEqual(result["modelCallsUsed"], 0)
        self.assertIsNone(result["result"]["scene"])
        self.assertEqual(result["result"]["evidence"], [])
        self.assertEqual(result["result"]["uiState"]["reviewMode"], "provisional checklist pending location")
        hazards = result["result"]["uiState"]["hazards"]
        self.assertTrue(any(hazard["title"] == "PV electrical isolation and inverter interface" for hazard in hazards))
        self.assertIn("near Hexham", " ".join(result["result"]["clarifyingQuestions"]))

    def test_durable_run_coordinate_site_profiles_are_activity_specific(self):
        solar_response = Mock()
        solar_response.raise_for_status.return_value = None
        solar_response.json.return_value = {
            "status": 200,
            "result": [
                {
                    "postcode": "NE46 1AA",
                    "outcode": "NE46",
                    "latitude": 54.9712,
                    "longitude": -2.1010,
                    "admin_district": "Northumberland",
                    "admin_ward": "Hexham",
                    "region": "North East",
                    "country": "England",
                }
            ],
        }
        quarry_response = Mock()
        quarry_response.raise_for_status.return_value = None
        quarry_response.json.return_value = {
            "status": 200,
            "result": [
                {
                    "postcode": "SK23 0AA",
                    "outcode": "SK23",
                    "latitude": 53.36,
                    "longitude": -1.93,
                    "admin_district": "High Peak",
                    "admin_ward": "Hope Valley",
                    "region": "East Midlands",
                    "country": "England",
                }
            ],
        }
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.location_resolver.httpx.get",
            side_effect=[solar_response, quarry_response],
        ):
            session = self._session()
            solar_created = self._run(
                session["sessionId"],
                "I want to visit Foxglove Farm Solar Site at 54.9712, -2.1010 tomorrow for a PV module inspection and access track survey.",
            ).json()
            quarry_created = self._run(
                session["sessionId"],
                "I want to visit Moor Edge Quarry at 53.3600, -1.9300 tomorrow for a drainage and slope inspection.",
            ).json()
            solar = self.client.post(
                f"/api/runs/{solar_created['runId']}/confirm-location",
                json={"candidateId": solar_created["result"]["locationCandidates"][0]["candidateId"]},
            ).json()
            quarry = self.client.post(
                f"/api/runs/{quarry_created['runId']}/confirm-location",
                json={"candidateId": quarry_created["result"]["locationCandidates"][0]["candidateId"]},
            ).json()

        self.assertEqual(solar_created["status"], "waiting_for_location_confirmation")
        self.assertEqual(quarry_created["status"], "waiting_for_location_confirmation")
        self.assertEqual(solar_created["result"]["evidence"], [])
        self.assertEqual(quarry_created["result"]["evidence"], [])
        self.assertEqual(solar_created["result"]["locationCandidates"][0]["source"], "user-supplied-coordinate")
        self.assertEqual(quarry_created["result"]["locationCandidates"][0]["source"], "user-supplied-coordinate")
        self.assertEqual(solar["status"], "completed")
        self.assertEqual(quarry["status"], "completed")
        self.assertEqual(solar["result"]["uiState"]["location"]["label"], "Foxglove Farm Solar Site")
        self.assertEqual(quarry["result"]["uiState"]["location"]["label"], "Moor Edge Quarry")
        self.assertEqual(solar["result"]["uiState"]["location"]["authority"], "Northumberland")
        self.assertEqual(quarry["result"]["uiState"]["location"]["authority"], "High Peak")
        solar_titles = {hazard["title"] for hazard in solar["result"]["uiState"]["hazards"]}
        quarry_titles = {hazard["title"] for hazard in quarry["result"]["uiState"]["hazards"]}
        self.assertEqual(solar["result"]["uiState"]["hazards"][0]["title"], "PV electrical isolation and inverter boundary")
        self.assertEqual(quarry["result"]["uiState"]["hazards"][0]["title"], "Excavation edge and unstable ground")
        self.assertIn("PV electrical isolation and inverter boundary", solar_titles)
        self.assertIn("Excavation edge and unstable ground", quarry_titles)
        self.assertNotEqual(solar_titles, quarry_titles)

    def test_durable_run_standalone_unsafe_request_blocks_before_location_parse(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(session["sessionId"], "Please certify RAMS and approve work today.")

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["currentStep"], "safety_gate")
        self.assertEqual(result["modelCallsUsed"], 0)
        self.assertEqual(result["safetyResult"]["level"], "blocked")
        self.assertFalse(result["result"]["needsClarification"])

    def test_durable_run_confirms_cached_location_candidate_before_review_workflow(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit Greenacre Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
            )
            created = response.json()
            confirm = self.client.post(
                f"/api/runs/{created['runId']}/confirm-location",
                json={"candidateId": "candidate-greenacre-solar-demo"},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(created["status"], "waiting_for_location_confirmation")
        self.assertTrue(created["result"]["needsLocationConfirmation"])
        self.assertEqual(created["result"]["nextStage"], "confirm_location")
        self.assertEqual(len(created["result"]["locationCandidates"]), 1)
        self.assertEqual(created["result"]["evidence"], [])
        self.assertEqual(created["toolResults"], [])
        self.assertNotIn("evaluationStopReason", created["result"])

        self.assertEqual(confirm.status_code, 202)
        result = confirm.json()
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["result"]["needsClarification"])
        self.assertEqual(result["result"]["uiState"]["location"]["label"], "Greenacre Solar Farm")
        self.assertIsNone(result["result"]["runtime"]["fixturePack"])
        self.assertEqual(result["result"]["runtime"]["fixturePackMode"], "synthetic-default")
        self.assertNotIn("8 Albert Embankment", result["result"]["assistantMessage"])

    def test_durable_run_geoapify_candidate_requires_confirmation_before_tools(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "place_id": "foxglove-demo-place",
                        "formatted": "Foxglove Farm Solar Site, Hexham, Northumberland, UK",
                        "city": "Hexham",
                        "county": "Northumberland",
                        "postcode": "NE46",
                        "lat": 54.9712,
                        "lon": -2.101,
                        "rank": {"confidence": 0.83},
                    },
                    "geometry": {"type": "Point", "coordinates": [-2.101, 54.9712]},
                }
            ],
        }
        with EnvPatch(
            ENABLE_BEDROCK="false",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
            ENABLE_GEOAPIFY_GEOCODING="true",
            GEOAPIFY_API_KEY="test-key",
        ), patch("app.geoapify_resolver.httpx.get", return_value=fake_response):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit Foxglove Farm Solar Site near Hexham tomorrow for a PV module inspection.",
            )
            created = response.json()
            confirm = self.client.post(
                f"/api/runs/{created['runId']}/confirm-location",
                json={"candidateId": created["result"]["locationCandidates"][0]["candidateId"]},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(created["status"], "waiting_for_location_confirmation")
        self.assertEqual(created["modelCallsUsed"], 0)
        self.assertTrue(created["result"]["needsLocationConfirmation"])
        self.assertEqual(created["result"]["locationCandidates"][0]["source"], "geoapify/geocode/search")
        self.assertEqual(created["result"]["evidence"], [])
        self.assertEqual(confirm.status_code, 202)
        result = confirm.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["uiState"]["location"]["label"], "Foxglove Farm Solar Site, Hexham, Northumberland, UK")
        self.assertNotIn("8 Albert Embankment", result["result"]["assistantMessage"])

    def test_durable_run_safety_blocks_certified_rams_request(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow. Please certify RAMS and approve work today.",
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["safetyResult"]["level"], "blocked")
        self.assertFalse(result["finalUiState"]["safety"]["allowed"])
        self.assertEqual(result["result"]["annotations"], [])

    def test_durable_run_can_be_cancelled_before_worker_starts(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey.",
                autoStart=False,
            )
            run_id = response.json()["runId"]
            cancel = self.client.post(f"/api/runs/{run_id}/cancel")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(cancel.status_code, 200)
        result = cancel.json()
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(result["cancelRequested"])
        self.assertEqual(result["modelCallsUsed"], 0)

    def test_invalid_model_tool_request_falls_back_to_default_tool_sequence(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
            BEDROCK_MOCK_PLANNER_SCENARIO="invalid-tool",
            BEDROCK_MAX_MODEL_CALLS="2",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
        ):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey.",
                useBedrock=True,
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertIn("disallowed tool", result["fallbackReason"].lower())
        self.assertGreaterEqual(len(result["toolResults"]), 5)
        self.assertEqual(result["modelCallsUsed"], 2)

    def test_bad_order_allowlisted_model_tools_fall_back_to_default_sequence(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
            BEDROCK_MOCK_PLANNER_SCENARIO="bad-order",
            BEDROCK_MAX_MODEL_CALLS="2",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
        ):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey.",
                useBedrock=True,
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertIn("missing prior dependency", result["fallbackReason"])
        self.assertGreaterEqual(len(result["toolResults"]), 5)

    def test_three_call_mock_budget_records_planner_reasoner_and_compiler(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
            BEDROCK_MOCK_PLANNER_SCENARIO="v2-valid",
            BEDROCK_MAX_MODEL_CALLS="3",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
        ):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey.",
                useBedrock=True,
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["modelCallsUsed"], 3)
        model_call_names = [step["name"] for step in result["steps"] if step["name"].endswith("_model_call")]
        self.assertIn("planner_model_call", model_call_names)
        self.assertIn("reasoner_model_call", model_call_names)
        self.assertIn("compiler_model_call", model_call_names)
        self.assertEqual(result["runtime"]["phaseTokenBudgets"]["planner"], 900)
        self.assertEqual(result["runtime"]["phaseTokenBudgets"]["reasoner"], 1500)
        self.assertEqual(result["runtime"]["phaseTokenBudgets"]["compiler"], 2200)

    def test_poor_grounding_triggers_compile_retry_and_passes_after_loop(self):
        from app import durable_runner
        from app.tools import trace_step

        original_execute_tool = durable_runner.execute_tool
        compile_calls = {"count": 0}

        def patched_execute_tool(tool_name, context):
            if tool_name == "compile_review_pack":
                compile_calls["count"] += 1
                if compile_calls["count"] == 1:
                    briefing = {
                        "site": context["location"]["label"],
                        "headline": "Ungrounded draft review pack.",
                        "summary": ["This draft intentionally lacks evidence for retry testing."],
                        "priority_checks": ["Unsupported invented site hazard"],
                        "before_site_visit": ["Review current sources."],
                        "limitations": ["Human review is required."],
                    }
                    context["briefing"] = briefing
                    context["evidence"] = []
                    return {
                        "briefing": briefing,
                        "evidence": [],
                        "trace": trace_step(
                            "generate_site_brief",
                            "warning",
                            "Test double returned an intentionally weak briefing.",
                            {"mode": "test-weak-grounding", "evidence_count": 0},
                        ),
                    }
            return original_execute_tool(tool_name, context)

        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.durable_runner.execute_tool",
            side_effect=patched_execute_tool,
        ):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey.",
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(compile_calls["count"], 2)
        self.assertEqual(result["result"]["evaluationStopReason"], "passed_after_retry")
        self.assertTrue(result["result"]["evaluation"]["passed"])
        self.assertEqual(result["runtime"]["evaluationLoopCount"], 2)
        self.assertTrue(any(step["name"] == "output_improvement_loop" for step in result["steps"]))

    def test_persistent_poor_grounding_stops_at_max_evaluation_loops(self):
        from app import durable_runner
        from app.tools import trace_step

        original_execute_tool = durable_runner.execute_tool
        compile_calls = {"count": 0}

        def patched_execute_tool(tool_name, context):
            if tool_name == "compile_review_pack":
                compile_calls["count"] += 1
                briefing = {
                    "site": context["location"]["label"],
                    "headline": "Persistently ungrounded draft review pack.",
                    "summary": ["This draft intentionally lacks evidence for max-loop testing."],
                    "priority_checks": ["Unsupported invented site hazard"],
                    "before_site_visit": ["Review current sources."],
                    "limitations": ["Human review is required."],
                }
                context["briefing"] = briefing
                context["evidence"] = []
                return {
                    "briefing": briefing,
                    "evidence": [],
                    "trace": trace_step(
                        "generate_site_brief",
                        "warning",
                        "Test double returned a persistently weak briefing.",
                        {"mode": "test-persistent-weak-grounding", "evidence_count": 0},
                    ),
                }
            return original_execute_tool(tool_name, context)

        with EnvPatch(
            ENABLE_BEDROCK="false",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
            DURABLE_RUN_MAX_TOOL_CALLS="20",
        ), patch(
            "app.durable_runner.execute_tool",
            side_effect=patched_execute_tool,
        ):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey.",
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(compile_calls["count"], 3)
        self.assertEqual(result["result"]["evaluationStopReason"], "max_evaluation_loops")
        self.assertFalse(result["result"]["evaluation"]["passed"])
        self.assertEqual(result["runtime"]["evaluationLoopCount"], 3)
        self.assertEqual(result["result"]["briefing"]["generation_mode"], "deterministic-safer-fallback")
        self.assertNotIn("Unsupported invented site hazard", result["result"]["briefing"]["priority_checks"])

    def test_durable_run_timeout_is_enforced(self):
        from app.durable_runner import _RunTimedOut

        with EnvPatch(
            ENABLE_BEDROCK="false",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
            DURABLE_RUN_TIMEOUT_SECONDS="5",
        ):
            session = self._session()
            with patch("app.durable_runner._raise_if_stopped", side_effect=[None, _RunTimedOut("Durable run exceeded configured runtime timeout.")]):
                response = self._run(
                    session["sessionId"],
                    "I want to visit 8 Albert Embankment tomorrow for a survey.",
                )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errorSummary"]["type"], "_RunTimedOut")
        self.assertIn("timeout", result["errorSummary"]["message"].lower())

    def test_max_tool_call_cap_fails_with_checkpoint(self):
        with EnvPatch(
            ENABLE_BEDROCK="false",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
            DURABLE_RUN_MAX_TOOL_CALLS="2",
        ):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I want to visit 8 Albert Embankment tomorrow for a survey.",
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["currentStep"], "failed")
        self.assertIn("Maximum tool-call count", result["errorSummary"]["message"])

    def test_missing_memory_run_returns_404_after_restart_like_loss(self):
        response = self.client.get("/api/runs/run-does-not-exist")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
