"""FastAPI Application for Vinayak Procurement Copilot.

Provides REST endpoints for:
1. Requisition capture & catalog matching
2. Vendor quote ingestion & normalization
3. Comparative statement generation & HOD sign-off
4. Farvision ERP PO staging export
5. Health check
"""

from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.models.requisition import SiteRequisition, FarvisionCatalogItem, UnitOfMeasure
from src.models.quote import RawQuoteInput, NormalizedQuoteItem
from src.models.comparative import ComparativeStatement, ApprovalStatus
from src.services.catalog_service import (
    match_catalog_item,
    detect_duplicate_requisitions,
    get_default_vinayak_catalog,
)
from src.services.extractor_service import parse_quote_heuristic, extract_quote_with_groq
from src.services.cost_engine import normalize_quote
from src.services.scoring_engine import generate_comparative_statement
from src.services.vendor_service import get_default_vinayak_vendor_repo

app = FastAPI(
    title="Vinayak Procurement Copilot API",
    version="1.0.0",
    description="AI-assisted procurement: from site requirement to vendor comparative statement."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory stores for runtime
_catalog = get_default_vinayak_catalog()
_vendor_repo = get_default_vinayak_vendor_repo()
_requisitions: List[SiteRequisition] = []
_active_statements: dict[str, ComparativeStatement] = {}


class RequisitionParseRequest(BaseModel):
    raw_text: str = Field(..., description="Informal WhatsApp or site audio transcription")
    project_name: str = Field(default="Vinayak Amara")
    tower: str = Field(default="Tower-2")
    quantity: Decimal = Field(gt=0)
    required_by_date: str = Field(description="YYYY-MM-DD")


class QuoteIngestRequest(BaseModel):
    raw_document_text: str
    vendor_hint: Optional[str] = None


class ApprovalActionRequest(BaseModel):
    statement_id: str
    approved_by: str
    remarks: Optional[str] = None


@app.get("/health", tags=["System"])
def health_check():
    """Health and readiness check."""
    return {"status": "ok", "service": "Vinayak Procurement Copilot", "version": "1.0.0"}


@app.get("/api/v1/catalog", response_model=List[FarvisionCatalogItem], tags=["Catalog"])
def list_catalog():
    """Returns canonical Farvision ERP material master catalog."""
    return _catalog


@app.post("/api/v1/requisitions/parse", tags=["Requisition"])
def parse_and_match_requisition(req: RequisitionParseRequest):
    """Parses site engineer input, matches Farvision item, and checks duplicates."""
    from datetime import datetime
    req_date = datetime.strptime(req.required_by_date, "%Y-%m-%d").date()

    matched_item, score = match_catalog_item(req.raw_text, _catalog)
    if not matched_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not match material description to Farvision item master."
        )

    new_requisition = SiteRequisition(
        requisition_id=f"REQ-{len(_requisitions)+1:03d}",
        project_name=req.project_name,
        tower=req.tower,
        item_code=matched_item.item_code,
        material_description=matched_item.canonical_name,
        requested_quantity=req.quantity,
        target_unit=matched_item.standard_unit,
        required_by_date=req_date
    )

    duplicate_warnings = detect_duplicate_requisitions(new_requisition, _requisitions)
    _requisitions.append(new_requisition)

    return {
        "requisition": new_requisition,
        "matched_catalog_item": matched_item,
        "match_confidence": score,
        "duplicate_warnings": duplicate_warnings
    }


@app.post("/api/v1/quotes/extract", response_model=RawQuoteInput, tags=["Quotes"])
def extract_quote(req: QuoteIngestRequest):
    """Extracts raw unstructured vendor quotation into validated Pydantic schema."""
    return extract_quote_with_groq(req.raw_document_text, vendor_hint=req.vendor_hint)


@app.post("/api/v1/comparatives/generate", response_model=ComparativeStatement, tags=["Comparative"])
def build_comparative_statement(
    statement_id: str,
    project_name: str,
    package_title: str,
    boq_quantity: Decimal,
    boq_unit: UnitOfMeasure,
    budget_rate: Decimal,
    quotes: List[RawQuoteInput],
    coverage_per_drum: Optional[Decimal] = None
):
    """Normalizes all quotes and generates weighted comparative statement."""
    normalized = [
        normalize_quote(q, boq_quantity, boq_unit, coverage_per_drum_sqft=coverage_per_drum)
        for q in quotes
    ]

    tracks = {
        q.vendor_name: _vendor_repo.get_track_record(q.vendor_name)
        for q in normalized
    }

    statement = generate_comparative_statement(
        statement_id=statement_id,
        project_name=project_name,
        package_title=package_title,
        boq_quantity=boq_quantity,
        budget_rate=budget_rate,
        quotes=normalized,
        track_records=tracks
    )

    _active_statements[statement_id] = statement
    return statement


@app.post("/api/v1/approvals/sign", response_model=ComparativeStatement, tags=["Approval"])
def approve_comparative(action: ApprovalActionRequest):
    """HOD reviews and signs off on recommended comparative statement."""
    from datetime import datetime
    statement = _active_statements.get(action.statement_id)
    if not statement:
        raise HTTPException(status_code=404, detail="Comparative statement not found")

    statement.status = ApprovalStatus.APPROVED
    statement.approved_by = action.approved_by
    statement.approval_timestamp = datetime.now()
    return statement


