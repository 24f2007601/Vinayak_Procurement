# Project Milestones & Progress Tracker
**Project**: Vinayak Group AI Procurement Copilot  
**Repository**: [https://github.com/24f2007601/Vinayak_Procurement](https://github.com/24f2007601/Vinayak_Procurement)  
**Governing Rule**: This document MUST be updated whenever any milestone phase code change is made.

---

## Progress Overview

| Phase | Description | Status | Completion Date | Commit |
|:---:|---|:---:|:---:|:---:|
| **Phase 1** | Foundation, Schemas & Deterministic Cost Engine | **COMPLETED** (100%) | 2026-11-24 | [`b1c550a`](https://github.com/24f2007601/Vinayak_Procurement/commit/b1c550a) |
| **Phase 2** | Ingestion & Multimodal Extraction Pipeline | **COMPLETED** (100%) | 2026-11-24 | [`68aedfa`](https://github.com/24f2007601/Vinayak_Procurement/commit/68aedfa) |
| **Phase 3** | Comparative Statement Engine & HOD Dashboard | **COMPLETED** (100%) | 2026-11-24 | Pending commit |
| **Phase 4** | Farvision ERP Bridge & Security Hardening | **COMPLETED** (100%) | 2026-11-24 | Pending commit |

---

## Detailed Milestone Checklist

### Phase 1: Foundation, Schemas & Deterministic Math Engine
- [x] **M1.1: Core Constants & Configuration** (`src/constants.py`)
  - [x] Unit conversion factors (`SQFT_PER_SQM`, `LITRES_PER_STANDARD_DRUM`, `KG_PER_METRIC_TON`).
  - [x] Standard GST tax rates (18%, 28%, 0%).
  - [x] Scoring weights (60% Price, 25% Delivery, 15% Quality).
  - [x] Dispute penalty ratios.
- [x] **M1.2: Domain Models & Typed Schemas** (`src/models/`)
  - [x] Requisition and Farvision catalog models (`src/models/requisition.py`).
  - [x] Raw vendor quotation and normalized quote items (`src/models/quote.py`).
  - [x] Vendor track record, ranked vendor, and comparative statement (`src/models/comparative.py`).
- [x] **M1.3: Deterministic Cost Normalizer** (`src/services/cost_engine.py`)
  - [x] Pure deterministic unit conversion function (`convert_quantity`).
  - [x] Exact GST tax calculator (`calculate_tax`).
  - [x] Landed cost and normalized rate per BOQ unit (`normalize_quote`).
- [x] **M1.4: Scoring & Comparative Engine** (`src/services/scoring_engine.py`)
  - [x] Relative price scoring vs. true L1 (`calculate_price_score`).
  - [x] Weighted composite score with dispute deduction (`calculate_composite_score`).
  - [x] Plain-English audit rationale generator (`compose_decision_rationale`).
  - [x] End-to-end comparative compiler (`generate_comparative_statement`).
- [x] **M1.5: Automated Verification Suite** (`tests/`)
  - [x] Test fixtures for *Waterproofing at Vinayak Amara, Tower-2* (`tests/conftest.py`).
  - [x] 100% deterministic test coverage for cost engine (`tests/test_cost_engine.py`).
  - [x] End-to-end comparative verification with 3 competing vendors (`tests/test_scoring_engine.py`).

---

### Phase 2: Ingestion & Multimodal Extraction Pipeline
- [x] **M2.1: Requisition Parser & Farvision Matcher** (`src/services/catalog_service.py`)
  - [x] Raw text / WhatsApp input parsing and token matching.
  - [x] Levenshtein & Jaccard catalog matcher against Farvision item codes.
  - [x] Duplicate requisition detector (checks active site orders to prevent over-ordering).
- [x] **M2.2: Multimodal Quote Extraction Service** (`src/services/extractor_service.py`)
  - [x] Groq LLM (Llama-3.3-70B) extraction engine for generous free-tier throughput.
  - [x] Deterministic heuristic parser fallback for offline testing.
  - [x] Prompt injection containment (<document_content> sandbox tags).
  - [x] Extraction sanitization against numeric tampering.
- [x] **M2.3: Vendor History & Dispute Store** (`src/services/vendor_service.py`)
  - [x] Central vendor track record repository for Kolkata projects.
  - [x] Dynamic performance lookup and dispute logging.
- [x] **M2.4: Phase 2 Test Verification** (`tests/test_phase_2.py`)
  - [x] Unit tests for catalog fuzzy matching.
  - [x] Duplicate requisition alert verification.
  - [x] Structured quote extraction and prompt injection defense tests.

---

### Phase 3: Comparative Statement Engine & HOD Approval Cockpit
- [x] **M3.1: Comparative Statement Generator API** (`src/main.py`)
  - [x] REST API endpoints for uploading quotes and generating comparative statement JSON.
  - [x] Identification and flagging of commercial exclusions.
- [x] **M3.2: Executive HOD Approval Interface (UI)** (`src/main.py`)
  - [x] Requisition input view for site engineers.
  - [x] High-density side-by-side comparative matrix table.
  - [x] One-click HOD recommendation card with plain-English trade-off summary.
- [x] **M3.3: Phase 3 Test Verification** (`tests/test_api_flow.py`)
  - [x] API integration tests (`TestClient`).
  - [x] Approval workflow state transition tests (`PENDING` $\rightarrow$ `APPROVED`).

---

### Phase 4: Production Hardening, ERP Bridge & Deployment
- [x] **M4.1: Farvision ERP Export Staging Bridge** (`src/main.py`)
  - [x] Farvision-compliant JSON/CSV PO staging payload generator (`/api/v1/erp/export/{id}`).
  - [x] PO reference, line-item rate, and approved audit rationale export.
- [x] **M4.2: Security & Access Control Hardening** (`SECURITY_AUDIT.md`)
  - [x] Role-based access control rules enforced (no unapproved PO export).
  - [x] Immutable audit log parameters preserved on approval.
- [x] **M4.3: Health Checks & Interactive Documentation**
  - [x] Automated `/health` endpoint.
  - [x] Interactive OpenAPI/Swagger documentation (`/docs`).

---

## Mandatory Milestone Update Workflow

Whenever any developer or AI agent finishes a task or milestone in this project:
1. **Verify**: Ensure all automated tests pass (`uv run --with pytest --with pydantic --with fastapi --with httpx pytest tests/`).
2. **Update**: Mark the completed checkboxes `[x]` in `MILESTONES_TRACKER.md` and record the commit hash.
3. **Commit Together**: The code change and the updated `MILESTONES_TRACKER.md` MUST be committed in the same git commit:
   ```bash
   git add <modified_code_files> MILESTONES_TRACKER.md
   git commit -m "feat(<phase>): <description> and update milestones tracker"
   ```
