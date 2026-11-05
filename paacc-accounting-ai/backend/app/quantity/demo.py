"""PAACC quantity engine demo (Phase 5E-2). Deterministic, offline, in-memory SQLite; SYNTHETIC data only.

    python -m app.quantity.demo              # A) seeded components/measurements -> rule registry -> quantities
    python -m app.quantity.demo --pipeline   # + B) synthetic vector PDF -> 5A..5D -> scripted DEMO review -> 5E-2

Confirmations in this demo are scripted and labelled DEMO; in the product only an engineer confirms. Nothing here is a
real drawing or a real-world accuracy claim.
"""
import argparse
import os
import sys
import tempfile
from decimal import Decimal

DEMO_SECRET = "demo-local-secret-not-for-production"


def _env(tmp: str) -> None:
    os.environ.setdefault("PAACC_JWT_SECRET", DEMO_SECRET)
    os.environ["PAACC_STORAGE_DIR"] = tmp
    os.environ["PAACC_OCR_ENABLED"] = "false"


def _engine():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from app.models import Base
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


# ---------------------------------------------------------------- A) seeded dataset (spec §20)
SEED = [  # (label, component_type, status, measurement kind, value, unit, parameters)
    ("C1", "STEEL_POST", "CONFIRMED", "count", "51", "count",
     {"unit_length": {"value": "2.5", "unit": "m", "source_type": "ENGINEER_INPUT", "source_reference": "DEMO – chi tiết trụ (giả lập)"}}),
    ("C2", "GUARDRAIL", "CONFIRMED", "length", "125.40", "m", {}),
    ("C3", "BOLT", "CONFIRMED", "count", "240", "count", {}),
    ("C4", "CORRUGATED_SHEET", "CONFIRMED", "area", "85.75", "m2", {}),
    ("C5", "STEEL_POST", "CONFIRMED", "length", "100", "m",
     {"unit_weight": {"value": "3.95", "unit": "kg/m", "source_type": "PROJECT_STANDARD", "source_reference": "DEMO – tiêu chuẩn ST-001 (giả lập)"}}),
    ("C6", "STEEL_POST", "CANDIDATE", "count", "20", "count", {}),
]


def seed(db, user):
    import uuid

    from app.components.service import ensure_taxonomy
    from app.models import (ComponentSource, ComponentType, Document, DocumentVersion, Drawing, DrawingComponent, DrawingPage,
                            GeometryPrimitive, Measurement)
    ensure_taxonomy(db, user.company_id)
    doc = Document(company_id=user.company_id, title="DEMO – bản vẽ giả lập", kind="drawing")
    db.add(doc)
    db.flush()
    ver = DocumentVersion(company_id=user.company_id, document_id=doc.id, version_no=1, filename="demo.pdf", size_bytes=0,
                          sha256="0" * 64, storage_key="demo/none", uploaded_by=user.id)
    db.add(ver)
    db.flush()
    d = Drawing(company_id=user.company_id, document_id=doc.id, document_version_id=ver.id, version_no=1, sha256="0" * 64,
                filename="demo.pdf", status="processed", page_count=1, created_by=user.id)
    db.add(d)
    db.flush()
    page = DrawingPage(company_id=user.company_id, drawing_id=d.id, page_no=1, width_pt=1190, height_pt=842, kind="vector",
                       view_types=[{"value": "plan", "basis": "demo", "confidence": 1.0}], scale_status="confirmed", scale_ratio=100)
    db.add(page)
    db.flush()
    comps = {}
    for i, (label, ctype, status, kind, value, unit, params) in enumerate(SEED):
        y = 100.0 + 60 * i
        g = GeometryPrimitive(company_id=user.company_id, drawing_id=d.id, page_no=1, kind="line", points=[["100", str(y)], ["500", str(y)]],
                              closed=False, x0=100, y0=y, x1=500, y1=y, length_pt=Decimal("400"), path_index=i, item_index=0)
        db.add(g)
        db.flush()
        m = Measurement(company_id=user.company_id, drawing_id=d.id, page_no=1, kind=kind, geometry_ids=[str(g.id)],
                        value_paper=Decimal(value), paper_unit="count" if kind == "count" else "pt", value_real=Decimal(value),
                        real_unit=unit, scale_ratio=None if kind == "count" else 100, scale_source="demo-seed", formula="DEMO seed value",
                        method="demo-seed", status="confirmed", note="DEMO – giá trị giả lập", created_by=user.id)
        db.add(m)
        db.flush()
        t = db.query(ComponentType).filter_by(company_id=user.company_id, code=ctype).one_or_none()
        c = DrawingComponent(company_id=user.company_id, drawing_id=d.id, page_id=page.id, page_no=1, component_type=ctype,
                             component_type_id=t.id if t else None, name=t.name_vi if t else ctype, description=f"DEMO {label}",
                             x0=100, y0=y, x1=500, y1=y, centroid_x=300, centroid_y=y, view_context="PLAN", recognition_method="rule",
                             recognition_rule="demo-seed", recognition_confidence=1.0, confidence_band="HIGH", status=status,
                             reviewed_by=user.id if status == "CONFIRMED" else None)
        db.add(c)
        db.flush()
        db.add(ComponentSource(company_id=user.company_id, component_id=c.id, source_type="geometry", role="demo", geometry_id=g.id))
        db.add(ComponentSource(company_id=user.company_id, component_id=c.id, source_type="measurement", role=kind, measurement_id=m.id))
        comps[label] = (c, params)
    db.commit()
    _ = uuid
    return d, comps