@app.get("/api/v1/erp/export/{statement_id}", tags=["Farvision ERP"])
def export_to_farvision_po(statement_id: str):
    """Generates Farvision ERP PO staging payload."""
    statement = _active_statements.get(statement_id)
    if not statement:
        raise HTTPException(status_code=404, detail="Comparative statement not found")
    if statement.status != ApprovalStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Cannot export unapproved comparative statement")

    recommended = next(v for v in statement.ranked_vendors if v.is_recommended)
    q = recommended.normalized_quote

    return {
        "farvision_po_payload": {
            "po_reference": f"PO-FARVISION-{statement.statement_id}",
            "project_name": statement.project_name,
            "vendor_name": recommended.vendor_name,
            "item_package": statement.package_title,
            "quantity": float(statement.boq_quantity),
            "unit": q.boq_unit.value,
            "rate_per_unit": float(q.landed_rate_per_boq_unit),
            "total_po_amount": float(q.total_landed_cost),
            "approved_by": statement.approved_by,
            "approval_date": str(statement.approval_timestamp),
            "audit_rationale": recommended.decision_rationale
        }
    }


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
def executive_cockpit_dashboard():
    """Serves high-density responsive HOD Procurement Cockpit."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Vinayak Group — AI Procurement Copilot</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans p-6">
      <div class="max-w-6xl mx-auto space-y-6">
        <!-- Header -->
        <header class="bg-white p-6 rounded-xl shadow-sm border border-slate-200 flex justify-between items-center">
          <div>
            <h1 class="text-2xl font-bold text-slate-900">Vinayak Procurement Copilot</h1>
            <p class="text-sm text-slate-500">Kolkata Active Projects &bull; Site Requirement to Farvision PO</p>
          </div>
          <span class="px-3 py-1 bg-emerald-100 text-emerald-800 text-xs font-semibold rounded-full">Phase 1-4 Operational</span>
        </header>

        <!-- Executive Card -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-lg font-bold text-slate-900">Current Work Package: Vinayak Amara, Tower-2</h2>
            <span class="text-sm text-slate-500">BOQ: 12,500 sq.ft &bull; Baseline Budget: ₹45.00/sq.ft</span>
          </div>

          <!-- Comparative Statement Table -->
          <div class="overflow-x-auto">
            <table class="w-full text-left text-sm border-collapse">
              <thead>
                <tr class="border-b border-slate-200 bg-slate-50 text-slate-600">
                  <th class="p-3">Rank</th>
                  <th class="p-3">Vendor</th>
                  <th class="p-3">Quoted Rate</th>
                  <th class="p-3">GST & Freight</th>
                  <th class="p-3">Total Landed Cost</th>
                  <th class="p-3">Track Record</th>
                  <th class="p-3">Score</th>
                  <th class="p-3">Recommendation</th>
                </tr>
              </thead>
              <tbody>
                <tr class="border-b border-slate-100 bg-emerald-50/50">
                  <td class="p-3 font-bold text-emerald-700">#1 (Recommended)</td>
                  <td class="p-3 font-semibold">Asian Paints Chemical Division</td>
                  <td class="p-3">₹8,800 / drum (50 drums)</td>
                  <td class="p-3">18% GST + ₹5,000 Freight</td>
                  <td class="p-3 font-bold text-slate-900">₹5,24,200.00</td>
                  <td class="p-3 text-xs">92% On-time &bull; 0 Disputes</td>
                  <td class="p-3 font-mono font-bold text-emerald-700">0.9634</td>
                  <td class="p-3 text-xs text-slate-600">Recommended over L1 due to zero dispute risk & reliable delivery.</td>
                </tr>
                <tr class="border-b border-slate-100">
                  <td class="p-3 font-bold text-slate-500">#2 (L1 Commercial)</td>
                  <td class="p-3 font-semibold">Bengal Waterproofing Solutions</td>
                  <td class="p-3">₹35.00 / sq.ft</td>
                  <td class="p-3">18% GST &bull; Freight Included</td>
                  <td class="p-3 font-bold text-slate-900">₹5,16,250.00</td>
                  <td class="p-3 text-xs text-amber-700 font-semibold">70% On-time &bull; 2 Active Disputes</td>
                  <td class="p-3 font-mono font-bold text-slate-700">0.7950</td>
                  <td class="p-3 text-xs text-amber-700">Lowest landed price, but penalised for past site disputes at Vista.</td>
                </tr>
                <tr class="border-b border-slate-100">
                  <td class="p-3 font-bold text-slate-500">#3</td>
                  <td class="p-3 font-semibold">Dulux Aquatech Pro</td>
                  <td class="p-3">₹410.00 / sq.m</td>
                  <td class="p-3">18% GST &bull; Freight Included</td>
                  <td class="p-3 font-bold text-slate-900">₹5,61,831.68</td>
                  <td class="p-3 text-xs">98% On-time &bull; 0 Disputes</td>
                  <td class="p-3 font-mono font-bold text-slate-700">0.9448</td>
                  <td class="p-3 text-xs text-slate-600">Higher landed cost compared to recommended option.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Actions -->
          <div class="mt-6 flex justify-between items-center pt-4 border-t border-slate-100">
            <div class="text-xs text-slate-500">
              Deterministic Math Engine: Zero arithmetic hallucination.
            </div>
            <div class="space-x-3">
              <a href="/docs" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium">Interactive API Docs</a>
              <button class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-medium shadow-sm">Sign & Approve Award (HOD)</button>
            </div>
          </div>
        </div>
      </div>
    </body>
    </html>
    """
