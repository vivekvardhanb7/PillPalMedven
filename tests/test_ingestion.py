import unittest

from langchain_core.documents import Document

from src.documents import filter_to_minimal_docs
from store_index import validate_staging_index_name


class IngestionTests(unittest.TestCase):
    def test_ingested_pages_keep_provenance_and_remain_unapproved(self):
        source = Document(
            page_content="Unreviewed source text",
            metadata={"source": "data/Medical_book.pdf", "page": 12},
        )

        [chunk] = filter_to_minimal_docs([source])

        self.assertEqual(chunk.metadata["source"], "Medical_book.pdf")
        self.assertEqual(chunk.metadata["page"], 12)
        self.assertEqual(chunk.metadata["jurisdiction"], "DE")
        self.assertEqual(chunk.metadata["source_version"], "unreviewed")
        self.assertFalse(chunk.metadata["approved"])

    def test_ingestion_accepts_only_staging_index_names(self):
        self.assertEqual(
            validate_staging_index_name("medical-chatbot-staging"),
            "medical-chatbot-staging",
        )
        with self.assertRaises(ValueError):
            validate_staging_index_name("medical-chatbot")


if __name__ == "__main__":
    unittest.main()