def _row(label, ctype, rule, formula, qty, unit, status, source):
    return f"{label:<4}{ctype:<18}{rule:<26}{formula:<40}{qty:>12} {unit:<4} {status:<16}{source}"


def demo_seeded(out=sys.stdout) -> list[dict]:
    from sqlalchemy.orm import Session

    from app.cli import create_admin
    from app.quantity import engine as E
    from app.quantity import service as S
    from app.models import QuantityResult
    eng = _engine()
    rows = []
    with Session(eng, expire_on_commit=False) as db:
        user = create_admin(db, "DEMO Co", "demo@paacc.local", "demo-password-1")
        d, comps = seed(db, user)
        params = {str(c.id): p for c, p in comps.values() if p}
        summary = S.run_drawing(db, user, d, params)
        db.commit()
        print("PAACC QUANTITY ENGINE DEMO  (dữ liệu GIẢ LẬP – không phải bản vẽ thật)\n", file=out)
        print(_row("", "Cấu kiện", "Quy tắc", "Công thức", "Khối lượng", "ĐV", "Trạng thái", "Nguồn"), file=out)
        label_of = {str(c.id): lbl for lbl, (c, _) in comps.items()}
        for rid in summary["result_ids"]:
            q = db.get(QuantityResult, __import__("uuid").UUID(rid))
            src = ",".join(m["id"][:8] for m in q.source_measurement)
            val = "—" if q.quantity_value is None else E.fmt(q.quantity_value, q.unit, q.precision).rsplit(" ", 1)[0]
            rows.append({"label": label_of[str(q.component_id)], "type": q.source_component["component_type"], "rule": q.rule_code,
                         "trace": q.formula_trace, "value": val, "unit": q.unit, "status": q.status})
            print(_row(label_of[str(q.component_id)], q.source_component["component_type"], q.rule_code or q.calculation_method,
                       q.formula_trace or q.formula, val, E.UNIT_LABEL.get(q.unit, q.unit), q.status, f"measurement {src}"), file=out)
        c6, _ = comps["C6"]
        try:
            S.run(db, user, c6, None, {}, None, None, rule_code="STEEL_POST.COUNT")
            status = "UNEXPECTED"
        except E.QuantityError as e:
            status = f"BLOCKED (HTTP {e.status})"
            db.rollback()
        rows.append({"label": "C6", "type": "STEEL_POST", "rule": "STEEL_POST.COUNT", "trace": "", "value": "—", "unit": "",
                     "status": status})
        print(_row("C6", "STEEL_POST", "STEEL_POST.COUNT", "cấu kiện CANDIDATE", "—", "", status, ""), file=out)
        print(f"\nTóm tắt: {({k: v for k, v in summary.items() if k != 'result_ids'})}", file=out)
    return rows


