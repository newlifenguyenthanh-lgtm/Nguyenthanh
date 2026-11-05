"""Phase 5A – vector geometry extraction from PDF pages (read-only, deterministic).

PyMuPDF `page.get_drawings()` path items ('l' line, 'c' cubic Bézier, 're' rectangle, 'qu' quad) are turned into
primitives in DISPLAY space (see coords.py). Lengths/areas are exact Decimal arithmetic on the stored (0.01 pt)
coordinates; Bézier lengths are a fixed-subdivision approximation and flagged as such.

Real-world finding (Phase 4.1 document): office software and many plotters draw table and border lines as
*filled hairline rectangles*, not stroked lines. Those are converted to their centre line and marked
`derived_from = "filled_hairline_rect"` - the original rectangle stays recoverable from the stored width.
Nothing is ever deleted: exact duplicates are linked (`duplicate_of`), collinear overlaps are flagged.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

import pymupdf

from app.geometry.coords import PageFrame, q

HAIRLINE_MAX_PT = Decimal("1.5")  # filled rectangle thinner than this ...
HAIRLINE_MIN_RATIO = Decimal("4")  # ... and at least 4x longer than thick is a drawn line
BEZIER_STEPS = 32
MAX_PRIMITIVES_PER_PAGE = 200_000
AXIS_TOL = Decimal("0.5")
Pt = tuple[Decimal, Decimal]


@dataclass
class Primitive:
    kind: str  # line | polyline | polygon | rect | fill_region | curve | circle
    points: list[Pt]
    closed: bool = False
    length_pt: Decimal | None = None
    area_pt2: Decimal | None = None
    stroke_width: float | None = None
    stroke_color: str | None = None
    fill_color: str | None = None
    layer: str | None = None
    path_index: int = 0
    item_index: int = 0
    derived_from: str | None = None
    approximate: bool = False
    flags: list[str] = field(default_factory=list)
    duplicate_of: int | None = None  # index into the page's primitive list
    overlaps: list[int] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def bbox(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class PageGeometry:
    frame: PageFrame
    primitives: list[Primitive]
    status: str  # extracted | no_vector_geometry | raster_only | too_complex
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _dist(a: Pt, b: Pt) -> Decimal:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2).sqrt()


def polyline_length(pts: list[Pt], closed: bool = False) -> Decimal:
    total = sum((_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)), Decimal(0))
    if closed and len(pts) > 2:
        total += _dist(pts[-1], pts[0])
    return total


def shoelace_area(pts: list[Pt]) -> Decimal:
    s = sum((pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))), Decimal(0))
    return abs(s) / 2


def bezier_points(p0: Pt, p1: Pt, p2: Pt, p3: Pt, steps: int = BEZIER_STEPS) -> list[Pt]:
    out = []
    for i in range(steps + 1):
        t = Decimal(i) / steps
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
        out.append((q(x), q(y)))
    return out


def _color(c) -> str | None:
    if not c:
        return None
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in c[:3])


def _pt(frame: PageFrame, p) -> Pt:
    return frame.to_display(p.x, p.y)


def _rect_points(frame: PageFrame, r) -> list[Pt]:
    return [_pt(frame, pymupdf.Point(x, y)) for x, y in ((r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1))]


def _from_rect(frame: PageFrame, r, path: dict, pi: int, ii: int) -> Primitive:
    pts = _rect_points(frame, r)
    w, h = q(abs(r.x1 - r.x0)), q(abs(r.y1 - r.y0))
    filled_only = path.get("type") == "f"
    common = dict(stroke_color=_color(path.get("color")), fill_color=_color(path.get("fill")), layer=path.get("layer") or None,
                  path_index=pi, item_index=ii)
    thin, long = min(w, h), max(w, h)
    if filled_only and thin <= HAIRLINE_MAX_PT and (thin == 0 or long / thin >= HAIRLINE_MIN_RATIO):
        # a drawn line: centre line along the long axis; thickness kept as stroke width
        cx0, cy0, cx1, cy1 = (r.x0, (r.y0 + r.y1) / 2, r.x1, (r.y0 + r.y1) / 2) if w >= h else ((r.x0 + r.x1) / 2, r.y0, (r.x0 + r.x1) / 2, r.y1)
        a, b = _pt(frame, pymupdf.Point(cx0, cy0)), _pt(frame, pymupdf.Point(cx1, cy1))
        return Primitive("line", [a, b], length_pt=_dist(a, b), stroke_width=float(thin), derived_from="filled_hairline_rect", **common)
    kind = "fill_region" if filled_only else "rect"
    return Primitive(kind, pts, closed=True, length_pt=polyline_length(pts, True), area_pt2=w * h,
                     stroke_width=path.get("width"), **common)


def _circle(points: list[Pt]) -> dict | None:
    """Closed curve whose sampled points are all at the same distance from the bbox centre -> circle."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    rx, ry = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
    if rx <= 0 or abs(rx - ry) > Decimal("0.02") * rx:
        return None
    r = (rx + ry) / 2
    if all(abs(_dist(p, (cx, cy)) - r) <= Decimal("0.01") * r + Decimal("0.02") for p in points):
        return {"center": [str(q(cx)), str(q(cy))], "radius_pt": str(q(r))}
    return None


