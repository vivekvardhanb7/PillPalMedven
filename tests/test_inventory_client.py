import unittest
from unittest.mock import patch

from src.inventory import InventoryClient, InventoryUnavailable, SupabaseInventoryClient


class InventoryClientTests(unittest.TestCase):
    def test_supabase_checks_only_exact_inventory_id_and_quantity(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[{"quantity":2}]'
        with patch("src.inventory.urlopen", return_value=response) as mocked:
            self.assertTrue(SupabaseInventoryClient("https://project.supabase.co", "service-secret").availability("SKU/123"))
        request = mocked.call_args.args[0]
        self.assertIn("/rest/v1/medassist_inventory?", request.full_url)
        self.assertIn("inventory_product_id=eq.SKU%2F123", request.full_url)
        self.assertEqual(request.get_header("Apikey"), "service-secret")

    def test_supabase_zero_is_out_of_stock_but_missing_data_is_unknown(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        with patch("src.inventory.urlopen", return_value=response):
            client = SupabaseInventoryClient("https://project.supabase.co", "sb_secret_test")
            response.__enter__.return_value.read.return_value = b'[{"quantity":0}]'
            self.assertFalse(client.availability("SKU"))
            for payload in (b'[]', b'[{"quantity":null}]', b'[{"quantity":true}]', b'[{"quantity":-1}]', b'[{"quantity":1},{"quantity":2}]'):
                with self.subTest(payload=payload):
                    response.__enter__.return_value.read.return_value = payload
                    with self.assertRaises(InventoryUnavailable):
                        client.availability("SKU")

    def test_supabase_secret_key_is_not_sent_as_a_bearer_jwt(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[{"quantity":1}]'
        with patch("src.inventory.urlopen", return_value=response) as mocked:
            SupabaseInventoryClient("https://project.supabase.co", "sb_secret_test").availability("SKU")
        request = mocked.call_args.args[0]
        self.assertEqual(request.get_header("Apikey"), "sb_secret_test")
        self.assertIsNone(request.get_header("Authorization"))
    def test_non_utf8_inventory_response_is_reported_as_unavailable(self):
        from unittest.mock import MagicMock

        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"\xff"
        with patch("src.inventory.urlopen", return_value=response):
            with self.assertRaises(InventoryUnavailable):
                InventoryClient("https://inventory.example", None).availability("SKU-1")

    def test_availability_uses_a_bearer_token_when_configured(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"available": true}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.headers)
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("src.inventory.urlopen", side_effect=fake_urlopen):
            client = InventoryClient("https://inventory.example", "Bearer secret-token")
            self.assertTrue(client.availability("SKU-123"))

        self.assertEqual(
            captured["url"],
            "https://inventory.example/products/SKU-123/availability",
        )
        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(captured["headers"]["Accept"], "application/json")
        self.assertEqual(captured["timeout"], 3.0)

    def test_availability_rejects_invalid_payloads(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"available": "yes"}'

        with patch("src.inventory.urlopen", return_value=FakeResponse()):
            client = InventoryClient("https://inventory.example", "token")
            with self.assertRaises(InventoryUnavailable):
                client.availability("SKU-456")


if __name__ == "__main__":
    unittest.main()
