"""Evidence-checked book mentions; these never establish patient suitability."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.catalog import ProductRecord


class BookMedicineMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_name: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=100)
    evidence_quote: str = Field(min_length=10, max_length=1600)
    relationship: Literal["treatment_mention", "contraindicated", "other"]


class BookMedicineExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mentions: list[BookMedicineMention] = Field(default_factory=list, max_length=20)


# Name aliases only, never strength, formulation, brand, SKU or safety equivalence.
_NAME_ALIASES = (
    ("paracetamol", "acetaminophen"),
    ("ibuprofen",),
    ("diclofenac",),
    ("cetirizine", "cetirizin"),
    ("xylometazoline", "xylometazolin"),
    ("simeticone", "simethicone"),
    ("clotrimazole", "clotrimazol"),
    ("dexpanthenol",),
    ("loratadine", "loratadin"),
    ("levocetirizine", "levocetirizin"),
    ("desloratadine", "desloratadin"),
    ("naproxen",),
    ("aspirin", "acetylsalicylic acid"),
    ("loperamide", "loperamid"),
    ("pantoprazole", "pantoprazol"),
    ("dimenhydrinate",),
)


def _normalized(text: str) -> str:
    # PDF line wrapping can split a medicine name, e.g. "aceta-\nminophen".
    text = re.sub(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", "", text)
    # Keep word order and negation while tolerating PDF punctuation/OCR artifacts.
    return " ".join(re.findall(r"\w+", text.casefold()))


def _contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))


def catalog_medicine_search_terms(catalog: list[ProductRecord]) -> list[str]:
    terms = set()
    for product in catalog:
        if product.synthetic or product.catalog_status == "withdrawn":
            continue
        identity = _normalized(" ".join([product.name, *(product.active_ingredients or [])]))
        for group in _NAME_ALIASES:
            if any(_contains(identity, alias) for alias in group):
                terms.update(group)
    return sorted(terms)


def match_book_mentions(
    extraction: BookMedicineExtraction,
    passages: list[dict[str, str]],
    catalog: list[ProductRecord],
) -> list[dict[str, object]]:
    """Reject invented evidence/names; map only ingredient names in the catalog."""
    sources = {item["source_id"]: item for item in passages}
    matches = []
    seen = set()
    for mention in extraction.mentions:
        source = sources.get(mention.source_id)
        if source is None or mention.relationship != "treatment_mention":
            continue
        quote = _normalized(mention.evidence_quote)
        medicine = _normalized(mention.medicine_name)
        if quote not in _normalized(source["text"]) or not _contains(quote, medicine):
            continue
        for product in catalog:
            if product.synthetic or product.catalog_status == "withdrawn":
                continue
            identity = _normalized(" ".join([product.name, *(product.active_ingredients or [])]))
            aliases = [group for group in _NAME_ALIASES if any(_contains(identity, alias) for alias in group)]
            if not any(medicine in group for group in aliases):
                continue
            key = (product.product_id, mention.source_id)
            if key in seen:
                continue
            seen.add(key)
            matches.append({
                "product_id": product.product_id,
                "catalog_name": product.name,
                "book_medicine_name": mention.medicine_name,
                "source_id": mention.source_id,
                "evidence_quote": mention.evidence_quote,
                "match_type": "ingredient_name_only",
                "catalog_presence": "candidate_record",
                "stock_status": "unknown",
                "treatment_context": "ai_extracted",
                "exact_product_equivalence": "unconfirmed",
                "patient_suitability": "not_assessed",
                "recommendation_eligible": False,
            })
    return matches
