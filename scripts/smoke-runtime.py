from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
HARNESS_OUTPUT_SCHEMA_VERSION = "3d-rams.harness-output.v1"


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


def _start_agentcore(api_port: int) -> subprocess.Popen:
    env = {
        **os.environ,
        "ENABLE_BEDROCK": "false",
        "BEDROCK_MOCK_RESPONSE": "false",
        "BEDROCK_SIMULATE_FAILURE": "false",
        "PYTHONUNBUFFERED": "1",
    }
    return subprocess.Popen(
        [
            "agentcore",
            "dev",
            "--runtime",
            "rams_supervisor_runtime",
            "--skip-deploy",
            "--no-browser",
            "--no-traces",
            "--logs",
            "--port",
            str(api_port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=os.name != "nt",
    )


def _start_local_runtime(api_port: int) -> subprocess.Popen:
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
            str(Path(__file__).resolve()),
            "--serve-runtime",
            "--api-port",
            str(api_port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=os.name != "nt",
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
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=8)


def _stop_repo_orphans() -> None:
    if os.name == "nt":
        return
    patterns = [
        str(ROOT / "app" / "rams_supervisor_runtime" / ".venv" / "bin" / "uvicorn main:app"),
        str(ROOT / "frontend" / "node_modules" / ".bin" / "vite"),
    ]
    for pattern in patterns:
        try:
            output = subprocess.check_output(["pgrep", "-f", pattern], text=True)
        except subprocess.CalledProcessError:
            continue
        for line in output.splitlines():
            try:
                os.kill(int(line), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


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
        raise AssertionError(f"/invocations output.run missing keys: {missing}")
    if not result["evidence"]:
        raise AssertionError("/invocations returned no evidence entries")
    if not result["trace"]:
        raise AssertionError("/invocations returned no trace entries")
    if result["runtime"].get("briefingMode") not in {"disabled", "fallback", "real", "mocked"}:
        raise AssertionError(f"unexpected briefingMode: {result['runtime'].get('briefingMode')}")
    if result["safety"].get("allowed") is not True:
        raise AssertionError("default no-AWS smoke request should remain inside the safety boundary")
    contract = result["runtime"].get("harnessContract") or {}
    if result["runtime"].get("harnessOutputSchemaVersion") != HARNESS_OUTPUT_SCHEMA_VERSION:
        raise AssertionError("runtime missing Harness output schema version")
    if contract.get("contractCompliant") is not True:
        raise AssertionError(f"Harness output contract fallback was used: {contract.get('issues')}")
    subagent_outputs = result.get("subagentOutputs") or []
    if len(subagent_outputs) < 7:
        raise AssertionError(f"expected seven Harness subagent outputs; saw {len(subagent_outputs)}")
    for output in subagent_outputs:
        if output.get("schemaVersion") != HARNESS_OUTPUT_SCHEMA_VERSION:
            raise AssertionError(f"non-compliant Harness output from {output.get('subagent')}")


def _serve_runtime(api_port: int) -> int:
    runtime_root = ROOT / "app" / "rams_supervisor_runtime"
    tools_root = ROOT / "app" / "rams_agent_tools"
    for path in (tools_root, runtime_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    from main import invoke_local, ping_local

    class RuntimeHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path.split("?", 1)[0] != "/ping":
                self._send_json(404, {"error": "not_found"})
                return
            self._send_json(200, ping_local())

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            if self.path.split("?", 1)[0] != "/invocations":
                self._send_json(404, {"error": "not_found"})
                return
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(body)
                response = invoke_local(payload)
            except Exception as exc:  # noqa: BLE001 - smoke server should surface runtime errors as JSON.
                self._send_json(500, {"error": exc.__class__.__name__, "message": str(exc)})
                return
            self._send_json(200, response)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - http.server API
            return

    server = ThreadingHTTPServer(("127.0.0.1", api_port), RuntimeHandler)
    print(f"3D-RAMS local runtime smoke server listening on http://127.0.0.1:{api_port}", flush=True)
    server.serve_forever()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a no-AWS HTTP smoke test against AgentCore and frontend runtime servers.")
    parser.add_argument("--api-port", type=int, default=int(os.getenv("RAMS_SMOKE_API_PORT", "8765")))
    parser.add_argument("--frontend-port", type=int, default=int(os.getenv("RAMS_SMOKE_FRONTEND_PORT", "8766")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("RAMS_SMOKE_TIMEOUT", "45")))
    parser.add_argument("--serve-runtime", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.serve_runtime:
        return _serve_runtime(args.api_port)

    if not (FRONTEND / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist is missing. Run `npm run build` before smoke-runtime.")

    agentcore: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None
    runtime_server = "agentcore-cli"
    api_base = f"http://127.0.0.1:{args.api_port}"
    frontend_base = f"http://127.0.0.1:{args.frontend_port}"

    try:
        runtime_mode = os.getenv("RAMS_SMOKE_RUNTIME_MODE", "auto").strip().lower()
        if runtime_mode == "local-http":
            runtime_server = "local-http"
            agentcore = _start_local_runtime(args.api_port)
            _wait_for("local runtime", lambda: _request_json(f"{api_base}/ping"), args.timeout)
        else:
            agentcore = _start_agentcore(args.api_port)
            try:
                _wait_for("AgentCore", lambda: _request_json(f"{api_base}/ping"), args.timeout)
            except RuntimeError:
                _stop_process(agentcore)
                agentcore_output = _tail_output(agentcore)
                if runtime_mode == "agentcore":
                    raise RuntimeError(f"AgentCore CLI failed and fallback is disabled. Output: {agentcore_output}")
                runtime_server = "local-http-fallback"
                agentcore = _start_local_runtime(args.api_port)
                _wait_for("local runtime fallback", lambda: _request_json(f"{api_base}/ping"), args.timeout)

        frontend = _start_frontend(args.frontend_port)
        _wait_for("frontend", lambda: _request_text(frontend_base), args.timeout)

        health = _request_json(f"{api_base}/ping")
        if health.get("status") not in {"Healthy", "ok"}:
            raise AssertionError(f"unexpected health response: {health}")

        invocation = _request_json(
            f"{api_base}/invocations",
            {
                "input": {
                    "fixturePack": "public-lambeth-thames",
                    "includePlanningFixture": True,
                    "simulateMapFailure": False,
                    "useBedrock": False,
                }
            },
        )
        result = invocation["output"]["run"]
        _validate_agent_response(result)

        frontend_html = _request_text(frontend_base)
        if "3D-RAMS Demo1" not in frontend_html or 'id="root"' not in frontend_html:
            raise AssertionError("frontend preview did not serve the expected app shell")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "runtimeServer": runtime_server,
                    "agentcore": health,
                    "frontend": {"served": True, "port": args.frontend_port},
                    "agent": {
                        "briefingMode": result["runtime"]["briefingMode"],
                        "traceSteps": len(result["trace"]),
                        "evidenceItems": len(result["evidence"]),
                        "safety": result["safety"]["level"],
                        "harnessContract": result["runtime"]["harnessContract"]["contractCompliant"],
                    },
                },
                indent=2,
            )
        )
        return 0
    except (urllib.error.URLError, RuntimeError, AssertionError) as exc:
        print(f"Runtime smoke failed: {exc}", file=sys.stderr)
        _stop_process(frontend)
        _stop_process(agentcore)
        print("AgentCore output:", _tail_output(agentcore), file=sys.stderr)
        print("Frontend output:", _tail_output(frontend), file=sys.stderr)
        return 1
    finally:
        _stop_process(frontend)
        _stop_process(agentcore)
        _stop_repo_orphans()


if __name__ == "__main__":
    raise SystemExit(main())
