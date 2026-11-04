"""Content-addressed local store: files are written once under their SHA-256 and never modified."""
import hashlib
import re
from pathlib import Path

from app.config import get_settings


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ()]", "_", name, flags=re.UNICODE).strip(" .")
    return name[:200] or "file"


def save_bytes(company_id: str, data: bytes) -> tuple[str, str]:
    """Returns (sha256, storage_key). Idempotent: identical content is stored once per company."""
    digest = hashlib.sha256(data).hexdigest()
    key = f"{company_id}/{digest[:2]}/{digest}"
    path = Path(get_settings().storage_dir) / key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return digest, key


def open_path(storage_key: str) -> Path:
    root = Path(get_settings().storage_dir).resolve()
    p = (root / storage_key).resolve()
    if root not in p.parents:
        raise ValueError("invalid storage key")
    return p
