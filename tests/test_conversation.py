import unittest
from types import SimpleNamespace
from uuid import uuid4

from app import create_app
from src.catalog import load_candidate_catalog
from src.config import AppConfig
from src.llm import ExtractedFact, FactExtraction
from src.session_store import InMemorySessionStore


CASES = (
    (
        "general_information",
        "What is paracetamol used for?",
        "Wofuer wird Paracetamol verwendet?",
        "ASK_QUESTION",
    ),
    (
        "missing_product_data",
        "What medicine should I take?",
        "Welches Medikament soll ich nehmen?",
        "ASK_QUESTION",
    ),
    (
        "urgent_symptoms",
        "I have pressure in my chest, trouble breathing and I'm sweating.",
        "Ich habe Druck auf der Brust, Atemnot und schwitze.",
        "EMERGENCY",
    ),
)


class ConversationRoutingTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(recommendations_enabled=True),
            candidate_catalog=load_candidate_catalog(),
        ).test_client()

    def send(self, language, message, revision=0):
        session = self.client.post("/api/sessions").get_json()
        return self.client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": revision,
                "language": language,
                "message": message,
            },
        )

    def test_chat_and_voice_transcripts_route_the_same_cases_in_both_languages(self):
        for case_id, english, german, expected_action in CASES:
            for language, message in (("en", english), ("de", german)):
                for channel in ("chat", "voice_transcript"):
                    with self.subTest(
                        case=case_id, language=language, channel=channel
                    ):
                        response = self.send(language, message)
                        self.assertEqual(response.status_code, 200)
                        result = response.get_json()
                        self.assertEqual(result["action"], expected_action)
                        self.assertEqual(result["language"], language)
                        self.assertEqual(result["options"], [])

                        if case_id == "general_information":
                            self.assertEqual(result["intent"], case_id)
                            self.assertEqual(result["reason_codes"], ["PINECONE_NOT_CONFIGURED"])
                            self.assertEqual(result["sources"], [])
                            self.assertNotIn("112", result["message"])
                        elif case_id == "missing_product_data":
                            self.assertEqual(
                                result["intent"],
                                "personal_medicine_recommendation",
                            )
                            self.assertEqual(result["pending_question_ids"], ["symptoms"])
                            self.assertNotIn("112", result["message"])
                        else:
                            self.assertEqual(
                                result["reason_codes"], ["URGENT_SYMPTOMS_REPORTED"]
                            )
                            self.assertIn("112", result["message"])

    def test_pending_product_does_not_block_a_later_general_information_turn(self):
        session = self.client.post("/api/sessions").get_json()
        headers = {"Authorization": f"Bearer {session['access_token']}"}

        pending = self.client.post(
            "/api/chat",
            headers=headers,
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": 0,
                "language": "en",
                "message": "What medicine should I take?",
            },
        ).get_json()
        following = self.client.post(
            "/api/chat",
            headers=headers,
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": pending["session_revision"],
                "language": "en",
                "message": "What is paracetamol used for?",
            },
        ).get_json()

        self.assertEqual(pending["action"], "ASK_QUESTION")
        self.assertEqual(following["action"], "ASK_QUESTION")
        self.assertEqual(following["reason_codes"], ["PINECONE_NOT_CONFIGURED"])
        answered = self.client.post(
            "/api/chat",
            headers=headers,
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": following["session_revision"],
                "language": "en",
                "message": "Headache",
            },
        ).get_json()

        self.assertEqual(answered["intent"], "personal_medicine_recommendation")
        self.assertEqual(answered["pending_question_ids"], ["age"])

    def test_short_follow_up_and_correction_advance_without_repeating_known_facts(self):
        cases = (
            (
                "en",
                "What medicine should I take?",
                "Headache",
                "Actually, I am 35.",
                "When did this symptom begin",
            ),
            (
                "de",
                "Welches Medikament soll ich nehmen?",
                "Kopfschmerzen",
                "Eigentlich bin ich 35 Jahre alt.",
                "Wann hat dieses Symptom begonnen",
            ),
        )
        for language, request_text, symptom_text, correction, duration_prompt in cases:
            with self.subTest(language=language):
                session = self.client.post("/api/sessions").get_json()
                headers = {"Authorization": f"Bearer {session['access_token']}"}

                def send_turn(message, revision):
                    return self.client.post(
                        "/api/chat",
                        headers=headers,
                        json={
                            "session_id": session["session_id"],
                            "request_id": str(uuid4()),
                            "session_revision": revision,
                            "language": language,
                            "message": message,
                        },
                    ).get_json()

                request = send_turn(request_text, 0)
                symptom = send_turn(symptom_text, request["session_revision"])
                corrected_age = send_turn(correction, symptom["session_revision"])

                self.assertEqual(
                    symptom["intent"],
                    "personal_medicine_recommendation",
                )
                self.assertEqual(symptom["pending_question_ids"], ["age"])
                self.assertEqual(
                    corrected_age["pending_question_ids"],
                    ["symptom_duration"],
                )
                self.assertIn(duration_prompt, corrected_age["message"])

    def test_symptom_assessment_is_not_confused_with_product_data(self):
        response = self.send("en", "I have had a mild headache since yesterday.")

        result = response.get_json()
        self.assertEqual(result["intent"], "symptom_assessment")
        self.assertEqual(result["reason_codes"], ["NO_ACTIVE_REVIEWED_PROTOCOL"])
        self.assertEqual(result["assessment_status"], "intake_in_progress")
        self.assertEqual(result["pending_question_ids"], ["age"])
        self.assertNotIn("112", result["message"])

    def test_extracted_answer_to_pending_question_stays_in_assessment_flow(self):
        class ExtractionStub:
            def extract_facts(self, message, _assessment_state):
                if message.casefold() == "for me 25":
                    return FactExtraction(
                        facts=[
                            ExtractedFact(
                                name="subject_relationship",
                                value="self",
                                status="reported",
                                subject="self",
                                supporting_text="for me",
                            ),
                            ExtractedFact(
                                name="age",
                                value=25,
                                status="reported",
                                subject="self",
                                supporting_text="25",
                            ),
                        ]
                    )
                return FactExtraction()

        class UnexpectedRetriever:
            configured = True

            def search(self, _query, *, k=5):
                raise AssertionError("A pending assessment answer must not use Pinecone.")

        client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(),
            candidate_catalog=load_candidate_catalog(),
            llm_adapter=ExtractionStub(),
            retriever=UnexpectedRetriever(),
        ).test_client()
        session = client.post("/api/sessions").get_json()
        headers = {"Authorization": f"Bearer {session['access_token']}"}

        def send_turn(message, revision):
            return client.post(
                "/api/chat",
                headers=headers,
                json={
                    "session_id": session["session_id"],
                    "request_id": str(uuid4()),
                    "session_revision": revision,
                    "language": "en",
                    "message": message,
                },
            )

        symptom = send_turn("I have a headache", 0)
        self.assertEqual(symptom.status_code, 200)
        self.assertEqual(symptom.get_json()["pending_question_ids"], ["age"])

        answer = send_turn("for me 25", symptom.get_json()["session_revision"])

        self.assertEqual(answer.status_code, 200)
        result = answer.get_json()
        self.assertEqual(result["intent"], "symptom_assessment")
        self.assertEqual(result["pending_question_ids"], ["symptom_duration"])
        self.assertIn("When did this symptom begin", result["message"])

    def test_unextracted_answer_to_pending_duration_question_advances_intake(self):
        class ExtractionStub:
            def extract_facts(self, message, _assessment_state):
                if message.casefold() == "for me 25":
                    return FactExtraction(
                        facts=[
                            ExtractedFact(
                                name="subject_relationship",
                                value="self",
                                status="reported",
                                subject="self",
                                supporting_text="for me",
                            ),
                            ExtractedFact(
                                name="age",
                                value=25,
                                status="reported",
                                subject="self",
                                supporting_text="25",
                            ),
                        ]
                    )
                return FactExtraction()

        client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(),
            candidate_catalog=load_candidate_catalog(),
            llm_adapter=ExtractionStub(),
        ).test_client()
        session = client.post("/api/sessions").get_json()
        headers = {"Authorization": "Bearer " + session["access_token"]}

        def send_turn(message, revision):
            return client.post(
                "/api/chat",
                headers=headers,
                json={
                    "session_id": session["session_id"],
                    "request_id": str(uuid4()),
                    "session_revision": revision,
                    "language": "en",
                    "message": message,
                },
            )

        symptom = send_turn("headache", 0).get_json()
        age = send_turn("for me 25", symptom["session_revision"]).get_json()
        duration = send_turn("today morning", age["session_revision"]).get_json()
        allergies = send_turn(
            "no allergies", duration["session_revision"]
        ).get_json()
        medications = send_turn("none", allergies["session_revision"]).get_json()

        self.assertEqual(symptom["pending_question_ids"], ["age"])
        self.assertEqual(age["pending_question_ids"], ["symptom_duration"])
        self.assertNotEqual(duration["message"], age["message"])
        self.assertEqual(duration["pending_question_ids"], ["allergies"])
        self.assertIn("allergies", duration["message"].casefold())
        self.assertEqual(allergies["pending_question_ids"], ["current_medications"])
        self.assertIn("medicines", allergies["message"].casefold())
        self.assertEqual(medications["action"], "PHARMACIST_REFERRAL")
        self.assertNotEqual(medications["message"], allergies["message"])

    def test_negated_urgent_signals_do_not_add_routine_emergency_guidance(self):
        response = self.send("en", "I have no chest pressure or trouble breathing.")

        self.assertNotEqual(response.get_json()["action"], "EMERGENCY")
        self.assertNotIn("112", response.get_json()["message"])

    def test_inability_to_breathe_receives_immediate_emergency_guidance(self):
        for language, message in (
            ("en", "I can't breathe."),
            ("de", "Ich bekomme keine Luft."),
        ):
            with self.subTest(language=language):
                result = self.send(language, message).get_json()
                self.assertEqual(result["action"], "EMERGENCY")
                self.assertIn("112", result["message"])

    def test_ok_grants_pending_cloud_consent_and_replays_original_question(self):
        class StubRetriever:
            configured = True

            def __init__(self):
                self.queries = []

            def search(self, query, k):
                self.queries.append((query, k))
                return [
                    SimpleNamespace(
                        metadata={
                            "source_id": "REVIEWED-001",
                            "source_version": "v1",
                        },
                        page_content="Reviewed medicine information.",
                    )
                ]

        class StubLanguageAdapter:
            def __init__(self):
                self.questions = []

            def answer_general_information(self, question, excerpts):
                self.questions.append(question)
                return "Supported answer."

        retriever = StubRetriever()
        adapter = StubLanguageAdapter()
        client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(),
            llm_adapter=adapter,
            retriever=retriever,
        ).test_client()
        session = client.post("/api/sessions").get_json()
        headers = {"Authorization": f"Bearer {session['access_token']}"}

        def send(message, revision):
            return client.post(
                "/api/chat",
                headers=headers,
                json={
                    "session_id": session["session_id"],
                    "request_id": str(uuid4()),
                    "session_revision": revision,
                    "language": "en",
                    "message": message,
                },
            )

        result = send("What is paracetamol used for?", 0).get_json()
        self.assertEqual(result["action"], "GENERAL_INFORMATION")
        self.assertEqual(result["message"], "Supported answer.")
        self.assertTrue(result["ai_processing_consent"])
        self.assertEqual(
            retriever.queries,
            [("What is paracetamol used for?", 5)],
        )
        self.assertEqual(adapter.questions, ["What is paracetamol used for?"])

    def test_auto_cloud_consent_is_enabled_without_manual_checkbox(self):
        class StubRetriever:
            configured = True

            def __init__(self):
                self.queries = []

            def search(self, query, k):
                self.queries.append((query, k))
                return [
                    SimpleNamespace(
                        metadata={
                            "source_id": "REVIEWED-001",
                            "source_version": "v1",
                        },
                        page_content="Reviewed medicine information.",
                    )
                ]

        class StubLanguageAdapter:
            def __init__(self):
                self.questions = []

            def answer_general_information(self, question, excerpts):
                self.questions.append(question)
                return "Supported answer."

        retriever = StubRetriever()
        adapter = StubLanguageAdapter()
        client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(),
            llm_adapter=adapter,
            retriever=retriever,
        ).test_client()
        session = client.post("/api/sessions").get_json()
        headers = {"Authorization": f"Bearer {session['access_token']}"}

        def send(message, revision):
            return client.post(
                "/api/chat",
                headers=headers,
                json={
                    "session_id": session["session_id"],
                    "request_id": str(uuid4()),
                    "session_revision": revision,
                    "language": "en",
                    "message": message,
                },
            )

        result = send("What is paracetamol used for?", 0).get_json()

        self.assertEqual(result["action"], "GENERAL_INFORMATION")
        self.assertEqual(result["message"], "Supported answer.")
        self.assertTrue(result["ai_processing_consent"])
        self.assertEqual(retriever.queries, [("What is paracetamol used for?", 5)])
        self.assertEqual(adapter.questions, ["What is paracetamol used for?"])

    def test_readiness_reports_missing_clinical_wiring(self):
        readiness = self.client.get("/health/ready").get_json()

        self.assertTrue(readiness["recommendations_enabled"])
        self.assertEqual(readiness["active_protocol_count"], 0)
        self.assertFalse(readiness["retrieval_enabled"])
        self.assertTrue(readiness["pharmaceutical_checks_wired_to_chat"])
        self.assertTrue(readiness["catalog_data_pending"])

    def test_disabled_recommendations_do_not_block_symptom_intake(self):
        disabled_client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(recommendations_enabled=False),
        ).test_client()
        session = disabled_client.post("/api/sessions").get_json()
        response = disabled_client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={
                "session_id": session["session_id"],
                "request_id": str(uuid4()),
                "session_revision": 0,
                "language": "en",
                "message": "What medicine should I take?",
            },
        )

        result = response.get_json()
        self.assertEqual(result["action"], "ASK_QUESTION")
        self.assertEqual(result["intent"], "personal_medicine_recommendation")
        self.assertEqual(result["pending_question_ids"], ["symptoms"])
        self.assertEqual(result["reason_codes"], [])
        self.assertNotIn("112", result["message"])


if __name__ == "__main__":
    unittest.main()
