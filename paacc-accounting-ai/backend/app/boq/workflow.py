"""BOQ review & approval workflow (Milestone 4D). All state changes are audited and versioned."""
import datetime as dt
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.boq import service as S
from app.boq.generate import CATEGORY_ORDER
from app.config import get_settings
from app.deps import audit
from app.models import AITask, Boq, BoqItem, BoqItemRevision, BoqSource, User
from app.office.service import set_task_status, start_task
from app.security import has_perm
from app.takeoff.engine import MODULES

BoqError = S.BoqError


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _dec(name: str, v) -> str | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        raise BoqError(422, f"'{name}' không phải số") from None
    if not d.is_finite():
        raise BoqError(422, f"'{name}' không hợp lệ")
    return format(d, "f")


def ensure_editable(boq: Boq) -> None:
    if boq.status not in S.EDITABLE:
        raise BoqError(409, f"BOQ đang ở trạng thái '{boq.status}', không thể chỉnh sửa"
                       + (" – hãy tạo phiên bản mới" if boq.status == "approved" else ""))


def edit_item(db: Session, user: User, boq: Boq, item: BoqItem, changes: dict, reason: str) -> BoqItem:
    """changes: inputs{name: value}, unit_system, waste_override, description, spec, category, stated_quantity, stated_unit."""
    ensure_editable(boq)
    if not reason.strip():
        raise BoqError(422, "Cần ghi lý do chỉnh sửa")
    touched = []
    if "inputs" in changes and changes["inputs"]:
        allowed = {f.name for f in MODULES[item.module].fields} if item.module else set()
        unknown = set(changes["inputs"]) - allowed
        if unknown:
            raise BoqError(422, f"Tham số không thuộc module: {sorted(unknown)}")
        new_inputs = dict(item.inputs)
        for name, value in changes["inputs"].items():
            old = new_inputs.get(name, {})
            new_inputs[name] = {**old, "value": _dec(name, value), "origin": "engineer",
                                "previous_value": old.get("value"), "previous_origin": old.get("origin")}
            touched.append(name)
        item.inputs = new_inputs
    if "stated_quantity" in changes:
        if item.module is not None:
            raise BoqError(422, "Hạng mục được tính theo công thức – sửa tham số thay vì khối lượng")
        old = item.inputs.get("quantity", {})
        item.inputs = {**item.inputs, "quantity": {**old, "value": _dec("quantity", changes["stated_quantity"]), "origin": "engineer",
                                                   "previous_value": old.get("value"), "previous_origin": old.get("origin")}}
        touched.append("quantity")
    if "unit_system" in changes:
        if changes["unit_system"] not in (None, "mm", "cm", "m"):
            raise BoqError(422, "Đơn vị kích thước phải là mm, cm hoặc m")
        item.unit_system = changes["unit_system"]
        touched.append("unit_system")
    if "stated_unit" in changes:
        item.stated_unit = changes["stated_unit"] or None
        touched.append("stated_unit")
    if "waste_override" in changes:
        w = _dec("waste_override", changes["waste_override"])
        if w is not None and not Decimal("0") <= Decimal(w) <= Decimal("1"):
            raise BoqError(422, "Hao hụt phải trong khoảng 0–1")
        item.waste_override = None if w is None else Decimal(w)
        touched.append("waste_override")
    for f in ("description", "spec"):
        if f in changes and changes[f] is not None:
            setattr(item, f, str(changes[f])[:1000])
            touched.append(f)
    if "category" in changes and changes["category"]:
        if changes["category"] not in CATEGORY_ORDER:
            raise BoqError(422, "Danh mục không hợp lệ")
        item.category = changes["category"]
        touched.append("category")
    if not touched:
        raise BoqError(422, "Không có thay đổi")
    was = item.review_status
    item.review_status = "pending"  # any change needs a fresh review
    item.version += 1
    item.updated_by = user.id
    S.recompute(boq, item)
    S.refresh_duplicates(db, boq)
    S.record(db, user, item, "edited", reason)
    audit(db, user, "edit", "boq_item", item.id, {"boq_id": str(boq.id), "fields": touched, "reason": reason,
                                                     "review_reset": was != "pending"})
    return item


