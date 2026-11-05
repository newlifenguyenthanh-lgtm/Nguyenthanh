"""Phase 5C service: text blocks, association runs, conflict checks, chainage intervals, review, provenance."""
import datetime as dt
import math
import uuid
from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.association import classify as C
from app.association import engine as E
from app.config import get_settings
from app.deps import audit
from app.geometry import measure as M
from app.geometry.measure_service import DB_DP, regions_for, to_prim
from app.models import (Drawing, DrawingPage, DrawingTextBlock, ExtractedItem, GeometryPrimitive, Measurement,
                        TextGeometryAssociation as A, User)
from app.office.service import set_task_status, start_task
from app.takeoff.engine import CalcError

OPEN = ("CANDIDATE", "REVIEW_REQUIRED", "AMBIGUOUS", "CONFLICT")
DOWNSTREAM_OK = ("CONFIRMED",)


class AssocError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now():
    return dt.datetime.now(dt.timezone.utc)


def params() -> E.Params:
    s = get_settings()
    return E.Params(auto_threshold=s.assoc_auto_threshold, review_threshold=s.assoc_review_threshold, margin=s.assoc_margin)


# ---------------------------------------------------------------- text blocks
def _inside(b, r) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] <= cx <= r[2] and r[1] <= cy <= r[3]


def exclusion_regions(db: Session, d: Drawing, page_no: int) -> tuple[list, list]:
    rows = list(db.scalars(select(ExtractedItem).where(ExtractedItem.drawing_id == d.id, ExtractedItem.page_no == page_no,
                                                       ExtractedItem.kind.in_(("table", "region")))))
    tables = [(r.x0, r.y0, r.x1, r.y1) for r in rows if r.kind == "table"]
    titles = [(r.x0, r.y0, r.x1, r.y1) for r in rows if r.kind == "region" and (r.data or {}).get("region_type") == "title_block"]
    return tables, titles


def build_text_blocks(db: Session, d: Drawing) -> int:
    """Creates blocks for text lines that have none yet (stable ids: reviewed associations keep their subjects)."""
    have = set(db.scalars(select(DrawingTextBlock.extracted_item_id).where(DrawingTextBlock.drawing_id == d.id)))
    pages = {p.page_no: p for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id))}
    created = 0
    texts = list(db.scalars(select(ExtractedItem).where(ExtractedItem.drawing_id == d.id, ExtractedItem.kind == "text")))
    by_page = defaultdict(list)
    for t in texts:
        by_page[t.page_no].append(t)
    for page_no, items in by_page.items():
        tables, titles = exclusion_regions(db, d, page_no)
        rot = pages[page_no].rotation if page_no in pages else 0
        counts = Counter(C.normalize(t.text).upper() for t in items)
        for t in items:
            if t.id in have:
                continue
            b = (t.x0, t.y0, t.x1, t.y1)
            c = C.classify(t.text, in_table=any(_inside(b, r) for r in tables), in_title_block=any(_inside(b, r) for r in titles))
            dx, dy = (t.data or {}).get("direction") or (1.0, 0.0)
            flags = list(c.flags) + (["in_table"] if c.text_type == "TABLE" else []) + \
                (["in_title_block"] if any(_inside(b, r) for r in titles) else [])
            db.add(DrawingTextBlock(
                company_id=d.company_id, drawing_id=d.id, page_no=page_no, extracted_item_id=t.id, original_text=t.text,
                normalized_text=c.normalized_text, x0=t.x0, y0=t.y0, x1=t.x1, y1=t.y1, center_x=(t.x0 + t.x1) / 2,
                center_y=(t.y0 + t.y1) / 2, rotation=round((math.degrees(math.atan2(dy, dx)) + rot) % 360, 2),
                font_size=(t.data or {}).get("font_size"), font_name=(t.data or {}).get("font_name"), source=t.source,
                confidence=t.confidence, text_type=c.text_type, values=c.values or None, flags=flags or None,
                encoding=c.encoding, repeat_count=counts[c.normalized_text.upper()], updated_at=_now()))
            created += 1
    db.flush()
    return created


