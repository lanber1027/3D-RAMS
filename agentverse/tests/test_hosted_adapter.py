from __future__ import annotations

import importlib
import json
import os
import sys
import types
import unittest
from pathlib import Path


AGENTVERSE_ROOT = Path(__file__).resolve().parents[1]
if str(AGENTVERSE_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTVERSE_ROOT))


class HostedAdapterPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("AGENTCORE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/entry-test")
        _install_uagents_stubs()
        cls.hosted_adapter = importlib.import_module("hosted_adapter")

    def test_case_reference_builds_report_lookup_payload(self):
        payload = self.hosted_adapter._report_lookup_payload("case_ec2310c77382", "agentverse-session")

        self.assertEqual(payload["operation"], "getReport")
        self.assertEqual(payload["caller"], "agentverse")
        self.assertEqual(payload["caseId"], "case_ec2310c77382")
        self.assertEqual(payload["reportAccess"]["mode"], "asi_session")
        self.assertEqual(payload["reportAccess"]["sessionId"], "agentverse-session")
        self.assertEqual(payload["reportAccess"]["authorizedCaseIds"], ["case_ec2310c77382"])

    def test_entry_turn_payload_carries_session_report_access(self):
        payload = self.hosted_adapter._entry_turn_payload(
            "Confirmed. Proceed with the review-required workflow.",
            "agentverse-session",
        )

        self.assertTrue(payload["entryTurn"])
        self.assertTrue(payload["confirmedByUser"])
        self.assertEqual(payload["reportAccess"]["mode"], "asi_session")
        self.assertEqual(payload["reportAccess"]["sessionId"], "agentverse-session")

    def test_ask_me_to_confirm_is_not_confirmation(self):
        payload = self.hosted_adapter._entry_turn_payload(
            "Ask me to confirm before launching.",
            "agentverse-session",
        )

        self.assertFalse(payload["confirmedByUser"])

    def test_case_id_from_prompt(self):
        self.assertEqual(
            self.hosted_adapter._case_id_from_prompt("Show report /case/case_ec2310c77382 please"),
            "case_ec2310c77382",
        )

    def test_full_report_link_uses_frontend_base_and_session(self):
        response = json.dumps({"output": {"caseId": "case_ec2310c77382"}})
        previous = os.environ.get("PUBLIC_FRONTEND_BASE_URL")
        os.environ["PUBLIC_FRONTEND_BASE_URL"] = "https://example.test"
        try:
            text = self.hosted_adapter._append_full_report_link("Summary", response, "agentverse-session")
        finally:
            if previous is None:
                os.environ.pop("PUBLIC_FRONTEND_BASE_URL", None)
            else:
                os.environ["PUBLIC_FRONTEND_BASE_URL"] = previous

        self.assertIn("Full report: https://example.test/case/case_ec2310c77382?reportSessionId=agentverse-session", text)

    def test_session_id_prefers_message_conversation_id(self):
        first = self.hosted_adapter._session_id("sender-a", {"conversationId": "conversation-1"})
        second = self.hosted_adapter._session_id("sender-b", {"conversationId": "conversation-1"})

        self.assertEqual(first, second)

    def test_session_id_finds_nested_session_metadata(self):
        first = self.hosted_adapter._session_id("sender-a", {"metadata": {"thread_id": "thread-1"}})
        second = self.hosted_adapter._session_id("sender-b", {"metadata": {"thread_id": "thread-1"}})

        self.assertEqual(first, second)


def _install_uagents_stubs():
    if "uagents" in sys.modules:
        return

    class Agent:
        def run(self):
            return None

        def include(self, _protocol):
            return None

    class Protocol:
        def __init__(self, **_kwargs):
            pass

        def on_message(self, **_kwargs):
            def decorator(func):
                return func

            return decorator

    class Context:
        pass

    class ChatAcknowledgement:
        pass

    class ChatMessage:
        pass

    class TextContent:
        def __init__(self, text: str):
            self.text = text

    uagents = types.ModuleType("uagents")
    uagents.Agent = Agent
    uagents.Context = Context
    uagents.Protocol = Protocol
    sys.modules["uagents"] = uagents

    chat = types.ModuleType("uagents_core.contrib.protocols.chat")
    chat.ChatAcknowledgement = ChatAcknowledgement
    chat.ChatMessage = ChatMessage
    chat.TextContent = TextContent
    chat.chat_protocol_spec = {}
    sys.modules["uagents_core"] = types.ModuleType("uagents_core")
    sys.modules["uagents_core.contrib"] = types.ModuleType("uagents_core.contrib")
    sys.modules["uagents_core.contrib.protocols"] = types.ModuleType("uagents_core.contrib.protocols")
    sys.modules["uagents_core.contrib.protocols.chat"] = chat


if __name__ == "__main__":
    unittest.main()
