"""Unit tests for the Deterministic Cost Engine."""

from decimal import Decimal
import pytest
from src.models.requisition import UnitOfMeasure
from src.models.quote import RawQuoteInput, FreightTerm
from src.services.cost_engine import (
    convert_quantity,
    calculate_tax,
    normalize_quote,
    round_currency,
)


def test_convert_quantity_sqm_to_sqft():
    sqm = Decimal("100.0")
    sqft = convert_quantity(sqm, UnitOfMeasure.SQM, UnitOfMeasure.SQFT)
    assert round_currency(sqft) == Decimal("1076.39")


def test_convert_quantity_sqft_to_sqm():
    sqft = Decimal("1076.39")
    sqm = convert_quantity(sqft, UnitOfMeasure.SQFT, UnitOfMeasure.SQM)
    assert round_currency(sqm) == Decimal("100.00")


def test_convert_quantity_drum_to_sqft_with_coverage():
    # 50 drums with 250 sq.ft coverage per drum = 12,500 sq.ft
    drums = Decimal("50.0")
    sqft = convert_quantity(
        drums,
        UnitOfMeasure.DRUM,
        UnitOfMeasure.SQFT,
        coverage_per_drum_sqft=Decimal("250.0")
    )
    assert sqft == Decimal("12500.0")


def test_calculate_tax_18_percent():
    base = Decimal("100000.00")
    tax = calculate_tax(base, Decimal("18.0"))
    assert tax == Decimal("18000.00")


def test_normalize_quote_freight_and_tax():
    quote = RawQuoteInput(
        vendor_name="Test Vendor",
        quoted_unit_rate=Decimal("40.00"),
        quoted_unit=UnitOfMeasure.SQFT,
        gst_percent=Decimal("18.0"),
        freight_term=FreightTerm.EXTRA_FIXED,
        freight_amount=Decimal("2000.00")
    )
    boq_qty = Decimal("1000.0")
    boq_unit = UnitOfMeasure.SQFT

    normalized = normalize_quote(quote, boq_qty, boq_unit)

    # Base: 1000 * 40 = 40,000
    # Tax: 18% of 40,000 = 7,200
    # Freight: 2,000
    # Landed Total: 49,200
    # Landed per unit: 49.20
    assert normalized.base_material_cost == Decimal("40000.00")
    assert normalized.gst_amount == Decimal("7200.00")
    assert normalized.freight_amount == Decimal("2000.00")
    assert normalized.total_landed_cost == Decimal("49200.00")
    assert normalized.landed_rate_per_boq_unit == Decimal("49.20")
