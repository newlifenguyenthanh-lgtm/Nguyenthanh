"""Phase 5D – deterministic component recognition engine (pure; no DB, no LLM).

TEXT + GEOMETRY + MEASUREMENT + 5C ASSOCIATION + SPATIAL RELATIONSHIP + SYMBOL PATTERN + DRAWING CONTEXT
  -> component CANDIDATES with separate evidence scores. Never confirms, never computes quantities: every number that
  matters downstream comes from the injected `measure` callable (the 5B measurement engine) and is referenced by id.

The taxonomy and the recognition rules are DATA (TypeSpec.rule, Pattern rows); adding a component type does not
change this module.
"""
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from app.components import repetition as R
from app.components import spatial as S
from app.components import symbols as Y
from app.pdf.analysis import fold

SCORES = ("text", "geometry", "measurement", "symbol", "spatial", "repetition", "semantic")
LINEAR = ("line", "polyline", "curve")
BLOCK_FLAGS = {"in_table", "in_title_block", "page_number", "ENCODING_UNKNOWN"}
OPEN_ASSOC = ("CANDIDATE", "REVIEW_REQUIRED", "CONFIRMED", "CONFLICT")  # usable 5C evidence (AMBIGUOUS/REJECTED are not)


@dataclass
class TypeSpec:
    code: str
    group: str
    name_vi: str
    parent: str | None
    family: str
    rule: dict
    boq: dict | None = None
    member_type: str | None = None


@dataclass
class TextIn:
    id: str
    text_type: str
    original: str
    normalized: str
    bbox: S.BBox
    font_size: float = 10.0
    flags: list[str] = field(default_factory=list)
    values: dict = field(default_factory=dict)


@dataclass
class AssocIn:
    id: str
    text_id: str
    geometry_id: str
    type: str
    status: str
    rank: int
    confidence: float


@dataclass
class Measured:
    id: str
    kind: str
    value_real: Decimal | None
    value_paper: Decimal
    unit: str | None
    refused: str | None = None


@dataclass
class Params:
    high: float = 0.90
    medium: float = 0.70
    margin: float = 0.10
    min_repeat: int = 3
    radius_factor: float = 6.0
    min_radius: float = 30.0
    max_radius: float = 120.0
    length_abs_m: Decimal = Decimal("0.01")
    length_rel: Decimal = Decimal("0.005")
    diameter_abs_mm: Decimal = Decimal("1")
    diameter_rel: Decimal = Decimal("0.02")


@dataclass
class Comp:
    key: str
    type: str
    text_ids: list[str] = field(default_factory=list)
    geometry_ids: list[str] = field(default_factory=list)
    association_ids: list[str] = field(default_factory=list)
    measurement_ids: list[str] = field(default_factory=list)
    roles: list[tuple[str, str, str]] = field(default_factory=list)  # (source_type, id, role)
    scores: dict = field(default_factory=dict)
    applicable: set = field(default_factory=set)
    overall: float = 0.0
    band: str = "LOW"
    status: str = "CANDIDATE"
    reasons: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    dims: dict = field(default_factory=dict)  # STATED on the drawing (specification), never a quantity
    spec_texts: list[str] = field(default_factory=list)
    material: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)  # evidence: [{"relation", "a", "b"}]
    group: R.Group | None = None
    carrier_key: str | None = None
    from_carrier: bool = False
    bbox: S.BBox | None = None
    rule_ref: str = ""


GeoRef = S.Geo | None


@dataclass
class Result:
    comps: list[Comp]
    links: list[tuple[str, str, str]]  # (from_key, to_key, relation)
    groups: list[R.Group]
    timings_ms: dict
    stats: dict


