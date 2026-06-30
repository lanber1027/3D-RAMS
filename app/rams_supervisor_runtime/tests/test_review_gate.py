import sys
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_ROOT.parent / "rams_agent_tools"
for path in (TOOLS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from supervisor_core.review_gate import (  # noqa: E402
    REVIEW_INPUT_SCHEMA,
    REVIEW_OUTPUT_SCHEMA,
    build_review_input,
    deterministic_review,
    run_independent_review_loop,
)


def base_run() -> dict:
    return {
        "caseId": "case_review_test",
        "trace": [],
        "safety": {
            "allowed": True,
            "level": "review_required",
            "message": "Allowed as a non-certified pre-visit briefing that requires human review.",
            "triggeredRules": [],
            "requiresHumanReview": True,
        },
    }


def base_report() -> dict:
    return {
        "caseId": "case_review_test",
        "status": "review_required",
        "intake": {"caseId": "case_review_test", "goal": "pre-visit review"},
        "executiveSummary": {"summary": [], "limitations": []},
        "findings": [],
        "visualization": {"annotations": []},
        "evidenceRegister": {"sources": [], "evidence": []},
        "reviewGate": {},
        "dataQuality": {"gaps": [], "warnings": []},
        "reasoning": {},
        "trace": [],
    }


class IndependentReviewGateTests(unittest.TestCase):
    def test_review_input_and_pass_output_contract(self):
        run = base_run()
        report = base_report()

        review_input = build_review_input(run=run, structured_report=report)
        review = deterministic_review(review_input)

        self.assertEqual(review_input["schemaVersion"], REVIEW_INPUT_SCHEMA)
        self.assertEqual(review_input["safetyBoundary"]["nonCertifiedRams"], True)
        self.assertEqual(review["schemaVersion"], REVIEW_OUTPUT_SCHEMA)
        self.assertEqual(review["decision"], "pass")
        self.assertEqual(review["status"], "ok")

    def test_revise_removes_unsupported_finding_and_passes_with_caveat(self):
        run = base_run()
        report = base_report()
        report["findings"] = [
            {
                "id": "unsupported-access",
                "title": "Unsupported access claim",
                "references": {"sourceIds": [], "evidenceIds": []},
                "humanReviewRequired": True,
            }
        ]
        report["visualization"]["annotations"] = [{"id": "unsupported-access"}]

        reviewed = run_independent_review_loop(run=run, draft_report=report)

        self.assertEqual(reviewed["reportStatus"], "passed_with_caveats")
        self.assertEqual(reviewed["structuredReport"]["findings"], [])
        self.assertEqual(reviewed["structuredReport"]["visualization"]["annotations"], [])
        gate = reviewed["structuredReport"]["reviewGate"]
        self.assertEqual(gate["decision"], "pass_with_caveats")
        self.assertEqual(gate["revisionCount"], 1)
        self.assertTrue(any(step["name"] == "supervisor_revision_pass" for step in reviewed["run"]["trace"]))

    def test_block_prevents_normal_report_delivery(self):
        run = base_run()
        report = base_report()
        report["executiveSummary"]["summary"] = ["This pack is approved for work."]

        reviewed = run_independent_review_loop(run=run, draft_report=report)

        self.assertEqual(reviewed["reportStatus"], "blocked")
        self.assertEqual(reviewed["structuredReport"]["status"], "blocked")
        self.assertEqual(reviewed["structuredReport"]["reviewGate"]["decision"], "block")
        self.assertFalse(reviewed["structuredReport"]["reviewGate"]["safetyAllowed"])

    def test_max_revision_attempts_becomes_review_required(self):
        def always_revise(_review_input: dict) -> dict:
            return {
                "schemaVersion": REVIEW_OUTPUT_SCHEMA,
                "reviewer": {"name": "test-reviewer", "mode": "deterministic"},
                "decision": "revise",
                "status": "warning",
                "summary": "Still needs revision.",
                "issues": [
                    {
                        "id": "still-open",
                        "severity": "medium",
                        "message": "Still open.",
                        "affects": ["sections.candidate-findings"],
                        "requiredAction": "add_caveat",
                    }
                ],
                "requiredRevisions": ["Still open."],
                "caveats": [],
                "trace": [],
            }

        reviewed = run_independent_review_loop(
            run=base_run(),
            draft_report=base_report(),
            reviewer=always_revise,
            max_revision_attempts=2,
        )

        gate = reviewed["structuredReport"]["reviewGate"]
        self.assertEqual(reviewed["reportStatus"], "review_required")
        self.assertEqual(gate["decision"], "revise")
        self.assertEqual(gate["revisionCount"], 2)
        self.assertTrue(gate["caveats"])


if __name__ == "__main__":
    unittest.main()
