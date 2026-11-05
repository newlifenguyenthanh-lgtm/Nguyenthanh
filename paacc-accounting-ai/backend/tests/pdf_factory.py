"""Synthetic construction-drawing PDFs for tests. All content is invented test data, not real drawings."""
from pathlib import Path

import pymupdf

FONT_CANDIDATES = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf",
                   "/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
FONT = next((f for f in FONT_CANDIDATES if Path(f).exists()), None)
VIETNAMESE = FONT is not None


def _text(page, xy, s, size=10, rotate=0):
    kw = {"fontsize": size, "rotate": rotate}
    if FONT:
        kw.update(fontname="vn", fontfile=FONT)
    page.insert_text(xy, s if VIETNAMESE else _ascii(s), **kw)


def _ascii(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D")) if unicodedata.category(c) != "Mn")


SHEET_LINES = [
    "DẦM D1 300x600 L=6000 SL=4 - BÊ TÔNG B25",
    "THÉP HỘP 50x50x2 L=6000 SL=10",
    "BẢN MÃ PL10 200x300 SL=8",
    "CỐT THÉP Ø16a200 L=3500 SL=24 CB400-V",
]


def drawing_sheet(doc, *, number="KC-01", title="MẶT BẰNG KẾT CẤU DẦM TẦNG 1", rev="A", scale="1:100",
                  units="mm", lines=SHEET_LINES, table=True, rotation=0):
    """A3 landscape structural sheet: annotations, a ruled material schedule and a title block."""
    page = doc.new_page(width=1190, height=842)
    page.draw_rect(pymupdf.Rect(20, 20, 1170, 822), width=1.2)
    for x in range(100, 700, 100):  # some vector geometry (grid lines)
        page.draw_line((x, 80), (x, 500), width=0.3)
    y = 120
    for s in lines:
        _text(page, (720, y), s); y += 22
    _text(page, (300, 560), "6000", 9)  # bare CAD dimension (no unit)
    _text(page, (90, 300), "3500", 9, rotate=90)  # vertical dimension text
    if table:
        x0, y0, cw, rh = 60, 600, [40, 220, 120, 60, 80], 20
        header = ["STT", "TÊN CẤU KIỆN", "QUY CÁCH", "ĐVT", "KHỐI LƯỢNG"]
        rows = [header, ["1", "Dầm D1", "300x600", "m3", "4,32"], ["2", "Thép hộp", "50x50x2", "kg", "180,86"]]
        width = sum(cw)
        for i in range(len(rows) + 1):
            page.draw_line((x0, y0 + i * rh), (x0 + width, y0 + i * rh), width=0.6)
        xs = [x0]
        for w in cw:
            xs.append(xs[-1] + w)
        for x in xs:
            page.draw_line((x, y0), (x, y0 + len(rows) * rh), width=0.6)
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                _text(page, (xs[c] + 3, y0 + r * rh + 14), cell, 8)
    tb = [f"CÔNG TRÌNH: NHÀ XƯỞNG MẪU", f"TÊN BẢN VẼ: {title}", f"BẢN VẼ SỐ: {number}", f"LẦN SỬA: {rev}",
          f"TỶ LỆ: {scale}" if scale else "", f"ĐƠN VỊ KÍCH THƯỚC: {units}" if units else ""]
    page.draw_rect(pymupdf.Rect(820, 660, 1160, 812), width=0.8)
    yy = 680
    for s in tb:
        if s:
            _text(page, (830, yy), s, 9); yy += 21
    if rotation:
        page.set_rotation(rotation)
    return page


def vector_pdf(**kw) -> bytes:
    doc = pymupdf.open()
    drawing_sheet(doc, **kw)
    return doc.tobytes()


def scanned_pdf(dpi=200, **kw) -> bytes:
    """Rasterise a vector sheet and embed it as an image-only page (no text layer) - simulates a scan."""
    src = pymupdf.open(stream=vector_pdf(table=False, **kw), filetype="pdf")
    pix = src[0].get_pixmap(dpi=dpi)
    out = pymupdf.open()
    page = out.new_page(width=src[0].rect.width, height=src[0].rect.height)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    return out.tobytes()


def mixed_doc(**kw) -> bytes:
    """Page 1 vector, page 2 scanned."""
    out = pymupdf.open(stream=vector_pdf(**kw), filetype="pdf")
    out.insert_pdf(pymupdf.open(stream=scanned_pdf(number="KC-02", title="MẶT CẮT DẦM"), filetype="pdf"))
    return out.tobytes()


def encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    _text(doc.new_page(), (72, 72), "secret")
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")


# Rows of a synthetic supplier quotation reproducing the STRUCTURE of the real document validated in Phase 4.1
# (text above the table, two-row header, roman/numbered groups, priced assembly with components, a group that
# continues on the next page, a total row). Invented items and quantities - no real data.
QUOTE_HEADER = ["STT", "Chủng loại, quy cách", "ĐVT", "Số lượng", "Đơn giá (VNĐ)", "Thành tiền (VNĐ)", "Ghi chú"]
QUOTE_PAGE1 = [
    ["", "", "", "", "Cung cấp vật tư", "", ""],
    ["I", "An toàn giao thông", "", "", "", "", ""],
    ["1", "Biển báo", "", "", "", "", ""],
    ["", "Biển tròn D1.2m", "cái", "3,00", "1.000", "3.000", ""],
    ["", "Biển CN W.203c (bxh = 1.2x0.9m)", "cái", "1,00", "2.000", "2.000", ""],
    ["2", "Giá treo biển", "", "", "", "", ""],
    ["", "Cột biển báo loại 1.3, cột D88.3, dày 2.9mm, L=6.100mm", "cột", "2,00", "1.000", "2.000", ""],
    ["3", "Tôn lượn sóng", "", "", "", "", ""],
    ["3.1", "Tôn sóng làm mới loại B-1", "m", "1.204,00", "1.000", "1.204.000", ""],
    ["", "Cột thép D140x4.5x2500", "cái", "600,00", "", "-", ""],
    ["", "Bu lông D20x180mm", "cái", "1.200,00", "", "-", ""],
    ["3.2", "Tôn sóng cải tạo", "", "", "", "", ""],
    ["", "Bu lông D20x180mm", "cái", "320,00", "1.000", "320.000", ""],
]
QUOTE_PAGE2 = [
    ["", "", "", "", "Cung cấp vật tư", "", ""],
    ["", "Bu lông D16x30mm", "cái", "3.840,00", "1.000", "3.840.000", ""],
    ["4", "Hàng rào B40", "", "", "", "", ""],
    ["4.1", "Loại 1.3 (Làm mới)", "bộ", "10,00", "1.000", "10.000", ""],
    ["", "Cột thân trên D75x3,25 L=1,89mm", "cột", "10,00", "", "-", ""],
    ["", "Bulong M16x35", "bộ", "40,00", "", "-", ""],
    ["5", "Đinh phản quang- 3M", "cái", "25,00", "1.000", "25.000", ""],
    ["6", "Hạng mục chưa có khối lượng", "", "", "", "", ""],
    ["", "Cộng sau thuế:", "", "", "", "1.364.000", ""],
]


def _ruled_table(page, x0, y0, widths, rows, rh=18, size=7):
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    for i in range(len(rows) + 1):
        page.draw_line((x0, y0 + i * rh), (xs[-1], y0 + i * rh), width=0.5)
    for x in xs:
        page.draw_line((x, y0), (x, y0 + len(rows) * rh), width=0.5)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell:
                _text(page, (xs[c] + 2, y0 + r * rh + 12), cell, size)


def quotation_pdf() -> bytes:
    doc = pymupdf.open()
    widths = [30, 260, 35, 55, 60, 70, 40]
    p1 = doc.new_page(width=612, height=792)
    _text(p1, (420, 60), "Hà Nội, ngày 01 tháng 01 năm 2026", 8)
    _text(p1, (260, 90), "BÁO GIÁ", 14)
    _text(p1, (40, 115), "Kính gửi: CÔNG TY MẪU", 9)
    _text(p1, (40, 130), "Hạng mục: An toàn giao thông", 9)
    _ruled_table(p1, 40, 150, widths, [QUOTE_HEADER] + QUOTE_PAGE1)
    _text(p1, (300, 770), "1/2", 8)
    p2 = doc.new_page(width=612, height=792)
    _ruled_table(p2, 40, 50, widths, [QUOTE_HEADER] + QUOTE_PAGE2)
    _text(p2, (40, 300), "B. Điều kiện báo giá: đơn giá đã bao gồm VAT 10%.", 8)
    _text(p2, (300, 770), "2/2", 8)
    return doc.tobytes()