# ------------------------------------------------------------------ taxonomy helpers
class Taxonomy:
    def __init__(self, types: list[TypeSpec], catalog: dict):
        self.by = {t.code: t for t in types}
        self.catalog = catalog
        self.compiled = {t.code: self._compile(t) for t in types}

    @staticmethod
    def _compile(t: TypeSpec):
        kws = []
        for kw in t.rule.get("keywords", []):
            u = kw.upper()
            kws.append((u, re.compile(r"(?<!\w)" + re.escape(u) + r"(?!\w)"), re.compile(r"(?<!\w)" + re.escape(fold(u)) + r"(?!\w)")))
        return kws, [re.compile(x) for x in t.rule.get("regex", [])]

    def ancestors(self, code: str) -> list[str]:
        out, cur = [], self.by.get(code)
        while cur and cur.parent and cur.parent not in out:
            out.append(cur.parent)
            cur = self.by.get(cur.parent)
        return out

    def depth(self, code: str) -> int:
        return len(self.ancestors(code))

    def generic(self, code: str) -> bool:
        return self.by[code].group == "GENERIC"

    def compatible(self, a: str, b: str) -> bool:
        if a == b or self.generic(a) or self.generic(b):
            return True
        return a in self.ancestors(b) or b in self.ancestors(a) or self.by[a].family == self.by[b].family

    def weights(self, code: str) -> dict:
        return {**self.catalog["default_weights"], **(self.by[code].rule.get("weights") or {})}

    def disciplines(self, code: str) -> list[str]:
        return self.catalog.get("discipline_groups", {}).get(self.by[code].group, [])


# ------------------------------------------------------------------ text -> type
def stated_dims(t: TextIn) -> dict:
    out: dict = {}
    for d in (t.values or {}).get("dimensions", []) or []:
        v = d.get("values") or []
        if d.get("type") == "round" and v:
            out["diameter_mm"] = v[0]
            if len(v) > 1:
                out["thickness_mm"] = v[1]
        elif d.get("type") == "bolt" and len(v) >= 2:
            out.update(bolt_diameter_mm=v[0], bolt_length_mm=v[1])
        elif v:
            out.setdefault("dimensions", []).append({"type": d.get("type"), "values": v})
        if d.get("unit") is None and v:
            out["unit_basis"] = "quy ước mm cho quy cách thép (đơn vị không ghi trên bản vẽ)"
    ln = (t.values or {}).get("length")
    if ln and ln.get("value_m") and not ln.get("ambiguous"):
        out["stated_length_m"] = ln["value_m"]
    return out


def match_types(t: TextIn, tax: Taxonomy) -> list[tuple[str, float, str]]:
    """[(type_code, text_score, matched)] after specificity resolution. Context exclusions applied here."""
    if BLOCK_FLAGS & set(t.flags):
        return []
    U = t.normalized.upper()
    ascii_only = fold(U) == U
    F = fold(U)
    specs = {s.get("category") for s in (t.values or {}).get("specs", []) or []}
    dimt = {d.get("type") for d in (t.values or {}).get("dimensions", []) or []}
    default_ex = set(tax.catalog.get("default_exclude_text_types", []))
    hits: list[tuple[str, float, str]] = []
    for code, ts in tax.by.items():
        if ts.group == "GENERIC":
            continue
        excl = set(ts.rule.get("exclude_text_types") or default_ex)
        if t.text_type in excl:
            continue
        kws, rxs = tax.compiled[code]
        kw = max((u for u, rd, ra in kws if (ra if ascii_only else rd).search(F if ascii_only else U)), key=len, default=None)
        rx = next((m.group(0) for r in rxs for m in [r.search(F)] if m), None)
        sp = specs & set(ts.rule.get("spec_categories", []))
        dm = dimt & set(ts.rule.get("dimension_types", []))
        if kw or rx:
            hits.append((code, 1.0, kw or rx))
        elif sp:
            hits.append((code, 0.9, "spec:" + ",".join(sorted(sp))))
        elif dm:
            hits.append((code, float(ts.rule.get("dimension_score", 0.6)), "dim:" + ",".join(sorted(dm))))
    # specificity: a keyword contained in a longer matched keyword loses ("TƯỜNG" vs "TƯỜNG CHẮN XE"); an ancestor loses to its child
    keep = []
    for c, s, m in hits:
        longer = any(o != c and not m.startswith(("spec:", "dim:")) and m != om and m in om for o, _, om in hits)
        parent_of_hit = any(c in tax.ancestors(o) for o, _, _ in hits if o != c)
        if not longer and not parent_of_hit:
            keep.append((c, s, m))
    return sorted(keep, key=lambda x: -x[1])


