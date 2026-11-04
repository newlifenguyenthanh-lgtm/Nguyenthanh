"""BOQ domain service: generation, recomputation, duplicates, revision history."""
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.boq import generate as G
from app.models import Boq, BoqItem, BoqItemRevision, BoqSource, Drawing, DrawingPage, ExtractedItem, User
from app.office.service import set_task_status, start_task
from app.takeoff.engine import MODULES, MeasurementRules

DEFAULT_RULES = {"decimals": 3, "steel_density": "7850", "waste": {}}
EDITABLE = ("draft", "returned")


class BoqError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- rules
def validate_rules(raw: dict | None) -> dict:
    r = {**DEFAULT_RULES, **(raw or {})}
    try:
        decimals = int(r["decimals"])
        density = Decimal(str(r["steel_density"]))
        waste = {k: str(Decimal(str(v))) for k, v in (r.get("waste") or {}).items()}
    except Exception:  # noqa: BLE001
        raise BoqError(422, "Quy tắc đo bóc không hợp lệ") from None
    if not 0 <= decimals <= 6 or density <= 0:
        raise BoqError(422, "decimals phải 0–6, steel_density phải > 0")
    for k, v in waste.items():
        if k not in G.CATEGORY_ORDER or not Decimal("0") <= Decimal(v) <= Decimal("1"):
            raise BoqError(422, f"Hao hụt '{k}' không hợp lệ (danh mục: {G.CATEGORY_ORDER}, giá trị 0–1)")
    return {"decimals": decimals, "steel_density": str(density), "waste": waste}


def measurement_rules(boq: Boq) -> MeasurementRules:
    return MeasurementRules(decimals=int(boq.rules["decimals"]), steel_density=Decimal(boq.rules["steel_density"]))


def waste_for(boq: Boq, item: BoqItem) -> Decimal:
    if item.waste_override is not None:
        return Decimal(item.waste_override)
    return Decimal(boq.rules.get("waste", {}).get(item.category, "0"))


# ---------------------------------------------------------------- item computation
def origin_of(inputs: dict) -> str:
    origins = {v.get("origin") for v in inputs.values() if v.get("value") not in (None, "")}
    if not origins:
        return "extracted"
    return origins.pop() if len(origins) == 1 else "mixed"


def recompute(boq: Boq, item: BoqItem) -> None:
    w = waste_for(boq, item)
    c = G.compute(item.module, item.inputs, item.unit_system, w, measurement_rules(boq), item.stated_unit)
    # store at the column scale (Numeric(20,4)) so API responses are identical before and after a DB round trip;
    # the value itself was already rounded by the engine to the BOQ's `decimals` rule.
    q = None if c.quantity is None else c.quantity.quantize(Decimal("0.0001"))
    item.waste_factor, item.quantity, item.unit = w.quantize(Decimal("0.0001")), q, c.unit
    item.formula_text, item.excel_expr, item.calc_inputs = c.formula_text, c.excel_expr, c.calc_inputs
    computed = c.quantity is not None
    flags = []
    for f in item.source_flags or []:
        if f["severity"] == "blocking" and computed:
            continue  # resolved: all inputs now present and valid
        if f["code"] == "diameter_convention_mm" and item.inputs.get("diameter_mm", {}).get("origin") == "engineer":
            continue
        if f["code"] == "unit_conflict" and item.unit_system and item.inputs and any(
                v.get("origin") == "engineer" for v in item.inputs.values()):
            continue
        flags.append(f)
    flags += [f.as_dict() for f in c.flags]
    if item.module and MODULES[item.module].dimensional and not item.unit_system and not any(
            f["code"] in ("unit_unconfirmed", "inconsistent_units") for f in flags):
        flags.append({"code": "unit_unconfirmed", "severity": "blocking", "message": "Chưa có đơn vị kích thước"})
    for d in item.duplicates or []:
        msg = {"same_source_annotation": "Cùng một ghi chú nguồn được dùng cho nhiều hạng mục",
               "identical_calculation": "Trùng phép tính với hạng mục khác",
               "schedule_and_annotation": "Có thể trùng giữa bảng thống kê và ghi chú trên bản vẽ"
               + (" (khối lượng khớp)" if d.get("quantities_match") else " (khối lượng KHÔNG khớp)" if d.get("quantities_match") is False else "")}[d["reason"]]
        flags.append({"code": "possible_duplicate", "severity": "warning", "message": msg, "other_id": d["other_id"]})
    item.flags = flags
    item.origin = origin_of(item.inputs)


def refresh_duplicates(db: Session, boq: Boq) -> None:
    all_items = list(db.scalars(select(BoqItem).where(BoqItem.boq_id == boq.id)))
    items = [i for i in all_items if i.review_status != "rejected"]
    for i in all_items:
        if i.review_status == "rejected":
            i.duplicates = []
            recompute(boq, i)
    groups = G.duplicate_groups([{"id": str(i.id), "module": i.module, "calc_inputs": i.calc_inputs, "unit_system": i.unit_system,
                                  "source_item_ids": i.source_item_ids or [], "mark": i.mark, "section_key": i.section_key,
                                  "category": i.category, "quantity": i.quantity, "unit": i.unit} for i in items])
    for i in items:
        i.duplicates = groups.get(str(i.id), [])
        recompute(boq, i)


def blocking(item: BoqItem) -> list[dict]:
    return [f for f in item.flags or [] if f["severity"] == "blocking"]


