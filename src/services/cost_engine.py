"""Deterministic Cost & Unit Normalizer Engine.

Zero LLM Math: Pure functions performing exact conversions and landed costs.
Adheres to clean-code rules G1, G2, G3, G4.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from src.constants import SQFT_PER_SQM, LITRES_PER_STANDARD_DRUM, KG_PER_METRIC_TON
from src.models.requisition import UnitOfMeasure
from src.models.quote import RawQuoteInput, NormalizedQuoteItem, FreightTerm

TWO_DECIMALS = Decimal("0.01")


def round_currency(amount: Decimal) -> Decimal:
    """Rounds amount to 2 decimal places using standard financial rounding."""
    return amount.quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)


def convert_quantity(
    quantity: Decimal,
    from_unit: UnitOfMeasure,
    to_unit: UnitOfMeasure,
    coverage_per_drum_sqft: Optional[Decimal] = None
) -> Decimal:
    """Converts a quantity between supported units.
    
    Clean-code G4: Single responsibility conversion.
    """
    if from_unit == to_unit:
        return quantity

    # Area conversions: SQFT <-> SQM
    if from_unit == UnitOfMeasure.SQM and to_unit == UnitOfMeasure.SQFT:
        return quantity * SQFT_PER_SQM
    if from_unit == UnitOfMeasure.SQFT and to_unit == UnitOfMeasure.SQM:
        return quantity / SQFT_PER_SQM

    # Mass conversions: MT <-> KG
    if from_unit == UnitOfMeasure.MT and to_unit == UnitOfMeasure.KG:
        return quantity * KG_PER_METRIC_TON
    if from_unit == UnitOfMeasure.KG and to_unit == UnitOfMeasure.MT:
        return quantity / KG_PER_METRIC_TON

    # Liquid packaging: DRUM <-> LITRE
    if from_unit == UnitOfMeasure.DRUM and to_unit == UnitOfMeasure.LITRE:
        return quantity * LITRES_PER_STANDARD_DRUM
    if from_unit == UnitOfMeasure.LITRE and to_unit == UnitOfMeasure.DRUM:
        return quantity / LITRES_PER_STANDARD_DRUM

    # Special construction material coverage: SQFT <-> DRUMS
    if coverage_per_drum_sqft and coverage_per_drum_sqft > 0:
        if from_unit == UnitOfMeasure.SQFT and to_unit == UnitOfMeasure.DRUM:
            return (quantity / coverage_per_drum_sqft).quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)
        if from_unit == UnitOfMeasure.DRUM and to_unit == UnitOfMeasure.SQFT:
            return quantity * coverage_per_drum_sqft

    raise ValueError(f"Unsupported unit conversion from {from_unit.value} to {to_unit.value}")


def calculate_tax(base_amount: Decimal, gst_percent: Decimal) -> Decimal:
    """Calculates GST amount on base material."""
    tax = base_amount * (gst_percent / Decimal("100.0"))
    return round_currency(tax)


def normalize_quote(
    raw_quote: RawQuoteInput,
    boq_quantity: Decimal,
    boq_unit: UnitOfMeasure,
    coverage_per_drum_sqft: Optional[Decimal] = None
) -> NormalizedQuoteItem:
    """Computes exact landed cost and normalizes unit rate to canonical BOQ."""
    # Convert required BOQ quantity into vendor's quoting unit
    required_in_vendor_unit = convert_quantity(
        quantity=boq_quantity,
        from_unit=boq_unit,
        to_unit=raw_quote.quoted_unit,
        coverage_per_drum_sqft=coverage_per_drum_sqft
    )

    base_material_cost = round_currency(required_in_vendor_unit * raw_quote.quoted_unit_rate)
    gst_amount = calculate_tax(base_material_cost, raw_quote.gst_percent)

    freight_amount = Decimal("0.0")
    if raw_quote.freight_term == FreightTerm.EXTRA_FIXED:
        freight_amount = raw_quote.freight_amount
    elif raw_quote.freight_term == FreightTerm.EX_WAREHOUSE and raw_quote.freight_amount > 0:
        freight_amount = raw_quote.freight_amount

    total_landed = round_currency(base_material_cost + gst_amount + freight_amount)
    landed_rate_per_boq = round_currency(total_landed / boq_quantity)

    return NormalizedQuoteItem(
        vendor_name=raw_quote.vendor_name,
        quoted_unit_rate=raw_quote.quoted_unit_rate,
        quoted_unit=raw_quote.quoted_unit,
        normalized_quantity=required_in_vendor_unit,
        boq_unit=boq_unit,
        base_material_cost=base_material_cost,
        gst_amount=gst_amount,
        freight_amount=freight_amount,
        total_landed_cost=total_landed,
        landed_rate_per_boq_unit=landed_rate_per_boq,
        payment_terms_days=raw_quote.payment_terms_days,
        delivery_lead_days=raw_quote.delivery_lead_days,
        exclusions=raw_quote.exclusions
    )
