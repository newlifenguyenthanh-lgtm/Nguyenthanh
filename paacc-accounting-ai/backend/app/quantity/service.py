"""Phase 5E-1 service: run a quantity for a CONFIRMED component, versioning, review, provenance."""
import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import audit
from app.models import (ComponentRepeatGroup, ComponentSource, ComponentType, DrawingComponent, DrawingTextBlock, GeometryPrimitive,
                        Measurement, QuantityResult as Q, TextGeometryAssociation, User)
from app.quantity import engine as E
from app.quantity.units import UnitError

STATUSES = ("DRAFT", "CALCULATED", "REQUIRES_REVIEW", "CONFIRMED", "REJECTED", "BLOCKED")
TRANSITIONS = {  # nothing goes to a BOQ from here; 5F reads CONFIRMED, non-superseded results only
    "DRAFT": {"CALCULATED", "REQUIRES_REVIEW", "BLOCKED"},  # set by the engine inside one run
    "CALCULATED": {"CONFIRMED", "REJECTED"},
    "REQUIRES_REVIEW": {"REJECTED"},  # fix the inputs (confirm the measurement / add a sourced parameter) and re-run
    "BLOCKED": {"REJECTED"},
    "CONFIRMED": {"REJECTED"},  # withdrawal needs a reason
    "REJECTED": set(),
}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _d(v):
    return None if v is None else f"{v.normalize():f}"


def run(db: Session, user: User, c: DrawingComponent, method: str | None, parameters: dict, precision: int | None,
        rounding_rule: str | None) -> Q:
    if c.status != "CONFIRMED":
        raise E.QuantityError(422, f"Cấu kiện đang {c.status} – chỉ cấu kiện CONFIRMED mới được tính khối lượng")
    if c.representation_of_id:
        raise E.QuantityError(422, "Đây là biểu diễn (chi tiết/mặt cắt) của cấu kiện khác – tính trên cấu kiện chính")
    mids = [s.measurement_id for s in db.scalars(select(ComponentSource).where(ComponentSource.component_id == c.id,
                                                                               ComponentSource.measurement_id.is_not(None)))]
    ms = [m for m in (db.get(Measurement, i) for i in dict.fromkeys(mids)) if m]
    if method is None:
        t = db.get(ComponentType, c.component_type_id) if c.component_type_id else None
        kind = (t.boq or {}).get("measurement_kind") if t else None
        method = E.DEFAULT_METHOD.get(kind or "")
        if not method:
            raise E.QuantityError(422, "Loại cấu kiện chưa có phương pháp tính mặc định – chọn phương pháp")
    grp = db.get(ComponentRepeatGroup, c.repeat_group_id) if c.repeat_group_id else None
    s = get_settings()
    try:
        calc = E.calculate(method, [E.MeasIn(str(m.id), m.kind, m.value_real, m.real_unit, m.status, m.details or {}) for m in ms],
                           parameters, precision=s.quantity_precision if precision is None else precision,
                           rounding_rule=rounding_rule or s.quantity_rounding, group_status=grp.pattern_status if grp else None)
    except (ValueError, UnitError) as e:
        raise E.QuantityError(getattr(e, "status", 422), str(e))
    prev = list(db.scalars(select(Q).where(Q.component_id == c.id, Q.quantity_type == calc.quantity_type,
                                           Q.calculation_method == calc.method, Q.superseded_by_id.is_(None))))
    version = (db.scalar(select(func.max(Q.version)).where(Q.component_id == c.id, Q.quantity_type == calc.quantity_type,
                                                           Q.calculation_method == calc.method)) or 0) + 1
    used = [m for m in ms if str(m.id) in calc.input_measurement_ids]
    q = Q(company_id=c.company_id, project_id=c.project_id, drawing_id=c.drawing_id, page_id=c.page_id, component_id=c.id,
          measurement_id=used[0].id if used else None, input_measurement_ids=calc.input_measurement_ids, quantity_type=calc.quantity_type,
          unit=calc.unit, precision=calc.precision, rounding_rule=calc.rounding_rule, calculation_method=calc.method, formula=calc.formula,
          parameters=calc.parameters or None, status="DRAFT", version=version, created_by=user.id, updated_at=_now(),
          source_component={"id": str(c.id), "component_type": c.component_type, "status": c.status, "specification": c.specification,
                            "repeat_group_status": grp.pattern_status if grp else None},
          source_measurement=[{"id": str(m.id), "kind": m.kind, "value_real": _d(m.value_real), "real_unit": m.real_unit,
                               "status": m.status, "scale_ratio": m.scale_ratio, "scale_source": m.scale_source} for m in used])
    db.add(q)
    db.flush()
    _set(q, calc.status)  # DRAFT -> CALCULATED | REQUIRES_REVIEW | BLOCKED (validated)
    q.raw_value, q.quantity_value, q.reason = calc.raw, calc.value, "; ".join(calc.reasons)[:2000]
    for p in prev:
        p.superseded_by_id, p.updated_at = q.id, _now()
    audit(db, user, "quantity_run", "quantity_result", q.id,
          {"component_id": str(c.id), "method": calc.method, "status": q.status, "raw": _d(calc.raw), "value": _d(calc.value),
           "unit": calc.unit, "inputs": calc.input_measurement_ids, "supersedes": [str(p.id) for p in prev]})
    return q


