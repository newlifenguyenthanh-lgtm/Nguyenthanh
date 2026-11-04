import pytest

from tests import pdf_factory as pf
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr


@pytest.fixture()
def a(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    return login(env, "admin@a.test", "pw-admin-1")


def processed(env, a, data=None, **kw):
    doc = upload(env, a, data or pf.vector_pdf(**kw))
    d = process(env, a, doc["id"]).json()
    assert d["status"] == "processed", d
    return d, env.get(f"{B}/drawings/{d['id']}", headers=a).json()


def test_title_block_classification_and_unverified_scale(env, a):
    _, full = processed(env, a)
    p = full["pages"][0]
    assert p["drawing_number"] == "KC-01" and p["revision"] == "A"
    assert p["title"].startswith("MẶT BẰNG KẾT CẤU" if pf.VIETNAMESE else "MAT BANG KET CAU")
    assert [x["value"] for x in p["disciplines"]] == ["structural"]
    assert {v["value"] for v in p["view_types"]} >= {"plan", "schedule"}
    assert p["scale_status"] == "unverified" and p["scale_ratio"] is None  # detected, not applied
    assert p["scale_candidates"][0]["ratio"] == 100
    assert p["units_status"] == "unverified" and p["units"] is None and p["units_candidates"][0]["unit"] == "mm"
    regions = {r["data"]["region_type"] for r in env.get(f"{B}/drawings/{full['id']}/items?kind=region", headers=a).json()}
    assert {"title_block", "schedule_table"} <= regions


def test_dimensions_specs_have_source_coordinates_and_confidence(env, a):
    d, full = processed(env, a)
    dims = env.get(f"{B}/drawings/{d['id']}/items?kind=dimension", headers=a).json()
    texts = {x["id"]: x for x in env.get(f"{B}/drawings/{d['id']}/items?kind=text", headers=a).json()}
    sec = next(x for x in dims if x["data"]["type"] == "section" and x["data"]["values"] == ["300", "600"])
    src = texts[sec["data"]["from_item_id"]]
    assert sec["bbox"] == src["bbox"] and sec["page_no"] == 1 and sec["confidence"] == 0.8
    assert "unit_not_stated" in sec["data"]["flags"]
    bare = next(x for x in dims if x["data"]["type"] == "bare_number" and x["text"] == "6000")
    assert bare["confidence"] == 0.5 and bare["data"]["unit"] is None
    specs = {x["data"]["category"] for x in env.get(f"{B}/drawings/{d['id']}/items?kind=spec", headers=a).json()}
    assert {"concrete_grade", "rebar_grade", "steel_box", "plate"} <= specs
    table = env.get(f"{B}/drawings/{d['id']}/items?kind=table", headers=a).json()[0]
    assert table["data"]["table_type"] == "material_schedule" and table["data"]["header_map"]["4"] == "quantity"


def test_no_scale_or_units_printed_means_not_detected(env, a):
    _, full = processed(env, a, scale=None, units=None)
    p = full["pages"][0]
    assert p["scale_status"] == "not_detected" and p["units_status"] == "not_detected"
    assert p["scale_candidates"] == [] and p["units_candidates"] == []


def test_ocr_page_analysis_uses_ocr_confidence(env, a):
    d, full = processed(env, a, data=pf.scanned_pdf())
    p = full["pages"][0]
    assert p["drawing_number"] == "KC-02"
    assert p["title_fields"]["drawing_number"]["confidence"] == round(0.9 * 0.88, 3)
    sc = p["scale_candidates"][0]
    assert sc["ratio"] == 50 and sc["confidence"] == round(0.9 * 0.76, 3)
    box = next(x for x in env.get(f"{B}/drawings/{d['id']}/items?kind=dimension", headers=a).json() if x["data"]["type"] == "section")
    assert box["confidence"] == round(0.8 * 0.47, 3) and box["data"]["from_source"] == "ocr"


def test_calibration_requires_permission_and_is_audited(env, a):
    d, _ = processed(env, a)
    v = login(env, "viewer@a.test", "pw-x")
    url = f"{B}/drawings/{d['id']}/pages/1/calibration"
    assert env.post(url, json={"scale_ratio": 100, "units": "mm"}, headers=v).status_code == 403
    assert env.post(url, json={}, headers=a).status_code == 422
    assert env.post(url, json={"scale_ratio": 100, "not_to_scale": True}, headers=a).status_code == 422
    assert env.post(url, json={"units": "inch"}, headers=a).status_code == 422
    r = env.post(url, json={"scale_ratio": 100, "units": "mm"}, headers=a).json()
    assert r["scale_status"] == "confirmed" and r["scale_ratio"] == 100 and r["units"] == "mm" and r["calibrated_by"]
    r = env.post(url, json={"scale_ratio": 50}, headers=a).json()
    assert "scale_differs_from_detected" in r["warnings"] and r["scale_ratio"] == 50
    log = [x for x in env.get(f"{B}/audit-logs", headers=a).json() if x["action"] == "calibrate"]
    assert log[0]["detail"]["before"]["scale_ratio"] == 100 and log[0]["detail"]["after"]["scale_ratio"] == 50
    assert env.post(f"{B}/drawings/{d['id']}/pages/9/calibration", json={"units": "mm"}, headers=a).status_code == 404


def test_revisions_across_uploads_and_duplicate_findings(env, a):
    rev_a = pf.vector_pdf(rev="A")
    d1, _ = processed(env, a, data=rev_a)
    d2, _ = processed(env, a, rev="B")
    rev = next(f for f in d2["findings"] if f["type"] == "revision")
    assert rev["relation"] == "newer_than" and rev["other_drawing_id"] == d1["id"] and rev["other_revision"] == "A"
    d3, _ = processed(env, a, rev="B", title="MẶT BẰNG KẾT CẤU DẦM TẦNG 1 (SỬA)")
    conflict = [f for f in d3["findings"] if f["type"] == "revision" and f["other_drawing_id"] == d2["id"]]
    assert conflict[0]["relation"] == "conflict_same_revision_different_content" and conflict[0]["severity"] == "warning"
    sheets = env.get(f"{B}/drawing-sheets?number=KC-01", headers=a).json()
    assert [s["revision"] for s in sheets] == ["A", "B", "B"]
    b = login(env, "admin@b.test", "pw-admin-2")
    assert env.get(f"{B}/drawing-sheets?number=KC-01", headers=b).json() == []
    dup_doc = upload(env, a, rev_a, title="copy")  # byte-identical file uploaded as another document
    d4 = process(env, a, dup_doc["id"]).json()
    types = {f["type"] for f in d4["findings"]}
    assert "duplicate_file" in types and any(f.get("relation") == "identical_file" for f in d4["findings"])


def test_repeated_annotations_reported(env, a):
    lines = pf.SHEET_LINES + ["DẦM D2 300x600 L=6000 SL=2"]
    d, _ = processed(env, a, lines=lines)
    rep = [f for f in d["findings"] if f["type"] == "repeated_annotation"]
    assert any(f["text"] == "300x600" and len(f["occurrences"]) >= 2 for f in rep)