def _chain(frame: PageFrame, path: dict, pi: int) -> list[Primitive]:
    """Split a path into connected runs of 'l'/'c' segments -> line / polyline / polygon / curve / circle."""
    out: list[Primitive] = []
    run: list[Pt] = []
    run_start_item, has_curve = 0, False

    def flush(closed_hint: bool):
        nonlocal run, has_curve
        if len(run) >= 2:
            closed = closed_hint or (len(run) > 3 and _dist(run[0], run[-1]) <= Decimal("0.05"))
            pts = run[:-1] if closed and _dist(run[0], run[-1]) <= Decimal("0.05") and len(run) > 3 else run
            common = dict(stroke_width=path.get("width"), stroke_color=_color(path.get("color")), fill_color=_color(path.get("fill")),
                          layer=path.get("layer") or None, path_index=pi, item_index=run_start_item)
            if has_curve:
                circ = _circle(pts) if closed else None
                if circ:
                    r = Decimal(circ["radius_pt"])
                    out.append(Primitive("circle", pts, closed=True, length_pt=2 * Decimal("3.14159265358979323846") * r,
                                         area_pt2=Decimal("3.14159265358979323846") * r * r, approximate=False, extra=circ, **common))
                else:
                    out.append(Primitive("curve", pts, closed=closed, length_pt=polyline_length(pts, closed), approximate=True,
                                         area_pt2=shoelace_area(pts) if closed else None, **common))
            elif len(pts) == 2 and not closed:
                out.append(Primitive("line", pts, length_pt=_dist(pts[0], pts[1]), **common))
            else:
                out.append(Primitive("polygon" if closed else "polyline", pts, closed=closed, length_pt=polyline_length(pts, closed),
                                     area_pt2=shoelace_area(pts) if closed else None, **common))
        run, has_curve = [], False

    for ii, it in enumerate(path["items"]):
        op = it[0]
        if op in ("l", "c"):
            start = _pt(frame, it[1])
            if run and _dist(run[-1], start) > Decimal("0.05"):
                flush(False)
            if not run:
                run, run_start_item = [start], ii
            if op == "l":
                run.append(_pt(frame, it[2]))
            else:
                has_curve = True
                run.extend(bezier_points(start, _pt(frame, it[2]), _pt(frame, it[3]), _pt(frame, it[4]))[1:])
        else:
            flush(False)
            if op == "re":
                out.append(_from_rect(frame, it[1], path, pi, ii))
            elif op == "qu":
                quad = it[1]
                pts = [_pt(frame, p) for p in (quad.ul, quad.ur, quad.lr, quad.ll)]
                out.append(Primitive("polygon", pts, closed=True, length_pt=polyline_length(pts, True), area_pt2=shoelace_area(pts),
                                     stroke_width=path.get("width"), stroke_color=_color(path.get("color")),
                                     fill_color=_color(path.get("fill")), layer=path.get("layer") or None, path_index=pi, item_index=ii))
    flush(bool(path.get("closePath")))
    return out


def _dedup_key(p: Primitive) -> tuple:
    pts = [(round(x, 1), round(y, 1)) for x, y in p.points]
    if p.kind == "line":
        pts = sorted(pts)
    return p.kind, tuple(pts)


def mark_duplicates_and_overlaps(prims: list[Primitive]) -> None:
    """Exact duplicates (same geometry drawn twice) -> duplicate_of; collinear overlapping axis-aligned lines -> overlaps.
    Never removes anything: measurements later skip duplicates and require review for overlaps."""
    seen: dict[tuple, int] = {}
    for i, p in enumerate(prims):
        k = _dedup_key(p)
        if k in seen:
            p.duplicate_of = seen[k]
            p.flags.append("duplicate_geometry")
        else:
            seen[k] = i
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for i, p in enumerate(prims):
        if p.kind != "line" or p.duplicate_of is not None:
            continue
        (x0, y0), (x1, y1) = p.points
        if abs(y0 - y1) <= AXIS_TOL:
            buckets[("h", round((y0 + y1) / 2))].append(i)
        elif abs(x0 - x1) <= AXIS_TOL:
            buckets[("v", round((x0 + x1) / 2))].append(i)
    for (axis, _), idx in buckets.items():
        span = lambda p: (min(p.points[0][0], p.points[1][0]), max(p.points[0][0], p.points[1][0])) if axis == "h" else \
            (min(p.points[0][1], p.points[1][1]), max(p.points[0][1], p.points[1][1]))
        line_pos = lambda p: (p.points[0][1] + p.points[1][1]) / 2 if axis == "h" else (p.points[0][0] + p.points[1][0]) / 2
        idx.sort(key=lambda i: span(prims[i])[0])
        for n, i in enumerate(idx):
            a0, a1 = span(prims[i])
            for j in idx[n + 1:]:
                b0, b1 = span(prims[j])
                if b0 >= a1:
                    break
                if abs(line_pos(prims[i]) - line_pos(prims[j])) <= AXIS_TOL and min(a1, b1) - max(a0, b0) > AXIS_TOL:
                    prims[i].overlaps.append(j)
                    prims[j].overlaps.append(i)
    for p in prims:
        if p.overlaps:
            p.flags.append("collinear_overlap")


