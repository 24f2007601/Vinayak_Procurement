"""Automated integration tests for Phase 3 & Phase 4 API endpoints."""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_health_check_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_catalog_endpoint():
    response = client.get("/api/v1/catalog")
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 4
    assert any(i["item_code"] == "MAT-WP-001" for i in items)


def test_requisition_parse_endpoint():
    payload = {
        "raw_text": "Need urgent dr fixit fastflex chemical for waterproofing at Amara tower 2",
        "project_name": "Vinayak Amara",
        "tower": "Tower-2",
        "quantity": "50.0",
        "required_by_date": "2026-12-15"
    }
    response = client.post("/api/v1/requisitions/parse", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["matched_catalog_item"]["item_code"] == "MAT-WP-001"
    assert data["match_confidence"] >= 0.35


def test_end_to_end_comparative_and_approval_flow():
    # 1. Post quotes to comparative generator
    payload = {
        "statement_id": "CS-AMR-T2-E2E",
        "project_name": "Vinayak Amara",
        "package_title": "Waterproofing at Vinayak Amara, Tower-2",
        "boq_quantity": "12500.0",
        "boq_unit": "sq.ft",
        "budget_rate": "45.0",
        "coverage_per_drum": "250.0",
        "quotes": [
            {
                "vendor_name": "Bengal Waterproofing Solutions",
                "quoted_unit_rate": "35.00",
                "quoted_unit": "sq.ft",
                "gst_percent": "18.0",
                "freight_term": "included"
            },
            {
                "vendor_name": "Asian Paints Chemical Division",
                "quoted_unit_rate": "8800.00",
                "quoted_unit": "drum",
                "gst_percent": "18.0",
                "freight_term": "extra_fixed",
                "freight_amount": "5000.00"
            }
        ]
    }
    comp_res = client.post(
        "/api/v1/comparatives/generate",
        params={
            "statement_id": payload["statement_id"],
            "project_name": payload["project_name"],
            "package_title": payload["package_title"],
            "boq_quantity": payload["boq_quantity"],
            "boq_unit": payload["boq_unit"],
            "budget_rate": payload["budget_rate"],
            "coverage_per_drum": payload["coverage_per_drum"]
        },
        json=payload["quotes"]
    )
    assert comp_res.status_code == 200
    cs = comp_res.json()
    assert cs["l1_vendor_name"] == "Bengal Waterproofing Solutions"
    assert cs["recommended_vendor_name"] == "Asian Paints Chemical Division"

    # 2. HOD Approves
    appr_res = client.post("/api/v1/approvals/sign", json={
        "statement_id": "CS-AMR-T2-E2E",
        "approved_by": "Arindam Mukherjee (HOD Projects)"
    })
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "APPROVED"

    # 3. Export to Farvision PO staging payload
    erp_res = client.get("/api/v1/erp/export/CS-AMR-T2-E2E")
    assert erp_res.status_code == 200
    po = erp_res.json()["farvision_po_payload"]
    assert po["vendor_name"] == "Asian Paints Chemical Division"
    assert po["total_po_amount"] == 524200.0
    assert po["approved_by"] == "Arindam Mukherjee (HOD Projects)"
