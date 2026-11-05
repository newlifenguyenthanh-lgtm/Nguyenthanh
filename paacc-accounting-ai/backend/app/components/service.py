"""Phase 5D service: taxonomy seeding, recognition runs, persistence, plan/detail representation, review, 5E hand-over."""
import datetime as dt
import functools
import json
import pathlib
import uuid
from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.components import engine as E
from app.components import spatial as S
from app.components import symbols as Y
from app.config import get_settings
from app.deps import audit
from app.geometry import measure as M
from app.geometry.measure_service import DB_DP, regions_for, to_prim
from app.models import (AITask, AuditLog, ComponentBoqCandidate, ComponentRelation, ComponentRepeatGroup, ComponentSource,
                        ComponentSymbolPattern, ComponentType, Drawing, DrawingComponent as C, DrawingPage, DrawingTextBlock,
                        ExtractedItem, GeometryPrimitive, Measurement, ScaleRegion, TextGeometryAssociation, User)
from app.office.service import set_task_status, start_task
from app.pdf.analysis import fold
from app.takeoff.engine import CalcError

STATUSES = ("CANDIDATE", "REVIEW_REQUIRED", "CONFIRMED", "REJECTED", "AMBIGUOUS", "CONFLICT", "OCCLUDED")
OPEN = ("CANDIDATE", "REVIEW_REQUIRED", "AMBIGUOUS", "CONFLICT", "OCCLUDED")
TRANSITIONS = {  # validated state machine; CANDIDATE never jumps to CONFIRMED (review first), nothing jumps to BOQ
    "CANDIDATE": {"REVIEW_REQUIRED", "REJECTED", "AMBIGUOUS"},
    "REVIEW_REQUIRED": {"CONFIRMED", "REJECTED", "AMBIGUOUS"},
    "AMBIGUOUS": {"REVIEW_REQUIRED", "CONFIRMED", "REJECTED"},
    "CONFLICT": {"REVIEW_REQUIRED", "CONFIRMED", "REJECTED", "AMBIGUOUS"},
    "OCCLUDED": {"REVIEW_REQUIRED", "CONFIRMED", "REJECTED", "AMBIGUOUS"},
    "CONFIRMED": {"REVIEW_REQUIRED"},  # re-open (reason required)
    "REJECTED": {"REVIEW_REQUIRED"},
}
NOTE_REQUIRED_TO_CONFIRM = {"AMBIGUOUS", "CONFLICT", "OCCLUDED"}
QUANTITY_KEYS = {"quantity", "count", "length", "length_m", "area", "area_m2", "spacing", "spacing_m", "volume", "volume_m3",
                 "stated_length_m", "comparisons"}
# page-level view (from the 4B title); "schedule"/"general_notes" describe PART of a sheet, never the whole drawing area
VIEW = {"plan": "PLAN", "section": "SECTION", "elevation": "ELEVATION", "detail": "DETAIL", "profile": "SECTION"}
CATALOG = pathlib.Path(__file__).with_name("catalog.json")
METHOD = "component-5D"


class ComponentError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now():
    return dt.datetime.now(dt.timezone.utc)


@functools.lru_cache
def catalog() -> dict:
    return json.loads(CATALOG.read_text())


# ---------------------------------------------------------------- taxonomy (data, per company)
def ensure_taxonomy(db: Session, company_id) -> None:
    """Adds catalog types/patterns the company does not have yet. Never overwrites company edits."""
    cat = catalog()
    have = set(db.scalars(select(ComponentType.code).where(ComponentType.company_id == company_id)))
    for t in cat["types"]:
        if t["code"] not in have:
            db.add(ComponentType(company_id=company_id, code=t["code"], group_code=t["group"], name_vi=t["name_vi"], parent_code=t["parent"],
                                 family=t["family"], member_type=t.get("member_type"), rule=t["rule"], boq=t.get("boq"),
                                 catalog_version=cat["version"], updated_at=_now()))
    if not db.scalar(select(func.count()).select_from(ComponentSymbolPattern).where(ComponentSymbolPattern.company_id == company_id)):
        for p in cat["symbol_patterns"]:
            db.add(ComponentSymbolPattern(company_id=company_id, component_type=p["component_type"], pattern_type=p["pattern_type"],
                                          parameters=p["parameters"], tolerance=p["tolerance"], confidence_weight=p["confidence_weight"]))
    db.flush()


