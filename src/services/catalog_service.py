"""Farvision ERP Catalog Matching & Duplicate Requisition Detection.

Adheres to clean-python and clean-general rules:
- Max function < 40 lines
- Max file < 300 lines
- Single responsibility (G4)
- No magic numbers (G3)
"""

import re
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple
from src.models.requisition import FarvisionCatalogItem, SiteRequisition, UnitOfMeasure

SIMILARITY_MATCH_THRESHOLD = 0.35
DEFAULT_DUPLICATE_WINDOW_DAYS = 30


def _tokenize(text: str) -> set[str]:
    """Extracts lowercase alphanumeric words for token matching."""
    return set(re.findall(r"\b[a-z0-9]+\b", text.lower()))


def calculate_jaccard_similarity(text_a: str, text_b: str) -> float:
    """Computes Jaccard word-level similarity between two descriptions."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a.intersection(tokens_b)
    union = tokens_a.union(tokens_b)
    return len(intersection) / len(union)


def match_catalog_item(
    raw_description: str,
    catalog: List[FarvisionCatalogItem],
    threshold: float = SIMILARITY_MATCH_THRESHOLD
) -> Tuple[Optional[FarvisionCatalogItem], float]:
    """Matches an informal site material description to a canonical Farvision item."""
    if not raw_description or not catalog:
        return None, 0.0

    best_match: Optional[FarvisionCatalogItem] = None
    best_score: float = 0.0

    raw_tokens = _tokenize(raw_description)

    for item in catalog:
        # Check canonical name & item code tokens
        target_text = f"{item.canonical_name} {item.category} {item.item_code}"
        score = calculate_jaccard_similarity(raw_description, target_text)

        # Bonus for exact token matches (e.g., brand name like 'fixit' or 'fosroc')
        item_tokens = _tokenize(item.canonical_name)
        if any(tok in raw_tokens for tok in item_tokens if len(tok) > 4):
            score += 0.20

        if score > best_score:
            best_score = score
            best_match = item

    if best_score >= threshold:
        return best_match, round(best_score, 4)
    return None, round(best_score, 4)


def detect_duplicate_requisitions(
    new_requisition: SiteRequisition,
    active_requisitions: List[SiteRequisition],
    window_days: int = DEFAULT_DUPLICATE_WINDOW_DAYS
) -> List[str]:
    """Identifies overlapping orders for the same item code at the same site/tower."""
    warnings: List[str] = []

    for active in active_requisitions:
        # Match project and item code
        same_project = active.project_name.lower() == new_requisition.project_name.lower()
        same_tower = active.tower.lower() == new_requisition.tower.lower()
        same_item = active.item_code == new_requisition.item_code

        if same_project and same_tower and same_item:
            day_delta = abs((new_requisition.required_by_date - active.required_by_date).days)
            if day_delta <= window_days:
                warnings.append(
                    f"Duplicate warning: Requisition {active.requisition_id} already ordered "
                    f"{active.requested_quantity} {active.target_unit.value} for {active.tower} "
                    f"within {day_delta} days (required by {active.required_by_date})."
                )

    return warnings


def get_default_vinayak_catalog() -> List[FarvisionCatalogItem]:
    """Returns baseline Farvision catalog seeded with standard Kolkata packages."""
    return [
        FarvisionCatalogItem(
            item_code="MAT-WP-001",
            canonical_name="Dr. Fixit Fastflex Elastomeric Waterproofing Coating",
            category="Waterproofing",
            standard_unit=UnitOfMeasure.SQFT,
            budget_rate=Decimal("45.00")
        ),
        FarvisionCatalogItem(
            item_code="MAT-WP-002",
            canonical_name="Fosroc Brushbond Polymer Modified Cementitious Coating",
            category="Waterproofing",
            standard_unit=UnitOfMeasure.SQFT,
            budget_rate=Decimal("48.00")
        ),
        FarvisionCatalogItem(
            item_code="MAT-WP-003",
            canonical_name="Asian Paints SmartCare Damp Block 2K",
            category="Waterproofing",
            standard_unit=UnitOfMeasure.DRUM,
            budget_rate=Decimal("8500.00")
        ),
        FarvisionCatalogItem(
            item_code="MAT-STL-001",
            canonical_name="Fe 550 TMT Rebar (Tata Tiscon / Shyam Steel)",
            category="Steel",
            standard_unit=UnitOfMeasure.MT,
            budget_rate=Decimal("58000.00")
        ),
        FarvisionCatalogItem(
            item_code="MAT-CEM-001",
            canonical_name="PPC Cement Grade 43/53 (Ambuja / UltraTech)",
            category="Cement",
            standard_unit=UnitOfMeasure.KG,
            budget_rate=Decimal("7.20")
        )
    ]