def extract_page_geometry(page: "pymupdf.Page", page_no: int, page_kind: str) -> PageGeometry:
    frame = PageFrame.of(page, page_no)
    if page_kind == "scanned":
        return PageGeometry(frame, [], "raster_only", ["raster_page_no_vector_geometry"])
    paths = page.get_drawings()
    n_items = sum(len(p["items"]) for p in paths)
    if n_items > MAX_PRIMITIVES_PER_PAGE:
        return PageGeometry(frame, [], "too_complex", [f"vector_items_{n_items}_exceed_limit_{MAX_PRIMITIVES_PER_PAGE}"],
                            {"path_count": len(paths), "item_count": n_items})
    prims: list[Primitive] = []
    for pi, path in enumerate(paths):
        prims.extend(_chain(frame, path, pi))
    warnings = []
    for p in prims:
        if not all(frame.inside(x, y) for x, y in p.points):
            p.flags.append("outside_page")
    mark_duplicates_and_overlaps(prims)
    if not prims:
        warnings.append("no_vector_geometry")
    if page_kind == "mixed":
        warnings.append("raster_content_not_vectorised")
    by_kind: dict[str, int] = defaultdict(int)
    for p in prims:
        by_kind[p.kind] += 1
    stats = {"path_count": len(paths), "item_count": n_items, "by_kind": dict(by_kind),
             "derived_hairlines": sum(1 for p in prims if p.derived_from == "filled_hairline_rect"),
             "duplicates": sum(1 for p in prims if p.duplicate_of is not None),
             "overlapping": sum(1 for p in prims if p.overlaps),
             "layers": sorted({p.layer for p in prims if p.layer})}
    return PageGeometry(frame, prims, "extracted" if prims else "no_vector_geometry", warnings, stats)


def extract_pdf_geometry(data: bytes, page_kinds: dict[int, str]) -> list[PageGeometry]:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [extract_page_geometry(doc[i], i + 1, page_kinds.get(i + 1, "vector")) for i in range(doc.page_count)]


def axis_runs(prims: list[Primitive], gap_tol: Decimal = Decimal("1.5"), min_len: Decimal = Decimal("0")) -> list[dict]:
    """Merges collinear, touching axis-aligned line primitives into continuous runs (a border drawn cell by cell
    becomes one line). Pure analysis view: stored primitives are unchanged; each run lists its member indexes."""
    groups: dict[tuple, list[tuple[Decimal, Decimal, int]]] = defaultdict(list)
    for i, p in enumerate(prims):
        if p.kind != "line" or p.duplicate_of is not None:
            continue
        (x0, y0), (x1, y1) = p.points
        if abs(y0 - y1) <= AXIS_TOL:
            groups[("h", round((y0 + y1) / 2 / AXIS_TOL))].append((min(x0, x1), max(x0, x1), i))
        elif abs(x0 - x1) <= AXIS_TOL:
            groups[("v", round((x0 + x1) / 2 / AXIS_TOL))].append((min(y0, y1), max(y0, y1), i))
    out = []
    for (axis, _), segs in groups.items():
        segs.sort()
        cur = None
        for s, e, i in segs:
            if cur and s - cur["end"] <= gap_tol:
                cur["end"], cur["members"] = max(cur["end"], e), cur["members"] + [i]
            else:
                if cur:
                    out.append(cur)
                cur = {"axis": axis, "start": s, "end": e, "members": [i]}
        out.append(cur)
    for r in out:
        p = prims[r["members"][0]]
        r["pos"] = (p.points[0][1] + p.points[1][1]) / 2 if r["axis"] == "h" else (p.points[0][0] + p.points[1][0]) / 2
        r["length_pt"] = r["end"] - r["start"]
    return sorted((r for r in out if r["length_pt"] >= min_len), key=lambda r: (r["axis"], r["pos"], r["start"]))