def review_item(db: Session, user: User, boq: Boq, item: BoqItem, decision: str, note: str) -> BoqItem:
    ensure_editable(boq)
    if decision not in ("accept", "reject", "reset"):
        raise BoqError(422, "Quyết định không hợp lệ")
    if decision == "accept":
        if S.blocking(item):
            raise BoqError(409, "Không thể chấp nhận: còn lỗi chặn – " + "; ".join(f["message"] for f in S.blocking(item)))
        if item.quantity is None:
            raise BoqError(409, "Không thể chấp nhận hạng mục chưa có khối lượng")
    if decision == "reject" and not note.strip():
        raise BoqError(422, "Cần ghi lý do loại bỏ")
    item.review_status = {"accept": "accepted", "reject": "rejected", "reset": "pending"}[decision]
    item.version += 1
    item.updated_by = user.id
    if note.strip():
        item.notes = _append_note(item.notes, user, note)
    S.refresh_duplicates(db, boq)  # rejected items no longer count as duplicates
    S.record(db, user, item, {"accept": "accepted", "reject": "rejected", "reset": "review_reset"}[decision], note)
    audit(db, user, decision, "boq_item", item.id, {"boq_id": str(boq.id), "note": note,
                                                     "warnings": [f["code"] for f in item.flags or [] if f["severity"] == "warning"]})
    return item


def _append_note(existing: str, user: User, note: str) -> str:
    line = f"[{_now().strftime('%d/%m/%Y %H:%M')} {user.email}] {note.strip()}"
    return (existing + "\n" + line).strip()[-4000:]


def annotate_item(db: Session, user: User, boq: Boq, item: BoqItem, note: str) -> BoqItem:
    if not note.strip():
        raise BoqError(422, "Ghi chú trống")
    if boq.status == "approved":
        raise BoqError(409, "BOQ đã phê duyệt – không thể thêm ghi chú")
    item.notes = _append_note(item.notes, user, note)
    item.version += 1
    S.record(db, user, item, "annotated", note)
    audit(db, user, "annotate", "boq_item", item.id, {"boq_id": str(boq.id)})
    return item


def submit(db: Session, user: User, boq: Boq, note: str) -> Boq:
    ensure_editable(boq)
    items = list(db.scalars(select(BoqItem).where(BoqItem.boq_id == boq.id)))
    pending = [i.item_no for i in items if i.review_status == "pending"]
    if pending:
        raise BoqError(409, f"Còn {len(pending)} hạng mục chưa rà soát (STT {', '.join(map(str, pending[:10]))})")
    accepted = [i for i in items if i.review_status == "accepted"]
    if not accepted:
        raise BoqError(409, "BOQ không có hạng mục nào được chấp nhận")
    bad = [i.item_no for i in accepted if S.blocking(i) or i.quantity is None]
    if bad:
        raise BoqError(409, f"Hạng mục đã chấp nhận nhưng còn lỗi chặn: {bad}")
    task = start_task(db, user, "quantity_surveyor", f"Phê duyệt BOQ: {boq.title} (v{boq.version_no})", status="waiting_approval",
                      requires_approval=True, project_id=boq.project_id, entity="boq", entity_id=boq.id)
    boq.status, boq.submitted_by, boq.submitted_at, boq.approval_task_id = "submitted", user.id, _now(), task.id
    boq.decided_by, boq.decided_at, boq.decision_note = None, None, ""
    audit(db, user, "submit", "boq", boq.id, {"note": note, "accepted": len(accepted), "rejected": len(items) - len(accepted)})
    return boq


