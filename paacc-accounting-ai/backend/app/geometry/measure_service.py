"""Phase 5B service: load primitives + scale context, run the pure engine, persist, review."""
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import audit
from app.geometry import measure as M
from app.models import Drawing, DrawingPage, GeometryPrimitive, Measurement, ScaleRegion, User
from app.takeoff.engine import CalcError


DB_DP = Decimal("0.000001")  # column scale Numeric(24,6): identical responses before/after a DB round trip


class MeasureError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def to_prim(g: GeometryPrimitive) -> M.Prim:
    return M.Prim(str(g.id), g.kind, [(Decimal(x), Decimal(y)) for x, y in g.points], g.closed,
                  g.length_pt, g.area_pt2, (Decimal(str(g.x0)), Decimal(str(g.y0)), Decimal(str(g.x1)), Decimal(str(g.y1))))


def regions_for(db: Session, drawing_id, page_no: int) -> list[M.ScaleRegion]:
    rows = db.scalars(select(ScaleRegion).where(ScaleRegion.drawing_id == drawing_id, ScaleRegion.page_no == page_no,
                                                ScaleRegion.status == "confirmed"))
    return [M.ScaleRegion(str(r.id), tuple(Decimal(str(v)) for v in (r.x0, r.y0, r.x1, r.y1)), r.scale_ratio) for r in rows]


def page_of(db: Session, drawing_id, page_no: int) -> DrawingPage:
    p = db.scalar(select(DrawingPage).where(DrawingPage.drawing_id == drawing_id, DrawingPage.page_no == page_no))
    if p is None:
        raise MeasureError(404, "Trang không tồn tại")
    return p


def run_measure(db: Session, user: User, d: Drawing, kind: str, geometry_ids: list[uuid.UUID], note: str = "") -> Measurement:
    if kind not in M.KINDS:
        raise MeasureError(422, f"Loại phép đo phải là một trong {M.KINDS}")
    rows = [db.get(GeometryPrimitive, g) for g in dict.fromkeys(geometry_ids)]
    if not rows or any(r is None or r.drawing_id != d.id for r in rows):
        raise MeasureError(404, "Không tìm thấy đối tượng hình học trong bản vẽ này")
    pages = {r.page_no for r in rows}
    if len(pages) != 1:
        raise MeasureError(422, "Một phép đo chỉ dùng đối tượng trên cùng một trang")
    bad = [r for r in rows if r.status == "rejected" or r.duplicate_of is not None]
    if bad:
        raise MeasureError(409, "Không đo trên hình học đã loại bỏ hoặc bản trùng lặp")
    page = page_of(db, d.id, pages.pop())
    try:
        res = M.measure(kind, [to_prim(r) for r in rows], regions_for(db, d.id, page.page_no), page.scale_ratio, page.scale_status)
    except CalcError as e:
        raise MeasureError(422, str(e))
    m = Measurement(company_id=d.company_id, drawing_id=d.id, page_no=page.page_no, kind=kind, geometry_ids=[str(r.id) for r in rows],
                    value_paper=res.value_paper.quantize(DB_DP), paper_unit=res.paper_unit,
                    value_real=None if res.value_real is None else res.value_real.quantize(DB_DP), real_unit=res.real_unit,
                    scale_ratio=res.scale.ratio if res.scale else None, scale_source=res.scale.source if res.scale else None,
                    formula=res.formula, details=res.details, note=note, created_by=user.id)
    db.add(m)
    db.flush()
    audit(db, user, "measure", "measurement", m.id, {"kind": kind, "geometry_ids": m.geometry_ids, "real": str(res.value_real)})
    return m


def decide(db: Session, user: User, m: Measurement, status: str, note: str) -> Measurement:
    if status not in ("confirmed", "rejected"):
        raise MeasureError(422, "Trạng thái không hợp lệ")
    if status == "rejected" and not note.strip():
        raise MeasureError(422, "Cần ghi lý do loại bỏ")
    if status == "confirmed" and m.value_real is None and m.kind != "count":
        raise MeasureError(409, "Chưa có giá trị thật (tỷ lệ chưa xác nhận) – không thể xác nhận phép đo")
    m.status, m.note, m.decided_by, m.decided_at = status, note or m.note, user.id, dt.datetime.now(dt.timezone.utc)
    audit(db, user, status, "measurement", m.id, {"note": note})
    return m


def measurement_dict(m: Measurement) -> dict:
    return {"id": str(m.id), "drawing_id": str(m.drawing_id), "page_no": m.page_no, "kind": m.kind, "geometry_ids": m.geometry_ids,
            "value_paper": str(m.value_paper), "paper_unit": m.paper_unit,
            "value_real": None if m.value_real is None else str(m.value_real), "real_unit": m.real_unit,
            "scale_ratio": m.scale_ratio, "scale_source": m.scale_source, "formula": m.formula, "details": m.details or {},
            "method": m.method, "status": m.status, "note": m.note}


def region_dict(r: ScaleRegion) -> dict:
    return {"id": str(r.id), "page_no": r.page_no, "bbox": [r.x0, r.y0, r.x1, r.y1], "scale_ratio": r.scale_ratio,
            "label": r.label, "status": r.status, "note": r.note}
