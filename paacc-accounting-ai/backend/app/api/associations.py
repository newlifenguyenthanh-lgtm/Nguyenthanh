"""Phase 5C API: text blocks, text ↔ geometry associations, review actions, provenance chain."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.drawings import get_drawing
from app.api.geometry import prim_dict
from app.api.measurements import get_measurement
from app.association import service as S
from app.db import get_db
from app.deps import require
from app.geometry.measure_service import measurement_dict
from app.models import DrawingTextBlock, GeometryPrimitive, Measurement, TextGeometryAssociation as A, User

router = APIRouter()


def _err(e: S.AssocError):
    return HTTPException(e.status, str(e))


def _s(v):
    return None if v is None else f"{v.normalize():f}"


def block_dict(b: DrawingTextBlock) -> dict:
    return {"id": str(b.id), "page_no": b.page_no, "extracted_item_id": str(b.extracted_item_id),
            "original_text": b.original_text, "normalized_text": b.normalized_text, "bbox": [b.x0, b.y0, b.x1, b.y1],
            "center": [b.center_x, b.center_y], "rotation": b.rotation, "font_size": b.font_size, "font_name": b.font_name,
            "source": b.source, "confidence": b.confidence, "text_type": b.text_type, "values": b.values or {},
            "flags": b.flags or [], "encoding": b.encoding, "repeat_count": b.repeat_count}


def assoc_dict(a: A) -> dict:
    return {"id": str(a.id), "drawing_id": str(a.drawing_id), "page_no": a.page_no, "text_block_id": str(a.text_block_id),
            "geometry_id": str(a.geometry_id), "association_type": a.association_type, "rank": a.rank,
            "distance": a.distance, "angle_difference": a.angle_difference, "overlap_ratio": a.overlap_ratio,
            "orientation_match": a.orientation_match, "semantic_match": a.semantic_match, "relation": a.relation,
            "components": a.components or {}, "confidence": a.confidence, "status": a.status, "reason": a.reason,
            "origin": a.origin, "duplicate_of": str(a.duplicate_of) if a.duplicate_of else None,
            "measurement_id": str(a.measurement_id) if a.measurement_id else None,
            "text_value": _s(a.text_value), "measured_value": _s(a.measured_value), "difference": _s(a.difference),
            "unit": "m" if a.text_value is not None else None, "history": a.history or [],
            "decided_by": str(a.decided_by) if a.decided_by else None,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None}


def get_assoc(db: Session, aid: uuid.UUID, user: User) -> A:
    a = db.get(A, aid)
    if not a or a.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy liên kết")
    return a


@router.get("/drawings/{did}/pages/{page_no}/text-blocks")
def text_blocks(did: uuid.UUID, page_no: int, text_type: str | None = None, user: User = Depends(require("drawing:read")),
                db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(DrawingTextBlock).where(DrawingTextBlock.drawing_id == d.id, DrawingTextBlock.page_no == page_no)
    if text_type:
        stmt = stmt.where(DrawingTextBlock.text_type == text_type.upper())
    return [block_dict(b) for b in db.scalars(stmt.order_by(DrawingTextBlock.y0, DrawingTextBlock.x0))]


@router.get("/drawings/{did}/pages/{page_no}/associations")
def page_associations(did: uuid.UUID, page_no: int, status: str | None = None, text_block_id: uuid.UUID | None = None,
                      geometry_id: uuid.UUID | None = None, user: User = Depends(require("drawing:read")),
                      db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(A).where(A.drawing_id == d.id, A.page_no == page_no)
    if status:
        stmt = stmt.where(A.status == status.upper())
    if text_block_id:
        stmt = stmt.where(A.text_block_id == text_block_id)
    if geometry_id:
        stmt = stmt.where(A.geometry_id == geometry_id)
    return [assoc_dict(a) for a in db.scalars(stmt.order_by(A.text_block_id, A.rank))]


@router.post("/drawings/{did}/associations/run")
def run(did: uuid.UUID, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    d = get_drawing(db, did, user)
    try:
        return S.run_with_task(db, user, d)
    except S.AssocError as e:
        raise _err(e)


class CreateIn(BaseModel):
    text_block_id: uuid.UUID
    geometry_id: uuid.UUID
    association_type: str
    reason: str = ""


@router.post("/associations", status_code=201)
def create(body: CreateIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    b = db.get(DrawingTextBlock, body.text_block_id)
    if not b or b.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy khối chữ")
    d = get_drawing(db, b.drawing_id, user)
    try:
        a = S.create_manual(db, user, d, b, body.geometry_id, body.association_type.upper(), body.reason)
    except S.AssocError as e:
        raise _err(e)
    db.commit()
    return assoc_dict(a)


@router.get("/associations/{aid}")
def one(aid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    """Provenance chain: TEXT -> ASSOCIATION -> GEOMETRY -> MEASUREMENT."""
    a = get_assoc(db, aid, user)
    g = db.get(GeometryPrimitive, a.geometry_id)
    m = db.get(Measurement, a.measurement_id) if a.measurement_id else None
    return {**assoc_dict(a), "provenance": {"text": block_dict(db.get(DrawingTextBlock, a.text_block_id)),
                                            "association": {"id": str(a.id), "type": a.association_type, "status": a.status,
                                                            "confidence": a.confidence, "origin": a.origin},
                                            "geometry": prim_dict(g), "measurement": measurement_dict(m) if m else None,
                                            "downstream_allowed": a.status == "CONFIRMED" and a.duplicate_of is None}}


class ReassignIn(BaseModel):
    geometry_id: uuid.UUID
    reason: str = ""


@router.patch("/associations/{aid}")
def reassign(aid: uuid.UUID, body: ReassignIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    a = get_assoc(db, aid, user)
    try:
        S.reassign(db, user, a, body.geometry_id, body.reason)
    except S.AssocError as e:
        raise _err(e)
    db.commit()
    return assoc_dict(a)


class NoteIn(BaseModel):
    note: str = ""


@router.post("/associations/{aid}/confirm")
def confirm(aid: uuid.UUID, body: NoteIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    a = get_assoc(db, aid, user)
    try:
        S.confirm(db, user, a, body.note)
    except S.AssocError as e:
        raise _err(e)
    db.commit()
    return assoc_dict(a)


@router.post("/associations/{aid}/reject")
def reject(aid: uuid.UUID, body: NoteIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    a = get_assoc(db, aid, user)
    try:
        S.reject(db, user, a, body.note)
    except S.AssocError as e:
        raise _err(e)
    db.commit()
    return assoc_dict(a)


@router.post("/associations/{aid}/mark-ambiguous")
def mark_ambiguous(aid: uuid.UUID, body: NoteIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    a = get_assoc(db, aid, user)
    try:
        S.mark_ambiguous(db, user, a, body.note)
    except S.AssocError as e:
        raise _err(e)
    db.commit()
    return assoc_dict(a)


@router.get("/measurements/{mid}/associations")
def measurement_associations(mid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    m = get_measurement(db, mid, user)
    return [assoc_dict(a) for a in db.scalars(select(A).where(A.measurement_id == m.id).order_by(A.created_at))]
