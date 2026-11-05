"""Real-drawing validation harness: behaviour checked on a SYNTHETIC sheet (the harness itself makes no accuracy claim)."""
import json
import subprocess
import sys
from pathlib import Path

from tests import component_helpers as H

BACKEND = Path(__file__).resolve().parents[1]


def _run(tmp_path, *extra):
    pdf = tmp_path / "synthetic_fence.pdf"
    pdf.write_bytes(H.sheet_fence())
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "tools.validate_real_drawing", "--pdf", str(pdf), "--out", str(out), *extra],
                       cwd=BACKEND, capture_output=True, text=True, timeout=600)
    rep = json.loads((out / "synthetic_fence.validation.json").read_text()) if (out / "synthetic_fence.validation.json").exists() else None
    return r, rep, out


def test_without_decisions_nothing_is_confirmed_or_quantified(tmp_path):
    r, rep, out = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert {c["type"] for c in rep["components"]} == {"FENCE", "FENCE_POST"}
    assert all(c["state"] != "CONFIRMED" for c in rep["components"]) and rep["quantities"] == []
    assert rep["result"]["5E-2 Quantity Rules"].startswith("NOT_EXERCISED")
    assert rep["result"]["End-to-end Quantity"] == "NOT_VALIDATED (MANUAL_REFERENCE: NOT_AVAILABLE)"
    md = (out / "synthetic_fence.validation.md").read_text()
    assert "MANUAL_REFERENCE: NOT_AVAILABLE" in md and "REAL DRAWING VALIDATION RESULT" in md and "do not commit" in md


def test_engineer_decisions_and_manual_comparison(tmp_path):
    fp_f, fp_p = "p1:FENCE:80,300,660,300", "p1:FENCE_POST:96,296,644,304"
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps({"reviewer": "TEST", "scale": {"1": 100}, "confirm_components": [fp_f, fp_p],
                               "confirm_measurements_of": [fp_f, fp_p], "parameters": {fp_p: {"unit_length": {
                                   "value": "2.5", "unit": "m", "source_type": "DRAWING_NOTE", "source_reference": "note"}}}}))
    ref = tmp_path / "manual.csv"
    ref.write_text("item,rule_code,unit,quantity\nFence,FENCE.LENGTH,m,20.461\nPosts,FENCE_POST.COUNT,ea,11\n"
                   "Post steel,FENCE_POST.TOTAL_LENGTH,m,25\nFooting,FOOTING,m3,1.2\n")
    r, rep, _ = _run(tmp_path, "--decisions", str(dec), "--manual-ref", str(ref))
    assert r.returncode == 0, r.stderr
    rows = {x["item"]: x["status"] for x in rep["manual_comparison"]["rows"]}
    assert rows == {"Fence": "CORRECT", "Posts": "WRONG", "Post steel": "CORRECT", "Footing": "CANNOT_TAKEOFF"}
    assert rep["result"]["Traceability"] == "PASS" and rep["result"]["End-to-end Quantity"] == "FAIL"
    q = next(x for x in rep["quantities"] if x["rule_code"] == "FENCE_POST.TOTAL_LENGTH")
    assert q["formula_trace"] == "10 × 2.500 m = 25.000 m" and q["provenance"]["drawing"]["page_no"] == 1


def test_unconfirmed_measurements_keep_quantities_in_review(tmp_path):
    fp_f = "p1:FENCE:80,300,660,300"
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps({"reviewer": "TEST", "scale": {"1": 100}, "confirm_components": [fp_f]}))
    ref = tmp_path / "manual.csv"
    ref.write_text("item,rule_code,unit,quantity\nFence,FENCE.LENGTH,m,20.461\n")
    r, rep, _ = _run(tmp_path, "--decisions", str(dec), "--manual-ref", str(ref))
    assert [q["status"] for q in rep["quantities"]] == ["REQUIRES_REVIEW"]
    assert rep["manual_comparison"]["rows"][0]["status"] == "NEEDS_REVIEW"  # never upgraded to CORRECT


def test_refuses_to_write_results_inside_the_repository(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(H.sheet_fence())
    r = subprocess.run([sys.executable, "-m", "tools.validate_real_drawing", "--pdf", str(pdf), "--out", str(BACKEND / "tmp_out")],
                       cwd=BACKEND, capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "Refusing" in r.stderr and not (BACKEND / "tmp_out").exists()
