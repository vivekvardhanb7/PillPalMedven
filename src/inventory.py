import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class InventoryUnavailable(RuntimeError):
    pass


class InventoryClient:
    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        *,
        timeout_seconds: float = 3.0,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._token = self._normalize_token(token)
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _normalize_token(token: str | None) -> str | None:
        if token is None:
            return None
        normalized = token.strip()
        if normalized.lower().startswith("bearer "):
            normalized = normalized[7:].strip()
        return normalized or None

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def availability(self, inventory_product_id: str) -> bool:
        if not self._base_url:
            raise InventoryUnavailable("INVENTORY_API_URL is not configured.")
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        
        request = Request(
            f"{self._base_url}/products/{quote(inventory_product_id, safe='')}/availability",
            headers=headers,
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InventoryUnavailable(
                "The inventory service did not return a valid availability response."
            ) from error
        if not isinstance(body, dict) or not isinstance(body.get("available"), bool):
            raise InventoryUnavailable(
                "The inventory response must contain a boolean 'available' field."
            )
        return body["available"]


class SupabaseInventoryClient:
    """Read one exact inventory ID from the dedicated server-side table."""

    def __init__(self, url: str | None, service_key: str | None, *, timeout_seconds: float = 3.0):
        self._url = url.rstrip("/") if url else None
        self._service_key = service_key
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._url and self._service_key)

    def availability(self, inventory_product_id: str) -> bool:
        if not self.configured:
            raise InventoryUnavailable("Supabase inventory is not configured.")
        query = urlencode({"select": "quantity", "inventory_product_id": f"eq.{inventory_product_id}", "limit": "2"})
        headers = {"apikey": self._service_key, "Accept": "application/json"}
        if not self._service_key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self._service_key}"
        request = Request(f"{self._url}/rest/v1/medassist_inventory?{query}", headers=headers)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                rows = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InventoryUnavailable("Supabase inventory could not be checked.") from error
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise InventoryUnavailable("Inventory product was not found or is ambiguous.")
        quantity = rows[0].get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise InventoryUnavailable("Inventory quantity is unknown or invalid.")
        return quantity > 0
