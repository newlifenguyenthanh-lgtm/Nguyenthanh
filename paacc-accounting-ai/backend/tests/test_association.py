"""Phase 5C: text classification/normalisation, association engine, conflicts, chainage, review, provenance.

All drawings here are SYNTHETIC (tests/geometry_helpers.sheet, invented content). Passing these tests says nothing about
accuracy on real construction drawings - see docs/PHASE5C_TEXT_GEOMETRY_ASSOCIATION.md §Validation.
"""
import ast
import pathlib
from decimal import Decimal as D

import pytest

from app.association import engine as E
from app.association.classify import classify, normalize
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr
from tests.geometry_helpers import sheet


# ------------------------------------------------------------------ 1-4 normalisation & classification (pure)
@pytest.mark.parametrize("text,ttype,value_m,comma", [
    ("L=125.50m", "LENGTH", "125.50", False),
    ("L = 125,50m", "LENGTH", "125.50", True),
    ("125,50m", "LENGTH", "125.50", True),
    ("12550 mm", "LENGTH", "12.550", False),
    ("L=(4700+5200)mm", "LENGTH", "9.900", False),
])
def test_length_normalisation(text, ttype, value_m, comma):
    c = classify(text)
    assert c.original_text == text and c.text_type == ttype
    assert c.values["length"]["value_m"] == value_m and c.values["length"]["decimal_comma"] is comma


@pytest.mark.parametrize("text,meters", [("Km12+350", ["12350"]), ("0+250", ["250"]), ("K0+250 - K0+500", ["250", "500"])])
def test_chainage_parsing(text, meters):
    c = classify(text)
    assert c.text_type == "CHAINAGE" and [x["meters"] for x in c.values["chainage"]] == meters


def test_dimension_spec_and_normalised_forms():
    assert normalize("M16×35") == "M16x35" and normalize("L  =  5m") == "L=5m"
    assert classify("D88.3").text_type == "DIMENSION" and classify("M16x35").values["dimensions"][0]["type"] == "bolt"
    assert classify("Bê tông M300").text_type == "MATERIAL"
    assert classify("Thép hộp 50x50x2").text_type == "SPECIFICATION"
    assert classify("S=12.5m2").text_type == "AREA"


def test_3m_is_never_metres_by_default():
    c = classify("3M")
    assert c.text_type == "OTHER" and "length" not in c.values and "brand_or_notation_possible" in c.flags
    amb = classify("CAO 3M")  # uppercase M inside a sentence: maybe metres, maybe not -> ambiguous, never auto
    assert amb.values["length"]["ambiguous"] and "unit_case_ambiguous" in amb.flags


@pytest.mark.parametrize("text,ttype", [
    ("BẢN VẼ SỐ: GT-01", "TITLE"), ("TỶ LỆ: 1:100", "SCALE"), ("LẦN SỬA: A", "REVISION"), ("GHI CHÚ: thi công theo TCVN", "NOTE"),
    ("CHI TIẾT A", "DETAIL_REFERENCE"), ("MẶT CẮT A-A", "DETAIL_REFERENCE"), ("HỘ LAN TÔN LƯỢN SÓNG", "LABEL"), ("125.5", "OTHER"),
])
def test_rule_based_text_types(text, ttype):
    assert classify(text).text_type == ttype


def test_table_and_page_number_classification():
    assert classify("25.40", in_table=True).text_type == "TABLE"
    c = classify("1/1")
    assert c.text_type == "OTHER" and "page_number" in c.flags


def test_tcvn3_text_is_flagged_never_converted():
    c = classify("ChiÒu dµi tuyÕn")
    assert c.original_text == "ChiÒu dµi tuyÕn" and c.normalized_text == "ChiÒu dµi tuyÕn"  # no conversion
    assert c.text_type == "UNKNOWN" and "ENCODING_UNKNOWN" in c.flags and c.encoding
    assert classify("Ghi chó").flags == []  # documented 5A.1 miss: all-valid characters, not detectable per string


# ------------------------------------------------------------------ 5-10 engine (pure)
def T(id_, ttype, bbox, rot=0.0, size=9.0, flags=None, text="x"):
    return E.TextB(id_, ttype, text, bbox, rot, size, flags or [])


def G(id_, pts, kind="line", closed=False):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return E.GeoP(id_, kind, pts, closed, (min(xs), min(ys), max(xs), max(ys)))


