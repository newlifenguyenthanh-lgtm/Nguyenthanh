import math
from decimal import Decimal as D

import pytest

from app.takeoff.engine import MODULES, CalcError, MeasurementRules, calculate, list_modules
from app.takeoff.measure import real_length_from_paper


def q(key, waste="0", **p):
    return calculate(key, p, D(waste))


def test_concrete_prism_exact():
    r = q("concrete_prism", unit="mm", length=3000, width=300, height=600, count=2)
    assert r.quantity == D("1.080") and r.unit == "m3"
    r = q("concrete_prism", "0.02", unit="mm", length=3000, width=300, height=600, count=2)
    assert r.net == D("1.08") and r.quantity == D("1.102")  # 1.1016 -> 1.102 (half-up, 3 dp)


def test_unit_conversion_consistent_across_units():
    a = q("concrete_prism", unit="mm", length=3000, width=300, height=600, count=1).quantity
    b = q("concrete_prism", unit="cm", length=300, width=30, height=60, count=1).quantity
    c = q("concrete_prism", unit="m", length=3, width=0.3, height=0.6, count=1).quantity
    assert a == b == c == D("0.540")


def test_concrete_area_thickness():
    assert q("concrete_area_thickness", unit="mm", area_m2="25", thickness=200).quantity == D("5.000")


def test_rebar_weight_against_independent_math_and_table_anchor():
    r = q("rebar_weight", unit="m", diameter_mm=16, length=6, count=10)
    expected = math.pi / 4 * 16**2 * 1e-6 * 6 * 7850 * 10
    assert float(r.quantity) == pytest.approx(expected, abs=5e-4)
    unit_w = q("rebar_weight", unit="m", diameter_mm=16, length=1, count=1, ).net
    assert float(unit_w) == pytest.approx(1.578, abs=0.001)  # widely tabulated D16 unit weight


def test_steel_plate_exact():
    r = q("steel_plate", unit="mm", length=1000, width=500, thickness=10, count=1)
    assert r.quantity == D("39.250") and D(r.extras["area_m2"]) == D("0.5")


def test_steel_box_exact():
    # 50x50x2: area = 2500 - 46*46 = 384 mm2 ; 384e-6 * 6 m * 7850 = 18.0864 kg
    r = q("steel_box_hollow", unit="mm", width=50, height=50, thickness=2, length=6000, count=1)
    assert r.quantity == D("18.086")
    assert q("steel_box_hollow", unit="mm", width=50, height=50, thickness=2, length=6000, count=3).quantity == D("54.259")


def test_section_by_weight_and_simple_modules():
    assert q("steel_section_by_weight", unit="m", length=6, unit_weight_kg_m="12.5", count=2).quantity == D("150.000")
    assert q("length_total", unit="mm", length=2500, count=4).quantity == D("10.000")
    assert q("area_rect", unit="m", length=2, width=1.5, count=3).quantity == D("9.000")
    assert q("count_items", count=7).quantity == D("7.000")


def test_custom_rules_density_and_decimals():
    rules = MeasurementRules(decimals=1, steel_density=D("7850"))
    r = calculate("steel_plate", dict(unit="mm", length=1000, width=500, thickness=10, count=1), rules=rules)
    assert r.quantity == D("39.3") and r.inputs["steel_density"] == D("7850")


@pytest.mark.parametrize("params,code", [
    (dict(length=1, width=1, height=1, count=1), "unit_missing"),
    (dict(unit="inch", length=1, width=1, height=1, count=1), "unit_missing"),
    (dict(unit="m", length=1, width=1, count=1), "input_missing"),
    (dict(unit="m", length=0, width=1, height=1, count=1), "non_positive"),
    (dict(unit="m", length=-1, width=1, height=1, count=1), "non_positive"),
    (dict(unit="m", length=1, width=1, height=1, count="1.5"), "count_not_integer"),
    (dict(unit="m", length="abc", width=1, height=1, count=1), "invalid_number"),
    (dict(unit="m", length="NaN", width=1, height=1, count=1), "invalid_number"),
    (dict(unit="m", length=True, width=1, height=1, count=1), "invalid_number"),
])
def test_input_errors(params, code):
    with pytest.raises(CalcError) as e:
        calculate("concrete_prism", params)
    assert e.value.code == code


def test_waste_bounds_unknown_module_and_geometry():
    with pytest.raises(CalcError) as e:
        q("count_items", "1.5", count=1)
    assert e.value.code == "invalid_waste"
    with pytest.raises(CalcError):
        q("count_items", "-0.1", count=1)
    with pytest.raises(CalcError) as e:
        calculate("nope", {})
    assert e.value.code == "unknown_module"
    with pytest.raises(CalcError) as e:
        q("steel_box_hollow", unit="mm", width=50, height=50, thickness=25, length=1000, count=1)
    assert e.value.code == "invalid_geometry"


def test_waste_default_is_zero_never_implicit():
    assert calculate("count_items", {"count": 10}).quantity == D("10.000")


def test_scale_requires_confirmation():
    assert real_length_from_paper(D("25"), 100, True) == D("2500")
    with pytest.raises(CalcError) as e:
        real_length_from_paper(D("25"), 100, False)
    assert e.value.code == "scale_unconfirmed"


def test_registry_listing_and_formula_text():
    assert {m["key"] for m in list_modules()} == set(MODULES)
    r = q("steel_plate", "0.05", unit="mm", length=1000, width=500, thickness=10, count=1)
    assert "1000 × 500" in r.formula_text and "(1 + 0.05)" in r.formula_text
