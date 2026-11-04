from decimal import Decimal as D

import pytest

from app.pdf.analysis import (Line, classify, classify_table, duplicate_findings, find_dimensions, find_specs,
                              find_symbols, fold, notes_regions, parse_number, revision_rank, scale_status,
                              title_block, units_status)


def L(text, id="t1", bbox=(0, 0, 100, 10), page=1, source="text", conf=None):
    return Line(id, page, text, bbox, source, conf)


def dims(text, **kw):
    return [f.data | {"flags": f.flags, "conf": f.confidence, "raw": f.raw} for f in find_dimensions(L(text, **kw)) if f.kind == "dimension"]


def test_fold_preserves_length_and_strips_accents():
    for s in ["BẢN VẼ SỐ", "Đơn vị: mm", "Thép hộp 50×50×2", "Ø16a200", "m²"]:
        assert len(fold(s)) == len(s)
    assert fold("Đơn vị kích thước") == "DON VI KICH THUOC" and fold("φ16") == "Ø16"


@pytest.mark.parametrize("raw,value,amb", [
    ("6000", D("6000"), False), ("4,32", D("4.32"), False), ("12.5", D("12.5"), False),
    ("6,000", None, True), ("6.000", None, True), ("0,500", D("0.500"), False),
    ("1.250.000", D("1250000"), False), ("1.250,5", D("1250.5"), False), ("1,250.5", D("1250.5"), False),
    ("1.25.0", None, True),
])
def test_parse_number(raw, value, amb):
    assert parse_number(raw) == (value, amb)


def test_section_dimensions_with_and_without_unit():
    d = dims("DẦM D1 300x600 L=6000 SL=4")
    sec = next(x for x in d if x["type"] == "section")
    assert sec["values"] == ["300", "600"] and sec["unit"] is None and "unit_not_stated" in sec["flags"]
    lab = next(x for x in d if x["type"] == "labeled")
    assert lab["label"] == "L" and lab["values"] == ["6000"]
    with_unit = dims("Tiết diện 300 x 600 mm")[0]
    assert with_unit["unit"] == "mm" and with_unit["unit_explicit"] and with_unit["conf"] == 0.95
    box = dims("THÉP HỘP 50×50×2")[0]
    assert box["values"] == ["50", "50", "2"]


def test_count_bar_value_and_stated_quantity():
    f = find_dimensions(L("CỐT THÉP Ø16a200 L=3500 SL=24"))
    kinds = {(x.kind, x.data.get("type")) for x in f}
    assert ("count", "count") in kinds and ("dimension", "bar") in kinds
    bar = next(x for x in f if x.data.get("type") == "bar")
    assert bar.data["diameter"] == "16" and bar.data["spacing"] == "200" and bar.data["unit"] is None
    assert next(x for x in f if x.kind == "count").data["count"] == "24"
    assert dims("Cao độ sàn 3,5m")[0]["values"] == ["3.5"]
    sq = dims("Bê tông lót 12,5 m3")[0]
    assert sq["type"] == "stated_quantity" and sq["unit"] == "m3" and sq["values"] == ["12.5"]


def test_ambiguous_and_bare_numbers_are_flagged_not_guessed():
    a = dims("L=6,000")[0]
    assert a["values"] == [None] and "ambiguous_number" in a["flags"] and a["conf"] == 0.3
    bare = dims("6000")[0]
    assert bare["type"] == "bare_number" and bare["unit"] is None and bare["conf"] == 0.5
    assert dims("TẦNG 1") == [] and dims("KC-01") == [] and dims("1:100") == [] and dims("04/11/2026") == []


def test_ocr_confidence_reduces_finding_confidence():
    d = dims("300x600 mm", source="ocr", conf=0.5)[0]
    assert d["conf"] == 0.475


def test_specs():
    cats = lambda t: {(f.data["category"], f.data["value"]) for f in find_specs(L(t))}
    assert ("concrete_grade", "B25") in cats("BÊ TÔNG B25")
    assert not any(c == "concrete_grade" for c, _ in cats("DẦM B25"))  # needs a concrete cue
    assert ("concrete_grade", "C25/30") in cats("Concrete C25/30")
    assert ("rebar_grade", "CB400-V") in cats("CỐT THÉP CB400-V")
    assert ("steel_grade", "SS400") in cats("THÉP SS400")
    assert ("steel_box", "HOP50X50X2") in {(c, v.replace("THEP", "")) for c, v in cats("THÉP HỘP 50x50x2")}
    plate = next(f for f in find_specs(L("BẢN MÃ PL10 200x300")) if f.data.get("thickness"))
    assert plate.data["thickness"] == "10" and plate.data["unit"] is None
    assert ("steel_profile", "I200") in cats("Dầm thép I200")
    assert ("steel_profile", "L50X50X5") in cats("Thép góc L50x50x5")
    assert not any(c == "steel_profile" for c, _ in cats("L=6000"))


def test_symbols_and_references():
    s = find_symbols(L("Cao độ +3.600 ; i=2%; MẶT CẮT A-A; xem bản vẽ KC-05"))
    types = {f.data.get("type") or f.kind for f in s}
    assert {"elevation", "slope", "section_marker", "reference"} <= types
    assert next(f for f in s if f.kind == "reference").data["ref"] == "KC-05"
    assert next(f for f in s if f.data.get("type") == "elevation").data["value"] == "3.600"
    assert find_symbols(L("CHI TIẾT 3/KC-04"))[-1].data["ref"] == "KC-04"


