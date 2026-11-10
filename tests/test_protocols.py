import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from app import create_app
from src.config import AppConfig
from src.session_store import InMemorySessionStore


class ReviewedProtocolRoutingTests(unittest.TestCase):
    def create_client(self, directory, *, include_guidance):
        protocol = {
            "protocol_id": "TEST-ONLY-HEADACHE",
            "version": "fixture-v1",
            "status": "active",
            "approved": True,
            "approved_by": "test-fixture-only",
            "jurisdiction": "DE",
            "symptom_terms": ["headache", "kopfschmerz"],
            "questions": [
                {
                    "question_id": "TEST-NONREQUIRED-QUESTION",
                    "fact_id": "symptom_duration",
                    "prompt_en": "Test duration question.",
                    "prompt_de": "Testfrage zur Dauer.",
                    "required": False,
                }
            ],
            "permitted_product_ids": ["P01"],
            "source_ids": ["TEST-SOURCE"],
            "source_versions": {"TEST-SOURCE": "fixture-v1"},
        }
        if include_guidance:
            protocol.update(
                {
                    "assessment_guidance_en": "TEST FIXTURE: reviewed guidance.",
                    "assessment_guidance_de": "TEST FIXTURE: gepruefter Hinweis.",
                }
            )
        protocol_path = Path(directory) / "protocols.json"
        protocol_path.write_text(json.dumps([protocol]), encoding="utf-8")
        return create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(protocol_catalog_path=str(protocol_path)),
        ).test_client()

    def send_symptom(self, client, language, message):
        session = client.post("/api/sessions").get_json()
        return client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": 0,
                "language": language,
                "message": message,
            },
        ).get_json()

    def test_symptom_assessment_returns_reviewed_guidance_without_medicine_option(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self.create_client(directory, include_guidance=True)
            for language, symptom, expected_guidance in (
                ("en", "I have a headache.", "TEST FIXTURE: reviewed guidance."),
                ("de", "Ich habe Kopfschmerzen.", "TEST FIXTURE: gepruefter Hinweis."),
            ):
                with self.subTest(language=language):
                    result = self.send_symptom(client, language, symptom)
                    self.assertEqual(result["action"], "SELF_CARE")
                    self.assertEqual(result["intent"], "symptom_assessment")
                    self.assertEqual(result["message"], expected_guidance)
                    self.assertEqual(result["options"], [])
                    self.assertEqual(
                        result["sources"],
                        [{"source_id": "TEST-SOURCE", "source_version": "fixture-v1"}],
                    )

    def test_symptom_assessment_blocks_when_reviewed_outcome_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self.create_client(directory, include_guidance=False)
            result = self.send_symptom(client, "en", "I have a headache.")

        self.assertEqual(result["action"], "PHARMACIST_REFERRAL")
        self.assertEqual(result["intent"], "symptom_assessment")
        self.assertEqual(
            result["reason_codes"],
            ["PROTOCOL_ASSESSMENT_OUTCOME_MISSING"],
        )
        self.assertEqual(result["options"], [])
        self.assertNotIn("112", result["message"])


if __name__ == "__main__":
    unittest.main()
