# Web Design Guidelines Audit Report
**Target**: `src/main.py` (Neobrutalism Executive Procurement Cockpit)  
**Guidelines Standard**: Web Interface Guidelines (Vercel / W3C WCAG 2.1 AA)  
**Style System**: [Neobrutalism.dev](https://www.neobrutalism.dev/)

---

## 1. Design & Typography Audit

- [x] **Typography Scale**: Uses `Space Grotesk` for headlines and high-readability body text; uses `Space Mono` for numbers, currencies, item codes, and badges.
- [x] **High Contrast Accessibility**:
  - Background is soft cream `#FEFCE8` with pure black borders (`#000000`).
  - Text is `#000000` on yellow (`#FDE047`), green (`#86EFAC`), and white backgrounds (contrast ratio > 12:1, far exceeding WCAG AAA standard of 7:1).
  - Clear visual demarcation between table rows and data cells.
- [x] **Tactile Neobrutalist Feedback**:
  - Hard non-blurred shadows (`box-shadow: 4px 4px 0px 0px #000000`).
  - Active and hover states have physical translations (`transform: translate(2px, 2px)` on hover and `translate(4px, 4px)` on click).
  - Explicit cursor styles (`cursor-pointer` on interactive elements, `cursor-not-allowed` on disabled buttons).

---

## 2. Interaction & Functional Audit

- [x] **Interactive Requisition Matching**: Form allows entering site text and renders Farvision item code, baseline budget rate, and duplicate order alerts directly.
- [x] **Direct State Progression**:
  - Default status: `STATUS: AWAITING HOD APPROVAL` (Amber banner).
  - Upon clicking `Sign & Approve Award`:
    - Status changes to `STATUS: APPROVED BY HOD` (Mint green banner).
    - Approval button disables and changes state to `Approved & Signed`.
    - Farvision Export button activates (`bg-[#67E8F9]` cyan), enabling 1-click JSON download of the PO payload.
    - Timestamped digital audit log banner appears.
- [x] **Mobile Responsiveness**:
  - Flex headers wrap cleanly on smaller mobile screens (`flex-col md:flex-row`).
  - 12-column grid collapses to a single stacked column on tablets and phones (`grid-cols-1 lg:grid-cols-12`).
  - Comparative statement table is enclosed in a horizontal overflow container (`overflow-x-auto`) to preserve readability without page layout breakage.

---

## 3. Findings & Resolution

| Rule / Component | Audit Finding | Resolution Applied |
|---|---|---|
| `viewport` Meta Tag | Crucial for mobile scaling and preventing horizontal overflow. | Verified present: `<meta name="viewport" content="width=device-width, initial-scale=1.0">`. |
| Focus Outlines | Standard Neobrutalism often removes browser outlines. | Custom high-contrast `:focus` shadow and border applied to all inputs (`box-shadow: 4px 4px 0px 0px #000000`). |
| Form Semantics | Screen readers require explicit label tags. | Every input has a dedicated `<label class="block text-xs font-mono font-bold uppercase mb-1">` attached. |
| Button Disabled States | Disabled buttons must visually communicate non-interactive state. | Disabled buttons have explicit `opacity-50 cursor-not-allowed` styles. |
