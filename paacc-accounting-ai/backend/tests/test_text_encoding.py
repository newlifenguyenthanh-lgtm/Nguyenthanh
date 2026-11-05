"""Phase 5A.1: legacy Vietnamese encoding detection (detection only - text is never modified).
Strings below reproduce patterns found in the supplied real workbook (generic words, no confidential data)."""
import pytest

from app.text.encoding import detect
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr


@pytest.mark.parametrize("text,enc", [
    ("VÞ trÝ cöa ra - vµo (Lµm míi)", "tcvn3"),   # = "Vị trí cửa ra - vào (Làm mới)"
    ("ChiÒu dµi (m)", "tcvn3"),                    # = "Chiều dài (m)"
    ("Khèi l­îng", "tcvn3"),                   # = "Khối lượng"
    ("Bª t«ng cèt thÐp", "tcvn3"),                 # = "Bê tông cốt thép"
    ("Vieät Nam", "vni"), ("ñöôøng giao thoâng", "vni"),
    ("Vá»‹ trÃ­ cá»­a", "utf8_mojibake"),           # UTF-8 bytes read as Latin-1
])
def test_legacy_encodings_detected(text, enc):
    g = detect(text)
    assert g.encoding == enc and g.suspicious and g.evidence and 0.5 <= g.confidence <= 0.99


@pytest.mark.parametrize("text", ["Vị trí cửa ra - vào (Làm mới)", "Thép hình", "Bê tông C30", "cái", "Màng PQ 4000",
                                  "Bu lông D20x180mm", "Hàng rào B40", "± 0.000", "L = 25.5m", ""])
def test_unicode_and_ascii_are_not_flagged(text):
    assert not detect(text).suspicious


def test_known_limitation_tcvn3_using_only_valid_looking_letters():
    # Real false negative (1 of 9 TCVN3 strings in the supplied workbook): "Ghi chó" is TCVN3 for "Ghi chú",
    # but every character is valid Unicode Vietnamese and "chó" is a real word -> undecidable without context.
    assert detect("Ghi chó").encoding == "unicode"


def test_drawing_text_items_carry_encoding_flag_and_page_warning(env, monkeypatch):
    import pymupdf
    from tests import pdf_factory as pf
    use_ocr(monkeypatch, FakeOcr())
    a = login(env, "admin@a.test", "pw-admin-1")
    doc = pymupdf.open()
    p = doc.new_page()
    kw = {"fontname": "vn", "fontfile": pf.FONT} if pf.FONT else {}
    p.insert_text((72, 100), "ChiÒu dµi tuyÕn", fontsize=11, **kw)
    p.insert_text((72, 130), "Chiều dài tuyến", fontsize=11, **kw)
    d = process(env, a, upload(env, a, doc.tobytes())["id"]).json()
    items = {i["text"]: i for i in env.get(f"{B}/drawings/{d['id']}/items?kind=text", headers=a).json()}
    legacy = items["ChiÒu dµi tuyÕn"]
    assert legacy["data"]["encoding"]["encoding"] == "tcvn3" and legacy["text"] == "ChiÒu dµi tuyÕn"  # original kept
    assert "encoding" not in items["Chiều dài tuyến"]["data"]
    page = env.get(f"{B}/drawings/{d['id']}", headers=a).json()["pages"][0]
    assert "legacy_encoding_suspected:tcvn3:1" in page["warnings"]
