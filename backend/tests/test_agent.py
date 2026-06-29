import unittest
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import run_site_briefing


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


class SiteBriefingAgentTests(unittest.TestCase):
    def test_happy_path_returns_scene_annotations_evidence_and_trace(self):
        result = run_site_briefing({"latitude": 52.2053, "longitude": -1.6022})

        self.assertEqual(result["scene"]["provider"], "cesium-local-fixture")
        self.assertGreaterEqual(len(result["annotations"]), 5)
        self.assertGreaterEqual(len(result["evidence"]), 2)
        self.assertGreaterEqual(len(result["trace"]), 8)
        self.assertTrue(result["safety"]["allowed"])
        self.assertIn("request", result)
        self.assertIn("runtime", result)
        self.assertEqual(result["runtime"]["briefingMode"], "disabled")
        self.assertIn("sources", result)
        self.assertIn("runOverview", result["architecture"])
        self.assertEqual(result["architecture"]["runOverview"]["briefingMode"], "disabled")

    def test_missing_planning_fixture_keeps_geospatial_warning(self):
        result = run_site_briefing({"includePlanningFixture": False})

        load_step = next(step for step in result["trace"] if step["name"] == "load_planning_context")
        self.assertEqual(load_step["status"], "warning")
        planning_source = next(source for source in result["sources"] if source["id"] == "planning-fixture")
        self.assertEqual(planning_source["status"], "unavailable")
        self.assertTrue(
            any("Planning evidence was unavailable" in item for item in result["briefing"]["limitations"])
        )

    def test_tool_failure_uses_map_fallback(self):
        result = run_site_briefing({"simulateMapFailure": True})

        geo_step = next(step for step in result["trace"] if step["name"] == "load_geospatial_features")
        self.assertEqual(geo_step["status"], "fallback")
        self.assertIn("fallback", geo_step["fallbackReason"].lower())
        self.assertGreaterEqual(result["scene"]["featureCount"], 1)

    def test_unsafe_request_is_blocked(self):
        result = run_site_briefing({"additionalRequest": "Please certify RAMS and approve work today."})

        self.assertFalse(result["safety"]["allowed"])
        self.assertEqual(result["annotations"], [])
        self.assertIn("blocked", result["safety"]["level"])
        self.assertIn("certify rams", result["safety"]["triggeredRules"])

    def test_low_confidence_feature_is_labelled(self):
        result = run_site_briefing({})

        confidences = {annotation["confidence"] for annotation in result["annotations"]}
        self.assertIn("low", confidences)

    def test_architecture_visualizer_contract_tracks_sources_trace_and_aws_mapping(self):
        result = run_site_briefing({"goal": "Pre-visit RAMS scoping pack"})
        architecture = result["architecture"]

        self.assertGreaterEqual(len(architecture["sources"]), 5)
        self.assertGreaterEqual(len(architecture["currentTrace"]), 9)
        self.assertGreaterEqual(len(architecture["awsPath"]), 5)
        self.assertIn("safetyGate", architecture)
        self.assertTrue(all("id" in step for step in result["trace"]))
        self.assertTrue(all("sourceIds" in step for step in result["trace"]))
        self.assertTrue(any(step["name"] == "generate_bedrock_briefing" for step in result["trace"]))

    def test_bedrock_mock_mode_updates_briefing_and_trace(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
            BEDROCK_MOCK_UNSAFE_RESPONSE=None,
            AWS_REGION="eu-west-2",
            BEDROCK_MODEL_ID="anthropic.claude-3-7-sonnet-20250219-v1:0",
        ):
            result = run_site_briefing({"useBedrock": True})

        self.assertEqual(result["runtime"]["briefingMode"], "mocked")
        self.assertEqual(result["briefing"]["generation_mode"], "bedrock-mock")
        bedrock_step = next(step for step in result["trace"] if step["name"] == "generate_bedrock_briefing")
        self.assertEqual(bedrock_step["status"], "ok")
        self.assertEqual(bedrock_step["output"]["modelId"], "anthropic.claude-3-7-sonnet-20250219-v1:0")
        self.assertEqual(bedrock_step["output"]["maxTokens"], 1200)
        self.assertEqual(bedrock_step["output"]["temperature"], 0.2)

    def test_unsafe_bedrock_mock_briefing_is_blocked_after_generation(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE="true",
            BEDROCK_MOCK_UNSAFE_RESPONSE="true",
            BEDROCK_MODEL_ID="anthropic.claude-3-7-sonnet-20250219-v1:0",
        ):
            result = run_site_briefing({"useBedrock": True})

        self.assertEqual(result["runtime"]["briefingMode"], "mocked")
        self.assertFalse(result["safety"]["allowed"])
        self.assertEqual(result["safety"]["level"], "blocked")
        self.assertEqual(result["annotations"], [])
        self.assertIn("certified rams", result["safety"]["triggeredRules"])
        self.assertIn("approved for work", result["safety"]["triggeredRules"])
        self.assertIn("certified rams", result["safety"]["triggeredSources"]["generatedBriefing"])
        self.assertEqual(result["briefing"]["headline"], "Request blocked by safety gate.")

        bedrock_step = next(step for step in result["trace"] if step["name"] == "generate_bedrock_briefing")
        safety_step = next(step for step in result["trace"] if step["name"] == "safety_gate")
        self.assertEqual(bedrock_step["status"], "ok")
        self.assertEqual(safety_step["status"], "blocked")
        self.assertIn("generatedBriefing", safety_step["output"]["triggeredSources"])

    def test_bedrock_failure_falls_back_to_deterministic_briefing(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_SIMULATE_FAILURE="true",
            BEDROCK_MOCK_UNSAFE_RESPONSE=None,
            BEDROCK_MODEL_ID="anthropic.claude-3-7-sonnet-20250219-v1:0",
        ):
            result = run_site_briefing({"useBedrock": True})

        self.assertEqual(result["runtime"]["briefingMode"], "fallback")
        self.assertIn("Bedrock briefing failed", result["runtime"]["fallbackReason"])
        self.assertNotEqual(result["briefing"].get("generation_mode"), "bedrock")
        bedrock_step = next(step for step in result["trace"] if step["name"] == "generate_bedrock_briefing")
        self.assertEqual(bedrock_step["status"], "fallback")
        self.assertIn("deterministic briefing used", bedrock_step["fallbackReason"])


if __name__ == "__main__":
    unittest.main()
