import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import audit, require
from app.models import Document, DocumentVersion, Drawing, DrawingPage, ExtractedItem, User
from app.pdf import service
from app.pdf.extract import PdfError, render_page_png
from app.storage import open_path

router = APIRouter()


def analysis_hook():
    """Post-extraction steps inside the same processing task: 4B text analysis, 5A vector geometry, 5C association candidates,
    5D component candidates.
    A geometry failure never fails the drawing: affected pages get geometry_status='failed'."""
    from app.config import get_settings
    from app.geometry.service import extract_into
    from app.pdf.analysis_service import analyze_drawing

    def run(db: Session, d: Drawing, extraction=None):
        analyze_drawing(db, d, extraction)
        if get_settings().geometry_on_process:
            db.flush()
            try:
                with db.begin_nested():
                    extract_into(db, d)
            except Exception as e:  # noqa: BLE001
                for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id)):
                    p.geometry_status, p.geometry_stats = "failed", {"error": f"{type(e).__name__}: {e}"[:500]}
        if get_settings().geometry_on_process and get_settings().association_on_process:
            # 5C: candidates only (never confirmed here); a failure leaves the drawing processed without associations
            from app.association.service import run as associate
            db.flush()
            try:
                with db.begin_nested():
                    stats = associate(db, d)
            except Exception as e:  # noqa: BLE001
                stats = {"error": f"{type(e).__name__}: {e}"[:500]}
            for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id)):
                p.geometry_stats = {**(p.geometry_stats or {}), "association": stats}
            if get_settings().component_on_process and "error" not in stats:
                # 5D: component CANDIDATES only (never confirmed here); a failure never fails the drawing
                from app.components.service import run as recognise
                db.flush()
                try:
                    with db.begin_nested():
                        cstats = recognise(db, d)
                except Exception as e:  # noqa: BLE001
                    cstats = {"error": f"{type(e).__name__}: {e}"[:500]}
                for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id)):
                    p.geometry_stats = {**(p.geometry_stats or {}), "components": cstats}
    return run


class DrawingIn(BaseModel):
    document_id: uuid.UUID
    version_no: int | None = None  # default: current version


def drawing_dict(d: Drawing) -> dict:
    return {"id": str(d.id), "document_id": str(d.document_id), "document_version_id": str(d.document_version_id),
            "version_no": d.version_no, "project_id": str(d.project_id) if d.project_id else None,
            "filename": d.filename, "sha256": d.sha256, "status": d.status, "page_count": d.page_count,
            "metadata": d.pdf_metadata or {}, "findings": d.findings or [],
            "duplicate_of_drawing_id": str(d.duplicate_of_drawing_id) if d.duplicate_of_drawing_id else None,
            "error_code": d.error_code, "error_message": d.error_message,
            "ai_task_id": str(d.ai_task_id) if d.ai_task_id else None,
            "processed_at": d.processed_at.isoformat() if d.processed_at else None}


def page_dict(p: DrawingPage) -> dict:
    out = {c: getattr(p, c) for c in ("page_no", "width_pt", "height_pt", "rotation", "kind", "text_chars",
                                      "image_coverage", "vector_paths", "ocr_used", "ocr_engine", "ocr_mean_confidence")}
    out["warnings"] = p.warnings or []
    for c in ("drawing_number", "title", "revision", "title_fields", "disciplines", "view_types", "scale_candidates",
              "scale_status", "scale_ratio", "units_candidates", "units_status", "units", "geometry_status", "geometry_stats", "page_frame"):
        out[c] = getattr(p, c)
    out["calibrated_at"] = p.calibrated_at.isoformat() if p.calibrated_at else None
    out["calibrated_by"] = str(p.calibrated_by) if p.calibrated_by else None
    return out


def item_dict(i: ExtractedItem) -> dict:
    return {"id": str(i.id), "page_no": i.page_no, "kind": i.kind, "text": i.text, "bbox": [i.x0, i.y0, i.x1, i.y1],
            "source": i.source, "confidence": i.confidence, "data": i.data or {}}


def get_drawing(db: Session, did: uuid.UUID, user: User) -> Drawing:
    d = db.get(Drawing, did)
    if not d or d.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy bản vẽ")
    return d


@router.post("/drawings", status_code=201)
def create_and_process(body: DrawingIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    doc = db.get(Document, body.document_id)
    if not doc or doc.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy tài liệu")
    n = body.version_no or doc.current_version
    ver = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.version_no == n))
    if not ver:
        raise HTTPException(404, "Không tìm thấy phiên bản tài liệu")
    existing = db.scalar(select(Drawing).where(Drawing.document_version_id == ver.id, Drawing.status != "failed"))
    if existing:
        raise HTTPException(409, {"message": "Phiên bản này đã được phân tích", "drawing_id": str(existing.id)})
    d = service.create_drawing(db, user, doc, ver)
    audit(db, user, "create", "drawing", d.id, {"document_id": str(doc.id), "version_no": n})
    db.commit()
    return drawing_dict(service.process_drawing(db, user, d, analysis_hook()))


