"""Unit tests for draft-BOQ candidate generation, computation and duplicate detection (pure functions)."""
from decimal import Decimal as D

from app.boq import generate as G
from app.pdf.analysis import Line, find_dimensions, find_specs
from app.takeoff.engine import MeasurementRules


def derived_for(text, src="text", conf=None):
    ln = Line("L1", 1, text, (10, 10, 200, 20), src, conf)
    out = []
    for n, f in enumerate(find_dimensions(ln) + find_specs(ln)):
        out.append({"id": f"d{n}", "kind": f.kind, "text": f.raw, "confidence": f.confidence,
                    "data": {**f.data, "flags": f.flags, "from_source": src}})
    line = {"id": "L1", "page_no": 1, "text": text, "bbox": [10, 10, 200, 20]}
    return line, out


def cand(text, units=None, status="not_detected", **kw):
    line, der = derived_for(text, **kw)
    return G.candidates_from_line(line, der, units, status, "drw")


def codes(c):
    return {f.code for f in c.flags}


def test_concrete_candidate_requires_confirmed_units():
    c = cand("DẦM D1 300x600 L=6000 SL=4 - BÊ TÔNG B25")
    assert c.module == "concrete_prism" and c.category == "concrete" and c.mark == "D1" and c.section_key == "300x600"
    assert {k: v["value"] for k, v in c.inputs.items()} == {"width": "300", "height": "600", "length": "6000", "count": "4"}
    assert c.unit_system is None and "unit_unconfirmed" in codes(c)
    ok = cand("DẦM D1 300x600 L=6000 SL=4", units="mm", status="confirmed")
    assert ok.unit_system == "mm" and "unit_unconfirmed" not in codes(ok)
    # detected-but-unconfirmed page units are NOT used
    assert cand("DẦM D1 300x600 L=6000 SL=4", units="mm", status="unverified").unit_system is None


def test_explicit_units_on_line_and_conflicts():
    c = cand("DẦM 0,3x0,6 m L=6 m SL=2")
    assert c.unit_system == "m" and not codes(c) & {"unit_unconfirmed", "inconsistent_units"}
    mixed = cand("DẦM 300x600 mm L=6 m SL=2")
    assert "inconsistent_units" in codes(mixed) and mixed.unit_system is None
    conflict = cand("DẦM 0,3x0,6 m L=6 m SL=2", units="mm", status="confirmed")
    assert "unit_conflict" in codes(conflict) and conflict.unit_system == "m"


def test_missing_values_are_not_invented():
    c = cand("DẦM D2 300x600 L=6000", units="mm", status="confirmed")  # no SL
    assert c.inputs["count"]["value"] is None
    r = G.compute(c.module, c.inputs, c.unit_system, D(0), MeasurementRules())
    assert r.quantity is None and r.flags[0].code == "input_missing"
    prof = cand("Dầm thép I200 L=6000 SL=2", units="mm", status="confirmed")
    assert prof.module == "steel_section_by_weight" and prof.inputs["unit_weight_kg_m"]["value"] is None
    assert "unit_weight_required" in codes(prof)


def test_rebar_box_plate_candidates_and_quantities():
    rules = MeasurementRules()
    reb = cand("CỐT THÉP Ø16a200 L=3500 SL=24 CB400-V", units="mm", status="confirmed")
    assert reb.module == "rebar_weight" and reb.inputs["diameter_mm"]["value"] == "16"
    assert "diameter_convention_mm" in codes(reb)
    r = G.compute(reb.module, reb.inputs, reb.unit_system, D(0), rules)
    assert r.quantity == D("132.580") and r.unit == "kg"  # pi/4*16^2e-6*3.5*7850*24 = 132.58024 (float cross-check)
    box = cand("THÉP HỘP 50x50x2 L=6000 SL=10", units="mm", status="confirmed")
    assert G.compute(box.module, box.inputs, box.unit_system, D(0), rules).quantity == D("180.864")
    pl = cand("BẢN MÃ PL10 200x300 SL=8", units="mm", status="confirmed")
    assert pl.module == "steel_plate" and G.compute(pl.module, pl.inputs, pl.unit_system, D(0), rules).quantity == D("37.680")
    assert cand("Ghi chú chung", units="mm", status="confirmed") is None
    assert cand("6000", units="mm", status="confirmed") is None


