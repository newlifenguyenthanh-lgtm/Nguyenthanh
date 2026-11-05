import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.drawings import get_drawing
from app.db import get_db
from app.deps import require
from app.geometry import service as GS
from app.geometry.coords import paper_mm, real_m
from app.models import Drawing, DrawingPage, GeometryPrimitive, User
from app.takeoff.engine import CalcError

router = APIRouter()


def prim_dict(g: GeometryPrimitive, page: DrawingPage | None = None) -> dict:
    out = {"id": str(g.id), "page_no": g.page_no, "kind": g.kind, "points": g.points, "closed": g.closed,
           "bbox": [g.x0, g.y0, g.x1, g.y1], "length_pt": None if g.length_pt is None else str(g.length_pt),
           "area_pt2": None if g.area_pt2 is None else str(g.area_pt2), "stroke_width": g.stroke_width,
           "stroke_color": g.stroke_color, "fill_color": g.fill_color, "layer": g.layer, "derived_from": g.derived_from,
           "approximate": g.approximate, "flags": g.flags or [], "duplicate_of": str(g.duplicate_of) if g.duplicate_of else None,
           "overlaps": g.overlaps or [], "extra": g.extra or {}, "status": g.status, "review_note": g.review_note,
           "source": {"path_index": g.path_index, "item_index": g.item_index}}
    if page is not None and g.length_pt is not None:
        out["length_paper_mm"] = str(paper_mm(g.length_pt).quantize(Decimal("0.01")))
        try:
            out["length_real_m"] = str(real_m(g.length_pt, page.scale_ratio, page.scale_status))
            out["real_basis"] = f"1:{page.scale_ratio} (đã xác nhận)"
        except CalcError as e:
            out["length_real_m"], out["real_basis"] = None, str(e)
    return out


@router.get("/drawings/{did}/geometry/summary")
def summary(did: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    d = get_drawing(db, did, user)
    pages = db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id).order_by(DrawingPage.page_no))
    counts = dict(db.execute(select(GeometryPrimitive.status, func.count()).where(GeometryPrimitive.drawing_id == d.id)
                             .group_by(GeometryPrimitive.status)).all())
    return {"drawing_id": str(d.id), "review_counts": counts,
            "pages": [{"page_no": p.page_no, "kind": p.kind, "geometry_status": p.geometry_status, "stats": p.geometry_stats or {},
                       "frame": p.page_frame, "scale_status": p.scale_status, "scale_ratio": p.scale_ratio} for p in pages]}


@router.get("/drawings/{did}/geometry")
def list_geometry(did: uuid.UUID, page: int | None = None, kind: str | None = None, status: str | None = None,
                  x0: float | None = None, y0: float | None = None, x1: float | None = None, y1: float | None = None,
                  include_duplicates: bool = False, min_length_pt: float | None = None,
                  limit: int = Query(2000, le=20000), offset: int = 0,
                  user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> list[dict]:
    d = get_drawing(db, did, user)
    stmt = select(GeometryPrimitive).where(GeometryPrimitive.drawing_id == d.id)
    if page:
        stmt = stmt.where(GeometryPrimitive.page_no == page)
    if kind:
        stmt = stmt.where(GeometryPrimitive.kind.in_(kind.split(",")))
    if status:
        stmt = stmt.where(GeometryPrimitive.status == status)
    if not include_duplicates:
        stmt = stmt.where(GeometryPrimitive.duplicate_of.is_(None))
    if None not in (x0, y0, x1, y1):  # intersects the window (display points)
        stmt = stmt.where(GeometryPrimitive.x1 >= x0, GeometryPrimitive.x0 <= x1, GeometryPrimitive.y1 >= y0, GeometryPrimitive.y0 <= y1)
    if min_length_pt is not None:
        stmt = stmt.where(GeometryPrimitive.length_pt >= Decimal(str(min_length_pt)))
    stmt = stmt.order_by(GeometryPrimitive.page_no, GeometryPrimitive.y0, GeometryPrimitive.x0).limit(limit).offset(offset)
    return [prim_dict(g) for g in db.scalars(stmt)]


@router.get("/drawings/{did}/geometry/axis-runs")
def axis_runs_view(did: uuid.UUID, page: int, min_length_pt: float = 15.0, user: User = Depends(require("drawing:read")),
                   db: Session = Depends(get_db)) -> list[dict]:
    """Collinear touching horizontal/vertical lines merged into continuous runs (borders drawn cell by cell)."""
    from app.geometry.primitives import Primitive, axis_runs
    d = get_drawing(db, did, user)
    rows = list(db.scalars(select(GeometryPrimitive).where(GeometryPrimitive.drawing_id == d.id, GeometryPrimitive.page_no == page,
                                                          GeometryPrimitive.kind == "line", GeometryPrimitive.duplicate_of.is_(None),
                                                          GeometryPrimitive.status != "rejected")))
    prims = [Primitive("line", [(Decimal(x), Decimal(y)) for x, y in g.points]) for g in rows]
    return [{"axis": r["axis"], "pos": str(r["pos"]), "start": str(r["start"]), "end": str(r["end"]), "length_pt": str(r["length_pt"]),
             "geometry_ids": [str(rows[i].id) for i in r["members"]]}
            for r in axis_runs(prims, min_len=Decimal(str(min_length_pt)))]


def _prim(db: Session, gid: uuid.UUID, user: User) -> tuple[GeometryPrimitive, DrawingPage]:
    g = db.get(GeometryPrimitive, gid)
    if not g or g.company_id != user.company_id:
        raise HTTPException(404, "Không tìm thấy đối tượng hình học")
    page = db.scalar(select(DrawingPage).where(DrawingPage.drawing_id == g.drawing_id, DrawingPage.page_no == g.page_no))
    return g, page


@router.get("/geometry/{gid}")
def get_one(gid: uuid.UUID, user: User = Depends(require("drawing:read")), db: Session = Depends(get_db)) -> dict:
    g, page = _prim(db, gid, user)
    return prim_dict(g, page)


class ReviewIn(BaseModel):
    status: str
    note: str = ""


@router.patch("/geometry/{gid}")
def review(gid: uuid.UUID, body: ReviewIn, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    g, page = _prim(db, gid, user)
    try:
        GS.review(db, user, g, body.status, body.note)
    except GS.GeometryError as e:
        raise HTTPException(e.status, str(e))
    db.commit()
    return prim_dict(g, page)


@router.post("/drawings/{did}/geometry/extract")
def extract(did: uuid.UUID, user: User = Depends(require("drawing:write")), db: Session = Depends(get_db)) -> dict:
    d: Drawing = get_drawing(db, did, user)
    try:
        return GS.run_extraction(db, user, d)
    except GS.GeometryError as e:
        raise HTTPException(e.status, str(e))
