"""Phase 5E-1 API: quantity results of confirmed components (foundation only – no BOQ, no Excel)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.components import get_component
from app.db import get_db
from app.deps import require
from app.models import QuantityResult as Q, User
from app.quantity import engine as E
from app.quantity import service as S

router = APIRouter()


def _err(e: E.QuantityError):
    return HTTPException(e.status, str(e))


def get_result(db: Session, qid: uuid.UUID, user: User) -> Q:
    q = db.get(Q, qid)
    if not q or q.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy kết quả khối lượng")
    return q


@router.get("/components/{cid}/quantity-results")
def list_results(cid: uuid.UUID, include_superseded: bool = False, user: User = Depends(require("drawing:read")),
                 db: Session = Depends(get_db)) -> list[dict]:
    c = get_component(db, cid, user)
    stmt = select(Q).where(Q.component_id == c.id)
    if not include_superseded:
        stmt = stmt.where(Q.superseded_by_id.is_(None))
    return [S.result_dict(q) for q in db.scalars(stmt.order_by(Q.quantity_type, Q.version))]


class RunIn(BaseModel):
    method: str | None = None  # default: from the component type's measurement kind
    parameters: dict = Field(default_factory=dict)  # e.g. {"unit_weight": {"value": "3.95", "unit": "kg/m", "source": "TCVN …"}}
    precision: int | None = None
    rounding_rule: str | None = None


@router.post("/components/{cid}/quantity/run", status_code=201)
def run(cid: uuid.UUID, body: RunIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    try:
        q = S.run(db, user, c, body.method, body.parameters, body.precision, body.rounding_rule)
    except E.QuantityError as e:
        db.rollback()
        raise _err(e)
    db.commit()
    return {**S.result_dict(q), "provenance": S.provenance(db, q)}


@router.get("/quantity-results/{qid}")
def one(qid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    q = get_result(db, qid, user)
    return {**S.result_dict(q), "provenance": S.provenance(db, q)}


class ReviewIn(BaseModel):
    decision: str
    note: str = ""


@router.post("/quantity-results/{qid}/review")
def review(qid: uuid.UUID, body: ReviewIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    q = get_result(db, qid, user)
    try:
        S.review(db, user, q, body.decision, body.note)
    except E.QuantityError as e:
        db.rollback()
        raise _err(e)
    db.commit()
    return S.result_dict(q)
