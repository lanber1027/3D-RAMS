from __future__ import annotations

import sys
import unittest
from pathlib import Path


ENTRY_APP_ROOT = Path(__file__).resolve().parents[1]
if str(ENTRY_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(ENTRY_APP_ROOT))

from intake_coordinator import (  # noqa: E402
    IntakeValidationError,
    build_confirmed_entry_payload,
    build_entry_turn,
    coordinate_intake,
)


class IntakeCoordinatorTests(unittest.TestCase):
    def test_missing_location_returns_clarification(self):
        result = coordinate_intake({"message": "Can you help me?", "conversationId": "c1"})

        self.assertEqual(result["status"], "clarification_required")
        self.assertTrue(result["clarifyingQuestions"])
        self.assertIsNone(result["caseId"])

    def test_site_message_returns_confirmation_ready_intake(self):
        result = coordinate_intake(
            {
                "message": "I want to visit 8 Albert Embankment tomorrow for a survey for 2km",
                "conversationId": "c2",
            }
        )

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["intake"]["locationText"], "8 Albert Embankment")
        self.assertEqual(result["intake"]["areaScope"]["meters"], 2000)
        self.assertIsNone(result["caseId"])

    def test_site_message_without_area_asks_only_for_area(self):
        result = coordinate_intake(
            {
                "message": "I want to visit 8 Albert Embankment tomorrow for a survey",
                "conversationId": "c2-missing-area",
            }
        )

        self.assertEqual(result["status"], "clarification_required")
        self.assertEqual(result["clarifyingQuestions"], ["What area should I cover around the site, for example a radius or boundary?"])

    def test_confirmed_intake_creates_case_id(self):
        payload = {
            "message": "I want to visit 8 Albert Embankment tomorrow for a survey for 2km",
            "conversationId": "c3",
            "confirmedByUser": True,
        }

        result = coordinate_intake(payload)
        confirmed = build_confirmed_entry_payload(build_entry_turn(payload), result)

        self.assertEqual(result["status"], "launch_ready")
        self.assertTrue(result["caseId"].startswith("case_"))
        self.assertEqual(confirmed["caseId"], result["caseId"])
        self.assertTrue(confirmed["confirmedByUser"])

    def test_confirmed_payload_preserves_report_access(self):
        payload = {
            "message": "I want to visit 8 Albert Embankment tomorrow for a survey for 2km",
            "conversationId": "proxy-session-id",
            "confirmedByUser": True,
            "reportAccess": {
                "mode": "asi_session",
                "sessionId": "asi-launch-session",
                "authorizedCaseIds": ["case_expected"],
            },
        }

        result = coordinate_intake(payload)
        confirmed = build_confirmed_entry_payload(build_entry_turn(payload), result)

        self.assertEqual(confirmed["reportAccess"]["sessionId"], "asi-launch-session")

    def test_invalid_model_json_is_rejected(self):
        with self.assertRaisesRegex(IntakeValidationError, "valid JSON"):
            coordinate_intake({"message": "8 Albert Embankment for 2km"}, model_json=lambda _: "not json")

    def test_confirmation_message_includes_summary_when_model_message_is_empty_shell(self):
        result = coordinate_intake(
            {"message": "review 48 Quernmore Road within 800m", "conversationId": "c-empty-details"},
            model_json=lambda _: {
                "status": "confirmation_required",
                "assistantMessage": "Please confirm the details below before proceeding.",
                "intake": {
                    "locationText": "48 Quernmore Road, London",
                    "areaScope": {"type": "radius", "meters": 800},
                    "userGoal": "confined workspace inspection readiness review",
                    "materials": [],
                },
            },
        )

        self.assertEqual(result["status"], "confirmation_required")
        self.assertIn("48 Quernmore Road", result["assistantMessage"])
        self.assertIn("800m radius", result["assistantMessage"])
        self.assertIn("48 Quernmore Road", result["confirmation"]["summary"])

    def test_invalid_model_json_uses_deterministic_fallback(self):
        result = coordinate_intake(
            {
                "message": "I want to visit 8 Albert Embankment tomorrow for a survey for 2km",
                "conversationId": "c4",
            },
            model_json=lambda _: "not json",
            fallback_to_deterministic=True,
        )

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["fallbackReason"], "invalid_model_json")
        self.assertEqual(result["intakeMode"], "fallback")
        self.assertEqual(result["intake"]["locationText"], "8 Albert Embankment")

    def test_model_schema_failure_uses_deterministic_fallback_and_can_launch(self):
        result = coordinate_intake(
            {
                "message": "I want to visit 8 Albert Embankment tomorrow for a survey for 2km",
                "conversationId": "c5",
                "confirmedByUser": True,
            },
            model_json=lambda _: {"status": "launch_ready", "intake": {"locationText": "8 Albert Embankment"}},
            fallback_to_deterministic=True,
        )

        self.assertEqual(result["status"], "launch_ready")
        self.assertEqual(result["fallbackReason"], "schema_validation_failed")
        self.assertEqual(result["intakeMode"], "fallback")
        self.assertTrue(result["caseId"].startswith("case_"))

    def test_invalid_model_json_can_fallback_to_deterministic_intake(self):
        result = coordinate_intake(
            {"message": "8 Albert Embankment survey for 2km", "conversationId": "c4"},
            model_json=lambda _: "not json",
            fallback_to_deterministic=True,
        )

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["intakeMode"], "fallback")
        self.assertEqual(result["fallbackReason"], "invalid_model_json")


if __name__ == "__main__":
    unittest.main()
