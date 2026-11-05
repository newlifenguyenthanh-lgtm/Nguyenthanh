"""Migrations and critical workflows on real PostgreSQL (exact NUMERIC money, UUID, JSON)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.cli import create_admin
from app.db import get_db
from app.main import app
from app.models import User
from app.security import hash_password
from tests import pdf_factory as pf
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr
from tests.pg_support import alembic_cfg, fresh_pg_engine, requires_pg

pytestmark = requires_pg


@pytest.fixture()
def pg(tmp_path, monkeypatch):
    monkeypatch.setenv("PAACC_STORAGE_DIR", str(tmp_path / "store"))
    engine = fresh_pg_engine(monkeypatch)

    def override():
        with Session(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[get_db] = override
    with Session(engine) as s:
        admin = create_admin(s, "PG Co A", "admin@pga.test", "pw-admin-1")
        s.add(User(company_id=admin.company_id, email="director@pga.test", password_hash=hash_password("pw-x"), role="director"))
        create_admin(s, "PG Co B", "admin@pgb.test", "pw-admin-2")
        s.commit()
    yield TestClient(app), engine
    app.dependency_overrides.clear()
    engine.dispose()


def test_migrations_upgrade_downgrade_roundtrip(pg, monkeypatch):
    from alembic import command
    _, engine = pg
    tables = set(inspect(engine).get_table_names())
    assert {"companies", "documents", "ai_tasks", "drawings", "drawing_pages", "extracted_items"} <= tables
    command.downgrade(alembic_cfg(), "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(alembic_cfg(), "head")
    with engine.connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar()


def test_money_is_exact_numeric_on_postgres(pg):
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d = login(client, "director@pga.test", "pw-x")
    pid = client.post(f"{B}/projects", json={"code": "P", "name": "p"}, headers=a).json()["id"]
    part = client.post(f"{B}/partners", json={"name": "x", "kind": "customer"}, headers=a).json()["id"]
    cid = client.post(f"{B}/contracts", json={"project_id": pid, "partner_id": part, "number": "1", "direction": "outbound",
                                              "original_value": "123456789012345.67"}, headers=a).json()["id"]
    ap = client.post(f"{B}/contracts/{cid}/appendices", json={"number": "PL", "delta_value": "0.01"}, headers=a).json()
    client.post(f"{B}/appendices/{ap['id']}/approve", headers=d)
    assert client.get(f"{B}/contracts/{cid}/summary", headers=a).json()["adjusted_value"] == "123456789012345.68"


def test_drawing_workflow_and_isolation_on_postgres(pg, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    b = login(client, "admin@pgb.test", "pw-admin-2")
    d = process(client, a, upload(client, a, pf.mixed_doc())["id"]).json()
    assert d["status"] == "processed" and d["page_count"] == 2
    full = client.get(f"{B}/drawings/{d['id']}", headers=a).json()
    assert [p["kind"] for p in full["pages"]] == ["vector", "scanned"]
    assert client.get(f"{B}/drawings/{d['id']}", headers=b).status_code == 404
    assert client.get(f"{B}/office/departments/engineering_qs", headers=a).json()["agents"][0]["status"] == "completed"


def test_boq_generation_on_postgres(pg, monkeypatch):
    from tests.drawing_helpers import make_boq, processed_drawing
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d = processed_drawing(client, a)
    boq = make_boq(client, a, [d["id"]]).json()
    qs = {i["quantity"] for i in boq["items"]}
    assert {"4.3200", "180.8640", "37.6800", "132.5800", "180.8600"} <= qs
    again = client.get(f"{B}/boqs/{boq['id']}", headers=a).json()
    assert [i["quantity"] for i in again["items"]] == [i["quantity"] for i in boq["items"]]


def test_boq_review_and_approval_on_postgres(pg, monkeypatch):
    from tests.drawing_helpers import make_boq, processed_drawing
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d_ = login(client, "director@pga.test", "pw-x")
    boq = make_boq(client, a, [processed_drawing(client, a)["id"]]).json()
    base = f"{B}/boqs/{boq['id']}"
    for i in boq["items"]:
        dec = "accept" if not i["has_blocking"] and i["module"] else "reject"
        assert client.post(f"{base}/items/{i['id']}/review", json={"decision": dec, "note": "pg"}, headers=a).status_code == 200
    assert client.post(f"{base}/submit", json={"note": ""}, headers=a).json()["status"] == "submitted"
    assert client.post(f"{base}/decision", json={"decision": "approve"}, headers=a).status_code == 403  # four eyes
    approved = client.post(f"{base}/decision", json={"decision": "approve"}, headers=d_).json()
    assert approved["status"] == "approved"
    t = {(x["category"], x["unit"]): x["accepted"] for x in approved["totals"]}
    assert t[("concrete", "m3")] == "4.3200" and t[("steel_box", "kg")] == "180.8640"


def test_boq_export_on_postgres(pg, monkeypatch, tmp_path):
    import io

    import openpyxl
    from tests.drawing_helpers import make_boq, processed_drawing
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    boq = make_boq(client, a, [processed_drawing(client, a)["id"]]).json()
    exp = client.post(f"{B}/boqs/{boq['id']}/exports", headers=a).json()
    wb = openpyxl.load_workbook(io.BytesIO(client.get(f"{B}/boq-exports/{exp['id']}/download", headers=a).content))
    assert wb.sheetnames == ["Tổng hợp", "BOQ", "Tính chi tiết", "Truy vết nguồn"]
    assert client.get(f"{B}/boqs/{boq['id']}/exports", headers=a).json()[0]["sha256"] == exp["sha256"]


def test_vector_geometry_on_postgres(pg, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d = process(client, a, upload(client, a, pf.vector_pdf())["id"]).json()
    assert client.get(f"{B}/drawings/{d['id']}/geometry/summary", headers=a).json()["pages"][0]["geometry_status"] == "extracted"
    border = client.get(f"{B}/drawings/{d['id']}/geometry?kind=rect&min_length_pt=3000", headers=a).json()
    assert [g["length_pt"] for g in border] == ["3904.0000"]
    runs = client.get(f"{B}/drawings/{d['id']}/geometry/axis-runs?page=1", headers=a).json()
    assert runs and all(r["geometry_ids"] for r in runs)


def test_measurements_on_postgres(pg, monkeypatch):
    from tests.geometry_helpers import sheet
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d = process(client, a, upload(client, a, sheet())["id"]).json()
    client.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": 100}, headers=a)
    g = next(x for x in client.get(f"{B}/drawings/{d['id']}/geometry?kind=line", headers=a).json() if x["length_pt"] == "720.0000")
    m = client.post(f"{B}/measurements", json={"drawing_id": d["id"], "kind": "length", "geometry_ids": [g["id"]]}, headers=a).json()
    assert m["value_real"] == "25.400000" and client.get(f"{B}/measurements/{m['id']}", headers=a).json()["value_real"] == "25.400000"


def test_associations_on_postgres(pg, monkeypatch):
    from tests.geometry_helpers import sheet
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d = process(client, a, upload(client, a, sheet())["id"]).json()
    client.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": 100}, headers=a)
    assert client.post(f"{B}/drawings/{d['id']}/associations/run", headers=a).status_code == 200
    blocks = {b["original_text"]: b for b in client.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=a).json()}
    assert blocks["Km12+350"]["values"]["chainage"][0]["meters"] == "12350"
    rows = client.get(f"{B}/drawings/{d['id']}/pages/1/associations?text_block_id={blocks['L=13.50m']['id']}", headers=a).json()
    top = rows[0]
    assert top["status"] == "CONFLICT" and (top["text_value"], top["measured_value"], top["difference"]) == ("13.5", "12.7", "0.8")
    ok = client.post(f"{B}/associations/{top['id']}/confirm", json={"note": "kỹ sư chấp nhận, sẽ sửa bản vẽ"}, headers=a).json()
    assert ok["status"] == "CONFIRMED"
    p = client.get(f"{B}/associations/{top['id']}", headers=a).json()["provenance"]
    assert p["measurement"]["value_real"] == "12.700000" and p["downstream_allowed"] is True


def test_components_on_postgres(pg, monkeypatch):
    from tests import component_helpers as H
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d = process(client, a, upload(client, a, H.sheet_plan_detail())["id"]).json()
    for n in (1, 2):
        client.post(f"{B}/drawings/{d['id']}/pages/{n}/calibration", json={"scale_ratio": 10}, headers=a)
    run = client.post(f"{B}/drawings/{d['id']}/components/run", headers=a).json()
    assert run["representations"] == 1 and run["task_status"] == "waiting_approval"
    cs = client.get(f"{B}/drawings/{d['id']}/components", headers=a).json()
    plan = next(c for c in cs if c["page_no"] == 1)
    det = next(c for c in cs if c["page_no"] == 2)
    assert plan["component_type"] == det["component_type"] == "STEEL_POST" and det["representation_of_id"] == plan["id"]
    ev = client.get(f"{B}/components/{plan['id']}/evidence", headers=a).json()
    assert ev["measurements"][0]["value_real"] == "0.0883"
    assert plan["status"] == "REVIEW_REQUIRED"  # MEDIUM evidence: already in the review queue
    assert client.post(f"{B}/components/{plan['id']}/review", json={}, headers=a).status_code == 409  # REVIEW_REQUIRED -> itself: invalid
    assert client.post(f"{B}/components/{plan['id']}/confirm", json={}, headers=a).json()["status"] == "CONFIRMED"
    [b] = client.get(f"{B}/drawings/{d['id']}/component-boq-candidates", headers=a).json()
    assert b["approval_status"] == "NOT_APPROVED" and b["measurement_id"] is None  # count of a single post: not measured, 5E decides
    other = login(client, "admin@pgb.test", "pw-admin-2")
    assert client.get(f"{B}/components/{plan['id']}", headers=other).status_code == 404
    assert [h["action"] for h in client.get(f"{B}/components/{plan['id']}/history", headers=a).json()] == \
        ["confirm", "prepare_boq_candidate"]


def test_quantity_results_on_postgres(pg, monkeypatch):
    from tests import component_helpers as H
    use_ocr(monkeypatch, FakeOcr())
    client, _ = pg
    a = login(client, "admin@pga.test", "pw-admin-1")
    d = process(client, a, upload(client, a, H.sheet_fence())["id"]).json()
    client.post(f"{B}/drawings/{d['id']}/pages/1/calibration", json={"scale_ratio": 100}, headers=a)
    client.post(f"{B}/drawings/{d['id']}/components/run", headers=a)
    f = next(c for c in client.get(f"{B}/drawings/{d['id']}/components", headers=a).json() if c["component_type"] == "FENCE")
    assert client.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=a).status_code == 422  # still CANDIDATE
    client.post(f"{B}/components/{f['id']}/review", json={}, headers=a)
    client.post(f"{B}/components/{f['id']}/confirm", json={}, headers=a)
    r1 = client.post(f"{B}/components/{f['id']}/quantity/run", json={}, headers=a).json()
    client.post(f"{B}/measurements/{r1['measurement_id']}/confirm", json={"note": "ok"}, headers=a)
    r2 = client.post(f"{B}/components/{f['id']}/quantity/run", json={"precision": 2}, headers=a).json()
    got = client.get(f"{B}/quantity-results/{r2['id']}", headers=a).json()
    assert (got["raw_value"], got["quantity_value"], got["unit"], got["status"]) == ("20.461", "20.46", "m", "CALCULATED")
    assert got["provenance"]["measurements"][0]["status"] == "confirmed"
    assert client.get(f"{B}/quantity-results/{r1['id']}", headers=a).json()["superseded_by_id"] == r2["id"]
    other = login(client, "admin@pgb.test", "pw-admin-2")
    assert client.get(f"{B}/quantity-results/{r2['id']}", headers=other).status_code == 404
    assert client.post(f"{B}/quantity-results/{r2['id']}/review", json={"decision": "confirm"}, headers=a).json()["status"] == "CONFIRMED"
