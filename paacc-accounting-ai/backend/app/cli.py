"""Bootstrap (run `alembic upgrade head` first): python -m app.cli create-admin --company "Công ty Phương Anh" --email x --password-env VAR"""
import argparse
import os

from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Company, User
from app.security import hash_password


def create_admin(db: Session, company: str, email: str, password: str, full_name: str = "") -> User:
    co = Company(name=company)
    db.add(co); db.flush()
    u = User(company_id=co.id, email=email.lower(), full_name=full_name,
             password_hash=hash_password(password), role="admin")
    db.add(u); db.commit()
    return u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create-admin"])
    ap.add_argument("--company", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password-env", required=True, help="name of env var holding the password")
    a = ap.parse_args()
    with Session(get_engine()) as db:
        create_admin(db, a.company, a.email, os.environ[a.password_env])
    print("admin created")


if __name__ == "__main__":
    main()
