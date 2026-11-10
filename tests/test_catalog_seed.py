from datetime import date
import tempfile
import unittest
from pathlib import Path

from app import create_app
from src.catalog import ClinicalStatus, load_product_catalog, persist_product_catalog
from src.catalog_seed import build_seed_catalog, seed_product_catalog_file
from src.config import AppConfig
from src.recommendations import catalog_record_ready
from src.session_store import InMemorySessionStore


class CatalogSeedTests(unittest.TestCase):
    def test_build_seed_catalog_keeps_all_records_pending(self):
        products = build_seed_catalog()

        self.assertEqual(len(products), 30)
        self.assertEqual(len({p.product_id for p in products}), 30)
        for product in products:
            self.assertFalse(catalog_record_ready(product))
            self.assertEqual(product.catalog_status, "candidate")
            self.assertEqual(product.clinical_status, "pending")
            self.assertIsNone(product.reviewed_by)
            self.assertIsNone(product.approval_date)

    def test_seed_utility_cannot_mark_selected_products_approved(self):
        with self.assertRaisesRegex(ValueError, "cannot approve products"):
            build_seed_catalog(active_ids=["P11", "P15"])

    def test_seed_file_persistence_and_loading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_file = Path(temp_dir) / "seeded_catalog.json"
            seeded = seed_product_catalog_file(catalog_file)

            self.assertTrue(catalog_file.exists())
            loaded = load_product_catalog(catalog_file)
            self.assertEqual(len(loaded), 30)
            self.assertEqual([p.product_id for p in loaded], [p.product_id for p in seeded])
            self.assertTrue(all(not catalog_record_ready(product) for product in loaded))

    def test_loader_discards_generated_placeholder_approvals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_file = Path(temp_dir) / "product_catalog.json"
            candidates = build_seed_catalog()
            generated_records = [
                product.model_copy(
                    update={
                        "catalog_status": "active",
                        "clinical_status": ClinicalStatus.APPROVED,
                        "reviewed_by": "Clinical Pharmacist Reviewer",
                        "approval_date": date(2026, 11, 10),
                    }
                )
                for product in candidates
            ]
            persist_product_catalog(generated_records, catalog_file)

            loaded = load_product_catalog(catalog_file)

            self.assertTrue(all(product.clinical_status == ClinicalStatus.PENDING for product in loaded))
            self.assertTrue(all(product.catalog_status == "candidate" for product in loaded))
            self.assertTrue(all(product.reviewed_by is None for product in loaded))

    def test_health_ready_with_seeded_catalog_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_file = Path(temp_dir) / "product_catalog.json"
            seed_product_catalog_file(catalog_file)

            app = create_app(
                session_store=InMemorySessionStore(),
                config=AppConfig(product_catalog_path=str(catalog_file)),
            )
            client = app.test_client()
            health = client.get("/health/ready").get_json()

            self.assertEqual(health["candidate_product_count"], 30)
            self.assertTrue(health["catalog_data_pending"])
            self.assertEqual(health["catalog_ready_product_ids"], [])


if __name__ == "__main__":
    unittest.main()