def type_specs(db: Session, company_id) -> list[E.TypeSpec]:
    rows = db.scalars(select(ComponentType).where(ComponentType.company_id == company_id, ComponentType.active.is_(True)))
    return [E.TypeSpec(r.code, r.group_code, r.name_vi, r.parent_code, r.family, r.rule or {}, r.boq, r.member_type) for r in rows]


def pattern_specs(db: Session, company_id, known: set[str]) -> list[Y.Pattern]:
    rows = db.scalars(select(ComponentSymbolPattern).where(ComponentSymbolPattern.company_id == company_id,
                                                           ComponentSymbolPattern.active.is_(True)))
    return [Y.Pattern(str(r.id), r.component_type, r.pattern_type, r.parameters or {}, r.tolerance or {}, r.confidence_weight)
            for r in rows if r.pattern_type in Y.PATTERN_TYPES and (r.component_type is None or r.component_type in known)]


def engine_params() -> E.Params:
    s = get_settings()
    return E.Params(high=s.component_high, medium=s.component_medium, margin=s.component_margin,
                    length_abs_m=Decimal(s.assoc_conflict_abs_m), length_rel=Decimal(s.assoc_conflict_rel))


# ---------------------------------------------------------------- measurement bridge (5B is the single source of truth)
def _measurer(db: Session, d: Drawing, page: DrawingPage, user: User | None):
    regions = regions_for(db, d.id, page.page_no)
    gcache: dict[str, GeometryPrimitive] = {}
    existing = defaultdict(list)
    for m in db.scalars(select(Measurement).where(Measurement.drawing_id == d.id, Measurement.page_no == page.page_no,
                                                  Measurement.status != "rejected")):
        existing[(m.kind, tuple(m.geometry_ids))].append(m)

    def measure(kind: str, gids: list[str]) -> E.Measured | None:
        rows = []
        for g in gids:
            if g not in gcache:
                gcache[g] = db.get(GeometryPrimitive, uuid.UUID(g))
            rows.append(gcache[g])
        try:
            res = M.measure(kind, [to_prim(r) for r in rows], regions, page.scale_ratio, page.scale_status)
        except CalcError:
            return None
        ratio = res.scale.ratio if res.scale else None
        for m in existing.get((kind, tuple(gids)), []):  # reuse: same kind + geometry + scale -> same measurement
            if m.scale_ratio == ratio and (m.value_real is None) == (res.value_real is None):
                return E.Measured(str(m.id), kind, m.value_real, m.value_paper, m.real_unit, (m.details or {}).get("real_refused"))
        m = Measurement(company_id=d.company_id, drawing_id=d.id, page_no=page.page_no, kind=kind, geometry_ids=list(gids),
                        value_paper=res.value_paper.quantize(DB_DP), paper_unit=res.paper_unit,
                        value_real=None if res.value_real is None else res.value_real.quantize(DB_DP), real_unit=res.real_unit,
                        scale_ratio=ratio, scale_source=res.scale.source if res.scale else None, formula=res.formula, details=res.details,
                        method=METHOD, note="Tạo tự động khi nhận dạng cấu kiện (5D)", created_by=user.id if user else None)
        db.add(m)
        db.flush()
        existing[(kind, tuple(gids))].append(m)
        return E.Measured(str(m.id), kind, m.value_real, m.value_paper, m.real_unit, res.details.get("real_refused"))
    return measure


# ---------------------------------------------------------------- run
def _page_view(page: DrawingPage) -> str:
    for v in page.view_types or []:
        if v.get("value") in VIEW:
            return VIEW[v["value"]]
    return "UNKNOWN"


