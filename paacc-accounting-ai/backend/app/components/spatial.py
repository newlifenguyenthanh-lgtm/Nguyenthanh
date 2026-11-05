"""Phase 5D – pure spatial primitives and relationships (floats on DISPLAY pt; heuristics only, never quantities).

Relations: NEAR, ON, INSIDE, INTERSECTS, ALIGNED_WITH, PARALLEL_TO, PERPENDICULAR_TO, CONNECTED_TO, REPEATED_ALONG, BETWEEN.
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field

from app.association.engine import _point_seg, _rect_seg, _seg_cross

RELATIONS = ("NEAR", "ON", "INSIDE", "INTERSECTS", "ALIGNED_WITH", "PARALLEL_TO", "PERPENDICULAR_TO", "CONNECTED_TO",
             "REPEATED_ALONG", "BETWEEN")
Pt = tuple[float, float]
BBox = tuple[float, float, float, float]


@dataclass
class Geo:
    id: str
    kind: str
    points: list[Pt]
    closed: bool
    bbox: BBox
    order: int = 0  # draw order (path_index, item_index) – later = on top
    filled: bool = False
    length_pt: float | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def centre(self) -> Pt:
        return (self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2

    @property
    def size(self) -> float:
        return max(self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1])

    def segments(self) -> list[tuple[Pt, Pt]]:
        pts = self.points
        segs = list(zip(pts, pts[1:]))
        if self.closed and len(pts) > 2:
            segs.append((pts[-1], pts[0]))
        return segs or [(pts[0], pts[0])]


class Grid:
    """Uniform grid over bboxes (same idea as the 5C index): query cost ~ nearby objects, never all objects."""
    def __init__(self, items: list, cell: float = 64.0, bbox=lambda x: x.bbox, key=lambda x: x.id):
        self.cell, self.cells, self.items, self._bbox = cell, defaultdict(list), {}, bbox
        for it in items:
            k = key(it)
            self.items[k] = it
            for c in self._keys(bbox(it)):
                self.cells[c].append(k)

    def _keys(self, b):
        c = self.cell
        for ix in range(int(math.floor(b[0] / c)), int(math.floor(b[2] / c)) + 1):
            for iy in range(int(math.floor(b[1] / c)), int(math.floor(b[3] / c)) + 1):
                yield ix, iy

    def query(self, b: BBox, pad: float = 0.0) -> list:
        b = (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)
        seen = dict.fromkeys(k for c in self._keys(b) for k in self.cells.get(c, ()))
        return [self.items[k] for k in seen]


def angle_of(a: Pt, b: Pt) -> float | None:
    if a == b:
        return None
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180


def angle_diff(a1: float | None, a2: float | None) -> float | None:
    if a1 is None or a2 is None:
        return None
    d = abs(a1 - a2) % 180
    return min(d, 180 - d)


def main_angle(g: Geo) -> float | None:
    segs = [s for s in g.segments() if s[0] != s[1]]
    if not segs:
        return None
    a, b = max(segs, key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
    return angle_of(a, b)


def point_geo(p: Pt, g: Geo) -> tuple[float, float]:
    """Distance from a point to a geometry outline and its normalised position along the path (0..1)."""
    segs = g.segments()
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs]
    total = sum(lens) or 1.0
    best, pos, acc = math.inf, 0.0, 0.0
    for (a, b), L in zip(segs, lens):
        d, t = _point_seg(p, a, b)
        if d < best:
            best, pos = d, (acc + t * L) / total
        acc += L
    return best, pos


def box_geo(b: BBox, g: Geo) -> float:
    return min(_rect_seg(b, s0, s1) for s0, s1 in g.segments())


def bbox_gap(a: BBox, b: BBox) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def inside(p: Pt, g: Geo) -> bool:
    if g.kind == "circle":
        (cx, cy), r = g.centre, g.size / 2
        return math.hypot(p[0] - cx, p[1] - cy) <= r
    if not g.closed or len(g.points) < 3:
        return False
    x, y, res = p[0], p[1], False
    pts = g.points
    for i in range(len(pts)):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % len(pts)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            res = not res
    return res


def intersects(a: Geo, b: Geo) -> bool:
    return any(_seg_cross(p1, p2, q1, q2) for p1, p2 in a.segments() for q1, q2 in b.segments())


def endpoints(g: Geo) -> list[Pt]:
    return [] if g.closed else [g.points[0], g.points[-1]]


def connected(a: Geo, b: Geo, tol: float) -> bool:
    """An open end of one touches the other's outline (or, for circles, its centre)."""
    for e in endpoints(a):
        if point_geo(e, b)[0] <= tol or (b.kind == "circle" and math.hypot(e[0] - b.centre[0], e[1] - b.centre[1]) <= tol):
            return True
    for e in endpoints(b):
        if point_geo(e, a)[0] <= tol or (a.kind == "circle" and math.hypot(e[0] - a.centre[0], e[1] - a.centre[1]) <= tol):
            return True
    return False


def relations(a: Geo, b: Geo, near_pt: float = 20.0, angle_tol: float = 5.0, touch_pt: float = 2.0) -> list[str]:
    """Pairwise relations of geometry a with respect to geometry b."""
    out = []
    gap = min(box_geo(a.bbox, b), box_geo(b.bbox, a))
    if gap <= near_pt:
        out.append("NEAR")
    if inside(a.centre, b) and a.size < b.size:
        out.append("INSIDE")
    if intersects(a, b):
        out.append("INTERSECTS")
    if connected(a, b, touch_pt):
        out.append("CONNECTED_TO")
    if not a.closed and all(point_geo(p, b)[0] <= touch_pt for p in a.points):
        out.append("ON")
    d = angle_diff(main_angle(a), main_angle(b))
    if d is not None and a.kind != "circle" and b.kind != "circle":
        if d <= angle_tol:
            out.append("PARALLEL_TO")
            # collinear: a's points lie on b's infinite line
            (p, q) = max(b.segments(), key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
            L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
            if all(abs((q[0] - p[0]) * (p[1] - y) - (p[0] - x) * (q[1] - p[1])) / L <= touch_pt for x, y in a.points):
                out.append("ALIGNED_WITH")
        elif abs(d - 90) <= angle_tol:
            out.append("PERPENDICULAR_TO")
    return out


def text_relation(b: BBox, g: Geo, radius: float) -> tuple[str | None, float]:
    """Relation of a text box to a geometry + proximity score in [0,1]."""
    if g.kind == "circle" or g.closed:
        if inside(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), g):
            return "INSIDE", 1.0
    d = box_geo(b, g)
    if d == 0:
        return "ON", 1.0
    if d <= radius:
        return "NEAR", max(0.0, 1 - d / radius)
    return None, 0.0


def between(b: BBox, g1: Geo, g2: Geo, tol: float = 1.0) -> bool:
    """Text box lies between two parallel geometries (each on a different side)."""
    c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    d1, d2 = point_geo(c, g1)[0], point_geo(c, g2)[0]
    gap = point_geo(g1.centre, g2)[0]
    return d1 + d2 <= gap + tol
