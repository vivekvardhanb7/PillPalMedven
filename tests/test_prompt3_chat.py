import unittest
from uuid import uuid4

from app import create_app
from src.config import AppConfig
from src.session_store import InMemorySessionStore
from tests.prompt3_scenarios import SCENARIOS


class Prompt3ChatSmokeTests(unittest.TestCase):
    def test_openers_do_not_invent_recommendations_or_add_routine_emergency_guidance(self):
        client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(recommendations_enabled=True),
        ).test_client()

        for case_id, english, german in SCENARIOS:
            for language, message in (("en", english), ("de", german)):
                with self.subTest(case_id=case_id, language=language):
                    session = client.post("/api/sessions").get_json()
                    response = client.post(
                        "/api/chat",
                        headers={
                            "Authorization": f"Bearer {session['access_token']}"
                        },
                        json={
                            "session_id": session["session_id"],
                            "request_id": str(uuid4()),
                            "session_revision": 0,
                            "language": language,
                            "message": message,
                        },
                    )

                    self.assertEqual(response.status_code, 200)
                    result = response.get_json()
                    self.assertEqual(result["language"], language)
                    self.assertTrue(result["recommendations_enabled"])
                    self.assertEqual(result["options"], [])
                    self.assertNotEqual(result["action"], "MEDICINE_OPTION")
                    if result["action"] == "EMERGENCY":
                        self.assertIn("112", result["message"])
                    else:
                        self.assertNotIn("112", result["message"])


if __name__ == "__main__":
    unittest.main()
