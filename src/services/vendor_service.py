"""Vendor History & Trust Profile Store.

Codifies tribal vendor knowledge for Vinayak Group's Kolkata projects.
Adheres to clean-python rules.
"""

from decimal import Decimal
from typing import Dict, Optional
from src.models.comparative import VendorTrackRecord

BENCHMARK_DEFAULT_ON_TIME = Decimal("80.0")
BENCHMARK_DEFAULT_QUALITY = Decimal("80.0")


class VendorProfileRepository:
    """Repository storing recorded vendor quality, delivery rates, and disputes."""

    def __init__(self, initial_records: Optional[Dict[str, VendorTrackRecord]] = None):
        self._records: Dict[str, VendorTrackRecord] = initial_records or {}

    def get_track_record(self, vendor_name: str) -> VendorTrackRecord:
        """Retrieves performance metrics or returns a neutral benchmark profile."""
        clean_name = vendor_name.strip()
        # Direct lookup or case-insensitive search
        for name, record in self._records.items():
            if name.lower() == clean_name.lower():
                return record

        return VendorTrackRecord(
            vendor_name=clean_name,
            on_time_delivery_pct=BENCHMARK_DEFAULT_ON_TIME,
            quality_pass_pct=BENCHMARK_DEFAULT_QUALITY,
            active_disputes=0
        )

    def record_dispute(self, vendor_name: str, incident_note: str) -> VendorTrackRecord:
        """Increments dispute counter for a vendor upon site conflict."""
        record = self.get_track_record(vendor_name)
        updated = VendorTrackRecord(
            vendor_name=record.vendor_name,
            on_time_delivery_pct=record.on_time_delivery_pct,
            quality_pass_pct=max(record.quality_pass_pct - Decimal("5.0"), Decimal("0.0")),
            active_disputes=record.active_disputes + 1
        )
        self._records[record.vendor_name] = updated
        return updated


def get_default_vinayak_vendor_repo() -> VendorProfileRepository:
    """Pre-seeds repository with Vinayak Group's active Kolkata vendor panel."""
    records = {
        "Bengal Waterproofing Solutions": VendorTrackRecord(
            vendor_name="Bengal Waterproofing Solutions",
            on_time_delivery_pct=Decimal("70.0"),
            quality_pass_pct=Decimal("80.0"),
            active_disputes=2  # Flagged in Vinayak Vista project
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
    return VendorProfileRepository(records)
