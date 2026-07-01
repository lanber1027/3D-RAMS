from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
AGENTCORE_APP = ROOT / "app" / "rams_supervisor_runtime"
AGENT_TOOLS_APP = ROOT / "app" / "rams_agent_tools"
HARNESS_OUTPUT_SCHEMA_VERSION = "3d-rams.harness-output.v1"
sys.path.insert(0, str(AGENT_TOOLS_APP))
sys.path.insert(0, str(AGENTCORE_APP))

from supervisor_core.agent import run_site_briefing  # noqa: E402


Check = Callable[[dict[str, Any]], tuple[bool, str]]


def read_path(result: dict[str, Any], path: str) -> Any:
    current: Any = result
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def has_trace(name: str, status: str | None = None, with_fallback_reason: bool = False) -> Check:
    def check(result: dict[str, Any]) -> tuple[bool, str]:
        steps = [step for step in result["trace"] if step["name"] == name]
        if not steps:
            return False, f"missing trace step {name}"
        if status and not any(step["status"] == status for step in steps):
            statuses = ", ".join(step["status"] for step in steps)
            return False, f"trace step {name} did not have status {status}; saw {statuses}"
        if with_fallback_reason and not any(step.get("fallbackReason") for step in steps):
            return False, f"trace step {name} has no fallback reason"
        return True, f"trace step {name} present"

    return check