def _region_view(regions: list[ScaleRegion], cx: float, cy: float) -> str | None:
    for r in regions:
        if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1:
            F = fold(r.label or "")
            for pat, v in (("CHI TIET", "DETAIL"), ("MAT CAT", "SECTION"), ("MAT DUNG", "ELEVATION"), ("MAT BANG", "PLAN")):
                if pat in F:
                    return v
    return None


def _cleanup(db: Session, d: Drawing) -> set[uuid.UUID]:
    """Drop open, never-reviewed rule candidates (+ their links). Returns ids of kept components."""
    drop = set(db.scalars(select(C.id).where(C.drawing_id == d.id, C.recognition_method == "rule", C.status.in_(OPEN),
                                             C.reviewed_by.is_(None))))
    if drop:
        groups = set(db.scalars(select(C.repeat_group_id).where(C.id.in_(drop), C.repeat_group_id.is_not(None))))
        db.execute(delete(ComponentSource).where(ComponentSource.component_id.in_(drop)))
        db.execute(delete(ComponentRelation).where(or_(ComponentRelation.from_component_id.in_(drop),
                                                       ComponentRelation.to_component_id.in_(drop))))
        db.execute(delete(ComponentBoqCandidate).where(ComponentBoqCandidate.component_id.in_(drop)))
        for k in db.scalars(select(C).where(C.parent_id.in_(drop) | C.representation_of_id.in_(drop))):
            if k.id not in drop:
                k.parent_id = None if k.parent_id in drop else k.parent_id
                k.representation_of_id = None if k.representation_of_id in drop else k.representation_of_id
        db.flush()
        db.execute(delete(C).where(C.id.in_(drop)))
        db.flush()
        if groups:
            db.execute(delete(ComponentRepeatGroup).where(ComponentRepeatGroup.id.in_(groups)))
    db.flush()
    # 5D measurements nobody references any more
    used = set(db.scalars(select(ComponentSource.measurement_id).where(ComponentSource.measurement_id.is_not(None))))
    used |= set(db.scalars(select(TextGeometryAssociation.measurement_id).where(TextGeometryAssociation.drawing_id == d.id,
                                                                                TextGeometryAssociation.measurement_id.is_not(None))))
    used |= set(db.scalars(select(ComponentBoqCandidate.measurement_id).where(ComponentBoqCandidate.measurement_id.is_not(None))))
    for col in (ComponentRepeatGroup.count_measurement_id, ComponentRepeatGroup.spacing_measurement_id):
        used |= set(db.scalars(select(col).where(col.is_not(None))))
    for m in db.scalars(select(Measurement).where(Measurement.drawing_id == d.id, Measurement.method == METHOD,
                                                  Measurement.status == "computed")):
        if m.id not in used:
            db.delete(m)
    db.flush()
    return set(db.scalars(select(C.id).where(C.drawing_id == d.id)))


