"""Phase 5D – symbol pattern matching over vector primitives (no computer vision).

A pattern is DATA (component_symbol_patterns row): pattern_type + parameters + tolerance + confidence_weight.
Supported pattern types: circle, rectangle, line, parallel_lines, cross, arrow, leader, filled_region, circle_with_stem.
"repeated geometry" is handled by repetition.py over the symbols found here.
"""
import math
from dataclasses import dataclass, field

from app.components import spatial as S

PATTERN_TYPES = ("circle", "rectangle", "line", "parallel_lines", "cross", "arrow", "leader", "filled_region", "circle_with_stem")


@dataclass
class Pattern:
    id: str
    component_type: str | None
    pattern_type: str
    parameters: dict
    tolerance: dict
    confidence_weight: float


@dataclass
class Symbol:
    pattern_id: str
    pattern_type: str
    component_type: str | None
    geometry_ids: list[str]
    bbox: S.BBox
    weight: float
    size: float  # characteristic size (pt): circle diameter, rectangle long side, line length ...
    attrs: dict = field(default_factory=dict)
    anchor_id: str = ""  # the one geometry that stands for this symbol in counts (circle of a post, rect of a pit ...)

    @property
    def centre(self) -> S.Pt:
        return (self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2


def _union(*bs):
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def _is_rect(g: S.Geo, angle_tol: float) -> bool:
    if g.kind == "rect":
        return True
    if g.kind != "polygon" or len(g.points) != 4:
        return False
    segs = g.segments()
    for (a, b), (c, d) in zip(segs, segs[1:] + segs[:1]):
        diff = S.angle_diff(S.angle_of(a, b), S.angle_of(c, d))
        if diff is None or abs(diff - 90) > angle_tol:
            return False
    return True


def _seg_len(g: S.Geo) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in g.segments())


