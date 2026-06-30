from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agentcore_client import invoke_runtime_json


class FrontendProxyHandler(BaseHTTPRequestHandler):
    server_version = "3DRAMSAgentCoreProxy/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        self._send_json({"ok": True}, status=204)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path.rstrip("/") == "/health":
            self._send_json({"status": "ok", "service": "3d-rams-agentcore-proxy"})
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path.rstrip("/") not in {"", "/invoke"}:
            self._send_json({"error": "not_found"}, status=404)
            return
        try:
            payload = self._read_json()
            runtime_arn = os.environ["AGENTCORE_RUNTIME_ARN"]
            conversation_id = str(payload.get("conversationId") or payload.get("sessionId") or "frontend-demo-session")
            response = invoke_runtime_json(
                runtime_arn=runtime_arn,
                payload=payload,
                session_id=conversation_id,
                user_id="3d-rams-frontend",
                timeout=int(os.getenv("AGENTCORE_PROXY_TIMEOUT", "120")),
            )
            self._send_json(response)
        except Exception as exc:  # noqa: BLE001 - user-facing local proxy error.
            self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=502)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("Proxy payload must be a JSON object.")
        return parsed

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("access-control-allow-origin", os.getenv("AGENTCORE_PROXY_ALLOWED_ORIGIN", "*"))
        self.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
        self.send_header("access-control-allow-headers", "content-type,authorization")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if status != 204:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        if os.getenv("AGENTCORE_PROXY_LOGS", "false").lower() in {"1", "true", "yes", "on"}:
            super().log_message(format, *args)


def run() -> None:
    host = os.getenv("AGENTCORE_PROXY_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("AGENTCORE_PROXY_PORT", "8787")))
    server = ThreadingHTTPServer((host, port), FrontendProxyHandler)
    print(f"3D-RAMS AgentCore frontend proxy listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
