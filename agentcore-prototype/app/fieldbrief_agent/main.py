from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import RuntimeConfig  # noqa: E402
from backend.app.conversation_router import handle_conversation_message  # noqa: E402
from backend.app.session_store import create_session  # noqa: E402


def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    """AgentCore prototype invoke function.

    This function intentionally mirrors the hosted conversation contract while
    keeping the current MVP's guards and app-layer memory intact. It is a
    sidecar prototype entrypoint, not the active hosted API path.
    """
    os.environ.setdefault("DURABLE_RUN_PROCESS_INLINE", "true")
    config = RuntimeConfig.from_env(request_bedrock=bool(payload.get("useBedrock", True)))
    session_id = payload.get("sessionId")
    if not session_id:
        session = create_session(
            tester_alias=payload.get("testerAlias") or "agentcore-prototype",
            access_label="agentcore-prototype",
            config=config,
        )
        session_id = session["sessionId"]
    return handle_conversation_message(
        session_id=session_id,
        message=str(payload.get("message") or "What can 3D-RAMS do?"),
        uploaded_file_ids=list(payload.get("uploadedFileIds") or []),
        use_bedrock=bool(payload.get("useBedrock", True)),
        config=config,
    )


def main() -> None:
    """Local stdin/stdout harness for prototype smoke checks."""
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    print(json.dumps(invoke(payload), indent=2))


if __name__ == "__main__":
    os.environ.setdefault("ENABLE_BEDROCK", "false")
    main()