def test_engine_nearest_aligned_line_wins():
    texts = [T("t", "LENGTH", (400, 186, 447, 196))]
    geoms = [G("near", [(100, 200), (820, 200)]), G("far", [(100, 225), (820, 225)]), G("cross", [(420, 100), (420, 180)])]
    c = E.associate(texts, geoms)
    assert c[0].geometry_id == "near" and c[0].rank == 1 and c[0].status == "CANDIDATE" and c[0].confidence >= 0.9
    assert c[0].relation == "above" and c[0].orientation_match


def test_engine_rotated_text_prefers_parallel_line():
    texts = [T("t", "LENGTH", (936, 313, 946, 360), rot=270)]
    geoms = [G("vert", [(950, 150), (950, 510)]), G("horiz", [(900, 365), (1000, 365)])]
    top = E.associate(texts, geoms)[0]
    assert top.geometry_id == "vert" and top.angle_difference == 0.0


def test_engine_two_parallel_candidates_are_ambiguous():
    c = E.associate([T("t", "LENGTH", (180, 402, 212, 411), size=7)], [G("a", [(100, 400), (300, 400)]), G("b", [(100, 412), (300, 412)])])
    assert [x.status for x in c[:2]] == ["AMBIGUOUS", "AMBIGUOUS"]


def test_engine_thresholds_are_configurable():
    texts, geoms = [T("t", "LENGTH", (400, 186, 447, 196))], [G("g", [(100, 200), (820, 200)])]
    assert E.associate(texts, geoms)[0].status == "CANDIDATE"
    assert E.associate(texts, geoms, E.Params(auto_threshold=0.99, review_threshold=0.5))[0].status == "REVIEW_REQUIRED"
    assert E.associate(texts, geoms, E.Params(auto_threshold=0.995, review_threshold=0.99))[0].status == "AMBIGUOUS"


def test_engine_excluded_types_regions_and_ambiguous_flags():
    g = [G("g", [(100, 200), (820, 200)])]
    for tt in ("TABLE", "TITLE", "SCALE", "REVISION", "OTHER", "UNKNOWN"):
        assert E.associate([T("t", tt, (400, 186, 447, 196))], g) == []
    assert E.associate([T("t", "LENGTH", (400, 186, 447, 196))], g, excluded_regions=[(0, 0, 900, 300)]) == []
    flagged = E.associate([T("t", "LENGTH", (400, 186, 447, 196), flags=["unit_case_ambiguous"])], g)[0]
    assert flagged.status == "AMBIGUOUS"


def test_engine_detail_reference_only_to_compatible_geometry():
    c = E.associate([T("t", "DETAIL_REFERENCE", (1020, 617, 1062, 626), size=8)],
                    [G("circ", [(986, 620), (1014, 620)], kind="circle", closed=True), G("line", [(1020, 630), (1060, 630)])])
    assert [x.geometry_id for x in c] == ["circ"] and c[0].association_type == "REFERENCE_TO"


def test_engine_duplicate_text_points_to_primary():
    geoms = [G("g", [(100, 200), (820, 200)])]
    texts = [T("a", "LENGTH", (400, 186, 447, 196), text="L=25.40m"), T("b", "LENGTH", (600, 188, 647, 198), text="L=25.40M")]
    c = {x.text_id: x for x in E.associate(texts, geoms)}
    assert {c["a"].duplicate_of_text, c["b"].duplicate_of_text} == {None, "a" if c["b"].duplicate_of_text else "b"}


def test_engine_uses_spatial_index_not_all_pairs(monkeypatch):
    calls = []
    real = E.score
    monkeypatch.setattr(E, "score", lambda *a, **k: calls.append(1) or real(*a, **k))
    geoms = [G(f"g{i}", [(i * 50.0, 5000), (i * 50.0 + 40, 5000)]) for i in range(2000)]  # far away from the text
    geoms.append(G("near", [(100, 200), (820, 200)]))
    c = E.associate([T("t", "LENGTH", (400, 186, 447, 196))], geoms)
    assert c[0].geometry_id == "near" and len(calls) < 10


def test_association_package_has_no_llm_dependency():
    """LLMs may only propose candidates (origin ai_inferred) - nothing in 5C calls one, and nothing computes with one."""
    pkg = pathlib.Path(E.__file__).parent
    for f in pkg.glob("*.py"):
        mods = {n.module or "" for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, ast.ImportFrom)}
        mods |= {a.name for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.startswith(("app.ai", "app.llm", "anthropic", "openai")) for m in mods), f


# ------------------------------------------------------------------ 11-22 service + API (synthetic sheet)
@pytest.fixture()
def drw(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, sheet())["id"]).json()
    blocks = {b["original_text"]: b for b in env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=a).json()}
    return a, d, blocks


def assocs(env, a, d, **q):
    return env.get(f"{B}/drawings/{d['id']}/pages/1/associations", params=q, headers=a).json()


