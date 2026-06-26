from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(name: str) -> str:
    with (FIXTURES / name).open("r", encoding="utf-8") as handle:
        return handle.read()

