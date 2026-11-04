"""Bootstrap and user administration (run `alembic upgrade head` first).

  python -m app.cli create-admin --company "Công ty Phương Anh" --email admin@example.com --password-env PAACC_ADMIN_PW
  python -m app.cli create-user  --company-of admin@example.com --email qs@example.com --role qs_engineer \
                                 --full-name "Kỹ sư QS" --password-env PAACC_USER_PW
Passwords are read from an environment variable so they never appear in shell history.
"""
import argparse
import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Company, User
from app.security import ROLE_PERMS, hash_password


class CliError(ValueError):
    pass


def create_admin(db: Session, company: str, email: str, password: str, full_name: str = "") -> User:
    co = Company(name=company)
    db.add(co); db.flush()
    u = User(company_id=co.id, email=email.lower(), full_name=full_name,
             password_hash=hash_password(password), role="admin")
    db.add(u); db.commit()
    return u


def create_user(db: Session, company_of: str, email: str, role: str, password: str, full_name: str = "") -> User:
    if role not in ROLE_PERMS:
        raise CliError(f"Vai trò không hợp lệ: {role}. Hợp lệ: {', '.join(sorted(ROLE_PERMS))}")
    if len(password) < 8:
        raise CliError("Mật khẩu phải có ít nhất 8 ký tự")
    ref = db.scalar(select(User).where(User.email == company_of.lower()))
    if ref is None:
        raise CliError(f"Không tìm thấy người dùng tham chiếu {company_of}")
    if db.scalar(select(User).where(User.email == email.lower())):
        raise CliError(f"Email đã tồn tại: {email}")
    u = User(company_id=ref.company_id, email=email.lower(), full_name=full_name, password_hash=hash_password(password), role=role)
    db.add(u); db.commit()
    return u


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("create-admin")
    a1.add_argument("--company", required=True)
    a2 = sub.add_parser("create-user")
    a2.add_argument("--company-of", required=True, help="email of an existing user of the target company")
    a2.add_argument("--role", required=True, choices=sorted(ROLE_PERMS))
    for p in (a1, a2):
        p.add_argument("--email", required=True)
        p.add_argument("--full-name", default="")
        p.add_argument("--password-env", required=True, help="name of env var holding the password")
    a = ap.parse_args(argv)
    password = os.environ.get(a.password_env)
    if not password:
        print(f"Biến môi trường {a.password_env} chưa được đặt", file=sys.stderr)
        return 2
    with Session(get_engine()) as db:
        try:
            if a.cmd == "create-admin":
                create_admin(db, a.company, a.email, password, a.full_name)
            else:
                create_user(db, a.company_of, a.email, a.role, password, a.full_name)
        except CliError as e:
            print(str(e), file=sys.stderr)
            return 1
    print(f"{a.cmd}: {a.email} OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
