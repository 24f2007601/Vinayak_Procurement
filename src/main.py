"""FastAPI Application for Vinayak Procurement Copilot with Neobrutalism UI & Farvision ERP Bridge.

Complete Phase 1-4 Operational Stack:
1. Requisition Ingestion & Farvision Matcher
2. Multimodal Quote Extractor (Groq Llama-3.3-70B + Heuristic)
3. Deterministic Cost & Comparative Statement Engine
4. Neobrutalism HOD Decision Cockpit
5. Farvision ERP CSV/JSON PO Staging Export & Immutable Audit Logger
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.models.requisition import SiteRequisition, FarvisionCatalogItem, UnitOfMeasure
from src.models.quote import RawQuoteInput, NormalizedQuoteItem, FreightTerm
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
from src.services.erp_service import generate_farvision_po_payload, generate_farvision_csv
from src.services.audit_service import audit_logger, AuditEventType

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

# Runtime state
_catalog = get_default_vinayak_catalog()
_vendor_repo = get_default_vinayak_vendor_repo()
_requisitions: List[SiteRequisition] = []

# Pre-seed active comparative statement for the default work package (Amara Tower-2)
def _create_default_statement() -> ComparativeStatement:
    boq_qty = Decimal("12500.0")
    boq_unit = UnitOfMeasure.SQFT
    budget_rate = Decimal("45.00")
    quotes = [
        RawQuoteInput(
            vendor_name="Bengal Waterproofing Solutions",
            quoted_unit_rate=Decimal("35.00"),
            quoted_unit=UnitOfMeasure.SQFT,
            gst_percent=Decimal("18.0"),
            freight_term=FreightTerm.INCLUDED,
            exclusions=["Surface grinding and crack filling extra at actuals"]
        ),
        RawQuoteInput(
            vendor_name="Asian Paints Chemical Division",
            quoted_unit_rate=Decimal("8800.00"),
            quoted_unit=UnitOfMeasure.DRUM,
            gst_percent=Decimal("18.0"),
            freight_term=FreightTerm.EXTRA_FIXED,
            freight_amount=Decimal("5000.00")
        ),
        RawQuoteInput(
            vendor_name="Dulux Aquatech Pro",
            quoted_unit_rate=Decimal("410.00"),
            quoted_unit=UnitOfMeasure.SQM,
            gst_percent=Decimal("18.0"),
            freight_term=FreightTerm.INCLUDED
        )
    ]
    norm = [
        normalize_quote(q, boq_qty, boq_unit, coverage_per_drum_sqft=Decimal("250.0"))
        for q in quotes
    ]
    tracks = {q.vendor_name: _vendor_repo.get_track_record(q.vendor_name) for q in norm}
    return generate_comparative_statement(
        statement_id="CS-AMR-T2-E2E",
        project_name="Vinayak Amara",
        package_title="Waterproofing at Vinayak Amara, Tower-2",
        boq_quantity=boq_qty,
        budget_rate=budget_rate,
        quotes=norm,
        track_records=tracks
    )

_default_statement = _create_default_statement()
_active_statements: dict[str, ComparativeStatement] = {
    "CS-AMR-T2-E2E": _default_statement
}


class RequisitionParseRequest(BaseModel):
    raw_text: str = Field(..., description="Informal WhatsApp or site audio transcription")
    project_name: str = Field(default="Vinayak Amara")
    tower: str = Field(default="Tower-2")
    quantity: Decimal = Field(gt=0)
    required_by_date: str = Field(description="YYYY-MM-DD")
    actor_id: str = Field(default="site_engineer_01")


class QuoteIngestRequest(BaseModel):
    raw_document_text: str
    vendor_hint: Optional[str] = None
    actor_id: str = Field(default="procurement_officer_01")


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

    # Log to audit trail
    audit_logger.log_event(
        event_type=AuditEventType.REQUISITION_CREATED,
        actor_id=req.actor_id,
        reference_id=new_requisition.requisition_id,
        payload={"item_code": matched_item.item_code, "quantity": float(req.quantity)}
    )

    return {
        "requisition": new_requisition,
        "matched_catalog_item": matched_item,
        "match_confidence": score,
        "duplicate_warnings": duplicate_warnings
    }


@app.post("/api/v1/quotes/extract", response_model=RawQuoteInput, tags=["Quotes"])
def extract_quote(req: QuoteIngestRequest):
    """Extracts raw unstructured vendor quotation into validated Pydantic schema."""
    parsed = extract_quote_with_groq(req.raw_document_text, vendor_hint=req.vendor_hint)
    audit_logger.log_event(
        event_type=AuditEventType.QUOTE_INGESTED,
        actor_id=req.actor_id,
        reference_id=parsed.vendor_name,
        payload={"rate": float(parsed.quoted_unit_rate), "unit": parsed.quoted_unit.value}
    )
    return parsed


@app.post("/api/v1/comparatives/generate", response_model=ComparativeStatement, tags=["Comparative"])
def build_comparative_statement(
    statement_id: str,
    project_name: str,
    package_title: str,
    boq_quantity: Decimal,
    boq_unit: UnitOfMeasure,
    budget_rate: Decimal,
    quotes: List[RawQuoteInput],
    coverage_per_drum: Optional[Decimal] = None,
    actor_id: str = "procurement_lead_01"
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

    audit_logger.log_event(
        event_type=AuditEventType.COMPARATIVE_GENERATED,
        actor_id=actor_id,
        reference_id=statement_id,
        payload={
            "l1_vendor": statement.l1_vendor_name,
            "recommended_vendor": statement.recommended_vendor_name,
            "vendors_count": len(quotes)
        }
    )

    return statement


@app.post("/api/v1/approvals/sign", response_model=ComparativeStatement, tags=["Approval"])
def approve_comparative(action: ApprovalActionRequest):
    """HOD reviews and signs off on recommended comparative statement."""
    statement = _active_statements.get(action.statement_id)
    if not statement:
        raise HTTPException(status_code=404, detail="Comparative statement not found")

    statement.status = ApprovalStatus.APPROVED
    statement.approved_by = action.approved_by
    statement.approval_timestamp = datetime.now()

    audit_logger.log_event(
        event_type=AuditEventType.HOD_APPROVED,
        actor_id=action.approved_by,
        reference_id=action.statement_id,
        payload={"recommended_vendor": statement.recommended_vendor_name, "remarks": action.remarks}
    )

    return statement


@app.get("/api/v1/erp/export/json/{statement_id}", tags=["Farvision ERP"])
def export_to_farvision_json(statement_id: str):
    """Generates Farvision ERP PO staging payload in JSON format."""
    statement = _active_statements.get(statement_id)
    if not statement:
        raise HTTPException(status_code=404, detail="Comparative statement not found")
    if statement.status != ApprovalStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Cannot export unapproved comparative statement")

    payload = generate_farvision_po_payload(statement)
    audit_logger.log_event(
        event_type=AuditEventType.ERP_EXPORTED,
        actor_id=statement.approved_by or "system",
        reference_id=statement_id,
        payload={"format": "JSON", "po_id": payload["po_header"]["farvision_po_id"]}
    )
    return payload


@app.get("/api/v1/erp/export/csv/{statement_id}", tags=["Farvision ERP"])
def export_to_farvision_csv(statement_id: str):
    """Generates Farvision ERP PO staging file in legacy CSV format."""
    statement = _active_statements.get(statement_id)
    if not statement:
        raise HTTPException(status_code=404, detail="Comparative statement not found")
    if statement.status != ApprovalStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Cannot export unapproved comparative statement")

    csv_data = generate_farvision_csv(statement)
    audit_logger.log_event(
        event_type=AuditEventType.ERP_EXPORTED,
        actor_id=statement.approved_by or "system",
        reference_id=statement_id,
        payload={"format": "CSV", "po_id": f"PO-{statement_id}"}
    )
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=farvision_po_{statement_id}.csv"}
    )


@app.get("/api/v1/audit/logs", tags=["Audit"])
def get_audit_trail(reference_id: Optional[str] = None):
    """Returns immutable tamper-proof audit records."""
    if reference_id:
        return audit_logger.get_logs_for_reference(reference_id)
    return audit_logger.get_all_logs()


# Compatibility route for earlier UI calls
@app.get("/api/v1/erp/export/{statement_id}", tags=["Farvision ERP"])
def export_to_farvision_po(statement_id: str):
    return export_to_farvision_json(statement_id)


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
def neobrutalism_dashboard():
    """Serves high-contrast Neobrutalism styled HOD Procurement Cockpit."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vinayak Group &bull; AI Procurement Copilot</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700;800&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
  <style>
    body {
      font-family: 'Space Grotesk', sans-serif;
      background-color: #FEFCE8;
      transition: background-color 0.2s ease, color 0.2s ease;
    }
    body.dark {
      background-color: #0B1120;
      color: #F8FAFC;
    }
    .font-mono {
      font-family: 'Space Mono', monospace;
    }
    .neo-box {
      border: 3px solid #000000;
      box-shadow: 5px 5px 0px 0px #000000;
    }
    body.dark .neo-box {
      border-color: #F8FAFC;
      box-shadow: 5px 5px 0px 0px #F8FAFC;
      background-color: #111827;
      color: #F8FAFC;
    }
    .neo-box-sm {
      border: 2px solid #000000;
      box-shadow: 3px 3px 0px 0px #000000;
    }
    body.dark .neo-box-sm {
      border-color: #F8FAFC;
      box-shadow: 3px 3px 0px 0px #F8FAFC;
      background-color: #1F2937;
      color: #F8FAFC;
    }
    body.dark header.neo-box {
      background-color: #EAB308 !important;
      color: #000000 !important;
      border-color: #F8FAFC !important;
    }
    body.dark header.neo-box h1,
    body.dark header.neo-box p {
      color: #000000 !important;
    }
    /* Dark mode text readability overrides */
    body.dark .text-slate-600,
    body.dark .text-slate-700,
    body.dark .text-slate-800,
    body.dark .text-black {
      color: #E2E8F0 !important;
    }
    body.dark table {
      border-color: #F8FAFC !important;
    }
    body.dark table th,
    body.dark table td {
      border-color: #475569 !important;
    }
    body.dark table tbody tr {
      background-color: #1E293B !important;
      color: #F8FAFC !important;
    }
    body.dark table tbody tr.bg-\[\#DCFCE7\] {
      background-color: #064E3B !important; /* Deep contrast emerald for winner row in dark mode */
      color: #ECFDF5 !important;
    }
    body.dark table tbody tr.bg-\[\#DCFCE7\] td {
      border-color: #059669 !important;
    }
    body.dark table tbody tr.bg-\[\#DCFCE7\] .text-emerald-800,
    body.dark table tbody tr.bg-\[\#DCFCE7\] .text-emerald-900 {
      color: #6EE7B7 !important;
    }
    body.dark table tbody tr .text-emerald-700 {
      color: #34D399 !important;
    }
    body.dark table tbody tr .text-red-800 {
      color: #FCA5A5 !important;
    }
    body.dark table tbody tr .text-slate-600 {
      color: #CBD5E1 !important;
    }
    body.dark table tbody tr .text-slate-800 {
      color: #F1F5F9 !important;
    }
    body.dark #matchOutput {
      background-color: #854D0E !important;
      color: #FEF9C3 !important;
      border-color: #F8FAFC !important;
    }
    body.dark #matchOutput div {
      color: #FEF9C3 !important;
    }
    body.dark .bg-\[\#FFFBEB\] {
      background-color: #1E293B !important;
      border-color: #F8FAFC !important;
    }
    body.dark .bg-\[\#FBCFE8\] {
      background-color: #831843 !important;
      border-color: #F8FAFC !important;
      color: #FCE7F3 !important;
    }
    body.dark .bg-\[\#FBCFE8\] h3,
    body.dark .bg-\[\#FBCFE8\] p {
      color: #FCE7F3 !important;
    }
    body.dark .bg-\[\#FEF08A\] {
      background-color: #713F12 !important;
      border-color: #F8FAFC !important;
      color: #FEF08A !important;
    }
    body.dark .bg-\[\#FEF08A\] h4,
    body.dark .bg-\[\#FEF08A\] p,
    body.dark .bg-\[\#FEF08A\] strong {
      color: #FEF9C3 !important;
    }
    body.dark #statusBadge {
      background-color: #CA8A04 !important;
      color: #000000 !important;
      border-color: #F8FAFC !important;
    }
    /* Clear, high-contrast Export Buttons */
    .export-btn-disabled {
      background-color: #E2E8F0 !important;
      color: #64748B !important;
      border: 2px solid #000000 !important;
      box-shadow: 2px 2px 0px 0px #000000 !important;
      cursor: not-allowed !important;
      opacity: 0.9 !important;
    }
    body.dark .export-btn-disabled {
      background-color: #1E293B !important;
      color: #94A3B8 !important;
      border: 2px solid #64748B !important;
      box-shadow: 2px 2px 0px 0px #334155 !important;
      cursor: not-allowed !important;
      opacity: 0.9 !important;
    }
    .export-btn-active {
      background-color: #38BDF8 !important;
      color: #000000 !important;
      border: 3px solid #000000 !important;
      box-shadow: 4px 4px 0px 0px #000000 !important;
      cursor: pointer !important;
    }
    body.dark .export-btn-active {
      background-color: #38BDF8 !important;
      color: #000000 !important;
      border: 3px solid #F8FAFC !important;
      box-shadow: 4px 4px 0px 0px #F8FAFC !important;
      cursor: pointer !important;
    }
    body.dark .neo-btn {
      border-color: #F8FAFC;
      box-shadow: 4px 4px 0px 0px #F8FAFC;
    }
    .neo-btn:hover {
      transform: translate(2px, 2px);
      box-shadow: 2px 2px 0px 0px #000000;
    }
    body.dark .neo-btn:hover {
      box-shadow: 2px 2px 0px 0px #F8FAFC;
    }
    .neo-btn:active {
      transform: translate(4px, 4px);
      box-shadow: 0px 0px 0px 0px #000000;
    }
    .neo-input {
      border: 3px solid #000000;
      box-shadow: 3px 3px 0px 0px #000000;
      outline: none;
    }
    body.dark .neo-input {
      border-color: #F8FAFC;
      box-shadow: 3px 3px 0px 0px #F8FAFC;
      background-color: #1E293B;
      color: #F8FAFC;
    }
    .neo-input:focus {
      border-color: #000000;
      box-shadow: 4px 4px 0px 0px #000000;
      background-color: #FFFBEB;
    }
    body.dark .neo-input:focus {
      border-color: #F8FAFC;
      box-shadow: 4px 4px 0px 0px #F8FAFC;
      background-color: #334155;
    }
  </style>
</head>
<body class="text-black min-h-screen p-4 md:p-8">

  <div class="max-w-7xl mx-auto space-y-8">

    <!-- Top Header -->
    <header class="neo-box bg-[#FDE047] p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div>
        <div class="flex items-center gap-3">
          <span class="bg-black text-white px-3 py-1 font-mono text-xs uppercase font-bold tracking-wider">Vinayak Group</span>
          <span class="bg-[#86EFAC] text-black px-3 py-1 font-mono text-xs uppercase font-bold border-2 border-black">5 Kolkata Sites</span>
        </div>
        <h1 class="text-3xl md:text-5xl font-extrabold tracking-tight mt-2 text-black">PROCUREMENT PORTAL</h1>
        <p class="font-bold text-sm md:text-base text-black mt-1">Site Requisitions &bull; Vendor Comparatives &bull; Purchase Orders</p>
      </div>

      <!-- Theme Mode Toggle -->
      <button id="themeToggleBtn" onclick="toggleTheme()" class="neo-btn bg-white hover:bg-slate-100 text-black px-3.5 py-2 font-mono text-xs font-bold uppercase flex items-center gap-2 cursor-pointer" aria-label="Toggle light and dark mode">
        <span id="themeIcon">🌙</span>
        <span id="themeLabel">Dark Mode</span>
      </button>
    </header>

    <!-- Main Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">

      <!-- Left Column: Site Ingestion & WhatsApp Parser -->
      <section class="lg:col-span-4 space-y-6">
        <div class="neo-box bg-white p-6 space-y-4">
          <div class="flex items-center justify-between border-b-2 border-black pb-3">
            <h2 class="text-xl font-bold uppercase tracking-wide">1. Site Requisition</h2>
            <span class="font-mono text-xs bg-[#BAE6FD] border border-black px-2 py-0.5 font-bold">WhatsApp / Audio</span>
          </div>

          <form id="reqForm" class="space-y-3" onsubmit="event.preventDefault(); submitRequisition();">
            <div>
              <label class="block text-xs font-mono font-bold uppercase mb-1">Project Site</label>
              <select id="reqProject" class="w-full neo-input p-2.5 text-sm font-bold bg-white">
                <option value="Vinayak Amara">Vinayak Amara (Rajarhat)</option>
                <option value="Vinayak Vista">Vinayak Vista (Lake Town)</option>
                <option value="Vinayak Citadel">Vinayak Citadel (EM Bypass)</option>
              </select>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <div>
                <label class="block text-xs font-mono font-bold uppercase mb-1">Tower / Area</label>
                <input id="reqTower" type="text" value="Tower-2" class="w-full neo-input p-2.5 text-sm font-bold" />
              </div>
              <div>
                <label class="block text-xs font-mono font-bold uppercase mb-1">Quantity</label>
                <input id="reqQty" type="number" value="50" class="w-full neo-input p-2.5 text-sm font-bold" />
              </div>
            </div>

            <div>
              <label class="block text-xs font-mono font-bold uppercase mb-1">Required By Date</label>
              <input id="reqDate" type="date" value="2026-12-15" class="w-full neo-input p-2.5 text-sm font-bold" />
            </div>

            <div>
              <label class="block text-xs font-mono font-bold uppercase mb-1">Site Engineer Note</label>
              <textarea id="reqText" rows="2" class="w-full neo-input p-2.5 text-sm font-medium" placeholder="e.g. Urgent Dr Fixit fastflex chemical for terrace waterproofing"></textarea>
            </div>

            <!-- Voice Note / Audio Upload Section -->
            <div class="border-2 border-dashed border-black p-3 bg-[#FFFBEB] space-y-2">
              <div class="flex items-center justify-between">
                <label class="text-xs font-mono font-bold uppercase flex items-center gap-1.5 cursor-pointer">
                  <span>🎙️ Voice Note / Audio</span>
                </label>
                <span id="audioStatus" class="text-[10px] font-mono text-slate-500">.mp3, .wav, .m4a, .ogg</span>
              </div>
              <input id="audioInput" type="file" accept="audio/*" class="w-full text-xs font-mono file:mr-2 file:py-1 file:px-2 file:border-2 file:border-black file:bg-[#BAE6FD] file:font-bold file:cursor-pointer cursor-pointer" onchange="handleAudioUpload(event)" />
            </div>

            <button type="submit" class="w-full neo-btn bg-[#67E8F9] hover:bg-[#22D3EE] text-black font-extrabold uppercase py-3 text-sm">
              Match Farvision Catalog &rarr;
            </button>
          </form>

          <div id="matchOutput" class="hidden neo-box-sm bg-[#FEF08A] p-4 text-xs space-y-1 font-mono"></div>
        </div>

        <div class="neo-box bg-[#FBCFE8] p-5 space-y-2">
          <h3 class="font-bold text-sm uppercase flex items-center gap-2">
            <span class="w-3 h-3 bg-black inline-block"></span>
            Vendor Evaluation Policy
          </h3>
          <p class="text-xs leading-relaxed font-medium">
            Quotes are evaluated on landed cost (60%), past delivery track record (25%), and quality pass rate (15%). Active site disputes carry automatic score deductions.
          </p>
        </div>
      </section>

      <!-- Right Column: Comparative Statement Cockpit -->
      <section class="lg:col-span-8 space-y-6">

        <div class="neo-box bg-white p-6 space-y-6">
          <div class="flex flex-col md:flex-row justify-between items-start md:items-center border-b-3 border-black pb-4 gap-2">
            <div>
              <span id="packageTag" class="bg-black text-white px-2 py-0.5 font-mono text-xs font-bold uppercase">Package #WP-AMR-T2</span>
              <h2 id="packageTitle" class="text-2xl font-black uppercase mt-1">Waterproofing at Vinayak Amara, Tower-2</h2>
              <p id="packageMeta" class="text-xs font-mono text-slate-700">BOQ: 12,500 sq.ft &bull; Baseline Budget: ₹45.00/sq.ft &bull; Total Budget: ₹5,62,500.00</p>
            </div>
            <div id="statusBadge" class="bg-[#FDE047] neo-box-sm px-4 py-1.5 font-mono font-bold text-xs uppercase">
              STATUS: AWAITING HOD APPROVAL
            </div>
          </div>

          <!-- Comparative Matrix Table -->
          <div class="overflow-x-auto">
            <table class="w-full text-left text-sm border-2 border-black border-collapse">
              <thead>
                <tr class="bg-black text-white font-mono text-xs uppercase">
                  <th class="p-3 border-r border-slate-700">Vendor / Bidder</th>
                  <th class="p-3 border-r border-slate-700">Quoted Rate</th>
                  <th class="p-3 border-r border-slate-700">Taxes & Freight</th>
                  <th class="p-3 border-r border-slate-700">Total Landed Cost</th>
                  <th class="p-3 border-r border-slate-700">Track Record</th>
                  <th class="p-3 border-r border-slate-700">Score</th>
                  <th class="p-3">Rank & Decision</th>
                </tr>
              </thead>
              <tbody id="comparativeTableBody" class="font-medium">
                <tr class="border-b-2 border-black bg-[#DCFCE7]">
                  <td class="p-3 border-r-2 border-black font-bold">
                    Asian Paints Chemical Div.
                    <span class="block text-[10px] font-mono font-normal text-slate-600">20L Drum Packaging</span>
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono">
                    ₹8,800/drum
                    <span class="block text-[10px] text-slate-600">50 drums needed</span>
                  </td>
                  <td class="p-3 border-r-2 border-black text-xs">
                    18% GST (₹79,200)<br>
                    Freight: ₹5,000 extra
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono font-bold text-base">
                    ₹5,24,200.00
                    <span class="block text-[10px] text-emerald-800 font-bold">₹41.94 / sq.ft landed</span>
                  </td>
                  <td class="p-3 border-r-2 border-black text-xs font-mono">
                    92% On-time<br>
                    95% Quality<br>
                    <span class="text-emerald-700 font-bold">0 Disputes</span>
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono font-bold text-lg text-emerald-900">
                    0.9634
                  </td>
                  <td class="p-3">
                    <span class="bg-[#86EFAC] border border-black px-2 py-0.5 font-mono text-xs font-black uppercase inline-block mb-1">
                      RECOMMENDED
                    </span>
                    <p class="text-[11px] leading-tight text-slate-800">
                      Top composite score. Zero dispute risk & 92% on-time delivery rate justify slight premium over L1.
                    </p>
                  </td>
                </tr>

                <tr class="border-b-2 border-black bg-white">
                  <td class="p-3 border-r-2 border-black font-bold">
                    Bengal Waterproofing Sol.
                    <span class="block text-[10px] font-mono font-normal text-slate-600">Direct sq.ft Quote</span>
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono">
                    ₹35.00/sq.ft
                  </td>
                  <td class="p-3 border-r-2 border-black text-xs">
                    18% GST (₹78,750)<br>
                    Freight: Included
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono font-bold text-base">
                    ₹5,16,250.00
                    <span class="block text-[10px] text-slate-600">₹41.30 / sq.ft landed</span>
                  </td>
                  <td class="p-3 border-r-2 border-black text-xs font-mono">
                    70% On-time<br>
                    80% Quality<br>
                    <span class="bg-red-200 text-red-900 font-bold px-1">2 Disputes</span>
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono font-bold text-lg text-slate-700">
                    0.7950
                  </td>
                  <td class="p-3">
                    <span class="bg-[#FEF08A] border border-black px-2 py-0.5 font-mono text-xs font-bold uppercase inline-block mb-1">
                      L1 COMMERCIAL
                    </span>
                    <p class="text-[11px] leading-tight text-red-800 font-semibold">
                      Lowest landed price by 1.5%, but penalised for past quality disputes at Vinayak Vista. Excludes surface grinding.
                    </p>
                  </td>
                </tr>

                <tr class="bg-white">
                  <td class="p-3 border-r-2 border-black font-bold">
                    Dulux Aquatech Pro
                    <span class="block text-[10px] font-mono font-normal text-slate-600">Normalized from Sq.m</span>
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono">
                    ₹410.00/sq.m
                    <span class="block text-[10px] text-slate-600">~₹38.09 / sq.ft</span>
                  </td>
                  <td class="p-3 border-r-2 border-black text-xs">
                    18% GST (₹85,703)<br>
                    Freight: Included
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono font-bold text-base">
                    ₹5,61,831.68
                    <span class="block text-[10px] text-slate-600">₹44.95 / sq.ft landed</span>
                  </td>
                  <td class="p-3 border-r-2 border-black text-xs font-mono">
                    98% On-time<br>
                    99% Quality<br>
                    <span class="text-emerald-700 font-bold">0 Disputes</span>
                  </td>
                  <td class="p-3 border-r-2 border-black font-mono font-bold text-lg text-slate-700">
                    0.9448
                  </td>
                  <td class="p-3">
                    <span class="bg-slate-200 border border-black px-2 py-0.5 font-mono text-xs font-bold uppercase inline-block mb-1">
                      RANK #3
                    </span>
                    <p class="text-[11px] leading-tight text-slate-600">
                      Clean execution record, but highest landed total cost.
                    </p>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- HOD Action Deck -->
          <div class="neo-box-sm bg-[#FEF08A] p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
            <div>
              <h4 class="font-bold text-base uppercase">HOD Award Sign-off</h4>
              <p id="hodDeckSummary" class="text-xs text-slate-800">
                Recommended award: <strong>Asian Paints Chemical Division</strong> (₹5,24,200.00). Click below to approve and export to Farvision ERP.
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button id="approveBtn" onclick="signApproval();" class="neo-btn bg-[#86EFAC] hover:bg-[#4ADE80] font-black uppercase text-sm px-5 py-3">
                Approve Award &check;
              </button>
              <button id="exportJsonBtn" disabled onclick="downloadERPPayload('json');" class="neo-btn export-btn-disabled font-bold uppercase text-xs px-4 py-3 flex items-center gap-1.5" title="Approve award first to unlock export">
                <span>📄</span> Export JSON
              </button>
              <button id="exportCsvBtn" disabled onclick="downloadERPPayload('csv');" class="neo-btn export-btn-disabled font-bold uppercase text-xs px-4 py-3 flex items-center gap-1.5" title="Approve award first to unlock export">
                <span>📊</span> Export CSV
              </button>
            </div>
          </div>

          <!-- Live Audit Log -->
          <div id="approvalBanner" class="hidden neo-box-sm bg-[#86EFAC] p-4 text-xs font-mono font-bold"></div>

        </div>
      </section>

    </div>

  </div>

  <script>
    let currentStatementId = "CS-AMR-T2-E2E";

    function toggleTheme() {
      const isDark = document.body.classList.toggle('dark');
      localStorage.setItem('theme', isDark ? 'dark' : 'light');
      updateThemeUI(isDark);
    }

    function updateThemeUI(isDark) {
      const icon = document.getElementById('themeIcon');
      const label = document.getElementById('themeLabel');
      if (icon && label) {
        icon.innerText = isDark ? '☀️' : '🌙';
        label.innerText = isDark ? 'Light Mode' : 'Dark Mode';
      }
    }

    // Auto-load saved theme preference
    if (localStorage.getItem('theme') === 'dark' || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches && !localStorage.getItem('theme'))) {
      document.body.classList.add('dark');
      updateThemeUI(true);
    }

    function handleAudioUpload(event) {
      const file = event.target.files[0];
      if (!file) return;

      const status = document.getElementById('audioStatus');
      status.innerText = "Transcribing audio...";
      status.className = "text-[10px] font-mono text-emerald-800 font-bold";

      // Simulate voice note transcription (or plug into Whisper/Groq Audio endpoint)
      setTimeout(() => {
        const textField = document.getElementById('reqText');
        const fileName = file.name.toLowerCase();
        
        if (fileName.includes("cement") || fileName.includes("ambuja")) {
          textField.value = "Need 200 bags PPC Grade 53 cement for foundation casting urgent";
        } else if (fileName.includes("steel") || fileName.includes("tmt")) {
          textField.value = "Require 15 MT Tata Tiscon Fe 550 TMT rebar for column work";
        } else {
          textField.value = "Urgent Dr Fixit fastflex chemical for terrace waterproofing at Tower 2";
        }

        status.innerText = `Transcribed: ${file.name}`;
      }, 600);
    }

    async function submitRequisition() {
      const project = document.getElementById('reqProject').value;
      const tower = document.getElementById('reqTower').value;
      const qty = parseFloat(document.getElementById('reqQty').value) || 50;
      const reqDate = document.getElementById('reqDate').value;
      const note = document.getElementById('reqText').value || "dr fixit fastflex chemical for waterproofing at amara tower 2";

      const payload = {
        raw_text: note,
        project_name: project,
        tower: tower,
        quantity: qty,
        required_by_date: reqDate
      };

      try {
        const res = await fetch('/api/v1/requisitions/parse', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        const box = document.getElementById('matchOutput');
        box.classList.remove('hidden');
        box.innerHTML = `
          <div class="font-bold text-black border-b border-black pb-1 uppercase">Farvision Item Matched (${Math.round(data.match_confidence * 100)}% Confidence)</div>
          <div>Code: <strong>${data.matched_catalog_item.item_code}</strong></div>
          <div>Item: ${data.matched_catalog_item.canonical_name}</div>
          <div>Baseline Rate: ₹${data.matched_catalog_item.budget_rate} / ${data.matched_catalog_item.standard_unit}</div>
          ${data.duplicate_warnings.length > 0 ? `<div class="text-red-700 font-bold mt-1">${data.duplicate_warnings[0]}</div>` : ''}
        `;

        // Dynamically re-evaluate Comparative Statement for this matched requisition
        await updateComparativeForRequisition(data.requisition, data.matched_catalog_item);

      } catch (err) {
        alert("Catalog matching failed: " + err);
      }
    }

    async function updateComparativeForRequisition(req, catalogItem) {
      currentStatementId = "CS-" + req.requisition_id;
      const newPackageTitle = `${catalogItem.category} at ${req.project_name}, ${req.tower}`;

      // Update Header Display
      document.getElementById('packageTag').innerText = `Package #${req.requisition_id}`;
      document.getElementById('packageTitle').innerText = newPackageTitle;

      // Base BOQ area from quantity (if drums, 1 drum = 250 sq.ft)
      const boqQty = catalogItem.standard_unit === "drum" ? (req.requested_quantity * 250) : (req.requested_quantity * 250);
      const totalBudget = boqQty * catalogItem.budget_rate;
      document.getElementById('packageMeta').innerText = `BOQ: ${boqQty.toLocaleString()} sq.ft • Baseline Budget: ₹${catalogItem.budget_rate}/sq.ft • Total Budget: ₹${totalBudget.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

      // Quotes dynamically adjusted to requisition quantity
      const quotesPayload = [
        {
          vendor_name: "Bengal Waterproofing Solutions",
          quoted_unit_rate: "35.00",
          quoted_unit: "sq.ft",
          gst_percent: "18.0",
          freight_term: "included",
          exclusions: ["Surface grinding and crack filling extra"]
        },
        {
          vendor_name: "Asian Paints Chemical Division",
          quoted_unit_rate: "8800.00",
          quoted_unit: "drum",
          gst_percent: "18.0",
          freight_term: "extra_fixed",
          freight_amount: "5000.00"
        },
        {
          vendor_name: "Dulux Aquatech Pro",
          quoted_unit_rate: "410.00",
          quoted_unit: "sq.m",
          gst_percent: "18.0",
          freight_term: "included"
        }
      ];

      const res = await fetch(`/api/v1/comparatives/generate?statement_id=${currentStatementId}&project_name=${encodeURIComponent(req.project_name)}&package_title=${encodeURIComponent(newPackageTitle)}&boq_quantity=${boqQty}&boq_unit=sq.ft&budget_rate=${catalogItem.budget_rate}&coverage_per_drum=250`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(quotesPayload)
      });

      if (res.ok) {
        const cs = await res.json();
        renderComparativeRows(cs);

        // Reset approval state
        document.getElementById('statusBadge').innerText = "STATUS: AWAITING HOD APPROVAL";
        document.getElementById('statusBadge').className = "bg-[#FDE047] neo-box-sm px-4 py-1.5 font-mono font-bold text-xs uppercase";

        const btn = document.getElementById('approveBtn');
        btn.innerText = "Approve Award ✓";
        btn.disabled = false;
        btn.className = "neo-btn bg-[#86EFAC] hover:bg-[#4ADE80] font-black uppercase text-sm px-5 py-3";

        ['exportJsonBtn', 'exportCsvBtn'].forEach(id => {
          const b = document.getElementById(id);
          b.disabled = true;
          b.className = "neo-btn export-btn-disabled font-bold uppercase text-xs px-4 py-3 flex items-center gap-1.5";
        });

        document.getElementById('approvalBanner').classList.add('hidden');
      }
    }

    function renderComparativeRows(cs) {
      const tbody = document.getElementById('comparativeTableBody');
      tbody.innerHTML = '';

      cs.ranked_vendors.forEach((v) => {
        const q = v.normalized_quote;
        const isRec = v.is_recommended;
        const isL1 = v.is_l1;

        const rowBg = isRec ? 'bg-[#DCFCE7]' : 'bg-white';
        const rankPill = isRec 
          ? `<span class="bg-[#86EFAC] border border-black px-2 py-0.5 font-mono text-xs font-black uppercase inline-block mb-1">RECOMMENDED</span>`
          : (isL1 ? `<span class="bg-[#FEF08A] border border-black px-2 py-0.5 font-mono text-xs font-bold uppercase inline-block mb-1">L1 COMMERCIAL</span>` : `<span class="bg-slate-200 border border-black px-2 py-0.5 font-mono text-xs font-bold uppercase inline-block mb-1">RANK #${v.rank}</span>`);

        const disputesBadge = v.track_record.active_disputes > 0
          ? `<span class="bg-red-200 text-red-900 font-bold px-1">${v.track_record.active_disputes} Disputes</span>`
          : `<span class="text-emerald-700 font-bold">0 Disputes</span>`;

        const tr = document.createElement('tr');
        tr.className = `border-b-2 border-black ${rowBg}`;
        tr.innerHTML = `
          <td class="p-3 border-r-2 border-black font-bold">
            ${v.vendor_name}
            <span class="block text-[10px] font-mono font-normal text-slate-600">Unit: ${q.quoted_unit}</span>
          </td>
          <td class="p-3 border-r-2 border-black font-mono">
            ₹${Number(q.quoted_unit_rate).toLocaleString('en-IN')} / ${q.quoted_unit}
            <span class="block text-[10px] text-slate-600">Req: ${Number(q.normalized_quantity).toLocaleString()} ${q.quoted_unit}</span>
          </td>
          <td class="p-3 border-r-2 border-black text-xs">
            18% GST (₹${Number(q.gst_amount).toLocaleString('en-IN')})<br>
            Freight: ₹${Number(q.freight_amount).toLocaleString('en-IN')}
          </td>
          <td class="p-3 border-r-2 border-black font-mono font-bold text-base">
            ₹${Number(q.total_landed_cost).toLocaleString('en-IN', {minimumFractionDigits: 2})}
            <span class="block text-[10px] text-emerald-800 font-bold">₹${Number(q.landed_rate_per_boq_unit).toFixed(2)} / sq.ft</span>
          </td>
          <td class="p-3 border-r-2 border-black text-xs font-mono">
            ${v.track_record.on_time_delivery_pct}% On-time<br>
            ${v.track_record.quality_pass_pct}% Quality<br>
            ${disputesBadge}
          </td>
          <td class="p-3 border-r-2 border-black font-mono font-bold text-lg ${isRec ? 'text-emerald-900' : 'text-slate-700'}">
            ${v.composite_score}
          </td>
          <td class="p-3">
            ${rankPill}
            <p class="text-[11px] leading-tight ${isL1 && !isRec ? 'text-red-800 font-semibold' : 'text-slate-800'}">
              ${v.decision_rationale}
            </p>
          </td>
        `;
        tbody.appendChild(tr);
      });

      const rec = cs.ranked_vendors.find(v => v.is_recommended);
      document.getElementById('hodDeckSummary').innerHTML = `
        Recommended award: <strong>${rec.vendor_name}</strong> (₹${Number(rec.normalized_quote.total_landed_cost).toLocaleString('en-IN', {minimumFractionDigits: 2})}). Click below to approve and export to Farvision ERP.
      `;
    }

    async function signApproval() {
      const payload = {
        statement_id: currentStatementId,
        approved_by: "Arindam Mukherjee (HOD Projects)",
        remarks: "Approved as recommended. Reliability prioritised over disputed L1."
      };

      try {
        const res = await fetch('/api/v1/approvals/sign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          document.getElementById('statusBadge').innerText = "STATUS: APPROVED BY HOD";
          document.getElementById('statusBadge').className = "bg-[#86EFAC] neo-box-sm px-4 py-1.5 font-mono font-bold text-xs uppercase";

          const btn = document.getElementById('approveBtn');
          btn.innerText = "Approved & Signed";
          btn.disabled = true;
          btn.className = "neo-btn bg-slate-300 font-bold uppercase text-xs px-5 py-3 cursor-not-allowed";

          ['exportJsonBtn', 'exportCsvBtn'].forEach(id => {
            const b = document.getElementById(id);
            b.disabled = false;
            b.className = "neo-btn export-btn-active hover:brightness-105 font-black uppercase text-xs px-4 py-3 flex items-center gap-1.5";
          });

          const banner = document.getElementById('approvalBanner');
          banner.classList.remove('hidden');
          banner.innerHTML = `
            <div>✓ DIGITAL SIGNATURE RECORDED: Arindam Mukherjee (HOD Projects) • ${new Date().toLocaleTimeString()}</div>
            <div class="text-slate-800 font-normal">Audit Reference: FARVISION-PO-${currentStatementId} • Ready for ERP Injection</div>
          `;
        }
      } catch (err) {
        alert("Approval failed: " + err);
      }
    }

    async function downloadERPPayload(format) {
      const url = `/api/v1/erp/export/${format}/${currentStatementId}`;
      window.open(url, '_blank');
    }
  </script>
</body>
</html>
    """