def match(patterns: list[Pattern], geoms: list[S.Geo], grid: S.Grid, texts: list | None = None) -> list[Symbol]:
    """All symbol occurrences of all ACTIVE patterns. texts: [(id, bbox)] for leader detection."""
    out: list[Symbol] = []
    for p in patterns:
        P, T, w = p.parameters, p.tolerance, p.confidence_weight
        if p.pattern_type == "circle":
            for g in geoms:
                if g.kind == "circle" and P.get("min_radius_pt", 0) <= g.size / 2 <= P.get("max_radius_pt", 1e9):
                    out.append(Symbol(p.id, "circle", p.component_type, [g.id], g.bbox, w, g.size, {"radius_pt": g.size / 2}, g.id))
        elif p.pattern_type == "rectangle":
            for g in geoms:
                if _is_rect(g, T.get("angle_deg", 3.0)) and P.get("min_side_pt", 0) <= g.size <= P.get("max_side_pt", 1e9):
                    out.append(Symbol(p.id, "rectangle", p.component_type, [g.id], g.bbox, w, g.size, {}, g.id))
        elif p.pattern_type == "line":
            for g in geoms:
                if g.kind == "line" and _seg_len(g) >= P.get("min_length_pt", 0):
                    out.append(Symbol(p.id, "line", p.component_type, [g.id], g.bbox, w, _seg_len(g), {}, g.id))
        elif p.pattern_type == "filled_region":
            for g in geoms:
                bw, bh = g.bbox[2] - g.bbox[0], g.bbox[3] - g.bbox[1]
                if g.kind == "fill_region" and bw * bh >= P.get("min_area_pt2", 0):
                    out.append(Symbol(p.id, "filled_region", p.component_type, [g.id], g.bbox, w, g.size, {}, g.id))
        elif p.pattern_type == "arrow":
            for g in geoms:
                if g.closed and len(g.points) == 3 and g.size <= P.get("max_size_pt", 8.0):
                    out.append(Symbol(p.id, "arrow", p.component_type, [g.id], g.bbox, w, g.size, {}, g.id))
        elif p.pattern_type == "circle_with_stem":
            tol, ang = T.get("touch_pt", 2.0), T.get("angle_deg", 10.0)
            for g in geoms:
                if g.kind != "circle" or not (P.get("min_radius_pt", 0) <= g.size / 2 <= P.get("max_radius_pt", 1e9)):
                    continue
                for h in grid.query(g.bbox, pad=tol):
                    if h.id == g.id or h.kind != "line" or _seg_len(h) < P.get("min_stem_pt", 0):
                        continue
                    a = S.main_angle(h)
                    if P.get("orientation") == "vertical" and (a is None or abs(a - 90) > ang):
                        continue
                    if S.connected(h, g, tol):
                        out.append(Symbol(p.id, "circle_with_stem", p.component_type, [g.id, h.id], _union(g.bbox, h.bbox), w, g.size,
                                          {"radius_pt": g.size / 2, "stem_pt": _seg_len(h)}, g.id))
                        break
        elif p.pattern_type == "parallel_lines":
            ang, lo, hi, ov = T.get("angle_deg", 3.0), P.get("min_gap_pt", 0), P.get("max_gap_pt", 20), P.get("min_overlap", 0.5)
            lines = [g for g in geoms if g.kind == "line"]
            seen = set()
            for g in lines:
                for h in grid.query(g.bbox, pad=hi):
                    if h.kind != "line" or h.id <= g.id or (g.id, h.id) in seen:
                        continue
                    diff = S.angle_diff(S.main_angle(g), S.main_angle(h))
                    if diff is None or diff > ang:
                        continue
                    gap = S.point_geo(h.centre, g)[0]
                    a, b = g.points[0], g.points[-1]
                    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                    pr = sorted(((x - a[0]) * ux + (y - a[1]) * uy) for x, y in h.points)
                    overlap = max(0.0, min(pr[-1], L) - max(pr[0], 0.0)) / min(L, (pr[-1] - pr[0]) or L)
                    perp = min(abs((x - a[0]) * -uy + (y - a[1]) * ux) for x, y in h.points)
                    if lo <= perp <= hi and overlap >= ov:
                        seen.add((g.id, h.id))
                        out.append(Symbol(p.id, "parallel_lines", p.component_type, [g.id, h.id], _union(g.bbox, h.bbox), w, perp,
                                          {"gap_pt": round(perp, 2), "overlap": round(overlap, 3)}, g.id))
        elif p.pattern_type == "cross":
            ang, cr = T.get("angle_deg", 10.0), T.get("centre_rel", 0.2)
            lines = [g for g in geoms if g.kind == "line" and P.get("min_arm_pt", 0) * 2 <= _seg_len(g) <= P.get("max_arm_pt", 1e9) * 2]
            ids = {g.id for g in lines}
            for g in lines:
                for h in grid.query(g.bbox):
                    diff = S.angle_diff(S.main_angle(g), S.main_angle(h))
                    if h.id <= g.id or h.id not in ids or diff is None or abs(diff - 90) > ang:
                        continue
                    if S.intersects(g, h) and math.hypot(g.centre[0] - h.centre[0], g.centre[1] - h.centre[1]) <= cr * max(_seg_len(g), _seg_len(h)):
                        out.append(Symbol(p.id, "cross", p.component_type, [g.id, h.id], _union(g.bbox, h.bbox), w,
                                          max(_seg_len(g), _seg_len(h)), {}, g.id))
        elif p.pattern_type == "leader" and texts:
            tg, gg = P.get("max_text_gap_pt", 4.0), P.get("max_target_gap_pt", 3.0)
            tgrid = S.Grid(texts, bbox=lambda x: x[1], key=lambda x: x[0])  # texts indexed too: never geometry x all texts
            for g in geoms:
                if g.kind not in ("line", "polyline") or g.closed:
                    continue
                e0, e1 = g.points[0], g.points[-1]
                for near, far in ((e0, e1), (e1, e0)):
                    for tid, tb in tgrid.query((near[0], near[1], near[0], near[1]), pad=tg):
                        if S.bbox_gap(tb, (near[0], near[1], near[0], near[1])) > tg:
                            continue
                        for h in grid.query((far[0], far[1], far[0], far[1]), pad=gg):
                            if h.id != g.id and S.point_geo(far, h)[0] <= gg:
                                out.append(Symbol(p.id, "leader", None, [g.id, h.id], _union(g.bbox, h.bbox), w, _seg_len(g),
                                                  {"text_id": tid, "target_id": h.id}, h.id))
    return out
