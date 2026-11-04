import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.boq import service as S
from app.boq.generate import CATEGORY_ORDER
from app.db import get_db
from app.deps import audit, require
from app.models import Boq, BoqItem, BoqSource, Drawing, Project, User
from app.takeoff.engine import MODULES, list_modules

router = APIRouter()


def _err(e: S.BoqError):
    return HTTPException(e.status, str(e))


def get_boq(db: Session, bid: uuid.UUID, user: User) -> Boq:
    b = db.get(Boq, bid)
    if not b or b.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy BOQ")
    return b


def get_item(db: Session, boq: Boq, iid: uuid.UUID) -> BoqItem:
    i = db.get(BoqItem, iid)
    if not i or i.boq_id != boq.id:
        raise HTTPException(404, "Không tìm thấy hạng mục")
    return i


def boq_dict(db: Session, b: Boq, with_items: bool = True) -> dict:
    items = list(db.scalars(select(BoqItem).where(BoqItem.boq_id == b.id).order_by(BoqItem.item_no)))
    sources = list(db.scalars(select(BoqSource).where(BoqSource.boq_id == b.id)))
    counts = {s: sum(1 for i in items if i.review_status == s) for s in ("pending", "accepted", "rejected")}
    out = {"id": str(b.id), "title": b.title, "project_id": str(b.project_id) if b.project_id else None, "version_no": b.version_no,
           "previous_boq_id": str(b.previous_boq_id) if b.previous_boq_id else None, "status": b.status, "rules": b.rules,
           "submitted_by": str(b.submitted_by) if b.submitted_by else None, "submitted_at": b.submitted_at.isoformat() if b.submitted_at else None,
           "decided_by": str(b.decided_by) if b.decided_by else None, "decided_at": b.decided_at.isoformat() if b.decided_at else None,
           "decision_note": b.decision_note, "created_at": b.created_at.isoformat() if b.created_at else None,
           "generation_task_id": str(b.generation_task_id) if b.generation_task_id else None,
           "approval_task_id": str(b.approval_task_id) if b.approval_task_id else None,
           "sources": [{"drawing_id": str(s.drawing_id), "document_version_id": str(s.document_version_id)} for s in sources],
           "item_count": len(items), "review_counts": counts, "blocking_count": sum(1 for i in items if S.blocking(i) and i.review_status != "rejected")}
    if with_items:
        out["items"] = [S.item_dict(i) for i in items]
    return out


class BoqIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    drawing_ids: list[uuid.UUID] = Field(min_length=1)
    project_id: uuid.UUID | None = None
    rules: dict | None = None


@router.get("/takeoff/modules")
def modules(user: User = Depends(require("boq:read"))) -> dict:
    return {"modules": list_modules(), "categories": CATEGORY_ORDER}


@router.post("/boqs", status_code=201)
def create_boq(body: BoqIn, user: User = Depends(require("boq:write")), db: Session = Depends(get_db)) -> dict:
    try:
        rules = S.validate_rules(body.rules)
    except S.BoqError as e:
        raise _err(e)
    drawings = []
    for did in dict.fromkeys(body.drawing_ids):
        d = db.get(Drawing, did)
        if not d or d.company_id != user.company_id:
            raise HTTPException(404, "Không tìm thấy bản vẽ")
        if d.status != "processed":
            raise HTTPException(409, f"Bản vẽ {d.filename} chưa được phân tích thành công")
        drawings.append(d)
    project_id = body.project_id or next((d.project_id for d in drawings if d.project_id), None)
    if project_id:
        p = db.get(Project, project_id)
        if not p or p.company_id != user.company_id:
            raise HTTPException(404, "Không tìm thấy dự án")
    b = S.generate_boq(db, user, body.title, drawings, project_id, rules)
    audit(db, user, "generate", "boq", b.id, {"drawings": [str(d.id) for d in drawings], "rules": rules})
    db.commit()
    return boq_dict(db, b)


@router.get("/boqs")
def list_boqs(project_id: uuid.UUID | None = None, status: str | None = None,
              user: User = Depends(require("boq:read")), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Boq).where(Boq.company_id == user.company_id).order_by(Boq.created_at.desc())
    if project_id:
        stmt = stmt.where(Boq.project_id == project_id)
    if status:
        stmt = stmt.where(Boq.status == status)
    return [boq_dict(db, b, with_items=False) for b in db.scalars(stmt)]


