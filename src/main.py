"""FastAPI Application for Vinayak Procurement Copilot with Neobrutalism UI.

Neobrutalism Aesthetics:
- High contrast bold 2px/3px black borders (`border-2 border-black` / `border-3 border-black`)
- Hard drop shadows with no blur (`shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]`)
- Vivid retro-modern palette: Vibrant Yellow/Amber (#FEF08A / #FDE047), Mint (#86EFAC), Electric Blue, Coral
- Bold typography with mono badges and tactile hover translations (`hover:translate-x-0.5 hover:translate-y-0.5 hover:shadow-[2px_2px_0px_0px_rgba(0,0,0,1)]`)
- Accessibility compliant, full keyboard navigable, semantic HTML
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
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
      background-color: #FEFCE8; /* Creamy warm yellow background */
    }
    .font-mono {
      font-family: 'Space Mono', monospace;
    }
    .neo-box {
      border: 3px solid #000000;
      box-shadow: 5px 5px 0px 0px #000000;
    }
    .neo-box-sm {
      border: 2px solid #000000;
      box-shadow: 3px 3px 0px 0px #000000;
    }
    .neo-btn {
      border: 3px solid #000000;
      box-shadow: 4px 4px 0px 0px #000000;
      transition: all 0.15s ease-in-out;
    }
    .neo-btn:hover {
      transform: translate(2px, 2px);
      box-shadow: 2px 2px 0px 0px #000000;
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
    .neo-input:focus {
      border-color: #000000;
      box-shadow: 4px 4px 0px 0px #000000;
      background-color: #FFFBEB;
    }
  </style>
</head>
<body class="text-black min-h-screen p-4 md:p-8">

  <div class="max-w-7xl mx-auto space-y-8">

    <!-- Top Header -->
    <header class="neo-box bg-[#FDE047] p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div>
        <div class="flex items-center gap-3">
          <span class="bg-black text-white px-3 py-1 font-mono text-xs uppercase font-bold tracking-wider">Kolkata Projects</span>
          <span class="bg-[#86EFAC] text-black px-3 py-1 font-mono text-xs uppercase font-bold border-2 border-black">5 Sites Active</span>
        </div>
        <h1 class="text-3xl md:text-5xl font-extrabold tracking-tight mt-2 text-black">VINAYAK PROCUREMENT COPILOT</h1>
        <p class="font-bold text-sm md:text-base text-black mt-1">Site Requisitions &bull; Automated Normalization &bull; Farvision PO Handoff</p>
      </div>
      <div class="flex flex-wrap gap-3">
        <a href="/docs" target="_blank" class="neo-btn bg-white hover:bg-slate-100 text-black font-bold px-4 py-2.5 text-sm uppercase font-mono">
          API Specs
        </a>
        <a href="/health" target="_blank" class="neo-btn bg-[#86EFAC] hover:bg-[#4ADE80] text-black font-bold px-4 py-2.5 text-sm uppercase font-mono">
          System Healthy &bull; 1.0.0
        </a>
      </div>
    </header>

    <!-- Main Grid: Site Input (Left) & Active Package (Right) -->
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
              <textarea id="reqText" rows="3" class="w-full neo-input p-2.5 text-sm font-medium" placeholder="e.g. Urgent Dr Fixit fastflex chemical for terrace waterproofing"></textarea>
            </div>

            <button type="submit" class="w-full neo-btn bg-[#67E8F9] hover:bg-[#22D3EE] text-black font-extrabold uppercase py-3 text-sm">
              Match Farvision Catalog &rarr;
            </button>
          </form>

          <!-- Match Output Box -->
          <div id="matchOutput" class="hidden neo-box-sm bg-[#FEF08A] p-4 text-xs space-y-1 font-mono"></div>
        </div>

        <!-- Vendor Trust Matrix Pill -->
        <div class="neo-box bg-[#FBCFE8] p-5 space-y-2">
          <h3 class="font-bold text-sm uppercase flex items-center gap-2">
            <span class="w-3 h-3 bg-black inline-block"></span>
            Tribal Vendor Intelligence
          </h3>
          <p class="text-xs leading-relaxed font-medium">
            Price is only 60% of the award decision. 40% weights quality test pass history and on-time delivery. Vendors with active site disputes receive an immediate algorithmic penalty.
          </p>
        </div>
      </section>

      <!-- Right Column: Comparative Statement Cockpit (The Crown Jewel) -->
      <section class="lg:col-span-8 space-y-6">

        <div class="neo-box bg-white p-6 space-y-6">
          <div class="flex flex-col md:flex-row justify-between items-start md:items-center border-b-3 border-black pb-4 gap-2">
            <div>
              <span class="bg-black text-white px-2 py-0.5 font-mono text-xs font-bold uppercase">Package #WP-AMR-T2</span>
              <h2 class="text-2xl font-black uppercase mt-1">Waterproofing at Vinayak Amara, Tower-2</h2>
              <p class="text-xs font-mono text-slate-700">BOQ: 12,500 sq.ft &bull; Baseline Budget: ₹45.00/sq.ft &bull; Total Budget: ₹5,62,500.00</p>
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
              <tbody class="font-medium">
                <!-- Vendor 1: Recommended Winner -->
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

                <!-- Vendor 2: L1 on raw price, but penalized for dispute -->
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

                <!-- Vendor 3: Quoted in SQ.M -->
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
              <h4 class="font-bold text-base uppercase">HOD Executive Decision Gate</h4>
              <p class="text-xs text-slate-800">
                AI recommends <strong>Asian Paints Chemical Division</strong> (₹5,24,200.00). Farvision ERP PO will only be generated upon your signature.
              </p>
            </div>
            <div class="flex gap-3">
              <button id="approveBtn" onclick="signApproval();" class="neo-btn bg-[#86EFAC] hover:bg-[#4ADE80] font-black uppercase text-sm px-6 py-3">
                Sign & Approve Award &check;
              </button>
              <button id="exportBtn" disabled onclick="downloadERPPayload();" class="neo-btn bg-white hover:bg-slate-100 font-bold uppercase text-xs px-4 py-3 opacity-50 cursor-not-allowed">
                Export Farvision PO
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
    async function submitRequisition() {
      const payload = {
        raw_text: document.getElementById('reqText').value || "dr fixit fastflex chemical for waterproofing at amara tower 2",
        project_name: document.getElementById('reqProject').value,
        tower: document.getElementById('reqTower').value,
        quantity: parseFloat(document.getElementById('reqQty').value),
        required_by_date: document.getElementById('reqDate').value
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
      } catch (err) {
        alert("Catalog matching failed: " + err);
      }
    }

    async function signApproval() {
      const payload = {
        statement_id: "CS-AMR-T2-E2E",
        approved_by: "Arindam Mukherjee (HOD Projects)",
        remarks: "Approved Asian Paints as recommended. Zero dispute risk prioritised."
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
          btn.className = "neo-btn bg-slate-300 font-bold uppercase text-xs px-6 py-3 cursor-not-allowed";

          const exportBtn = document.getElementById('exportBtn');
          exportBtn.disabled = false;
          exportBtn.classList.remove('opacity-50', 'cursor-not-allowed');
          exportBtn.className = "neo-btn bg-[#67E8F9] hover:bg-[#22D3EE] font-bold uppercase text-xs px-4 py-3";

          const banner = document.getElementById('approvalBanner');
          banner.classList.remove('hidden');
          banner.innerHTML = `
            <div>&check; DIGITAL SIGNATURE RECORDED: Arindam Mukherjee (HOD Projects) &bull; ${new Date().toLocaleTimeString()}</div>
            <div class="text-slate-800 font-normal">Audit Reference: FARVISION-PO-CS-AMR-T2-E2E &bull; Ready for ERP Injection</div>
          `;
        }
      } catch (err) {
        alert("Approval failed: " + err);
      }
    }

    async function downloadERPPayload() {
      try {
        const res = await fetch('/api/v1/erp/export/CS-AMR-T2-E2E');
        const data = await res.json();
        const jsonStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(data, null, 2));
        const downloadAnchor = document.createElement('a');
        downloadAnchor.setAttribute("href", jsonStr);
        downloadAnchor.setAttribute("download", "farvision_po_export_CS-AMR-T2-E2E.json");
        document.body.appendChild(downloadAnchor);
        downloadAnchor.click();
        downloadAnchor.remove();
      } catch (err) {
        alert("Failed to export: " + err);
      }
    }
  </script>
</body>
</html>
    """
