import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.registry import AGENTS
from app.models import (AITask, AuditLog, Boq, Contract, ContractAppendix, Department, DepartmentMember, Document,
                        Drawing, DrawingPage, GeometryPrimitive, Project, User)
from app.office.catalog import CATALOG, DEFAULT_DEPARTMENTS, default_layout
from app.office.status import TaskView, agent_status, combine, utc

ACTIVE = ("queued", "running", "waiting_approval")


def ensure_departments(db: Session, company_id: uuid.UUID) -> list[Department]:
    rows = list(db.scalars(select(Department).where(Department.company_id == company_id).order_by(Department.sort_order)))
    if rows:
        return rows
    for i, (code, name, color, *_rest) in enumerate(DEFAULT_DEPARTMENTS):
        db.add(Department(company_id=company_id, code=code, name_vi=name, sort_order=i, color=color, layout=default_layout(i)))
    db.commit()
    return list(db.scalars(select(Department).where(Department.company_id == company_id).order_by(Department.sort_order)))


def task_dict(t: AITask) -> dict:
    return {"id": str(t.id), "agent_key": t.agent_key, "department_code": t.department_code, "title": t.title,
            "status": t.status, "requires_approval": t.requires_approval, "error_message": t.error_message,
            "output_summary": t.output_summary, "project_id": str(t.project_id) if t.project_id else None,
            "created_at": utc(t.created_at).isoformat() if t.created_at else None,
            "finished_at": utc(t.finished_at).isoformat() if t.finished_at else None}


def _pending_business_approvals(db: Session, company_id: uuid.UUID) -> dict[str, int]:
    appendices = db.scalar(select(func.count()).select_from(ContractAppendix).where(
        ContractAppendix.company_id == company_id, ContractAppendix.status == "draft")) or 0
    return {"contract_payment": appendices}


