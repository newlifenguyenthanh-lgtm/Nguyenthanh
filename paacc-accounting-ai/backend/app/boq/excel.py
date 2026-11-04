"""Professional BOQ workbook (OpenPyXL) with live formulas and full source traceability.

Sheets
- "Tổng hợp": header (status, approval, rules) + totals per category/unit via SUMIFS over ACCEPTED rows.
- "BOQ": detailed quantities; each quantity cell references its calculation block.
- "Tính chi tiết": one block per item - every input in its own cell (with provenance) and the
  quantity as an Excel formula over those cells, so a reviewer can audit/change inputs in Excel.
- "Truy vết nguồn": source drawings (document version, SHA-256) and per-item page / region / source text.
Formulas use only standard functions (ROUND, PI, SUMIFS, COUNTIFS) so Excel and LibreOffice agree.
"""
import io
import re
from dataclasses import dataclass, field

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

UNIT_LABEL = {"m3": "m³", "m2": "m²", "kg": "kg", "m": "m", "cái": "cái", "tấn": "tấn", "bộ": "bộ", "tấm": "tấm", "thanh": "thanh"}
CATEGORY_VI = {"concrete": "Bê tông", "rebar": "Cốt thép", "structural_steel": "Thép hình", "steel_box": "Thép hộp",
               "plate": "Bản mã / thép tấm", "other": "Khác"}
REVIEW_VI = {"pending": "Chờ rà soát", "accepted": "Chấp nhận", "rejected": "Loại bỏ"}
ORIGIN_VI = {"extracted": "Trích xuất từ bản vẽ", "ai_inferred": "AI suy luận", "engineer": "Kỹ sư nhập", "mixed": "Hỗn hợp",
             "rule": "Quy tắc đo bóc"}
STATUS_VI = {"draft": "BẢN NHÁP – CHƯA PHÊ DUYỆT", "submitted": "ĐANG CHỜ PHÊ DUYỆT – CHƯA CÓ HIỆU LỰC",
             "returned": "BỊ TRẢ LẠI – CHƯA PHÊ DUYỆT", "approved": "ĐÃ PHÊ DUYỆT"}
DERIVED_LABEL = {"to_m": "Hệ số đổi đơn vị → m", "steel_density": "Tỷ trọng thép (kg/m³)"}

HEAD_FILL = PatternFill("solid", fgColor="14325C")
SUB_FILL = PatternFill("solid", fgColor="E8EEF7")
WARN_FILL = PatternFill("solid", fgColor="FFF4E5")
THIN = Side(style="thin", color="B8C2D0")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WHITE_BOLD = Font(bold=True, color="FFFFFF")


@dataclass
class ExportItem:
    item_no: int
    category: str
    description: str
    spec: str
    unit: str | None
    quantity: str | None
    module: str | None
    excel_expr: str | None
    calc_inputs: dict[str, str]
    input_labels: dict[str, str]
    input_meta: dict[str, dict]  # name -> {origin, source_item_id, note}
    waste_factor: str
    formula_text: str
    review_status: str
    origin: str
    notes: str
    flags: list[dict]
    drawing_label: str
    page_no: int | None
    bbox: list[float] | None
    source_text: str
    item_id: str
    unit_system: str | None


@dataclass
class ExportMeta:
    company: str
    title: str
    version_no: int
    status: str
    project: str
    rules: dict
    submitted: str = ""
    decided: str = ""
    decision_note: str = ""
    exported_by: str = ""
    exported_at: str = ""
    sources: list[dict] = field(default_factory=list)  # {label, filename, version_no, sha256, pages, drawing_id}


def unit_label(u: str | None) -> str:
    return UNIT_LABEL.get(u or "", u or "")


def _hdr(ws: Worksheet, row: int, headers: list[str], widths: list[int] | None = None) -> None:
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font, cell.fill, cell.border = WHITE_BOLD, HEAD_FILL, BOX
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if widths:
        for c, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(c)].width = w


def _num_format(decimals: int) -> str:
    return "#,##0" + ("." + "0" * decimals if decimals else "")


