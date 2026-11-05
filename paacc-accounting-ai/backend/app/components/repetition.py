"""Phase 5D – repeated component detection (posts, pits, delineators …) from symbol occurrences.

A group = >= min_count symbols of the same pattern and size (within tolerance) arranged along a carrier line/polyline
(REPEATED_ALONG) or on one straight row. The visible count is NEVER extrapolated: hidden members are reported (OCCLUDED),
not added. Spacing/count values that matter downstream are produced by the 5B measurement engine, not here.
"""
import math
from dataclasses import dataclass, field

from app.components import spatial as S
from app.components.symbols import Symbol

REGULAR, IRREGULAR, OCCLUDED = "REGULAR", "IRREGULAR_PATTERN", "OCCLUDED"


@dataclass
class Group:
    key: str
    pattern_type: str
    component_type: str | None
    members: list[Symbol]
    carrier_id: str | None
    gaps_pt: list[float]
    pattern_status: str
    start: S.Pt
    end: S.Pt
    occluders: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def bbox(self) -> S.BBox:
        bs = [m.bbox for m in self.members]
        return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)

    @property
    def signature(self) -> dict:
        return {"pattern_type": self.pattern_type, "size_pt": round(sum(m.size for m in self.members) / len(self.members), 2)}


def _size_clusters(syms: list[Symbol], rel: float) -> list[list[Symbol]]:
    out: list[list[Symbol]] = []
    for s in sorted(syms, key=lambda s: s.size):
        if out and abs(s.size - out[-1][0].size) <= rel * max(out[-1][0].size, 1e-9):
            out[-1].append(s)
        else:
            out.append([s])
    return out


def _chains(syms: list[Symbol], link: float) -> list[list[Symbol]]:
    """Single-linkage clusters of symbol centres (grid-assisted)."""
    grid = S.Grid(syms, cell=max(link, 8.0), key=lambda s: id(s))
    seen, out = set(), []
    for s in syms:
        if id(s) in seen:
            continue
        stack, comp = [s], []
        seen.add(id(s))
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in grid.query(x.bbox, pad=link):
                if id(y) not in seen and math.dist(x.centre, y.centre) <= link:
                    seen.add(id(y))
                    stack.append(y)
        out.append(comp)
    return out


def _nearest(syms: list[Symbol]) -> list[float]:
    """Nearest-neighbour distance per symbol via the grid (growing search radius), not all pairs."""
    grid = S.Grid(syms, cell=64.0, key=lambda s: id(s))
    out = []
    for s in syms:
        for pad in (16.0, 64.0, 256.0, 1024.0):  # isolated beyond 1024 pt: not part of a row
            ds = [math.dist(s.centre, o.centre) for o in grid.query(s.bbox, pad=pad) if o is not s]
            ds = [d for d in ds if d <= pad]
            if ds:
                out.append(min(ds))
                break
    return out or [0.0]


def _status(gaps: list[float], rel_tol: float) -> str:
    if not gaps:
        return REGULAR
    mean = sum(gaps) / len(gaps)
    return REGULAR if max(gaps) - min(gaps) <= rel_tol * mean else IRREGULAR


