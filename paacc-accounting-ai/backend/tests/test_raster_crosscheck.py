"""Phase 5A: the independent raster channel used to validate vector geometry (synthetic PDF, known lines)."""
from decimal import Decimal as D

import pymupdf

from app.geometry.primitives import axis_runs, extract_page_geometry
from tests.test_golden_compare import EXP, run
from tools.golden_compare import compare
from tools.raster_lines import match_axis_lines, raster_axis_lines


def ruled_pdf():
    doc = pymupdf.open()
    p = doc.new_page(width=400, height=300)
    for y in (50, 80, 110):  # three table rules drawn cell by cell as hairline filled rectangles (like office PDFs)
        for x0, x1 in ((50, 150), (150.6, 350)):
            p.draw_rect(pymupdf.Rect(x0, y, x1, y + 0.12), color=None, fill=(0, 0, 0))
    p.draw_line((50, 50), (50, 110), width=0.6)
    p.insert_text((60, 70), "Text glyphs are not lines", fontsize=9)
    return doc.tobytes(), doc


def vector_runs(doc):
    g = extract_page_geometry(doc[0], 1, "vector")
    return [{"axis": r["axis"], "pos": float(r["pos"]), "start": float(r["start"]), "end": float(r["end"])}
            for r in axis_runs(g.primitives, min_len=D(15))]


def test_raster_channel_agrees_with_vector_runs():
    data, doc = ruled_pdf()
    vec = vector_runs(doc)
    assert len(vec) == 4  # 3 merged horizontal rules (50..350) + 1 vertical
    r = raster_axis_lines(data, 1)
    m = match_axis_lines(vec, r["horizontal"] + r["vertical"])
    assert m["matched"] == 4 and m["vector_only"] == [] and m["raster_only"] == []  # 0.12 pt hairlines found, glyphs ignored


def test_comparator_scores_geometry_against_expected_raster_lines():
    data, doc = ruled_pdf()
    r = raster_axis_lines(data, 1)
    lines = r["horizontal"] + r["vertical"] + [{"axis": "h", "pos": 250.0, "start": 10.0, "end": 60.0, "excluded": "image"}]
    expected = {**EXP, "dimensions": [], "materials": [], "boq_rows": [], "duplicates": [],
                "geometry": {"pages": [{"page_no": 1, "axis_lines": lines}]}}
    res = run([])
    res["geometry_axis_runs"] = {"1": vector_runs(doc)[:3]}  # one vector run missing
    out = compare(expected, res)
    assert out["geometry"]["total"] == 4 and out["summary"]["geometry"]["correct"] == 3
    assert len(out["geometry"]["rows"][0]["missing"]) == 1
