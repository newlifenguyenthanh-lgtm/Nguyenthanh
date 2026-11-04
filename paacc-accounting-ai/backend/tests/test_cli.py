import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import cli
from app.models import Base, User


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_create_user_in_same_company_with_role(db):
    admin = cli.create_admin(db, "Cty", "Admin@x.test", "pw-admin-123")
    u = cli.create_user(db, "admin@x.test", "QS@x.test", "qs_engineer", "pw-qs-12345", "Kỹ sư QS")
    assert u.company_id == admin.company_id and u.role == "qs_engineer" and u.email == "qs@x.test"
    assert u.password_hash.startswith("scrypt$") and "pw-qs" not in u.password_hash


@pytest.mark.parametrize("args,msg", [
    (("admin@x.test", "a@x.test", "superuser", "pw-12345678"), "Vai trò"),
    (("admin@x.test", "a@x.test", "viewer", "short"), "8 ký tự"),
    (("nobody@x.test", "a@x.test", "viewer", "pw-12345678"), "tham chiếu"),
    (("admin@x.test", "admin@x.test", "viewer", "pw-12345678"), "đã tồn tại"),
])
def test_create_user_validation(db, args, msg):
    cli.create_admin(db, "Cty", "admin@x.test", "pw-admin-123")
    with pytest.raises(cli.CliError, match=msg):
        cli.create_user(db, *args)
    assert len(list(db.scalars(select(User)))) == 1


def test_main_requires_password_env(monkeypatch, capsys):
    monkeypatch.delenv("NOPE_PW", raising=False)
    assert cli.main(["create-admin", "--company", "c", "--email", "e@x.test", "--password-env", "NOPE_PW"]) == 2
    assert "NOPE_PW" in capsys.readouterr().err