# ---------------------------------------------------------------- B) full pipeline on a synthetic vector PDF
def _fence_pdf() -> bytes:
    import pymupdf
    doc = pymupdf.open()
    p = doc.new_page(width=1190, height=842)
    p.draw_rect(pymupdf.Rect(820, 700, 1160, 812), width=0.8)
    p.insert_text((830, 720), "BAN VE SO: DEMO-01", fontsize=9)
    p.insert_text((830, 740), "TEN BAN VE: MAT BANG BO TRI HANG RAO", fontsize=9)
    xs = [100 + 60 * i for i in range(10)]
    p.draw_line((80, 300), (660, 300), width=0.6)
    for x in xs:
        p.draw_circle((x, 300), 4, width=0.5)
    p.insert_text((330, 292), "HANG RAO B40", fontsize=9)
    return doc.tobytes()


def demo_pipeline(out=sys.stdout) -> list[dict]:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.cli import create_admin
    from app.db import get_db
    from app.main import app
    eng = _engine()

    def override():
        with Session(eng, expire_on_commit=False) as s:
            yield s
    app.dependency_overrides[get_db] = override
    with Session(eng) as s:
        create_admin(s, "DEMO Co", "demo@paacc.local", "demo-password-1")
    c = TestClient(app)
    B = "/api/v1"
    tok = c.post(f"{B}/auth/login", json={"email": "demo@paacc.local", "password": "demo-password-1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    doc = c.post(f"{B}/documents", data={"title": "DEMO fence", "kind": "drawing"},
                 files={"file": ("demo.pdf", _fence_pdf(), "application/pdf")}, headers=h).json()
    d = c.post(f"{B}/drawings", json={"document_id": doc["id"]}, headers=h).json()
    c.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": 100}, headers=h)
    c.post(f"{B}/drawings/{d['id']}/associations/run", headers=h)
    c.post(f"{B}/drawings/{d['id']}/components/run", headers=h)
    print("\n— Pipeline: PDF giả lập → 5A hình học → 5B phép đo → 5C liên kết → 5D cấu kiện → 5E-2 khối lượng —", file=out)
    print("  (kỹ sư DEMO xác nhận theo kịch bản; trong sản phẩm chỉ kỹ sư thật mới xác nhận)", file=out)
    for comp in c.get(f"{B}/drawings/{d['id']}/components", headers=h).json():
        if comp["status"] == "CANDIDATE":
            c.post(f"{B}/components/{comp['id']}/review", json={"note": "DEMO"}, headers=h)
        c.post(f"{B}/components/{comp['id']}/confirm", json={"note": "DEMO – xác nhận theo kịch bản"}, headers=h)
        for mid in comp["source_measurement_ids"]:
            c.post(f"{B}/measurements/{mid}/confirm", json={"note": "DEMO – xác nhận theo kịch bản"}, headers=h)
    summary = c.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=h).json()
    rows = c.get(f"{B}/drawings/{d['id']}/quantity-results", headers=h).json()
    for r in rows:
        print(_row("", r["component_type"], r["rule_code"] or r["calculation_method"], r["formula_trace"] or r["formula"],
                   r["quantity_value"] or "—", r["unit"], r["status"], f"trang {r['page_no']}"), file=out)
    print(f"Tóm tắt: {({k: v for k, v in summary.items() if k != 'result_ids'})}", file=out)
    app.dependency_overrides.clear()
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pipeline", action="store_true", help="also run a synthetic vector PDF through 5A..5E-2")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        _env(tmp)
        demo_seeded()
        if args.pipeline:
            demo_pipeline()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