def _count(db, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def _metrics(db: Session, cid: uuid.UUID, code: str, pending_total: int, now: dt.datetime) -> list[dict]:
    """Only counts from existing tables. Empty list = module not built yet."""
    def docs(kind):
        return _count(db, select(Document.id).where(Document.company_id == cid, Document.kind == kind))
    projects = select(Project.id).where(Project.company_id == cid)
    m: list[tuple[str, str, object]] = []
    if code == "board":
        m = [("projects", "Tổng số dự án", _count(db, projects)),
             ("active_projects", "Dự án đang thi công", _count(db, projects.where(Project.status == "active"))),
             ("pending_approvals", "Chờ phê duyệt (toàn công ty)", pending_total)]
    elif code == "bidding":
        m = [("quote_docs", "Tài liệu báo giá", docs("quote")), ("email_docs", "Email lưu trữ", docs("email"))]
    elif code == "engineering_qs":
        drw = lambda st: _count(db, select(Drawing.id).where(Drawing.company_id == cid, Drawing.status == st))
        boq = lambda *st: _count(db, select(Boq.id).where(Boq.company_id == cid, Boq.status.in_(st)))
        m = [("drawing_docs", "Bản vẽ", docs("drawing")),
             ("drawings_processing", "Bản vẽ đang phân tích", drw("processing")),
             ("drawings_processed", "Bản vẽ đã phân tích", drw("processed")),
             ("drawings_failed", "Bản vẽ phân tích lỗi", drw("failed")),
             ("boq_draft", "BOQ nháp chờ rà soát", boq("draft", "returned")),
             ("boq_submitted", "BOQ chờ phê duyệt", boq("submitted")),
             ("boq_approved", "BOQ đã phê duyệt", boq("approved")),
             ("geometry_pages", "Trang có hình học vector", _count(db, select(DrawingPage.id).where(
                 DrawingPage.company_id == cid, DrawingPage.geometry_status == "extracted"))),
             ("raster_pages", "Trang chỉ có ảnh quét (chưa có hình học)", _count(db, select(DrawingPage.id).where(
                 DrawingPage.company_id == cid, DrawingPage.geometry_status == "raster_only"))),
             ("geometry_ambiguous", "Đối tượng hình học cần xem lại", _count(db, select(GeometryPrimitive.id).where(
                 GeometryPrimitive.company_id == cid, GeometryPrimitive.status == "ambiguous")))]
    elif code == "cad_design":
        m = [("drawing_docs", "Bản vẽ", docs("drawing"))]
    elif code == "estimation":
        m = [("boq_docs", "Tài liệu BOQ", docs("boq"))]
    elif code == "contract_payment":
        contracts = select(Contract).where(Contract.company_id == cid)
        out_total = db.scalar(select(func.coalesce(func.sum(Contract.original_value), 0)).where(
            Contract.company_id == cid, Contract.direction == "outbound"))
        m = [("contracts", "Số hợp đồng", _count(db, contracts.with_only_columns(Contract.id))),
             ("outbound_original_value", "Giá trị HĐ đầu ra (gốc, VND)", str(Decimal(str(out_total)).quantize(Decimal("0.01")))),
             ("pending_appendices", "Phụ lục chờ duyệt", _pending_business_approvals(db, cid)["contract_payment"])]
    elif code == "construction":
        m = [("active_projects", "Dự án đang thi công", _count(db, projects.where(Project.status == "active")))]
    elif code == "internal_audit":
        since = now - dt.timedelta(days=7)
        m = [("audit_events_7d", "Sự kiện nhật ký 7 ngày", _count(db, select(AuditLog.id).where(
            AuditLog.company_id == cid, AuditLog.created_at >= since.replace(tzinfo=None))))]
    return [{"key": k, "label_vi": label, "value": str(v)} for k, label, v in m]


def overview(db: Session, user: User, now: dt.datetime | None = None, detail_code: str | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    cid = user.company_id
    depts = ensure_departments(db, cid)
    tasks = list(db.scalars(select(AITask).where(AITask.company_id == cid)))
    by_agent: dict[str, list[AITask]] = {}
    for t in tasks:
        by_agent.setdefault(t.agent_key, []).append(t)
    members = db.execute(select(DepartmentMember, User).join(User, User.id == DepartmentMember.user_id)
                         .where(DepartmentMember.company_id == cid)).all()
    pending = _pending_business_approvals(db, cid)
    pending_total = sum(pending.values()) + sum(1 for t in tasks if t.status == "waiting_approval")
    out = []
    for d in depts:
        if detail_code and d.code != detail_code:
            continue
        agents = []
        for spec in (a for a in AGENTS.values() if a.department == d.code):
            ts = by_agent.get(spec.key, [])
            current = next((t for t in sorted(ts, key=lambda t: utc(t.created_at), reverse=True) if t.status in ACTIVE), None)
            agents.append({"key": spec.key, "name_vi": spec.title_vi or spec.title, "enabled": not spec.tax_domain,
                           "status": agent_status([TaskView(t.status, t.finished_at, t.created_at) for t in ts], now),
                           "current_task": task_dict(current) if current else None})
        dept_tasks = [t for t in tasks if t.department_code == d.code]
        counts = {s: sum(1 for t in dept_tasks if t.status == s) for s in ("queued", "running", "waiting_approval", "completed", "error")}
        biz_pending = pending.get(d.code, 0)
        statuses = [a["status"] for a in agents] + (["waiting_approval"] if biz_pending else [])
        cat = CATALOG.get(d.code, {"route": None, "module_status": "planned", "phase": None, "doc_kinds": ()})
        item = {"code": d.code, "name_vi": d.name_vi, "color": d.color, "layout": d.layout,
                "status": combine(statuses), "agents": agents, "task_counts": counts,
                "pending_business_approvals": biz_pending,
                "employees": [{"user_id": str(u.id), "name": u.full_name or u.email, "role": u.role, "job_title": m.job_title}
                              for m, u in members if m.department_id == d.id],
                "module": {"route": cat["route"], "status": cat["module_status"], "phase": cat["phase"]},
                "metrics": _metrics(db, cid, d.code, pending_total, now)}
        if detail_code:
            item["recent_tasks"] = [task_dict(t) for t in sorted(dept_tasks, key=lambda t: utc(t.created_at), reverse=True)[:20]]
            kinds = cat["doc_kinds"]
            item["recent_documents"] = [] if not kinds else [
                {"id": str(x.id), "title": x.title, "kind": x.kind, "current_version": x.current_version}
                for x in db.scalars(select(Document).where(Document.company_id == cid, Document.kind.in_(kinds))
                                    .order_by(Document.created_at.desc()).limit(10))]
        out.append(item)
    return out


def start_task(db: Session, user: User, agent_key: str, title: str, *, status: str = "running",
               requires_approval: bool = False, project_id=None, entity=None, entity_id=None) -> AITask:
    spec = AGENTS[agent_key]
    now = dt.datetime.now(dt.timezone.utc)
    t = AITask(company_id=user.company_id, agent_key=agent_key, department_code=spec.department, title=title[:255],
               status=status, requires_approval=requires_approval, project_id=project_id, entity=entity,
               entity_id=entity_id, created_by=user.id, started_at=now if status == "running" else None, updated_at=now)
    db.add(t)
    db.flush()
    return t


def set_task_status(t: AITask, status: str, *, output: str = "", error: str = "") -> None:
    now = dt.datetime.now(dt.timezone.utc)
    t.status, t.updated_at = status, now
    if status == "running" and not t.started_at:
        t.started_at = now
    if status in ("completed", "error", "cancelled"):
        t.finished_at = now
    if output:
        t.output_summary = output[:2000]
    if error:
        t.error_message = error[:2000]