def decide(db: Session, user: User, boq: Boq, decision: str, note: str) -> Boq:
    if not has_perm(user.role, "boq:approve"):
        raise BoqError(403, "Không có quyền phê duyệt BOQ")
    if boq.status != "submitted":
        raise BoqError(409, "BOQ không ở trạng thái chờ phê duyệt")
    if decision not in ("approve", "return"):
        raise BoqError(422, "Quyết định không hợp lệ")
    if get_settings().boq_four_eyes and boq.submitted_by == user.id:
        raise BoqError(403, "Người trình không được tự phê duyệt BOQ (nguyên tắc 4 mắt)")
    if decision == "return" and not note.strip():
        raise BoqError(422, "Cần ghi lý do trả lại")
    task = db.get(AITask, boq.approval_task_id) if boq.approval_task_id else None
    boq.decided_by, boq.decided_at, boq.decision_note = user.id, _now(), note
    if decision == "approve":
        boq.status = "approved"
        if task and task.status == "waiting_approval":
            set_task_status(task, "completed", output=f"Đã phê duyệt bởi {user.email}")
    else:
        boq.status = "returned"
        if task and task.status == "waiting_approval":
            set_task_status(task, "cancelled", error=f"Trả lại bởi {user.email}: {note}")
    if task:
        task.decided_by = user.id
    audit(db, user, decision, "boq", boq.id, {"note": note, "version_no": boq.version_no})
    return boq


def new_version(db: Session, user: User, boq: Boq, reason: str) -> Boq:
    if boq.status != "approved":
        raise BoqError(409, "Chỉ tạo phiên bản mới từ BOQ đã phê duyệt")
    if not reason.strip():
        raise BoqError(422, "Cần ghi lý do tạo phiên bản mới")
    newer = db.scalar(select(Boq).where(Boq.previous_boq_id == boq.id))
    if newer:
        raise BoqError(409, "Đã có phiên bản mới hơn")
    nb = Boq(company_id=boq.company_id, project_id=boq.project_id, title=boq.title, version_no=boq.version_no + 1,
             previous_boq_id=boq.id, status="draft", rules=dict(boq.rules), created_by=user.id)
    db.add(nb)
    db.flush()
    for s in db.scalars(select(BoqSource).where(BoqSource.boq_id == boq.id)):
        db.add(BoqSource(company_id=s.company_id, boq_id=nb.id, drawing_id=s.drawing_id, document_version_id=s.document_version_id))
    for i in db.scalars(select(BoqItem).where(BoqItem.boq_id == boq.id).order_by(BoqItem.item_no)):
        c = BoqItem(company_id=i.company_id, boq_id=nb.id, item_no=i.item_no, category=i.category, description=i.description,
                    spec=i.spec, module=i.module, inputs=i.inputs, unit_system=i.unit_system, stated_unit=i.stated_unit,
                    waste_override=i.waste_override, origin=i.origin, review_status="pending", source_flags=i.source_flags,
                    notes=i.notes, drawing_id=i.drawing_id, page_no=i.page_no, bbox=i.bbox, source_item_ids=i.source_item_ids,
                    mark=i.mark, section_key=i.section_key, updated_by=user.id)
        db.add(c)
        db.flush()
        S.recompute(nb, c)
        S.record(db, user, c, "copied_from_version", f"Từ v{boq.version_no} (hạng mục {i.id}). {reason}")
    S.refresh_duplicates(db, nb)
    audit(db, user, "new_version", "boq", nb.id, {"previous_boq_id": str(boq.id), "reason": reason})
    return nb


def history(db: Session, item: BoqItem) -> list[dict]:
    rows = db.scalars(select(BoqItemRevision).where(BoqItemRevision.item_id == item.id).order_by(BoqItemRevision.created_at))
    return [{"version": r.version, "action": r.action, "reason": r.reason, "changed_by": str(r.changed_by) if r.changed_by else None,
             "at": r.created_at.isoformat() if r.created_at else None,
             "quantity": r.snapshot.get("quantity"), "review_status": r.snapshot.get("review_status"),
             "inputs": {k: v.get("value") for k, v in (r.snapshot.get("inputs") or {}).items()}} for r in rows]