def tb_lines():
    return [L("CÔNG TRÌNH: NHÀ XƯỞNG MẪU", "a", (830, 670, 1000, 682)),
            L("TÊN BẢN VẼ: MẶT BẰNG KẾT CẤU DẦM TẦNG 1", "b", (830, 691, 1100, 703)),
            L("BẢN VẼ SỐ: KC-01", "c", (830, 712, 950, 724)),
            L("LẦN SỬA: A", "d", (830, 733, 900, 745)),
            L("TỶ LỆ: 1:100", "e", (830, 754, 920, 766)),
            L("ĐƠN VỊ KÍCH THƯỚC: mm", "f", (830, 775, 990, 787)),
            L("CHI TIẾT A - TL 1:20", "g", (100, 100, 200, 110))]


def test_title_block_fields_scale_and_units():
    r = title_block(tb_lines())
    f = r["fields"]
    assert f["drawing_number"]["value"] == "KC-01" and f["drawing_number"]["item_ids"] == ["c"]
    assert f["title"]["value"] == "MẶT BẰNG KẾT CẤU DẦM TẦNG 1"
    assert f["revision"]["value"] == "A" and f["project"]["value"] == "NHÀ XƯỞNG MẪU"
    assert {(c["ratio"], c["labeled"]) for c in r["scale_candidates"]} == {(100, True), (20, True)}
    assert [c["unit"] for c in r["unit_candidates"]] == ["mm"]
    assert units_status(r["unit_candidates"]) == "unverified"
    assert scale_status(r["scale_candidates"], r["nts_item_ids"]) == "conflicting"  # 1:100 sheet + 1:20 detail
    single = title_block(tb_lines()[:6])
    assert scale_status(single["scale_candidates"], []) == "unverified"


def test_label_value_on_next_line_and_missing_values():
    r = title_block([L("SỐ BẢN VẼ", "a", (830, 700, 900, 712)), L("GT-12", "b", (830, 716, 880, 728))])
    assert r["fields"]["drawing_number"]["value"] == "GT-12" and r["fields"]["drawing_number"]["item_ids"] == ["a", "b"]
    empty = title_block([L("Ghi chú chung", "x")])
    assert empty["fields"] == {} and scale_status(empty["scale_candidates"], []) == "not_detected"
    assert units_status([]) == "not_detected"
    nts = title_block([L("TỶ LỆ: N.T.S", "a")])
    assert nts["scale_candidates"] == [] and scale_status([], nts["nts_item_ids"]) == "nts_declared"


def test_classification():
    c = classify("MẶT BẰNG KẾT CẤU DẦM TẦNG 1", "KC-01", "", True)
    assert [d["value"] for d in c["disciplines"]] == ["structural"]
    assert {v["value"] for v in c["view_types"]} == {"plan", "schedule"}
    road = classify("MẶT CẮT NGANG ĐIỂN HÌNH", "GT-03", "BIỂN BÁO W.203c", False)
    assert road["disciplines"][0] == {"value": "traffic", "basis": "number_prefix", "confidence": 0.6}
    assert {v["value"] for v in road["view_types"]} >= {"section", "profile"}
    guess = classify(None, None, "Hệ thống thoát nước mưa", False)
    assert guess["disciplines"][0]["basis"] == "page_text" and guess["disciplines"][0]["confidence"] == 0.4
    assert classify(None, None, "", False) == {"disciplines": [], "view_types": []}


def test_table_classification():
    t = classify_table([["STT", "TÊN CẤU KIỆN", "QUY CÁCH", "ĐVT", "KHỐI LƯỢNG"], ["1", "Dầm", "300x600", "m3", "4,32"]])
    assert t == {"header_map": {"0": "stt", "1": "description", "2": "spec", "3": "unit", "4": "quantity"}, "table_type": "material_schedule"}
    assert classify_table([["A", "B"], ["1", "2"]])["table_type"] == "unknown"


def test_notes_region():
    ls = [L("GHI CHÚ:", "n", (50, 400, 120, 410)), L("1. Bê tông B25", "n1", (50, 414, 200, 424)),
          L("2. Thép CB400-V", "n2", (50, 428, 200, 438)), L("far away", "z", (50, 700, 100, 710))]
    r = notes_regions(ls)
    assert r[0]["item_ids"] == ["n", "n1", "n2"] and r[0]["bbox"] == [50, 400, 200, 438]


def test_duplicate_detection():
    a = L("300x600", "a", (10, 10, 60, 20)); b = L("300x600", "b", (10.5, 10, 60.5, 20)); c = L("300x600", "c", (400, 10, 450, 20))
    ds = [f for ln in (a, b, c) for f in find_dimensions(ln)]
    f = duplicate_findings([a, b, c], ds)
    over = [x for x in f if x["type"] == "overlapping_duplicate_text"]
    assert over and over[0]["item_ids"] == ["a", "b"]
    rep = next(x for x in f if x["type"] == "repeated_annotation")
    assert len(rep["occurrences"]) == 3
    p1 = [L(f"line {i}", f"p1{i}", page=1) for i in range(6)]
    p2 = [L(f"line {i}", f"p2{i}", page=2) for i in range(6)]
    assert any(x["type"] == "duplicate_page" and x["pages"] == [1, 2] for x in duplicate_findings(p1 + p2, []))


def test_revision_rank():
    assert revision_rank("B") > revision_rank("A") and revision_rank("2") > revision_rank("1")
    assert revision_rank("") is None and revision_rank("??") is None
