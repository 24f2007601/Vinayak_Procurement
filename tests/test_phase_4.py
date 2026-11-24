"""Unit and integration tests for Phase 4: Farvision ERP Bridge & Audit Trail."""

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.services.audit_service import audit_logger

client = TestClient(app)


def test_farvision_csv_and_json_export_endpoints():
    """Verifies that approved statements can be exported in both CSV and JSON formats."""
    # 1. Setup approved statement
    setup_payload = [
        {
            "vendor_name": "Asian Paints Chemical Division",
            "quoted_unit_rate": "8800.00",
            "quoted_unit": "drum",
            "gst_percent": "18.0",
            "freight_term": "extra_fixed",
            "freight_amount": "5000.00"
        }
    ]
    client.post(
        "/api/v1/comparatives/generate",
        params={
            "statement_id": "CS-PHASE4-TEST",
            "project_name": "Vinayak Amara",
            "package_title": "Waterproofing Tower 2",
            "boq_quantity": "12500.0",
            "boq_unit": "sq.ft",
            "budget_rate": "45.0",
            "coverage_per_drum": "250.0"
        },
        json=setup_payload
    )

    # Attempt export prior to approval should fail with 400
    pre_appr = client.get("/api/v1/erp/export/json/CS-PHASE4-TEST")
    assert pre_appr.status_code == 400
    assert "Cannot export unapproved" in pre_appr.json()["detail"]

    # Sign & Approve
    client.post("/api/v1/approvals/sign", json={
        "statement_id": "CS-PHASE4-TEST",
        "approved_by": "Senior Project Director"
    })

    # 2. Test JSON export
    json_res = client.get("/api/v1/erp/export/json/CS-PHASE4-TEST")
    assert json_res.status_code == 200
    data = json_res.json()
    assert data["po_header"]["farvision_po_id"] == "PO-CS-PHASE4-TEST"
    assert data["po_header"]["approved_by"] == "Senior Project Director"
    assert data["po_line_items"][0]["total_po_amount"] == 524200.0

    # 3. Test CSV export
    csv_res = client.get("/api/v1/erp/export/csv/CS-PHASE4-TEST")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert "PO-CS-PHASE4-TEST" in csv_res.text
    assert "PO_NUMBER,PROJECT,VENDOR" in csv_res.text


def test_audit_logs_endpoint():
    """Verifies that all events are preserved in the immutable audit log."""
    res = client.get("/api/v1/audit/logs")
    assert res.status_code == 200
    logs = res.json()
    assert len(logs) > 0
    # Confirm event types exist
    event_types = [l["event_type"] for l in logs]
    assert "HOD_APPROVED" in event_types or "ERP_EXPORTED" in event_types or "COMPARATIVE_GENERATED" in event_types