def run(db: Session, d: Drawing, user: User | None = None) -> dict:
    ensure_taxonomy(db, d.company_id)
    if not db.scalar(select(func.count()).select_from(DrawingTextBlock).where(DrawingTextBlock.drawing_id == d.id)):
        from app.association.service import build_text_blocks
        build_text_blocks(db, d)
    kept = _cleanup(db, d)
    kept_geo = {s.geometry_id for s in db.scalars(select(ComponentSource).where(ComponentSource.component_id.in_(kept),
                                                                                 ComponentSource.geometry_id.is_not(None)))} if kept else set()
    kept_txt = {s.text_block_id for s in db.scalars(select(ComponentSource).where(ComponentSource.component_id.in_(kept),
                                                                                   ComponentSource.text_block_id.is_not(None)))} if kept else set()
    types = type_specs(db, d.company_id)
    type_ids = dict(db.execute(select(ComponentType.code, ComponentType.id).where(ComponentType.company_id == d.company_id)).all())
    patterns = pattern_specs(db, d.company_id, {t.code for t in types})
    stats, timings = Counter(), Counter()
    for page in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id).order_by(DrawingPage.page_no)):
        geos = list(db.scalars(select(GeometryPrimitive).where(GeometryPrimitive.drawing_id == d.id, GeometryPrimitive.page_no == page.page_no,
                                                               GeometryPrimitive.duplicate_of.is_(None), GeometryPrimitive.status != "rejected")))
        blocks = [b for b in db.scalars(select(DrawingTextBlock).where(DrawingTextBlock.drawing_id == d.id,
                                                                       DrawingTextBlock.page_no == page.page_no)) if b.id not in kept_txt]
        assocs = list(db.scalars(select(TextGeometryAssociation).where(TextGeometryAssociation.drawing_id == d.id,
                                                                       TextGeometryAssociation.page_no == page.page_no)))
        regions = list(db.scalars(select(ExtractedItem).where(ExtractedItem.drawing_id == d.id, ExtractedItem.page_no == page.page_no,
                                                              ExtractedItem.kind.in_(("table", "region")))))
        excl_boxes = [(r.x0, r.y0, r.x1, r.y1) for r in regions
                      if r.kind == "table" or (r.data or {}).get("region_type") in ("title_block", "notes")]
        # detail callout bubbles stay usable: a callout circle only becomes a component if a component text/group claims it;
        # REFERENCE_TO links are attached as 'reference' evidence instead
        excluded = {str(g.id) for g in geos if g.id in kept_geo or any(
            b[0] <= g.x0 and b[1] <= g.y0 and g.x1 <= b[2] and g.y1 <= b[3] for b in excl_boxes)}
        res = E.recognize(
            [E.TextIn(str(b.id), b.text_type, b.original_text, b.normalized_text, (b.x0, b.y0, b.x1, b.y1), b.font_size or 10.0,
                      b.flags or [], b.values or {}) for b in blocks],
            [S.Geo(str(g.id), g.kind, [(float(x), float(y)) for x, y in g.points], g.closed, (g.x0, g.y0, g.x1, g.y1),
                   g.path_index * 10000 + g.item_index, g.kind == "fill_region", float(g.length_pt) if g.length_pt is not None else None,
                   g.flags or []) for g in geos],
            [E.AssocIn(str(a.id), str(a.text_block_id), str(a.geometry_id), a.association_type, a.status, a.rank, a.confidence)
             for a in assocs if a.duplicate_of is None],
            types, patterns, catalog(), disciplines=[x.get("value") for x in page.disciplines or []],
            measure=_measurer(db, d, page, user), params=engine_params(), excluded_geometry=excluded)
        for k, v in res.timings_ms.items():
            timings[k] += v
        stats["symbols"] += res.stats["symbols"]
        stats["repeat_groups"] += len(res.groups)
        _persist(db, d, page, res, type_ids, user, stats)
    stats["representations"] = link_representations(db, d)
    stats["components"] = db.scalar(select(func.count()).select_from(C).where(C.drawing_id == d.id)) or 0
    db.flush()
    return {**dict(stats), "timings_ms": {k: round(v, 1) for k, v in timings.items()}}


