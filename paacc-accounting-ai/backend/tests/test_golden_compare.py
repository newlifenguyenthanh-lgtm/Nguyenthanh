"""Unit tests of the golden-dataset comparator on synthetic data (no confidential material)."""
from tools.golden_compare import compare


def dim(id_, page, text, values, unit=None, typ="section", flags=None):
    return {"id": id_, "page_no": page, "kind": "dimension", "text": text, "source": "analysis",
            "data": {"type": typ, "values": values, "unit": unit, "flags": flags or []}}


def run(items, pages=None, boq=None):
    return {"code_commit": "test", "steps": {}, "items": items, "drawing": {"pages": pages or [{"page_no": 1, "kind": "vector",
            "drawing_number": None, "title": None, "revision": None, "scale_candidates": [], "units_candidates": []}]},
            "boq_generated": {"items": boq or []}}


EXP = {"document": {"file": "x.pdf"}, "pages": [{"page_no": 1, "kind": "vector", "drawing_number": None, "title": None,
       "revision": None, "scale_ratio": None, "units": None}],
       "dimensions": [{"page": 1, "raw": "L=5150mm", "values": ["5150"], "unit": "mm", "kind": "labeled"},
                      {"page": 1, "raw": "D34x3mm", "values": ["34", "3"], "unit": "mm", "kind": "round"},
                      {"page": 1, "raw": "L=6.100mm", "status": "ambiguous"},
                      {"page": 1, "raw": "L=1,89mm", "status": "requires_engineer"}],
       "not_dimensions": [{"page": 1, "raw": "3M", "reason": "brand"}],
       "materials": [{"page": 1, "raw": "S.509", "category": "traffic_sign"}],
       "boq_rows": [{"page": 1, "group": "1", "description": "Biển tròn D1.4m", "unit": "cái", "quantity": "2.00"},
                    {"page": 1, "group": "1", "description": "Bu lông D20x180mm", "unit": "cái", "quantity": "1452.00"}],
       "duplicates": [{"page": 1, "description": "Bu lông D20x180mm", "quantity": "1452.00", "expect": "flag_component_of_parent"}]}


def test_classification_and_verified_denominators():
    items = [dim("a", 1, "L=5150mm", ["5150"], "mm", "labeled"),
             dim("b", 1, "34x3mm", ["34", "3"], "mm"),                  # partial (lost the D / round semantics)
             dim("c", 1, "L=6.100mm", [None], "mm", "labeled", ["ambiguous_number"]),
             dim("d", 1, "L=1,89mm", ["1.89"], "mm", "labeled"),        # silently accepted -> INCORRECT
             dim("e", 1, "3M", ["3"], "m", "value_with_unit"),           # trap hit -> INCORRECT, not consumed by D34x3mm
             dim("f", 1, "726,00", ["726.00"], None, "bare_number")]     # unmatched -> false positive
    boq = [{"id": "1", "page_no": 1, "description": "Dòng 1", "quantity": "2.0000", "unit": "cái", "category": "other", "flags": [],
            "module": None, "group_path": []},
           {"id": "2", "page_no": 1, "description": "Bu lông D20x180mm", "quantity": "1452.0000", "unit": "cái", "category": "guardrail",
            "flags": [{"code": "component_of_parent"}], "module": None, "group_path": [{"code": "1", "title": "x"}]}]
    r = compare(EXP, run(items, boq=boq))
    st = {x["raw"]: x["status"] for x in r["dimensions"]["rows"]}
    assert st == {"L=5150mm": "CORRECT", "D34x3mm": "PARTIALLY_CORRECT", "L=6.100mm": "CORRECT", "L=1,89mm": "INCORRECT"}
    assert r["dimensions"]["false_positive_traps"][0]["status"] == "INCORRECT"
    assert [f["text"] for f in r["dimensions"]["false_positives"]] == ["726,00"]
    assert r["summary"]["dimensions"] == {"correct": 2, "total": 4, "accuracy_pct": 50.0}
    assert r["metadata"]["accuracy_pct"] == 100.0
    assert r["materials"]["counts"] == {"MISSING": 1} and r["summary"]["materials"]["accuracy_pct"] == 0.0
    assert [x["status"] for x in r["boq"]["rows"]] == ["PARTIALLY_CORRECT", "CORRECT"]
    assert r["boq"]["group_context"]["counts"] == {"INCORRECT": 1, "CORRECT": 1}
    assert r["duplicates"]["counts"] == {"CORRECT": 1}


def test_false_scale_is_incorrect_and_empty_denominator_has_no_percentage():
    pages = [{"page_no": 1, "kind": "vector", "drawing_number": None, "title": None, "revision": None,
              "scale_candidates": [{"ratio": 2}], "units_candidates": []}]
    r = compare({**EXP, "dimensions": [], "materials": [], "boq_rows": [], "duplicates": []}, run([], pages))
    assert next(x for x in r["metadata"]["rows"] if x["field"] == "scale")["status"] == "INCORRECT"
    assert r["summary"]["dimensions"]["accuracy_pct"] is None and r["summary"]["boq"]["accuracy_pct"] is None
