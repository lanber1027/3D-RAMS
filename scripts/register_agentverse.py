#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


AGENT_NAME = "3d-rams"
ENV_FILE = ".env.agentverse"


def load_local_env(path: str = ENV_FILE) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name and name not in os.environ:
                os.environ[name] = value


def require_python_310() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ is required for AgentVerse registration.")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    require_python_310()
    load_local_env()
    agentverse_key = require_env("AGENTVERSE_KEY")
    seed_phrase = require_env("AGENT_SEED_PHRASE")
    endpoint_url = require_env("AGENT_ENDPOINT_URL")

    try:
        from uagents_core.utils.registration import (
            RegistrationRequestCredentials,
            register_chat_agent,
        )
    except ImportError as exc:
        raise SystemExit("Missing dependency: uagents_core. Install uagents-core in the Python environment.") from exc

    register_chat_agent(
        AGENT_NAME,
        endpoint_url,
        active=True,
        credentials=RegistrationRequestCredentials(
            agentverse_api_key=agentverse_key,
            agent_seed_phrase=seed_phrase,
        ),
    )
    print(f"Registered {AGENT_NAME} with AgentVerse.")


if __name__ == "__main__":
    main()
