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

    def test_vague_place_request_enters_location_needed_without_fake_site_name(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I need to do a site visit near a park in Brighton, can you help me find it",
            )

        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "waiting_for_location_confirmation")
        self.assertTrue(result["result"]["needsClarification"])
        self.assertFalse(result["result"]["needsLocationConfirmation"])
        self.assertEqual(result["result"]["nextStage"], "provide_location_detail")
        self.assertEqual(result["result"]["locationCandidates"], [])
        location_resolution = result["result"]["uiState"]["locationResolution"]
        self.assertEqual(location_resolution["siteName"], "park near Brighton")
        self.assertEqual(location_resolution["intent"]["placeHint"], "park")
        self.assertEqual(location_resolution["intent"]["areaHint"], "Brighton")
        self.assertNotIn("can you help me find it", location_resolution["siteName"])
        self.assertIsNone(result["result"]["scene"])
        self.assertEqual(result["result"]["evidence"], [])
        parse_step = next(step for step in result["result"]["trace"] if step["name"] == "chat_parse_user_request")
        self.assertTrue(parse_step["output"]["vagueLocationHint"])
        self.assertEqual(parse_step["output"]["siteResolution"], "unresolved")

    def test_vague_place_request_skips_geoapify_even_when_enabled(self):
        with EnvPatch(
            ENABLE_BEDROCK="false",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
            ENABLE_GEOAPIFY_GEOCODING="true",
            GEOAPIFY_API_KEY="test-key",
        ), patch("app.geoapify_resolver.httpx.get") as geoapify_get:
            session = self._session()
            response = self._run(
                session["sessionId"],
                "I need to do a site visit near a park in Brighton, can you help me find it",
            )

        geoapify_get.assert_not_called()
        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "waiting_for_location_confirmation")
        self.assertFalse(result["result"]["needsLocationConfirmation"])
        self.assertEqual(result["result"]["nextStage"], "provide_location_detail")
        self.assertEqual(result["result"]["locationCandidates"], [])
        resolver_step = next(step for step in result["result"]["trace"] if step["name"] == "resolve_location_candidates")
        self.assertEqual(resolver_step["output"]["geoapifyLookup"]["status"], "skipped")
        self.assertEqual(result["result"]["uiState"]["locationResolution"]["siteName"], "park near Brighton")

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

    def test_conversation_follow_up_uses_session_memory_not_new_site_run(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
                    "useBedrock": False,
                },
            ).json()
            follow_up = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "What do you mean",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(first["action"], "started_run")
        self.assertEqual(first["run"]["status"], "waiting_for_location_confirmation")
        self.assertEqual(follow_up["action"], "answered_from_memory")
        self.assertEqual(follow_up["route"], "follow_up")
        self.assertNotIn("review pack for What do you mean", follow_up["assistantMessage"])
        self.assertIn("previous step", follow_up["assistantMessage"])
        self.assertEqual(len(session_state["runs"]), 1)
        self.assertEqual(session_state["runs"][0]["runId"], first["run"]["runId"])
        self.assertEqual(session_state["workingMemory"]["activeRunId"], first["run"]["runId"])
        self.assertEqual(session_state["workingMemory"]["pendingUserAction"], "confirm_or_correct_location")

    def test_conversation_greeting_does_not_become_fake_site_run_without_bedrock(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Hello",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "greeting")
        self.assertNotIn("review pack for Hello", response["assistantMessage"])
        self.assertEqual(session_state["runs"], [])
        self.assertIsNone(session_state["workingMemory"]["activeRunId"])

    def test_conversation_greeting_uses_bedrock_orchestrator_without_starting_run(self):
        with EnvPatch(ENABLE_BEDROCK="true", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.conversation_router.generate_bedrock_conversation_orchestration",
            return_value=(
                {
                    "route": "greeting",
                    "assistantMessage": "Hi. Send a postcode or coordinate plus the visit activity.",
                    "shouldStartRun": False,
                    "pendingUserAction": "provide_site_location_and_activity",
                    "reason": "Greeting only.",
                },
                {"provider": "bedrock", "phase": "conversation-orchestrator", "modelCallCount": 1},
            ),
        ) as orchestrator:
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Hello",
                    "useBedrock": True,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        orchestrator.assert_called_once()
        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "greeting")
        self.assertEqual(response["assistantMessage"], "Hi. Send a postcode or coordinate plus the visit activity.")
        self.assertEqual(response["conversationState"]["intent"], "conversation")
        self.assertEqual(response["conversationState"]["allowedNextAction"], "answer")
        self.assertFalse(response["conversationState"]["shouldStartRun"])
        self.assertEqual(session_state["runs"], [])
        self.assertEqual(session_state["workingMemory"]["pendingUserAction"], "provide_site_location_and_activity")

    def test_conversation_ignores_unknown_bedrock_pending_action_code(self):
        with EnvPatch(ENABLE_BEDROCK="true", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.conversation_router.generate_bedrock_conversation_orchestration",
            return_value=(
                {
                    "route": "conversation",
                    "assistantMessage": "I am waiting for: provide_information.",
                    "shouldStartRun": False,
                    "pendingUserAction": "provide_information",
                    "reason": "Generic information request.",
                },
                {"provider": "bedrock", "phase": "conversation-orchestrator", "modelCallCount": 1},
            ),
        ):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I'm not feeling well",
                    "useBedrock": True,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "conversation")
        self.assertEqual(session_state["runs"], [])
        self.assertIsNone(session_state["workingMemory"]["pendingUserAction"])
        self.assertNotIn("provide_information", response["assistantMessage"])
        self.assertIn("site-visit preparation", response["assistantMessage"])

    def test_conversation_does_not_promise_tool_work_without_trusted_location(self):
        model_promises = [
            "I can help with your visit to a park in Brighton. Let me gather some information about this location.",
            "I’m going to fetch the local context for this location.",
            "I can gather the relevant site information now.",
            "I am checking available evidence for this site.",
        ]
        for model_promise in model_promises:
            with self.subTest(model_promise=model_promise), EnvPatch(
                ENABLE_BEDROCK="true",
                APP_ACCESS_TOKEN_HASH=None,
                DURABLE_RUN_PROCESS_INLINE="true",
            ), patch(
                "app.conversation_router.generate_bedrock_conversation_orchestration",
                return_value=(
                    {
                        "route": "conversation",
                        "assistantMessage": model_promise,
                        "shouldStartRun": False,
                        "pendingUserAction": "provide_location_detail",
                        "reason": "Needs trusted location evidence.",
                    },
                    {"provider": "bedrock", "phase": "conversation-orchestrator", "modelCallCount": 1},
                ),
            ):
                session = self._session()
                response = self.client.post(
                    "/api/conversation/message",
                    json={
                        "sessionId": session["sessionId"],
                        "message": "There is a park close to where I live in Brighton, I need to visit there",
                        "useBedrock": True,
                    },
                ).json()
                session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

            self.assertEqual(response["action"], "answered_from_memory")
            self.assertEqual(response["route"], "conversation")
            self.assertEqual(session_state["runs"], [])
            self.assertNotIn("gather", response["assistantMessage"].lower())
            self.assertNotIn("fetch", response["assistantMessage"].lower())
            self.assertNotIn("checking", response["assistantMessage"].lower())
            self.assertIn("have not started map, evidence, risk, or briefing tools", response["assistantMessage"])
            self.assertFalse(response["observability"]["toolsStarted"])
            self.assertEqual(response["observability"]["phase"], "waiting_for_user")
            self.assertIn("toolsStarted", response["trace"][0]["output"])
            self.assertEqual(response["modelCalls"][0]["phase"], "conversation-orchestrator")

    def test_status_response_includes_observability_when_no_run_exists(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "status",
                    "useBedrock": False,
                },
            ).json()

        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "status")
        self.assertFalse(response["observability"]["toolsStarted"])
        self.assertIn("No tools started", response["observability"]["noToolReason"])
        self.assertEqual(response["trace"][0]["output"]["route"], "status")

    def test_conversation_stale_unknown_pending_action_is_removed_from_llm_context(self):
        from app.config import RuntimeConfig
        from app.session_store import llm_session_context, update_working_memory

        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
        ):
            session = self._session()
            update_working_memory(session["sessionId"], RuntimeConfig.from_env(request_bedrock=False), pendingUserAction="provide_information")
            session_state_before = self.client.get(f"/api/session/{session['sessionId']}").json()
            context = llm_session_context(session_state_before)
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "What do you mean",
                    "useBedrock": True,
                },
            ).json()

        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "follow_up")
        self.assertIsNone(context["workingMemory"]["pendingUserAction"])
        self.assertNotIn("provide_information", response["assistantMessage"])

    def test_conversation_stale_latest_assistant_message_is_sanitized_in_follow_up(self):
        from app.config import RuntimeConfig
        from app.session_store import update_working_memory

        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            update_working_memory(
                session["sessionId"],
                RuntimeConfig.from_env(request_bedrock=False),
                latestAssistantMessage="I am waiting for: provide_information.",
            )
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "What do you mean",
                    "useBedrock": False,
                },
            ).json()

        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "follow_up")
        self.assertNotIn("provide_information", response["assistantMessage"])
        self.assertIn("site-visit preparation", response["assistantMessage"])

    def test_conversation_site_request_uses_bedrock_orchestrator_then_starts_guarded_run(self):
        with EnvPatch(ENABLE_BEDROCK="true", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.conversation_router.generate_bedrock_conversation_orchestration",
            return_value=(
                {
                    "route": "new_run",
                    "assistantMessage": "I will pass this into the guarded run.",
                    "shouldStartRun": True,
                    "pendingUserAction": None,
                    "reason": "Site-review request detected.",
                },
                {"provider": "bedrock", "phase": "conversation-orchestrator", "modelCallCount": 1},
            ),
        ) as orchestrator:
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": True,
                },
            ).json()

        orchestrator.assert_called_once()
        self.assertEqual(response["action"], "started_run")
        self.assertEqual(response["route"], "new_or_guarded_run")
        self.assertEqual(response["run"]["status"], "waiting_for_location_confirmation")

    def test_conversation_site_signal_overrides_bedrock_conversation_misroute(self):
        with EnvPatch(ENABLE_BEDROCK="true", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.conversation_router.generate_bedrock_conversation_orchestration",
            return_value=(
                {
                    "route": "conversation",
                    "assistantMessage": "This looks like general conversation.",
                    "shouldStartRun": False,
                    "pendingUserAction": None,
                    "reason": "Intent classifier mistake.",
                },
                {"provider": "bedrock", "phase": "conversation-orchestrator", "modelCallCount": 1},
            ),
        ):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": True,
                },
            ).json()

        self.assertEqual(response["action"], "started_run")
        self.assertEqual(response["route"], "new_or_guarded_run")
        self.assertEqual(response["run"]["status"], "waiting_for_location_confirmation")
        self.assertNotEqual(response["assistantMessage"], "This looks like general conversation.")

    def test_conversation_unsafe_bedrock_block_does_not_create_run(self):
        with EnvPatch(ENABLE_BEDROCK="true", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.conversation_router.generate_bedrock_conversation_orchestration",
            return_value=(
                {
                    "route": "conversation",
                    "assistantMessage": "I cannot certify RAMS or approve work. I can only provide a human-review pack.",
                    "shouldStartRun": False,
                    "pendingUserAction": "provide_safe_site_visit_request",
                    "reason": "Unsafe request.",
                },
                {"provider": "bedrock", "phase": "conversation-orchestrator", "modelCallCount": 1},
            ),
        ):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Please certify RAMS and approve work today.",
                    "useBedrock": True,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "conversation")
        self.assertIn("cannot certify RAMS", response["assistantMessage"])
        self.assertEqual(session_state["runs"], [])

    def test_unsafe_conversation_does_not_mix_refusal_with_tool_promise(self):
        with EnvPatch(ENABLE_BEDROCK="true", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.conversation_router.generate_bedrock_conversation_orchestration",
            return_value=(
                {
                    "route": "conversation",
                    "assistantMessage": "I cannot certify RAMS, but I can gather and check the site context for you.",
                    "shouldStartRun": False,
                    "pendingUserAction": "provide_safe_site_visit_request",
                    "reason": "Unsafe request.",
                },
                {"provider": "bedrock", "phase": "conversation-orchestrator", "modelCallCount": 1},
            ),
        ):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Please certify RAMS and approve work today.",
                    "useBedrock": True,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(response["action"], "answered_from_memory")
        self.assertEqual(response["route"], "conversation")
        self.assertEqual(session_state["runs"], [])
        self.assertIn("cannot certify RAMS", response["assistantMessage"])
        self.assertIn("have not started map, evidence, risk, or briefing tools", response["assistantMessage"])
        self.assertNotIn("can gather", response["assistantMessage"].lower())
        self.assertNotIn("check the site context", response["assistantMessage"].lower())
        self.assertFalse(response["observability"]["toolsStarted"])

    def test_conversation_bedrock_orchestrator_failure_falls_back_to_guarded_run(self):
        with EnvPatch(ENABLE_BEDROCK="true", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.conversation_router.generate_bedrock_conversation_orchestration",
            side_effect=RuntimeError("no credentials"),
        ):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": True,
                },
            ).json()

        self.assertEqual(response["action"], "started_run")
        self.assertEqual(response["route"], "new_or_guarded_run")
        self.assertEqual(response["run"]["status"], "waiting_for_location_confirmation")

    def test_conversation_started_run_handles_queued_result_none(self):
        queued_run = {
            "runId": "run-queued-test",
            "sessionId": "session-placeholder",
            "status": "queued",
            "currentStep": "queued",
            "result": None,
        }
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="false"), patch(
            "app.conversation_router.create_durable_run",
            return_value=queued_run,
        ):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["action"], "started_run")
        self.assertEqual(result["run"]["status"], "queued")
        self.assertIn("queued", result["assistantMessage"])

    def test_conversation_rejects_candidate_without_starting_fake_run(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            ).json()
            rejection = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Nope",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(first["run"]["status"], "waiting_for_location_confirmation")
        self.assertEqual(rejection["action"], "answered_from_memory")
        self.assertEqual(rejection["route"], "reject_location")
        self.assertNotIn("review pack for Nope", rejection["assistantMessage"])
        self.assertIn("will not run", rejection["assistantMessage"])
        self.assertEqual(len(session_state["runs"]), 1)
        self.assertEqual(session_state["workingMemory"]["pendingUserAction"], "provide_corrected_location")
        self.assertEqual(session_state["workingMemory"]["rejectedRunId"], first["run"]["runId"])

    def test_conversation_chat_confirm_guides_to_confirm_button(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            ).json()
            confirm = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "yes",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(first["run"]["status"], "waiting_for_location_confirmation")
        self.assertEqual(confirm["action"], "answered_from_memory")
        self.assertEqual(confirm["route"], "confirm_by_chat")
        self.assertIn("Confirm this site", confirm["assistantMessage"])
        self.assertEqual(len(session_state["runs"]), 1)
        self.assertEqual(session_state["workingMemory"]["pendingUserAction"], "confirm_or_correct_location")

    def test_conversation_corrected_coordinate_starts_new_gated_run(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            ).json()
            correction = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Actually use 50.825351, -0.125125 for the survey site.",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(correction["action"], "started_run")
        self.assertEqual(correction["route"], "location_correction")
        self.assertEqual(correction["run"]["status"], "waiting_for_location_confirmation")
        self.assertNotEqual(first["run"]["runId"], correction["run"]["runId"])
        self.assertEqual(len(session_state["runs"]), 2)
        self.assertEqual(session_state["workingMemory"]["previousRunId"], first["run"]["runId"])
        self.assertEqual(session_state["workingMemory"]["activeRunId"], correction["run"]["runId"])
        self.assertEqual(session_state["workingMemory"]["pendingUserAction"], "confirm_or_correct_location")

    def test_conversation_bare_coordinate_while_pending_is_location_correction(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            ).json()
            correction = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "50.825351, -0.125125",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(correction["route"], "location_correction")
        self.assertEqual(correction["run"]["status"], "waiting_for_location_confirmation")
        self.assertEqual(session_state["workingMemory"]["previousRunId"], first["run"]["runId"])
        self.assertEqual(session_state["workingMemory"]["activeRunId"], correction["run"]["runId"])

    def test_conversation_bare_postcode_while_pending_is_location_correction(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "status": 200,
            "result": {
                "postcode": "BN2 9SB",
                "outcode": "BN2",
                "latitude": 50.825351,
                "longitude": -0.125125,
                "admin_district": "Brighton and Hove",
                "admin_county": None,
                "admin_ward": "Queen's Park",
                "parish": None,
                "region": "South East",
                "country": "England",
            },
        }
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"), patch(
            "app.location_resolver.httpx.get",
            return_value=fake_response,
        ):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            ).json()
            correction = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "BN2 9SB",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(correction["route"], "location_correction")
        self.assertEqual(correction["run"]["status"], "waiting_for_location_confirmation")
        parse_trace = next(
            trace
            for trace in correction["run"]["partialUiState"]["trace"]
            if trace.get("name") == "chat_parse_user_request"
        )
        self.assertTrue(parse_trace["output"]["clarificationRequired"])
        self.assertEqual(parse_trace["output"]["siteResolution"], "postcode-confirmation")
        self.assertEqual(session_state["workingMemory"]["previousRunId"], first["run"]["runId"])
        self.assertEqual(session_state["workingMemory"]["activeRunId"], correction["run"]["runId"])

    def test_conversation_reject_then_corrected_coordinate_starts_new_gated_run(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            ).json()
            rejected = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Not this site",
                    "useBedrock": False,
                },
            ).json()
            correction = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "The corrected coordinate is 50.825351, -0.125125.",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(rejected["route"], "reject_location")
        self.assertEqual(correction["action"], "started_run")
        self.assertEqual(correction["route"], "location_correction")
        self.assertEqual(correction["run"]["status"], "waiting_for_location_confirmation")
        self.assertEqual(len(session_state["runs"]), 2)
        self.assertEqual(session_state["workingMemory"]["previousRunId"], first["run"]["runId"])
        self.assertEqual(session_state["workingMemory"]["activeRunId"], correction["run"]["runId"])

    def test_conversation_start_over_without_site_clears_active_run(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None, DURABLE_RUN_PROCESS_INLINE="true"):
            session = self._session()
            first = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Greenacre Solar Farm tomorrow for a survey.",
                    "useBedrock": False,
                },
            ).json()
            start_over = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Start again",
                    "useBedrock": False,
                },
            ).json()
            session_state = self.client.get(f"/api/session/{session['sessionId']}").json()

        self.assertEqual(start_over["action"], "answered_from_memory")
        self.assertEqual(start_over["route"], "start_over_without_site")
        self.assertIn("fresh site review", start_over["assistantMessage"])
        self.assertEqual(len(session_state["runs"]), 1)
        self.assertEqual(session_state["workingMemory"]["previousRunId"], first["run"]["runId"])
        self.assertIsNone(session_state["workingMemory"]["activeRunId"])
        self.assertEqual(session_state["workingMemory"]["pendingUserAction"], "provide_new_site_request")

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

    def test_conversation_durable_planner_receives_sanitized_session_context(self):
        from app.tool_registry import default_tool_sequence

        captured = {}

        def fake_tool_plan(*, config, request_summary, tool_schemas, session_context=None):
            captured["sessionContext"] = session_context
            return {
                "rationale": "Use the standard bounded review workflow.",
                "tool_calls": [{"name": name, "arguments": {}} for name in default_tool_sequence()],
            }, {
                "mode": "test",
                "phase": "planner-plan",
                "modelCallCount": 1,
            }

        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MAX_MODEL_CALLS="1",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
        ), patch("app.durable_runner.generate_bedrock_tool_plan", side_effect=fake_tool_plan):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit 8 Albert Embankment tomorrow for a survey.",
                    "useBedrock": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        context = captured["sessionContext"]
        self.assertEqual(context["contextType"], "bounded-session-summary")
        self.assertIn("access codes", context["privacyBoundary"])
        self.assertEqual(context["recentTurns"][-1]["role"], "user")
        self.assertEqual(context["recentTurns"][-1]["summary"]["siteName"], "8 Albert Embankment")
        self.assertEqual(context["recentTurns"][-1]["route"], "user_input")
        serialized = str(context)
        self.assertNotIn("I want to visit", serialized)
        self.assertNotIn(session["sessionId"], serialized)
        self.assertNotIn("run-", serialized)
        self.assertNotIn("accessCode", serialized)

    def test_all_bedrock_phases_receive_bounded_session_context(self):
        from app.tool_registry import default_tool_sequence

        captured = {}

        def fake_tool_plan(*, config, request_summary, tool_schemas, session_context=None):
            captured["planner"] = session_context
            return {
                "rationale": "Use the standard bounded review workflow.",
                "tool_calls": [{"name": name, "arguments": {}} for name in default_tool_sequence()],
            }, {"mode": "test", "phase": "planner-plan", "modelCallCount": 1}

        def fake_reasoning(*, config, location, hazards, evidence, executed_tools, session_context=None):
            captured["reasoner"] = session_context
            return {
                "ranked_risks": [],
                "uncertainties": [],
                "approval_required": True,
            }, {"mode": "test", "phase": "risk-reasoner", "modelCallCount": 1}

        def fake_synthesis(*, config, location, hazards, deterministic_briefing, evidence, planning_available, executed_tools, session_context=None):
            captured["compiler"] = session_context
            briefing = dict(deterministic_briefing)
            briefing["generation_mode"] = "test-llm-context"
            return briefing, {"mode": "test", "phase": "planner-synthesis", "modelCallCount": 1}

        def fake_evaluator(*, config, deterministic_evaluation, location, hazards, evidence, briefing, executed_tools, session_context=None):
            captured["evaluator"] = session_context
            evaluation = dict(deterministic_evaluation)
            evaluation["passed"] = True
            evaluation["scores"] = {"grounding": 1.0, "relevance": 1.0, "completeness": 1.0, "safety": 1.0}
            evaluation["issues"] = []
            evaluation["retryTools"] = []
            return evaluation, {"mode": "test", "phase": "output-evaluator", "modelCallCount": 1}

        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MAX_MODEL_CALLS="4",
            APP_ACCESS_TOKEN_HASH=None,
            DURABLE_RUN_PROCESS_INLINE="true",
        ), patch("app.durable_runner.generate_bedrock_tool_plan", side_effect=fake_tool_plan), patch(
            "app.durable_runner.generate_bedrock_risk_reasoning", side_effect=fake_reasoning
        ), patch(
            "app.durable_runner.generate_bedrock_planner_synthesis", side_effect=fake_synthesis
        ), patch(
            "app.durable_runner.generate_bedrock_output_evaluation", side_effect=fake_evaluator
        ):
            session = self._session()
            response = self.client.post(
                "/api/conversation/message",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit 8 Albert Embankment tomorrow for a survey.",
                    "useBedrock": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(captured), {"planner", "reasoner", "compiler", "evaluator"})
        for context in captured.values():
            self.assertEqual(context["contextType"], "bounded-session-summary")
            self.assertEqual(context["recentTurns"][-1]["summary"]["siteName"], "8 Albert Embankment")
            self.assertNotIn(session["sessionId"], str(context))

    def test_llm_session_context_sanitizes_turns_and_working_memory(self):
        from app.config import RuntimeConfig
        from app.session_store import add_conversation_turn, create_session, llm_session_context, update_working_memory

        with EnvPatch(APP_ACCESS_TOKEN_HASH=None):
            config = RuntimeConfig.from_env(request_bedrock=False)
            session = create_session(tester_alias="qa-memory", access_label="team-test", config=config)
            add_conversation_turn(
                session["sessionId"],
                role="user",
                text="I want to visit 50.825351, -0.125125 tomorrow. access code is 3drams-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa. https://example.invalid/private.pdf",
                metadata={"routeInput": True, "accessCode": "should-not-appear", "uploadUrl": "https://example.invalid/upload"},
                config=config,
            )
            add_conversation_turn(
                session["sessionId"],
                role="assistant",
                text="Confirm this site before tools run.",
                metadata={"route": "follow_up", "runId": "run-private"},
                config=config,
            )
            update_working_memory(
                session["sessionId"],
                config,
                pendingUserAction="confirm_or_correct_location",
                activeRunId="run-private",
                confirmedLocation={
                    "name": "Coordinate 50.825351, -0.125125",
                    "latitude": 50.825351,
                    "longitude": -0.125125,
                    "source": "user-supplied-coordinate",
                    "confidence": "medium",
                },
            )
            context = llm_session_context(session)

        self.assertEqual(context["workingMemory"]["pendingUserAction"], "confirm_or_correct_location")
        self.assertEqual(context["workingMemory"]["confirmedLocation"]["name"], "Coordinate 50.825351, -0.125125")
        self.assertEqual(len(context["recentTurns"]), 2)
        self.assertNotIn("text", context["recentTurns"][0])
        self.assertTrue(context["recentTurns"][0]["summary"]["hasCoordinate"])
        serialized = str(context)
        self.assertNotIn("should-not-appear", serialized)
        self.assertNotIn("3drams-", serialized)
        self.assertNotIn("example.invalid", serialized)
        self.assertNotIn("uploadUrl", serialized)
        self.assertNotIn("run-private", serialized)
        self.assertNotIn(session["sessionId"], serialized)

    def test_llm_session_context_omits_sensitive_parser_derived_labels(self):
        from app.config import RuntimeConfig
        from app.session_store import add_conversation_turn, create_session, llm_session_context, update_working_memory

        with EnvPatch(APP_ACCESS_TOKEN_HASH=None):
            config = RuntimeConfig.from_env(request_bedrock=False)
            session = create_session(tester_alias="qa-memory", access_label="team-test", config=config)
            sensitive_prompts = [
                "Please visit access code is 3drams-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa for survey.",
                "Please visit https://example.invalid/private.pdf for survey.",
                "Please visit session-deadbeefdeadbeef and run-deadbeefdeadbeef for survey.",
                "Please visit api key is sk-test-12345 for survey.",
                "Please visit secret key is abc123 for survey.",
                "Please visit private key is abc123 for survey.",
                "Please visit session id is abc123 for survey.",
                "Please visit run id is abc123 for survey.",
            ]
            for prompt in sensitive_prompts:
                add_conversation_turn(
                    session["sessionId"],
                    role="user",
                    text=prompt,
                    metadata={"routeInput": True},
                    config=config,
                )
            update_working_memory(
                session["sessionId"],
                config,
                latestLocationResolution={
                    "siteName": "https://example.invalid/private.pdf",
                    "needsLocationConfirmation": True,
                    "nextStage": "waiting_for_location_confirmation",
                    "locationCandidates": [{"label": "redacted"}],
                },
                confirmedLocation={
                    "name": "run-deadbeefdeadbeef",
                    "latitude": 50.825351,
                    "longitude": -0.125125,
                    "source": "user-supplied-coordinate",
                    "confidence": "medium",
                },
                latestReviewSummary={
                    "status": "completed",
                    "headline": "session-deadbeefdeadbeef should not be retained",
                    "generationMode": "real",
                },
            )
            context = llm_session_context(session)

        serialized = str(context)
        for turn in context["recentTurns"]:
            self.assertIsNone(turn["summary"]["siteName"])
        self.assertIsNone(context["workingMemory"]["latestLocationResolution"]["siteName"])
        self.assertIsNone(context["workingMemory"]["confirmedLocation"]["name"])
        self.assertIsNone(context["workingMemory"]["latestReviewSummary"]["headline"])
        self.assertNotIn("3drams-", serialized)
        self.assertNotIn("example.invalid", serialized)
        self.assertNotIn("session-deadbeefdeadbeef", serialized)
        self.assertNotIn("run-deadbeefdeadbeef", serialized)
        self.assertNotIn("api key", serialized)
        self.assertNotIn("secret key", serialized)
        self.assertNotIn("private key", serialized)
        self.assertNotIn("session id is", serialized)
        self.assertNotIn("run id is", serialized)

    def test_llm_evaluator_upstream_retry_expands_downstream_dependencies(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
            BEDROCK_MOCK_PLANNER_SCENARIO="v2-valid",
            BEDROCK_MOCK_EVALUATOR_SCENARIO="fail-upstream-geo",
            BEDROCK_MAX_MODEL_CALLS="4",
            DURABLE_RUN_MAX_TOOL_CALLS="15",
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
        self.assertEqual(result["result"]["evaluationStopReason"], "passed_after_retry")
        improvement = next(step for step in result["steps"] if step["name"] == "output_improvement_loop")
        retry_tools = improvement["output"]["retryTools"]
        self.assertIn("load_geospatial_features", retry_tools)
        self.assertIn("build_scene_config", retry_tools)
        self.assertIn("extract_hazard_notes", retry_tools)
        self.assertIn("rank_risks", retry_tools)
        self.assertIn("create_annotations", retry_tools)
        self.assertIn("compile_review_pack", retry_tools)
        self.assertTrue(
            any(
                step["name"] == "tool:build_scene_config" and step["output"].get("evaluationLoop") == 1
                for step in result["steps"]
            )
        )

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
