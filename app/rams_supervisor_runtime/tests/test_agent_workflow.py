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
from rams_agent_tools.config import RuntimeConfig  # noqa: E402
from rams_agent_tools.tools import SUPERVISOR_HARNESS_SUBAGENTS, harness_for_group, tools_for_group  # noqa: E402
from supervisor_core.agent import run_site_briefing  # noqa: E402
from supervisor_core.harness_contract import HARNESS_OUTPUT_SCHEMA_VERSION, validate_harness_output  # noqa: E402
from supervisor_core.subagent_invoker import AgentCoreHarnessInvoker  # noqa: E402


def authorized_material(case_id: str = "case_material_test_001") -> dict:
    return {
        "materialId": "asio_material_site_access_plan",
        "sourceSystem": "asio",
        "type": "application/pdf",
        "label": "Site access plan",
        "summary": "Uploaded by the ASI user for this case.",
        "caseId": case_id,
        "sizeBytes": 24576,
        "access": {
            "mode": "asio_authorized_reference",
            "expiresAt": "2099-01-01T00:00:00Z",
            "retrievalUrl": "https://materials.example.invalid/access-plan.pdf?token=DUMMY_RETRIEVAL_URL_SHOULD_NOT_LEAK",
            "token": "DUMMY_MATERIAL_ACCESS_MARKER_SHOULD_NOT_LEAK",
        },
        "rawContent": "DUMMY RAW MATERIAL CONTENT SHOULD NOT LEAK",
    }


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
        self.assertTrue(result["runtime"]["bedrockRequested"])
        self.assertFalse(result["runtime"]["bedrockEnabled"])
        self.assertFalse(result["runtime"]["bedrockUsed"])
        self.assertEqual(result["runtime"]["plannerMode"], "deterministic")
        self.assertEqual(result["runtime"]["activeAgentMode"], "deterministic-planner")
        self.assertEqual(result["runtime"]["modelCallCount"], 0)
        self.assertEqual(result["llmPlan"]["initialParallelGroups"], ["geospatial_subagent", "planning_subagent"])
        self.assertEqual(result["llmPlan"]["sequentialGroups"][0], "material_subagent")
        self.assertEqual(result["llmPlan"]["reportParallelGroups"], ["annotation_subagent", "briefing_subagent"])
        self.assertEqual(result["reasoning"]["mode"], "deterministic")
        self.assertIn("reportFit", result["reasoning"])
        self.assertTrue(result["reasoning"]["reviewQuestions"])
        self.assertEqual(result["draftReport"]["status"], "draft")
        self.assertEqual(result["reviewGate"]["status"], "passed_with_caveats")
        self.assertEqual(result["finalReportStatus"], "review_passed")
        self.assertEqual(result["modelCalls"], [])
        self.assertEqual(result["fallback"]["status"], "used")
        self.assertIsNone(result["request"]["fixturePack"])
        self.assertEqual(result["runtime"]["fixturePackMode"], "synthetic-default")
        self.assertIn("sources", result)
        self.assertTrue(any(step["name"] == "plan_subagent_workflow" for step in result["trace"]))
        self.assertTrue(any(step["name"] == "reason_over_evidence" for step in result["trace"]))
        self.assertTrue(any(step["name"] == "independent_review_gate" for step in result["trace"]))
        self.assertIn("runOverview", result["architecture"])
        self.assertEqual(result["architecture"]["runOverview"]["briefingMode"], "disabled")

    def test_reasoning_pass_is_mandatory_and_after_subagent_evidence(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        trace_names = [step["name"] for step in result["trace"]]
        self.assertIn("reason_over_evidence", trace_names)
        self.assertLess(trace_names.index("safety_gate"), trace_names.index("reason_over_evidence"))

        reasoning = result["reasoning"]
        self.assertEqual(reasoning["mode"], "deterministic")
        self.assertIn(reasoning["status"], {"ok", "warning"})
        self.assertTrue(any(item["sectionId"] == "candidate-findings" for item in reasoning["reportFit"]))
        self.assertTrue(all("rationale" in item for item in reasoning["findingAssessments"]))

        reason_step = next(step for step in result["trace"] if step["name"] == "reason_over_evidence")
        self.assertEqual(reason_step["output"]["mode"], "deterministic")
        self.assertGreaterEqual(reason_step["output"]["reportFitCount"], 5)
        self.assertGreaterEqual(reason_step["output"]["findingAssessmentCount"], 1)

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

    def test_authorized_asio_material_reference_produces_safe_evidence_and_trace(self):
        result = run_site_briefing(
            {
                "caseId": "case_material_test_001",
                "fixturePack": "public-lambeth-thames",
                "useBedrock": False,
                "materials": [authorized_material()],
            }
        )

        material_ingestion = result["materialIngestion"]
        self.assertEqual(material_ingestion["status"], "ok")
        self.assertEqual(material_ingestion["accepted"], 1)
        self.assertEqual(material_ingestion["skipped"], [])
        self.assertEqual(material_ingestion["references"][0]["access"]["retrieval"], {"method": "retrieval_url", "provided": True})
        self.assertEqual(result["request"]["materials"][0]["access"]["retrieval"], {"method": "retrieval_url", "provided": True})
        self.assertEqual(result["runtime"]["materialIngestionStatus"], "ok")
        self.assertEqual(result["runtime"]["materialEvidenceCount"], 1)

        evidence_by_id = {item["id"]: item for item in result["evidence"]}
        self.assertIn("ev-material-asio-material-site-access-plan", evidence_by_id)
        material_evidence = evidence_by_id["ev-material-asio-material-site-access-plan"]
        self.assertEqual(material_evidence["status"], "authorized-material-fixture")
        self.assertTrue(material_evidence["citations"])
        self.assertFalse(material_evidence["citations"][0]["rawContentStored"])

        hazard_ids = {item["id"] for item in result["hazards"]}
        self.assertIn("material-asio-material-site-access-plan-access-plan-public-realm", hazard_ids)
        trace_step = next(step for step in result["trace"] if step["name"] == "ingest_material_references")
        self.assertEqual(trace_step["status"], "ok")
        self.assertEqual(trace_step["output"]["accepted"], 1)
        self.assertIn("ev-material-asio-material-site-access-plan", trace_step["evidenceIds"])
        dispatch_step = next(step for step in result["trace"] if step["name"] == "dispatch_material_subagent")
        self.assertEqual(dispatch_step["output"]["groups"], ["material_subagent"])
        self.assertEqual(dispatch_step["output"]["harnesses"]["material_subagent"], "rams_material_harness")
        material_output = next(output for output in result["subagentOutputs"] if output["subagent"]["name"] == "material_subagent")
        self.assertEqual(material_output["subagent"]["harness"], "rams_material_harness")
        self.assertEqual(material_output["data"]["accepted"], 1)

        serialized = json.dumps(result)
        self.assertNotIn("DUMMY_MATERIAL_ACCESS_MARKER_SHOULD_NOT_LEAK", serialized)
        self.assertNotIn("DUMMY_RETRIEVAL_URL_SHOULD_NOT_LEAK", serialized)
        self.assertNotIn("retrievalUrl", serialized)
        self.assertNotIn("DUMMY RAW MATERIAL CONTENT SHOULD NOT LEAK", serialized)

    def test_denied_expired_and_oversized_materials_are_skipped_without_secret_leakage(self):
        result = run_site_briefing(
            {
                "caseId": "case_material_test_002",
                "useBedrock": False,
                "materials": [
                    {
                        "materialId": "asio_material_denied",
                        "sourceSystem": "asio",
                        "type": "application/pdf",
                        "label": "Denied material",
                        "caseId": "case_material_test_002",
                        "access": {
                            "mode": "asio_authorized_reference",
                            "status": "denied",
                            "token": "DENIED_DUMMY_ACCESS_MARKER_SHOULD_NOT_LEAK",
                        },
                        "rawContent": "DENIED DUMMY RAW CONTENT SHOULD NOT LEAK",
                    },
                    {
                        "materialId": "asio_material_expired",
                        "sourceSystem": "asio",
                        "type": "image/png",
                        "label": "Expired material",
                        "caseId": "case_material_test_002",
                        "access": {
                            "mode": "asio_authorized_reference",
                            "expiresAt": "2000-01-01T00:00:00Z",
                        },
                    },
                    {
                        "materialId": "asio_material_oversized",
                        "sourceSystem": "asio",
                        "type": "application/pdf",
                        "label": "Oversized material",
                        "caseId": "case_material_test_002",
                        "sizeBytes": 10 * 1024 * 1024 + 1,
                        "access": {"mode": "asio_authorized_reference"},
                    },
                ],
            }
        )

        ingestion = result["materialIngestion"]
        self.assertEqual(ingestion["status"], "warning")
        self.assertEqual(ingestion["accepted"], 0)
        reasons = {item["reason"] for item in ingestion["skipped"]}
        self.assertEqual(reasons, {"denied", "expired", "oversized"})

        trace_step = next(step for step in result["trace"] if step["name"] == "ingest_material_references")
        self.assertEqual(trace_step["status"], "warning")
        self.assertEqual({item["reason"] for item in trace_step["output"]["skipped"]}, reasons)
        material_output = next(output for output in result["subagentOutputs"] if output["subagent"]["name"] == "material_subagent")
        self.assertEqual(material_output["status"], "warning")
        self.assertEqual(material_output["data"]["skippedCount"], 3)

        serialized = json.dumps(result)
        self.assertNotIn("DENIED_DUMMY_ACCESS_MARKER_SHOULD_NOT_LEAK", serialized)
        self.assertNotIn("DENIED DUMMY RAW CONTENT SHOULD NOT LEAK", serialized)
        self.assertNotIn("rawContent", serialized)

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
            if step["name"] in {
                "dispatch_parallel_tool_groups",
                "dispatch_material_subagent",
                "dispatch_parallel_report_groups",
            }
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
        self.assertEqual(
            dispatch_steps["dispatch_material_subagent"]["output"]["harnesses"]["material_subagent"],
            "rams_material_harness",
        )
        self.assertEqual(result["runtime"]["subagentExecutionMode"], "direct-local-harness-adapter")

    def test_material_subagent_is_registered_for_planner_and_tools(self):
        self.assertEqual(harness_for_group("material_subagent"), "rams_material_harness")
        self.assertEqual(tools_for_group("material_subagent"), ["ingest_material_references"])
        self.assertEqual(SUPERVISOR_HARNESS_SUBAGENTS["material_subagent"]["phase"], "material_evidence_ingestion")

    def test_subagent_outputs_use_shared_harness_envelope(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        self.assertEqual(result["runtime"]["harnessOutputSchemaVersion"], HARNESS_OUTPUT_SCHEMA_VERSION)
        self.assertTrue(result["runtime"]["harnessContract"]["contractCompliant"])
        self.assertEqual(result["runtime"]["harnessContract"]["fallbackCount"], 0)
        self.assertEqual(len(result["subagentOutputs"]), 7)
        self.assertEqual(
            result["runtime"]["harnessContract"]["observedSubagents"],
            [
                "geospatial_subagent",
                "planning_subagent",
                "material_subagent",
                "hazard_subagent",
                "open_web_subagent",
                "annotation_subagent",
                "briefing_subagent",
            ],
        )
        for output in result["subagentOutputs"]:
            self.assertEqual(validate_harness_output(output, expected_group=output["subagent"]["name"]), [])
            self.assertEqual(output["schemaVersion"], HARNESS_OUTPUT_SCHEMA_VERSION)
            self.assertIsInstance(output["data"], dict)
            self.assertIsInstance(output["trace"], list)

    def test_open_web_mock_populates_external_signals_without_live_api(self):
        with EnvPatch(TAVILY_MOCK_RESPONSE="true", TAVILY_API_KEY=None):
            result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        open_web = result["externalSignals"]["openWeb"]
        self.assertEqual(open_web["status"], "ok")
        self.assertEqual(open_web["mode"], "mock")
        self.assertTrue(open_web["items"])
        self.assertFalse(result["runtime"]["liveApiCalls"])
        self.assertTrue(
            any(step["name"] == "search_open_web_signals" and step["status"] == "ok" for step in result["trace"])
        )

    def test_agentcore_harness_non_standard_output_uses_visible_contract_fallback(self):
        class FakeHarnessClient:
            def invoke_harness(self, **kwargs):
                legacy_result = {
                    "location": {"label": "Legacy Harness output"},
                    "features": [],
                    "scene": {},
                    "trace": [],
                }
                return {
                    "stream": [
                        {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
                        {
                            "contentBlockDelta": {
                                "contentBlockIndex": 0,
                                "delta": {"text": json.dumps(legacy_result)},
                            }
                        },
                    ]
                }

        with EnvPatch(RAMS_HARNESS_ARNS=json.dumps({"rams_geospatial_harness": "arn:test:geospatial"})):
            invoker = AgentCoreHarnessInvoker(
                config=RuntimeConfig.from_env(request_bedrock=False),
                client=FakeHarnessClient(),
            )
            result = invoker.invoke_geospatial({}, fixture_pack=None)

        self.assertEqual(result["schemaVersion"], HARNESS_OUTPUT_SCHEMA_VERSION)
        self.assertEqual(result["status"], "fallback")
        self.assertTrue(result["metadata"]["contractFallback"])
        self.assertTrue(result["metadata"]["contractValidationIssues"])
        self.assertTrue(
            any(
                step["name"] == "agentcore_harness_schema_fallback"
                and step["fallbackReason"] == "agentcore_harness_output_contract_invalid"
                for step in result["trace"]
            )
        )

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
        self.assertTrue(result["runtime"]["bedrockRequested"])
        self.assertTrue(result["runtime"]["bedrockEnabled"])
        self.assertTrue(result["runtime"]["bedrockUsed"])
        self.assertEqual(result["runtime"]["plannerMode"], "mocked")
        self.assertEqual(result["runtime"]["activeAgentMode"], "llm-planner-mock")
        self.assertEqual(result["runtime"]["modelCallCount"], 1)
        self.assertEqual(len(result["modelCalls"]), 1)
        self.assertEqual(result["modelCalls"][0]["phase"], "planner-plan")
        self.assertEqual(result["briefing"]["generation_mode"], "bedrock-mock")
        planner_step = next(step for step in result["trace"] if step["name"] == "plan_subagent_workflow")
        self.assertEqual(planner_step["status"], "ok")
        self.assertEqual(planner_step["output"]["plannerStatus"], "mocked")
        self.assertEqual(result["reasoning"]["mode"], "deterministic")
        bedrock_step = next(step for step in result["trace"] if step["name"] == "generate_bedrock_briefing")
        self.assertEqual(bedrock_step["status"], "ok")
        self.assertEqual(bedrock_step["output"]["modelId"], "anthropic.claude-3-7-sonnet-20250219-v1:0")
        self.assertEqual(bedrock_step["output"]["maxTokens"], 1200)
        self.assertEqual(bedrock_step["output"]["temperature"], 0.2)

    def test_bedrock_requested_failure_uses_deterministic_fallback_metadata(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_SIMULATE_FAILURE="true",
            BEDROCK_MOCK_RESPONSE=None,
        ):
            result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": True})

        self.assertEqual(result["runtime"]["briefingMode"], "fallback")
        self.assertEqual(result["runtime"]["plannerMode"], "fallback")
        self.assertEqual(result["runtime"]["activeAgentMode"], "deterministic-planner-fallback")
        self.assertFalse(result["runtime"]["bedrockUsed"])
        self.assertIn("bedrock_simulated_failure", result["runtime"]["fallbackReason"])

        planner_step = next(step for step in result["trace"] if step["name"] == "plan_subagent_workflow")
        bedrock_step = next(step for step in result["trace"] if step["name"] == "generate_bedrock_briefing")
        self.assertEqual(planner_step["status"], "fallback")
        self.assertEqual(planner_step["fallbackReason"], "bedrock_simulated_failure")
        self.assertEqual(bedrock_step["status"], "fallback")
        self.assertEqual(bedrock_step["fallbackReason"], "bedrock_simulated_failure")
        self.assertEqual(result["briefing"]["dataMode"], "cached-public-fixture")

    def test_bedrock_not_requested_ignores_simulated_failure(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_SIMULATE_FAILURE="true",
            BEDROCK_MOCK_RESPONSE=None,
        ):
            result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        self.assertEqual(result["runtime"]["briefingMode"], "disabled")
        self.assertEqual(result["runtime"]["plannerMode"], "deterministic")
        self.assertFalse(result["runtime"]["bedrockUsed"])
        self.assertFalse(any(step.get("fallbackReason") == "bedrock_simulated_failure" for step in result["trace"]))

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
        self.assertEqual(result["reviewGate"]["status"], "blocked")

    def test_independent_review_pass_path_is_visible(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False, "_reviewDecision": "pass"})

        self.assertEqual(result["draftReport"]["status"], "draft")
        self.assertEqual(result["reviewGate"]["status"], "passed")
        self.assertEqual(result["reviewGate"]["decision"], "pass")
        self.assertEqual(result["finalReportStatus"], "review_passed")
        review_step = next(step for step in result["trace"] if step["name"] == "independent_review_gate")
        self.assertEqual(review_step["output"]["decision"], "pass")

    def test_independent_review_revise_triggers_bounded_revision(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False, "_reviewDecision": "revise"})

        self.assertEqual(result["reviewGate"]["status"], "passed_with_caveats")
        self.assertEqual(result["reviewGate"]["revisionCount"], 1)
        trace_names = [step["name"] for step in result["trace"]]
        self.assertIn("supervisor_review_revision", trace_names)
        self.assertEqual(result["finalReportStatus"], "review_passed")

    def test_independent_review_block_withholds_deep_report_delivery(self):
        result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False, "_reviewDecision": "block"})

        self.assertEqual(result["reviewGate"]["status"], "blocked")
        self.assertEqual(result["finalReportStatus"], "blocked")
        self.assertEqual(result["hazards"], [])
        self.assertEqual(result["annotations"], [])

    def test_independent_review_max_revision_returns_review_required(self):
        result = run_site_briefing(
            {
                "fixturePack": "public-lambeth-thames",
                "useBedrock": False,
                "_reviewDecision": "revise_forever",
                "_reviewMaxRevisionAttempts": 1,
            }
        )

        self.assertEqual(result["reviewGate"]["status"], "review_required")
        self.assertEqual(result["reviewGate"]["revisionCount"], 1)
        self.assertEqual(result["finalReportStatus"], "review_required")
        self.assertGreaterEqual(result["reviewGate"]["attemptCount"], 2)

    def test_bedrock_requested_failure_falls_back_without_blocking_report(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_MOCK_RESPONSE=None,
            BEDROCK_SIMULATE_FAILURE="true",
            BEDROCK_MOCK_UNSAFE_RESPONSE=None,
        ):
            result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": True})

        self.assertTrue(result["runtime"]["bedrockRequested"])
        self.assertTrue(result["runtime"]["bedrockEnabled"])
        self.assertFalse(result["runtime"]["bedrockUsed"])
        self.assertEqual(result["runtime"]["briefingMode"], "fallback")
        self.assertEqual(result["runtime"]["plannerMode"], "fallback")
        self.assertEqual(result["runtime"]["activeAgentMode"], "deterministic-planner-fallback")
        self.assertTrue(result["safety"]["allowed"])
        self.assertTrue(result["annotations"])
        self.assertEqual(result["runtime"]["fallbackReason"], "bedrock_simulated_failure")
        fallback_steps = [step for step in result["trace"] if step["status"] == "fallback"]
        self.assertTrue(any(step["name"] == "plan_subagent_workflow" for step in fallback_steps))
        self.assertTrue(any(step["name"] == "generate_bedrock_briefing" for step in fallback_steps))

    def test_bedrock_not_requested_never_uses_bedrock_even_when_env_enabled(self):
        with EnvPatch(
            ENABLE_BEDROCK="true",
            BEDROCK_SIMULATE_FAILURE="true",
        ):
            result = run_site_briefing({"fixturePack": "public-lambeth-thames", "useBedrock": False})

        self.assertFalse(result["runtime"]["bedrockRequested"])
        self.assertFalse(result["runtime"]["bedrockEnabled"])
        self.assertFalse(result["runtime"]["bedrockUsed"])
        self.assertEqual(result["runtime"]["plannerMode"], "deterministic")
        self.assertEqual(result["runtime"]["briefingMode"], "disabled")


if __name__ == "__main__":
    unittest.main()
