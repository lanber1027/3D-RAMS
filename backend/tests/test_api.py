import os
import sys
import unittest
from pathlib import Path

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
        with EnvPatch(ENABLE_BEDROCK="false", APP_ACCESS_TOKEN_HASH=None):
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
        self.assertFalse(result["needsClarification"])
        self.assertNotIn("8 Albert Embankment", result["assistantMessage"])
        self.assertIn("Bilsbrae", result["assistantMessage"])
        self.assertAlmostEqual(result["uiState"]["location"]["latitude"], 56.1234)
        self.assertAlmostEqual(result["uiState"]["location"]["longitude"], -3.4567)
        self.assertIsNone(result["runtime"]["fixturePack"])
        self.assertEqual(result["runtime"]["fixturePackMode"], "synthetic-default")

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
