"""Phase 5A: vector geometry extraction + coordinate system (synthetic PDFs with known geometry)."""
from decimal import Decimal as D

import pymupdf
import pytest

from app.geometry.coords import PT_TO_MM, paper_mm, real_m, real_mm
from app.geometry.primitives import axis_runs, extract_page_geometry, polyline_length, shoelace_area
from app.takeoff.engine import CalcError


def page(w=600, h=400):
    doc = pymupdf.open()
    return doc, doc.new_page(width=w, height=h)


def geom(p, kind="vector"):
    return extract_page_geometry(p, 1, kind)


def by_kind(g, kind):
    return [x for x in g.primitives if x.kind == kind]


def test_stroked_line_exact_decimal_length():
    doc, p = page()
    p.draw_line((100, 100), (400, 500), width=0.5)  # 3-4-5 triangle: 300 x 400 -> 500
    ln = by_kind(geom(p), "line")[0]
    assert ln.length_pt == D("500") and ln.points == [(D("100.00"), D("100.00")), (D("400.00"), D("500.00"))]
    assert ln.derived_from is None and ln.stroke_width == 0.5


def test_polyline_polygon_rect_and_fill_region():
    doc, p = page()
    p.draw_polyline([(10, 10), (110, 10), (110, 60)])                       # open: 100 + 50
    p.draw_polyline([(200, 200), (300, 200), (300, 300)], closePath=True)    # right triangle legs 100
    p.draw_rect(pymupdf.Rect(400, 50, 500, 100), width=1)                    # stroked rect 100 x 50
    p.draw_rect(pymupdf.Rect(400, 150, 500, 250), color=None, fill=(0.5, 0.5, 0.5))  # filled area
    g = geom(p)
    pl = by_kind(g, "polyline")[0]
    assert pl.length_pt == D("150") and not pl.closed
    tri = by_kind(g, "polygon")[0]
    assert tri.closed and tri.area_pt2 == D("5000") and tri.length_pt == D(200) + D(20000).sqrt()
    rect = by_kind(g, "rect")[0]
    assert rect.area_pt2 == D("5000") and rect.length_pt == D("300")
    fill = by_kind(g, "fill_region")[0]
    assert fill.area_pt2 == D("10000") and fill.fill_color == "#808080"


def test_filled_hairline_rectangles_become_lines():
    # Phase 4.1 real-document finding: office/plotter PDFs draw borders as thin filled rectangles
    doc, p = page()
    p.draw_rect(pymupdf.Rect(100, 200, 400, 200.6), color=None, fill=(0, 0, 0))   # horizontal 0.6 pt
    p.draw_rect(pymupdf.Rect(50, 20, 50.12, 320), color=None, fill=(0, 0, 0))     # vertical 0.12 pt
    p.draw_rect(pymupdf.Rect(300, 300, 301.4, 302), color=None, fill=(0, 0, 0))   # small square-ish: not a line
    g = geom(p)
    lines = by_kind(g, "line")
    assert len(lines) == 2 and all(x.derived_from == "filled_hairline_rect" for x in lines)
    h = next(x for x in lines if x.points[0][1] == x.points[1][1])
    assert h.points == [(D("100.00"), D("200.30")), (D("400.00"), D("200.30"))] and h.length_pt == D("300") and h.stroke_width == 0.6
    assert g.stats["derived_hairlines"] == 2 and len(by_kind(g, "fill_region")) == 1


def test_circle_and_curve():
    doc, p = page()
    p.draw_circle((300, 200), 50)
    p.draw_bezier((10, 300), (60, 250), (110, 350), (160, 300))
    g = geom(p)
    c = by_kind(g, "circle")[0]
    assert D(c.extra["radius_pt"]) == D("50.00") and abs(c.length_pt - D("314.159")) < D("0.01")
    cv = by_kind(g, "curve")[0]
    assert cv.approximate and D("150") < cv.length_pt < D("175")


def test_rotation_and_cropbox_give_display_coordinates():
    doc, p = page()
    p.draw_line((100, 100), (300, 100))
    p.set_cropbox(pymupdf.Rect(50, 50, 550, 350))
    g = geom(p)
    assert by_kind(g, "line")[0].points == [(D("50.00"), D("50.00")), (D("250.00"), D("50.00"))]
    assert g.frame.cropbox == (50.0, 50.0, 550.0, 350.0) and (g.frame.width_pt, g.frame.height_pt) == (500.0, 300.0)
    p.set_rotation(90)
    g = geom(p)
    ln = by_kind(g, "line")[0]
    assert (g.frame.width_pt, g.frame.height_pt) == (300.0, 500.0) and ln.points == [(D("250.00"), D("50.00")), (D("250.00"), D("250.00"))]
    assert ln.length_pt == D("200") and "outside_page" not in ln.flags


def test_duplicates_and_collinear_overlaps_are_flagged_not_removed():
    doc, p = page()
    p.draw_line((10, 10), (200, 10))
    p.draw_line((200, 10), (10, 10))       # same line, reversed: duplicate
    p.draw_line((150, 10.2), (300, 10.2))  # collinear overlap 150..200
    p.draw_line((10, 50), (100, 50))
    p.draw_line((101, 50), (190, 50))      # touching but not overlapping
    g = geom(p)
    lines = by_kind(g, "line")
    assert len(lines) == 5
    dup = [x for x in lines if x.duplicate_of is not None]
    assert len(dup) == 1 and "duplicate_geometry" in dup[0].flags
    over = [x for x in lines if x.overlaps]
    assert len(over) == 2 and all("collinear_overlap" in x.flags for x in over)
    runs = axis_runs(g.primitives)
    joined = next(r for r in runs if r["pos"] == D("50.00"))
    assert joined["length_pt"] == D("180") and len(joined["members"]) == 2  # 10..190 with a 1 pt gap


def test_raster_page_has_no_fake_geometry():
    doc, p = page()
    p.draw_line((0, 0), (100, 100))
    g = geom(p, kind="scanned")
    assert g.status == "raster_only" and g.primitives == [] and "raster_page_no_vector_geometry" in g.warnings
    doc2, empty = page()
    assert geom(empty).status == "no_vector_geometry"


def test_coordinate_conversion_is_exact_and_needs_confirmed_scale():
    assert paper_mm(D("72")) == D("25.4") and PT_TO_MM * 72 == D("25.4")
    assert real_mm(D("72"), 100, "confirmed") == D("2540")
    assert real_m(D("72"), 100, "confirmed") == D("2.540")
    for status, ratio in (("unverified", 100), ("not_to_scale", None), ("confirmed", None), ("nts_declared", 50)):
        with pytest.raises(CalcError) as e:
            real_m(D("72"), ratio, status)
        assert e.value.code == "scale_unconfirmed"


def test_pure_measurement_helpers():
    sq = [(D(0), D(0)), (D(10), D(0)), (D(10), D(10)), (D(0), D(10))]
    assert polyline_length(sq, closed=True) == D(40) and shoelace_area(sq) == D(100)