def top_for(env, a, d, block):
    return next(x for x in assocs(env, a, d, text_block_id=block["id"]) if x["rank"] == 1)


def calibrate_and_run(env, a, d, ratio=100):
    env.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": ratio}, headers=a)
    r = env.post(f"{B}/drawings/{d['id']}/associations/run", headers=a)
    assert r.status_code == 200
    return r.json()


def test_text_blocks_api_keeps_original_and_classifies(env, drw):
    a, d, blocks = drw
    assert blocks["L=25.40m"]["text_type"] == "LENGTH" and blocks["L=25.40m"]["values"]["length"]["value_m"] == "25.40"
    assert blocks["L=12.70m"]["rotation"] in (90.0, 270.0)
    assert blocks["25.40"]["text_type"] == "TABLE" and "in_table" in blocks["25.40"]["flags"]
    assert blocks["BẢN VẼ SỐ: GT-01"]["text_type"] == "TITLE" and "in_title_block" in blocks["TỶ LỆ: 1:100"]["flags"]
    assert blocks["1/1"]["flags"] == ["page_number"]
    only = env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks?text_type=chainage", headers=a).json()
    assert sorted(b["original_text"] for b in only) == ["Km12+350", "Km12+600"]


def test_processing_creates_candidates_but_never_confirms(env, drw):
    a, d, blocks = drw
    rows = assocs(env, a, d)
    assert rows and all(r["status"] != "CONFIRMED" and r["origin"] == "rule" for r in rows)
    excluded = {blocks[t]["id"] for t in ("25.40", "125.5", "BẢN VẼ SỐ: GT-01", "TỶ LỆ: 1:100", "LẦN SỬA: A", "1/1", "STT")}
    assert not excluded & {r["text_block_id"] for r in rows}  # table / title block / page number never associated
    top = top_for(env, a, d, blocks["L=25.40m"])
    assert top["association_type"] == "DIMENSION_OF" and "chưa có tỷ lệ" in top["reason"] and top["measured_value"] is None


def test_matching_dimension_on_confirmed_scale(env, drw):
    a, d, blocks = drw
    calibrate_and_run(env, a, d)
    top = top_for(env, a, d, blocks["L=25.40m"])
    assert top["status"] == "CANDIDATE" and top["confidence"] >= 0.9
    assert (top["text_value"], top["measured_value"], top["difference"]) == ("25.4", "25.4", "0")
    m = env.get(f"{B}/measurements/{top['measurement_id']}", headers=a).json()
    assert m["value_real"] == "25.400000" and m["method"] == "geometry-5B.1/assoc-5C"


def test_conflict_shows_text_geometry_difference_and_is_not_corrected(env, drw):
    a, d, blocks = drw
    stats = calibrate_and_run(env, a, d)
    top = top_for(env, a, d, blocks["L=13.50m"])
    assert top["status"] == "CONFLICT" and stats["conflicts"] >= 1
    assert (top["text_value"], top["measured_value"], top["difference"]) == ("13.5", "12.7", "0.8")
    assert "Chữ: 13.5 m · Hình học: 12.7 m · Chênh: 0.8 m" in top["reason"]
    again = env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=a).json()
    assert next(b for b in again if b["id"] == blocks["L=13.50m"]["id"])["original_text"] == "L=13.50m"  # never rewritten
    # confirming a conflict requires an explicit engineer note
    assert env.post(f"{B}/associations/{top['id']}/confirm", json={}, headers=a).status_code == 422


def test_parallel_lines_stay_ambiguous_without_conflict_check(env, drw):
    a, d, blocks = drw
    calibrate_and_run(env, a, d)
    rows = assocs(env, a, d, text_block_id=blocks["L=5.00m"]["id"])
    assert [r["status"] for r in rows[:2]] == ["AMBIGUOUS", "AMBIGUOUS"] and rows[0]["measured_value"] is None


