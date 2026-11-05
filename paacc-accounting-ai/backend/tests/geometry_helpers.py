"""Synthetic vector sheet with exactly known geometry for Phase 5B/5C tests (invented content, no real data)."""
import pymupdf

from tests import pdf_factory as pf


def _t(page, xy, s, size=10, rotate=0):
    kw = {"fontsize": size, "rotate": rotate}
    if pf.FONT:
        kw.update(fontname="vn", fontfile=pf.FONT)
    page.insert_text(xy, s, **kw)


def sheet(table=True, detail=True, extra=None) -> bytes:
    """A 1190x842 pt sheet:
    - G_LONG: horizontal line (100,200)-(820,200) = 720 pt  -> 25.400 m at 1:100; label "L=25.40m" above it
    - G_SHORT: horizontal line (100,300)-(460,300) = 360 pt -> 12.700 m; text "L=13.50m" above (conflict 0.80 m)
    - G_VERT: vertical line (950,150)-(950,510) = 360 pt; rotated text "L=12.70m" beside it
    - two parallel lines close together with one "L=5.00m" between them (ambiguous)
    - chainage ticks "Km12+350" / "Km12+600" at both ends of a polyline (250 pt route)
    - ruled table bottom-left with numbers; title block bottom-right; detail callout "CHI TIẾT A" + circle
    """
    doc = pymupdf.open()
    p = doc.new_page(width=1190, height=842)
    p.draw_line((100, 200), (820, 200), width=0.5)
    _t(p, (400, 194), "L=25.40m", 9)
    p.draw_line((100, 300), (460, 300), width=0.5)
    _t(p, (240, 294), "L=13.50m", 9)
    p.draw_line((950, 150), (950, 510), width=0.5)
    _t(p, (944, 360), "L=12.70m", 9, rotate=90)
    p.draw_line((100, 400), (300, 400), width=0.5)
    p.draw_line((100, 412), (300, 412), width=0.5)
    _t(p, (180, 409), "L=5.00m", 7)
    p.draw_polyline([(500, 400), (650, 400), (750, 400)], width=0.8)
    _t(p, (490, 392), "Km12+350", 8)
    _t(p, (735, 392), "Km12+600", 8)
    _t(p, (560, 420), "HỘ LAN TÔN LƯỢN SÓNG", 8)
    if detail:
        p.draw_circle((1000, 620), 14)
        _t(p, (1020, 624), "CHI TIẾT A", 8)
        _t(p, (300, 560), "Xem chi tiết A-A", 8)
    if table:
        x0, y0 = 60, 600
        for i in range(4):
            p.draw_line((x0, y0 + i * 20), (x0 + 300, y0 + i * 20), width=0.5)
        for x in (60, 100, 260, 360):
            p.draw_line((x, y0), (x, y0 + 60), width=0.5)
        for r, row in enumerate([["STT", "Hạng mục", "Chiều dài"], ["1", "Hộ lan", "125.5"], ["2", "Hàng rào", "25.40"]]):
            for c, (cell, x) in enumerate(zip(row, (63, 103, 263))):
                _t(p, (x, y0 + r * 20 + 14), cell, 8)
    p.draw_rect(pymupdf.Rect(820, 700, 1160, 812), width=0.8)
    for n, s in enumerate(["BẢN VẼ SỐ: GT-01", "TỶ LỆ: 1:100", "LẦN SỬA: A"]):
        _t(p, (830, 720 + n * 20), s, 9)
    _t(p, (590, 830), "1/1", 8)
    if extra:
        extra(p)
    return doc.tobytes()
