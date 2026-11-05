"""Phase 5A API: geometry extracted during processing, coordinate conversion only on confirmed scale, review, isolation."""
from decimal import Decimal as D

import pytest

from tests import pdf_factory as pf
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr


@pytest.fixture()
def a(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    return login(env, "admin@a.test", "pw-admin-1")


def processed(env, h, data):
    d = process(env, h, upload(env, h, data)["id"]).json()
    assert d["status"] == "processed", d
    return d


def test_geometry_extracted_during_processing(env, a):
    d = processed(env, a, pf.vector_pdf())
    s = env.get(f"{B}/drawings/{d['id']}/geometry/summary", headers=a).json()
    p = s["pages"][0]
    assert p["geometry_status"] == "extracted" and p["stats"]["by_kind"]["line"] >= 6 and p["frame"]["rotation"] == 0
    assert s["review_counts"] == {"extracted": sum(p["stats"]["by_kind"].values())}
    # sheet border rect (20,20)-(1170,822): perimeter 2*(1150+802)
    border = env.get(f"{B}/drawings/{d['id']}/geometry?kind=rect&min_length_pt=3000", headers=a).json()
    assert [g["length_pt"] for g in border] == ["3904.0000"]
    grid = env.get(f"{B}/drawings/{d['id']}/geometry?kind=line&x0=95&y0=70&x1=605&y1=510", headers=a).json()
    assert {g["length_pt"] for g in grid if g["points"][0][0] == g["points"][1][0]} == {"420.0000"}  # grid x=100..600, y 80..500
    full = env.get(f"{B}/drawings/{d['id']}", headers=a).json()
    assert full["pages"][0]["geometry_status"] == "extracted"


def test_real_length_only_after_engineer_confirms_scale(env, a):
    d = processed(env, a, pf.vector_pdf())
    gid = env.get(f"{B}/drawings/{d['id']}/geometry?kind=rect&min_length_pt=3000", headers=a).json()[0]["id"]
    g = env.get(f"{B}/geometry/{gid}", headers=a).json()
    assert g["length_paper_mm"] == str((D("3904") * D("25.4") / 72).quantize(D("0.01")))
    assert g["length_real_m"] is None and "chưa được kỹ sư xác nhận" in g["real_basis"]
    env.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": 100, "units": "mm"}, headers=a)
    g = env.get(f"{B}/geometry/{gid}", headers=a).json()
    assert g["length_real_m"] == "137.724" and g["real_basis"] == "1:100 (đã xác nhận)"  # 3904 pt = 1377.24 mm paper x 100
    env.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"not_to_scale": True}, headers=a)
    assert env.get(f"{B}/geometry/{gid}", headers=a).json()["length_real_m"] is None


def test_real_quotation_layout_hairlines(env, a):
    # synthetic PDF with the real document's structure; ruled table drawn with stroked lines here
    d = processed(env, a, pf.quotation_pdf())
    pages = env.get(f"{B}/drawings/{d['id']}/geometry/summary", headers=a).json()["pages"]
    assert [p["geometry_status"] for p in pages] == ["extracted", "extracted"]
    # header + 13 rows -> 15 horizontal rules, 7 columns -> 8 vertical rules; page 2: header + 9 rows -> 11 + 8
    assert [p["stats"]["by_kind"] for p in pages] == [{"line": 23}, {"line": 19}]


def test_scanned_page_is_raster_only(env, a):
    d = processed(env, a, pf.scanned_pdf())
    p = env.get(f"{B}/drawings/{d['id']}/geometry/summary", headers=a).json()["pages"][0]
    assert p["geometry_status"] == "raster_only" and env.get(f"{B}/drawings/{d['id']}/geometry", headers=a).json() == []


def test_review_reextract_task_and_isolation(env, a):
    d = processed(env, a, pf.vector_pdf())
    v, b = login(env, "viewer@a.test", "pw-x"), login(env, "admin@b.test", "pw-admin-2")
    gid = env.get(f"{B}/drawings/{d['id']}/geometry?kind=line", headers=a).json()[0]["id"]
    assert env.patch(f"{B}/geometry/{gid}", json={"status": "rejected"}, headers=v).status_code == 403
    assert env.patch(f"{B}/geometry/{gid}", json={"status": "rejected"}, headers=a).status_code == 422  # reason required
    assert env.patch(f"{B}/geometry/{gid}", json={"status": "bogus", "note": "x"}, headers=a).status_code == 422
    r = env.patch(f"{B}/geometry/{gid}", json={"status": "ambiguous", "note": "Không rõ thuộc cấu kiện nào"}, headers=a).json()
    assert r["status"] == "ambiguous"
    assert env.post(f"{B}/drawings/{d['id']}/geometry/extract", headers=a).status_code == 409  # never overwrite reviewed geometry
    env.patch(f"{B}/geometry/{gid}", json={"status": "extracted", "note": "đặt lại"}, headers=a)
    r = env.post(f"{B}/drawings/{d['id']}/geometry/extract", headers=a)
    assert r.status_code == 200 and r.json()["primitives"] > 0
    task = next(t for t in env.get(f"{B}/ai-tasks", headers=a).json() if t["title"].startswith("Trích xuất hình học"))
    assert task["status"] == "completed" and task["agent_key"] == "pdf_drawing"
    assert "review_geometry" in [x["action"] for x in env.get(f"{B}/audit-logs", headers=a).json()]
    for url in (f"/drawings/{d['id']}/geometry", f"/drawings/{d['id']}/geometry/summary", f"/geometry/{gid}"):
        assert env.get(f"{B}{url}", headers=b).status_code == 404
    assert env.post(f"{B}/drawings/{d['id']}/geometry/extract", headers=b).status_code == 404


def test_geometry_can_be_disabled_without_affecting_processing(env, a, monkeypatch):
    monkeypatch.setenv("PAACC_GEOMETRY_ON_PROCESS", "false")
    d = processed(env, a, pf.vector_pdf())
    s = env.get(f"{B}/drawings/{d['id']}/geometry/summary", headers=a).json()
    assert s["pages"][0]["geometry_status"] == "not_extracted"
    assert env.get(f"{B}/drawings/{d['id']}/items?kind=dimension", headers=a).json()  # Phase 4 analysis unaffected


def test_engineering_room_shows_real_geometry_metrics(env, a):
    processed(env, a, pf.vector_pdf())
    processed(env, a, pf.scanned_pdf())
    m = {x["key"]: x["value"] for x in env.get(f"{B}/office/departments/engineering_qs", headers=a).json()["metrics"]}
    assert m["geometry_pages"] == "1" and m["raster_pages"] == "1" and m["geometry_ambiguous"] == "0"
