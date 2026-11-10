import unittest
from uuid import uuid4

from app import create_app
from src.catalog import load_candidate_catalog
from src.config import AppConfig
from src.session_store import InMemorySessionStore


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            InMemorySessionStore(),
            config=AppConfig(),
            candidate_catalog=load_candidate_catalog(),
        )
        self.client = self.app.test_client()

    def create_session(self):
        response = self.client.post("/api/sessions")
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def chat(
        self,
        session,
        revision=0,
        request_id=None,
        message="question",
        language="en",
    ):
        return self.client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={
                "session_id": session["session_id"],
                "request_id": request_id or str(uuid4()),
                "session_revision": revision,
                "language": language,
                "message": message,
            },
        )

    def test_medicine_request_starts_symptom_intake_and_increments_revision(self):
        session = self.create_session()

        response = self.chat(session, message="What medicine should I take?")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["action"], "ASK_QUESTION")
        self.assertEqual(body["session_revision"], 1)
        self.assertTrue(body["recommendations_enabled"])
        self.assertEqual(body["intent"], "personal_medicine_recommendation")
        self.assertEqual(body["reason_codes"], [])
        self.assertEqual(body["pending_question_ids"], ["symptoms"])
        self.assertIn("symptom", body["message"].lower())
        self.assertNotIn("112", body["message"])
        self.assertEqual(body["sources"], [])

    def test_english_and_german_greetings_route_before_eligibility(self):
        for language, message, greeting in (
            ("en", "hi", "Hello!"),
            ("de", "hallo", "Hallo!"),
        ):
            with self.subTest(language=language):
                session = self.create_session()
                response = self.chat(session, message=message, language=language)
                body = response.get_json()

                self.assertEqual(body["action"], "GREETING")
                self.assertEqual(body["intent"], "greeting")
                self.assertEqual(body["reason_codes"], [])
                self.assertIn(greeting, body["message"])
                self.assertNotIn("112", body["message"])
                self.assertEqual(body["catalog_candidate_count"], 30)

    def test_sessions_are_isolated(self):
        first = self.create_session()
        second = self.create_session()

        self.assertEqual(self.chat(first).get_json()["session_revision"], 1)
        self.assertEqual(self.chat(second).get_json()["session_revision"], 1)

    def test_idempotent_request_and_stale_revision(self):
        session = self.create_session()
        request_id = str(uuid4())

        first = self.chat(session, request_id=request_id)
        retry = self.chat(session, request_id=request_id)
        stale = self.chat(session, revision=0)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.get_json(), first.get_json())
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["error"]["code"], "REVISION_CONFLICT")

    def test_chat_requires_session_token(self):
        session = self.create_session()
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": 0,
                "message": "hello",
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_reset_invalidates_token(self):
        session = self.create_session()
        reset = self.client.post(
            "/api/session/reset",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={"session_id": session["session_id"]},
        )

        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.chat(session).status_code, 404)

    def test_message_size_and_input_validation(self):
        session = self.create_session()

        too_long = self.chat(session, message="x" * 4001)
        invalid_revision = self.client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": True,
                "message": "hello",
            },
        )

        self.assertEqual(too_long.status_code, 413)
        self.assertEqual(invalid_revision.status_code, 400)

    def test_health_endpoints_do_not_claim_clinical_readiness(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        ready = self.client.get("/health/ready")

        self.assertEqual(ready.status_code, 200)
        self.assertFalse(ready.get_json()["clinical_paths_ready"])
        self.assertTrue(ready.get_json()["recommendations_enabled"])
        self.assertTrue(ready.get_json()["catalog_data_pending"])

    def test_legacy_unprotected_chat_endpoint_is_removed(self):
        self.assertEqual(self.client.post("/get", data={"msg": "hello"}).status_code, 404)

    def test_language_must_be_a_supported_string(self):
        session = self.create_session()
        for language in ([], {}, None, True, 1, "fr"):
            with self.subTest(language=language):
                response = self.chat(session, message="hello", language=language)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"]["code"], "INVALID_LANGUAGE")
        self.assertEqual(self.chat(session, message="hello").status_code, 200)

    def test_request_body_limit_returns_json(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 128
        response = self.client.post(
            "/api/chat", data='{"message":"' + "x" * 256 + '"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"]["code"], "REQUEST_TOO_LARGE")

    def test_session_tokens_chat_and_errors_are_not_cacheable(self):
        session_response = self.client.post("/api/sessions")
        session = session_response.get_json()
        for response in (
            session_response,
            self.chat(session, message="hello"),
            self.client.post("/api/chat", json={}),
        ):
            self.assertEqual(response.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
