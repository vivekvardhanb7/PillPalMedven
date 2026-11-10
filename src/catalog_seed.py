"""Utility to persist the 30 candidate products without clinical approvals."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from src.catalog import (
    ProductRecord,
    load_candidate_catalog,
    persist_product_catalog,
)


def build_seed_catalog(
    *,
    active_ids: Sequence[str] | None = None,
) -> list[ProductRecord]:
    """Return all pending candidates; selecting IDs cannot create approvals."""
    if active_ids:
        raise ValueError(
            "The seed utility cannot approve products; use verified review records."
        )
    return load_candidate_catalog()


def seed_product_catalog_file(
    target_path: str | Path = "instance/product_catalog.json",
    *,
    active_ids: Sequence[str] | None = None,
) -> list[ProductRecord]:
    """Builds and persists a product catalog JSON file."""
    products = build_seed_catalog(active_ids=active_ids)
    persist_product_catalog(products, target_path)
    return products


if __name__ == "__main__":
    seed_product_catalog_file()
    print("Persisted all 30 candidate products with pending clinical status.")