def _persist(db: Session, d: Drawing, page: DrawingPage, res: E.Result, type_ids: dict, user, stats: Counter) -> None:
    sregions = list(db.scalars(select(ScaleRegion).where(ScaleRegion.drawing_id == d.id, ScaleRegion.page_no == page.page_no,
                                                         ScaleRegion.status != "rejected")))
    page_view = _page_view(page)
    rows: dict[str, C] = {}
    for c in res.comps:
        x0, y0, x1, y1 = c.bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        grp_row = None
        if c.group:
            g = c.group
            mids = {r: i for t, i, r in c.roles if t == "measurement"}
            grp_row = ComponentRepeatGroup(company_id=d.company_id, drawing_id=d.id, page_no=page.page_no, pattern_type=g.pattern_type,
                                           signature=g.signature, carrier_geometry_id=uuid.UUID(g.carrier_id) if g.carrier_id else None,
                                           pattern_status=g.pattern_status,
                                           count_measurement_id=uuid.UUID(mids["count"]) if "count" in mids else None,
                                           spacing_measurement_id=uuid.UUID(mids["spacing"]) if "spacing" in mids else None,
                                           start_x=g.start[0], start_y=g.start[1], end_x=g.end[0], end_y=g.end[1], gaps_pt=g.gaps_pt,
                                           occluders=g.occluders or None)
            db.add(grp_row)
            db.flush()
        tid = type_ids.get(c.type)
        row = C(company_id=d.company_id, project_id=d.project_id, drawing_id=d.id, page_id=page.id, page_no=page.page_no,
                component_type=c.type, component_type_id=tid, name=_type_name(db, d.company_id, c.type),
                description="; ".join(dict.fromkeys(c.labels))[:2000], specification="; ".join(dict.fromkeys(c.spec_texts))[:1000],
                material="; ".join(dict.fromkeys(x for x in c.material if x))[:255], x0=x0, y0=y0, x1=x1, y1=y1, centroid_x=cx, centroid_y=cy,
                view_context=_region_view(sregions, cx, cy) or page_view, recognition_method="rule", recognition_rule=c.rule_ref,
                recognition_confidence=c.overall, confidence_band=c.band,
                **{f"{k}_score": c.scores.get(k) for k in E.SCORES}, status=c.status,
                ambiguity_reason="; ".join(c.ambiguous + c.conflicts)[:2000], repeat_group_id=grp_row.id if grp_row else None,
                dimensions={k: v for k, v in c.dims.items() if k != "comparisons"} or None,
                evidence={"reasons": c.reasons, "relations": c.relations, "alternatives": c.alternatives,
                          "comparisons": c.dims.get("comparisons", []), "conflicts": c.conflicts, "ambiguous": c.ambiguous,
                          "applicable_scores": sorted(c.applicable), "rule": c.rule_ref},
                created_by=user.id if user else None, updated_at=_now())
        db.add(row)
        rows[c.key] = row
        stats[f"status_{c.status}"] += 1
    db.flush()
    for c in res.comps:
        row = rows[c.key]
        seen = set()
        for st, sid, role in c.roles:
            if (st, sid) in seen:
                continue
            seen.add((st, sid))
            col = {"text": "text_block_id", "geometry": "geometry_id", "measurement": "measurement_id", "association": "association_id"}[st]
            db.add(ComponentSource(company_id=d.company_id, component_id=row.id, source_type=st, role=role[:32], **{col: uuid.UUID(sid)}))
    for a, b, rel in res.links:
        db.add(ComponentRelation(company_id=d.company_id, drawing_id=d.id, from_component_id=rows[a].id, to_component_id=rows[b].id,
                                 relation_type=rel))
        if rel == "PART_OF":
            rows[a].parent_id = rows[b].id
    db.flush()


def _type_name(db: Session, company_id, code: str) -> str:
    return db.scalar(select(ComponentType.name_vi).where(ComponentType.company_id == company_id, ComponentType.code == code)) or code


# ---------------------------------------------------------------- plan / section / detail: representations, not new components
def _spec_key(c: C) -> str:
    dims = c.dimensions or {}
    if dims.get("diameter_mm"):
        return f"D{Decimal(dims['diameter_mm']).normalize():f}"
    if dims.get("bolt_diameter_mm"):
        return f"M{dims['bolt_diameter_mm']}x{dims.get('bolt_length_mm')}"
    return fold(c.specification or "").replace(" ", "")


