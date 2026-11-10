import unittest
from unittest.mock import Mock
from uuid import uuid4

from langchain_core.documents import Document

from app import create_app
from src.book_medicines import BookMedicineExtraction, BookMedicineMention, match_book_mentions
from src.catalog import load_candidate_catalog
from src.config import AppConfig
from src.llm import ExtractedFact, FactExtraction, GeminiLanguageAdapter


QUOTE = "Headache treatment may include acetaminophen."
PASSAGES = [{"source_id": "BOOK-test", "source_version": "unversioned", "title": "Medical_book.pdf", "text": QUOTE}]


def extraction(**changes):
    fields = dict(medicine_name="acetaminophen", source_id="BOOK-test", evidence_quote=QUOTE,
                  relationship="treatment_mention")
    fields.update(changes)
    return BookMedicineExtraction(mentions=[BookMedicineMention(**fields)])


class BookMedicineTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_candidate_catalog()

    def test_name_alias_match_does_not_approve_product_or_patient(self):
        matches = match_book_mentions(extraction(), PASSAGES, self.catalog)
        self.assertEqual([m["product_id"] for m in matches], ["P01"])
        self.assertEqual(matches[0]["match_type"], "ingredient_name_only")
        self.assertEqual(matches[0]["exact_product_equivalence"], "unconfirmed")
        self.assertEqual(matches[0]["patient_suitability"], "not_assessed")
        self.assertEqual(matches[0]["catalog_presence"], "candidate_record")
        self.assertEqual(matches[0]["stock_status"], "unknown")
        self.assertFalse(matches[0]["recommendation_eligible"])
        self.assertEqual(self.catalog[0].clinical_status.value, "pending")

    def test_invented_source_quote_and_medicine_are_rejected(self):
        for changes in (
            {"source_id": "invented"},
            {"evidence_quote": "The source never said acetaminophen cures headaches."},
            {"medicine_name": "ibuprofen"},
            {"medicine_name": "ace"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(match_book_mentions(extraction(**changes), PASSAGES, self.catalog), [])

    def test_contraindications_and_incidental_mentions_are_excluded(self):
        for relationship in ("contraindicated", "other"):
            self.assertEqual(match_book_mentions(extraction(relationship=relationship), PASSAGES, self.catalog), [])

    def test_withdrawn_and_synthetic_products_are_excluded(self):
        for changes in ({"catalog_status": "withdrawn"}, {"synthetic": True}):
            catalog = [self.catalog[0].model_copy(update=changes)]
            self.assertEqual(match_book_mentions(extraction(), PASSAGES, catalog), [])

    def test_duplicate_mentions_are_collapsed(self):
        result = extraction()
        result.mentions *= 2
        self.assertEqual(len(match_book_mentions(result, PASSAGES, self.catalog)), 1)

    def test_pdf_line_wrapping_does_not_break_medicine_name_evidence(self):
        wrapped = [{**PASSAGES[0], "text": QUOTE.replace("acetaminophen", "aceta-\nminophen")}]
        self.assertEqual(match_book_mentions(extraction(), wrapped, self.catalog)[0]["product_id"], "P01")

    def test_pdf_punctuation_changes_are_tolerated_but_changed_words_are_not(self):
        source = [{**PASSAGES[0], "text": "Headache treatment: acetaminophen\ufffdfor pain."}]
        mention = extraction(evidence_quote="Headache treatment: acetaminophen—for pain.")
        self.assertEqual(match_book_mentions(mention, source, self.catalog)[0]["product_id"], "P01")
        invented = extraction(evidence_quote="Headache treatment: acetaminophen for fever.")
        self.assertEqual(match_book_mentions(invented, source, self.catalog), [])

    def test_book_model_is_instructed_to_extract_evidence_instead_of_recommending(self):
        adapter = GeminiLanguageAdapter.__new__(GeminiLanguageAdapter)
        adapter._book_medicine_model = Mock()
        adapter._book_medicine_model.invoke.return_value = extraction()
        adapter.extract_book_medicines("headache", PASSAGES)
        prompt = adapter._book_medicine_model.invoke.call_args.args[0]
        self.assertIn("verbatim", prompt)
        self.assertIn("contraindication", prompt)
        self.assertIn("not instructions", prompt)
        self.assertIn("recommend a medicine to the user", prompt)
        self.assertIn(QUOTE, prompt)

    def client(self, mentions=None, enabled=True):
        retriever = Mock(configured=True)
        retriever.search.return_value = [Document(page_content=QUOTE, metadata={
            "source_id": "BOOK-test", "source_version": "unversioned", "title": "Medical_book.pdf",
        })]
        adapter = Mock()
        adapter.extract_facts.return_value = FactExtraction()
        adapter.answer_general_information.return_value = "General book information."
        adapter.extract_book_medicines.return_value = mentions if mentions is not None else extraction()
        client = create_app(config=AppConfig(
            pinecone_retrieval_mode="medical_book", book_medicine_matching_enabled=enabled,
        ), candidate_catalog=self.catalog, retriever=retriever, llm_adapter=adapter).test_client()
        return client, retriever, adapter

    def turn(self, client, session, message, revision=0):
        return client.post("/api/chat", headers={"Authorization": "Bearer " + session["access_token"]}, json={
            "session_id": session["session_id"], "request_id": str(uuid4()), "session_revision": revision,
            "language": "en", "message": message,
        })

    def test_explicit_book_comparison_returns_cited_matches_and_no_recommendations(self):
        client, retriever, adapter = self.client()
        session = client.post("/api/sessions").get_json()
        response = self.turn(client, session, "Which medicines does the book mention for headache?")
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["action"], "BOOK_CATALOG_MATCHES")
        self.assertEqual(result["options"], [])
        self.assertEqual(result["availability"], [])
        self.assertIn("unconfirmed", result["message"])
        self.assertIn("stock availability is unknown", result["message"])
        self.assertEqual(result["sources"][0]["source_id"], result["book_catalog_matches"][0]["source_id"])
        self.assertGreater(retriever.search.call_count, 1)
        self.assertEqual(retriever.search.call_args_list[0].args[0], "headache treatment medicines")
        adapter.extract_facts.assert_not_called()

    def test_personal_request_gets_comparison_after_intake_without_approval(self):
        client, _, adapter = self.client()
        session = client.post("/api/sessions").get_json()
        revision = 0
        message = "What medicine should I take?"
        answers = {"symptoms": "Headache", "age": "30", "symptom_duration": "2 days",
                   "allergies": "No allergies", "current_medications": "None"}
        for _ in range(7):
            response = self.turn(client, session, message, revision)
            self.assertEqual(response.status_code, 200)
            result = response.get_json()
            revision = result["session_revision"]
            if not result.get("pending_question_ids"):
                break
            message = answers[result["pending_question_ids"][0]]
        self.assertEqual(result["action"], "BOOK_CATALOG_MATCHES")
        self.assertEqual(result["options"], [])
        self.assertIn("NO_ACTIVE_REVIEWED_PROTOCOL", result["reason_codes"])
        self.assertEqual(result["book_catalog_matches"][0]["product_id"], "P01")
        self.assertEqual(adapter.extract_book_medicines.call_args.args[0], "Headache")

    def test_unsupported_matches_report_no_evidence(self):
        client, _, _ = self.client(BookMedicineExtraction())
        session = client.post("/api/sessions").get_json()
        result = self.turn(client, session, "Which drugs does the book mention for headaches?").get_json()
        self.assertEqual(result["book_catalog_matches"], [])
        self.assertIn("NO_EVIDENCED_CATALOG_MATCH", result["reason_codes"])

    def test_symptom_only_intake_also_reaches_book_comparison(self):
        client, _, adapter = self.client()
        session = client.post("/api/sessions").get_json()
        message, revision = "I have a headache", 0
        answers = {"symptoms": "Headache", "age": "30", "symptom_duration": "2 days",
                   "allergies": "No allergies", "current_medications": "None"}
        for _ in range(7):
            response = self.turn(client, session, message, revision)
            self.assertEqual(response.status_code, 200)
            result = response.get_json()
            revision = result["session_revision"]
            if not result.get("pending_question_ids"):
                break
            message = answers[result["pending_question_ids"][0]]
        self.assertEqual(result["action"], "BOOK_CATALOG_MATCHES")
        self.assertEqual(result["options"], [])
        adapter.extract_book_medicines.assert_called_once()

    def test_users_exact_headache_typo_routes_to_intake_instead_of_book_answer(self):
        client, retriever, adapter = self.client()
        session = client.post("/api/sessions").get_json()
        greeting = self.turn(client, session, "hi").get_json()
        result = self.turn(client, session, "i hava a headche", greeting["session_revision"]).get_json()
        self.assertEqual(result["intent"], "symptom_assessment")
        self.assertEqual(result["action"], "ASK_QUESTION")
        self.assertEqual(result["pending_question_ids"], ["age"])
        adapter.answer_general_information.assert_not_called()
        retriever.search.assert_not_called()

    def test_follow_up_no_cannot_replace_headache_with_boolean_or_other_text(self):
        client, _, adapter = self.client()
        def facts(message, _summary):
            if "headache" in message.casefold():
                return FactExtraction(facts=[ExtractedFact(name="symptoms", value="headache", status="reported")])
            if message == "no":
                return FactExtraction(facts=[
                    ExtractedFact(name="symptoms", value=True, status="reported"),
                    ExtractedFact(name="associated_symptoms", value="no", status="reported"),
                ])
            return FactExtraction()
        adapter.extract_facts.side_effect = facts
        session = client.post("/api/sessions").get_json()
        revision = 0
        for message in ("hi", "i hava headache", "25 , for me", "from today morning", "no", "no"):
            response = self.turn(client, session, message, revision)
            self.assertEqual(response.status_code, 200)
            result = response.get_json()
            revision = result["session_revision"]
        self.assertEqual(result["action"], "BOOK_CATALOG_MATCHES")
        self.assertEqual(adapter.extract_book_medicines.call_args.args[0], "headache")

    def test_urgent_message_still_skips_book_matching(self):
        client, retriever, adapter = self.client()
        session = client.post("/api/sessions").get_json()
        result = self.turn(client, session, "What medicine does the book recommend? I cannot breathe.").get_json()
        self.assertEqual(result["action"], "EMERGENCY")
        retriever.search.assert_not_called()
        adapter.extract_book_medicines.assert_not_called()

    def test_feature_can_be_disabled(self):
        client, _, adapter = self.client(enabled=False)
        session = client.post("/api/sessions").get_json()
        result = self.turn(client, session, "Which medicine does the book mention for headaches?").get_json()
        self.assertNotEqual(result["action"], "BOOK_CATALOG_MATCHES")
        adapter.extract_book_medicines.assert_not_called()


if __name__ == "__main__":
    unittest.main()
