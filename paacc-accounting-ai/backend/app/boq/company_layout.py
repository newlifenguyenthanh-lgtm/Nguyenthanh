"""Company quantity-BOQ layout ('Tong hop' sheet of the company's takeoff workbook), reproduced from a layout
specification - NOT by copying the company file (which holds other projects' data, external links, WMF images and
data-validation extensions that openpyxl would silently drop). See docs/BOQ_TEMPLATE_MAPPING.md.
"""
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

LAYOUT_KEY = "company_kl"
SHEET = "Tong hop"
FONT = "Times New Roman"
# column, header, width (taken from the template)
COLUMNS = [("A", "STT", 24.1), ("B", "HẠNG MỤC", 52.7), ("C", "ĐƠN VỊ", 12.2), ("D", "TỔNG KHỐI LƯỢNG", 25.6), ("E", "GHI CHÚ", 27.2)]
TRACE_COLUMN = ("F", "NGUỒN / TRUY VẾT (PAACC)", 40.0)  # extension: not in the company template, outside its print area
NUMBER_FORMAT = '_-* #,##0.00_-;\\-* #,##0.00_-;_-* \\-??_-;_-@_-'  # template's accounting format, column D
HEADER_FILL = PatternFill("solid", fgColor="FFC0C0C0")
GROUP_FILL = PatternFill("solid", fgColor="FFFFFF00")  # level-1 groups (1, 2, 3 ...) are yellow in the template
THIN = Side(style="thin")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STATUS_NOTE = {"pending": "Chờ rà soát", "rejected": "Loại bỏ"}


def _level(code: str) -> int:
    c = code.strip().rstrip(".")
    return 0 if c and all(ch in "IVXLC" for ch in c) else c.count(".") + 1


def _style(ws: Worksheet, row: int, *, bold=False, italic=False, fill=None, indent=0):
    for col, _, _ in COLUMNS:
        cell = ws[f"{col}{row}"]
        cell.font = Font(name=FONT, size=12, bold=bold, italic=italic)
        cell.border = BOX
        cell.alignment = Alignment(horizontal="center" if col in "ACD" else "left", vertical="center", wrap_text=col in "BE",
                                   indent=indent if col == "B" else 0)
        if fill:
            cell.fill = fill
    ws[f"D{row}"].number_format = NUMBER_FORMAT


def build_sheet(ws: Worksheet, title: str, version_no: int, status_label: str, items, result_cell: dict[str, str],
                calc_sheet: str, category_vi: dict[str, str]) -> None:
    """items: ExportItem list in BOQ order. Quantity cells are live references to the calculation sheet."""
    ws["A1"] = f"BẢNG TỔNG HỢP KHỐI LƯỢNG – {title} (phiên bản {version_no}) – {status_label}"
    ws["A1"].font = Font(name=FONT, size=13, bold=True)
    for col, header, width in COLUMNS:
        ws.column_dimensions[col].width = width
        ws.merge_cells(f"{col}2:{col}3")
        c = ws[f"{col}2"]
        c.value, c.font, c.fill, c.border = header, Font(name=FONT, size=12, bold=True), HEADER_FILL, BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws[f"{col}3"].border = BOX
    col, header, width = TRACE_COLUMN
    ws.column_dimensions[col].width = width
    ws[f"{col}2"] = header
    ws[f"{col}2"].font = Font(name=FONT, size=10, bold=True, color="7A869A")
    row = 4
    emitted: set[tuple] = set()
    synth = 0
    for it in items:
        if it.review_status == "rejected":
            continue
        path = list(it.group_path or [])
        if not path:  # annotation-derived item: group under a synthesised category heading
            cat = category_vi.get(it.category, it.category)
            key = ("cat", cat)
            if key not in emitted:
                synth += 1
                emitted.add(key)
                ws[f"A{row}"], ws[f"B{row}"] = str(synth), cat
                _style(ws, row, bold=True, fill=GROUP_FILL)
                row += 1
        own = path[-1] if path and it.is_coded_row else None
        for n, g in enumerate(path[:-1] if own else path):
            key = tuple(x["code"] for x in path[:n + 1])
            if key in emitted:
                continue
            emitted.add(key)
            lvl = _level(g["code"])
            ws[f"A{row}"], ws[f"B{row}"] = g["code"], g["title"]
            _style(ws, row, bold=True, fill=GROUP_FILL if lvl == 1 else None)
            row += 1
        if own:
            emitted.add(tuple(x["code"] for x in path))
        ws[f"A{row}"] = own["code"] if own else None
        ws[f"B{row}"] = it.description
        ws[f"C{row}"] = it.unit or ""
        if it.item_id in result_cell:
            ws[f"D{row}"] = f"='{calc_sheet}'!{result_cell[it.item_id]}"
        else:
            ws[f"D{row}"] = None
        note = (it.notes or "").splitlines()[-1].split("] ", 1)[-1] if it.notes else ""
        ws[f"E{row}"] = "; ".join(x for x in (STATUS_NOTE.get(it.review_status, ""), note) if x) or None
        ws[f"F{row}"] = f"{it.drawing_label} tr.{it.page_no} | {it.item_id}" if it.page_no else it.item_id
        ws[f"F{row}"].font = Font(name=FONT, size=9, color="7A869A")
        component = any(f.get("code") == "component_of_parent" for f in it.flags)
        _style(ws, row, bold=bool(own), italic=component, indent=1 if component else 0)
        row += 1
    ws.print_area = f"A1:E{max(row - 1, 3)}"
    ws.print_title_rows = "1:3"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.freeze_panes = "A4"
