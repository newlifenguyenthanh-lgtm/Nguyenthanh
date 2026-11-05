"""Synthetic vector sheets for Phase 5D (invented content, exact known geometry; NOT real drawings)."""
import pymupdf

from tests.geometry_helpers import _t

POST_R = 12.515  # 25.03 pt diameter = 8.83 mm on paper = 88.3 mm at 1:10


def _frame(p, title: str, number: str = "GT-01"):
    p.draw_rect(pymupdf.Rect(820, 700, 1160, 812), width=0.8)
    _t(p, (830, 720), f"BẢN VẼ SỐ: {number}", 9)
    _t(p, (830, 740), f"TÊN BẢN VẼ: {title}", 9)
    _t(p, (830, 760), "TỶ LỆ: 1:10", 9)


def post(p, x, y, label=True, r=POST_R):
    p.draw_circle((x, y), r, width=0.5)
    p.draw_line((x, y + r), (x, y + r + 80), width=0.5)  # stem (elevation line) touching the circle
    if label:
        _t(p, (x + r + 4, y + 3), "D88.3", 9)


def fence(p, n=10, x0=100.0, y=300.0, step=60.0, gaps=None, occlude=None, label="HÀNG RÀO B40", r=4.0):
    """occlude: None | "member" (opaque box drawn LATER over one post) | "gap" (one post missing under an opaque box)."""
    xs, x = [], x0
    for i in range(n):
        xs.append(x)
        x += (gaps[i] if gaps and i < len(gaps) else step)
    hidden = xs[n // 2]
    p.draw_line((xs[0] - 20, y), (xs[-1] + 20, y), width=0.6)
    for cx in xs:
        if occlude == "gap" and cx == hidden:
            continue
        p.draw_circle((cx, y), r, width=0.5)
    if label:
        _t(p, ((xs[0] + xs[-1]) / 2 - 30, y - 8), label, 9)
    if occlude:  # e.g. a legend / hatch box drawn over the row
        p.draw_rect(pymupdf.Rect(hidden - 12, y - 12, hidden + 12, y + 12), color=None, fill=(1, 1, 1), width=0)
    return xs


def page(doc, title, build, number="GT-01"):
    p = doc.new_page(width=1190, height=842)
    _frame(p, title, number)
    build(p)
    return p


def pdf(*pages) -> bytes:
    doc = pymupdf.open()
    for title, build, number in pages:
        page(doc, title, build, number)
    return doc.tobytes()


def sheet_post() -> bytes:
    return pdf(("MẶT BẰNG BỐ TRÍ TRỤ", lambda p: post(p, 500, 200), "GT-01"))


def sheet_bolt(in_note=False) -> bytes:
    def b(p):
        if in_note:
            _t(p, (100, 500), "GHI CHÚ: liên kết dùng bu lông M16x35 mạ kẽm", 9)
        else:
            _t(p, (300, 300), "M16x35", 9)
    return pdf(("CHI TIẾT LIÊN KẾT", b, "KC-02"))


def sheet_fence(**kw) -> bytes:
    return pdf(("MẶT BẰNG BỐ TRÍ HÀNG RÀO", lambda p: fence(p, **kw), "GT-03"))


def sheet_plan_detail() -> bytes:
    """Page 1 plan: one steel post with D88.3 + callout "CHI TIẾT A". Page 2: the SAME post drawn in detail."""
    def plan(p):
        post(p, 500, 200)
        _t(p, (470, 160), "CHI TIẾT A", 8)

    def detail(p):
        post(p, 400, 300)
    return pdf(("MẶT BẰNG BỐ TRÍ TRỤ", plan, "GT-04"), ("CHI TIẾT A", detail, "GT-05"))
