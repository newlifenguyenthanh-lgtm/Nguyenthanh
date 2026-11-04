import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import audit, require
from app.models import Partner, Project, User

router = APIRouter()


class ProjectIn(BaseModel):
    code: str
    name: str
    location: str | None = None
    status: str = "planning"
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    location: str | None = None
    status: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None


def _p(p: Project) -> dict:
    return {"id": str(p.id), "code": p.code, "name": p.name, "location": p.location,
            "status": p.status, "start_date": p.start_date, "end_date": p.end_date}


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: User = Depends(require("project:write")),
                   db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(Project).where(Project.company_id == user.company_id, Project.code == body.code)):
        raise HTTPException(409, "Mã dự án đã tồn tại")
    p = Project(company_id=user.company_id, **body.model_dump())
    db.add(p); db.flush()
    audit(db, user, "create", "project", p.id, body.model_dump(mode="json"))
    db.commit()
    return _p(p)


@router.get("/projects")
def list_projects(q: str | None = None, status: str | None = None,
                  user: User = Depends(require("project:read")), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Project).where(Project.company_id == user.company_id).order_by(Project.code)
    if q:
        stmt = stmt.where(Project.name.ilike(f"%{q}%") | Project.code.ilike(f"%{q}%"))
    if status:
        stmt = stmt.where(Project.status == status)
    return [_p(p) for p in db.scalars(stmt)]


@router.patch("/projects/{pid}")
def update_project(pid: uuid.UUID, body: ProjectPatch, user: User = Depends(require("project:write")),
                   db: Session = Depends(get_db)) -> dict:
    p = db.get(Project, pid)
    if not p or p.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy dự án")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(p, k, v)
    audit(db, user, "update", "project", p.id, {k: str(v) for k, v in changes.items()})
    db.commit()
    return _p(p)


class PartnerIn(BaseModel):
    name: str
    tax_code: str | None = None
    kind: str  # customer | supplier | subcontractor


@router.post("/partners", status_code=201)
def create_partner(body: PartnerIn, user: User = Depends(require("partner:write")),
                   db: Session = Depends(get_db)) -> dict:
    if body.kind not in {"customer", "supplier", "subcontractor"}:
        raise HTTPException(422, "kind không hợp lệ")
    p = Partner(company_id=user.company_id, **body.model_dump())
    db.add(p); db.flush()
    audit(db, user, "create", "partner", p.id, body.model_dump())
    db.commit()
    return {"id": str(p.id), "name": p.name, "kind": p.kind, "tax_code": p.tax_code}


@router.get("/partners")
def list_partners(kind: str | None = None, user: User = Depends(require("partner:read")),
                  db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Partner).where(Partner.company_id == user.company_id).order_by(Partner.name)
    if kind:
        stmt = stmt.where(Partner.kind == kind)
    return [{"id": str(p.id), "name": p.name, "kind": p.kind, "tax_code": p.tax_code} for p in db.scalars(stmt)]
