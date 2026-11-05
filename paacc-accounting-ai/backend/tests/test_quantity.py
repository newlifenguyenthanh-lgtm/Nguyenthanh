"""Phase 5E-1: quantity engine foundation (pure Decimal engine + API on SYNTHETIC drawings; no real-data claim)."""
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.quantity import engine as E
from app.quantity import rounding, units
from app.quantity.service import TRANSITIONS
from tests import component_helpers as H
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr


def M(kind, value, unit, status="confirmed", **details):
    return E.MeasIn(f"m-{kind}", kind, None if value is None else D(value), unit, status, details)


# ------------------------------------------------------------------ pure engine
def test_1_count_reference():
    c = E.calculate("COUNT_REFERENCE", [M("count", "51", "count")], precision=0)
    assert (c.status, c.value, c.unit, c.input_measurement_ids) == ("CALCULATED", D("51"), "ea", ["m-count"])


def test_2_length_reference():
    c = E.calculate("MEASUREMENT_REFERENCE", [M("length", "125.40", "m")], precision=2)
    assert (c.status, c.value, c.unit, c.quantity_type) == ("CALCULATED", D("125.40"), "m", "LENGTH")


def test_3_area_and_perimeter_reference():
    assert E.calculate("AREA_REFERENCE", [M("area", "25.50", "m2")], precision=2).value == D("25.50")
    assert E.calculate("PERIMETER_REFERENCE", [M("perimeter", "20.4", "m")]).value == D("20.400")


def test_4_unit_normalisation():
    assert units.convert(D("2500"), "mm", "m") == D("2.5")
    assert units.convert(D("1"), "m2", "mm2") == D("1000000")
    assert units.convert(D("1"), "m3", "mm3") == D("1000000000")
    assert units.convert(D("1"), "t", "kg") == D("1000")
    assert units.to_base(D("250"), "cm") == (D("2.5"), "m") and units.normalize("m²") == "m2" and units.normalize("cái") == "ea"
    with pytest.raises(units.UnitError):
        units.convert(D("1"), "m", "kg")
    with pytest.raises(units.UnitError):
        units.convert(D("1"), "set", "ea")  # count units never silently mixed
    with pytest.raises(units.UnitError):
        units.convert(2500.0, "mm", "m")  # floats refused
    # a mm-denominated engineer parameter is normalised before calculation
    c = E.calculate("COUNT_X_LENGTH", [M("count", "4", "count")], {"unit_length": {"value": "2500", "unit": "mm", "source": "bản vẽ"}})
    assert c.value == D("10.000") and c.unit == "m"


def test_5_decimal_no_float_drift():
    assert 0.1 * 3 != 0.3  # the float problem this engine must not have
    c = E.calculate("COUNT_X_LENGTH", [M("count", "3", "count")], {"unit_length": {"value": "0.1", "unit": "m", "source": "x"}}, precision=6)
    assert c.raw == D("0.3") and c.value == D("0.300000") and isinstance(c.raw, D)
    c = E.calculate("LENGTH_X_UNIT_WEIGHT", [M("length", "100", "m")], {"unit_weight": {"value": "3.95", "unit": "kg/m", "source": "bảng tra"}})
    assert c.raw == D("395.00") and c.value == D("395.000") and c.unit == "kg" and c.quantity_type == "WEIGHT"


def test_6_explicit_rounding_only_on_the_final_value():
    c = E.calculate("MEASUREMENT_REFERENCE", [M("length", "12.345678", "m")], precision=2, rounding_rule="ROUND_HALF_UP")
    assert (c.raw, c.value, c.precision, c.rounding_rule) == (D("12.345678"), D("12.35"), 2, "ROUND_HALF_UP")
    assert rounding.apply(D("12.345"), 2, "ROUND_HALF_EVEN") == D("12.34")
    assert rounding.apply(D("12.345"), 2, "ROUND_HALF_UP") == D("12.35")
    assert rounding.apply(D("12.341"), 2, "ROUND_CEILING") == D("12.35")
    # derived: no intermediate rounding (51 x 2.4999 = 127.4949 -> 127.49, not 51 x 2.50)
    c = E.calculate("COUNT_X_LENGTH", [M("count", "51", "count")], {"unit_length": {"value": "2.4999", "unit": "m", "source": "x"}}, precision=2)
    assert c.raw == D("127.4949") and c.value == D("127.49")
    with pytest.raises(ValueError):
        E.calculate("COUNT_REFERENCE", [M("count", "1", "count")], rounding_rule="BANKERS")


