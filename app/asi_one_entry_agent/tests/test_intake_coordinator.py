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
