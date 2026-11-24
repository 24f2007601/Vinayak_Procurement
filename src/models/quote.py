"""Vendor quotation domain models."""

from decimal import Decimal
from enum import Enum
from typing import List
from pydantic import BaseModel, Field
from src.models.requisition import UnitOfMeasure


class FreightTerm(str, Enum):
    """Freight terms offered by vendor."""
    INCLUDED = "included"
    EXTRA_FIXED = "extra_fixed"
    EX_WAREHOUSE = "ex_warehouse"


class RawQuoteInput(BaseModel):
    """Direct parameters extracted from a vendor quotation document."""
    vendor_name: str = Field(..., description="Name of the bidding vendor")
    quoted_unit_rate: Decimal = Field(..., gt=0, description="Quoted unit rate in INR")
    quoted_unit: UnitOfMeasure = Field(..., description="Unit as quoted by vendor")
    gst_percent: Decimal = Field(default=Decimal("18.0"), ge=0, le=100)
    freight_term: FreightTerm = Field(default=FreightTerm.INCLUDED)
    freight_amount: Decimal = Field(default=Decimal("0.0"), ge=0)
    payment_terms_days: int = Field(default=30, ge=0, description="Credit days")
    delivery_lead_days: int = Field(default=7, ge=0, description="Lead time in days")
    exclusions: List[str] = Field(default_factory=list, description="Omitted scope or special conditions")


class NormalizedQuoteItem(BaseModel):
    """Standardized quote with deterministic landed cost aligned to BOQ."""
    vendor_name: str
    quoted_unit_rate: Decimal
    quoted_unit: UnitOfMeasure
    normalized_quantity: Decimal
    boq_unit: UnitOfMeasure
    base_material_cost: Decimal
    gst_amount: Decimal
    freight_amount: Decimal
    total_landed_cost: Decimal
    landed_rate_per_boq_unit: Decimal
    payment_terms_days: int
    delivery_lead_days: int
    exclusions: List[str]
