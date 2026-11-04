import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import audit, require
from app.models import Document, DocumentVersion, Project, User
from app.storage import open_path, safe_filename, save_bytes

router = APIRouter()
KINDS = {"drawing", "boq", "quote", "contract", "email", "other"}


async def _read(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "File quá lớn")
    if not data:
        raise HTTPException(422, "File rỗng")
    return data


def _v(v: DocumentVersion) -> dict:
    return {"version_no": v.version_no, "filename": v.filename, "size_bytes": v.size_bytes,
            "sha256": v.sha256, "note": v.note, "content_type": v.content_type,
            "uploaded_by": str(v.uploaded_by), "created_at": v.created_at}


def _d(d: Document) -> dict:
    return {"id": str(d.id), "title": d.title, "kind": d.kind, "project_id": str(d.project_id) if d.project_id else None,
            "current_version": d.current_version}


def _doc(db: Session, did: uuid.UUID, user: User) -> Document:
    d = db.get(Document, did)
    if not d or d.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy tài liệu")
    return d


def _duplicate_of(db: Session, user: User, digest: str, exclude: uuid.UUID | None = None) -> str | None:
    stmt = select(DocumentVersion.document_id).where(
        DocumentVersion.company_id == user.company_id, DocumentVersion.sha256 == digest)
    if exclude:
        stmt = stmt.where(DocumentVersion.document_id != exclude)
    r = db.scalars(stmt).first()
    return str(r) if r else None


async def _add_version(db, user, doc, file, note) -> tuple[DocumentVersion, str | None]:
    data = await _read(file)
    digest, key = save_bytes(str(user.company_id), data)
    dup = _duplicate_of(db, user, digest, exclude=doc.id)
    last = db.scalar(select(func.max(DocumentVersion.version_no)).where(DocumentVersion.document_id == doc.id)) or 0
    v = DocumentVersion(company_id=user.company_id, document_id=doc.id, version_no=last + 1,
                        filename=safe_filename(file.filename or "file"), size_bytes=len(data), sha256=digest,
                        storage_key=key, note=note, uploaded_by=user.id,
                        content_type=file.content_type or "application/octet-stream")
    db.add(v)
    doc.current_version = v.version_no
    db.flush()
    audit(db, user, "upload", "document_version", v.id, {"document_id": str(doc.id), "version": v.version_no, "sha256": digest})
    return v, dup


@router.post("/documents", status_code=201)
async def create_document(title: str = Form(...), kind: str = Form("other"), project_id: uuid.UUID | None = Form(None),
                          note: str = Form(""), file: UploadFile = File(...),
                          user: User = Depends(require("document:write")), db: Session = Depends(get_db)) -> dict:
    if kind not in KINDS:
        raise HTTPException(422, "kind không hợp lệ")
    if project_id:
        p = db.get(Project, project_id)
        if not p or p.company_id != user.company_id:
            raise HTTPException(404, "Không tìm thấy dự án")
    doc = Document(company_id=user.company_id, title=title, kind=kind, project_id=project_id, current_version=0)
    db.add(doc); db.flush()
    v, dup = await _add_version(db, user, doc, file, note)
    db.commit()
    return {**_d(doc), "version": _v(v), "duplicate_of_document_id": dup}


@router.post("/documents/{did}/versions", status_code=201)
async def upload_version(did: uuid.UUID, note: str = Form(""), file: UploadFile = File(...),
                         user: User = Depends(require("document:write")), db: Session = Depends(get_db)) -> dict:
    doc = _doc(db, did, user)
    v, dup = await _add_version(db, user, doc, file, note)
    db.commit()
    return {**_d(doc), "version": _v(v), "duplicate_of_document_id": dup}


@router.get("/documents")
def list_documents(project_id: uuid.UUID | None = None, kind: str | None = None, q: str | None = None,
                   user: User = Depends(require("document:read")), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Document).where(Document.company_id == user.company_id).order_by(Document.created_at.desc())
    if project_id:
        stmt = stmt.where(Document.project_id == project_id)
    if kind:
        stmt = stmt.where(Document.kind == kind)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q}%"))
    return [_d(d) for d in db.scalars(stmt)]


@router.get("/documents/{did}/versions")
def list_versions(did: uuid.UUID, user: User = Depends(require("document:read")), db: Session = Depends(get_db)) -> list[dict]:
    _doc(db, did, user)
    rows = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == did).order_by(DocumentVersion.version_no))
    return [_v(v) for v in rows]


@router.get("/documents/{did}/versions/{n}/download")
def download(did: uuid.UUID, n: int, user: User = Depends(require("document:read")), db: Session = Depends(get_db)):
    _doc(db, did, user)
    v = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == did, DocumentVersion.version_no == n))
    if not v:
        raise HTTPException(404, "Không tìm thấy phiên bản")
    audit(db, user, "download", "document_version", v.id); db.commit()
    return FileResponse(open_path(v.storage_key), media_type=v.content_type, filename=v.filename)