def test_derived_count_x_length_and_unit_weight_foundation():
    c = E.calculate("COUNT_X_LENGTH", [M("count", "51", "count")], {"unit_length": {"value": "2.5", "unit": "m", "source": "chi tiết A"}})
    assert c.value == D("127.500") and c.input_measurement_ids == ["m-count"] and c.parameters["unit_length"]["source"] == "chi tiết A"
    missing = E.calculate("LENGTH_X_UNIT_WEIGHT", [M("length", "100", "m")])
    assert missing.status == "REQUIRES_REVIEW" and missing.value is None and "không tự đoán" in missing.reasons[0]
    unsourced = E.calculate("LENGTH_X_UNIT_WEIGHT", [M("length", "100", "m")], {"unit_weight": {"value": "3.95", "unit": "kg/m"}})
    assert unsourced.status == "REQUIRES_REVIEW" and unsourced.value is None
    with pytest.raises(E.QuantityError):
        E.calculate("LENGTH_X_UNIT_WEIGHT", [M("length", "1", "m")], {"unit_weight": {"value": "3.95", "unit": "m", "source": "x"}})
    with pytest.raises(E.QuantityError):
        E.calculate("VOLUME_MAGIC", [])


@pytest.mark.parametrize("meas,group,status", [
    ([M("length", "5", "m", status="computed")], None, "REQUIRES_REVIEW"),  # 5B not confirmed by an engineer
    ([M("length", "5", "m", status="rejected")], None, "BLOCKED"),
    ([M("length", None, None, status="computed")], None, "BLOCKED"),  # no confirmed scale -> no real value
    ([], None, "BLOCKED"),
])
def test_8_non_authoritative_measurement_never_yields_a_value(meas, group, status):
    c = E.calculate("MEASUREMENT_REFERENCE", meas, group_status=group)
    assert c.status == status and c.value is None and c.raw is None


@pytest.mark.parametrize("group", ["OCCLUDED", "IRREGULAR_PATTERN"])
def test_8b_occluded_or_irregular_count_requires_review(group):
    c = E.calculate("COUNT_REFERENCE", [M("count", "9", "count")], group_status=group)
    assert c.status == "REQUIRES_REVIEW" and c.value is None


def test_8c_irregular_spacing_requires_review():
    assert E.calculate("SPACING_REFERENCE", [M("spacing", "2.1", "m", uniform=False)]).status == "REQUIRES_REVIEW"


def test_state_machine():
    assert TRANSITIONS["CALCULATED"] == {"CONFIRMED", "REJECTED"}
    assert "CONFIRMED" not in TRANSITIONS["REQUIRES_REVIEW"] | TRANSITIONS["BLOCKED"] | TRANSITIONS["DRAFT"]
    assert TRANSITIONS["REJECTED"] == set()


def test_engine_has_no_llm_and_no_float():
    import ast
    import pathlib
    for f in pathlib.Path(E.__file__).parent.glob("*.py"):
        src = f.read_text()
        tree = ast.parse(src)
        mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.startswith(("app.ai", "app.llm", "anthropic", "openai")) for m in mods), f
        assert "float(" not in src and "round(" not in src, f


# ------------------------------------------------------------------ API (synthetic fence drawing, scale 1:100)
@pytest.fixture()
def fence(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, H.sheet_fence())["id"]).json()
    env.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": 100}, headers=a)
    env.post(f"{B}/drawings/{d['id']}/components/run", headers=a)
    cs = env.get(f"{B}/drawings/{d['id']}/components", headers=a).json()
    return a, d, {c["component_type"]: c for c in cs}


def confirm_component(env, a, c):
    if c["status"] == "CANDIDATE":
        env.post(f"{B}/components/{c['id']}/review", json={}, headers=a)
    r = env.post(f"{B}/components/{c['id']}/confirm", json={"note": "ok"}, headers=a)
    assert r.status_code == 200, r.text
    return r.json()


def test_7_unconfirmed_component_is_refused(env, fence):
    a, d, cs = fence
    assert cs["FENCE"]["status"] == "CANDIDATE"
    r = env.post(f"{B}/components/{cs['FENCE']['id']}/quantity/run", json={}, headers=a)
    assert r.status_code == 422 and "CONFIRMED" in r.json()["detail"]
    assert env.get(f"{B}/components/{cs['FENCE']['id']}/quantity-results", headers=a).json() == []


