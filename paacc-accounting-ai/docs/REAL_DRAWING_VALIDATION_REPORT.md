# Real Document Validation Report – Phase 4.1

**Redaction:** this committed version contains no confidential data: no company or person names, prices, bank
details, project identity or complete item lists. Full per-item results and the expected values live in the private
golden dataset (`test-data/golden-dataset/`, git-ignored) and were delivered to the requester outside GitHub.

## 1. What was supplied

| # | File type | Pages / sheets | Role | Processed by the drawing pipeline? |
|---|---|---|---|---|
| R1 | PDF, 2 pages | 2 vector pages (text layer, 3 embedded images: letterhead, signature/seal) | **Supplier quotation for road-safety (ATGT) materials, printed from Excel with "Microsoft: Print To PDF"** | yes |
| W1 | `.xlsx` quotation workbook | 5 sheets (quotation, unit-price analysis, material/labour prices, price summary) | company quotation template (Module 02/03 – pricing) | no (not a PDF) |
| W2, W3 | `.xlsx` quotation workbooks (two revisions of one quotation) | 12 sheets each, 7 hidden | company quotation template | no |
| W4 | `.xls` (Excel 97) quantity-takeoff workbook for a road-safety section | 15 sheets (summary + one sheet per work type) | **company BOQ / quantity template** (`Tong hop` sheet) | no |

### Key finding 1: no construction drawing was supplied
The only PDF is a quotation table, not a drawing. It has no plan or section geometry, no title block, no scale, no
dimension lines and no drawing number. The validation therefore exercises table, dimension-text, material, BOQ,
duplicate and export logic on a real document. It **cannot** validate:
- title-block reading (drawing number, revision)
- scale and unit detection
- dimensions placed on geometry
- cross-sheet duplicates
- scanned-drawing OCR

Those remain **unvalidated on real data** and need real drawing PDFs.

### Key finding 2: the files are not anonymised
- R1 shows two company names, the project, a bank account number, a signature and a company seal.
- W4's file properties contain personal names.

Nothing from these files, and no value derived from them, is committed. See §7.

### Ground truth
- R1's 59 table rows (50 quantity lines, 9 group headings) were transcribed by visual reading of the rendered pages.
- Every row was confirmed against the PDF text layer (59/59).
- Quantity lines were cross-referenced with W4 where comparable: 35/50 agree exactly. Of the rest:
  - 2 differ, for explained reasons (below).
  - 13 are not comparable: W4 breaks the fence and glare-screen components down into kg of steel, not pieces.
- Ambiguous values are recorded as ambiguous (e.g. `L=6.100mm`). Values that look like source typos (e.g. `L=1,89mm`
  for a 1.89 m post) are recorded as needing engineer confirmation. No expected value was guessed.

Explained discrepancies between sources (not pipeline errors):
- **Guardrail length differs by 7 m (0.5 %).** The quotation computes the length from components:
  - Its formula is `panels × 4 m + end pieces × 3 m`.
  - The takeoff gives the measured route length.
  - An engineer must decide which applies.
- **Reflective road studs:** the quotation quantity matches the takeoff's *new* studs line, not its total (the total includes re-used studs).

## 2. Baseline (existing Phase 4 code, commit `c0f6bfa`, before any change)

Pipeline steps: all succeeded – processed (2 vector pages) → analysis → draft BOQ (36 items) → simulated review
(25 accepted, 11 rejected) → submit → approve (second user) → Excel export.

| Category | Verified denominator | Baseline correct | Notes |
|---|---|---|---|
| Page metadata (number, title, revision, scale, units, page kind × 2 pages) | 12 | **11** | footer `1/2` taken as a 1:2 scale candidate |
| Dimensions | 60 | **19** (+28 partial, 6 incorrect, 7 missing) | plus 26 false-positive "dimensions" (table quantities such as `726,00`) and the brand `3M` read as 3 m |
| Materials / specifications | 7 | **0** | sign codes, sheeting grades, guardrail/fence types not recognised |
| BOQ rows (description + unit + quantity) | 50 | **0** (25 partial, 1 incorrect, 24 missing) | page-1 table lost; descriptions replaced by "Dòng N" |
| Group / hierarchy context of BOQ rows | 26 matched rows | **0** | no hierarchy captured |
| Duplicate / overlap handling | 38 cases | **0** | component-of-assembly not modelled; cases unmatched because rows were missing |
| BOQ false-positive items | – | 10 | 5 phantom concrete items, 5 heading rows as items |

Percentages are deliberately omitted where they would mislead. Each "correct" count above is out of a verified denominator.

### Baseline errors by root cause
| # | Root cause | Effect | Class |
|---|---|---|---|
| B1 | Table header assumed to be row 0; text printed above the table became row 0 | entire page-1 table (25 quantity lines) not mapped → MISSING | INCORRECT |
| B2 | Header synonyms are exact matches; the combined header "Chủng loại, quy cách" (type, specification) matched nothing | descriptions lost ("Dòng N") → PARTIALLY_CORRECT for 25 rows | INCORRECT |
| B3 | Group headings / sub-headers (no unit, no quantity) turned into BOQ items | 5 blocking noise items | INCORRECT |
| B4 | Hierarchy (I / 1 / 4.1) and page-break continuation not captured | children not linked to their assembly; page-2 rows lose group 4.2 | MISSING |
| B5 | Text lines inside a schedule table also run through the annotation rules; "Cột" (post) triggers the concrete rule | 5 phantom concrete items (steel posts) | INCORRECT / DUPLICATE |
| B6 | Bare numbers inside table cells classified as dimensions | 26 false-positive dimensions | INCORRECT |
| B7 | Unlabelled `1/N` accepted as a scale | false 1:2 scale candidate from the page footer | INCORRECT |
| B8 | `D`-prefixed round sections (`D88.3`, `D140x4.5x2500`, `D75x3,25`) and bolts (`M16x35`, `Bu lông D20x180mm`) not recognised | 7 MISSING, 21 PARTIALLY_CORRECT | MISSING |
| B9 | Mixed separators inside one token not resolved (`6.014x4.10m`) | value dropped as ambiguous although the token itself proves `.` is decimal | INCORRECT |
| B10 | Implausible post lengths (`L=1,89mm`) accepted silently | 6 silent acceptances | REQUIRES_ENGINEER_CONFIRMATION missed |
| B11 | Length expressions `L=(4700+5200)mm` not parsed | 2 MISSING | MISSING |
| B12 | `3M` (brand) read as 3 metres | 1 false positive | INCORRECT |
| B13 | No road-safety (ATGT) vocabulary: sign codes (QCVN 41), reflective-sheeting grades, guardrail/fence types; all items fall in category `other` | 0/7 materials; meaningless totals mixing signs with bolts | MISSING |

Correctly handled at baseline:
- page kind (vector)
- explicit-unit sections (`1.44x0.9m`, `624x389x4.3mm`)
- labelled lengths (`L=5150mm`, `L=4.33m`)
- Vietnamese thousands/decimal quantities (`3.998,17` → 3998.17)
- the genuinely ambiguous `L=6.100mm` (flagged, not guessed)
- no false drawing number, title or revision
- the full review → four-eyes approval → Excel export workflow

*(Sections 3–8 are written after tuning; see below.)*
