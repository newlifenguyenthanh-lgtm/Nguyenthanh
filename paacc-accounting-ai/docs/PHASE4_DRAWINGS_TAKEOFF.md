# Phase 4 – PDF Drawing AI, Quantity Takeoff, BOQ Review & Excel Export

Status: **foundation complete and verified end-to-end on synthetic drawings**. It has **not yet been validated on real
construction drawings**: accuracy claims for real sheets must wait for anonymised samples (see §7).

## 1. Pipeline

```
upload PDF (immutable document version, SHA-256)
  → 4A extraction (read-only): text lines / tables / metadata; scanned pages → Tesseract OCR (vie+eng)
  → 4B analysis (rules): title block, scale & unit CANDIDATES, dimensions, specs, symbols, references, regions, duplicates, revisions
  → engineer confirms scale/units per page (audited)
  → 4C draft BOQ: rule-based components + Decimal engine; schedule rows copied verbatim; flags
  → 4D review: edit (reason) / accept / reject (note) / annotate → submit → approve (other person, boq:approve)
  → 4E Excel export (live formulas + traceability), stored and versioned
```
Each processing or generation step writes an `ai_tasks` row, so the 3D office (Engineering & QS) shows real status.

## 2. Principles enforced in code
| Rule | Where |
|---|---|
| Original files are never modified (bytes only, content-addressed store) | `app/pdf/extract.py`, `app/storage.py`, test `test_extraction_and_rendering_never_modify_input` |
| Every value keeps page + bbox (PDF points, displayed space, top-left origin) + source item id | `extracted_items`, `boq_items.bbox/source_item_ids` |
| Scale/units are only candidates until a human confirms them | `drawing_pages.scale_status/units_status`, `POST …/calibration` |
| Missing values are never invented; ambiguous numbers (6,000) are flagged, not guessed | `app/pdf/analysis.py::parse_number`, `app/boq/generate.py` |
| Quantities are computed only by the deterministic Decimal engine; LLMs never compute | `app/takeoff/engine.py` |
| Provenance per input: `extracted` / `ai_inferred` / `engineer` (previous value kept) | `boq_items.inputs` |
| Approval needs `boq:approve` and a different person from the submitter (four-eyes) | `app/boq/workflow.py::decide`, setting `PAACC_BOQ_FOUR_EYES` |
| Accepting a possible duplicate requires a confirmation note | `workflow.review_item` |
| Approved BOQs are immutable; changes create a new version | `workflow.new_version` |

## 3. What is recognised (rule-based, Vietnamese + English)
- **Title block:** drawing number, title, revision, project, scale (`TỶ LỆ 1:100`, `SCALE 1/50`, NTS), units (`ĐƠN VỊ: mm`).
- **Dimensions:** sections `300x600`, `50x50x2`; bars `Ø16a200`; labelled `L=6000`, `H=3,5m`; counts `SL=24`; stated `12,5 m3`; bare CAD numbers. Bare numbers get low confidence and "unit not stated".
- **Specs:** concrete grade (`B25`, `M300`, `C25/30`, with a concrete cue), rebar grade (`CB400-V`, `CIII`, `SD390`), steel grade (`SS400`, `Q345B`), hollow sections, plates (`PL10`), profiles (`I200`, `L50x50x5`).
- **Symbols:** elevations (`+3.600`), slopes (`i=2%`), section and detail markers. **References:** `xem bản vẽ KC-05`, `CHI TIẾT 3/KC-04`.
- **Classification:** disciplines (architectural, structural, traffic, infrastructure, MEP) and view types (plan, section, elevation, detail, schedule, profile). Each comes with its basis (title, number prefix or page text) and a confidence.
- **Draft BOQ components:** concrete prism, rebar by diameter, hollow box, plate, steel profile, and schedule-table rows.
  - Profile kg/m is never looked up: the engineer must enter it.