def test_chainage_interval_only_from_two_chainages_on_same_geometry(env, drw):
    a, d, blocks = drw
    stats = calibrate_and_run(env, a, d)
    assert stats["chainage_intervals"] == 1
    k1, k2 = top_for(env, a, d, blocks["Km12+350"]), top_for(env, a, d, blocks["Km12+600"])
    assert k1["association_type"] == "CHAINAGE_FOR" and k1["geometry_id"] == k2["geometry_id"]
    # Km12+600 - Km12+350 = 250 m, but the synthetic polyline is 250 pt = 8.819 m at 1:100 -> conflict, nothing corrected
    assert k1["status"] == k2["status"] == "CONFLICT" and k1["text_value"] == "250" and k1["measured_value"] == "8.819"
    m = env.get(f"{B}/measurements/{k1['measurement_id']}", headers=a).json()
    assert m["kind"] == "chainage_interval" and m["value_real"] == "250.000000" and m["scale_source"] == "chainage"
    linked = env.get(f"{B}/measurements/{m['id']}/associations", headers=a).json()
    assert {x["id"] for x in linked} == {k1["id"], k2["id"]}
    # re-running does not pile up interval measurements
    calibrate_and_run(env, a, d)
    ms = [x for x in env.get(f"{B}/drawings/{d['id']}/measurements", headers=a).json() if x["kind"] == "chainage_interval"]
    assert len(ms) == 1


def test_detail_reference_and_label(env, drw):
    a, d, blocks = drw
    ref = assocs(env, a, d, text_block_id=blocks["CHI TIẾT A"]["id"])
    assert ref and {r["association_type"] for r in ref} == {"REFERENCE_TO"}
    g = env.get(f"{B}/geometry/{ref[0]['geometry_id']}", headers=a).json()
    assert g["kind"] == "circle"
    assert assocs(env, a, d, text_block_id=blocks["Xem chi tiết A-A"]["id"]) == []  # nothing nearby: no cross-page guess
    label = top_for(env, a, d, blocks["HỘ LAN TÔN LƯỢN SÓNG"])
    assert label["association_type"] == "LABEL_OF"


def test_repeated_text_marked_duplicate_and_not_measured_twice(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    from tests.geometry_helpers import _t
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, sheet(extra=lambda p: _t(p, (650, 194), "L=25.40m", 9)))["id"]).json()
    calibrate_and_run(env, a, d)
    blocks = [b for b in env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=a).json() if b["original_text"] == "L=25.40m"]
    assert len(blocks) == 2 and all(b["repeat_count"] == 2 for b in blocks)
    tops = [top_for(env, a, d, b) for b in blocks]
    primary = [t for t in tops if t["duplicate_of"] is None]
    dup = [t for t in tops if t["duplicate_of"]]
    assert len(primary) == 1 and len(dup) == 1 and dup[0]["duplicate_of"] == primary[0]["id"]
    assert dup[0]["measurement_id"] is None and primary[0]["measurement_id"]
    assert env.post(f"{B}/associations/{dup[0]['id']}/confirm", json={"note": "x"}, headers=a).status_code == 409


def test_review_workflow_confirm_reject_ambiguous(env, drw):
    a, d, blocks = drw
    calibrate_and_run(env, a, d)
    rows = assocs(env, a, d, text_block_id=blocks["L=5.00m"]["id"])
    assert env.post(f"{B}/associations/{rows[0]['id']}/reject", json={}, headers=a).status_code == 422  # reason required
    ok = env.post(f"{B}/associations/{rows[1]['id']}/confirm", json={"note": "đường dưới là đường kích thước"}, headers=a).json()
    assert ok["status"] == "CONFIRMED" and ok["decided_by"]
    after = {r["id"]: r["status"] for r in assocs(env, a, d, text_block_id=blocks["L=5.00m"]["id"])}
    assert after[rows[0]["id"]] == "REJECTED"  # the competing candidate is closed automatically
    lbl = top_for(env, a, d, blocks["HỘ LAN TÔN LƯỢN SÓNG"])
    m = env.post(f"{B}/associations/{lbl['id']}/mark-ambiguous", json={"note": "nhãn chung cho cả đoạn"}, headers=a).json()
    assert m["status"] == "AMBIGUOUS" and "nhãn chung" in m["reason"]
    rej = env.post(f"{B}/associations/{m['id']}/reject", json={"note": "không phải đối tượng này"}, headers=a).json()
    assert rej["status"] == "REJECTED"
    assert env.post(f"{B}/associations/{rej['id']}/confirm", json={"note": "x"}, headers=a).status_code == 409


def test_reassign_keeps_history_and_rechecks(env, drw):
    a, d, blocks = drw
    calibrate_and_run(env, a, d)
    top = top_for(env, a, d, blocks["L=13.50m"])
    lines = env.get(f"{B}/drawings/{d['id']}/geometry?kind=line", headers=a).json()
    long_line = next(g for g in lines if g["length_pt"] == "720.0000")
    assert env.patch(f"{B}/associations/{top['id']}", json={"geometry_id": long_line["id"]}, headers=a).status_code == 422
    r = env.patch(f"{B}/associations/{top['id']}", json={"geometry_id": long_line["id"], "reason": "thử đường dài"}, headers=a).json()
    h = r["history"][-1]
    assert h["old_geometry_id"] == top["geometry_id"] and h["new_geometry_id"] == long_line["id"]
    assert h["reason"] == "thử đường dài" and h["user"] == "admin@a.test" and h["timestamp"]
    assert r["origin"] == "engineer" and r["status"] == "CONFLICT" and r["measured_value"] == "25.4"  # 13.5 vs 25.4 re-checked
    # re-running the rule engine never overwrites the engineer's choice
    calibrate_and_run(env, a, d)
    kept = env.get(f"{B}/associations/{top['id']}", headers=a).json()
    assert kept["geometry_id"] == long_line["id"] and kept["history"] == r["history"]