# ---------------------------------------------------------------- run
def _geom_rows(db: Session, d: Drawing, page_no: int) -> list[GeometryPrimitive]:
    return list(db.scalars(select(GeometryPrimitive).where(GeometryPrimitive.drawing_id == d.id, GeometryPrimitive.page_no == page_no,
                                                          GeometryPrimitive.duplicate_of.is_(None), GeometryPrimitive.status != "rejected")))


def _geop(g: GeometryPrimitive) -> E.GeoP:
    return E.GeoP(str(g.id), g.kind, [(float(x), float(y)) for x, y in g.points], g.closed, (g.x0, g.y0, g.x1, g.y1))


def _textb(b: DrawingTextBlock) -> E.TextB:
    return E.TextB(str(b.id), b.text_type, b.normalized_text, (b.x0, b.y0, b.x1, b.y1), b.rotation or 0.0, b.font_size or 10.0, b.flags or [])


def run(db: Session, d: Drawing, user: User | None = None) -> dict:
    build_text_blocks(db, d)
    # keep every engineer-made or engineer-decided association; drop only open rule candidates
    db.execute(delete(A).where(A.drawing_id == d.id, A.origin == "rule", A.status.in_(OPEN), A.decided_by.is_(None)))
    db.flush()
    # chainage intervals are derived from rule candidates: drop the undecided ones nothing references any more
    used = set(db.scalars(select(A.measurement_id).where(A.drawing_id == d.id, A.measurement_id.is_not(None))))
    for m in db.scalars(select(Measurement).where(Measurement.drawing_id == d.id, Measurement.method == "chainage-5C",
                                                  Measurement.status == "computed")):
        if m.id not in used:
            db.delete(m)
    db.flush()
    decided_texts = set(db.scalars(select(A.text_block_id).where(A.drawing_id == d.id)))
    stats = Counter()
    for page in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id).order_by(DrawingPage.page_no)):
        blocks = [b for b in db.scalars(select(DrawingTextBlock).where(DrawingTextBlock.drawing_id == d.id,
                                                                       DrawingTextBlock.page_no == page.page_no))
                  if b.id not in decided_texts]
        stats["text_blocks"] += len(blocks)
        stats["excluded_text_blocks"] += sum(1 for b in blocks if b.text_type in E.EXCLUDED_TYPES)
        geoms = _geom_rows(db, d, page.page_no)
        tables, titles = exclusion_regions(db, d, page.page_no)
        cands = E.associate([_textb(b) for b in blocks], [_geop(g) for g in geoms], params(), tables + titles)
        rows: dict[tuple, A] = {}
        for c in cands:
            a = A(company_id=d.company_id, drawing_id=d.id, page_no=page.page_no, text_block_id=uuid.UUID(c.text_id),
                  geometry_id=uuid.UUID(c.geometry_id), association_type=c.association_type, rank=c.rank, distance=c.distance,
                  angle_difference=c.angle_difference, overlap_ratio=c.overlap_ratio, orientation_match=c.orientation_match,
                  semantic_match=c.semantic_match, relation=c.relation, components=c.components, confidence=c.confidence,
                  status=c.status, reason=c.reason, origin="rule", updated_at=_now())
            db.add(a)
            rows[(c.text_id, c.geometry_id, c.rank)] = a
            stats[f"status_{c.status}"] += 1
        db.flush()
        for c in cands:
            if c.duplicate_of_text:
                primary = next(r for (t, g, k), r in rows.items() if t == c.duplicate_of_text and g == c.geometry_id and k == 1)
                rows[(c.text_id, c.geometry_id, c.rank)].duplicate_of = primary.id
                stats["duplicates"] += 1
        blocks_by_id = {str(b.id): b for b in blocks}
        geoms_by_id = {str(g.id): g for g in geoms}
        for (tid, gid, rank), a in rows.items():
            if rank == 1 and a.association_type == "DIMENSION_OF":
                check_dimension(db, d, page, a, blocks_by_id[tid], geoms_by_id[gid], user)
        stats["chainage_intervals"] += chainage_intervals(db, d, page, [a for (t, g, k), a in rows.items() if k == 1], blocks_by_id,
                                                          geoms_by_id, user)
    stats["conflicts"] = sum(1 for a in db.scalars(select(A).where(A.drawing_id == d.id, A.status == "CONFLICT")))
    db.flush()
    return dict(stats)


