import os

os.environ["PAACC_JWT_SECRET"] = "test-secret-not-for-production-use"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.cli import create_admin
from app.db import get_db
from app.main import app
from app.models import Base, User
from app.security import hash_password

B = "/api/v1"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PAACC_STORAGE_DIR", str(tmp_path / "store"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override():
        with Session(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[get_db] = override
    with Session(engine) as s:
        admin = create_admin(s, "Cty A", "admin@a.test", "pw-admin-1")
        co = admin.company_id
        for role in ("viewer", "director"):
            s.add(User(company_id=co, email=f"{role}@a.test", password_hash=hash_password("pw-x"), role=role))
        other = create_admin(s, "Cty B", "admin@b.test", "pw-admin-2")
        s.commit()
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def login(client, email, pw):
    r = client.post(f"{B}/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