def link_representations(db: Session, d: Drawing) -> int:
    comps = list(db.scalars(select(C).where(C.drawing_id == d.id, C.status != "REJECTED")))
    families = dict(db.execute(select(ComponentType.code, ComponentType.family).where(ComponentType.company_id == d.company_id)).all())
    plan = [c for c in comps if c.view_context in ("PLAN", "UNKNOWN")]
    made = 0
    for c in comps:
        if c.view_context not in ("DETAIL", "SECTION", "ELEVATION") or c.representation_of_id:
            continue
        same = [p for p in plan if p.id != c.id and (p.page_no != c.page_no or p.view_context == "PLAN")]
        same = [p for p in same if families.get(p.component_type) == families.get(c.component_type)]
        key = _spec_key(c)
        match = [p for p in same if key and _spec_key(p) == key] or ([] if key else same if len(same) == 1 else [])
        if not match:
            ev = dict(c.evidence or {})
            ev.setdefault("reasons", []).append("Chỉ thấy ở chi tiết/mặt cắt – kiểm tra có phải cấu kiện riêng")
            c.evidence = ev
            continue
        target = max(match, key=lambda p: (p.repeat_group_id is not None, p.recognition_confidence))
        c.representation_of_id = target.id
        ev = dict(c.evidence or {})
        ev.setdefault("reasons", []).append(f"Biểu diễn ({c.view_context}) của cấu kiện trang {target.page_no} – không tính thành cấu kiện mới")
        c.evidence = ev
        db.add(ComponentRelation(company_id=d.company_id, drawing_id=d.id, from_component_id=c.id, to_component_id=target.id,
                                 relation_type="REPRESENTATION_OF", detail={"spec_key": key}))
        db.add(ComponentRelation(company_id=d.company_id, drawing_id=d.id, from_component_id=target.id, to_component_id=c.id,
                                 relation_type="DETAILED_IN", detail={"view": c.view_context}))
        made += 1
    # detail callouts ("CHI TIẾT A") next to a plan component -> REFERENCES the components on the page titled "CHI TIẾT A"
    pages = {p.page_no: p for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id))}
    refs = list(db.scalars(select(DrawingTextBlock).where(DrawingTextBlock.drawing_id == d.id, DrawingTextBlock.text_type == "DETAIL_REFERENCE")))
    for t in refs:
        F = fold(t.original_text)
        targets = [pn for pn, p in pages.items() if pn != t.page_no and p.title and fold(p.title).replace(" ", "").find(F.replace(" ", "")) >= 0]
        if not targets:
            continue
        near = [c for c in plan if c.page_no == t.page_no and S.bbox_gap((c.x0, c.y0, c.x1, c.y1), (t.x0, t.y0, t.x1, t.y1)) <= 60]
        for c in near:
            for o in comps:
                if o.page_no in targets and o.id != c.id:
                    db.add(ComponentRelation(company_id=d.company_id, drawing_id=d.id, from_component_id=c.id, to_component_id=o.id,
                                             relation_type="REFERENCES", detail={"text": t.original_text}))
            db.add(ComponentSource(company_id=d.company_id, component_id=c.id, source_type="text", role="reference", text_block_id=t.id))
    db.flush()
    return made


# ---------------------------------------------------------------- AI task integration (existing task system)
def run_with_task(db: Session, user: User, d: Drawing) -> dict:
    if d.status != "processed":
        raise ComponentError(409, "Bản vẽ chưa được xử lý thành công")
    task = start_task(db, user, "pdf_drawing", f"Nhận dạng cấu kiện: {d.filename} (v{d.version_no})", project_id=d.project_id,
                      entity="drawing_components", entity_id=d.id)
    db.commit()
    try:
        stats = run(db, d, user)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        task = db.merge(task)
        set_task_status(task, "error", error=f"{type(e).__name__}: {e}"[:2000])
        db.commit()
        raise
    open_n = db.scalar(select(func.count()).select_from(C).where(C.drawing_id == d.id, C.status.in_(OPEN))) or 0
    out = f"{stats.get('components', 0)} cấu kiện; {open_n} chờ kỹ sư review"
    # waiting_approval is this system's "waiting for review" state; it closes when the last open component is decided
    set_task_status(task, "waiting_approval" if open_n else "completed", output=out)
    audit(db, user, "run_components", "drawing", d.id, {k: v for k, v in stats.items() if k != "timings_ms"} | {"timings_ms": stats["timings_ms"]})
    db.commit()
    return {**stats, "task_id": str(task.id), "task_status": task.status, "open": open_n}


def _close_task_if_done(db: Session, drawing_id) -> None:
    if db.scalar(select(func.count()).select_from(C).where(C.drawing_id == drawing_id, C.status.in_(OPEN))):
        return
    for t in db.scalars(select(AITask).where(AITask.entity == "drawing_components", AITask.entity_id == drawing_id,
                                             AITask.status == "waiting_approval")):
        set_task_status(t, "completed", output=(t.output_summary + " · đã review xong")[:2000])