def test_ambiguous_and_low_confidence_flags():
    amb = cand("DẦM 300x600 L=6,000 SL=2", units="mm", status="confirmed")
    assert "ambiguous_number" in codes(amb) and amb.inputs["length"]["value"] is None
    low = cand("THÉP HỘP 50x50x2 L=6000 SL=10", units="mm", status="confirmed", src="ocr", conf=0.5)
    assert "low_confidence_source" in codes(low)


def test_schedule_table_rows_are_copied_verbatim():
    table = {"id": "T1", "page_no": 1, "bbox": [60, 600, 580, 660], "data": {
        "table_type": "material_schedule", "header_map": {"0": "stt", "1": "description", "2": "spec", "3": "unit", "4": "quantity"},
        "rows": [["STT", "TÊN", "QUY CÁCH", "ĐVT", "KL"], ["1", "Dầm D1", "300x600", "m3", "4,32"], ["2", "Thép hộp", "50x50x2", "kg", "1,250"],
                 ["3", "Bản mã", "", "", ""]],
        "cells": [[None] * 5, [[60, 620, 100, 640]] * 5, [[60, 640, 100, 660]] * 5, [[60, 660, 100, 680]] * 5]}}
    cs = G.candidates_from_table(table, "drw")
    assert [c.category for c in cs] == ["concrete", "steel_box", "plate"]
    assert cs[0].module is None and cs[0].inputs["quantity"]["value"] == "4.32" and cs[0].stated_unit == "m3"
    assert cs[0].inputs["quantity"]["cell"] == [1, 4] and cs[0].bbox == [60, 620, 100, 640] and cs[0].mark == "D1"
    assert cs[1].inputs["quantity"]["value"] is None and "ambiguous_number" in codes(cs[1])
    assert {"quantity_missing", "unit_missing"} <= codes(cs[2])
    r = G.compute(None, cs[0].inputs, None, D("0.05"), MeasurementRules(), "m3")
    assert r.quantity == D("4.536") and "(1 + 0.05)" in r.formula_text


def test_sanity_warnings():
    f = G.sanity_flags("rebar_weight", {"diameter_mm": D(15), "length": D(300), "to_m": D(1), "count": D(1)}, "m")
    assert {x.code for x in f} == {"nonstandard_rebar_diameter", "suspicious_large_dimension"}
    f = G.sanity_flags("steel_plate", {"length": D(100), "width": D(100), "thickness": D(150), "to_m": D("0.001"), "count": D(20000)}, "mm")
    assert {x.code for x in f} == {"suspicious_plate_thickness", "suspicious_count"}


def test_duplicate_groups():
    base = {"unit_system": "mm", "mark": None, "section_key": None, "category": "concrete", "unit": "m3"}
    items = [
        {**base, "id": "a", "module": "concrete_prism", "calc_inputs": {"w": "1"}, "source_item_ids": ["L1"], "quantity": D("4.32"), "mark": "D1", "section_key": "300x600"},
        {**base, "id": "b", "module": "concrete_prism", "calc_inputs": {"w": "1"}, "source_item_ids": ["L2"], "quantity": D("4.32")},
        {**base, "id": "c", "module": None, "calc_inputs": {"quantity": "4.32"}, "source_item_ids": ["T1"], "quantity": D("4.32"), "mark": "D1", "section_key": "300x600"},
        {**base, "id": "d", "module": None, "calc_inputs": {}, "source_item_ids": ["T1"], "quantity": D("9"), "mark": "D2", "section_key": "300x600"},
    ]
    g = G.duplicate_groups(items)
    assert {"other_id": "b", "reason": "identical_calculation"} in g["a"]
    assert {"other_id": "c", "reason": "schedule_and_annotation", "quantities_match": True} in g["a"]
    assert all(x["other_id"] != "d" for x in g["a"])  # different mark -> not a duplicate
    assert "d" not in g or all(x["other_id"] != "c" for x in g["d"])  # two table rows are never compared to each other
