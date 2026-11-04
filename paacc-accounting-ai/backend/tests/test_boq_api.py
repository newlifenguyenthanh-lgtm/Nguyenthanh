from decimal import Decimal as D

import pytest

from tests import pdf_factory as pf
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, make_boq, processed_drawing, use_ocr


@pytest.fixture()
def a(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    return login(env, "admin@a.test", "pw-admin-1")


def by_desc(boq, start):
    return next(i for i in boq["items"] if i["description"].upper().startswith(start.upper()))


def norm(s):
    return pf._ascii(s).upper()


def find(boq, prefix):
    return next(i for i in boq["items"] if norm(i["description"]).startswith(norm(prefix)))


def test_generate_draft_boq_from_drawing_with_confirmed_units(env, a):
    d = processed_drawing(env, a)
    r = make_boq(env, a, [d["id"]])
    assert r.status_code == 201, r.text
    boq = r.json()
    assert boq["status"] == "draft" and boq["version_no"] == 1 and boq["item_count"] == 6
    assert boq["sources"][0]["drawing_id"] == d["id"] and boq["sources"][0]["document_version_id"] == d["document_version_id"]
    beam = find(boq, "DẦM D1 300x600")
    assert beam["module"] == "concrete_prism" and beam["quantity"] == "4.3200" and beam["unit"] == "m3"
    assert beam["origin"] == "extracted" and beam["review_status"] == "pending" and beam["page_no"] == 1
    assert beam["inputs"]["length"] == {"value": "6000", "origin": "extracted", "source_item_id": beam["inputs"]["length"]["source_item_id"]}
    assert beam["excel_expr"] == "{length}*{width}*{height}*{count}*{to_m}^3" and "300 × 600" in beam["formula_text"]
    assert beam["source_item_ids"][0] and len(beam["bbox"]) == 4
    assert find(boq, "THÉP HỘP")["quantity"] == "180.8640"
    assert find(boq, "BẢN MÃ")["quantity"] == "37.6800"
    rebar = find(boq, "CỐT THÉP")
    assert rebar["quantity"] == "132.5800" and any(f["code"] == "diameter_convention_mm" for f in rebar["flags"])
    # schedule rows copied verbatim and cross-checked against annotations
    stated = [i for i in boq["items"] if i["module"] is None]
    assert {(i["quantity"], i["unit"]) for i in stated} == {("4.3200", "m3"), ("180.8600", "kg")}
    dup = next(f for f in beam["flags"] if f["code"] == "possible_duplicate")
    assert "khớp" in dup["message"] and dup["other_id"] in {i["id"] for i in stated}
    # categories ordered: concrete first
    assert [i["category"] for i in boq["items"]][:2] == ["concrete", "concrete"]
    # AI task for the virtual office
    task = next(t for t in env.get(f"{B}/ai-tasks?department=engineering_qs", headers=a).json() if t["agent_key"] == "quantity_surveyor")
    assert task["status"] == "completed" and "6 hạng mục" in task["output_summary"]


def test_units_not_confirmed_blocks_calculation_but_keeps_stated_rows(env, a):
    d = processed_drawing(env, a, units=None)
    boq = make_boq(env, a, [d["id"]]).json()
    beam = find(boq, "DẦM D1")
    assert beam["quantity"] is None and beam["has_blocking"]
    assert any(f["code"] == "unit_unconfirmed" for f in beam["flags"])
    assert boq["blocking_count"] == 4  # the 4 annotation-derived items
    assert {i["quantity"] for i in boq["items"] if i["module"] is None} == {"4.3200", "180.8600"}


def test_measurement_rules_waste_and_recalculation(env, a):
    d = processed_drawing(env, a)
    r = make_boq(env, a, [d["id"]], rules={"waste": {"concrete": "0.02"}, "decimals": 2})
    boq = r.json()
    beam = find(boq, "DẦM D1")
    assert beam["quantity"] == "4.4100" and beam["waste_factor"] == "0.0200"  # 4.32*1.02 = 4.4064 -> 4.41
    assert make_boq(env, a, [d["id"]], rules={"waste": {"concrete": "2"}}).status_code == 422
    assert make_boq(env, a, [d["id"]], rules={"waste": {"nope": "0.1"}}).status_code == 422
    upd = env.patch(f"{B}/boqs/{boq['id']}/rules", json={"waste": {"concrete": "0"}, "decimals": 3, "reason": "Theo HĐ"}, headers=a).json()
    assert find(upd, "DẦM D1")["quantity"] == "4.3200" and find(upd, "DẦM D1")["version"] == 2


def test_engineer_added_items(env, a):
    d = processed_drawing(env, a)
    boq = make_boq(env, a, [d["id"]]).json()
    url = f"{B}/boqs/{boq['id']}/items"
    r = env.post(url, json={"category": "structural_steel", "description": "Dầm thép I200", "module": "steel_section_by_weight",
                            "inputs": {"length": "6", "unit_weight_kg_m": "21.3", "count": "2"}, "unit_system": "m"}, headers=a)
    assert r.status_code == 201, r.text
    it = r.json()
    assert it["origin"] == "engineer" and it["quantity"] == "255.6000" and it["item_no"] == 7
    s = env.post(url, json={"category": "other", "description": "Bulông M20", "quantity": "48", "stated_unit": "bộ"}, headers=a).json()
    assert s["quantity"] == "48.0000" and s["unit"] == "bộ"
    assert env.post(url, json={"category": "x", "description": "a"}, headers=a).status_code == 422
    assert env.post(url, json={"category": "other", "description": "a", "module": "nope"}, headers=a).status_code == 422
    assert env.post(url, json={"category": "other", "description": "a", "module": "count_items", "inputs": {"zz": "1"}}, headers=a).status_code == 422
    assert env.post(url, json={"category": "other", "description": "a", "quantity": "abc", "stated_unit": "m"}, headers=a).status_code == 422


def test_scanned_drawing_ocr_item_flagged_low_confidence(env, a):
    d = processed_drawing(env, a, data=pf.scanned_pdf())
    boq = make_boq(env, a, [d["id"]]).json()
    box = boq["items"][0]
    assert box["module"] == "steel_box_hollow" and box["quantity"] == "180.8640"
    assert any(f["code"] == "low_confidence_source" for f in box["flags"])


def test_permissions_validation_and_isolation(env, a):
    d = processed_drawing(env, a)
    v = login(env, "viewer@a.test", "pw-x")
    b = login(env, "admin@b.test", "pw-admin-2")
    assert make_boq(env, v, [d["id"]]).status_code == 403
    assert make_boq(env, b, [d["id"]]).status_code == 404
    assert make_boq(env, a, []).status_code == 422
    boq = make_boq(env, a, [d["id"]]).json()
    assert env.get(f"{B}/boqs/{boq['id']}", headers=v).status_code == 200
    assert env.get(f"{B}/boqs/{boq['id']}", headers=b).status_code == 404
    assert env.get(f"{B}/boqs", headers=b).json() == []
    assert env.patch(f"{B}/boqs/{boq['id']}/rules", json={"decimals": 2}, headers=v).status_code == 403
    assert len(env.get(f"{B}/takeoff/modules", headers=v).json()["modules"]) == 9