@router.get("/drawings")
def list_drawings(project_id: uuid.UUID | None = None, document_id: uuid.UUID | None = None, status: str | None = None,
                  user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Drawing).where(Drawing.company_id == user.company_id).order_by(Drawing.created_at.desc())
    for col, val in ((Drawing.project_id, project_id), (Drawing.document_id, document_id), (Drawing.status, status)):
        if val:
            stmt = stmt.where(col == val)
    return [drawing_dict(d) for d in db.scalars(stmt)]


@router.get("/drawings/{did}")
def get_one(did: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    d = get_drawing(db, did, user)
    pages = db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id).order_by(DrawingPage.page_no))
    counts = dict(db.execute(select(ExtractedItem.kind, func.count()).where(ExtractedItem.drawing_id == d.id)
                             .group_by(ExtractedItem.kind)).all())
    title = db.get(Document, d.document_id).title
    return {**drawing_dict(d), "document_title": title, "pages": [page_dict(p) for p in pages], "item_counts": counts}


@router.get("/drawings/{did}/items")
def list_items(did: uuid.UUID, page: int | None = None, kind: str | None = None, q: str | None = None,
               limit: int = Query(500, le=5000), offset: int = 0,
               user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(ExtractedItem).where(ExtractedItem.drawing_id == d.id)
    if page:
        stmt = stmt.where(ExtractedItem.page_no == page)
    if kind:
        stmt = stmt.where(ExtractedItem.kind.in_(kind.split(",")))
    if q:
        stmt = stmt.where(ExtractedItem.text.ilike(f"%{q}%"))
    stmt = stmt.order_by(ExtractedItem.page_no, ExtractedItem.y0, ExtractedItem.x0).limit(limit).offset(offset)
    return [item_dict(i) for i in db.scalars(stmt)]


class CalibrationIn(BaseModel):
    scale_ratio: int | None = Field(None, gt=0, le=100000)
    not_to_scale: bool = False
    units: str | None = Field(None, pattern="^(mm|cm|m)$")
    note: str = ""


@router.post("/drawings/{did}/pages/{n}/calibration")
def calibrate(did: uuid.UUID, n: int, body: CalibrationIn, user: User = Depends(require("drawing:write")),
              db: Session = Depends(get_db)) -> dict:
    """Human confirmation of scale/units. Detected candidates are never applied automatically."""
    d = get_drawing(db, did, user)
    p = db.scalar(select(DrawingPage).where(DrawingPage.drawing_id == d.id, DrawingPage.page_no == n))
    if not p:
        raise HTTPException(404, "Trang không tồn tại")
    if body.scale_ratio is None and not body.not_to_scale and body.units is None:
        raise HTTPException(422, "Cần xác nhận tỷ lệ, 'không theo tỷ lệ' hoặc đơn vị")
    if body.scale_ratio and body.not_to_scale:
        raise HTTPException(422, "Không thể vừa có tỷ lệ vừa 'không theo tỷ lệ'")
    before = {"scale_status": p.scale_status, "scale_ratio": p.scale_ratio, "units_status": p.units_status, "units": p.units}
    warnings = []
    if body.scale_ratio or body.not_to_scale:
        detected = {c["ratio"] for c in (p.scale_candidates or [])}
        if body.scale_ratio and detected and body.scale_ratio not in detected:
            warnings.append("scale_differs_from_detected")
        p.scale_ratio = body.scale_ratio
        p.scale_status = "not_to_scale" if body.not_to_scale else "confirmed"
    if body.units:
        detected_u = {c["unit"] for c in (p.units_candidates or [])}
        if detected_u and body.units not in detected_u:
            warnings.append("units_differ_from_detected")
        p.units, p.units_status = body.units, "confirmed"
    p.calibrated_by, p.calibrated_at = user.id, dt.datetime.now(dt.timezone.utc)
    audit(db, user, "calibrate", "drawing_page", p.id, {"drawing_id": str(d.id), "page_no": n, "before": before,
          "after": {"scale_status": p.scale_status, "scale_ratio": p.scale_ratio, "units": p.units},
          "warnings": warnings, "note": body.note})
    db.commit()
    return {**page_dict(p), "warnings": (p.warnings or []) + warnings}


@router.get("/drawing-sheets")
def find_sheets(number: str, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    """All processed pages carrying a drawing number (revision history across uploads)."""
    rows = db.execute(select(DrawingPage, Drawing).join(Drawing, Drawing.id == DrawingPage.drawing_id).where(
        DrawingPage.company_id == user.company_id, DrawingPage.drawing_number == number).order_by(Drawing.created_at)).all()
    return [{"drawing_id": str(d.id), "page_no": p.page_no, "revision": p.revision, "title": p.title,
             "document_id": str(d.document_id), "version_no": d.version_no, "sha256": d.sha256, "status": d.status}
            for p, d in rows]


@router.get("/drawings/{did}/pages/{n}/image")
def page_image(did: uuid.UUID, n: int, dpi: int = Query(100, ge=20, le=200),
               user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> Response:
    d = get_drawing(db, did, user)
    data = open_path(db.get(DocumentVersion, d.document_version_id).storage_key).read_bytes()
    try:
        png = render_page_png(data, n, dpi)
    except PdfError as e:
        raise HTTPException(404, str(e))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})