# ------------------------------------------------------------------ main
def recognize(texts: list[TextIn], geoms: list[S.Geo], assocs: list[AssocIn], types: list[TypeSpec], patterns: list[Y.Pattern],
              catalog: dict, *, disciplines: list[str], measure: Callable[[str, list[str]], Measured | None],
              params: Params | None = None, excluded_geometry: set[str] | None = None) -> Result:
    p = params or Params()
    t0 = time.perf_counter()
    tax = Taxonomy(types, catalog)
    excluded_geometry = excluded_geometry or set()
    usable = [g for g in geoms if g.id not in excluded_geometry]
    gby = {g.id: g for g in usable}
    ggrid = S.Grid(usable)
    tby = {t.id: t for t in texts}
    # ---- symbols (pattern data) + repetition
    syms = Y.match(patterns, usable, ggrid, [(t.id, t.bbox) for t in texts if not (BLOCK_FLAGS & set(t.flags))])
    pat_by_id = {x.id: x for x in patterns}
    best_rep: dict[str, Y.Symbol] = {}
    for s in syms:
        if pat_by_id[s.pattern_id].parameters.get("repeatable") and (s.anchor_id not in best_rep or s.weight > best_rep[s.anchor_id].weight):
            best_rep[s.anchor_id] = s
    carriers = [g for g in usable if g.kind in ("line", "polyline") and (g.length_pt or 0) > 0]
    fills = [g for g in usable if g.kind == "fill_region"]
    groups = R.detect(list(best_rep.values()), carriers, fills, {g.id: g.order for g in usable}, min_count=p.min_repeat)
    t_cand = time.perf_counter()
    sgrid = S.Grid([s for s in syms if s.component_type], key=lambda s: id(s))
    leaders = defaultdict(list)
    for s in syms:
        if s.pattern_type == "leader":
            leaders[s.attrs["text_id"]].append(s.attrs["target_id"])
    by_text_assoc = defaultdict(list)
    for a in assocs:
        if a.status in OPEN_ASSOC:
            by_text_assoc[a.text_id].append(a)

    comps: list[Comp] = []
    n = 0

    def new(type_code: str) -> Comp:
        nonlocal n
        n += 1
        return Comp(f"c{n}", type_code, rule_ref=f"{type_code}@catalog")

    def semantic(code: str) -> float:
        want = tax.disciplines(code)
        if not want:
            return 0.5
        if not disciplines:
            return 0.6
        return 1.0 if set(want) & set(disciplines) else 0.3

    def do_measure(c: Comp, kind: str, gids: list[str], stated=None, compare=None):
        m = measure(kind, gids)
        if m is None:
            c.scores["measurement"] = 0.0
            return None
        c.measurement_ids.append(m.id)
        c.roles.append(("measurement", m.id, kind))
        if m.value_real is None:
            c.scores["measurement"] = 0.5
            c.reasons.append(f"Đo {kind}: chưa có tỷ lệ được kỹ sư xác nhận ({m.refused or 'paper only'})")
            return m
        if stated is None or compare is None:
            c.scores["measurement"] = 0.8
            return m
        if compare == "length":
            tol = max(p.length_abs_m, abs(stated) * p.length_rel)
            diff, unit, measured = stated - m.value_real, "m", m.value_real
        else:  # diameter: stated mm vs measured m
            measured = (m.value_real * 1000)
            tol = max(p.diameter_abs_mm, abs(stated) * p.diameter_rel)
            diff, unit = stated - measured, "mm"
        c.dims.setdefault("comparisons", []).append({"kind": kind, "stated": f"{stated.normalize():f}", "measured": f"{measured.normalize():f}",
                                                     "difference": f"{diff.normalize():f}", "unit": unit, "measurement_id": m.id})
        if abs(diff) > tol:
            c.scores["measurement"] = 0.0
            c.conflicts.append(f"Ghi trên bản vẽ: {stated.normalize():f} {unit} · Hình học: {measured.normalize():f} {unit} · "
                               f"Chênh: {abs(diff).normalize():f} {unit} – không tự sửa")
        else:
            c.scores["measurement"] = 1.0
        return m

    # ---- 1) text-triggered candidates (each tied type is evaluated on its evidence; measurement only for the winner)
    def build(t: TextIn, code: str, tscore: float, matched: str) -> tuple[Comp, GeoRef]:
        ts = tax.by[code]
        c = new(code)
        c.text_ids.append(t.id)
        c.roles.append(("text", t.id, "trigger"))
        c.scores["text"] = tscore
        c.applicable.update({"text", "semantic"})
        c.dims.update(stated_dims(t))
        if matched.startswith(("dim:", "spec:")) or c.dims.get("diameter_mm") or c.dims.get("bolt_diameter_mm"):
            c.spec_texts.append(t.original)
        c.material += [s_.get("value") for s_ in (t.values or {}).get("specs", []) or []
                       if s_.get("category") in ("concrete_grade", "rebar_grade", "steel_grade")]
        c.labels.append(t.original)
        radius = max(p.min_radius, min(p.max_radius, p.radius_factor * (t.font_size or 10)))
        kinds = tuple(ts.rule.get("geometry_kinds") or ())
        optional = bool(ts.rule.get("geometry_optional"))
        # evidence: 5C association (usable statuses only)
        best_a = sorted(by_text_assoc.get(t.id, []), key=lambda a_: (a_.status != "CONFIRMED", a_.rank))
        a = next((x for x in best_a if x.geometry_id in gby), None)
        a_score = 0.0
        if a:
            c.association_ids.append(a.id)
            c.roles.append(("association", a.id, a.type))
            a_score = 1.0 if a.status == "CONFIRMED" else a.confidence
            if a.status == "CONFLICT":
                c.conflicts.append("Liên kết chữ ↔ hình học (5C) đang XUNG ĐỘT")
        # evidence: symbols near the text compatible with the type
        sym, s_score, srel = None, 0.0, None
        if any(x.component_type and tax.compatible(x.component_type, code) and not tax.generic(x.component_type) for x in patterns):
            c.applicable.add("symbol")
        for s_ in sgrid.query(t.bbox, pad=radius):
            if not tax.compatible(s_.component_type, code) or tax.generic(s_.component_type):
                continue
            rel, prox = (("ON", 1.0) if a and a.geometry_id in s_.geometry_ids else
                         ("NEAR", max(0.0, 1 - S.bbox_gap(t.bbox, s_.bbox) / radius)))
            if t.id in leaders and set(leaders[t.id]) & set(s_.geometry_ids):
                rel, prox = "LEADER", 1.0
            val = s_.weight * (1.0 if s_.component_type == code else 0.8) * prox
            if prox > 0 and val > s_score:
                sym, s_score, srel = s_, val, rel
        # chosen geometry: symbol > associated geometry of a fitting kind > nearest geometry of a fitting kind
        chosen: list[str] = []
        prim = None
        if sym:
            chosen = list(sym.geometry_ids)
            prim = gby.get(sym.anchor_id)
            c.relations.append({"relation": srel, "a": t.id, "b": sym.anchor_id})
            c.roles.extend(("geometry", g, "symbol:" + sym.pattern_type) for g in chosen)
            c.scores["symbol"] = round(s_score, 3)
        elif a and (not kinds or gby[a.geometry_id].kind in kinds):
            prim = gby[a.geometry_id]
            chosen = [prim.id]
            c.roles.append(("geometry", prim.id, "associated"))
        elif kinds:
            near = [(S.box_geo(t.bbox, g), g) for g in ggrid.query(t.bbox, pad=radius) if g.kind in kinds]
            near = [x for x in near if x[0] <= radius]
            if near:
                prim = min(near, key=lambda x: (x[0], x[1].id))[1]
                chosen = [prim.id]
                c.roles.append(("geometry", prim.id, "nearest"))
        c.geometry_ids = list(dict.fromkeys(chosen))
        if prim or not optional:  # optional geometry (bolt callout, rebar note): absence is not evidence against
            c.applicable.update({"geometry", "spatial"} | ({"symbol"} if "symbol" in c.applicable else set()))
        else:
            c.applicable.discard("symbol")
        c.scores["geometry"] = 0.0 if not prim else (1.0 if not kinds or prim.kind in kinds else 0.4)
        sp = a_score if (a and prim and prim.id == a.geometry_id) else 0.0
        if prim:
            rel, prox = S.text_relation(t.bbox, prim, radius)
            sp = max(sp, prox)
            if rel and not sym:
                c.relations.append({"relation": rel, "a": t.id, "b": prim.id})
            if t.id in leaders and prim.id in leaders[t.id]:
                sp = 1.0
                c.relations.append({"relation": "LEADER", "a": t.id, "b": prim.id})
        c.scores["spatial"] = round(sp, 3)
        c.scores["semantic"] = semantic(code)
        c.bbox = _bbox([gby[g].bbox for g in c.geometry_ids if g in gby] or [t.bbox])
        return c, prim

    def measure_text_comp(c: Comp, prim) -> None:
        ts = tax.by[c.type]
        mk, cmp_ = ts.rule.get("measurement_kind"), ts.rule.get("compare")
        if mk not in ("length", "diameter", "area") or not prim:
            return
        c.applicable.add("measurement")
        if mk == "diameter" and prim.kind == "circle":
            st = Decimal(c.dims["diameter_mm"]) if c.dims.get("diameter_mm") else None
            do_measure(c, "diameter", [prim.id], st, cmp_ if st is not None else None)
        elif mk == "length" and prim.kind in LINEAR:
            st = Decimal(c.dims["stated_length_m"]) if c.dims.get("stated_length_m") else None
            do_measure(c, "length", [prim.id], st, cmp_ if st is not None else None)
        elif mk == "area" and prim.closed:
            do_measure(c, "area", [prim.id])
        else:
            c.scores["measurement"] = 0.0

    for t in texts:
        hits = match_types(t, tax)
        if not hits:
            continue
        top = hits[0][1]
        trial = [build(t, code, sc, m) for code, sc, m in hits if top - sc < p.margin][:6]
        for c, _ in trial:
            _finalise(c, tax, p)
        trial.sort(key=lambda x: (-x[0].overall, -tax.depth(x[0].type), x[0].type))
        c, prim = trial[0]
        c.alternatives = [{"type": o.type, "overall": o.overall} for o, _ in trial[1:]] + \
                         [{"type": code, "text_score": sc, "matched": m} for code, sc, m in hits if top - sc >= p.margin]
        if len(trial) > 1 and c.overall - trial[1][0].overall < p.margin and not tax.compatible(c.type, trial[1][0].type):
            c.ambiguous.append(f"Chữ khớp nhiều loại cấu kiện có điểm gần nhau: {c.type} / {trial[1][0].type}")
        for k in SCORES:  # reset finalisation placeholders before measurement/merge
            if c.scores.get(k) is None:
                c.scores.pop(k, None)
        measure_text_comp(c, prim)
        comps.append(c)

    # ---- 2) generic linear components: LENGTH text DIMENSION_OF a line that has no typed component
    taken_texts = {tid for c in comps for tid in c.text_ids}
    for t in texts:
        if t.id in taken_texts or t.text_type != "LENGTH" or BLOCK_FLAGS & set(t.flags):
            continue
        a = next((a for a in sorted(by_text_assoc.get(t.id, []), key=lambda a: (a.status != "CONFIRMED", a.rank))
                  if a.type == "DIMENSION_OF"), None)
        if not a or a.geometry_id not in gby or gby[a.geometry_id].kind not in LINEAR:
            continue
        g = gby[a.geometry_id]
        c = new("LINEAR_COMPONENT")
        c.text_ids.append(t.id)
        c.roles += [("text", t.id, "dimension"), ("association", a.id, a.type), ("geometry", g.id, "associated")]
        c.association_ids.append(a.id)
        c.geometry_ids = [g.id]
        c.dims.update(stated_dims(t))
        c.labels.append(t.original)
        c.applicable.update({"text", "geometry", "spatial", "semantic", "measurement"})
        c.scores.update(text=0.5, geometry=1.0, spatial=1.0 if a.status == "CONFIRMED" else a.confidence, semantic=0.5)
        if a.status == "CONFLICT":
            c.conflicts.append("Liên kết chữ ↔ hình học (5C) đang XUNG ĐỘT")
        st = Decimal(c.dims["stated_length_m"]) if c.dims.get("stated_length_m") else None
        do_measure(c, "length", [g.id], st, "length" if st is not None else None)
        c.relations.append({"relation": "ON" if S.box_geo(t.bbox, g) == 0 else "NEAR", "a": t.id, "b": g.id})
        c.bbox = g.bbox
        comps.append(c)

    # ---- 3) repeated groups -> ONE component each (never one per post)
    owner = {}
    for c in comps:
        for gid in c.geometry_ids:
            owner.setdefault(gid, c)
    for grp in groups:
        carrier = owner.get(grp.carrier_id) if grp.carrier_id else None
        code = grp.component_type or "STEEL_POST"
        from_carrier = False
        if carrier and tax.by[carrier.type].member_type:
            code, from_carrier = tax.by[carrier.type].member_type, True
        c = new(code)
        c.group, c.from_carrier = grp, from_carrier
        c.geometry_ids = [g for m in grp.members for g in m.geometry_ids]
        c.roles += [("geometry", g, "member") for g in c.geometry_ids]
        c.applicable.update({"text", "symbol", "spatial", "repetition", "semantic", "measurement"})
        c.scores.update(text=0.7 if from_carrier else 0.0, symbol=round(sum(m.weight for m in grp.members) / len(grp.members), 3),
                        spatial=1.0 if grp.carrier_id else 0.8, semantic=semantic(code),
                        repetition={R.REGULAR: 1.0, R.IRREGULAR: 0.6, R.OCCLUDED: 0.4}[grp.pattern_status])
        if grp.carrier_id:
            c.relations.append({"relation": "REPEATED_ALONG", "a": grp.key, "b": grp.carrier_id})
            if carrier:
                c.carrier_key = carrier.key
        else:
            c.relations.append({"relation": "ALIGNED_WITH", "a": grp.key, "b": "row"})
        anchors = [m.anchor_id for m in grp.members]
        cnt = measure("count", anchors)
        if cnt:
            c.measurement_ids.append(cnt.id)
            c.roles.append(("measurement", cnt.id, "count"))
        spc = measure("spacing", anchors) if len(anchors) >= 3 else None
        if spc:
            c.measurement_ids.append(spc.id)
            c.roles.append(("measurement", spc.id, "spacing"))
        c.scores["measurement"] = 1.0 if spc and spc.value_real is not None else (0.6 if cnt else 0.0)
        if spc and spc.value_real is None:
            c.reasons.append("Bước lặp: chưa có tỷ lệ xác nhận – chỉ có giá trị trên giấy")
        c.reasons += grp.reasons
        if grp.pattern_status == R.IRREGULAR:
            c.reasons.append("IRREGULAR_PATTERN")
        c.bbox = grp.bbox
        comps.append(c)

    # ---- 4) identity merge: one physical component may appear as text + symbol + geometry + dimension
    comps, links = _merge(comps, tax)
    # ---- 5) attach remaining 5C evidence (labels, materials, chainage, notes) to the component owning the geometry
    owner = {}
    for c in comps:
        for gid in c.geometry_ids:
            owner.setdefault(gid, c)
    used_texts = {tid for c in comps for tid in c.text_ids}
    for a in assocs:
        if a.status not in OPEN_ASSOC or a.text_id in used_texts or a.geometry_id not in owner or a.rank != 1:
            continue
        c = owner[a.geometry_id]
        t = tby.get(a.text_id)
        if not t:
            continue
        c.text_ids.append(t.id)
        c.association_ids.append(a.id)
        role = {"MATERIAL_OF": "material", "CHAINAGE_FOR": "chainage", "LABEL_OF": "label", "NOTE_FOR": "note",
                "REFERENCE_TO": "reference", "DIMENSION_OF": "dimension"}.get(a.type, "evidence")
        c.roles += [("text", t.id, role), ("association", a.id, a.type)]
        if role == "material":
            c.material.append(t.normalized)
        elif role == "label":
            c.labels.append(t.original)
        elif role == "dimension":
            c.dims.update({k: v for k, v in stated_dims(t).items() if k not in c.dims})
        if a.status == "CONFLICT":
            c.conflicts.append(f"Liên kết 5C của “{t.original}” đang XUNG ĐỘT")
        used_texts.add(t.id)
    # ---- 6) score + status
    for c in comps:
        _finalise(c, tax, p)
    t_end = time.perf_counter()
    stats = {"symbols": len(syms), "groups": len(groups), "components": len(comps)}
    return Result(comps, links, groups, {"candidate_generation": round((t_cand - t0) * 1000, 1),
                                         "recognition": round((t_end - t_cand) * 1000, 1), "total": round((t_end - t0) * 1000, 1)}, stats)