def _tolerance(text_m: Decimal) -> Decimal:
    s = get_settings()
    return max(Decimal(s.assoc_conflict_abs_m), abs(text_m) * Decimal(s.assoc_conflict_rel))


def _real_length(db: Session, d: Drawing, page: DrawingPage, g: GeometryPrimitive) -> M.Result | None:
    if g.length_pt is None:
        return None
    return M.measure("length", [to_prim(g)], regions_for(db, d.id, page.page_no), page.scale_ratio, page.scale_status)


def _measurement_for(db: Session, d: Drawing, page: DrawingPage, g: GeometryPrimitive, res: M.Result, user) -> Measurement:
    for m in db.scalars(select(Measurement).where(Measurement.drawing_id == d.id, Measurement.kind == "length",
                                                  Measurement.status != "rejected", Measurement.value_real.is_not(None))):
        if m.geometry_ids == [str(g.id)] and m.scale_ratio == res.scale.ratio:
            return m  # reuse: one measurement per geometry + scale, never a duplicate
    m = Measurement(company_id=d.company_id, drawing_id=d.id, page_no=page.page_no, kind="length", geometry_ids=[str(g.id)],
                    value_paper=res.value_paper.quantize(DB_DP), paper_unit=res.paper_unit, value_real=res.value_real.quantize(DB_DP),
                    real_unit=res.real_unit, scale_ratio=res.scale.ratio, scale_source=res.scale.source, formula=res.formula,
                    details=res.details, method="geometry-5B.1/assoc-5C", note="Tạo tự động khi kiểm tra liên kết chữ ↔ hình học",
                    created_by=user.id if user else None)
    db.add(m)
    db.flush()
    return m


def check_dimension(db: Session, d: Drawing, page: DrawingPage, a: A, b: DrawingTextBlock, g: GeometryPrimitive, user) -> None:
    """Text length vs geometry measured on a CONFIRMED scale. Never corrects either side."""
    length = (b.values or {}).get("length")
    if not length or length.get("ambiguous") or not length.get("value_m"):
        return
    a.text_value = Decimal(length["value_m"]).quantize(DB_DP)
    if a.status == "AMBIGUOUS":  # geometry not determined yet: comparing would be meaningless
        return
    res = _real_length(db, d, page, g)
    if res is None or res.value_real is None:
        a.reason += "; chưa có tỷ lệ xác nhận – chưa kiểm tra xung đột với hình học"
        return
    if a.duplicate_of is None:
        a.measurement_id = _measurement_for(db, d, page, g, res, user).id
    a.measured_value = res.value_real.quantize(DB_DP)
    a.difference = (a.text_value - a.measured_value).quantize(DB_DP)
    if abs(a.difference) > _tolerance(a.text_value):
        a.status = "CONFLICT"
        a.reason = (f"Chữ: {a.text_value.normalize():f} m · Hình học: {a.measured_value.normalize():f} m · "
                    f"Chênh: {abs(a.difference).normalize():f} m – không tự sửa")
    else:
        a.reason += f"; khớp đo đạc (chênh {abs(a.difference).normalize():f} m)"


