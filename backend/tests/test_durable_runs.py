import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
        return self.client.post("/api/session/start", json={"testerAlias": "qa-v2"}).json()

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
