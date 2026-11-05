"""Phase 5D API: component recognition, evidence, review, history, 5E hand-over (draft only), taxonomy."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.drawings import get_drawing
from app.components import service as S
from app.db import get_db
from app.deps import audit, require
from app.models import (ComponentBoqCandidate, ComponentRelation, ComponentRepeatGroup, ComponentSymbolPattern, ComponentType,
                        DrawingComponent as C, User)

router = APIRouter()

SCORE_KEYS = ("text", "geometry", "measurement", "symbol", "spatial", "repetition", "semantic")


def _err(e: S.ComponentError):
    return HTTPException(e.status, str(e))


def comp_dict(db: Session, c: C, full: bool = False) -> dict:
    src = S.sources_of(db, c)
    out = {"id": str(c.id), "drawing_id": str(c.drawing_id), "project_id": str(c.project_id) if c.project_id else None,
           "page_id": str(c.page_id), "page_no": c.page_no, "component_type": c.component_type, "component_subtype": c.component_subtype,
           "name": c.name, "description": c.description, "specification": c.specification, "material": c.material,
           "bbox": [c.x0, c.y0, c.x1, c.y1], "centroid": [c.centroid_x, c.centroid_y], "view_context": c.view_context,
           "recognition_method": c.recognition_method, "recognition_rule": c.recognition_rule,
           "recognition_confidence": c.recognition_confidence, "confidence_band": c.confidence_band,
           "scores": {k: getattr(c, f"{k}_score") for k in SCORE_KEYS} | {"overall": c.recognition_confidence},
           "status": c.status, "ambiguity_reason": c.ambiguity_reason, "rejection_reason": c.rejection_reason,
           "parent_id": str(c.parent_id) if c.parent_id else None,
           "representation_of_id": str(c.representation_of_id) if c.representation_of_id else None,
           "repeat_group_id": str(c.repeat_group_id) if c.repeat_group_id else None, "dimensions": c.dimensions or {},
           "source_text_ids": src["text"], "source_geometry_ids": src["geometry"], "source_measurement_ids": src["measurement"],
           "source_association_ids": src["association"], "downstream_allowed": c.status == "CONFIRMED" and c.representation_of_id is None,
           "created_by": str(c.created_by) if c.created_by else None, "reviewed_by": str(c.reviewed_by) if c.reviewed_by else None,
           "created_at": c.created_at.isoformat() if c.created_at else None, "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
           "updated_at": c.updated_at.isoformat() if c.updated_at else None}
    if full:
        out["source_roles"] = src["roles"]
    return out


def get_component(db: Session, cid: uuid.UUID, user: User) -> C:
    c = db.get(C, cid)
    if not c or c.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy cấu kiện")
    return c


@router.get("/drawings/{did}/components")
def list_components(did: uuid.UUID, page: int | None = None, status: str | None = None, component_type: str | None = None,
                    geometry_id: uuid.UUID | None = None, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(C).where(C.drawing_id == d.id)
    if page:
        stmt = stmt.where(C.page_no == page)
    if status:
        stmt = stmt.where(C.status == status.upper())
    if component_type:
        stmt = stmt.where(C.component_type == component_type.upper())
    if geometry_id:
        from app.models import ComponentSource
        stmt = stmt.where(C.id.in_(select(ComponentSource.component_id).where(ComponentSource.geometry_id == geometry_id)))
    return [comp_dict(db, c) for c in db.scalars(stmt.order_by(C.page_no, C.y0, C.x0))]


@router.post("/drawings/{did}/components/run")
def run(did: uuid.UUID, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    d = get_drawing(db, did, user)
    try:
        return S.run_with_task(db, user, d)
    except S.ComponentError as e:
        raise _err(e)


@router.get("/components/{cid}")
def one(cid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    return comp_dict(db, get_component(db, cid, user), full=True)


@router.get("/components/{cid}/evidence")
def evidence(cid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    src = S.sources_of(db, c)
    grp = db.get(ComponentRepeatGroup, c.repeat_group_id) if c.repeat_group_id else None
    rels = db.scalars(select(ComponentRelation).where((ComponentRelation.from_component_id == c.id) | (ComponentRelation.to_component_id == c.id)))
    return {"component_id": str(c.id), "scores": {k: getattr(c, f"{k}_score") for k in SCORE_KEYS},
            "overall": c.recognition_confidence, "band": c.confidence_band, "rule": c.recognition_rule,
            "sources": src, "measurements": S.measurements_of(db, src["measurement"]), "stated_dimensions": c.dimensions or {},
            "detail": c.evidence or {},
            "repeat_group": None if not grp else {
                "id": str(grp.id), "pattern_type": grp.pattern_type, "signature": grp.signature, "pattern_status": grp.pattern_status,
                "carrier_geometry_id": str(grp.carrier_geometry_id) if grp.carrier_geometry_id else None,
                "count_measurement_id": str(grp.count_measurement_id) if grp.count_measurement_id else None,
                "spacing_measurement_id": str(grp.spacing_measurement_id) if grp.spacing_measurement_id else None,
                "start": [grp.start_x, grp.start_y], "end": [grp.end_x, grp.end_y], "gaps_pt": grp.gaps_pt, "occluders": grp.occluders or []},
            "relations": [{"from": str(r.from_component_id), "to": str(r.to_component_id), "type": r.relation_type, "detail": r.detail}
                          for r in rels]}


@router.get("/components/{cid}/history")
def history(cid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    return S.history(db, get_component(db, cid, user))


class NoteIn(BaseModel):
    note: str = ""


def _act(db: Session, fn, c: C, *args) -> dict:
    try:
        fn(db, *args)
    except S.ComponentError as e:
        db.rollback()
        raise _err(e)
    db.commit()
    return comp_dict(db, c, full=True)


@router.post("/components/{cid}/review")
def start_review(cid: uuid.UUID, body: NoteIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    return _act(db, lambda db_, *a: S.start_review(db_, user, c, body.note), c)


@router.post("/components/{cid}/confirm")
def confirm(cid: uuid.UUID, body: NoteIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    return _act(db, lambda db_, *a: S.confirm(db_, user, c, body.note), c)


@router.post("/components/{cid}/reject")
def reject(cid: uuid.UUID, body: NoteIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    return _act(db, lambda db_, *a: S.reject(db_, user, c, body.note), c)


@router.post("/components/{cid}/ambiguous")
def ambiguous(cid: uuid.UUID, body: NoteIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    return _act(db, lambda db_, *a: S.mark_ambiguous(db_, user, c, body.note), c)


class ReclassifyIn(BaseModel):
    component_type: str | None = None
    component_subtype: str | None = None
    description: str | None = Field(None, max_length=2000)
    specification: str | None = Field(None, max_length=1000)
    material: str | None = Field(None, max_length=255)
    dimensions: dict | None = None
    reason: str = ""


@router.post("/components/{cid}/reclassify")
def reclassify(cid: uuid.UUID, body: ReclassifyIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    changes = body.model_dump(exclude_unset=True, exclude={"reason"})
    if "component_type" in changes and changes["component_type"]:
        changes["component_type"] = changes["component_type"].upper()
    return _act(db, lambda db_, *a: S.reclassify(db_, user, c, changes, body.reason), c)


def boq_dict(b: ComponentBoqCandidate) -> dict:
    return {"id": str(b.id), "component_id": str(b.component_id), "description_vi": b.description_vi, "unit": b.unit,
            "measurement_id": str(b.measurement_id) if b.measurement_id else None, "status": b.status,
            "approval_status": b.approval_status, "note": b.note}


@router.post("/components/{cid}/boq-candidate")
def boq_candidate(cid: uuid.UUID, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    c = get_component(db, cid, user)
    try:
        b = S.prepare_boq_candidate(db, user, c)
    except S.ComponentError as e:
        raise _err(e)
    db.commit()
    return {"candidate": boq_dict(b) if b else None,
            "reason": None if b else "Không chuẩn bị BOQ: biểu diễn chi tiết/mặt cắt, hoặc loại cấu kiện không có quy tắc BOQ"}


@router.get("/drawings/{did}/component-boq-candidates")
def list_boq_candidates(did: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    out = []
    for b in db.scalars(select(ComponentBoqCandidate).where(ComponentBoqCandidate.drawing_id == d.id).order_by(ComponentBoqCandidate.created_at)):
        out.append({**boq_dict(b), "measurement": (S.measurements_of(db, [str(b.measurement_id)]) or [None])[0] if b.measurement_id else None})
    return out


# ---------------------------------------------------------------- taxonomy (extensible without code changes)
def type_dict(t: ComponentType) -> dict:
    return {"id": str(t.id), "code": t.code, "group": t.group_code, "name_vi": t.name_vi, "parent_code": t.parent_code, "family": t.family,
            "member_type": t.member_type, "rule": t.rule, "boq": t.boq, "active": t.active, "source": t.source}


@router.get("/component-types")
def list_types(user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    S.ensure_taxonomy(db, user.company_id)
    db.commit()
    return [type_dict(t) for t in db.scalars(select(ComponentType).where(ComponentType.company_id == user.company_id)
                                             .order_by(ComponentType.group_code, ComponentType.code))]


class TypeIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,47}$")
    group: str = Field(pattern=r"^[A-Z_]{2,24}$")
    name_vi: str = Field(min_length=1, max_length=255)
    parent_code: str | None = None
    family: str = Field(min_length=1, max_length=48)
    member_type: str | None = None
    rule: dict
    boq: dict | None = None


@router.post("/component-types", status_code=201)
def create_type(body: TypeIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    """Adds a company-specific component type + its recognition rule (data). The engine picks it up on the next run."""
    S.ensure_taxonomy(db, user.company_id)
    if db.scalar(select(ComponentType).where(ComponentType.company_id == user.company_id, ComponentType.code == body.code)):
        raise HTTPException(409, "Mã loại cấu kiện đã tồn tại")
    allowed = {"keywords", "regex", "spec_categories", "dimension_types", "dimension_score", "geometry_kinds", "geometry_optional",
               "measurement_kind", "compare", "weights", "exclude_text_types"}
    if set(body.rule) - allowed:
        raise HTTPException(422, f"Khoá quy tắc không hợp lệ: {sorted(set(body.rule) - allowed)}")
    if body.rule.get("measurement_kind") not in (None, "length", "area", "count", "diameter"):
        raise HTTPException(422, "measurement_kind không hợp lệ")
    t = ComponentType(company_id=user.company_id, code=body.code, group_code=body.group, name_vi=body.name_vi, parent_code=body.parent_code,
                      family=body.family, member_type=body.member_type, rule=body.rule, boq=body.boq, source="company")
    db.add(t)
    db.flush()
    audit(db, user, "create", "component_type", t.id, {"code": t.code})
    db.commit()
    return type_dict(t)


@router.get("/component-symbol-patterns")
def list_patterns(user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    S.ensure_taxonomy(db, user.company_id)
    db.commit()
    return [{"id": str(p.id), "component_type": p.component_type, "pattern_type": p.pattern_type, "parameters": p.parameters,
             "tolerance": p.tolerance, "confidence_weight": p.confidence_weight, "active": p.active}
            for p in db.scalars(select(ComponentSymbolPattern).where(ComponentSymbolPattern.company_id == user.company_id))]