@router.get("/boqs/{bid}")
def get_one(bid: uuid.UUID, user: User = Depends(require("boq:read")), db: Session = Depends(get_db)) -> dict:
    return boq_dict(db, get_boq(db, bid, user))


def ensure_editable(b: Boq):
    if b.status not in S.EDITABLE:
        raise HTTPException(409, f"BOQ ở trạng thái '{b.status}' không thể chỉnh sửa" + (" – hãy tạo phiên bản mới" if b.status == "approved" else ""))


class RulesIn(BaseModel):
    decimals: int | None = None
    steel_density: str | None = None
    waste: dict[str, str] | None = None
    reason: str = ""


@router.patch("/boqs/{bid}/rules")
def update_rules(bid: uuid.UUID, body: RulesIn, user: User = Depends(require("boq:write")), db: Session = Depends(get_db)) -> dict:
    b = get_boq(db, bid, user)
    ensure_editable(b)
    try:
        new = S.validate_rules({**b.rules, **body.model_dump(exclude_none=True, exclude={"reason"})})
    except S.BoqError as e:
        raise _err(e)
    before, b.rules = b.rules, new
    for i in db.scalars(select(BoqItem).where(BoqItem.boq_id == b.id)):
        old_q = i.quantity
        S.recompute(b, i)
        if i.quantity != old_q:
            i.version += 1
            S.record(db, user, i, "recalculated", f"Quy tắc đo bóc thay đổi. {body.reason}".strip())
    S.refresh_duplicates(db, b)
    audit(db, user, "update_rules", "boq", b.id, {"before": before, "after": new, "reason": body.reason})
    db.commit()
    return boq_dict(db, b)


class ItemIn(BaseModel):
    category: str
    description: str = Field(min_length=1, max_length=1000)
    spec: str = ""
    module: str | None = None
    inputs: dict[str, str | None] = {}
    unit_system: str | None = Field(None, pattern="^(mm|cm|m)$")
    quantity: str | None = None  # stated quantity when module is None
    stated_unit: str | None = None
    notes: str = ""


def parse_dec(name: str, v: str | None) -> str | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).replace(",", "."))
    except InvalidOperation:
        raise HTTPException(422, f"'{name}' không phải số") from None
    if not d.is_finite():
        raise HTTPException(422, f"'{name}' không hợp lệ")
    return format(d, "f")


@router.post("/boqs/{bid}/items", status_code=201)
def add_item(bid: uuid.UUID, body: ItemIn, user: User = Depends(require("boq:write")), db: Session = Depends(get_db)) -> dict:
    """Engineer-entered item (origin = engineer)."""
    b = get_boq(db, bid, user)
    ensure_editable(b)
    if body.category not in CATEGORY_ORDER:
        raise HTTPException(422, "Danh mục không hợp lệ")
    if body.module is not None and body.module not in MODULES:
        raise HTTPException(422, "Module tính không tồn tại")
    if body.module is None:
        if not body.stated_unit:
            raise HTTPException(422, "Cần đơn vị tính cho khối lượng nhập trực tiếp")
        inputs = {"quantity": {"value": parse_dec("quantity", body.quantity), "origin": "engineer", "source_item_id": None}}
    else:
        names = {f.name for f in MODULES[body.module].fields}
        unknown = set(body.inputs) - names
        if unknown:
            raise HTTPException(422, f"Tham số không thuộc module: {sorted(unknown)}")
        inputs = {n: {"value": parse_dec(n, body.inputs.get(n)), "origin": "engineer", "source_item_id": None} for n in names}
    i = BoqItem(company_id=user.company_id, boq_id=b.id, item_no=S.next_item_no(db, b), category=body.category,
                description=body.description, spec=body.spec, module=body.module, inputs=inputs, unit_system=body.unit_system,
                stated_unit=body.stated_unit, origin="engineer", source_flags=[], notes=body.notes, updated_by=user.id)
    db.add(i)
    db.flush()
    S.recompute(b, i)
    S.refresh_duplicates(db, b)
    S.record(db, user, i, "created_manually")
    audit(db, user, "add_item", "boq_item", i.id, {"boq_id": str(b.id)})
    db.commit()
    return S.item_dict(i)
