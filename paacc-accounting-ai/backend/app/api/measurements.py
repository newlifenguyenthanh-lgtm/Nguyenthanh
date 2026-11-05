import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.drawings import get_drawing
from app.db import get_db
from app.deps import audit, require
from app.geometry import measure_service as MS
from app.models import Measurement, ScaleRegion, User

router = APIRouter()


def _err(e: MS.MeasureError):
    return HTTPException(e.status, str(e))


class RegionIn(BaseModel):
    page_no: int
    bbox: list[float] = Field(min_length=4, max_length=4)
    scale_ratio: int = Field(gt=0, le=100000)
    label: str = ""


@router.post("/drawings/{did}/scale-regions", status_code=201)
def create_region(did: uuid.UUID, body: RegionIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    d = get_drawing(db, did, user)
    try:
        MS.page_of(db, d.id, body.page_no)
    except MS.MeasureError as e:
        raise _err(e)
    x0, y0, x1, y1 = body.bbox
    if x1 <= x0 or y1 <= y0:
        raise HTTPException(422, "Vùng không hợp lệ")
    r = ScaleRegion(company_id=d.company_id, drawing_id=d.id, page_no=body.page_no, x0=x0, y0=y0, x1=x1, y1=y1,
                    scale_ratio=body.scale_ratio, label=body.label, created_by=user.id)
    db.add(r); db.flush()
    audit(db, user, "create", "scale_region", r.id, body.model_dump())
    db.commit()
    return MS.region_dict(r)


@router.get("/drawings/{did}/scale-regions")
def list_regions(did: uuid.UUID, page: int | None = None, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(ScaleRegion).where(ScaleRegion.drawing_id == d.id)
    if page:
        stmt = stmt.where(ScaleRegion.page_no == page)
    return [MS.region_dict(r) for r in db.scalars(stmt.order_by(ScaleRegion.page_no, ScaleRegion.created_at))]


class DecisionIn(BaseModel):
    note: str = ""


@router.post("/scale-regions/{rid}/{decision}")
def decide_region(rid: uuid.UUID, decision: str, body: DecisionIn, user: User = Depends(require("drawing:write")),
                  db: Session = Depends(get_db)) -> dict:
    r = db.get(ScaleRegion, rid)
    if not r or r.company_id != user.company_id or decision not in ("confirm", "reject"):
        raise HTTPException(404, "Không tìm thấy vùng tỷ lệ")
    if decision == "reject" and not body.note.strip():
        raise HTTPException(422, "Cần ghi lý do")
    r.status = "confirmed" if decision == "confirm" else "rejected"
    r.note, r.decided_by, r.decided_at = body.note, user.id, dt.datetime.now(dt.timezone.utc)
    audit(db, user, decision, "scale_region", r.id, {"note": body.note, "scale_ratio": r.scale_ratio})
    db.commit()
    return MS.region_dict(r)


class MeasureIn(BaseModel):
    drawing_id: uuid.UUID
    kind: str
    geometry_ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)
    note: str = ""


@router.post("/measurements", status_code=201)
def create_measurement(body: MeasureIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    d = get_drawing(db, body.drawing_id, user)
    try:
        m = MS.run_measure(db, user, d, body.kind, body.geometry_ids, body.note)
    except MS.MeasureError as e:
        raise _err(e)
    db.commit()
    return MS.measurement_dict(m)


def get_measurement(db: Session, mid: uuid.UUID, user: User) -> Measurement:
    m = db.get(Measurement, mid)
    if not m or m.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy phép đo")
    return m


@router.get("/measurements/{mid}")
def one(mid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    return MS.measurement_dict(get_measurement(db, mid, user))


@router.get("/drawings/{did}/measurements")
def list_measurements(did: uuid.UUID, page: int | None = None, user: User = Depends(require("drawing:read")),
                      db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(Measurement).where(Measurement.drawing_id == d.id)
    if page:
        stmt = stmt.where(Measurement.page_no == page)
    return [MS.measurement_dict(m) for m in db.scalars(stmt.order_by(Measurement.created_at))]


@router.post("/measurements/{mid}/{decision}")
def decide_measurement(mid: uuid.UUID, decision: str, body: DecisionIn, user: User = Depends(require("drawing:write")),
                       db: Session = Depends(get_db)) -> dict:
    if decision not in ("confirm", "reject"):
        raise HTTPException(404, "Không hợp lệ")
    m = get_measurement(db, mid, user)
    try:
        MS.decide(db, user, m, "confirmed" if decision == "confirm" else "rejected", body.note)
    except MS.MeasureError as e:
        raise _err(e)
    db.commit()
    return MS.measurement_dict(m)
