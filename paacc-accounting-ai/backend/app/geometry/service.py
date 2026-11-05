"""Persistence + orchestration of vector geometry extraction (Phase 5A).

Runs inside the existing drawing-processing task (no separate progress system) or on demand with its own
ai_tasks row. Designed to move to a background worker later: the unit of work is one page, and the function
only needs (drawing id, user) - see docs/PHASE5_GEOMETRY_ARCHITECTURE.md.
"""
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.deps import audit
from app.geometry.primitives import PageGeometry, extract_page_geometry
from app.models import DocumentVersion, Drawing, DrawingPage, GeometryPrimitive, User
from app.office.service import set_task_status, start_task
from app.storage import open_path


class GeometryError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def reviewed_count(db: Session, d: Drawing) -> int:
    return db.scalar(select(func.count()).select_from(GeometryPrimitive).where(
        GeometryPrimitive.drawing_id == d.id, GeometryPrimitive.status != "extracted")) or 0


def persist_page(db: Session, d: Drawing, page: DrawingPage, g: PageGeometry) -> int:
    ids = [uuid.uuid4() for _ in g.primitives]
    rows = []
    for i, p in enumerate(g.primitives):
        x0, y0, x1, y1 = p.bbox
        rows.append(GeometryPrimitive(
            id=ids[i], company_id=d.company_id, drawing_id=d.id, page_no=page.page_no, kind=p.kind,
            points=[[str(x), str(y)] for x, y in p.points], closed=p.closed, x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1),
            length_pt=p.length_pt.quantize(Decimal("0.0001")) if p.length_pt is not None else None,
            area_pt2=p.area_pt2.quantize(Decimal("0.0001")) if p.area_pt2 is not None else None,
            stroke_width=p.stroke_width, stroke_color=p.stroke_color, fill_color=p.fill_color, layer=p.layer,
            path_index=p.path_index, item_index=p.item_index, derived_from=p.derived_from, approximate=p.approximate,
            flags=p.flags or None, duplicate_of=ids[p.duplicate_of] if p.duplicate_of is not None else None,
            overlaps=[str(ids[j]) for j in p.overlaps] or None, extra=p.extra or None))
    db.add_all(r for r in rows if r.duplicate_of is None)
    db.flush()  # originals first: duplicates reference them
    db.add_all(r for r in rows if r.duplicate_of is not None)
    page.geometry_status, page.geometry_stats = g.status, {**g.stats, "warnings": g.warnings}
    page.page_frame = g.frame.as_dict()
    return len(rows)


def extract_into(db: Session, d: Drawing, data: bytes | None = None) -> dict:
    """Extract all pages of a processed drawing. Replaces previous unreviewed geometry."""
    import pymupdf
    if reviewed_count(db, d):
        raise GeometryError(409, "Đã có hình học được kỹ sư xác nhận/loại bỏ – không ghi đè")
    db.execute(delete(GeometryPrimitive).where(GeometryPrimitive.drawing_id == d.id))
    pages = {p.page_no: p for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id))}
    data = data or open_path(db.get(DocumentVersion, d.document_version_id).storage_key).read_bytes()
    totals = {"pages": 0, "primitives": 0, "by_status": {}}
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for n in range(doc.page_count):
            page = pages.get(n + 1)
            if page is None:
                continue
            try:
                g = extract_page_geometry(doc[n], n + 1, page.kind)
                totals["primitives"] += persist_page(db, d, page, g)
                status = g.status
            except Exception as e:  # noqa: BLE001 - one bad page must not lose the others
                page.geometry_status, page.geometry_stats = "failed", {"error": f"{type(e).__name__}: {e}"[:500]}
                status = "failed"
            totals["pages"] += 1
            totals["by_status"][status] = totals["by_status"].get(status, 0) + 1
            db.flush()
    return totals


def run_extraction(db: Session, user: User, d: Drawing) -> dict:
    """On-demand (re-)extraction with its own ai_tasks row (agent pdf_drawing)."""
    if d.status != "processed":
        raise GeometryError(409, "Bản vẽ chưa được xử lý thành công")
    task = start_task(db, user, "pdf_drawing", f"Trích xuất hình học vector: {d.filename} (v{d.version_no})",
                      project_id=d.project_id, entity="drawing_geometry", entity_id=d.id)
    db.commit()
    try:
        totals = extract_into(db, d)
    except GeometryError:
        db.rollback()
        task = db.merge(task)
        set_task_status(task, "cancelled", error="Không ghi đè hình học đã được kiểm tra")
        db.commit()
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        task = db.merge(task)
        set_task_status(task, "error", error=f"{type(e).__name__}: {e}"[:2000])
        db.commit()
        raise
    set_task_status(task, "completed", output=f"{totals['primitives']} đối tượng hình học trên {totals['pages']} trang ({totals['by_status']})")
    audit(db, user, "extract_geometry", "drawing", d.id, totals)
    db.commit()
    return totals


def review(db: Session, user: User, prim: GeometryPrimitive, status: str, note: str) -> GeometryPrimitive:
    if status not in ("confirmed", "rejected", "ambiguous", "extracted"):
        raise GeometryError(422, "Trạng thái không hợp lệ")
    if status in ("rejected", "ambiguous") and not note.strip():
        raise GeometryError(422, "Cần ghi lý do")
    before = prim.status
    prim.status, prim.review_note = status, note
    prim.reviewed_by, prim.reviewed_at = user.id, dt.datetime.now(dt.timezone.utc)
    audit(db, user, "review_geometry", "geometry_primitive", prim.id, {"from": before, "to": status, "note": note})
    return prim
