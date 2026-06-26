import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import run_site_briefing


class SiteBriefingAgentTests(unittest.TestCase):
    def test_happy_path_returns_scene_annotations_evidence_and_trace(self):
        result = run_site_briefing({"latitude": 52.2053, "longitude": -1.6022})

        self.assertEqual(result["scene"]["provider"], "cesium-local-fixture")
        self.assertGreaterEqual(len(result["annotations"]), 5)
        self.assertGreaterEqual(len(result["evidence"]), 2)
        self.assertGreaterEqual(len(result["trace"]), 8)
        self.assertTrue(result["safety"]["allowed"])

    def test_missing_planning_fixture_keeps_geospatial_warning(self):
        result = run_site_briefing({"includePlanningFixture": False})

        load_step = next(step for step in result["trace"] if step["name"] == "load_planning_context")
        self.assertEqual(load_step["status"], "warning")
        self.assertTrue(
            any("Planning evidence was unavailable" in item for item in result["briefing"]["limitations"])
        )

    def test_tool_failure_uses_map_fallback(self):
        result = run_site_briefing({"simulateMapFailure": True})

        geo_step = next(step for step in result["trace"] if step["name"] == "load_geospatial_features")
        self.assertEqual(geo_step["status"], "fallback")
        self.assertGreaterEqual(result["scene"]["featureCount"], 1)

    def test_unsafe_request_is_blocked(self):
        result = run_site_briefing({"additionalRequest": "Please certify RAMS and approve work today."})

        self.assertFalse(result["safety"]["allowed"])
        self.assertEqual(result["annotations"], [])
        self.assertIn("blocked", result["safety"]["level"])

    def test_low_confidence_feature_is_labelled(self):
        result = run_site_briefing({})

        confidences = {annotation["confidence"] for annotation in result["annotations"]}
        self.assertIn("low", confidences)


if __name__ == "__main__":
    unittest.main()
