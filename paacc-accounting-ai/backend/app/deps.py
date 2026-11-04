import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, User
from app.security import decode_token, has_perm

bearer = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(401, "Chưa đăng nhập")
    try:
        user = db.get(User, uuid.UUID(decode_token(cred.credentials)))
    except Exception:
        raise HTTPException(401, "Token không hợp lệ")
    if user is None or not user.is_active:
        raise HTTPException(401, "Tài khoản không hợp lệ")
    return user


def require(perm: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not has_perm(user.role, perm):
            raise HTTPException(403, "Không đủ quyền")
        return user
    return dep


def audit(db: Session, user: User, action: str, entity: str, entity_id, detail: dict | None = None):
    db.add(AuditLog(company_id=user.company_id, user_id=user.id, action=action,
                    entity=entity, entity_id=entity_id, detail=detail))
