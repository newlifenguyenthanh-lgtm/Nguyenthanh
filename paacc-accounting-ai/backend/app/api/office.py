import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.registry import AGENTS
from app.db import get_db
from app.deps import audit, require
from app.models import AITask, Department, DepartmentMember, Project, User
from app.office.service import ensure_departments, overview, set_task_status, start_task, task_dict
from app.office.status import TASK_STATUSES, can_transition

router = APIRouter()


@router.get("/office/overview")
def office_overview(user: User = Depends(require("office:read")), db: Session = Depends(get_db)) -> dict:
    return {"departments": overview(db, user)}


@router.get("/office/departments/{code}")
def office_department(code: str, user: User = Depends(require("office:read")), db: Session = Depends(get_db)) -> dict:
    rows = overview(db, user, detail_code=code)
    if not rows:
        raise HTTPException(404, "Không tìm thấy phòng ban")
    return rows[0]


class MemberIn(BaseModel):
    user_id: uuid.UUID
    job_title: str = ""


@router.post("/office/departments/{code}/members", status_code=201)
def add_member(code: str, body: MemberIn, user: User = Depends(require("office:manage")),
               db: Session = Depends(get_db)) -> dict:
    dept = next((d for d in ensure_departments(db, user.company_id) if d.code == code), None)
    target = db.get(User, body.user_id)
    if dept is None or target is None or target.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy phòng ban hoặc người dùng")
    if db.scalar(select(DepartmentMember).where(DepartmentMember.department_id == dept.id,
                                                DepartmentMember.user_id == target.id)):
        raise HTTPException(409, "Người dùng đã thuộc phòng ban")
    m = DepartmentMember(company_id=user.company_id, department_id=dept.id, user_id=target.id, job_title=body.job_title)
    db.add(m); db.flush()
    audit(db, user, "assign", "department_member", m.id, {"department": code, "user_id": str(target.id)})
    db.commit()
    return {"id": str(m.id)}


class TaskIn(BaseModel):
    agent_key: str
    title: str
    requires_approval: bool = False
    project_id: uuid.UUID | None = None


class TaskStatusIn(BaseModel):
    status: str
    output_summary: str = ""
    error_message: str = ""


def _task(db: Session, tid: uuid.UUID, user: User) -> AITask:
    t = db.get(AITask, tid)
    if not t or t.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy tác vụ")
    return t


@router.post("/ai-tasks", status_code=201)
def create_task(body: TaskIn, user: User = Depends(require("ai_task:write")), db: Session = Depends(get_db)) -> dict:
    if body.agent_key not in AGENTS:
        raise HTTPException(422, "Agent không tồn tại")
    if body.project_id:
        p = db.get(Project, body.project_id)
        if not p or p.company_id != user.company_id:
            raise HTTPException(404, "Không tìm thấy dự án")
    t = start_task(db, user, body.agent_key, body.title, status="queued",
                   requires_approval=body.requires_approval, project_id=body.project_id)
    audit(db, user, "create", "ai_task", t.id, {"agent": body.agent_key, "title": body.title})
    db.commit()
    return task_dict(t)


@router.get("/ai-tasks")
def list_tasks(department: str | None = None, status: str | None = None,
               user: User = Depends(require("office:read")), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(AITask).where(AITask.company_id == user.company_id).order_by(AITask.created_at.desc()).limit(200)
    if department:
        stmt = stmt.where(AITask.department_code == department)
    if status:
        stmt = stmt.where(AITask.status == status)
    return [task_dict(t) for t in db.scalars(stmt)]


@router.post("/ai-tasks/{tid}/status")
def change_status(tid: uuid.UUID, body: TaskStatusIn, user: User = Depends(require("ai_task:write")),
                  db: Session = Depends(get_db)) -> dict:
    t = _task(db, tid, user)
    if body.status not in TASK_STATUSES or not can_transition(t.status, body.status):
        raise HTTPException(409, f"Không thể chuyển trạng thái {t.status} → {body.status}")
    if body.status == "completed" and t.requires_approval:
        raise HTTPException(409, "Tác vụ cần phê duyệt: chuyển sang 'waiting_approval'")
    src = t.status
    set_task_status(t, body.status, output=body.output_summary, error=body.error_message)
    audit(db, user, "status", "ai_task", t.id, {"from": src, "to": body.status})
    db.commit()
    return task_dict(t)


@router.post("/ai-tasks/{tid}/{decision}")
def decide_task(tid: uuid.UUID, decision: str, user: User = Depends(require("ai_task:approve")),
                db: Session = Depends(get_db)) -> dict:
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "Không hợp lệ")
    t = _task(db, tid, user)
    if t.status != "waiting_approval":
        raise HTTPException(409, "Tác vụ không ở trạng thái chờ phê duyệt")
    if t.entity == "boq":  # business approval: delegate so BOQ status, four-eyes rule and audit stay consistent
        from app.boq import workflow as W
        from app.models import Boq
        boq = db.get(Boq, t.entity_id)
        try:
            W.decide(db, user, boq, "approve" if decision == "approve" else "return",
                     "" if decision == "approve" else "Trả lại từ trung tâm tác vụ")
        except W.BoqError as e:
            db.rollback()
            raise HTTPException(e.status, str(e))
        db.commit()
        return task_dict(t)
    set_task_status(t, "completed" if decision == "approve" else "cancelled",
                    error="" if decision == "approve" else f"Bị từ chối bởi {user.email}")
    t.decided_by = user.id
    audit(db, user, decision, "ai_task", t.id)
    db.commit()
    return task_dict(t)
