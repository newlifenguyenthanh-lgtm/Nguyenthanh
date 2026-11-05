"""Regression gate on the confidential golden dataset (skipped unless PAACC_GOLDEN_DIR points at it).

For every expected file it runs the full pipeline on the matching PDF (isolated subprocess, temporary DB)
and fails if any category scores below the floor recorded in the document's manifest
(`regression_floor`: {"dimensions": n_correct, ...}).
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.golden_compare import compare

GOLDEN = Path(os.environ.get("PAACC_GOLDEN_DIR", "")) if os.environ.get("PAACC_GOLDEN_DIR") else None
BACKEND = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not GOLDEN or not any((GOLDEN / "expected").glob("*.expected.json")),
                                reason="golden dataset not supplied (set PAACC_GOLDEN_DIR)")


def _cases():
    if not GOLDEN:
        return []
    return sorted((GOLDEN / "expected").glob("*.expected.json"))


@pytest.mark.parametrize("expected_path", _cases(), ids=lambda p: p.name[:12])
def test_golden_document_does_not_regress(expected_path, tmp_path):
    expected = json.loads(expected_path.read_text())
    sha = expected["document"]["sha256"]
    pdf = next((p for p in (GOLDEN / "drawings").glob("*.pdf") if hashlib.sha256(p.read_bytes()).hexdigest() == sha), None)
    assert pdf, f"PDF with sha256 {sha[:12]} not found in drawings/"
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / pdf.name).write_bytes(pdf.read_bytes())
    subprocess.run([sys.executable, "-m", "tools.golden_run", "--input", str(inp), "--out", str(tmp_path), "--label", "gate"],
                   cwd=BACKEND, check=True, capture_output=True, timeout=900)
    run = json.loads((tmp_path / f"{pdf.stem}.gate.json").read_text())
    result = compare(expected, run)
    manifest = GOLDEN / "manifests" / f"{sha[:12]}.manifest.json"
    floor = json.loads(manifest.read_text()).get("regression_floor", {}) if manifest.exists() else {}
    for category, minimum in floor.items():
        got = result["summary"][category]["correct"]
        assert got >= minimum, f"{category}: {got} correct < floor {minimum}"
    assert result["pipeline_steps"]["process"]["status"] == "processed"
