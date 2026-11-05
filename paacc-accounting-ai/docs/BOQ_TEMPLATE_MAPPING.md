# Company BOQ / quotation template → PAACC mapping (Phase 4.1)

**Source:** the company workbooks supplied in Phase 4.1 (one quantity-takeoff workbook, three quotation workbooks).
Only their *structure* is described here. No quantities, prices, names, chainages or project data are reproduced.
The original files were never modified: they were read from a separate copy, and the export layer does not load them at all.

## 1. Inventory

| Workbook | Sheets (hidden in italics) | Role |
|---|---|---|
| Quantity takeoff (`.xls`, Excel 97) | `Tong hop` (summary), `Bien bao` (signs), `VachSon` (markings), `Ton lượn sóng` (guardrail), `Hàng rào B40` (fence), `Nang TLS -ben phai/trai` (raised guardrail L/R), `Dai phan cach be tong` (barrier), `Dinh phan quang` (studs), `TPQ tren cau va DPC`, *`Duong dan sinh`, `Duong gom`, `ATGT`, `Nut giao`, `foxz`* | **quantity BOQ – target of the PAACC export** |
| Quotation (`.xlsx`, ×3 revisions) | `Input`, `BG ` (quotation), `PT Đơn giá` (unit-price analysis, ~8–14k formulas), `ĐG VT_NC` (material/labour prices), `Sheet4`, *`BG - HSL BS`, `ATGT`, `Sheet1-3`, `BAO GIA VA Bung`, `Nhap`* | pricing (Module 02/03, Phase 6) – mapped for reference only |

## 2. Quantity BOQ sheet `Tong hop` → PAACC

| Template | Content in template | PAACC source | Notes |
|---|---|---|---|
| A `STT` (24.1) | hierarchy codes `VII`, `1`, `2`, … ; location (Km chainage) on some item rows | `boq_items.group_path[].code` (source codes) or synthesised `1..n` per category | Chainage is not modelled in PAACC → not reproduced. |
| B `HẠNG MỤC` (52.7) | description incl. specification text; sub-items indented with spaces or `-` | `description` | Assembly components are italic and indented (`component_of_parent`). |
| C `ĐƠN VỊ` (12.2) | unit as typed: `cái`, `cột`, `m`, `m2`, `m3`, `kg`, `tấn`, `bộ`, `modul` | `unit` (raw, e.g. `m3` – **not** `m³`, to match the template) | The template itself contains unit errors (bolts in `m3`, rebar in `m3`); PAACC writes the unit of the item. |
| D `TỔNG KHỐI LƯỢNG` (25.6) | value or formula; many are **external links** (`'[n]Sheet'!J62`) or design-rule formulas | live formula `='Tính chi tiết'!B<n>` to the PAACC calculation block (Decimal engine result) | Same accounting number format as the template. |
| E `GHI CHÚ` (27.2) | "Làm mới" (new) / "Tận dụng …" (re-used) / free notes | review status (if not accepted) + last engineer note | New / re-used is not a PAACC field yet. |
| — | — | **F `NGUỒN / TRUY VẾT (PAACC)`**: drawing sheet, page, item id | **Extension** outside the template's print area A:E; full trace also in the `Truy vết nguồn` sheet. |

**Formatting reproduced** (from `app/boq/company_layout.py`):
- Times New Roman 12 throughout.
- Header rows 2–3, each column merged vertically, grey fill `C0C0C0`, bold, centred, wrapped.
- Thin borders on every cell.
- Level-1 groups (`1`, `2`, …) bold with yellow fill `FFFF00`; Roman sections and deeper codes bold.
- Accounting format `_-* #,##0.00_-;\-* #,##0.00_-;_-* \-??_-;_-@_-` on column D.
- A3 landscape, print titles rows 1–3, print area A:E, frozen below the header.
- Row 1 carries the title, version and approval status (the template leaves row 1 empty).

**Subtotals and totals:** the template has none on the quantity sheet. Group rows carry no quantity because units
differ inside a group, and PAACC does the same.

**Workbook produced with `layout=company_kl`:** `Tong hop` (company layout), `BOQ` (PAACC detail with traceability), `Tính chi tiết`
(formulas over input cells) and `Truy vết nguồn` (source drawings with SHA-256). Approved/draft status appears in row 1 and in the footer.
Rejected items are excluded from `Tong hop` but kept in `BOQ`.

## 3. Quotation sheet `BG ` (reference for Phase 6)

| Template | Content |
|---|---|
| Rows 7–13 | title `BÁO GIÁ`, recipient, project, package, work item (merged B:K) |
| Rows 14–15 | header: `STT` · `Chủng loại, quy cách` · `ĐVT` · `Số lượng` · `ĐG/m2 ĐG/md` · `Đơn giá (VNĐ)` / `Cung cấp vật tư` · `Thành tiền (VNĐ)` · `Ghi chú` |
| Body | same hierarchy as the takeoff (I / 1 / 4.1); assembly rows carry the price; components carry quantities only |
| Formulas | unit price = `ROUND(cost × (1+markup1) × (1+markup2), -3)` from hidden columns; amount = quantity × price; one assembly length is computed from its components (panels × 4 m + end pieces × 3 m) |
| Footer | conditions, payment terms, bank details, signatures |

PAACC does not export quotations yet. Prices, markups and the `PT Đơn giá` cost analysis belong to Phase 6
(Estimation). The quantity columns map 1:1 to PAACC BOQ items, and the PAACC import of supplier quotations
(Phase 4.1 table logic) already reads this layout.

## 4. Not reproduced (deliberately), with reasons

| Template feature | Why not | Where it belongs |
|---|---|---|
| External links (`'[3]Bien bao'!J62`) between workbooks | links to files outside PAACC; PAACC keeps quantities in its own database + calculation sheet | replaced by in-workbook formulas |
| Design-rule lines derived from counts (e.g. foundation concrete = number of posts × fixed foundation dimensions; anchor bolts per gantry) | these are **company standard details, not values on the drawing**; generating them would invent quantities | future engineer-maintained "standard detail" rules with versioned parameters (Phase 6) |
| Per-work-type detail sheets with Km chainage per item | no chainage / alignment model in PAACC yet | Phase 7/9 (site and alignment model) |
| Legacy TCVN3/ABC-encoded text (e.g. `VÞ trÝ cöa ra - vµo`) present in the takeoff workbook | needs a verified TCVN3→Unicode conversion | backlog (high priority for CAD PDFs too) |
| Copying the company file itself as a base workbook | contains other projects' data, external links, WMF logo and data-validation extensions that openpyxl silently drops | layout reproduced from this specification instead |
| New/re-used marking (`Làm mới` / `Tận dụng`) | no PAACC field yet | BOQ item attribute (backlog) |
