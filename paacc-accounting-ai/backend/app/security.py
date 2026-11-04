import datetime as dt
import hashlib
import hmac
import os

import jwt

from app.config import get_settings

_N, _R, _P = 2**14, 8, 1

# Role -> permissions. "*" = all. Extended per module in later phases.
ROLE_PERMS: dict[str, set[str]] = {
    "admin": {"*"},
    "director": {"project:read", "project:write", "contract:read", "contract:write",
                 "contract:approve", "partner:read", "partner:write", "audit:read", "document:read", "document:write",
                 "office:read", "office:manage", "ai_task:write", "ai_task:approve"},
    "accountant": {"project:read", "contract:read", "contract:write", "partner:read", "partner:write", "document:read", "document:write",
                   "office:read", "ai_task:write"},
    "site_manager": {"project:read", "project:write", "contract:read", "partner:read", "document:read", "document:write",
                     "office:read", "ai_task:write"},
    "viewer": {"project:read", "contract:read", "partner:read", "document:read", "office:read"},
}


def has_perm(role: str, perm: str) -> bool:
    perms = ROLE_PERMS.get(role, set())
    return "*" in perms or perm in perms


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P)
        return hmac.compare_digest(calc.hex(), h)
    except ValueError:
        return False


def _secret() -> str:
    s = get_settings().jwt_secret
    if len(s) < 16:
        raise RuntimeError("PAACC_JWT_SECRET must be set (>=16 chars)")
    return s


def create_token(user_id: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=get_settings().jwt_hours)
    return jwt.encode({"sub": user_id, "exp": exp}, _secret(), algorithm="HS256")


def decode_token(token: str) -> str:
    return jwt.decode(token, _secret(), algorithms=["HS256"])["sub"]