def _bbox(bs):
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def _merge(comps: list[Comp], tax: Taxonomy) -> tuple[list[Comp], list[tuple[str, str, str]]]:
    parent = {c.key: c.key for c in comps}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    by_geom = defaultdict(list)
    for c in comps:
        for g in c.geometry_ids:
            by_geom[g].append(c)
    clash: set[tuple[str, str]] = set()
    for g, cs in by_geom.items():
        for x in cs[1:]:
            if tax.compatible(cs[0].type, x.type):
                parent[find(x.key)] = find(cs[0].key)
            else:
                clash.add(tuple(sorted((cs[0].key, x.key))))
    groups = defaultdict(list)
    for c in comps:
        groups[find(c.key)].append(c)
    out, alias = [], {}
    for members in groups.values():
        def pref(c):
            return (not tax.generic(c.type), c.from_carrier, c.group is not None, tax.depth(c.type), c.scores.get("text", 0))
        head = max(members, key=pref)
        for m in members:
            alias[m.key] = head.key
            if m is head:
                continue
            for attr in ("text_ids", "geometry_ids", "association_ids", "measurement_ids", "roles", "reasons", "conflicts", "ambiguous",
                         "spec_texts", "material", "labels", "relations"):
                getattr(head, attr).extend(x for x in getattr(m, attr) if x not in getattr(head, attr))
            for k, v in m.scores.items():
                head.scores[k] = max(head.scores.get(k, 0.0), v)
            head.applicable |= m.applicable
            for k, v in m.dims.items():
                if k == "comparisons":
                    head.dims.setdefault(k, []).extend(v)
                else:
                    head.dims.setdefault(k, v)
            head.group = head.group or m.group
            head.carrier_key = head.carrier_key or m.carrier_key
            head.bbox = _bbox([b for b in (head.bbox, m.bbox) if b])
            if m.type != head.type:
                head.alternatives.append({"type": m.type, "merged": True})
        if len(members) > 1:
            head.reasons.append(f"Gộp {len(members)} biểu diễn (chữ/ký hiệu/hình học/kích thước) thành 1 cấu kiện")
        out.append(head)
    for a, b in clash:
        for k in (a, b):
            c = next(x for x in out if x.key == alias.get(k, k))
            c.ambiguous.append("Cùng đối tượng hình học được nhận dạng thành loại cấu kiện khác nhau – cần kỹ sư chọn")
    links = []
    for c in out:
        if c.carrier_key:
            target = alias.get(c.carrier_key, c.carrier_key)
            if target != c.key:
                links += [(c.key, target, "PART_OF"), (c.key, target, "REPEATED_ALONG")]
    return out, links


def _finalise(c: Comp, tax: Taxonomy, p: Params) -> None:
    w = tax.weights(c.type)
    app = [k for k in SCORES if k in c.applicable and w.get(k, 0) > 0]
    tot = sum(w[k] for k in app) or 1.0
    for k in SCORES:
        c.scores.setdefault(k, None if k not in c.applicable else 0.0)
    c.overall = round(sum(w[k] * (c.scores.get(k) or 0.0) for k in app) / tot, 3)
    c.band = "HIGH" if c.overall >= p.high else "MEDIUM" if c.overall >= p.medium else "LOW"
    if c.conflicts:
        c.status = "CONFLICT"
    elif c.group and c.group.pattern_status == R.OCCLUDED:
        c.status = "OCCLUDED"
    elif c.ambiguous or c.band == "LOW":
        c.status = "AMBIGUOUS"
        if c.band == "LOW" and not c.ambiguous:
            c.ambiguous.append(f"Điểm tổng thấp ({c.overall}) – bằng chứng chưa đủ")
    elif c.band == "MEDIUM" or "IRREGULAR_PATTERN" in c.reasons:
        c.status = "REVIEW_REQUIRED"
    else:
        c.status = "CANDIDATE"
