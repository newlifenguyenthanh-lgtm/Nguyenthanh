"""Builds an Excel export for a BOQ, stores it immutably and records the export (Milestone 4E)."""
import datetime as dt
import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.boq.excel import ExportItem, ExportMeta, build_workbook
from app.deps import audit
from app.models import (Boq, BoqExport, BoqItem, BoqSource, Company, DocumentVersion, Drawing, DrawingPage, ExtractedItem,
                        Project, User)
from app.storage import save_bytes
from app.takeoff.engine import MODULES

VN_TZ = dt.timezone(dt.timedelta(hours=7))  # Asia/Ho_Chi_Minh (no DST)


def _vn(t: dt.datetime | None) -> str:
    if not t:
        return ""
    t = t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60] or "BOQ"


def export_boq(db: Session, user: User, boq: Boq) -> BoqExport:
    items = list(db.scalars(select(BoqItem).where(BoqItem.boq_id == boq.id).order_by(BoqItem.item_no)))
    sources = list(db.scalars(select(BoqSource).where(BoqSource.boq_id == boq.id)))
    drawings = {s.drawing_id: db.get(Drawing, s.drawing_id) for s in sources}
    labels: dict = {}
    sheet: dict = {}  # (drawing_id, page_no) -> drawing number printed on that page
    src_meta = []
    for s in sources:
        d = drawings[s.drawing_id]
        pages = list(db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id).order_by(DrawingPage.page_no)))
        for p in pages:
            sheet[(d.id, p.page_no)] = p.drawing_number or f"{d.filename} tr.{p.page_no}"
        labels[d.id] = ", ".join(dict.fromkeys(p.drawing_number for p in pages if p.drawing_number)) or d.filename
        ver = db.get(DocumentVersion, s.document_version_id)
        src_meta.append({"label": labels[d.id], "filename": d.filename, "version_no": ver.version_no, "sha256": d.sha256,
                         "pages": d.page_count, "drawing_id": str(d.id)})
    rows = []
    for i in items:
        first_src = (i.source_item_ids or [None])[0]
        src = db.get(ExtractedItem, uuid.UUID(first_src)) if first_src else None
        if src and src.kind == "table" and "cell" in (i.inputs.get("quantity") or {}):
            r, c = i.inputs["quantity"]["cell"]
            src_text = " | ".join((src.data or {}).get("rows", [[]])[r]) if r < len((src.data or {}).get("rows", [])) else src.text
        else:
            src_text = src.text if src else ""
        labels_i = {f.name: f.label_vi for f in MODULES[i.module].fields} if i.module else {"quantity": "Khối lượng (bảng thống kê)"}
        rows.append(ExportItem(
            item_no=i.item_no, category=i.category, description=i.description, spec=i.spec, unit=i.unit,
            quantity=None if i.quantity is None else str(i.quantity), module=i.module, excel_expr=i.excel_expr,
            calc_inputs=i.calc_inputs or {}, input_labels=labels_i, input_meta=i.inputs or {}, waste_factor=str(i.waste_factor),
            formula_text=i.formula_text, review_status=i.review_status, origin=i.origin, notes=i.notes, flags=i.flags or [],
            drawing_label=sheet.get((i.drawing_id, i.page_no), labels.get(i.drawing_id, "")) if i.drawing_id else "Kỹ sư nhập",
            page_no=i.page_no, bbox=i.bbox,
            source_text=src_text, item_id=str(i.id), unit_system=i.unit_system))
    project = db.get(Project, boq.project_id) if boq.project_id else None
    now = dt.datetime.now(dt.timezone.utc)
    submitted_by = db.get(User, boq.submitted_by) if boq.submitted_by else None
    decided_by = db.get(User, boq.decided_by) if boq.decided_by else None
    meta = ExportMeta(company=db.get(Company, boq.company_id).name, title=boq.title, version_no=boq.version_no, status=boq.status,
                      project=f"{project.code} – {project.name}" if project else "", rules=boq.rules,
                      submitted=f"{submitted_by.email} – {_vn(boq.submitted_at)}" if submitted_by else "",
                      decided=f"{decided_by.email} – {_vn(boq.decided_at)}" if decided_by else "",
                      decision_note=boq.decision_note, exported_by=user.email, exported_at=_vn(now), sources=src_meta)
    data = build_workbook(meta, rows)
    digest, key = save_bytes(str(user.company_id), data)
    suffix = "" if boq.status == "approved" else "_NHAP"
    slug = _slug(boq.title)
    filename = f"{'' if slug.upper().startswith('BOQ') else 'BOQ_'}{slug}_v{boq.version_no}{suffix}_{now.astimezone(VN_TZ).strftime('%Y%m%d_%H%M%S')}.xlsx"
    exp = BoqExport(company_id=boq.company_id, boq_id=boq.id, project_id=boq.project_id, boq_version_no=boq.version_no,
                    boq_status=boq.status, filename=filename, sha256=digest, size_bytes=len(data), storage_key=key,
                    item_count=len(items), created_by=user.id)
    db.add(exp)
    db.flush()
    audit(db, user, "export", "boq", boq.id, {"export_id": str(exp.id), "sha256": digest, "status": boq.status, "version_no": boq.version_no})
    return exp


def export_dict(e: BoqExport) -> dict:
    return {"id": str(e.id), "boq_id": str(e.boq_id), "project_id": str(e.project_id) if e.project_id else None,
            "boq_version_no": e.boq_version_no, "boq_status": e.boq_status, "filename": e.filename, "sha256": e.sha256,
            "size_bytes": e.size_bytes, "item_count": e.item_count, "created_by": str(e.created_by) if e.created_by else None,
            "created_at": e.created_at.isoformat() if e.created_at else None}