def chainage_intervals(db: Session, d: Drawing, page: DrawingPage, tops: list[A], blocks: dict, geoms: dict, user) -> int:
    """Interval ONLY for exactly two chainage texts associated (not ambiguous) with the SAME geometry."""
    by_geom = defaultdict(list)
    for a in tops:
        if a.association_type == "CHAINAGE_FOR" and a.status != "AMBIGUOUS" and a.duplicate_of is None:
            by_geom[str(a.geometry_id)].append(a)
    made = 0
    for gid, assocs in by_geom.items():
        if len(assocs) != 2:
            for a in assocs:
                a.reason += "; nhiều hơn 2 lý trình trên cùng hình học – không tự tạo khoảng" if len(assocs) > 2 else ""
            continue
        vals = [Decimal(blocks[str(a.text_block_id)].values["chainage"][0]["meters"]) for a in assocs]
        interval = abs(vals[1] - vals[0])
        g = geoms[gid]
        res = _real_length(db, d, page, g)
        details = {"from_m": str(min(vals)), "to_m": str(max(vals)), "texts": [blocks[str(a.text_block_id)].original_text for a in assocs],
                   "association_ids": [str(a.id) for a in assocs]}
        conflict = None
        if res is not None and res.value_real is not None:
            diff = interval - res.value_real
            details.update(geometry_real_m=str(res.value_real), difference_m=str(diff))
            if abs(diff) > _tolerance(interval):
                conflict = f"Lý trình: {interval.normalize():f} m · Hình học: {res.value_real.normalize():f} m · Chênh: {abs(diff).normalize():f} m"
        m = Measurement(company_id=d.company_id, drawing_id=d.id, page_no=page.page_no, kind="chainage_interval", geometry_ids=[gid],
                        value_paper=(g.length_pt or Decimal(0)).quantize(DB_DP), paper_unit="pt", value_real=interval.quantize(DB_DP),
                        real_unit="m", scale_source="chainage", formula=f"|{max(vals)} − {min(vals)}| m (lý trình)", details=details,
                        method="chainage-5C", note="Khoảng lý trình từ 2 chữ gắn cùng một hình học", created_by=user.id if user else None)
        db.add(m)
        db.flush()
        for a in assocs:
            a.measurement_id = m.id
            a.text_value = interval.quantize(DB_DP)
            if res is not None and res.value_real is not None:
                a.measured_value = res.value_real.quantize(DB_DP)
                a.difference = (interval - res.value_real).quantize(DB_DP)
            if conflict:
                a.status, a.reason = "CONFLICT", conflict + " – không tự sửa"
        made += 1
    return made


def run_with_task(db: Session, user: User, d: Drawing) -> dict:
    if d.status != "processed":
        raise AssocError(409, "Bản vẽ chưa được xử lý thành công")
    task = start_task(db, user, "pdf_drawing", f"Liên kết chữ ↔ hình học: {d.filename} (v{d.version_no})",
                      project_id=d.project_id, entity="drawing_associations", entity_id=d.id)
    db.commit()
    try:
        stats = run(db, d, user)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        task = db.merge(task)
        set_task_status(task, "error", error=f"{type(e).__name__}: {e}"[:2000])
        db.commit()
        raise
    set_task_status(task, "completed", output=f"{stats.get('text_blocks', 0)} khối chữ; " +
                    ", ".join(f"{k}={v}" for k, v in sorted(stats.items()) if k != "text_blocks"))
    audit(db, user, "run_associations", "drawing", d.id, stats)
    db.commit()
    return stats


# ---------------------------------------------------------------- review
def _decide(db: Session, user: User, a: A, status: str, note: str, action: str) -> A:
    a.status, a.decided_by, a.decided_at, a.updated_at = status, user.id, _now(), _now()
    if note:
        a.reason = (a.reason + " | " if a.reason else "") + f"{user.email}: {note}"
    audit(db, user, action, "text_geometry_association", a.id, {"note": note, "geometry_id": str(a.geometry_id)})
    return a


def confirm(db: Session, user: User, a: A, note: str) -> A:
    if a.status == "REJECTED":
        raise AssocError(409, "Liên kết đã bị loại bỏ")
    if a.duplicate_of:
        raise AssocError(409, "Đây là chữ lặp lại – hãy xác nhận liên kết chính")
    if a.status in ("CONFLICT", "AMBIGUOUS") and not note.strip():
        raise AssocError(422, "Liên kết đang xung đột/mơ hồ – cần ghi lý do khi xác nhận")
    for other in db.scalars(select(A).where(A.text_block_id == a.text_block_id, A.id != a.id, A.status != "REJECTED",
                                            A.association_type == a.association_type)):
        _decide(db, user, other, "REJECTED", "kỹ sư chọn liên kết khác", "auto_reject")
    return _decide(db, user, a, "CONFIRMED", note, "confirm")


def reject(db: Session, user: User, a: A, reason: str) -> A:
    if not reason.strip():
        raise AssocError(422, "Cần ghi lý do loại bỏ")
    return _decide(db, user, a, "REJECTED", reason, "reject")


def mark_ambiguous(db: Session, user: User, a: A, reason: str) -> A:
    if not reason.strip():
        raise AssocError(422, "Cần ghi lý do")
    return _decide(db, user, a, "AMBIGUOUS", reason, "mark_ambiguous")


