import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import audit, require
from app.domain.contracts import adjusted_value
from app.models import Contract, ContractAppendix, Partner, Project, User

router = APIRouter()


class ContractIn(BaseModel):
    project_id: uuid.UUID
    partner_id: uuid.UUID
    number: str
    title: str = ""
    direction: str = Field(pattern="^(outbound|inbound)$")
    original_value: Decimal = Field(ge=0)


class AppendixIn(BaseModel):
    number: str
    delta_value: Decimal
    reason: str = ""


def _own(db: Session, model, id_, user: User):
    obj = db.get(model, id_)
    if not obj or obj.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy dữ liệu")
    return obj


def _c(c: Contract) -> dict:
    return {"id": str(c.id), "number": c.number, "title": c.title, "direction": c.direction,
            "project_id": str(c.project_id), "partner_id": str(c.partner_id),
            "original_value": str(c.original_value), "status": c.status}


@router.post("/contracts", status_code=201)
def create_contract(body: ContractIn, user: User = Depends(require("contract:write")),
                    db: Session = Depends(get_db)) -> dict:
    _own(db, Project, body.project_id, user)
    _own(db, Partner, body.partner_id, user)
    c = Contract(company_id=user.company_id, **body.model_dump())
    db.add(c); db.flush()
    audit(db, user, "create", "contract", c.id, body.model_dump(mode="json"))
    db.commit()
    return _c(c)


@router.get("/contracts")
def list_contracts(project_id: uuid.UUID | None = None, user: User = Depends(require("contract:read")),
                   db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Contract).where(Contract.company_id == user.company_id).order_by(Contract.number)
    if project_id:
        stmt = stmt.where(Contract.project_id == project_id)
    return [_c(c) for c in db.scalars(stmt)]


@router.post("/contracts/{cid}/appendices", status_code=201)
def create_appendix(cid: uuid.UUID, body: AppendixIn, user: User = Depends(require("contract:write")),
                    db: Session = Depends(get_db)) -> dict:
    c = _own(db, Contract, cid, user)
    a = ContractAppendix(company_id=user.company_id, contract_id=c.id, **body.model_dump())
    db.add(a); db.flush()
    audit(db, user, "create", "contract_appendix", a.id, body.model_dump(mode="json"))
    db.commit()
    return {"id": str(a.id), "status": a.status}


@router.post("/appendices/{aid}/{decision}")
def decide_appendix(aid: uuid.UUID, decision: str, user: User = Depends(require("contract:approve")),
                    db: Session = Depends(get_db)) -> dict:
    if decision not in {"approve", "reject"}:
        raise HTTPException(404, "Không hợp lệ")
    a = _own(db, ContractAppendix, aid, user)
    if a.status != "draft":
        raise HTTPException(409, "Phụ lục đã được xử lý")
    a.status = "approved" if decision == "approve" else "rejected"
    a.approved_by = user.id
    audit(db, user, decision, "contract_appendix", a.id, {"delta_value": str(a.delta_value)})
    db.commit()
    return {"id": str(a.id), "status": a.status}


@router.get("/contracts/{cid}/summary")
def contract_summary(cid: uuid.UUID, user: User = Depends(require("contract:read")),
                     db: Session = Depends(get_db)) -> dict:
    c = _own(db, Contract, cid, user)
    apps = list(db.scalars(select(ContractAppendix).where(ContractAppendix.contract_id == c.id)))
    approved = sum((a.delta_value for a in apps if a.status == "approved"), Decimal("0"))
    return {"original_value": str(c.original_value), "approved_appendix_value": str(approved),
            "adjusted_value": str(adjusted_value(c.original_value, [(a.delta_value, a.status) for a in apps])),
            "pending_appendices": sum(1 for a in apps if a.status == "draft")}
