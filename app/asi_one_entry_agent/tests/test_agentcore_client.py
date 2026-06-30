from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path


ENTRY_APP_ROOT = Path(__file__).resolve().parents[1]
if str(ENTRY_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(ENTRY_APP_ROOT))

from agentcore_client import agentcore_url, extract_json_body, extract_text_body, signed_headers  # noqa: E402


class EnvPatch:
    def __init__(self, **updates: str):
        self.updates = updates
        self.previous: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self.updates.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AgentCoreClientTests(unittest.TestCase):
    def test_agentcore_url_encodes_runtime_arn_in_path(self):
        runtime_arn = "arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/test-runtime"
        url, host, path = agentcore_url(runtime_arn, "eu-west-2")

        self.assertEqual(host, "bedrock-agentcore.eu-west-2.amazonaws.com")
        self.assertIn("arn%3Aaws%3Abedrock-agentcore", path)
        self.assertEqual(url, f"https://{host}{path}")

    def test_signed_headers_include_agentcore_user_headers(self):
        with EnvPatch(AWS_ACCESS_KEY_ID="AKIAEXAMPLE", AWS_SECRET_ACCESS_KEY="secret"):
            headers = signed_headers(
                method="POST",
                path="/runtimes/example/invocations",
                host="bedrock-agentcore.eu-west-2.amazonaws.com",
                payload=b"{}",
                session_id="session-1",
                user_id="user-1",
                region="eu-west-2",
            )

        self.assertEqual(headers["x-amzn-bedrock-agentcore-runtime-session-id"], "session-1")
        self.assertEqual(headers["x-amzn-bedrock-agentcore-runtime-user-id"], "user-1")
        self.assertIn("AWS4-HMAC-SHA256", headers["authorization"])

    def test_extract_json_body_from_direct_json(self):
        payload = {"output": {"delivery": {"customerSummary": {"headline": "Done"}}}}

        self.assertEqual(extract_json_body(json.dumps(payload)), payload)
        self.assertEqual(extract_text_body(json.dumps(payload)), "Done")

    def test_extract_json_body_from_streamed_text_json(self):
        streamed = 'data: {"event":{"contentBlockDelta":{"delta":{"text":"{\\"output\\":"}}}}\n'
        streamed += 'data: {"event":{"contentBlockDelta":{"delta":{"text":"{\\"ok\\": true}}"}}}}\n'

        self.assertEqual(extract_json_body(streamed), {"output": {"ok": True}})

    def test_extract_text_body_from_streamed_entry_agent_message(self):
        inner = json.dumps(
            {
                "output": {
                    "entryAgent": {
                        "assistantMessage": "I need a little more information before I can launch.",
                        "clarifyingQuestions": ["Which site should I assess?"],
                    }
                }
            }
        )
        streamed = "data: " + json.dumps({"event": {"contentBlockDelta": {"delta": {"text": inner}}}}) + "\n"

        text = extract_text_body(streamed)

        self.assertIn("I need a little more information", text)
        self.assertIn("- Which site should I assess?", text)
        self.assertNotIn('"output"', text)

    def test_extract_text_body_from_entry_agent_message(self):
        payload = {
            "output": {
                "entryAgent": {
                    "assistantMessage": "I need a little more information before I can launch.",
                    "clarifyingQuestions": ["Which site should I assess?", "What area should I cover?"],
                }
            }
        }

        text = extract_text_body(json.dumps(payload))

        self.assertIn("I need a little more information", text)
        self.assertIn("- Which site should I assess?", text)
        self.assertNotIn('"output"', text)

    def test_extract_json_body_from_json_string_python_repr(self):
        raw = json.dumps("{'output': {'caseId': 'case_lookup_001', 'workflowMode': 'report_lookup'}}")

        self.assertEqual(
            extract_json_body(raw),
            {"output": {"caseId": "case_lookup_001", "workflowMode": "report_lookup"}},
        )


if __name__ == "__main__":
    unittest.main()
