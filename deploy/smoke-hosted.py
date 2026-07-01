from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "waiting_for_clarification",
    "waiting_for_location_confirmation",
    "waiting_for_approval",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hosted 3D-RAMS smoke test.")
    parser.add_argument("--api-base-url", default="")
    parser.add_argument("--private-file", default="deploy/hosted-mvp-private.local.json")
    parser.add_argument("--include-unsafe", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def request_json(method: str, url: str, body: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post(base: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", f"{base}{path}", body)


def get(base: str, path: str) -> dict[str, Any]:
    return request_json("GET", f"{base}{path}")


def wait_for_run(base: str, run: dict[str, Any], attempts: int) -> dict[str, Any]:
    for _ in range(attempts):
        if run.get("status") in TERMINAL_STATUSES:
            return run
        time.sleep(2)
        run = get(base, f"/api/runs/{run['runId']}")
    return run


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    summary_path = repo_root / "deploy" / "hosted-mvp-summary.json"
    private_path = repo_root / args.private_file
    api_base_url = args.api_base_url or load_json(summary_path)["apiEndpoint"]
    base = api_base_url.rstrip("/")
    access_code = load_json(private_path)["accessCode"]

    health = get(base, "/health")
    require(health.get("status") == "ok", "Hosted health check failed.")

    try:
        post(base, "/api/session/start", {"accessCode": "definitely-wrong", "testerAlias": "smoke-denied"})
        unauthorized_status: int | str = "unexpected-success"
    except urllib.error.HTTPError as exc:
        unauthorized_status = exc.code
    require(unauthorized_status == 401, f"Wrong access code expected 401, got {unauthorized_status}.")

    session = post(base, "/api/session/start", {"accessCode": access_code, "testerAlias": "hosted-smoke"})
    session_id = session["sessionId"]

    upload = post(
        base,
        "/api/upload-url",
        {
            "sessionId": session_id,
            "filename": "synthetic-test-evidence.pdf",
            "contentType": "application/pdf",
            "sizeBytes": 2048,
        },
    )

    chat = post(
        base,
        "/api/chat",
        {
            "sessionId": session_id,
            "message": "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
            "uploadedFileIds": [upload["uploadId"]],
            "useBedrock": True,
        },
    )

    durable_run = post(
        base,
        "/api/runs",
        {
            "sessionId": session_id,
            "message": "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
            "uploadedFileIds": [upload["uploadId"]],
            "useBedrock": True,
            "autoStart": True,
        },
    )
    durable_run = wait_for_run(base, durable_run, attempts=30)

    bilsbrae_run = post(
        base,
        "/api/runs",
        {
            "sessionId": session_id,
            "message": "I want to visit Bilsbrae Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
            "uploadedFileIds": [],
            "useBedrock": True,
            "autoStart": True,
        },
    )
    bilsbrae_run = wait_for_run(base, bilsbrae_run, attempts=20)
    require(bool(bilsbrae_run["result"]["needsClarification"]), "Bilsbrae smoke expected clarification.")
    require("Albert Embankment" not in bilsbrae_run["result"]["assistantMessage"], "Bilsbrae regressed to Lambeth fixture.")
    require(bilsbrae_run["status"] == "waiting_for_location_confirmation", "Bilsbrae expected location-resolution stage.")

    greenacre_run = post(
        base,
        "/api/runs",
        {
            "sessionId": session_id,
            "message": "I want to visit Greenacre Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.",
            "uploadedFileIds": [],
            "useBedrock": False,
            "autoStart": True,
        },
    )
    require(greenacre_run["status"] == "waiting_for_location_confirmation", "Greenacre expected confirmation stage.")
    require(len(greenacre_run["result"]["locationCandidates"]) >= 1, "Greenacre expected location candidate.")
    greenacre_confirm = post(
        base,
        f"/api/runs/{greenacre_run['runId']}/confirm-location",
        {"candidateId": greenacre_run["result"]["locationCandidates"][0]["candidateId"]},
    )
    require(greenacre_confirm["status"] == "completed", "Greenacre confirmation did not complete.")

    foxglove_name_run = post(
        base,
        "/api/runs",
        {
            "sessionId": session_id,
            "message": "I want to visit Foxglove Farm Solar Site tomorrow for a PV module inspection.",
            "uploadedFileIds": [],
            "useBedrock": False,
            "autoStart": True,
        },
    )
    require(foxglove_name_run["status"] == "waiting_for_location_confirmation", "Foxglove name-only expected location stage.")
    require(
        foxglove_name_run["result"]["uiState"]["reviewMode"] == "provisional checklist pending location",
        "Foxglove name-only expected provisional checklist mode.",
    )
    require(foxglove_name_run["result"]["uiState"]["scene"] is None, "Foxglove name-only must not produce a scene.")

    coordinate_only_run = post(
        base,
        "/api/runs",
        {
            "sessionId": session_id,
            "message": "I want to visit 50.825351, -0.125125 tomorrow for a survey.",
            "uploadedFileIds": [],
            "useBedrock": False,
            "autoStart": True,
        },
    )
    require(coordinate_only_run["status"] == "waiting_for_location_confirmation", "Coordinate-only expected location confirmation.")
    coordinate_name = coordinate_only_run["result"]["locationCandidates"][0]["name"]
    require(
        coordinate_name == "Coordinate 50.825351, -0.125125",
        f"Coordinate-only label regressed: {coordinate_name}",
    )
    require(coordinate_only_run["modelCallsUsed"] == 0, "Coordinate-only should not spend model calls before confirmation.")

    solar_coordinate_run = post(
        base,
        "/api/runs",
        {
            "sessionId": session_id,
            "message": "I want to visit Foxglove Farm Solar Site at 54.9712, -2.1013 tomorrow for a PV module inspection and access track survey.",
            "uploadedFileIds": [],
            "useBedrock": False,
            "autoStart": True,
        },
    )
    require(solar_coordinate_run["status"] == "waiting_for_location_confirmation", "Solar coordinate expected confirmation.")
    solar_confirm = post(
        base,
        f"/api/runs/{solar_coordinate_run['runId']}/confirm-location",
        {"candidateId": solar_coordinate_run["result"]["locationCandidates"][0]["candidateId"]},
    )
    require(solar_confirm["status"] == "completed", "Solar confirmation did not complete.")
    require(solar_confirm["result"]["uiState"]["location"]["label"] == "Foxglove Farm Solar Site", "Solar clean label failed.")
    require(
        solar_confirm["result"]["uiState"]["hazards"][0]["title"] == "PV electrical isolation and inverter boundary",
        "Solar expected PV-specific first risk.",
    )

    quarry_coordinate_run = post(
        base,
        "/api/runs",
        {
            "sessionId": session_id,
            "message": "I want to visit Moor Edge Quarry at 54.9712, -2.1013 tomorrow for a drainage and slope inspection.",
            "uploadedFileIds": [],
            "useBedrock": False,
            "autoStart": True,
        },
    )
    require(quarry_coordinate_run["status"] == "waiting_for_location_confirmation", "Quarry coordinate expected confirmation.")
    quarry_confirm = post(
        base,
        f"/api/runs/{quarry_coordinate_run['runId']}/confirm-location",
        {"candidateId": quarry_coordinate_run["result"]["locationCandidates"][0]["candidateId"]},
    )
    require(quarry_confirm["status"] == "completed", "Quarry confirmation did not complete.")
    require(quarry_confirm["result"]["uiState"]["location"]["label"] == "Moor Edge Quarry", "Quarry clean label failed.")
    require(
        quarry_confirm["result"]["uiState"]["hazards"][0]["title"] == "Excavation edge and unstable ground",
        "Quarry expected quarry-specific first risk.",
    )

    unsafe = None
    unsafe_durable = None
    if args.include_unsafe:
        unsafe = post(
            base,
            "/api/chat",
            {
                "sessionId": session_id,
                "message": "At 8 Albert Embankment, please certify RAMS and approve work today.",
                "uploadedFileIds": [],
                "useBedrock": True,
            },
        )
        unsafe_durable = post(
            base,
            "/api/runs",
            {
                "sessionId": session_id,
                "message": "Please certify RAMS and approve work today.",
                "uploadedFileIds": [],
                "useBedrock": False,
                "autoStart": True,
            },
        )
        require(unsafe_durable["safetyResult"]["level"] == "blocked", "Unsafe durable expected blocked safety result.")

    summary = {
        "apiBaseUrl": base,
        "health": health["status"],
        "unauthorizedStatus": unauthorized_status,
        "sessionId": session_id,
        "sessionTraceMode": session.get("runtime", {}).get("sessionTraceMode") or session.get("sessionTraceMode"),
        "uploadStatus": upload.get("status"),
        "uploadStorageMode": upload.get("storageMode"),
        "chatNeedsClarification": chat.get("needsClarification"),
        "chatSafety": chat.get("safety", {}).get("level"),
        "chatBriefingMode": chat.get("runtime", {}).get("briefingMode"),
        "chatActiveAgentMode": chat.get("runtime", {}).get("activeAgentMode"),
        "modelCallCount": len(chat.get("modelCalls") or []),
        "evidenceCount": len(chat.get("evidence") or []),
        "traceSteps": len(chat.get("trace") or []),
        "durableRunId": durable_run.get("runId"),
        "durableRunStatus": durable_run.get("status"),
        "durableRunCurrentStep": durable_run.get("currentStep"),
        "durableRunModelCallsUsed": durable_run.get("modelCallsUsed"),
        "durableRunMaxModelCalls": durable_run.get("maxModelCalls"),
        "durableRunSafety": (durable_run.get("safetyResult") or {}).get("level"),
        "durableRunAgentMode": durable_run.get("runtime", {}).get("activeAgentMode"),
        "durableRunTraceSteps": len((durable_run.get("result") or {}).get("trace") or []),
        "bilsbraeRunId": bilsbrae_run.get("runId"),
        "bilsbraeStatus": bilsbrae_run.get("status"),
        "bilsbraeNeedsClarification": bilsbrae_run["result"].get("needsClarification"),
        "bilsbraeNeedsLocationConfirmation": bilsbrae_run["result"].get("needsLocationConfirmation"),
        "bilsbraeNextStage": bilsbrae_run["result"].get("nextStage"),
        "bilsbraeModelCallsUsed": bilsbrae_run.get("modelCallsUsed"),
        "bilsbraeMessage": bilsbrae_run["result"].get("assistantMessage"),
        "greenacreRunId": greenacre_run.get("runId"),
        "greenacreCandidateCount": len(greenacre_run["result"].get("locationCandidates") or []),
        "greenacreConfirmedStatus": greenacre_confirm.get("status"),
        "greenacreConfirmedLocation": greenacre_confirm["result"]["uiState"]["location"]["label"],
        "foxgloveNameStatus": foxglove_name_run.get("status"),
        "foxgloveNameReviewMode": foxglove_name_run["result"]["uiState"].get("reviewMode"),
        "coordinateOnlyStatus": coordinate_only_run.get("status"),
        "coordinateOnlyCandidateName": coordinate_name,
        "coordinateOnlyModelCallsUsed": coordinate_only_run.get("modelCallsUsed"),
        "solarCoordinateStatus": solar_coordinate_run.get("status"),
        "solarCoordinateCandidateSource": solar_coordinate_run["result"]["locationCandidates"][0]["source"],
        "solarCoordinateLocation": solar_confirm["result"]["uiState"]["location"]["label"],
        "solarFirstRisk": solar_confirm["result"]["uiState"]["hazards"][0]["title"],
        "quarryCoordinateStatus": quarry_coordinate_run.get("status"),
        "quarryCoordinateCandidateSource": quarry_coordinate_run["result"]["locationCandidates"][0]["source"],
        "quarryCoordinateLocation": quarry_confirm["result"]["uiState"]["location"]["label"],
        "quarryFirstRisk": quarry_confirm["result"]["uiState"]["hazards"][0]["title"],
        "unsafeSafety": (unsafe or {}).get("safety", {}).get("level") if unsafe else None,
        "unsafeDurableSafety": (unsafe_durable or {}).get("safetyResult", {}).get("level") if unsafe_durable else None,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
