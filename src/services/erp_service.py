"""Farvision ERP Integration & Export Bridge Service.

Generates Farvision-compliant CSV and JSON Purchase Order (PO) staging files
and dispatches webhook notifications to ERP middleware.
Adheres to clean-code rules G1, G2, G3, G4.
"""

import csv
import io
from datetime import datetime
from typing import Any, Dict
from src.models.comparative import ComparativeStatement, ApprovalStatus


def generate_farvision_po_payload(statement: ComparativeStatement) -> Dict[str, Any]:
    """Builds a structured PO payload ready for Farvision ERP ingestion."""
    if statement.status != ApprovalStatus.APPROVED:
        raise ValueError("Cannot export unapproved comparative statement to ERP")

    recommended = next((v for v in statement.ranked_vendors if v.is_recommended), None)
    if not recommended:
        raise ValueError("No recommended vendor found on statement")

    q = recommended.normalized_quote

    return {
        "po_header": {
            "farvision_po_id": f"PO-{statement.statement_id}",
            "project_name": statement.project_name,
            "vendor_name": recommended.vendor_name,
            "approval_status": statement.status.value,
            "approved_by": statement.approved_by,
            "approved_at": str(statement.approval_timestamp or datetime.now()),
            "currency": "INR"
        },
        "po_line_items": [
            {
                "item_package": statement.package_title,
                "quantity": float(statement.boq_quantity),
                "unit": q.boq_unit.value,
                "quoted_rate": float(q.quoted_unit_rate),
                "quoted_unit": q.quoted_unit.value,
                "base_material_cost": float(q.base_material_cost),
                "gst_amount": float(q.gst_amount),
                "freight_amount": float(q.freight_amount),
                "landed_rate_per_boq_unit": float(q.landed_rate_per_boq_unit),
                "total_po_amount": float(q.total_landed_cost)
            }
        ],
        "audit_trail": {
            "composite_score": float(recommended.composite_score),
            "price_score": float(recommended.price_score),
            "is_l1_lowest_bidder": recommended.is_l1,
            "l1_bidder_name": statement.l1_vendor_name,
            "decision_rationale": recommended.decision_rationale
        }
    }


def generate_farvision_csv(statement: ComparativeStatement) -> str:
    """Exports approved PO into standard Farvision legacy CSV staging format."""
    payload = generate_farvision_po_payload(statement)
    header = payload["po_header"]
    item = payload["po_line_items"][0]
    audit = payload["audit_trail"]

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # CSV Header matching Farvision Purchase Order import schema
    writer.writerow([
        "PO_NUMBER",
        "PROJECT",
        "VENDOR",
        "ITEM_DESCRIPTION",
        "QUANTITY",
        "UNIT",
        "BASE_RATE",
        "TAX_AMOUNT",
        "FREIGHT_AMOUNT",
        "TOTAL_LANDED_AMOUNT",
        "APPROVED_BY",
        "APPROVAL_TIMESTAMP",
        "AUDIT_REASON"
    ])

    writer.writerow([
        header["farvision_po_id"],
        header["project_name"],
        header["vendor_name"],
        item["item_package"],
        item["quantity"],
        item["unit"],
        item["quoted_rate"],
        item["gst_amount"],
        item["freight_amount"],
        item["total_po_amount"],
        header["approved_by"],
        header["approved_at"],
        audit["decision_rationale"]
    ])

    return output.getvalue()