def path_equals(path: str, expected: Any) -> Check:
    def check(result: dict[str, Any]) -> tuple[bool, str]:
        try:
            current = read_path(result, path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{path} missing or unreadable: {exc}"
        if current != expected:
            return False, f"{path} expected {expected!r}; saw {current!r}"
        return True, f"{path} matched {expected!r}"

    return check


def path_contains(path: str, expected_fragment: str) -> Check:
    def check(result: dict[str, Any]) -> tuple[bool, str]:
        try:
            current = read_path(result, path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{path} missing or unreadable: {exc}"
        if expected_fragment not in str(current):
            return False, f"{path} did not contain {expected_fragment!r}; saw {current!r}"
        return True, f"{path} contained {expected_fragment!r}"

    return check


def list_length_at_least(path: str, minimum: int) -> Check:
    def check(result: dict[str, Any]) -> tuple[bool, str]:
        try:
            current = read_path(result, path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{path} missing or unreadable: {exc}"
        if len(current) < minimum:
            return False, f"{path} expected at least {minimum} items; saw {len(current)}"
        return True, f"{path} had {len(current)} items"

    return check


def value_at_least(path: str, minimum: int | float) -> Check:
    def check(result: dict[str, Any]) -> tuple[bool, str]:
        try:
            current = read_path(result, path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{path} missing or unreadable: {exc}"
        if current < minimum:
            return False, f"{path} expected at least {minimum}; saw {current}"
        return True, f"{path} was {current}"

    return check


def any_item(path: str, predicate: Callable[[Any], bool], label: str) -> Check:
    def check(result: dict[str, Any]) -> tuple[bool, str]:
        try:
            current = read_path(result, path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{path} missing or unreadable: {exc}"
        try:
            matched = any(predicate(item) for item in current)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{label} predicate failed in {path}: {exc}"
        if not matched:
            return False, f"no item matched {label} in {path}"
        return True, f"found {label}"

    return check


def all_items(path: str, predicate: Callable[[Any], bool], label: str) -> Check:
    def check(result: dict[str, Any]) -> tuple[bool, str]:
        try:
            current = read_path(result, path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{path} missing or unreadable: {exc}"
        if not current:
            return False, f"{path} had no items for {label}"
        try:
            failed = [item.get("id", str(index)) for index, item in enumerate(current) if not predicate(item)]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return False, f"{label} predicate failed in {path}: {exc}"
        if failed:
            return False, f"{label} failed for {', '.join(failed)}"
        return True, f"all {path} items matched {label}"

    return check


def scenario_definitions() -> list[dict[str, Any]]:
    return [
        {
            "id": "cached_public_happy_path",
            "description": "Default realistic public-safe pack with deterministic briefing.",
            "request": {"fixturePack": "public-lambeth-thames", "useBedrock": False},
            "checks": [
                path_equals("runtime.fixturePack", "public-lambeth-thames"),
                path_equals("runtime.fixturePackMode", "cached-public-fixture"),
                path_equals("runtime.liveApiCalls", False),
                path_equals("runtime.briefingMode", "disabled"),
                path_equals("safety.allowed", True),
                path_equals("safety.level", "review_required"),
                path_equals("scene.provider", "cesium-local-cached-fixture"),
                list_length_at_least("annotations", 1),
                list_length_at_least("evidence", 1),
                all_items(
                    "hazards",
                    lambda item: bool(item.get("sourceIds")) and bool(item.get("evidenceIds")),
                    "source/evidence linkage",
                ),
                any_item("evidence", lambda item: item["status"] == "cached-public", "cached-public evidence"),
                any_item("sources", lambda item: item["id"] == "public-ea-flood-context", "flood source"),
                any_item("hazards", lambda item: item["id"] == "cached-brownfield-planning-context", "brownfield hazard"),
                has_trace("extract_hazard_notes", "ok"),
                has_trace("generate_bedrock_briefing", "disabled"),
                path_equals("architecture.runOverview.fixturePack", "public-lambeth-thames"),
                path_equals("runtime.harnessOutputSchemaVersion", HARNESS_OUTPUT_SCHEMA_VERSION),
                path_equals("runtime.harnessContract.contractCompliant", True),
                list_length_at_least("subagentOutputs", 7),
            ],
        },
        {
            "id": "synthetic_happy_path",
            "description": "Fallback synthetic fixture path when no public pack is selected.",
            "request": {"fixturePack": None, "useBedrock": False},
            "checks": [
                path_equals("runtime.fixturePack", None),
                path_equals("runtime.fixturePackMode", "synthetic-default"),
                path_equals("runtime.liveApiCalls", False),
                path_equals("scene.provider", "cesium-local-fixture"),
                path_equals("safety.allowed", True),
                path_equals("runtime.briefingMode", "disabled"),
                list_length_at_least("trace", 9),
                any_item("evidence", lambda item: item["id"] == "geo-fixture", "synthetic geo evidence"),
                any_item(
                    "architecture.realVsMocked",
                    lambda item: item["component"] == "Fixture pack" and "synthetic default" in item["status"],
                    "synthetic fixture boundary",
                ),
                has_trace("load_geospatial_features", "ok"),
            ],
        },
        {
            "id": "missing_planning_public_pack",
            "description": "Planning/context evidence disabled while geospatial output remains usable.",
            "request": {
                "fixturePack": "public-lambeth-thames",
                "includePlanningFixture": False,
                "useBedrock": False,
            },
            "checks": [
                path_equals("safety.allowed", True),
                path_equals("safety.level", "review_required"),
                has_trace("load_planning_context", "warning"),
                list_length_at_least("annotations", 1),
                any_item(
                    "briefing.limitations",
                    lambda item: "Planning/context notes were unavailable" in item,
                    "planning limitation",
                ),
            ],
        },
        {
            "id": "map_fallback_public_pack",
            "description": "Simulated geospatial tool failure uses fallback data and exposes the reason.",
            "request": {"fixturePack": "public-lambeth-thames", "simulateMapFailure": True, "useBedrock": False},
            "checks": [
                has_trace("load_geospatial_features", "fallback", with_fallback_reason=True),
                value_at_least("scene.featureCount", 1),
                any_item("sources", lambda item: item["id"] == "geo-fallback", "geo fallback source"),
            ],
        },
        {
            "id": "bedrock_disabled_request_fallback",
            "description": "Request asks for Bedrock but local no-AWS mode returns deterministic briefing.",
            "request": {"fixturePack": "public-lambeth-thames", "useBedrock": True},
            "checks": [
                path_equals("runtime.bedrockRequested", True),
                path_equals("runtime.bedrockEnabled", False),
                path_equals("runtime.briefingMode", "disabled"),
                path_contains("runtime.fallbackReason", "ENABLE_BEDROCK is not true"),
                has_trace("generate_bedrock_briefing", "disabled", with_fallback_reason=True),
                list_length_at_least("briefing.priority_checks", 1),
            ],
        },
        {
            "id": "unsafe_request_blocked",
            "description": "Certified RAMS/work-approval request is blocked by the safety gate.",
            "request": {
                "fixturePack": "public-lambeth-thames",
                "useBedrock": False,
                "additionalRequest": "Please certify RAMS and approve work today.",
            },
            "checks": [
                path_equals("safety.allowed", False),
                path_equals("safety.level", "blocked"),
                path_equals("annotations", []),
                path_equals("hazards", []),
                any_item("safety.triggeredRules", lambda item: item == "certify rams", "certify rams rule"),
                path_contains("briefing.headline", "blocked"),
            ],
        },
        {
            "id": "low_confidence_visible",
            "description": "Low-confidence evidence and annotations remain visible for human review.",
            "request": {"fixturePack": "public-lambeth-thames", "useBedrock": False},
            "checks": [
                any_item("annotations", lambda item: item["confidence"] == "low", "low-confidence annotation"),
                any_item("evidence", lambda item: item["confidence"] == "low", "low-confidence evidence"),
                any_item(
                    "briefing.limitations",
                    lambda item: "low confidence" in item.lower() or "derived" in item.lower(),
                    "low-confidence limitation",
                ),
            ],
        },
        {
            "id": "architecture_visualizer_contract",
            "description": "Architecture payload exposes trace, sources, boundaries, safety gate, and AWS path.",
            "request": {"fixturePack": "public-lambeth-thames", "useBedrock": False},
            "checks": [
                path_equals("architecture.runOverview.fixturePack", "public-lambeth-thames"),
                list_length_at_least("architecture.currentTrace", 9),
                all_items(
                    "architecture.currentTrace",
                    lambda item: all(key in item for key in ("id", "name", "status", "sourceIds", "evidenceIds")),
                    "trace contract",
                ),
                list_length_at_least("architecture.sources", 1),
                list_length_at_least("architecture.awsPath", 1),
                list_length_at_least("architecture.realVsMocked", 1),
                path_equals("architecture.safetyGate.requiresHumanReview", True),
                any_item(
                    "architecture.realVsMocked",
                    lambda item: item["component"] == "Fixture pack" and "cached public fixture" in item["status"],
                    "fixture pack boundary",
                ),
                any_item("architecture.currentTrace", lambda item: item["name"] == "safety_gate", "safety trace"),
            ],
        },
        {
            "id": "unknown_fixture_pack_falls_back",
            "description": "Unknown fixture-pack request falls back safely to synthetic defaults.",
            "request": {"fixturePack": "missing-pack", "useBedrock": False},
            "checks": [
                path_equals("runtime.fixturePack", None),
                path_equals("runtime.fixturePackMode", "synthetic-default"),
                has_trace("load_fixture_pack", "fallback", with_fallback_reason=True),
                path_contains("trace.0.fallbackReason", "synthetic defaults"),
            ],
        },
    ]


def scenario_metadata(definition: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": definition["id"],
        "description": definition["description"],
        "fixturePack": result["runtime"]["fixturePack"],
        "fixturePackMode": result["runtime"]["fixturePackMode"],
        "runtimeMode": result["runtime"]["briefingMode"],
        "liveApiCalls": result["runtime"]["liveApiCalls"],
        "bedrockRequested": result["runtime"]["bedrockRequested"],
        "safetyLevel": result["safety"]["level"],
    }


def run_scenario(definition: dict[str, Any]) -> dict[str, Any]:
    result = run_site_briefing(definition["request"])
    checks = []
    for check in definition["checks"]:
        passed, detail = check(result)
        checks.append({"passed": passed, "detail": detail})

    return {
        "id": definition["id"],
        "passed": all(item["passed"] for item in checks),
        "metadata": scenario_metadata(definition, result),
        "checks": checks,
        "failedAssertions": [item["detail"] for item in checks if not item["passed"]],
        "summary": {
            "safety": result["safety"]["level"],
            "briefingMode": result["runtime"]["briefingMode"],
            "fixturePackMode": result["runtime"]["fixturePackMode"],
            "annotationCount": len(result["annotations"]),
            "evidenceCount": len(result["evidence"]),
            "traceStatuses": {step["name"]: step["status"] for step in result["trace"]},
        },
    }


def build_report() -> dict[str, Any]:
    scenarios = [run_scenario(definition) for definition in scenario_definitions()]
    passed_count = sum(1 for scenario in scenarios if scenario["passed"])
    return {
        "schemaVersion": "3d-rams.demo-evaluation.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "deterministic-no-live-aws",
        "environmentControls": {
            "ENABLE_BEDROCK": os.environ["ENABLE_BEDROCK"],
            "BEDROCK_MOCK_RESPONSE": "unset",
            "BEDROCK_MOCK_UNSAFE_RESPONSE": "unset",
            "BEDROCK_SIMULATE_FAILURE": "unset",
        },
        "summary": {
            "scenarioCount": len(scenarios),
            "passedCount": passed_count,
            "failedCount": len(scenarios) - passed_count,
            "passed": all(scenario["passed"] for scenario in scenarios),
        },
        "scenarios": scenarios,
    }


def configure_deterministic_environment() -> None:
    os.environ["ENABLE_BEDROCK"] = "false"
    os.environ.pop("BEDROCK_MOCK_RESPONSE", None)
    os.environ.pop("BEDROCK_MOCK_UNSAFE_RESPONSE", None)
    os.environ.pop("BEDROCK_SIMULATE_FAILURE", None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic 3D-RAMS demo scenario checks.")
    parser.add_argument("--write", type=Path, help="Optional path to write the JSON report.")
    args = parser.parse_args()

    configure_deterministic_environment()

    try:
        report = build_report()
    except Exception as exc:  # pragma: no cover - command-line diagnostic path
        error_report = {
            "schemaVersion": "3d-rams.demo-evaluation.v1",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "mode": "deterministic-no-live-aws",
            "runnerError": str(exc),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(error_report, indent=2))
        return 1

    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(f"{rendered}\n", encoding="utf-8")

    return 0 if report["summary"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