- **Duplicates:**
  - On the drawing: overprinted identical text, repeated annotations, duplicate pages, the same drawing number twice, identical files, and revision conflicts.
  - In the BOQ: the same source annotation, an identical calculation, or a schedule row versus an annotation (with a quantity-match check).

Confidence = pattern certainty × OCR confidence. For example, `300x600` without a unit = 0.8; read by OCR at 0.74 → 0.59.

## 4. API (all under `/api/v1`, company-scoped, audited)
| Area | Endpoints |
|---|---|
| Drawings | `POST /drawings`, `GET /drawings`, `GET /drawings/{id}`, `GET /drawings/{id}/items?page&kind&q`, `GET /drawings/{id}/pages/{n}/image`, `POST /drawings/{id}/pages/{n}/calibration`, `GET /drawing-sheets?number=` |
| BOQ | `POST /boqs`, `GET /boqs`, `GET /boqs/{id}`, `PATCH /boqs/{id}/rules`, `POST /boqs/{id}/items`, `PATCH /boqs/{id}/items/{iid}`, `POST …/review`, `POST …/notes`, `GET …/history`, `POST /boqs/{id}/submit`, `POST /boqs/{id}/decision`, `POST /boqs/{id}/new-version`, `GET /takeoff/modules` |
| Export | `POST /boqs/{id}/exports`, `GET /boqs/{id}/exports`, `GET /projects/{id}/boq-exports`, `GET /boq-exports/{id}/download` |

Permissions:
- `drawing:read/write`
- `boq:read/write/approve`:
  - `approve` is held only by director and admin.
  - `write` is held by the new `qs_engineer` role, which cannot approve.

## 5. Excel workbook
- **Tổng hợp:** status banner (draft or approved), approver, rules, and `SUMIFS` totals over accepted rows.
- **BOQ:** item number, category, description, spec, unit (m³, m², kg…), quantity, formula, drawing sheet, page, region, provenance, review status, flags, notes and item ID.
- **Tính chi tiết:** every input in its own cell, and the quantity as an Excel formula over those cells, including waste and `ROUND`.
- **Truy vết nguồn:** source drawings with document version and SHA-256, plus the source text of each item.

Formula integrity is tested by recalculating the file in LibreOffice and comparing every quantity and total with the Decimal engine.

## 6. Verified
- Automated tests (SQLite + PostgreSQL) cover:
  - vector extraction, scanned OCR (fake engine plus real Tesseract), dimensions, scale/unit validation
  - deterministic calculations, duplicates, review and approval permissions, revision history
  - Excel structure, formulas and traceability, AI-task integration, multi-company isolation, migrations.
- End-to-end in a headless browser on PostgreSQL with real Tesseract OCR, using a QS engineer and a director account:
  1. Upload a 2-page PDF (vector and scanned), process it, and inspect dimensions with overlays.
  2. Confirm scale and units.
  3. Generate a draft BOQ, review it (corrections, duplicate rejections, notes), and submit.
  4. The 3D office shows "waiting for approval"; the director approves.
  5. Export to Excel; the recalculated totals match.

## 7. Known limitations / next steps
- **Validated only on synthetic drawings.** Real Vietnamese drawing conventions (title-block layouts, CAD fonts, dimension styles) will need rule tuning against anonymised samples.
- **No geometric measurement.** Lengths and areas are not measured from vector paths. `real_length_from_paper` exists and requires a confirmed scale, but it is not yet wired to geometry. Quantities come only from written annotations and schedules.
- **Tables:**
  - Detection relies on ruled tables; borderless schedules are not detected.
  - OCR pages have no table detection.
  - Rotated dimension text is extracted, but not associated with dimension lines.
- **Processing is synchronous** within the request; large sets need a worker (Celery/Redis), and OCR time grows with page size.
- **No AI agent yet:** an `ai_inferred` agent is not implemented. The provenance model supports it, but no LLM is called.
- **Excel template:** the company template is not yet applied; the workbook uses PAACC's own layout. To add it, provide the template and map its columns in `app/boq/excel.py`.
- **User management** is CLI-only (`python -m app.cli create-user`).
