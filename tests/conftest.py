"""Test fixtures modeling real Vinayak Amara Tower-2 Waterproofing package."""

from decimal import Decimal
import pytest
from src.models.requisition import UnitOfMeasure, SiteRequisition
from src.models.quote import RawQuoteInput, FreightTerm
from src.models.comparative import VendorTrackRecord


@pytest.fixture
def amara_waterproofing_boq():
    """Canonical BOQ specification for Vinayak Amara Tower-2."""
    return {
        "project": "Vinayak Amara",
        "tower": "Tower-2",
        "package": "Waterproofing at Vinayak Amara, Tower-2",
        "boq_quantity": Decimal("12500.0"),  # 12,500 sq.ft
        "boq_unit": UnitOfMeasure.SQFT,
        "budget_rate": Decimal("45.0"),      # ₹45/sq.ft
        "coverage_per_drum": Decimal("250.0") # 250 sq.ft per 20L drum
    }


@pytest.fixture
def sample_vendor_quotes():
    """Three real-world style competing vendor quotes."""
    return [
        # Vendor 1: Lowest base rate, but excluded surface grinding and 2 past disputes
        RawQuoteInput(
            vendor_name="Bengal Waterproofing Solutions",
            quoted_unit_rate=Decimal("35.00"),
            quoted_unit=UnitOfMeasure.SQFT,
            gst_percent=Decimal("18.0"),
            freight_term=FreightTerm.INCLUDED,
            payment_terms_days=30,
            delivery_lead_days=10,
            exclusions=["Surface grinding and crack filling extra at actuals"]
        ),
        # Vendor 2: Quoted in SQ.M (requires conversion), all-inclusive, 0 disputes
        RawQuoteInput(
            vendor_name="Dulux Aquatech Pro",
            quoted_unit_rate=Decimal("410.00"),  # ₹410 per sq.m = ~₹38.09/sq.ft
            quoted_unit=UnitOfMeasure.SQM,
            gst_percent=Decimal("18.0"),
            freight_term=FreightTerm.INCLUDED,
            payment_terms_days=45,
            delivery_lead_days=3,
            exclusions=[]
        ),
        # Vendor 3: Quoted in DRUMS (20L packaging), ₹3,500 per drum, freight extra
        RawQuoteInput(
            vendor_name="Asian Paints Chemical Division",
            quoted_unit_rate=Decimal("8800.00"),
            quoted_unit=UnitOfMeasure.DRUM,
            gst_percent=Decimal("18.0"),
            freight_term=FreightTerm.EXTRA_FIXED,
            freight_amount=Decimal("5000.00"),
            payment_terms_days=30,
            delivery_lead_days=5,
            exclusions=["Unloading at site by client"]
        )
    ]


@pytest.fixture
def sample_vendor_tracks():
    """Recorded vendor history for Vinayak's approved panel."""
    return {
        "Bengal Waterproofing Solutions": VendorTrackRecord(
            vendor_name="Bengal Waterproofing Solutions",
            on_time_delivery_pct=Decimal("70.0"),
            quality_pass_pct=Decimal("80.0"),
            active_disputes=2  # High dispute penalty
        ),
        "Dulux Aquatech Pro": VendorTrackRecord(
            vendor_name="Dulux Aquatech Pro",
            on_time_delivery_pct=Decimal("98.0"),
            quality_pass_pct=Decimal("99.0"),
            active_disputes=0
        ),
        "Asian Paints Chemical Division": VendorTrackRecord(
            vendor_name="Asian Paints Chemical Division",
            on_time_delivery_pct=Decimal("92.0"),
            quality_pass_pct=Decimal("95.0"),
            active_disputes=0
        )
    }
