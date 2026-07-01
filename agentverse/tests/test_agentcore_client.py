from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


AGENTVERSE_ROOT = Path(__file__).resolve().parents[1]
if str(AGENTVERSE_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTVERSE_ROOT))


from agentcore_client import extract_text_body  # noqa: E402


class AgentCoreClientTextTests(unittest.TestCase):
    def test_report_lookup_returns_human_summary_not_raw_json(self):
        payload = {
            "output": {
                "caseId": "case_lookup_001",
                "reportStatus": "review_passed",
                "workflowMode": "cached_public_fixture",
                "entryAgent": {"mode": "cloud-report-lookup"},
                "structuredReport": {
                    "executiveSummary": {
                        "priorityChecks": ["Access route interface"],
                        "limitations": ["Draft only; human review required."],
                    }
                },
                "reviewGate": {
                    "status": "passed_with_caveats",
                    "safetyLevel": "review_required",
                    "requiresHumanReview": True,
                    "message": "Independent review passed with caveats.",
                    "caveats": ["Open-web signals unavailable."],
                },
                "citationMetadata": {
                    "findings": [
                        {
                            "title": "Temporary scaffold access route",
                            "evidenceIds": ["ev-access"],
                        }
                    ]
                },
                "evidenceSummary": [
                    {
                        "id": "ev-access",
                        "title": "Access context",
                        "summary": "Flags pedestrian and scaffold interface.",
                    }
                ],
            }
        }

        text = extract_text_body(json.dumps(payload))

        self.assertIn("Report /case/case_lookup_001: review_passed", text)
        self.assertIn("Temporary scaffold access route", text)
        self.assertIn("Access context", text)
        self.assertIn("Open-web signals unavailable.", text)
        self.assertNotIn('"structuredReport"', text)

    def test_launch_response_appends_report_summary_to_entry_message(self):
        payload = {
            "output": {
                "caseId": "case_launch_001",
                "reportStatus": "review_passed",
                "entryAgent": {
                    "status": "delivered",
                    "assistantMessage": "Cached public-source review pack for early site scoping.\n\nReport reference: /case/case_launch_001",
                },
                "structuredReport": {
                    "executiveSummary": {
                        "priorityChecks": ["Confined workspace readiness"],
                        "limitations": ["Draft only."],
                    }
                },
                "reviewGate": {
                    "status": "passed_with_caveats",
                    "safetyLevel": "review_required",
                    "requiresHumanReview": True,
                    "message": "Independent review passed with caveats.",
                },
            }
        }

        text = extract_text_body(json.dumps(payload))

        self.assertIn("Cached public-source review pack", text)
        self.assertIn("Report /case/case_launch_001: review_passed", text)
        self.assertIn("Confined workspace readiness", text)
        self.assertIn("Draft only.", text)


if __name__ == "__main__":
    unittest.main()