def _expr_to_excel(expr: str, cells: dict[str, str]) -> str:
    def sub(m):
        name = m.group(1)
        if name not in cells:
            raise KeyError(f"no cell for input '{name}'")
        return cells[name]
    return re.sub(r"\{(\w+)\}", sub, expr)


def build_workbook(meta: ExportMeta, items: list[ExportItem]) -> bytes:
    dec = int(meta.rules.get("decimals", 3))
    fmt = _num_format(dec)
    wb = Workbook()
    summary = wb.active
    summary.title = "Tổng hợp"
    boq = wb.create_sheet("BOQ")
    calc = wb.create_sheet("Tính chi tiết")
    trace = wb.create_sheet("Truy vết nguồn")

    # ---------------------------------------------------------------- calculation blocks
    calc.column_dimensions["A"].width = 34
    calc.column_dimensions["B"].width = 18
    calc.column_dimensions["C"].width = 14
    calc.column_dimensions["D"].width = 24
    calc.column_dimensions["E"].width = 40
    calc["A1"] = "TÍNH TOÁN CHI TIẾT – mỗi khối lượng là công thức Excel trên các ô tham số (có thể kiểm tra/sửa)"
    calc["A1"].font = Font(bold=True, size=12)
    r = 3
    result_cell: dict[str, str] = {}
    for it in items:
        calc.cell(row=r, column=1, value=f"STT {it.item_no} – {it.description}").font = Font(bold=True)
        calc.cell(row=r, column=1).fill = SUB_FILL
        for c in range(2, 6):
            calc.cell(row=r, column=c).fill = SUB_FILL
        r += 1
        _hdr(calc, r, ["Tham số", "Giá trị", "Đơn vị", "Nguồn gốc", "Ghi chú / mục nguồn"])
        r += 1
        cells: dict[str, str] = {}
        for name, value in it.calc_inputs.items():
            meta_i = it.input_meta.get(name, {})
            calc.cell(row=r, column=1, value=it.input_labels.get(name) or DERIVED_LABEL.get(name, name))
            calc.cell(row=r, column=2, value=float(value)).number_format = "General"
            unit = {"length": it.unit_system, "width": it.unit_system, "height": it.unit_system, "thickness": it.unit_system,
                    "diameter_mm": "mm", "area_m2": "m²", "unit_weight_kg_m": "kg/m", "steel_density": "kg/m³",
                    "quantity": unit_label(it.unit)}.get(name, "")
            calc.cell(row=r, column=3, value=unit or "")
            origin = meta_i.get("origin") or ("rule" if name in DERIVED_LABEL else "")
            calc.cell(row=r, column=4, value=ORIGIN_VI.get(origin, origin))
            calc.cell(row=r, column=5, value=meta_i.get("note") or (f"mục nguồn {meta_i['source_item_id']}" if meta_i.get("source_item_id") else ""))
            cells[name] = f"B{r}"
            r += 1
        calc.cell(row=r, column=1, value="Hệ số hao hụt")
        calc.cell(row=r, column=2, value=float(it.waste_factor))
        calc.cell(row=r, column=4, value=ORIGIN_VI["rule"])
        waste_cell = f"B{r}"
        r += 1
        calc.cell(row=r, column=1, value="Khối lượng chưa hao hụt").font = Font(italic=True)
        if it.quantity is not None and it.excel_expr:
            raw = _expr_to_excel(it.excel_expr, cells)
            calc.cell(row=r, column=2, value=f"={raw}").number_format = "0.000000"
            raw_cell = f"B{r}"
            r += 1
            calc.cell(row=r, column=1, value=f"KHỐI LƯỢNG ({unit_label(it.unit)}) – làm tròn {dec} số lẻ").font = Font(bold=True)
            res = calc.cell(row=r, column=2, value=f"=ROUND({raw_cell}*(1+{waste_cell}),{dec})")
            res.font, res.number_format, res.border = Font(bold=True), fmt, BOX
            calc.cell(row=r, column=3, value=unit_label(it.unit))
            calc.cell(row=r, column=5, value=it.formula_text)
            result_cell[it.item_id] = f"B{r}"
        else:
            calc.cell(row=r, column=2, value="Chưa tính được – thiếu dữ liệu")
            calc.cell(row=r, column=2).fill = WARN_FILL
        r += 2

    # ---------------------------------------------------------------- BOQ detail
    headers = ["STT", "Danh mục", "Mô tả công việc / cấu kiện", "Quy cách", "ĐVT", "Khối lượng", "Công thức / căn cứ tính",
               "Bản vẽ", "Trang", "Vùng trên trang (pt: x0, y0, x1, y1)", "Nguồn gốc dữ liệu", "Trạng thái rà soát", "Cảnh báo", "Ghi chú", "Mã hạng mục"]
    boq["A1"] = f"BẢNG KHỐI LƯỢNG CHI TIẾT – {meta.title} (phiên bản {meta.version_no})"
    boq["A1"].font = Font(bold=True, size=13)
    _hdr(boq, 3, headers, [6, 16, 44, 18, 7, 14, 50, 22, 6, 26, 18, 14, 36, 36, 38])
    first = 4
    for n, it in enumerate(items):
        row = first + n
        vals = [it.item_no, CATEGORY_VI.get(it.category, it.category), it.description, it.spec, unit_label(it.unit), None,
                it.formula_text, it.drawing_label, it.page_no,
                ", ".join(f"{v:.1f}" for v in it.bbox) if it.bbox else "", ORIGIN_VI.get(it.origin, it.origin),
                REVIEW_VI.get(it.review_status, it.review_status),
                "; ".join(f"[{f['severity']}] {f['message']}" for f in it.flags), it.notes, it.item_id]
        for c, v in enumerate(vals, start=1):
            cell = boq.cell(row=row, column=c, value=v)
            cell.border = BOX
            cell.alignment = Alignment(vertical="top", wrap_text=c in (3, 7, 13, 14))
        q = boq.cell(row=row, column=6)
        if it.item_id in result_cell:
            q.value = f"='Tính chi tiết'!{result_cell[it.item_id]}"
            q.number_format = fmt
        else:
            q.value, q.fill = "—", WARN_FILL
        if it.review_status != "accepted":
            for c in range(1, len(headers) + 1):
                boq.cell(row=row, column=c).font = Font(color="7A869A", italic=it.review_status == "pending",
                                                        strike=it.review_status == "rejected")
    last = first + max(len(items), 1) - 1
    boq.freeze_panes = "D4"
    boq.auto_filter.ref = f"A3:{get_column_letter(len(headers))}{last}"

    # ---------------------------------------------------------------- summary
    s = summary
    s.column_dimensions["A"].width = 28
    s.column_dimensions["B"].width = 10
    s.column_dimensions["C"].width = 20
    s.column_dimensions["D"].width = 16
    s.column_dimensions["E"].width = 18
    s["A1"] = meta.company or "PAACC Construction AI"
    s["A1"].font = Font(bold=True, size=12)
    s["A2"] = f"BẢNG TỔNG HỢP KHỐI LƯỢNG – {meta.title}"
    s["A2"].font = Font(bold=True, size=14)
    status = s.cell(row=3, column=1, value=f"Trạng thái: {STATUS_VI.get(meta.status, meta.status)}")
    status.font = Font(bold=True, size=12, color="1E7B45" if meta.status == "approved" else "C0392B")
    info = [("Dự án", meta.project or "—"), ("Phiên bản BOQ", meta.version_no), ("Trình duyệt", meta.submitted or "—"),
            ("Phê duyệt / quyết định", meta.decided or "—"), ("Ý kiến", meta.decision_note or "—"),
            ("Quy tắc đo bóc", f"làm tròn {dec} số lẻ; tỷ trọng thép {meta.rules.get('steel_density')} kg/m³; hao hụt: "
             + (", ".join(f"{CATEGORY_VI.get(k, k)} {v}" for k, v in (meta.rules.get('waste') or {}).items()) or "không")),
            ("Xuất bởi", f"{meta.exported_by} lúc {meta.exported_at}")]
    for i, (k, v) in enumerate(info, start=4):
        s.cell(row=i, column=1, value=k).font = Font(bold=True)
        s.cell(row=i, column=2, value=v)
    hr = 4 + len(info) + 1
    _hdr(s, hr, ["Danh mục", "ĐVT", "Khối lượng (đã chấp nhận)", "Số hạng mục chấp nhận", "Số hạng mục chờ rà soát"])
    groups = []
    for it in items:
        key = (CATEGORY_VI.get(it.category, it.category), unit_label(it.unit))
        if key not in groups and it.unit:
            groups.append(key)
    rng = lambda col: f"BOQ!${col}${first}:${col}${last}"
    for n, (cat, unit) in enumerate(groups, start=hr + 1):
        s.cell(row=n, column=1, value=cat).border = BOX
        s.cell(row=n, column=2, value=unit).border = BOX
        c = s.cell(row=n, column=3, value=f'=SUMIFS({rng("F")},{rng("B")},A{n},{rng("E")},B{n},{rng("L")},"{REVIEW_VI["accepted"]}")')
        c.number_format, c.border = fmt, BOX
        s.cell(row=n, column=4, value=f'=COUNTIFS({rng("B")},A{n},{rng("E")},B{n},{rng("L")},"{REVIEW_VI["accepted"]}")').border = BOX
        s.cell(row=n, column=5, value=f'=COUNTIFS({rng("B")},A{n},{rng("E")},B{n},{rng("L")},"{REVIEW_VI["pending"]}")').border = BOX
    note_row = hr + len(groups) + 2
    s.cell(row=note_row, column=1, value="Ghi chú: khối lượng tính bằng thuật toán xác định (Decimal) và công thức Excel trong sheet "
           "'Tính chi tiết'; không dùng AI để tính số liệu. Mỗi hạng mục có trang và vùng nguồn trong sheet 'BOQ' và 'Truy vết nguồn'.")
    s.cell(row=note_row, column=1).alignment = Alignment(wrap_text=True)
    s.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=5)
    s.row_dimensions[note_row].height = 45

    # ---------------------------------------------------------------- traceability
    t = trace
    t["A1"] = "BẢN VẼ NGUỒN (tệp gốc bất biến, nhận diện bằng SHA-256)"
    t["A1"].font = Font(bold=True)
    _hdr(t, 2, ["Bản vẽ", "Tên tệp", "Phiên bản tài liệu", "Số trang", "SHA-256", "Mã bản vẽ (hệ thống)"], [24, 30, 12, 9, 68, 38])
    for n, src in enumerate(meta.sources, start=3):
        for c, v in enumerate([src["label"], src["filename"], src["version_no"], src["pages"], src["sha256"], src["drawing_id"]], start=1):
            t.cell(row=n, column=c, value=v).border = BOX
    r0 = 3 + len(meta.sources) + 2
    t.cell(row=r0, column=1, value="TRUY VẾT TỪNG HẠNG MỤC").font = Font(bold=True)
    _hdr(t, r0 + 1, ["STT", "Bản vẽ", "Trang", "Vùng (pt)", "Văn bản nguồn trên bản vẽ", "Mã hạng mục"])
    for n, it in enumerate(items, start=r0 + 2):
        vals = [it.item_no, it.drawing_label, it.page_no, ", ".join(f"{v:.1f}" for v in it.bbox) if it.bbox else "", it.source_text, it.item_id]
        for c, v in enumerate(vals, start=1):
            t.cell(row=n, column=c, value=v).border = BOX

    for ws in (summary, boq, calc, trace):
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.oddFooter.center.text = f"{meta.title} v{meta.version_no} – {STATUS_VI.get(meta.status, meta.status)} – Trang &P/&N"
    boq.print_title_rows = "3:3"
    wb.properties.title = f"BOQ {meta.title} v{meta.version_no}"
    wb.properties.creator = "PAACC Construction AI"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
