"""Phase 5E-1 API: quantity results of confirmed components (foundation only – no BOQ, no Excel)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.components import get_component
from app.api.drawings import get_drawing
from app.db import get_db
from app.deps import require
from app.models import DrawingComponent, QuantityResult as Q, User
from app.quantity import engine as E
from app.quantity import rules as RR
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
    rule_code: str | None = None  # 5E-2 registry rule (preferred)
    method: str | None = None  # 5E-1 direct method; default: from the component type's measurement kind
    parameters: dict = Field(default_factory=dict)  # e.g. {"unit_weight": {"value": "3.95", "unit": "kg/m", "source": "TCVN …"}}
    precision: int | None = None
    rounding_rule: str | None = None


@router.post("/components/{cid}/quantity/run", status_code=201)
def run(cid: uuid.UUID, body: RunIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    try:
        q = S.run(db, user, c, body.method, body.parameters, body.precision, body.rounding_rule, rule_code=body.rule_code)
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


# ---------------------------------------------------------------- 5E-2: rule registry + whole-drawing runner
@router.get("/quantity-rules")
def list_rules(component_type: str | None = None, user: User = Depends(require("drawing:read"))) -> list[dict]:
    rs = RR.rules_for(component_type.upper()) if component_type else list(RR.registry().values())
    return [{"rule_code": r.rule_code, "component_type": r.component_type, "quantity_type": r.quantity_type, "method": r.method,
             "required_measurements": list(r.required_measurements), "required_parameters": list(r.required_parameters),
             "formula": r.formula, "output_unit": r.output_unit, "validation": r.validation, "auto": r.auto, "note": r.note} for r in rs]


class DrawingRunIn(BaseModel):
    parameters: dict[str, dict] = Field(default_factory=dict)  # {component_id: {param_name: {value, unit, source_type, source_reference}}}


@router.post("/drawings/{did}/quantities/run")
def run_drawing(did: uuid.UUID, body: DrawingRunIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    d = get_drawing(db, did, user)
    try:
        out = S.run_drawing(db, user, d, body.parameters)
    except E.QuantityError as e:
        db.rollback()
        raise _err(e)
    db.commit()
    return out


@router.get("/drawings/{did}/quantity-results")
def drawing_results(did: uuid.UUID, include_superseded: bool = False, user: User = Depends(require("drawing:read")),
                    db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(Q, DrawingComponent).join(DrawingComponent, DrawingComponent.id == Q.component_id).where(Q.drawing_id == d.id)
    if not include_superseded:
        stmt = stmt.where(Q.superseded_by_id.is_(None))
    return [{**S.result_dict(q), "component_type": c.component_type, "component_description": c.description, "page_no": c.page_no}
            for q, c in db.execute(stmt.order_by(DrawingComponent.page_no, Q.created_at))]
