from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rams_agent_tools.tools.materials import (  # noqa: E402
    ASI_MATERIAL_API_BASE_URL_ENV,
    ASI_MATERIAL_API_BEARER_TOKEN_ENV,
    MAX_MATERIAL_BYTES,
    ingest_material_references,
)


class MaterialRetrievalTests(unittest.TestCase):
    def test_retrieval_url_success_is_sanitized(self):
        secret_url_token = "URL_SECRET_SHOULD_NOT_LEAK"
        secret_body = "RAW MATERIAL BODY SHOULD NOT LEAK"
        with patch("rams_agent_tools.tools.materials.urllib.request.urlopen") as urlopen:
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
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["acceptedReferences"][0]["status"], "retrieved")
        self.assertEqual(result["acceptedReferences"][0]["retrievalMode"], "retrieval_url")
        self.assertEqual(result["references"][0]["access"]["retrieval"], {"method": "retrieval_url", "provided": True})

        serialized = json.dumps(result)
        self.assertNotIn(secret_url_token, serialized)
        self.assertNotIn("retrievalUrl", serialized)
        self.assertNotIn(secret_body, serialized)

    def test_retrieval_url_failure_statuses_are_structured(self):
        def fake_urlopen(request, timeout):
            url = request.full_url
            if url.endswith("/denied.txt"):
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            if url.endswith("/oversize.txt"):
                return FakeResponse({"Content-Type": "text/plain", "Content-Length": str(MAX_MATERIAL_BYTES + 1)}, b"")
            if url.endswith("/unsupported.html"):
                return FakeResponse({"Content-Type": "text/html"}, b"<p>not supported</p>")
            return FakeResponse({"Content-Type": "text/plain"}, b"ok")

        with patch("rams_agent_tools.tools.materials.urllib.request.urlopen", side_effect=fake_urlopen):
            result = ingest_material_references(
                [
                    material("denied-material", "text/plain", access={"retrievalUrl": "https://materials.example.invalid/denied.txt"}),
                    material("large-material", "text/plain", access={"retrievalUrl": "https://materials.example.invalid/oversize.txt"}),
                    material("html-material", "text/plain", access={"retrievalUrl": "https://materials.example.invalid/unsupported.html"}),
                    material(
                        "expired-material",
                        "text/plain",
                        access={
                            "retrievalUrl": "https://materials.example.invalid/material.txt",
                            "expiresAt": "2000-01-01T00:00:00Z",
                        },
                    ),
                ],
                case_id="case_material_retrieval_001",
            )

        self.assertEqual(result["accepted"], 0)
        self.assertEqual({item["reason"] for item in result["skipped"]}, {"denied", "too_large", "unsupported_type", "expired"})

    def test_api_handle_not_configured_is_sanitized(self):
        handle = "ASI_HANDLE_SECRET_SHOULD_NOT_LEAK"
        with patch.dict(os.environ, {ASI_MATERIAL_API_BASE_URL_ENV: "", ASI_MATERIAL_API_BEARER_TOKEN_ENV: ""}):
            result = ingest_material_references(
                [material("api-material", "text/plain", access={"apiHandle": handle})],
                case_id="case_material_retrieval_001",
            )

        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "retrieval_not_configured")
        self.assertNotIn(handle, json.dumps(result))

    def test_api_handle_success_uses_configured_adapter(self):
        handle = "api-handle-secret"
        bearer = "ASI_BEARER_SECRET_SHOULD_NOT_LEAK"
        seen: dict[str, str] = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["authorization"] = request.headers.get("Authorization", "")
            seen["case"] = request.headers.get("X-3d-rams-case-id", "")
            return FakeResponse({"Content-Type": "text/plain"}, b"private material body")

        with patch("rams_agent_tools.tools.materials.urllib.request.urlopen", side_effect=fake_urlopen):
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
                )

        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["acceptedReferences"][0]["status"], "retrieved")
        self.assertEqual(result["acceptedReferences"][0]["retrievalMode"], "api_handle")
        self.assertEqual(seen["url"], "https://asi.example.invalid/api/materials/api-handle-secret")
        self.assertEqual(seen["authorization"], f"Bearer {bearer}")
        self.assertEqual(seen["case"], "case_material_retrieval_001")

        serialized = json.dumps(result)
        self.assertNotIn(handle, serialized)
        self.assertNotIn(bearer, serialized)
        self.assertNotIn("private material body", serialized)


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