def test_manual_association_and_validation(env, drw):
    a, d, blocks = drw
    lines = env.get(f"{B}/drawings/{d['id']}/geometry?kind=line", headers=a).json()
    body = {"text_block_id": blocks["Xem chi tiết A-A"]["id"], "geometry_id": lines[0]["id"], "association_type": "NOTE_FOR"}
    assert env.post(f"{B}/associations", json=body, headers=a).status_code == 422  # reason required
    assert env.post(f"{B}/associations", json={**body, "association_type": "BOGUS", "reason": "x"}, headers=a).status_code == 422
    made = env.post(f"{B}/associations", json={**body, "reason": "ghi chú cho đường này"}, headers=a)
    assert made.status_code == 201 and made.json()["origin"] == "engineer" and made.json()["status"] == "REVIEW_REQUIRED"


def test_provenance_chain_and_downstream_only_confirmed(env, drw):
    from app.association.service import confirmed_for_downstream
    import uuid

    from app.db import get_db
    from app.main import app
    a, d, blocks = drw
    calibrate_and_run(env, a, d)
    top = top_for(env, a, d, blocks["L=25.40m"])
    p = env.get(f"{B}/associations/{top['id']}", headers=a).json()["provenance"]
    assert p["text"]["original_text"] == "L=25.40m" and p["association"]["type"] == "DIMENSION_OF"
    assert p["geometry"]["length_pt"] == "720.0000" and p["measurement"]["value_real"] == "25.400000"
    assert p["downstream_allowed"] is False
    env.post(f"{B}/associations/{top['id']}/confirm", json={"note": "đúng"}, headers=a)
    assert env.get(f"{B}/associations/{top['id']}", headers=a).json()["provenance"]["downstream_allowed"] is True
    db = next(app.dependency_overrides[get_db]())
    ids = {str(x.id) for x in confirmed_for_downstream(db, uuid.UUID(d["id"]))}
    db.close()
    assert ids == {top["id"]}


def test_company_isolation_and_permissions(env, drw):
    a, d, blocks = drw
    top = top_for(env, a, d, blocks["L=25.40m"])
    b = login(env, "admin@b.test", "pw-admin-2")
    assert env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=b).status_code == 404
    assert env.get(f"{B}/associations/{top['id']}", headers=b).status_code == 404
    assert env.post(f"{B}/associations/{top['id']}/confirm", json={"note": "x"}, headers=b).status_code == 404
    v = login(env, "viewer@a.test", "pw-x")
    assert env.get(f"{B}/drawings/{d['id']}/pages/1/associations", headers=v).status_code == 200
    assert env.post(f"{B}/associations/{top['id']}/confirm", json={"note": "x"}, headers=v).status_code == 403
    assert env.post(f"{B}/drawings/{d['id']}/associations/run", headers=v).status_code == 403


def test_tcvn3_text_block_preserved_and_not_associated(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    from tests.geometry_helpers import _t
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, sheet(extra=lambda p: _t(p, (400, 214), "ChiÒu dµi tuyÕn", 9)))["id"]).json()
    b = next(x for x in env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=a).json() if "tuy" in x["original_text"])
    assert b["original_text"] == "ChiÒu dµi tuyÕn" and b["text_type"] == "UNKNOWN" and "ENCODING_UNKNOWN" in b["flags"]
    assert env.get(f"{B}/drawings/{d['id']}/pages/1/associations?text_block_id={b['id']}", headers=a).json() == []


def test_association_failure_never_fails_processing(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    import app.association.service as S

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(S, "run", boom)
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, sheet())["id"]).json()
    assert d["status"] == "processed"
    summ = env.get(f"{B}/drawings/{d['id']}/geometry/summary", headers=a).json()
    assert summ["pages"][0]["stats"]["association"]["error"].startswith("RuntimeError")


def test_decimal_values_are_exact():
    c = classify("L=0,1m")
    assert D(c.values["length"]["value_m"]) == D("0.1")