# ---------------------------------------------------------------- review
def _transition(db: Session, user: User, c: C, to: str, note: str, action: str, extra: dict | None = None) -> C:
    src = c.status
    if to not in TRANSITIONS.get(src, set()):
        hint = " – chuyển sang REVIEW_REQUIRED trước" if src == "CANDIDATE" and to == "CONFIRMED" else ""
        raise ComponentError(409, f"Không thể chuyển {src} → {to}{hint}")
    c.status, c.reviewed_by, c.reviewed_at, c.updated_at = to, user.id, _now(), _now()
    audit(db, user, action, "drawing_component", c.id, {"from": src, "to": to, "note": note, **(extra or {})})
    if to != "CONFIRMED":
        for b in db.scalars(select(ComponentBoqCandidate).where(ComponentBoqCandidate.component_id == c.id,
                                                                ComponentBoqCandidate.status == "DRAFT")):
            b.status, b.note, b.updated_at = "WITHDRAWN", f"Cấu kiện chuyển {src} → {to}", _now()
    _close_task_if_done(db, c.drawing_id)
    return c


def start_review(db: Session, user: User, c: C, note: str) -> C:
    if c.status in ("CONFIRMED", "REJECTED") and not note.strip():
        raise ComponentError(422, "Cần ghi lý do mở lại")
    return _transition(db, user, c, "REVIEW_REQUIRED", note, "start_review")


def confirm(db: Session, user: User, c: C, note: str) -> C:
    if c.status in NOTE_REQUIRED_TO_CONFIRM and not note.strip():
        raise ComponentError(422, f"Cấu kiện đang {c.status} – cần ghi lý do khi xác nhận")
    _transition(db, user, c, "CONFIRMED", note, "confirm")
    prepare_boq_candidate(db, user, c)
    return c


def reject(db: Session, user: User, c: C, reason: str) -> C:
    if not reason.strip():
        raise ComponentError(422, "Cần ghi lý do loại bỏ")
    c.rejection_reason = reason[:2000]
    return _transition(db, user, c, "REJECTED", reason, "reject")


def mark_ambiguous(db: Session, user: User, c: C, reason: str) -> C:
    if not reason.strip():
        raise ComponentError(422, "Cần ghi lý do")
    c.ambiguity_reason = (reason + ("; " + c.ambiguity_reason if c.ambiguity_reason else ""))[:2000]
    return _transition(db, user, c, "AMBIGUOUS", reason, "mark_ambiguous")


EDITABLE = ("component_type", "component_subtype", "description", "specification", "material", "dimensions")


def reclassify(db: Session, user: User, c: C, changes: dict, reason: str) -> C:
    if not reason.strip():
        raise ComponentError(422, "Cần ghi lý do khi sửa/phân loại lại")
    bad = set(changes) - set(EDITABLE)
    if bad:
        raise ComponentError(422, f"Không sửa được trường: {', '.join(sorted(bad))}")
    dims = changes.get("dimensions")
    if dims is not None:
        if not isinstance(dims, dict) or QUANTITY_KEYS & {k.lower() for k in dims}:
            raise ComponentError(422, "Không sửa khối lượng/số đo tại nhận dạng cấu kiện – số đo lấy từ Measurement Engine")
    if "component_type" in changes:
        t = db.scalar(select(ComponentType).where(ComponentType.company_id == c.company_id, ComponentType.code == changes["component_type"],
                                                  ComponentType.active.is_(True)))
        if not t:
            raise ComponentError(422, "Loại cấu kiện không có trong danh mục")
        c.component_type_id, c.name = t.id, t.name_vi
    before = {k: getattr(c, k) for k in changes}
    for k, v in changes.items():
        setattr(c, k, ({**(c.dimensions or {}), **v} if k == "dimensions" else v))
    c.recognition_method = "engineer" if "component_type" in changes else c.recognition_method
    target = "REVIEW_REQUIRED" if c.status != "REVIEW_REQUIRED" else None
    if target:
        _transition(db, user, c, target, reason, "reclassify", {"before": _jsonable(before), "after": _jsonable(changes)})
    else:
        c.reviewed_by, c.reviewed_at, c.updated_at = user.id, _now(), _now()
        audit(db, user, "reclassify", "drawing_component", c.id, {"before": _jsonable(before), "after": _jsonable(changes), "note": reason})
    return c


