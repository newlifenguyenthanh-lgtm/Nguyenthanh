"""Phase 5B: deterministic measurement engine + scale regions (synthetic geometry with exact expected values)."""
from decimal import Decimal as D

import pytest

from app.geometry import measure as M
from app.takeoff.engine import CalcError
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr
from tests.geometry_helpers import sheet


def P(id_, pts, closed=False, length=None, area=None):
    pts = [(D(str(x)), D(str(y))) for x, y in pts]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return M.Prim(id_, "line", pts, closed, D(str(length)) if length is not None else None, D(str(area)) if area is not None else None,
                  (min(xs), min(ys), max(xs), max(ys)))


def test_length_real_value_exact_with_page_scale():
    r = M.measure("length", [P("a", [(0, 0), (720, 0)], length=720)], [], 100, "confirmed")
    assert r.value_paper == D(720) and r.value_real == D("25.400") and r.real_unit == "m" and r.scale.source == "page"


def test_area_perimeter_count_distance_spacing():
    sq = P("s", [(0, 0), (72, 0), (72, 72), (0, 72)], closed=True, length=288, area=5184)
    assert M.measure("area", [sq], [], 100, "confirmed").value_real == D("6.4516")  # (2.54 m)^2
    assert M.measure("perimeter", [sq], [], 100, "confirmed").value_real == D("10.160")
    assert M.measure("count", [sq, sq], [], None, "not_detected").value_real == D(2)
    a, b = P("a", [(0, 0), (0, 0)], length=0), P("b", [(72, 0), (72, 0)], length=0)
    assert M.measure("distance", [a, b], [], 100, "confirmed").value_real == D("2.540")
    posts = [P(str(i), [(i * 72, 0), (i * 72, 10)], length=10) for i in (0, 1, 2, 3)]
    sp = M.measure("spacing", posts, [], 50, "confirmed")
    assert sp.value_real == D("1.270") and sp.details["uniform"] is True


def test_scale_region_wins_and_mixed_scales_are_refused():
    detail = M.ScaleRegion("r1", (D(0), D(0), D(200), D(200)), 20)
    inside = P("a", [(10, 10), (82, 10)], length=72)
    r = M.measure("length", [inside], [detail], 100, "confirmed")
    assert r.value_real == D("0.508") and r.scale.source == "region:r1"  # 1:20 detail, not the page 1:100
    across = P("b", [(150, 50), (300, 50)], length=150)
    res = M.measure("length", [across], [detail], 100, "confirmed")
    assert res.value_real is None and res.details["real_refused"] == "scale_ambiguous"
    assert M.measure("length", [P("c", [(0, 0), (72, 0)], length=72)], [], 100, "unverified").details["real_refused"] == "scale_unconfirmed"


@pytest.mark.parametrize("kind,prims,code", [
    ("perimeter", [P("a", [(0, 0), (1, 0)], length=1)], "not_closed"),
    ("distance", [P("a", [(0, 0), (1, 0)], length=1)], "need_two"),
    ("spacing", [P("a", [(0, 0), (1, 0)], length=1)] * 2, "need_three"),
    ("volume", [P("a", [(0, 0), (1, 0)], length=1)], "unknown_kind"),
    ("length", [], "no_geometry"),
])
def test_engine_errors(kind, prims, code):
    with pytest.raises(CalcError) as e:
        M.measure(kind, prims, [], 100, "confirmed")
    assert e.value.code == code


@pytest.fixture()
def drw(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, sheet())["id"]).json()
    lines = env.get(f"{B}/drawings/{d['id']}/geometry?kind=line", headers=a).json()
    long_line = next(g for g in lines if g["length_pt"] == "720.0000")
    return a, d, long_line


def test_measurement_api_scale_regions_review_and_isolation(env, drw):
    a, d, g = drw
    m = env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=a).json()
    assert m["value_paper"] == "720.000000" and m["value_real"] is None and m["details"]["real_refused"] == "scale_unconfirmed"
    assert env.post(f"{B}/measurements/{m['id']}/confirm", json={}, headers=a).status_code == 409  # no real value yet
    env.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": 100}, headers=a)
    m = env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=a).json()
    assert m["value_real"] == "25.400000" and m["scale_source"] == "page" and "1:100" in m["formula"]
    reg = env.post(f"{B}/drawings/{d['id']}/scale-regions", json={"page_no": 1, "bbox": [50, 150, 900, 250], "scale_ratio": 50}, headers=a).json()
    assert reg["status"] == "candidate"
    m2 = env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=a).json()
    assert m2["value_real"] == "25.400000"  # an unconfirmed region is ignored
    assert env.post(f"{B}/scale-regions/{reg['id']}/reject", json={}, headers=a).status_code == 422
    env.post(f"{B}/scale-regions/{reg['id']}/confirm", json={"note": "chi tiết 1:50"}, headers=a)
    m3 = env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=a).json()
    assert m3["value_real"] == "12.700000" and m3["scale_source"] == f"region:{reg['id']}"
    assert env.post(f"{B}/measurements/{m3['id']}/reject", json={}, headers=a).status_code == 422
    assert env.post(f"{B}/measurements/{m3['id']}/confirm", json={"note": "ok"}, headers=a).json()["status"] == "confirmed"
    assert [x["kind"] for x in env.get(f"{B}/drawings/{d['id']}/measurements", headers=a).json()] == ["length"] * 4
    b = login(env, "admin@b.test", "pw-admin-2")
    assert env.get(f"{B}/measurements/{m3['id']}", headers=b).status_code == 404
    assert env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=b).status_code == 404
    v = login(env, "viewer@a.test", "pw-x")
    assert env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=v).status_code == 403
    assert env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "bogus", "geometry_ids": [g["id"]]}, headers=a).status_code == 422


def test_rejected_or_duplicate_geometry_not_measured(env, drw):
    a, d, g = drw
    env.patch(f"{B}/geometry/{g['id']}", json={"status": "rejected", "note": "nét phụ"}, headers=a)
    assert env.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=a).status_code == 409
