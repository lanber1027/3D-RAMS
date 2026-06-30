import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rams_agent_tools import fixtures as fixture_module  # noqa: E402
from supervisor_core.agent import run_site_briefing  # noqa: E402


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
        self.assertEqual(result["runtime"]["plannerMode"], "deterministic")
        self.assertEqual(result["runtime"]["activeAgentMode"], "deterministic-planner")
        self.assertEqual(result["runtime"]["modelCallCount"], 0)
        self.assertEqual(result["llmPlan"]["initialParallelGroups"], ["geospatial_subagent", "planning_subagent"])
        self.assertEqual(result["llmPlan"]["reportParallelGroups"], ["annotation_subagent", "briefing_subagent"])
        self.assertEqual(result["modelCalls"], [])
        self.assertEqual(result["fallback"]["status"], "used")
        self.assertIsNone(result["request"]["fixturePack"])
        self.assertEqual(result["runtime"]["fixturePackMode"], "synthetic-default")
        self.assertIn("sources", result)
        self.assertTrue(any(step["name"] == "plan_subagent_workflow" for step in result["trace"]))
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

    def test_lambeth_fixture_pack_returns_cached_public_sources_and_hazards(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        self.assertEqual(result["request"]["fixturePack"], "public-lambeth-thames")
        self.assertEqual(result["runtime"]["fixturePack"], "public-lambeth-thames")
        self.assertEqual(result["runtime"]["fixturePackMode"], "cached-public-fixture")
        self.assertFalse(result["runtime"]["liveApiCalls"])
        self.assertEqual(result["location"]["authority"], "London Borough of Lambeth")
        self.assertEqual(result["scene"]["provider"], "cesium-local-cached-fixture")
        self.assertEqual(result["scene"]["dataMode"], "cached-public-fixture")
        self.assertTrue(result["safety"]["allowed"])

        source_statuses = {source["id"]: source["status"] for source in result["sources"]}
        self.assertEqual(source_statuses["public-ea-flood-context"], "cached-public")
        self.assertEqual(source_statuses["public-lambeth-planning-context"], "cached-public")

        evidence_statuses = {item["id"]: item["status"] for item in result["evidence"]}
        self.assertEqual(evidence_statuses["ev-lambeth-flood-context"], "cached-public")
        self.assertTrue(all(item.get("sourceIds") for item in result["evidence"]))

        hazard_titles = {annotation["title"] for annotation in result["annotations"]}
        self.assertIn("River-edge and flood-context review", hazard_titles)
        self.assertTrue(all(annotation["sourceIds"] for annotation in result["annotations"]))
        self.assertTrue(all(hazard["sourceIds"] for hazard in result["hazards"]))
        self.assertTrue(all(hazard["evidenceIds"] for hazard in result["hazards"]))

        hazard_step = next(step for step in result["trace"] if step["name"] == "extract_hazard_notes")
        self.assertEqual(hazard_step["output"]["dataMode"], "cached-public-fixture")
        self.assertIn("public-ea-flood-context", hazard_step["sourceIds"])
        self.assertIn("ev-lambeth-flood-context", hazard_step["evidenceIds"])
        self.assertEqual(result["architecture"]["runOverview"]["fixturePack"], "public-lambeth-thames")
        self.assertTrue(
            any(
                item["component"] == "Fixture pack" and "cached public fixture" in item["status"]
                for item in result["architecture"]["realVsMocked"]
            )
        )

    def test_unknown_fixture_pack_falls_back_to_synthetic_defaults(self):
        result = run_site_briefing({"fixturePack": "missing-pack", "useBedrock": False})

        self.assertIsNone(result["runtime"]["fixturePack"])
        self.assertEqual(result["runtime"]["fixturePackMode"], "synthetic-default")
        self.assertEqual(result["scene"]["provider"], "cesium-local-fixture")
        fallback_step = next(step for step in result["trace"] if step["name"] == "load_fixture_pack")
        self.assertEqual(fallback_step["status"], "fallback")
        self.assertIn("synthetic defaults", fallback_step["fallbackReason"])

    def test_fixture_pack_path_traversal_falls_back_to_synthetic_defaults(self):
        result = run_site_briefing({"fixturePack": "../public-lambeth-thames", "useBedrock": False})

        self.assertIsNone(result["runtime"]["fixturePack"])
        self.assertEqual(result["runtime"]["fixturePackMode"], "synthetic-default")
        fallback_step = next(step for step in result["trace"] if step["name"] == "load_fixture_pack")
        self.assertEqual(fallback_step["status"], "fallback")
        self.assertIn("not allowed", fallback_step["fallbackReason"])

    def test_fixture_pack_planning_file_cannot_escape_pack_directory(self):
        previous_fixtures = fixture_module.FIXTURES
        previous_allowed = fixture_module.ALLOWED_FIXTURE_PACKS
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            pack_dir = temp_path / "malicious"
            pack_dir.mkdir()
            (temp_path / "secret.txt").write_text("PRIVATE", encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "location": {
                            "label": "Malicious fixture",
                            "latitude": 51.5,
                            "longitude": -0.1,
                        },
                        "planning": {"file": "../secret.txt"},
                    }
                ),
                encoding="utf-8",
            )

            try:
                fixture_module.FIXTURES = temp_path
                fixture_module.ALLOWED_FIXTURE_PACKS = {"malicious"}
                pack, warning = fixture_module.load_fixture_pack("malicious")
            finally:
                fixture_module.FIXTURES = previous_fixtures
                fixture_module.ALLOWED_FIXTURE_PACKS = previous_allowed

        self.assertIsNone(warning)
        self.assertIsNotNone(pack)
        self.assertIsNone(pack["planning"]["text"])
        self.assertTrue(any("missing" in item.lower() for item in pack["warnings"]))

    def test_architecture_visualizer_contract_tracks_agentcore_boundary(self):
        result = run_site_briefing({"goal": "Pre-visit RAMS scoping pack"})
        architecture = result["architecture"]

        self.assertGreaterEqual(len(architecture["sources"]), 5)
        self.assertGreaterEqual(len(architecture["currentTrace"]), 9)
        self.assertGreaterEqual(len(architecture["awsPath"]), 5)
        self.assertIn("safetyGate", architecture)
        self.assertTrue(all("id" in step for step in result["trace"]))
        self.assertTrue(all("sourceIds" in step for step in result["trace"]))
        self.assertTrue(any(step["name"] == "generate_bedrock_briefing" for step in result["trace"]))
        self.assertEqual(architecture["nodes"][1]["label"], "AgentCore invocation endpoint")
        self.assertEqual(architecture["edges"][0]["label"], "POST /invocations")

    def test_supervisor_dispatches_direct_tool_groups_in_parallel(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})
        dispatch_steps = {
            step["name"]: step
            for step in result["trace"]
            if step["name"] in {"dispatch_parallel_tool_groups", "dispatch_parallel_report_groups"}
        }

        self.assertEqual(
            dispatch_steps["dispatch_parallel_tool_groups"]["output"]["groups"],
            ["geospatial_subagent", "planning_subagent"],
        )
        self.assertEqual(
            dispatch_steps["dispatch_parallel_tool_groups"]["output"]["harnesses"]["geospatial_subagent"],
            "rams_geospatial_harness",
        )
        self.assertEqual(
            dispatch_steps["dispatch_parallel_report_groups"]["output"]["groups"],
            ["annotation_subagent", "briefing_subagent"],
        )
        self.assertEqual(
            dispatch_steps["dispatch_parallel_report_groups"]["output"]["harnesses"]["briefing_subagent"],
            "rams_briefing_harness",
        )
        self.assertEqual(
            dispatch_steps["dispatch_parallel_tool_groups"]["output"]["mode"],
            "direct-local-harness-adapter",
        )
        self.assertEqual(result["runtime"]["subagentExecutionMode"], "direct-local-harness-adapter")

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
        self.assertEqual(result["runtime"]["plannerMode"], "mocked")
        self.assertEqual(result["runtime"]["activeAgentMode"], "llm-planner-mock")
        self.assertEqual(result["runtime"]["modelCallCount"], 1)
        self.assertEqual(len(result["modelCalls"]), 1)
        self.assertEqual(result["modelCalls"][0]["phase"], "planner-plan")
        self.assertEqual(result["briefing"]["generation_mode"], "bedrock-mock")
        planner_step = next(step for step in result["trace"] if step["name"] == "plan_subagent_workflow")
        self.assertEqual(planner_step["status"], "ok")
        self.assertEqual(planner_step["output"]["plannerStatus"], "mocked")
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


if __name__ == "__main__":
    unittest.main()
