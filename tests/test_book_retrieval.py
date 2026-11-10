import unittest
from unittest.mock import Mock
from uuid import uuid4

from langchain_core.documents import Document

from app import create_app
from src.catalog import load_candidate_catalog
from src.config import AppConfig
from src.retrieval import ApprovedPineconeRetriever, MedicalBookPineconeRetriever, create_pinecone_retriever


BOOK_SOURCE = r"data\Medical_book.pdf"


class BookRetrievalTests(unittest.TestCase):
    def retriever(self, documents):
        retriever = MedicalBookPineconeRetriever(
            api_key="test-key", index_name="medical-chatbot", source=BOOK_SOURCE,
        )
        retriever._store = Mock()
        retriever._store.similarity_search.return_value = documents
        return retriever

    def test_legacy_book_chunks_are_citable_without_fabricating_approval(self):
        original = Document(page_content="Book passage about insulin.", metadata={"source": BOOK_SOURCE})
        retriever = self.retriever([original])
        [result] = retriever.search("What is insulin?", k=3)
        retriever._store.similarity_search.assert_called_once_with(
            "What is insulin?", k=3, filter={"source": {"$eq": BOOK_SOURCE}},
        )
        self.assertEqual(result.page_content, original.page_content)
        self.assertEqual(result.metadata["title"], "Medical_book.pdf")
        self.assertEqual(result.metadata["source_version"], "unversioned")
        self.assertFalse(result.metadata["approved"])
        self.assertEqual(result.metadata["review_status"], "unreviewed")
        self.assertTrue(result.metadata["source_id"].startswith("BOOK-"))
        self.assertEqual(original.metadata, {"source": BOOK_SOURCE})
        self.assertEqual(retriever.search("insulin")[0].metadata["source_id"], result.metadata["source_id"])

    def test_other_sources_and_empty_passages_are_excluded(self):
        retriever = self.retriever([
            Document(page_content="Other book", metadata={"source": "other.pdf"}),
            Document(page_content="No provenance"),
            Document(page_content="  ", metadata={"source": BOOK_SOURCE}),
        ])
        self.assertEqual(retriever.search("question"), [])

    def test_approved_mode_still_excludes_unreviewed_book(self):
        retriever = ApprovedPineconeRetriever(api_key="key", index_name="index")
        retriever._store = Mock()
        retriever._store.similarity_search.return_value = [
            Document(page_content="Unreviewed book", metadata={"source": BOOK_SOURCE}),
        ]
        self.assertEqual(retriever.search("question"), [])
        self.assertTrue(retriever._store.similarity_search.call_args.kwargs["filter"]["approved"])

    def test_invalid_modes_and_empty_book_source_are_rejected(self):
        with self.assertRaises(ValueError):
            AppConfig(pinecone_retrieval_mode="everything")
        with self.assertRaises(ValueError):
            AppConfig(pinecone_retrieval_mode="medical_book", pinecone_book_source=" ")

    def test_factory_selects_book_mode_and_respects_explicit_missing_credentials(self):
        retriever = create_pinecone_retriever(
            api_key="", index_name="", mode="medical_book", source=BOOK_SOURCE,
        )
        self.assertIsInstance(retriever, MedicalBookPineconeRetriever)
        self.assertFalse(retriever.configured)
        with self.assertRaises(ValueError):
            create_pinecone_retriever(mode="everything")

    def client(self, retriever, adapter):
        return create_app(
            config=AppConfig(pinecone_retrieval_mode="medical_book"),
            candidate_catalog=load_candidate_catalog(),
            retriever=retriever, llm_adapter=adapter,
        ).test_client()

    def ask(self, client, question):
        session = client.post("/api/sessions").get_json()
        return client.post("/api/chat", headers={"Authorization": "Bearer " + session["access_token"]}, json={
            "session_id": session["session_id"], "request_id": str(uuid4()),
            "session_revision": 0, "language": "en", "message": question,
        })

    def test_chat_passes_book_passages_to_llm_and_returns_citations(self):
        retriever = self.retriever([
            Document(page_content="Insulin is made by the pancreas.", metadata={"source": BOOK_SOURCE}),
        ])
        adapter = Mock()
        adapter.answer_general_information.return_value = "Book-grounded answer."
        client = self.client(retriever, adapter)
        response = self.ask(client, "What is insulin?")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["action"], "GENERAL_INFORMATION")
        self.assertEqual(body["sources"][0]["title"], "Medical_book.pdf")
        self.assertEqual(body["sources"][0]["source_type"], "medical_book_reference")
        question, passages = adapter.answer_general_information.call_args.args
        self.assertEqual(question, "What is insulin?")
        self.assertEqual(passages[0]["text"], "Insulin is made by the pancreas.")
        self.assertEqual(body["sources"][0]["source_id"], passages[0]["source_id"])
        ready = client.get("/health/ready").get_json()
        self.assertTrue(ready["medical_book_retrieval"])
        self.assertFalse(ready["approved_source_retrieval"])

    def test_missing_passages_do_not_trigger_an_ungrounded_answer(self):
        adapter = Mock()
        response = self.ask(self.client(self.retriever([]), adapter), "What is insulin?")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reason_codes"], ["NO_SOURCE_MATCH"])
        adapter.answer_general_information.assert_not_called()

    def test_emergency_routing_precedes_book_retrieval(self):
        retriever = self.retriever([])
        adapter = Mock()
        response = self.ask(self.client(retriever, adapter), "I cannot breathe")
        self.assertEqual(response.get_json()["action"], "EMERGENCY")
        retriever._store.similarity_search.assert_not_called()
        adapter.answer_general_information.assert_not_called()


if __name__ == "__main__":
    unittest.main()
