import os
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