def _set(q: Q, to: str) -> None:
    if to not in TRANSITIONS.get(q.status, set()):
        raise E.QuantityError(409, f"Không thể chuyển {q.status} → {to}")
    q.status, q.updated_at = to, _now()


def review(db: Session, user: User, q: Q, decision: str, note: str) -> Q:
    to = {"confirm": "CONFIRMED", "reject": "REJECTED"}.get(decision)
    if not to:
        raise E.QuantityError(422, "Quyết định phải là confirm hoặc reject")
    if to == "REJECTED" and not note.strip():
        raise E.QuantityError(422, "Cần ghi lý do loại bỏ")
    if to == "CONFIRMED":
        if q.superseded_by_id:
            raise E.QuantityError(409, "Kết quả đã có phiên bản mới hơn")
        c = db.get(DrawingComponent, q.component_id)
        if c.status != "CONFIRMED":
            raise E.QuantityError(422, f"Cấu kiện nguồn đang {c.status} – không xác nhận khối lượng")
    src = q.status
    _set(q, to)
    q.reviewed_by, q.reviewed_at = user.id, _now()
    if note:
        q.reason = ((q.reason + " | ") if q.reason else "") + f"{user.email}: {note}"
    audit(db, user, f"quantity_{decision}", "quantity_result", q.id, {"from": src, "to": to, "note": note})
    return q


def provenance(db: Session, q: Q) -> dict:
    """Quantity -> component -> measurement(s) -> geometry -> text / association -> drawing page."""
    srcs = list(db.scalars(select(ComponentSource).where(ComponentSource.component_id == q.component_id)))
    ms = []
    for mid in q.input_measurement_ids:
        m = db.get(Measurement, uuid.UUID(mid))
        if m:
            ms.append({"id": str(m.id), "kind": m.kind, "value_real": _d(m.value_real), "real_unit": m.real_unit, "status": m.status,
                       "geometry_ids": m.geometry_ids, "scale_source": m.scale_source, "formula": m.formula})
    geo_ids = list(dict.fromkeys([g for m in ms for g in m["geometry_ids"]] + [str(s.geometry_id) for s in srcs if s.geometry_id]))
    texts = [db.get(DrawingTextBlock, s.text_block_id) for s in srcs if s.text_block_id]
    assocs = [db.get(TextGeometryAssociation, s.association_id) for s in srcs if s.association_id]
    c = db.get(DrawingComponent, q.component_id)
    pages = {g.page_no for g in (db.get(GeometryPrimitive, uuid.UUID(i)) for i in geo_ids) if g}
    return {"quantity_result_id": str(q.id), "component": {"id": str(c.id), "type": c.component_type, "status": c.status},
            "measurements": ms, "geometry_ids": geo_ids,
            "texts": [{"id": str(t.id), "original_text": t.original_text} for t in texts if t],
            "association_ids": [str(a.id) for a in assocs if a],
            "drawing": {"drawing_id": str(q.drawing_id), "page_id": str(q.page_id), "page_no": c.page_no, "geometry_pages": sorted(pages)}}


def result_dict(q: Q) -> dict:
    return {"id": str(q.id), "component_id": str(q.component_id), "drawing_id": str(q.drawing_id), "page_id": str(q.page_id),
            "project_id": str(q.project_id) if q.project_id else None, "measurement_id": str(q.measurement_id) if q.measurement_id else None,
            "input_measurement_ids": q.input_measurement_ids, "quantity_type": q.quantity_type, "raw_value": _d(q.raw_value),
            "quantity_value": _d(q.quantity_value), "unit": q.unit, "precision": q.precision, "rounding_rule": q.rounding_rule,
            "calculation_method": q.calculation_method, "formula": q.formula, "parameters": q.parameters or {},
            "source_component": q.source_component, "source_measurement": q.source_measurement, "status": q.status, "reason": q.reason,
            "version": q.version, "superseded_by_id": str(q.superseded_by_id) if q.superseded_by_id else None,
            "created_by": str(q.created_by) if q.created_by else None, "reviewed_by": str(q.reviewed_by) if q.reviewed_by else None,
            "created_at": q.created_at.isoformat() if q.created_at else None, "updated_at": q.updated_at.isoformat() if q.updated_at else None,
            "reviewed_at": q.reviewed_at.isoformat() if q.reviewed_at else None}
