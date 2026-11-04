from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user, require
from app.models import AuditLog, User
from app.security import create_token, verify_password

router = APIRouter()


class Login(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: Login, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Sai email hoặc mật khẩu")
    return {"access_token": create_token(str(user.id)), "token_type": "bearer"}


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "role": user.role}


@router.get("/audit-logs")
def audit_logs(user: User = Depends(require("audit:read")), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AuditLog).where(AuditLog.company_id == user.company_id)
                      .order_by(AuditLog.created_at.desc()).limit(200))
    return [{"action": r.action, "entity": r.entity, "entity_id": str(r.entity_id),
             "user_id": str(r.user_id), "detail": r.detail} for r in rows]
