from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rams_agent_tools.config import RuntimeConfig  # noqa: E402
from rams_agent_tools.tools.materials import (  # noqa: E402
    ASI_MATERIAL_API_BASE_URL_ENV,
    ASI_MATERIAL_API_BEARER_TOKEN_ENV,
    ingest_material_references,
)


class MaterialRetrievalTests(unittest.TestCase):
    def test_retrieval_url_extracts_without_secret_leakage(self):
        secret_url_token = "URL_SECRET_SHOULD_NOT_LEAK"
        secret_body = "Access route uses public realm. RAW MATERIAL BODY SHOULD NOT LEAK"
        with mock_bedrock_env(), patch("rams_agent_tools.tools.materials.urllib.request.urlopen") as urlopen:
            urlopen.return_value = FakeResponse({"Content-Type": "text/plain"}, secret_body.encode())
            result = ingest_material_references(
                [
                    material(
                        "url-material",
                        "text/plain",
                        access={"retrievalUrl": f"https://materials.example.invalid/material.txt?token={secret_url_token}"},
                    )
                ],
                case_id="case_material_retrieval_001",
                config=RuntimeConfig.from_env(request_bedrock=True),
            )

        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["acceptedReferences"][0]["retrievalMode"], "bedrock-material-extraction")
        self.assertEqual(result["extractions"][0]["retrieval"]["mode"], "retrieval_url")

        serialized = json.dumps(result)
        self.assertNotIn(secret_url_token, serialized)
        self.assertNotIn("retrievalUrl", serialized)
        self.assertNotIn(secret_body, serialized)

    def test_api_handle_uses_configured_adapter_without_secret_leakage(self):
        handle = "api-handle-secret"
        bearer = "ASI_BEARER_SECRET_SHOULD_NOT_LEAK"
        seen: dict[str, str] = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["authorization"] = request.headers.get("Authorization", "")
            seen["case"] = request.headers.get("X-3d-rams-case-id", "")
            return FakeResponse({"Content-Type": "text/plain"}, b"access route note")

        with mock_bedrock_env(), patch("rams_agent_tools.tools.materials.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch.dict(
                os.environ,
                {
                    ASI_MATERIAL_API_BASE_URL_ENV: "https://asi.example.invalid/api/materials",
                    ASI_MATERIAL_API_BEARER_TOKEN_ENV: bearer,
                },
            ):
                result = ingest_material_references(
                    [material("api-material", "text/plain", access={"apiHandle": handle})],
                    case_id="case_material_retrieval_001",
                    config=RuntimeConfig.from_env(request_bedrock=True),
                )

        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["extractions"][0]["retrieval"]["mode"], "api_handle")
        self.assertEqual(seen["url"], "https://asi.example.invalid/api/materials/api-handle-secret")
        self.assertEqual(seen["authorization"], f"Bearer {bearer}")
        self.assertEqual(seen["case"], "case_material_retrieval_001")

        serialized = json.dumps(result)
        self.assertNotIn(handle, serialized)
        self.assertNotIn(bearer, serialized)


def mock_bedrock_env():
    return patch.dict(os.environ, {"ENABLE_BEDROCK": "true", "BEDROCK_MOCK_RESPONSE": "true", "MATERIAL_EXTRACTION_MODEL_ID": "amazon.nova-lite-v1:0"})


def material(material_id: str, material_type: str, *, access: dict[str, str]) -> dict:
    return {
        "materialId": material_id,
        "sourceSystem": "asio",
        "type": material_type,
        "label": material_id,
        "caseId": "case_material_retrieval_001",
        "sizeBytes": 128,
        "access": {
            "mode": "asio_authorized_reference",
            "expiresAt": access.pop("expiresAt", "2099-01-01T00:00:00Z"),
            "sessionId": "asi-session-001",
            **access,
        },
    }


class FakeResponse:
    def __init__(self, headers: dict[str, str], body: bytes) -> None:
        self.headers = headers
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int) -> bytes:
        return self.body[:size]


if __name__ == "__main__":
    unittest.main()