def test_api_flow_reference_versioning_provenance_review(env, fence):
    a, d, cs = fence
    f = confirm_component(env, a, cs["FENCE"])
    r1 = env.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=a).json()
    # the 5B length measurement is still 'computed' (not engineer-confirmed) -> no final value
    assert r1["status"] == "REQUIRES_REVIEW" and r1["quantity_value"] is None and r1["calculation_method"] == "MEASUREMENT_REFERENCE"
    assert env.post(f"{B}/quantity-results/{r1['id']}/review", json={"decision": "confirm"}, headers=a).status_code == 409
    env.post(f"{B}/measurements/{r1['measurement_id']}/confirm", json={"note": "đã kiểm"}, headers=a)
    r2 = env.post(f"{B}/components/{f['id']}/quantity/run", json={"precision": 2}, headers=a).json()
    assert (r2["status"], r2["raw_value"], r2["quantity_value"], r2["unit"], r2["version"]) == ("CALCULATED", "20.461", "20.46", "m", 2)
    assert r2["source_measurement"][0]["status"] == "confirmed" and r2["source_component"]["status"] == "CONFIRMED"
    p = r2["provenance"]
    assert p["component"]["id"] == f["id"] and p["measurements"][0]["id"] == r2["measurement_id"]
    assert p["geometry_ids"] and p["texts"][0]["original_text"] == "HÀNG RÀO B40" and p["drawing"]["page_no"] == 1
    listed = env.get(f"{B}/components/{f['id']}/quantity-results", headers=a).json()
    assert [x["id"] for x in listed] == [r2["id"]]  # v1 superseded, kept for history
    hist = env.get(f"{B}/components/{f['id']}/quantity-results?include_superseded=true", headers=a).json()
    assert [x["version"] for x in hist] == [1, 2] and hist[0]["superseded_by_id"] == r2["id"]
    assert env.post(f"{B}/quantity-results/{r2['id']}/review", json={"decision": "reject"}, headers=a).status_code == 422
    ok = env.post(f"{B}/quantity-results/{r2['id']}/review", json={"decision": "confirm", "note": "đúng"}, headers=a).json()
    assert ok["status"] == "CONFIRMED" and ok["reviewed_by"]
    # a group: count reference from the repeat group's 5B count measurement
    post = confirm_component(env, a, cs["FENCE_POST"])
    cnt = env.post(f"{B}/components/{post['id']}/quantity/run", json={"method": "COUNT_REFERENCE"}, headers=a).json()
    assert cnt["status"] == "REQUIRES_REVIEW" and "chưa được kỹ sư xác nhận" in cnt["reason"]
    env.post(f"{B}/measurements/{cnt['measurement_id']}/confirm", json={"note": "đếm đủ"}, headers=a)
    cnt = env.post(f"{B}/components/{post['id']}/quantity/run", json={"method": "COUNT_REFERENCE", "precision": 0}, headers=a).json()
    assert (cnt["status"], cnt["quantity_value"], cnt["unit"]) == ("CALCULATED", "10", "ea")
    derived = env.post(f"{B}/components/{post['id']}/quantity/run",
                       json={"method": "COUNT_X_LENGTH", "parameters": {"unit_length": {"value": "2.5", "unit": "m", "source": "chi tiết trụ"}}},
                       headers=a).json()
    assert derived["quantity_value"] == "25" and derived["input_measurement_ids"] == [cnt["measurement_id"]]
    assert derived["parameters"]["unit_length"]["source"] == "chi tiết trụ"


def test_rejected_measurement_blocks(env, fence):
    a, d, cs = fence
    f = confirm_component(env, a, cs["FENCE"])
    r = env.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=a).json()
    env.post(f"{B}/measurements/{r['measurement_id']}/reject", json={"note": "đo sai"}, headers=a)
    b = env.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=a).json()
    assert b["status"] == "BLOCKED" and b["quantity_value"] is None and "loại bỏ" in b["reason"]


def test_10_company_isolation_and_permissions(env, fence):
    a, d, cs = fence
    f = confirm_component(env, a, cs["FENCE"])
    q = env.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=a).json()
    other = login(env, "admin@b.test", "pw-admin-2")
    assert env.get(f"{B}/quantity-results/{q['id']}", headers=other).status_code == 404
    assert env.get(f"{B}/components/{f['id']}/quantity-results", headers=other).status_code == 404
    assert env.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=other).status_code == 404
    assert env.post(f"{B}/quantity-results/{q['id']}/review", json={"decision": "reject", "note": "x"}, headers=other).status_code == 404
    v = login(env, "viewer@a.test", "pw-x")
    assert env.get(f"{B}/quantity-results/{q['id']}", headers=v).status_code == 200
    assert env.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=v).status_code == 403


def test_11_audit(env, fence):
    from app.db import get_db
    from app.main import app
    a, d, cs = fence
    f = confirm_component(env, a, cs["FENCE"])
    q = env.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=a).json()
    env.post(f"{B}/quantity-results/{q['id']}/review", json={"decision": "reject", "note": "chưa đủ"}, headers=a)
    db = next(app.dependency_overrides[get_db]())
    acts = [x.action for x in db.scalars(select(AuditLog).where(AuditLog.entity == "quantity_result").order_by(AuditLog.created_at))]
    db.close()
    assert acts == ["quantity_run", "quantity_reject"]
