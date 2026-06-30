from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ENTRY_APP_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_APP_ROOT = ENTRY_APP_ROOT.parent / "rams_supervisor_runtime"
TOOLS_ROOT = ENTRY_APP_ROOT.parent / "rams_agent_tools"
ROOT = ENTRY_APP_ROOT.parents[1]
for app_root in (ENTRY_APP_ROOT, SUPERVISOR_APP_ROOT, TOOLS_ROOT):
    if str(app_root) in sys.path:
        sys.path.remove(str(app_root))
for app_root in (TOOLS_ROOT, SUPERVISOR_APP_ROOT, ENTRY_APP_ROOT):
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

from main import handle_invocation as handle_entry_invocation  # noqa: E402
from supervisor_core.agentcore_adapter import handle_invocation as handle_supervisor_invocation  # noqa: E402
from supervisor_core.report_store import load_report, persist_report  # noqa: E402


spec = importlib.util.spec_from_file_location(
    "hosted_agentcore_asio_smoke",
    ROOT / "scripts" / "hosted-agentcore-asio-smoke.py",
)
hosted_smoke = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(hosted_smoke)


class HostedAgentCoreAsioSmokeTests(unittest.TestCase):
    def test_run_smoke_exercises_entry_supervisor_store_and_lookup(self):
        store: dict = {}

        class WriteTable:
            def put_item(self, *, Item):
                store.update(Item)

        class ReadTable:
            def get_item(self, *, Key):
                assert Key == {"caseId": store["caseId"]}
                return {"Item": store}

        def fake_supervisor_runtime(**kwargs):
            payload = kwargs["payload"]
            input_payload = payload.get("input", {})
            if input_payload.get("operation") == "getReport":
                return load_report(
                    input_payload["caseId"],
                    access_context=input_payload.get("reportAccess") or input_payload.get("accessContext"),
                    table=ReadTable(),
                    table_name="smoke-report-store",
                )

            response = handle_supervisor_invocation(payload)
            response["output"]["persistence"] = persist_report(
                response["output"],
                table=WriteTable(),
                table_name="smoke-report-store",
            )
            return response

        def fake_entry(payload):
            return handle_entry_invocation(
                payload,
                supervisor_runtime_arn="arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/smoke-entry-test",
                invoke_runtime=fake_supervisor_runtime,
            )

        result = hosted_smoke.run_smoke(
            fake_entry,
            case_id="case_hosted_smoke_unit_001",
            bedrock_fallback=True,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["caseId"], "case_hosted_smoke_unit_001")
        self.assertEqual([check["status"] for check in result["checks"]], ["ok", "ok", "ok", "ok", "ok", "ok", "ok"])
        self.assertEqual(result["checks"][-1]["name"], "bedrock_requested_fallback")
        self.assertTrue(result["supervisor"]["structuredReport"])

    def test_frontend_html_validation_is_public_safe(self):
        self.assertEqual(
            hosted_smoke._validate_frontend_html('<html><body><div id="root"></div></body></html>'),
            {"status": "ok", "appShell": True},
        )

    def test_redaction_removes_secret_and_account_sensitive_values(self):
        fake_access_key = "AKIA" + "1234567890ABCDEF"
        redacted = hosted_smoke.redact_public_safe(
            {
                "authorization": "Bearer very-secret-token",
                "runtimeArn": "arn:aws:bedrock-agentcore:eu-west-2:123456789012:runtime/example",
                "signedUrl": "https://example.com/file?X-Amz-Signature=abc&X-Amz-Credential=def",
                "message": f"key {fake_access_key} account 123456789012",
            }
        )

        self.assertEqual(redacted["authorization"], "[REDACTED]")
        self.assertEqual(redacted["signedUrl"], "[REDACTED]")
        self.assertEqual(redacted["runtimeArn"], "[REDACTED_AWS_ARN]")
        self.assertIn("[REDACTED_AWS_ACCESS_KEY]", redacted["message"])
        self.assertIn("[REDACTED_ACCOUNT_ID]", redacted["message"])


if __name__ == "__main__":
    unittest.main()
