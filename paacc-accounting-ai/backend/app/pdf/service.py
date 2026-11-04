"""Drawing processing pipeline: read the stored (immutable) file, extract, persist, report via ai_tasks."""
import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import audit
from app.models import Document, DocumentVersion, Drawing, DrawingPage, ExtractedItem, User
from app.office.service import set_task_status, start_task
from app.pdf.extract import ExtractionResult, PdfError, extract_pdf
from app.pdf.ocr import OcrEngine, default_ocr
from app.storage import open_path

# Hook so tests (and future deployments) can choose the OCR engine. None -> default_ocr().
OCR_FACTORY = None


def get_ocr() -> OcrEngine | None:
    if not get_settings().ocr_enabled:
        return None
    return OCR_FACTORY() if OCR_FACTORY else default_ocr()


def create_drawing(db: Session, user: User, doc: Document, ver: DocumentVersion) -> Drawing:
    dup = db.scalar(select(Drawing).where(Drawing.company_id == user.company_id, Drawing.sha256 == ver.sha256,
                                          Drawing.document_id != doc.id).order_by(Drawing.created_at))
    d = Drawing(company_id=user.company_id, project_id=doc.project_id, document_id=doc.id, document_version_id=ver.id,
                version_no=ver.version_no, sha256=ver.sha256, filename=ver.filename, created_by=user.id,
                duplicate_of_drawing_id=dup.id if dup else None)
    db.add(d)
    db.flush()
    return d


def persist_extraction(db: Session, d: Drawing, r: ExtractionResult) -> None:
    db.execute(delete(ExtractedItem).where(ExtractedItem.drawing_id == d.id))
    db.execute(delete(DrawingPage).where(DrawingPage.drawing_id == d.id))
    for p in r.pages:
        db.add(DrawingPage(company_id=d.company_id, drawing_id=d.id, page_no=p.page_no, width_pt=p.width,
                           height_pt=p.height, rotation=p.rotation, kind=p.kind, text_chars=p.text_chars,
                           image_coverage=p.image_coverage, vector_paths=p.vector_paths, ocr_used=p.ocr_used,
                           ocr_engine=p.ocr_engine, ocr_mean_confidence=p.ocr_mean_confidence, warnings=p.warnings))
        for ln in p.lines:
            db.add(ExtractedItem(company_id=d.company_id, drawing_id=d.id, page_no=p.page_no, kind="text",
                                 text=ln.text[:4000], x0=ln.bbox[0], y0=ln.bbox[1], x1=ln.bbox[2], y1=ln.bbox[3],
                                 source=ln.source, confidence=ln.confidence,
                                 data={"direction": list(ln.direction), "font_size": ln.font_size}))
        for t in p.tables:
            db.add(ExtractedItem(company_id=d.company_id, drawing_id=d.id, page_no=p.page_no, kind="table",
                                 text=" | ".join(" ; ".join(r) for r in t.rows)[:4000],
                                 x0=t.bbox[0], y0=t.bbox[1], x1=t.bbox[2], y1=t.bbox[3], source="text",
                                 confidence=None, data={"rows": t.rows}))
    d.page_count, d.pdf_metadata = r.page_count, r.metadata


def process_drawing(db: Session, user: User, d: Drawing, analyze=None) -> Drawing:
    """Runs synchronously. Status is mirrored to an ai_tasks row (agent pdf_drawing) so the office shows it.
    `analyze(db, drawing, extraction)` is an optional post-extraction step (Milestone 4B)."""
    task = start_task(db, user, "pdf_drawing", f"Phân tích bản vẽ: {d.filename} (v{d.version_no})",
                      project_id=d.project_id, entity="drawing", entity_id=d.id)
    d.ai_task_id, d.status = task.id, "processing"
    db.commit()
    s = get_settings()
    try:
        data = open_path(db.get(DocumentVersion, d.document_version_id).storage_key).read_bytes()
        r = extract_pdf(data, get_ocr(), min_text_chars=s.ocr_min_text_chars, ocr_dpi=s.ocr_dpi,
                        max_ocr_side_px=s.ocr_max_side_px, max_pages=s.pdf_max_pages)
        persist_extraction(db, d, r)
        if analyze:
            analyze(db, d, r)
    except PdfError as e:
        db.rollback()
        d, task = db.merge(d), db.merge(task)
        d.status, d.error_code, d.error_message = "failed", e.code, str(e)
        set_task_status(task, "error", error=str(e))
        audit(db, user, "process_failed", "drawing", d.id, {"code": e.code})
        db.commit()
        return d
    except Exception as e:  # noqa: BLE001 - never leave a task "running" forever
        db.rollback()
        d, task = db.merge(d), db.merge(task)
        d.status, d.error_code, d.error_message = "failed", "internal_error", f"{type(e).__name__}: {e}"[:2000]
        set_task_status(task, "error", error=d.error_message)
        audit(db, user, "process_failed", "drawing", d.id, {"code": "internal_error"})
        db.commit()
        return d
    d.status, d.processed_at = "processed", dt.datetime.now(dt.timezone.utc)
    kinds = [p.kind for p in r.pages]
    lines = sum(len(p.lines) for p in r.pages)
    set_task_status(task, "completed", output=f"{r.page_count} trang ({', '.join(sorted(set(kinds)))}); "
                                              f"{lines} dòng chữ; {sum(len(p.tables) for p in r.pages)} bảng")
    audit(db, user, "process", "drawing", d.id, {"pages": r.page_count, "kinds": kinds})
    db.commit()
    return d
