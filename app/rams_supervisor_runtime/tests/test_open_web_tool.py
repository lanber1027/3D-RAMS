from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rams_agent_tools.tools.open_web import search_open_web_signals  # noqa: E402


class EnvPatch:
    def __init__(self, **updates: str | None):
        self.updates = updates
        self.previous: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self.updates.items():
            self.previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeTavilyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class OpenWebToolTests(unittest.TestCase):
    def test_disabled_mode_returns_clear_empty_signal_payload(self):
        with EnvPatch(ENABLE_TAVILY="false", TAVILY_API_KEY=None, TAVILY_MOCK_RESPONSE=None):
            open_web, trace = search_open_web_signals(
                {"label": "48 Quernmore Road", "authority": "London"},
                {"goal": "confined workspace review"},
                {"type": "radius", "meters": 25},
                now=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )

        self.assertEqual(open_web["status"], "disabled")
        self.assertEqual(open_web["provider"], "tavily")
        self.assertEqual(open_web["items"], [])
        self.assertEqual(open_web["sourceBoundary"], "non_authoritative_signal")
        self.assertFalse(open_web["liveCallAttempted"])
        self.assertEqual(trace["status"], "disabled")

    def test_enabled_without_key_is_not_configured_without_live_call(self):
        with EnvPatch(ENABLE_TAVILY="true", TAVILY_API_KEY=None, TAVILY_MOCK_RESPONSE=None):
            open_web, trace = search_open_web_signals(
                {"label": "48 Quernmore Road"},
                {"goal": "site review"},
                {"type": "radius", "meters": 25},
            )

        self.assertEqual(open_web["status"], "not_configured")
        self.assertFalse(open_web["liveCallAttempted"])
        self.assertEqual(trace["status"], "disabled")

    def test_mock_mode_returns_bounded_non_authoritative_items(self):
        with EnvPatch(TAVILY_MOCK_RESPONSE="true", TAVILY_API_KEY=None):
            open_web, trace = search_open_web_signals(
                {"label": "48 Quernmore Road"},
                {"goal": "site review"},
                {"type": "radius", "meters": 25},
                max_results=1,
            )

        self.assertEqual(open_web["status"], "ok")
        self.assertEqual(open_web["mode"], "mock")
        self.assertEqual(len(open_web["items"]), 1)
        self.assertEqual(open_web["items"][0]["sourceBoundary"], "non_authoritative_signal")
        self.assertIn("unverified-open-web-signal", open_web["items"][0]["flags"])
        self.assertEqual(trace["status"], "ok")

    def test_mock_mode_scrubs_api_key_from_output(self):
        secret = "dummy-tavily-secret-value"
        mock_results = {
            "results": [
                {
                    "title": f"Public result {secret}",
                    "url": "https://example.org/public-result",
                    "content": f"Snippet containing {secret} should be scrubbed.",
                    "score": 0.8,
                }
            ]
        }
        with EnvPatch(TAVILY_MOCK_RESPONSE="true", TAVILY_API_KEY=secret, TAVILY_MOCK_RESULTS_JSON=json.dumps(mock_results)):
            open_web, trace = search_open_web_signals({"label": "48 Quernmore Road"}, {"goal": "review"}, {})

        serialized = json.dumps({"openWeb": open_web, "trace": trace})
        self.assertNotIn(secret, serialized)
        self.assertIn("[redacted]", serialized)

    def test_mock_mode_drops_signed_or_credential_urls(self):
        mock_results = {
            "results": [
                {
                    "title": "Signed result",
                    "url": "https://example.org/private?X-Amz-Signature=dummy",
                    "content": "This signed URL should not be emitted.",
                    "score": 0.9,
                },
                {
                    "title": "Public result",
                    "url": "https://example.org/public",
                    "content": "This public URL can be emitted.",
                    "score": 0.8,
                },
            ]
        }
        with EnvPatch(TAVILY_MOCK_RESPONSE="true", TAVILY_MOCK_RESULTS_JSON=json.dumps(mock_results)):
            open_web, _trace = search_open_web_signals({"label": "48 Quernmore Road"}, {"goal": "review"}, {})

        self.assertEqual([item["url"] for item in open_web["items"]], ["https://example.org/public"])

    def test_live_mode_uses_env_config_and_normalizes_tavily_results(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["authorization"] = req.get_header("Authorization")
            return FakeTavilyResponse(
                {
                    "query": "returned query",
                    "results": [
                        {
                            "title": "Relevant public article",
                            "url": "https://news.example.org/article",
                            "content": "Public article snippet.",
                            "score": 0.91,
                            "published_date": "2026-06-20",
                        }
                    ],
                    "usage": {"credits": 1},
                    "request_id": "req-123",
                }
            )

        with EnvPatch(
            ENABLE_TAVILY="true",
            TAVILY_API_KEY="dummy-live-tavily-key",
            TAVILY_MOCK_RESPONSE=None,
            TAVILY_MAX_RESULTS="3",
            TAVILY_TIMEOUT_SECONDS="7",
            TAVILY_SEARCH_DEPTH="basic",
        ):
            with patch("rams_agent_tools.tools.open_web.urlopen", fake_urlopen):
                open_web, trace = search_open_web_signals({"label": "48 Quernmore Road"}, {"goal": "review"}, {})

        self.assertEqual(captured["url"], "https://api.tavily.com/search")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["authorization"], "Bearer dummy-live-tavily-key")
        self.assertEqual(captured["body"]["search_depth"], "basic")
        self.assertFalse(captured["body"]["include_raw_content"])
        self.assertEqual(captured["body"]["max_results"], 3)
        self.assertEqual(open_web["status"], "ok")
        self.assertEqual(open_web["mode"], "live")
        self.assertTrue(open_web["liveCallAttempted"])
        self.assertEqual(open_web["items"][0]["sourceType"], "news")
        self.assertEqual(open_web["items"][0]["relevance"], "high")
        self.assertEqual(trace["status"], "ok")
        self.assertNotIn("dummy-live-tavily-key", json.dumps(open_web))


if __name__ == "__main__":
    unittest.main()
