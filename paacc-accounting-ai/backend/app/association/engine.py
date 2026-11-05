"""Phase 5C – deterministic text ↔ geometry association (pure; no LLM, no measurement arithmetic here).

Pipeline: coarse spatial candidates (uniform grid index over geometry bboxes, never text × all geometry)
-> fine geometric scoring (distance, orientation, projection overlap, bbox relation)
-> semantic compatibility (text type ↔ geometry kind) -> weighted confidence -> ranking -> status.
Scores are heuristics in [0,1] (floats); quantities/lengths are never computed here.
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field

ASSOC_FOR = {"LENGTH": "DIMENSION_OF", "DIMENSION": "DIMENSION_OF", "AREA": "DIMENSION_OF", "COUNT": "DIMENSION_OF",
             "CHAINAGE": "CHAINAGE_FOR", "LABEL": "LABEL_OF", "MATERIAL": "MATERIAL_OF", "SPECIFICATION": "MATERIAL_OF",
             "NOTE": "NOTE_FOR", "DETAIL_REFERENCE": "REFERENCE_TO"}
# text types never associated with drawing geometry
EXCLUDED_TYPES = {"TABLE", "TITLE", "REVISION", "SCALE", "OTHER", "UNKNOWN"}
SEMANTIC = {  # association type -> geometry kind -> compatibility
    "DIMENSION_OF": {"line": 1.0, "polyline": 1.0, "curve": 0.8, "rect": 0.6, "polygon": 0.6, "circle": 0.4},
    "CHAINAGE_FOR": {"line": 0.9, "polyline": 1.0, "curve": 0.8, "rect": 0.2, "polygon": 0.2},
    "LABEL_OF": {"line": 0.6, "polyline": 0.8, "curve": 0.6, "rect": 0.8, "polygon": 0.8, "circle": 0.6, "fill_region": 0.6},
    "MATERIAL_OF": {"line": 0.6, "polyline": 0.7, "curve": 0.6, "rect": 0.8, "polygon": 0.8, "circle": 0.6, "fill_region": 0.7},
    "NOTE_FOR": {"line": 0.4, "polyline": 0.4, "rect": 0.5, "polygon": 0.5, "circle": 0.4, "fill_region": 0.4},
    "REFERENCE_TO": {"circle": 1.0, "polygon": 0.6, "rect": 0.6},
}
WEIGHTS = {  # distance, orientation, projection, semantic
    # chainage labels mark a POINT of the route (often at a segment end): projection says little, orientation more
    "DIMENSION_OF": (0.35, 0.25, 0.25, 0.15), "CHAINAGE_FOR": (0.45, 0.20, 0.05, 0.30),
    "LABEL_OF": (0.55, 0.05, 0.15, 0.25), "MATERIAL_OF": (0.55, 0.05, 0.15, 0.25),
    "NOTE_FOR": (0.60, 0.0, 0.15, 0.25), "REFERENCE_TO": (0.65, 0.0, 0.0, 0.35),
}


@dataclass
class Params:
    auto_threshold: float = 0.90
    review_threshold: float = 0.70
    margin: float = 0.10  # #1 must beat #2 by this much, otherwise AMBIGUOUS
    min_keep: float = 0.20
    top_k: int = 3
    radius_factor: float = 4.0  # search radius = factor x font size, clamped
    min_radius: float = 20.0
    max_radius: float = 80.0
    cell: float = 64.0


@dataclass
class TextB:
    id: str
    text_type: str
    normalized: str
    bbox: tuple[float, float, float, float]
    rotation_deg: float = 0.0
    font_size: float = 10.0
    flags: list[str] = field(default_factory=list)

    @property
    def center(self) -> tuple[float, float]:
        return (self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2


@dataclass
class GeoP:
    id: str
    kind: str
    points: list[tuple[float, float]]
    closed: bool
    bbox: tuple[float, float, float, float]


@dataclass
class Candidate:
    text_id: str
    geometry_id: str
    association_type: str
    distance: float
    angle_difference: float | None
    overlap_ratio: float
    orientation_match: bool
    semantic_match: float
    relation: str
    confidence: float
    rank: int = 0
    status: str = "CANDIDATE"
    reason: str = ""
    duplicate_of_text: str | None = None
    components: dict = field(default_factory=dict)


class GridIndex:
    """Uniform grid over bboxes: query cost ~ number of nearby objects, not all objects."""
    def __init__(self, items: list[GeoP], cell: float):
        self.cell, self.cells, self.items = cell, defaultdict(list), {g.id: g for g in items}
        for g in items:
            for k in self._keys(g.bbox):
                self.cells[k].append(g.id)

    def _keys(self, b):
        c = self.cell
        for ix in range(int(math.floor(b[0] / c)), int(math.floor(b[2] / c)) + 1):
            for iy in range(int(math.floor(b[1] / c)), int(math.floor(b[3] / c)) + 1):
                yield ix, iy

    def query(self, b) -> list[GeoP]:
        seen = {gid for k in self._keys(b) for gid in self.cells.get(k, ())}
        return [self.items[g] for g in seen]


def _segments(g: GeoP):
    pts = g.points
    segs = list(zip(pts, pts[1:]))
    if g.closed and len(pts) > 2:
        segs.append((pts[-1], pts[0]))
    return segs or [(pts[0], pts[0])]


def _point_seg(p, a, b):
    ax, ay, bx, by = *a, *b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(p[0] - qx, p[1] - qy), t


def _inside(p, g: GeoP) -> bool:
    if not g.closed or len(g.points) < 3:
        return False
    x, y, inside = p[0], p[1], False
    pts = g.points
    for i in range(len(pts)):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % len(pts)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def _seg_cross(p1, p2, q1, q2) -> bool:
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return o(p1, p2, q1) * o(p1, p2, q2) < 0 and o(q1, q2, p1) * o(q1, q2, p2) < 0


def _rect_seg(r, a, b) -> float:
    """Distance between an axis-aligned text bbox and a segment (0 when they touch/cross)."""
    x0, y0, x1, y1 = r
    if any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in (a, b)):
        return 0.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    if any(_seg_cross(a, b, e0, e1) for e0, e1 in edges):
        return 0.0
    d1 = min(_point_seg(c, a, b)[0] for c in corners)
    d2 = min(math.hypot(max(x0 - p[0], 0, p[0] - x1), max(y0 - p[1], 0, p[1] - y1)) for p in (a, b))
    return min(d1, d2)


def geometric(t: TextB, g: GeoP) -> dict:
    """Distance is measured from the text BOX (not its centre) to the nearest segment; direction from that segment."""
    c = t.center
    segs = _segments(g)
    d, a, b = min(((_rect_seg(t.bbox, a, b), a, b) for a, b in segs), key=lambda x: x[0])
    tparam = _point_seg(c, a, b)[1]
    if _inside(c, g):
        d = 0.0
    seg_angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180 if a != b else None
    text_angle = t.rotation_deg % 180
    ang = None if seg_angle is None else min(abs(seg_angle - text_angle), 180 - abs(seg_angle - text_angle))
    # projection of the text's extent onto the segment direction
    overlap = 0.0
    if a != b:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        corners = [(t.bbox[0], t.bbox[1]), (t.bbox[2], t.bbox[1]), (t.bbox[0], t.bbox[3]), (t.bbox[2], t.bbox[3])]
        proj = [((x - a[0]) * ux + (y - a[1]) * uy) for x, y in corners]
        lo, hi = min(proj), max(proj)
        if hi > lo:
            overlap = max(0.0, min(hi, L) - max(lo, 0.0)) / (hi - lo)
    gx0, gy0, gx1, gy1 = g.bbox
    if gx0 <= c[0] <= gx1 and gy0 <= c[1] <= gy1:
        rel = "inside"
    elif c[1] < gy0:
        rel = "above"
    elif c[1] > gy1:
        rel = "below"
    else:
        rel = "left" if c[0] < gx0 else "right"
    return {"distance": d, "angle": ang, "overlap": overlap, "relation": rel, "t": tparam}


def score(t: TextB, g: GeoP, atype: str, radius: float) -> Candidate | None:
    sem = SEMANTIC.get(atype, {}).get(g.kind, 0.0)
    if sem == 0.0:
        return None
    m = geometric(t, g)
    if m["distance"] > radius:
        return None
    w_d, w_o, w_p, w_s = WEIGHTS[atype]
    s_d = 1 - m["distance"] / radius
    s_o = 1 - min(m["angle"], 90) / 90 if m["angle"] is not None else 0.5
    s_p = m["overlap"]
    conf = w_d * s_d + w_o * s_o + w_p * s_p + w_s * sem
    return Candidate(t.id, g.id, atype, round(m["distance"], 2), None if m["angle"] is None else round(m["angle"], 1),
                     round(s_p, 3), m["angle"] is not None and m["angle"] <= 10, sem, m["relation"], round(conf, 3),
                     components={"distance": round(s_d, 3), "orientation": round(s_o, 3), "projection": round(s_p, 3),
                                 "semantic": sem, "radius_pt": round(radius, 1)})


def associate(texts: list[TextB], geoms: list[GeoP], params: Params | None = None,
              excluded_regions: list[tuple[float, float, float, float]] | None = None) -> list[Candidate]:
    p = params or Params()
    excluded_regions = excluded_regions or []

    def in_excluded(b):
        return any(r[0] <= b[0] and r[1] <= b[1] and b[2] <= r[2] and b[3] <= r[3] for r in excluded_regions)

    usable = [g for g in geoms if not in_excluded(g.bbox)]  # table rules / title-block frame are not drawing objects
    index = GridIndex(usable, p.cell)
    out: list[Candidate] = []
    for t in texts:
        atype = ASSOC_FOR.get(t.text_type)
        if atype is None or t.text_type in EXCLUDED_TYPES or in_excluded(t.bbox):
            continue
        radius = max(p.min_radius, min(p.max_radius, p.radius_factor * t.font_size))
        c = t.center
        window = (c[0] - radius, c[1] - radius, c[0] + radius, c[1] + radius)
        cands = [x for x in (score(t, g, atype, radius) for g in index.query(window)) if x and x.confidence >= p.min_keep]
        cands.sort(key=lambda x: (-x.confidence, x.distance, x.geometry_id))
        cands = cands[:p.top_k]
        for r, x in enumerate(cands, start=1):
            x.rank = r
        if cands:
            top = cands[0]
            second = cands[1].confidence if len(cands) > 1 else None
            if second is not None and top.confidence - second < p.margin:
                for x in cands[:2]:
                    x.status, x.reason = "AMBIGUOUS", f"Hai ứng viên điểm gần nhau ({top.confidence} / {second}) – cần kỹ sư chọn"
            elif top.confidence >= p.auto_threshold:
                top.status, top.reason = "CANDIDATE", "Điểm cao (auto candidate) – vẫn cần kỹ sư xác nhận"
            elif top.confidence >= p.review_threshold:
                top.status, top.reason = "REVIEW_REQUIRED", "Điểm trung bình – nên kiểm tra"
            else:
                top.status, top.reason = "AMBIGUOUS", "Điểm thấp – không tự gán"
            for x in cands[1:]:
                if x.status != "AMBIGUOUS":
                    x.status, x.reason = "CANDIDATE", f"Phương án thay thế hạng {x.rank}"
            if "ambiguous_number" in t.flags or "unit_case_ambiguous" in t.flags or "ENCODING_UNKNOWN" in t.flags:
                top.status, top.reason = "AMBIGUOUS", "Giá trị/chữ mơ hồ (" + ", ".join(t.flags) + ") – không tự gán"
        out.extend(cands)
    _duplicate_context(texts, out)
    return out


def _duplicate_context(texts: list[TextB], cands: list[Candidate]) -> None:
    """Same normalised text -> same geometry from several text blocks: one primary, the others reference it."""
    by_text = {t.id: t for t in texts}
    groups: dict[tuple, list[Candidate]] = defaultdict(list)
    for c in cands:
        if c.rank == 1:
            groups[(by_text[c.text_id].normalized.upper(), c.association_type, c.geometry_id)].append(c)
    for members in groups.values():
        if len(members) > 1:
            members.sort(key=lambda x: (-x.confidence, x.distance))
            for dup in members[1:]:
                dup.duplicate_of_text = members[0].text_id
                dup.reason = (dup.reason + "; " if dup.reason else "") + "Chữ lặp lại cho cùng hình học – không tạo phép đo riêng"
