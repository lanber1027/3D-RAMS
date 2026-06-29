from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _request_json(url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return response.read().decode("utf-8", errors="replace")


def _wait_for(label: str, check, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            check()
            return
        except Exception as exc:  # noqa: BLE001 - surface the last startup error below.
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready within {timeout_seconds}s: {last_error}")


def _start_backend(api_port: int) -> subprocess.Popen:
    env = {
        **os.environ,
        "ENABLE_BEDROCK": "false",
        "BEDROCK_MOCK_RESPONSE": "false",
        "BEDROCK_SIMULATE_FAILURE": "false",
        "PYTHONUNBUFFERED": "1",
    }
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _start_frontend(frontend_port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            _npm_command(),
            "run",
            "preview",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(frontend_port),
        ],
        cwd=FRONTEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def _tail_output(process: subprocess.Popen | None) -> str:
    if process is None or process.stdout is None:
        return ""
    try:
        return process.stdout.read()[-3000:]
    except Exception:  # noqa: BLE001 - diagnostics only.
        return ""


def _validate_agent_response(result: dict) -> None:
    required = ["scene", "briefing", "evidence", "trace", "architecture", "safety", "runtime"]
    missing = [key for key in required if key not in result]
    if missing:
        raise AssertionError(f"/api/run response missing keys: {missing}")
    if not result["evidence"]:
        raise AssertionError("/api/run returned no evidence entries")
    if not result["trace"]:
        raise AssertionError("/api/run returned no trace entries")
    if result["runtime"].get("briefingMode") not in {"deterministic", "disabled", "fallback", "real", "mocked"}:
        raise AssertionError(f"unexpected briefingMode: {result['runtime'].get('briefingMode')}")
    if result["safety"].get("allowed") is not True:
        raise AssertionError("default no-AWS smoke request should remain inside the safety boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a no-AWS HTTP smoke test against backend and frontend runtime servers.")
    parser.add_argument("--api-port", type=int, default=int(os.getenv("RAMS_SMOKE_API_PORT", "8765")))
    parser.add_argument("--frontend-port", type=int, default=int(os.getenv("RAMS_SMOKE_FRONTEND_PORT", "8766")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("RAMS_SMOKE_TIMEOUT", "45")))
    args = parser.parse_args()

    if not (FRONTEND / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist is missing. Run `npm run build` before smoke-runtime.")

    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None
    api_base = f"http://127.0.0.1:{args.api_port}"
    frontend_base = f"http://127.0.0.1:{args.frontend_port}"

    try:
        backend = _start_backend(args.api_port)
        _wait_for("backend", lambda: _request_json(f"{api_base}/health"), args.timeout)

        frontend = _start_frontend(args.frontend_port)
        _wait_for("frontend", lambda: _request_text(frontend_base), args.timeout)

        health = _request_json(f"{api_base}/health")
        if health != {"status": "ok", "service": "3d-rams-demo1"}:
            raise AssertionError(f"unexpected health response: {health}")

        result = _request_json(
            f"{api_base}/api/run",
            {
                "fixturePack": "public-lambeth-thames",
                "includePlanningFixture": True,
                "simulateMapFailure": False,
                "useBedrock": False,
            },
        )
        _validate_agent_response(result)

        frontend_html = _request_text(frontend_base)
        if "3D-RAMS Demo1" not in frontend_html or 'id="root"' not in frontend_html:
            raise AssertionError("frontend preview did not serve the expected app shell")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "backend": health,
                    "frontend": {"served": True, "port": args.frontend_port},
                    "agent": {
                        "briefingMode": result["runtime"]["briefingMode"],
                        "traceSteps": len(result["trace"]),
                        "evidenceItems": len(result["evidence"]),
                        "safety": result["safety"]["level"],
                    },
                },
                indent=2,
            )
        )
        return 0
    except (urllib.error.URLError, RuntimeError, AssertionError) as exc:
        print(f"Runtime smoke failed: {exc}", file=sys.stderr)
        _stop_process(frontend)
        _stop_process(backend)
        print("Backend output:", _tail_output(backend), file=sys.stderr)
        print("Frontend output:", _tail_output(frontend), file=sys.stderr)
        return 1
    finally:
        _stop_process(frontend)
        _stop_process(backend)


if __name__ == "__main__":
    raise SystemExit(main())
