"""Comparative statement and scoring domain models."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from src.models.quote import NormalizedQuoteItem


class ApprovalStatus(str, Enum):
    """HOD Approval status."""
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VendorTrackRecord(BaseModel):
    """Historical performance records for vendor."""
    vendor_name: str
    on_time_delivery_pct: Decimal = Field(..., ge=0, le=100)
    quality_pass_pct: Decimal = Field(..., ge=0, le=100)
    active_disputes: int = Field(default=0, ge=0)


class RankedVendor(BaseModel):
    """Evaluated vendor with composite ranking and audit reasoning."""
    rank: int
    vendor_name: str
    normalized_quote: NormalizedQuoteItem
    price_score: Decimal = Field(..., ge=0, le=1)
    track_record: VendorTrackRecord
    composite_score: Decimal = Field(..., ge=0, le=1)
    is_l1: bool = False
    is_recommended: bool = False
    decision_rationale: str


class ComparativeStatement(BaseModel):
    """Complete comparative statement ready for executive review."""
    statement_id: str
    project_name: str
    package_title: str
    boq_quantity: Decimal
    budget_rate: Decimal
    total_budget: Decimal
    ranked_vendors: List[RankedVendor]
    l1_vendor_name: str
    recommended_vendor_name: str
    executive_summary: str
    status: ApprovalStatus = ApprovalStatus.PENDING_APPROVAL
    approved_by: Optional[str] = None
    approval_timestamp: Optional[datetime] = None
