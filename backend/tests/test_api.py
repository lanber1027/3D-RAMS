import os
import sys
import unittest
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402
from app.access import hash_access_code  # noqa: E402


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


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_endpoint_returns_service_status(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "3d-rams-demo1"})

    def test_run_endpoint_returns_default_public_pack_contract(self):
        with EnvPatch(ENABLE_BEDROCK="false"):
            response = self.client.post(
                "/api/run",
                json={"fixturePack": "public-lambeth-thames", "useBedrock": False},
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["runtime"]["fixturePack"], "public-lambeth-thames")
        self.assertEqual(result["runtime"]["fixturePackMode"], "cached-public-fixture")
        self.assertFalse(result["runtime"]["liveApiCalls"])
        self.assertTrue(result["safety"]["allowed"])
        self.assertGreaterEqual(len(result["annotations"]), 1)
        self.assertGreaterEqual(len(result["evidence"]), 1)
        self.assertGreaterEqual(len(result["trace"]), 9)
        self.assertIn("architecture", result)

    def test_run_endpoint_accepts_fixture_pack_alias(self):
        with EnvPatch(ENABLE_BEDROCK="false"):
            response = self.client.post(
                "/api/run",
                json={"fixture_pack": "public-lambeth-thames", "useBedrock": False},
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["runtime"]["fixturePack"], "public-lambeth-thames")
        self.assertEqual(result["request"]["fixturePack"], "public-lambeth-thames")

    def test_run_endpoint_rejects_invalid_latitude(self):
        response = self.client.post(
            "/api/run",
            json={"latitude": "north", "longitude": -0.118712, "useBedrock": False},
        )

        self.assertEqual(response.status_code, 422)
        errors = response.json()["detail"]
        self.assertTrue(any(error["loc"][-1] == "latitude" for error in errors))

    def test_openapi_documents_run_request_schema(self):
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        schema = response.json()
        run_operation = schema["paths"]["/api/run"]["post"]
        request_ref = run_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        self.assertIn("latitude", request_schema["properties"])
        self.assertIn("longitude", request_schema["properties"])
        self.assertIn("fixturePack", request_schema["properties"])
        self.assertIn("agentMode", request_schema["properties"])

    def test_run_endpoint_exposes_llm_first_response_contract_in_no_aws_fallback(self):
        with EnvPatch(ENABLE_BEDROCK="false"):
            response = self.client.post(
                "/api/run",
                json={"fixturePack": "public-lambeth-thames", "useBedrock": True},
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["request"]["agentMode"], "llm-planner")
        self.assertEqual(result["runtime"]["agentMode"], "llm-planner")
        self.assertEqual(result["runtime"]["activeAgentMode"], "deterministic-fallback")
        self.assertEqual(result["runtime"]["briefingMode"], "fallback")
        self.assertIn("llmPlan", result)
        self.assertIn("llmToolCalls", result)
        self.assertIn("modelCalls", result)
        self.assertIn("tokenUsage", result)
        self.assertIn("fallback", result)
        self.assertEqual(result["llmPlan"]["status"], "fallback")
        self.assertEqual(result["llmToolCalls"], [])
        self.assertEqual(result["modelCalls"], [])
        self.assertEqual(result["fallback"]["status"], "fallback")

    def test_run_endpoint_requires_access_header_when_hosted_access_hash_is_set(self):
        with EnvPatch(
            APP_ACCESS_TOKEN_HASH=hash_access_code("team-code"),
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
        ):
            response = self.client.post(
                "/api/run",
                json={"fixturePack": "public-lambeth-thames", "useBedrock": True},
            )

        self.assertEqual(response.status_code, 401)

    def test_run_endpoint_accepts_access_header_when_hosted_access_hash_is_set(self):
        with EnvPatch(
            APP_ACCESS_TOKEN_HASH=hash_access_code("team-code"),
            ENABLE_BEDROCK="false",
        ):
            response = self.client.post(
                "/api/run",
                headers={"X-3DRAMS-Access": "team-code"},
                json={"fixturePack": "public-lambeth-thames", "useBedrock": False},
            )

        self.assertEqual(response.status_code, 200)

    def test_run_endpoint_reports_missing_planning_warning(self):
        with EnvPatch(ENABLE_BEDROCK="false"):
            response = self.client.post(
                "/api/run",
                json={
                    "fixturePack": "public-lambeth-thames",
                    "includePlanningFixture": False,
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        planning_step = next(step for step in result["trace"] if step["name"] == "load_planning_context")
        self.assertEqual(planning_step["status"], "warning")
        self.assertTrue(
            any("Planning/context notes were unavailable" in item for item in result["briefing"]["limitations"])
        )

    def test_run_endpoint_blocks_unsafe_request(self):
        with EnvPatch(ENABLE_BEDROCK="false"):
            response = self.client.post(
                "/api/run",
                json={
                    "fixturePack": "public-lambeth-thames",
                    "useBedrock": False,
                    "additionalRequest": "Please certify RAMS and approve work today.",
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertFalse(result["safety"]["allowed"])
        self.assertEqual(result["safety"]["level"], "blocked")
        self.assertEqual(result["annotations"], [])
        self.assertEqual(result["hazards"], [])
        self.assertIn("certify rams", result["safety"]["triggeredRules"])

    def test_session_start_allows_local_dev_without_access_hash(self):
        with EnvPatch(APP_ACCESS_TOKEN_HASH=None):
            response = self.client.post(
                "/api/session/start",
                json={"testerAlias": "qa"},
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["sessionId"].startswith("session-"))
        self.assertEqual(result["accessLabel"], "local-dev")
        self.assertEqual(result["runtime"]["accessMode"], "local-dev-open")

    def test_session_start_rejects_invalid_access_code_when_hash_is_set(self):
        with EnvPatch(APP_ACCESS_TOKEN_HASH="bad-hash"):
            response = self.client.post(
                "/api/session/start",
                json={"accessCode": "wrong"},
            )

        self.assertEqual(response.status_code, 401)

    def test_chat_endpoint_returns_clarifying_questions_without_site_signal(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Please prepare my pre-visit pack.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["needsClarification"])
        self.assertEqual(result["runtime"]["activeAgentMode"], "clarification")
        self.assertGreaterEqual(len(result["clarifyingQuestions"]), 1)
        self.assertEqual(result["modelCalls"], [])

    def test_chat_endpoint_clarifies_unknown_named_site_without_coordinate(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Bilsbrae Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["needsClarification"])
        self.assertFalse(result["needsLocationConfirmation"])
        self.assertEqual(result["nextStage"], "provide_location_detail")
        self.assertIn("Bilsbrae Solar Farm", result["assistantMessage"])
        self.assertEqual(result["runtime"]["activeAgentMode"], "location-resolution")
        self.assertEqual(result["scene"], None)
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["locationCandidates"], [])
        parse_step = next(step for step in result["trace"] if step["name"] == "chat_parse_user_request")
        self.assertEqual(parse_step["status"], "warning")
        self.assertEqual(parse_step["output"]["siteResolution"], "unresolved")
        self.assertIsNone(parse_step["output"]["fixturePackSelected"])
        resolver_step = next(step for step in result["trace"] if step["name"] == "resolve_location_candidates")
        self.assertEqual(resolver_step["status"], "warning")
        self.assertEqual(resolver_step["output"]["candidateCount"], 0)

    def test_chat_endpoint_coordinate_named_site_uses_synthetic_coordinate_not_lambeth(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "status": 200,
            "result": [
                {
                    "postcode": "KY12 9AB",
                    "outcode": "KY12",
                    "latitude": 56.123,
                    "longitude": -3.456,
                    "admin_district": "Fife",
                    "admin_ward": "Dunfermline Central",
                    "region": "Scotland",
                    "country": "Scotland",
                }
            ],
        }
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None), patch("app.location_resolver.httpx.get", return_value=fake_response):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Bilsbrae Solar Farm tomorrow at 56.1234, -3.4567 for a survey.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["needsClarification"])
        self.assertTrue(result["needsLocationConfirmation"])
        self.assertEqual(result["nextStage"], "confirm_location")
        self.assertNotIn("8 Albert Embankment", result["assistantMessage"])
        self.assertIn("Bilsbrae", result["assistantMessage"])
        self.assertIsNone(result["scene"])
        self.assertEqual(result["evidence"], [])
        candidate = result["locationCandidates"][0]
        self.assertEqual(candidate["source"], "user-supplied-coordinate")
        self.assertEqual(candidate["dataMode"], "source-labelled-coordinate")
        self.assertAlmostEqual(candidate["latitude"], 56.1234)
        self.assertAlmostEqual(candidate["longitude"], -3.4567)
        self.assertEqual(candidate["locationContext"]["district"], "Fife")
        parse_step = next(step for step in result["trace"] if step["name"] == "chat_parse_user_request")
        self.assertEqual(parse_step["output"]["siteResolution"], "coordinate-confirmation")
        resolver_step = next(step for step in result["trace"] if step["name"] == "resolve_location_candidates")
        self.assertEqual(resolver_step["output"]["candidateCount"], 1)

    def test_chat_endpoint_coordinate_site_keeps_clean_label_and_prompt_risks(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
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
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None), patch("app.location_resolver.httpx.get", return_value=fake_response):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Foxglove Farm Solar Site at 54.9712, -2.1010 tomorrow for a PV module inspection and access track survey.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        hazards = result["uiState"]["hazards"]
        self.assertIsNone(result["uiState"]["location"])
        self.assertTrue(result["needsLocationConfirmation"])
        self.assertEqual(result["locationCandidates"][0]["name"], "Foxglove Farm Solar Site")
        self.assertEqual(result["locationCandidates"][0]["locationContext"]["nearestTown"], "Hexham")
        self.assertEqual(hazards[0]["title"], "PV electrical isolation and inverter interface")
        self.assertTrue(any(hazard["title"] == "PV electrical isolation and inverter interface" for hazard in hazards))
        self.assertTrue(any(hazard.get("dataMode") == "provisional-from-user-description" for hazard in hazards))

    def test_chat_endpoint_coordinate_only_does_not_use_temporal_word_as_site_label(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "status": 200,
            "result": [
                {
                    "postcode": "BN2 0QU",
                    "outcode": "BN2",
                    "latitude": 50.825351,
                    "longitude": -0.125125,
                    "admin_district": "Brighton and Hove",
                    "admin_ward": "Queen's Park",
                    "region": "South East",
                    "country": "England",
                }
            ],
        }
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None), patch("app.location_resolver.httpx.get", return_value=fake_response):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit 50.825351, -0.125125 tomorrow for a survey.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["needsLocationConfirmation"])
        self.assertEqual(result["locationCandidates"][0]["name"], "Coordinate 50.825351, -0.125125")
        self.assertNotEqual(result["locationCandidates"][0]["name"].lower(), "tomorrow")

    def test_chat_endpoint_postcode_prompt_returns_source_labelled_candidate(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "status": 200,
            "result": {
                "postcode": "SW1A 1AA",
                "outcode": "SW1A",
                "latitude": 51.501,
                "longitude": -0.141,
                "admin_district": "Westminster",
                "admin_ward": "St James's",
            },
        }
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None), patch("app.location_resolver.httpx.get", return_value=fake_response):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Foxglove Farm Solar Site at SW1A 1AA tomorrow for a survey.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["needsLocationConfirmation"])
        self.assertEqual(result["nextStage"], "confirm_location")
        self.assertEqual(len(result["locationCandidates"]), 1)
        candidate = result["locationCandidates"][0]
        self.assertEqual(candidate["source"], "postcodes.io/postcodes")
        self.assertEqual(candidate["dataMode"], "source-labelled-location")
        self.assertEqual(candidate["countyOrAuthority"], "Westminster")

    def test_chat_endpoint_geoapify_prompt_returns_source_labelled_candidate_when_enabled(self):
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
            ENABLE_GEOAPIFY_GEOCODING="true",
            GEOAPIFY_API_KEY="test-key",
        ), patch("app.geoapify_resolver.httpx.get", return_value=fake_response) as get_mock:
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Foxglove Farm Solar Site near Hexham tomorrow for a PV module inspection.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_mock.call_count, 1)
        result = response.json()
        self.assertTrue(result["needsLocationConfirmation"])
        self.assertEqual(result["nextStage"], "confirm_location")
        self.assertEqual(result["scene"], None)
        self.assertEqual(result["evidence"], [])
        candidate = result["locationCandidates"][0]
        self.assertEqual(candidate["source"], "geoapify/geocode/search")
        self.assertEqual(candidate["provider"], "Geoapify")
        self.assertEqual(candidate["dataMode"], "source-labelled-location")
        self.assertEqual(candidate["confidence"], "high")
        resolver_step = next(step for step in result["trace"] if step["name"] == "resolve_location_candidates")
        self.assertEqual(resolver_step["output"]["geoapifyLookup"]["status"], "ok")
        self.assertEqual(resolver_step["output"]["candidateCount"], 1)

    def test_chat_endpoint_geoapify_failure_falls_back_to_provisional_location_gate(self):
        with EnvPatch(
            ENABLE_BEDROCK="false",
            APP_ACCESS_TOKEN_HASH=None,
            ENABLE_GEOAPIFY_GEOCODING="true",
            GEOAPIFY_API_KEY="test-key",
        ), patch("app.geoapify_resolver.httpx.get", side_effect=RuntimeError("rate limit")):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit Foxglove Farm Solar Site near Hexham tomorrow for a PV module inspection.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["needsClarification"])
        self.assertFalse(result["needsLocationConfirmation"])
        self.assertEqual(result["nextStage"], "provide_location_detail")
        self.assertEqual(result["locationCandidates"], [])
        self.assertEqual(result["scene"], None)
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["uiState"]["reviewMode"], "provisional checklist pending location")
        resolver_step = next(step for step in result["trace"] if step["name"] == "resolve_location_candidates")
        self.assertEqual(resolver_step["output"]["geoapifyLookup"]["status"], "warning")
        self.assertEqual(resolver_step["output"]["candidateCount"], 0)

    def test_chat_endpoint_standalone_certification_request_is_blocked(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "Please certify RAMS and approve work today.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertFalse(result["safety"]["allowed"])
        self.assertEqual(result["safety"]["level"], "blocked")
        self.assertEqual(result["runtime"]["activeAgentMode"], "safety-gate")
        self.assertFalse(result["needsClarification"])

    def test_chat_endpoint_runs_hosted_agent_contract_with_public_fixture(self):
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertFalse(result["needsClarification"])
        self.assertIn("RAMS-style pre-visit review pack", result["assistantMessage"])
        self.assertIn("uiState", result)
        self.assertIn("scene", result["uiState"])
        self.assertIn("evidence", result["uiState"])
        self.assertIn("trace", result["uiState"])
        self.assertTrue(result["safety"]["allowed"])
        self.assertEqual(result["runtime"]["hostedProductMode"], True)

    def test_chat_endpoint_reports_actual_memory_fallback_when_dynamodb_is_unavailable(self):
        with EnvPatch(
            ENABLE_BEDROCK="false",
            APP_ACCESS_TOKEN_HASH=None,
            DYNAMODB_SESSION_TABLE="missing-local-table",
            AWS_EC2_METADATA_DISABLED="true",
        ):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/chat",
                json={
                    "sessionId": session["sessionId"],
                    "message": "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
                    "useBedrock": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(session["runtime"]["sessionTraceMode"], "memory-fallback")
        self.assertEqual(result["runtime"]["sessionTraceMode"], "memory-fallback")

    def test_session_store_converts_coordinate_floats_for_dynamodb_trace(self):
        from app.config import RuntimeConfig
        from app import session_store
        from app.session_store import create_session, get_session, update_working_memory

        captured = {"getItemCalls": 0}

        class FakeTable:
            def put_item(self, *, Item):
                captured["item"] = Item

            def get_item(self, *, Key):
                captured["getItemCalls"] += 1
                return {"Item": captured["item"]}

        fake_boto3 = SimpleNamespace(resource=lambda *args, **kwargs: SimpleNamespace(Table=lambda name: FakeTable()))

        with EnvPatch(
            APP_ACCESS_TOKEN_HASH=None,
            DYNAMODB_SESSION_TABLE="fake-sessions",
            AWS_EC2_METADATA_DISABLED="true",
        ), patch.dict(sys.modules, {"boto3": fake_boto3}):
            config = RuntimeConfig.from_env(request_bedrock=False)
            session = create_session(tester_alias="qa", access_label="team-test", config=config)
            memory = update_working_memory(
                session["sessionId"],
                config,
                confirmedLocation={
                    "name": "Coordinate 54.9712, -2.1013",
                    "latitude": 54.9712,
                    "longitude": -2.1013,
                    "source": "user-supplied-coordinate",
                },
                latestLocationResolution={
                    "siteName": "Foxglove Farm Solar Site",
                    "locationCandidates": [
                        {
                            "candidateId": "candidate-coordinate-54-9712-2-1013",
                            "latitude": 54.9712,
                            "longitude": -2.1013,
                            "intent": {"coordinate": (54.9712, -2.1013)},
                        }
                    ],
                },
            )
            self.assertEqual(session["storageMode"], "dynamodb")
            self.assertEqual(memory["confirmedLocation"]["latitude"], 54.9712)
            saved_location = captured["item"]["workingMemory"]["confirmedLocation"]
            self.assertIsInstance(saved_location["latitude"], Decimal)
            self.assertIsInstance(saved_location["longitude"], Decimal)
            self.assertEqual(saved_location["latitude"], Decimal("54.9712"))
            self.assertEqual(saved_location["longitude"], Decimal("-2.1013"))
            saved_candidate = captured["item"]["workingMemory"]["latestLocationResolution"]["locationCandidates"][0]
            self.assertIsInstance(saved_candidate["intent"]["coordinate"], list)
            self.assertEqual(saved_candidate["intent"]["coordinate"], [Decimal("54.9712"), Decimal("-2.1013")])
            session_store._SESSIONS.pop(session["sessionId"], None)
            cold_session = get_session(session["sessionId"], config=config)
            cold_location = cold_session["workingMemory"]["confirmedLocation"]
            cold_candidate = cold_session["workingMemory"]["latestLocationResolution"]["locationCandidates"][0]

        self.assertEqual(captured["getItemCalls"], 1)
        self.assertIsInstance(cold_location["latitude"], float)
        self.assertIsInstance(cold_location["longitude"], float)
        self.assertEqual(cold_location["latitude"], 54.9712)
        self.assertEqual(cold_location["longitude"], -2.1013)
        self.assertEqual(cold_candidate["intent"]["coordinate"], [54.9712, -2.1013])

    def test_upload_url_returns_local_mock_when_s3_is_unconfigured(self):
        with EnvPatch(APP_ACCESS_TOKEN_HASH=None, S3_UPLOAD_BUCKET=None):
            session = self.client.post("/api/session/start", json={"testerAlias": "qa"}).json()
            response = self.client.post(
                "/api/upload-url",
                json={
                    "sessionId": session["sessionId"],
                    "filename": "site-photo.jpg",
                    "contentType": "image/jpeg",
                    "sizeBytes": 1024,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "mocked")
        self.assertEqual(result["storageMode"], "local-mock")


if __name__ == "__main__":
    unittest.main()
