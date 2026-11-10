import tempfile
import unittest
from pathlib import Path

from src.config import AppConfig
from src.session_store import InMemorySessionStore
from app import create_app


class CatalogAdminTests(unittest.TestCase):
    def test_non_ascii_admin_token_is_rejected_without_server_error(self):
        client = create_app(config=AppConfig(catalog_admin_token="test-secret")).test_client()
        for path in (
            "/api/admin/products/P01/withdraw",
            "/api/admin/products/P01/activate",
            "/api/admin/products/activate_all",
        ):
            with self.subTest(path=path):
                response = client.post(path, headers={"Authorization": "Bearer invalid-ä"})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.get_json()["error"]["code"], "UNAUTHORIZED")

    def test_withdrawal_requires_admin_token_and_persists_without_disabling_feature(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = str(Path(directory) / "product_catalog.json")
            app = create_app(
                session_store=InMemorySessionStore(),
                config=AppConfig(catalog_admin_token="test-only-secret", product_catalog_path=catalog_path),
            )
            client = app.test_client()

            unauthorized = client.post("/api/admin/products/P01/withdraw")
            response = client.post(
                "/api/admin/products/P01/withdraw",
                headers={"Authorization": "Bearer test-only-secret"},
            )
            catalog_response = client.get("/api/catalog").get_json()
            ready = client.get("/health/ready").get_json()

            self.assertEqual(unauthorized.status_code, 401)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "withdrawn")
            self.assertTrue(response.get_json()["recommendations_enabled"])
            self.assertEqual(len(catalog_response["products"]), 30)
            withdrawn = next(
                product
                for product in catalog_response["products"]
                if product["product_id"] == "P01"
            )
            self.assertEqual(withdrawn["catalog_status"], "withdrawn")
            self.assertEqual(withdrawn["clinical_status"], "withdrawn")
            self.assertTrue(ready["recommendations_enabled"])
            self.assertTrue(Path(catalog_path).is_file())

    def test_activation_is_rejected_without_verified_clinical_review(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = str(Path(directory) / "product_catalog.json")
            token = "test-only-secret"
            app = create_app(
                session_store=InMemorySessionStore(),
                config=AppConfig(catalog_admin_token=token, product_catalog_path=catalog_path),
            )
            client = app.test_client()

            unauthorized = client.post("/api/admin/products/P01/activate")
            response = client.post(
                "/api/admin/products/P01/activate",
                headers={"Authorization": f"Bearer {token}"},
            )
            catalog_response = client.get("/api/catalog").get_json()
            ready = client.get("/health/ready").get_json()

            self.assertEqual(unauthorized.status_code, 401)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error"]["code"], "CLINICAL_REVIEW_REQUIRED")
            self.assertTrue(ready["catalog_data_pending"])
            self.assertEqual(ready["catalog_ready_product_ids"], [])

            p01 = next(
                product
                for product in catalog_response["products"]
                if product["product_id"] == "P01"
            )
            self.assertEqual(p01["catalog_status"], "candidate")
            self.assertEqual(p01["clinical_status"], "pending")

    def test_bulk_activation_is_rejected_without_verified_clinical_review(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = str(Path(directory) / "product_catalog.json")
            token = "test-only-secret"
            app = create_app(
                session_store=InMemorySessionStore(),
                config=AppConfig(catalog_admin_token=token, product_catalog_path=catalog_path),
            )
            client = app.test_client()

            response = client.post(
                "/api/admin/products/activate_all",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error"]["code"], "CLINICAL_REVIEW_REQUIRED")

            ready = client.get("/health/ready").get_json()
            self.assertTrue(ready["catalog_data_pending"])
            self.assertEqual(ready["catalog_ready_product_ids"], [])


if __name__ == "__main__":
    unittest.main()
