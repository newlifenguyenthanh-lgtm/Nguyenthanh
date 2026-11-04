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
