"""Unit tests for the Scoring & Comparative Statement Engine."""

from decimal import Decimal
import pytest
from src.models.quote import FreightTerm, RawQuoteInput
from src.models.requisition import UnitOfMeasure
from src.services.cost_engine import normalize_quote
from src.services.scoring_engine import (
    calculate_price_score,
    calculate_composite_score,
    generate_comparative_statement,
)


def test_price_score_calculation():
    l1 = Decimal("100000.00")
    v1 = Decimal("100000.00")
    v2 = Decimal("125000.00")

    assert calculate_price_score(v1, l1) == Decimal("1.0000")
    # 100,000 / 125,000 = 0.8
    assert calculate_price_score(v2, l1) == Decimal("0.8000")


def test_amara_tower_2_comparative_selection(
    amara_waterproofing_boq,
    sample_vendor_quotes,
    sample_vendor_tracks
):
    """End-to-end test on Vinayak Amara Tower-2 Waterproofing package.
    
    Demonstrates that Bengal Waterproofing is L1 on price alone,
    but Dulux Aquatech Pro wins recommendation due to higher reliability
    and zero dispute penalties.
    """
    boq_qty = amara_waterproofing_boq["boq_quantity"]
    boq_unit = amara_waterproofing_boq["boq_unit"]
    coverage = amara_waterproofing_boq["coverage_per_drum"]

    normalized_quotes = [
        normalize_quote(q, boq_qty, boq_unit, coverage_per_drum_sqft=coverage)
        for q in sample_vendor_quotes
    ]

    statement = generate_comparative_statement(
        statement_id="CS-AMR-T2-001",
        project_name=amara_waterproofing_boq["project"],
        package_title=amara_waterproofing_boq["package"],
        boq_quantity=boq_qty,
        budget_rate=amara_waterproofing_boq["budget_rate"],
        quotes=normalized_quotes,
        track_records=sample_vendor_tracks
    )

    # 1. Check L1 identified accurately on raw price
    assert statement.l1_vendor_name == "Bengal Waterproofing Solutions"

    # 2. Check that Asian Paints Chemical Division wins overall composite recommendation
    # (High on-time 92%, high quality 95%, 0 disputes, and lower landed cost than Dulux)
    assert statement.recommended_vendor_name == "Asian Paints Chemical Division"

    # 3. Verify rank 1 has the recommendation flag
    rank_1 = statement.ranked_vendors[0]
    assert rank_1.vendor_name == "Asian Paints Chemical Division"
    assert rank_1.is_recommended is True

    # 4. Verify Bengal Waterproofing was penalized for active disputes
    bengal_entry = next(v for v in statement.ranked_vendors if v.vendor_name == "Bengal Waterproofing Solutions")
    assert bengal_entry.is_l1 is True
    assert bengal_entry.is_recommended is False
    assert "active dispute" in bengal_entry.decision_rationale
