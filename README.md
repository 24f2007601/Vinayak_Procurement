# Vinayak Procurement Copilot
**AI-Assisted Construction Procurement: From Site Requirement to Vendor Comparative**

[![GitHub Repository](https://img.shields.io/badge/GitHub-24f2007601%2FVinayak__Procurement-blue?logo=github)](https://github.com/24f2007601/Vinayak_Procurement)

> **Repository URL**: [https://github.com/24f2007601/Vinayak_Procurement](https://github.com/24f2007601/Vinayak_Procurement)

---

## Overview

**Vinayak Procurement Copilot** is an enterprise AI procurement assistant tailored for mid-market residential real estate developers (Vinayak Group, Kolkata — 5 active projects). 

It automates the manual, error-prone procurement lifecycle:
1. **Site Ingestion**: Captures site requisitions from WhatsApp, voice notes, or handwritten slips into structured Farvision ERP item codes.
2. **Duplicate & Budget Check**: Prevents over-ordering by verifying requisitions against live project BOQ budgets.
3. **RFQ Dispatch**: Sandboxed RFQ generation sent to category-approved vendors.
4. **Multimodal Quote Normalization**: Extracts unstructured PDF/email quotes and normalizes unit rates, GST (18%/28%), freight, payment terms, and scope exclusions.
5. **Comparative Statement (CS) Matrix**: Deterministic apples-to-apples cost comparison and scoring (60% Landed Cost, 25% Delivery Track Record, 15% Quality History).
6. **Executive HOD Decision Deck**: Clear, plain-English trade-off recommendations for HOD sign-off before ERP purchase order creation.

---

## Core Documentation

- **[PRODUCT_PLAN.md](file:///c:/Users/prith/Projects/Vinayak_Procurement/PRODUCT_PLAN.md)**: Product strategy, business case, personas, data models, and the `/ponytail` elimination ledger.
- **[SYSTEM_ARCHITECTURE.md](file:///c:/Users/prith/Projects/Vinayak_Procurement/SYSTEM_ARCHITECTURE.md)**: Architecture diagram, trust boundaries, deterministic math vs. probabilistic extraction, and schema design.
- **[PHASE_ROADMAP.md](file:///c:/Users/prith/Projects/Vinayak_Procurement/PHASE_ROADMAP.md)**: 4-phase staged delivery plan from core math engine to production hardening.
- **[SECURITY_AUDIT.md](file:///c:/Users/prith/Projects/Vinayak_Procurement/SECURITY_AUDIT.md)**: Threat model, prompt injection defense, financial integrity rules, and RBAC matrix.

---

## Core Tenets (`/ponytail`)

1. **Deterministic Arithmetic, Probabilistic Extraction**: LLMs extract parameters; pure Python code calculates landed costs and scores. Zero LLM math.
2. **AI Recommends, Human Sanctions**: The system advises with full audit trails; the HOD approves.
3. **Traceability to Source**: Every line item links back to the original vendor quotation document.
4. **Safety Compliance**: Never email real vendors—all RFQs route to sandboxed test inboxes.