def _engineer_scores(db: Session, b: DrawingTextBlock, g: GeometryPrimitive, atype: str) -> E.Candidate:
    c = E.score(_textb(b), _geop(g), atype, radius=1e9)
    if c is None:  # engineer choice is allowed even when the rule finds the pair incompatible
        m = E.geometric(_textb(b), _geop(g))
        c = E.Candidate(str(b.id), str(g.id), atype, round(m["distance"], 2), m["angle"], round(m["overlap"], 3), False, 0.0,
                        m["relation"], 0.0)
    return c


def _target_geometry(db: Session, a_page: int, drawing_id, gid: uuid.UUID) -> GeometryPrimitive:
    g = db.get(GeometryPrimitive, gid)
    if not g or g.drawing_id != drawing_id or g.page_no != a_page:
        raise AssocError(404, "Hình học không thuộc cùng trang bản vẽ")
    if g.status == "rejected" or g.duplicate_of is not None:
        raise AssocError(409, "Không liên kết với hình học đã loại bỏ hoặc bản trùng")
    return g


def _apply_scores(a: A, c: E.Candidate):
    a.distance, a.angle_difference, a.overlap_ratio = c.distance, c.angle_difference, c.overlap_ratio
    a.orientation_match, a.semantic_match, a.relation, a.confidence = c.orientation_match, c.semantic_match, c.relation, c.confidence
    a.components = c.components or None


def reassign(db: Session, user: User, a: A, new_gid: uuid.UUID, reason: str) -> A:
    if not reason.strip():
        raise AssocError(422, "Cần ghi lý do khi chọn hình học khác")
    g = _target_geometry(db, a.page_no, a.drawing_id, new_gid)
    old = a.geometry_id
    b = db.get(DrawingTextBlock, a.text_block_id)
    _apply_scores(a, _engineer_scores(db, b, g, a.association_type))
    a.geometry_id, a.origin, a.status = g.id, "engineer", "REVIEW_REQUIRED"
    a.measurement_id = a.measured_value = a.difference = None
    a.reason = f"Kỹ sư chọn hình học khác: {reason}"
    a.history = (a.history or []) + [{"old_geometry_id": str(old), "new_geometry_id": str(g.id), "reason": reason,
                                      "user": user.email, "user_id": str(user.id), "timestamp": _now().isoformat()}]
    if a.association_type == "DIMENSION_OF":
        d = db.get(Drawing, a.drawing_id)
        page = db.scalar(select(DrawingPage).where(DrawingPage.drawing_id == d.id, DrawingPage.page_no == a.page_no))
        check_dimension(db, d, page, a, b, g, user)
    a.updated_at = _now()
    audit(db, user, "reassign", "text_geometry_association", a.id, a.history[-1])
    return a


def create_manual(db: Session, user: User, d: Drawing, b: DrawingTextBlock, gid: uuid.UUID, atype: str, reason: str) -> A:
    if atype not in set(E.ASSOC_FOR.values()) | {"SCALE_FOR", "UNKNOWN"}:
        raise AssocError(422, "Loại liên kết không hợp lệ")
    if not reason.strip():
        raise AssocError(422, "Cần ghi lý do")
    g = _target_geometry(db, b.page_no, d.id, gid)
    a = A(company_id=d.company_id, drawing_id=d.id, page_no=b.page_no, text_block_id=b.id, geometry_id=g.id, association_type=atype,
          rank=1, status="REVIEW_REQUIRED", reason=f"Kỹ sư tạo: {reason}", origin="engineer", updated_at=_now())
    _apply_scores(a, _engineer_scores(db, b, g, atype))
    db.add(a)
    db.flush()
    if atype == "DIMENSION_OF":
        page = db.scalar(select(DrawingPage).where(DrawingPage.drawing_id == d.id, DrawingPage.page_no == b.page_no))
        check_dimension(db, d, page, a, b, g, user)
    audit(db, user, "create", "text_geometry_association", a.id, {"text_block_id": str(b.id), "geometry_id": str(g.id), "type": atype})
    return a


def confirmed_for_downstream(db: Session, drawing_id) -> list[A]:
    """The ONLY associations BOQ/geometry quantities may use (Phase 5E): confirmed, not a repeated text."""
    return list(db.scalars(select(A).where(A.drawing_id == drawing_id, A.status.in_(DOWNSTREAM_OK), A.duplicate_of.is_(None))))