def _jsonable(d: dict) -> dict:
    return {k: (str(v) if isinstance(v, (uuid.UUID, Decimal)) else v) for k, v in d.items()}


# ---------------------------------------------------------------- 5E hand-over (DRAFT only)
def _measurement_for_boq(db: Session, c: C, kind: str | None) -> Measurement | None:
    if not kind:
        return None
    ids = [s.measurement_id for s in db.scalars(select(ComponentSource).where(ComponentSource.component_id == c.id,
                                                                               ComponentSource.measurement_id.is_not(None)))]
    for mid in ids:
        m = db.get(Measurement, mid)
        if m and m.kind == kind and m.status != "rejected":
            return m
    return None


def prepare_boq_candidate(db: Session, user: User, c: C) -> ComponentBoqCandidate | None:
    if c.status != "CONFIRMED":
        raise ComponentError(409, "Chỉ cấu kiện đã được kỹ sư xác nhận mới được chuẩn bị cho BOQ (5E)")
    if c.representation_of_id:
        return None  # a detail/section view of a component already counted elsewhere
    t = db.get(ComponentType, c.component_type_id) if c.component_type_id else None
    if not t or not t.boq:
        return None
    existing = db.scalar(select(ComponentBoqCandidate).where(ComponentBoqCandidate.component_id == c.id, ComponentBoqCandidate.status == "DRAFT"))
    if existing:
        return existing
    m = _measurement_for_boq(db, c, t.boq.get("measurement_kind"))
    b = ComponentBoqCandidate(company_id=c.company_id, drawing_id=c.drawing_id, component_id=c.id, description_vi=t.boq["description_vi"],
                              unit=t.boq["unit"], measurement_id=m.id if m else None,
                              note="" if m else "Chưa có phép đo phù hợp – 5E phải đo/xác nhận trước khi tính khối lượng",
                              created_by=user.id, updated_at=_now())
    db.add(b)
    db.flush()
    audit(db, user, "prepare_boq_candidate", "drawing_component", c.id, {"boq_candidate_id": str(b.id), "measurement_id": str(b.measurement_id)})
    return b


def confirmed_for_downstream(db: Session, drawing_id) -> list[C]:
    """The ONLY components 5E may use: CONFIRMED and not merely a representation (detail/section) of another one."""
    return list(db.scalars(select(C).where(C.drawing_id == drawing_id, C.status == "CONFIRMED", C.representation_of_id.is_(None))))


# ---------------------------------------------------------------- read models
def sources_of(db: Session, c: C) -> dict:
    out = {"text": [], "geometry": [], "measurement": [], "association": []}
    roles = []
    for s in db.scalars(select(ComponentSource).where(ComponentSource.component_id == c.id)):
        sid = s.text_block_id or s.geometry_id or s.measurement_id or s.association_id
        if str(sid) not in out[s.source_type]:
            out[s.source_type].append(str(sid))
        roles.append({"type": s.source_type, "id": str(sid), "role": s.role})
    return {**out, "roles": roles}


def measurements_of(db: Session, ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        m = db.get(Measurement, uuid.UUID(i))
        if m:
            out.append({"id": str(m.id), "kind": m.kind, "value_real": None if m.value_real is None else f"{m.value_real.normalize():f}",
                        "real_unit": m.real_unit, "value_paper": f"{m.value_paper.normalize():f}", "paper_unit": m.paper_unit,
                        "scale_source": m.scale_source, "status": m.status, "method": m.method})
    return out


def history(db: Session, c: C) -> list[dict]:
    rows = db.execute(select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id)
                      .where(AuditLog.entity == "drawing_component", AuditLog.entity_id == c.id).order_by(AuditLog.created_at))
    return [{"action": a.action, "user": email, "at": a.created_at.isoformat() if a.created_at else None, "detail": a.detail}
            for a, email in rows]