# ---------------------------------------------------------------- serialisation + history
def item_dict(i: BoqItem) -> dict:
    return {"id": str(i.id), "item_no": i.item_no, "category": i.category, "description": i.description, "spec": i.spec,
            "module": i.module, "inputs": i.inputs, "unit_system": i.unit_system, "stated_unit": i.stated_unit,
            "waste_factor": str(i.waste_factor), "waste_override": None if i.waste_override is None else str(i.waste_override),
            "quantity": None if i.quantity is None else str(i.quantity), "unit": i.unit, "formula_text": i.formula_text,
            "excel_expr": i.excel_expr, "calc_inputs": i.calc_inputs or {}, "origin": i.origin, "review_status": i.review_status,
            "flags": i.flags or [], "notes": i.notes, "drawing_id": str(i.drawing_id) if i.drawing_id else None,
            "page_no": i.page_no, "bbox": i.bbox, "source_item_ids": i.source_item_ids or [], "version": i.version,
            "has_blocking": bool(blocking(i))}


def record(db: Session, user: User | None, item: BoqItem, action: str, reason: str = "") -> None:
    snap = item_dict(item)
    db.add(BoqItemRevision(company_id=item.company_id, boq_id=item.boq_id, item_id=item.id, version=item.version,
                           action=action, snapshot=snap, reason=reason, changed_by=user.id if user else None))


# ---------------------------------------------------------------- generation
def _page_ctx(db: Session, drawing: Drawing) -> dict[int, DrawingPage]:
    return {p.page_no: p for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == drawing.id))}


def candidates_for_drawing(db: Session, drawing: Drawing) -> list[G.Candidate]:
    rows = list(db.scalars(select(ExtractedItem).where(ExtractedItem.drawing_id == drawing.id)))
    as_dict = lambda r: {"id": str(r.id), "kind": r.kind, "page_no": r.page_no, "text": r.text, "bbox": [r.x0, r.y0, r.x1, r.y1],
                         "confidence": r.confidence, "data": r.data or {}, "source": r.source}
    derived_by_line: dict[str, list[dict]] = {}
    for r in rows:
        if r.source == "analysis" and (r.data or {}).get("from_item_id"):
            derived_by_line.setdefault(r.data["from_item_id"], []).append(as_dict(r))
    pages = _page_ctx(db, drawing)
    out: list[G.Candidate] = []
    for r in sorted((r for r in rows if r.kind == "text"), key=lambda r: (r.page_no, r.y0, r.x0)):
        der = derived_by_line.get(str(r.id), [])
        if not der:
            continue
        p = pages.get(r.page_no)
        c = G.candidates_from_line(as_dict(r), der, p.units if p else None, p.units_status if p else "not_analyzed", str(drawing.id))
        if c:
            out.append(c)
    for r in rows:
        if r.kind == "table":
            out += G.candidates_from_table(as_dict(r), str(drawing.id))
    return out


def generate_boq(db: Session, user: User, title: str, drawings: list[Drawing], project_id, rules: dict) -> Boq:
    boq = Boq(company_id=user.company_id, project_id=project_id, title=title, rules=rules, created_by=user.id)
    db.add(boq)
    db.flush()
    task = start_task(db, user, "quantity_surveyor", f"Tạo BOQ nháp: {title}", project_id=project_id, entity="boq", entity_id=boq.id)
    boq.generation_task_id = task.id
    db.commit()
    try:
        cands: list[G.Candidate] = []
        for d in drawings:
            db.add(BoqSource(company_id=user.company_id, boq_id=boq.id, drawing_id=d.id, document_version_id=d.document_version_id))
            cands += candidates_for_drawing(db, d)
        cands.sort(key=lambda c: (G.CATEGORY_ORDER.index(c.category), c.page_no, c.bbox[1]))
        for n, c in enumerate(cands, start=1):
            item = BoqItem(company_id=user.company_id, boq_id=boq.id, item_no=n, category=c.category, description=c.description[:1000],
                           spec=c.spec[:500], module=c.module, inputs=c.inputs, unit_system=c.unit_system, stated_unit=c.stated_unit,
                           origin=origin_of(c.inputs), source_flags=[f.as_dict() for f in c.flags], drawing_id=uuid.UUID(c.drawing_id),
                           page_no=c.page_no, bbox=c.bbox, source_item_ids=c.source_item_ids, mark=c.mark, section_key=c.section_key,
                           updated_by=user.id)
            db.add(item)
            db.flush()
            recompute(boq, item)
        refresh_duplicates(db, boq)
        db.flush()
        items = list(db.scalars(select(BoqItem).where(BoqItem.boq_id == boq.id)))
        for i in items:
            record(db, user, i, "generated")
        n_block = sum(1 for i in items if blocking(i))
        set_task_status(task, "completed", output=f"{len(items)} hạng mục nháp; {n_block} cần bổ sung dữ liệu; chờ kỹ sư rà soát")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        boq, task = db.merge(boq), db.merge(task)
        boq.status = "failed"
        set_task_status(task, "error", error=f"{type(e).__name__}: {e}"[:2000])
        db.commit()
        raise
    db.commit()
    return boq


def next_item_no(db: Session, boq: Boq) -> int:
    nums = list(db.scalars(select(BoqItem.item_no).where(BoqItem.boq_id == boq.id)))
    return max(nums, default=0) + 1