def _occluders(members: list[Symbol], gaps: list[float], fills: list[S.Geo], member_order: int) -> list[str]:
    """Filled regions drawn AFTER the members over a member or over an abnormally large gap -> possibly hidden members."""
    if not fills:
        return []
    med = sorted(gaps)[len(gaps) // 2] if gaps else 0
    spans = [m.bbox for m in members]
    for (a, b), gap in zip(zip(members, members[1:]), gaps):
        if med and gap > 1.5 * med:
            spans.append((min(a.centre[0], b.centre[0]), min(a.centre[1], b.centre[1]), max(a.centre[0], b.centre[0]),
                          max(a.centre[1], b.centre[1])))
    hit = []
    for f in fills:
        if f.order > member_order and any(S.bbox_gap(f.bbox, sp) == 0 for sp in spans):
            hit.append(f.id)
    return hit


def detect(symbols: list[Symbol], carriers: list[S.Geo], fills: list[S.Geo], orders: dict[str, int], *, min_count: int = 3,
           size_rel: float = 0.10, spacing_rel: float = 0.05, carrier_tol: float = 3.0) -> list[Group]:
    """symbols: occurrences of REPEATABLE patterns only. carriers: usable line/polyline geometry. orders: geometry id -> draw order."""
    groups: list[Group] = []
    cgrid = S.Grid(carriers)
    by_pattern: dict[str, list[Symbol]] = {}
    for s in symbols:
        by_pattern.setdefault(s.pattern_type, []).append(s)
    n = 0
    for ptype, syms in sorted(by_pattern.items()):
        for cluster in _size_clusters(syms, size_rel):
            if len(cluster) < min_count:
                continue
            free = list(cluster)
            # 1) along a carrier (route / fence line / guardrail line): REPEATED_ALONG
            cand: dict[str, list[tuple[float, Symbol]]] = {}
            for s in free:
                tol = max(carrier_tol, s.size)
                for c in cgrid.query(s.bbox, pad=tol):
                    if c.id in s.geometry_ids:
                        continue
                    d, pos = S.point_geo(s.centre, c)
                    if d <= tol:
                        cand.setdefault(c.id, []).append((pos, s))
            used: set[int] = set()
            for cid, lst in sorted(cand.items(), key=lambda kv: -len(kv[1])):
                lst = [(p, s) for p, s in lst if id(s) not in used]
                if len(lst) < min_count:
                    continue
                lst.sort(key=lambda x: x[0])
                c = next(x for x in carriers if x.id == cid)
                total = c.length_pt or sum(math.dist(a, b) for a, b in c.segments())
                gaps = [round((b[0] - a[0]) * total, 3) for a, b in zip(lst, lst[1:])]
                members = [s for _, s in lst]
                used.update(id(s) for s in members)
                n += 1
                groups.append(_make(f"g{n}", ptype, members, cid, gaps, fills, orders, spacing_rel))
            free = [s for s in free if id(s) not in used]
            # 2) straight rows without a carrier
            if len(free) >= min_count:
                nn = sorted(_nearest(free))
                link = 3.0 * nn[len(nn) // 2]
                for chain in _chains(free, link):
                    if len(chain) < min_count:
                        continue
                    xs, ys = [s.centre[0] for s in chain], [s.centre[1] for s in chain]
                    horiz = (max(xs) - min(xs)) >= (max(ys) - min(ys))
                    chain.sort(key=lambda s: s.centre[0] if horiz else s.centre[1])
                    a, b = chain[0].centre, chain[-1].centre
                    L = math.dist(a, b) or 1.0
                    resid = max(abs((b[0] - a[0]) * (a[1] - s.centre[1]) - (a[0] - s.centre[0]) * (b[1] - a[1])) / L for s in chain)
                    if resid > max(carrier_tol, chain[0].size):
                        continue  # a cluster, not a row: not a repetition pattern we can vouch for
                    gaps = [round(math.dist(p.centre, q.centre), 3) for p, q in zip(chain, chain[1:])]
                    n += 1
                    groups.append(_make(f"g{n}", ptype, chain, None, gaps, fills, orders, spacing_rel))
    return groups


def _make(key, ptype, members, carrier_id, gaps, fills, orders, spacing_rel) -> Group:
    status = _status(gaps, spacing_rel)
    order = max(orders.get(g, 0) for m in members for g in m.geometry_ids)
    occ = _occluders(members, gaps, fills, order)
    reasons = []
    if status == IRREGULAR:
        reasons.append(f"Khoảng cách không đều ({min(gaps):.1f}–{max(gaps):.1f} pt)")
    if occ:
        status = OCCLUDED
        reasons.append(f"Có {len(occ)} vùng tô vẽ đè lên dãy – có thể bị che; KHÔNG nội suy số lượng")
    types = {m.component_type for m in members}
    return Group(key, ptype, types.pop() if len(types) == 1 else None, members, carrier_id, gaps, status,
                 members[0].centre, members[-1].centre, occ, reasons)
