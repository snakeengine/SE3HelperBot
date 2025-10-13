from __future__ import annotations

# utils/media_cache.py

import hashlib, os
from pathlib import Path
from typing import Optional

try:
    from utils.paths import BASE
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "data")).resolve()

_CACHE_DIR = (BASE / "cache" / "media")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_EXT = {"gif": "gif", "png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp"}

def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()

def build_key(kind: str, payload: dict) -> str:
    """
    kind: 'gif' | 'png' | 'jpg' | 'webp' ...
    payload: أي بيانات تُحدد المُخرَج (نصوص/مقاسات/dpr/fps/seconds/lang ...).
    """
    buf = repr(sorted(payload.items())).encode("utf-8")
    return f"{kind}_{_sha1(buf)}"

def _path_for(kind: str, key: str) -> Path:
    ext = _EXT.get(kind.lower(), "bin")
    return _CACHE_DIR / f"{key}.{ext}"

def get(kind: str, key: str) -> Optional[bytes]:
    p = _path_for(kind, key)
    try:
        return p.read_bytes() if p.exists() else None
    except Exception:
        return None

def put(kind: str, key: str, data: bytes) -> str:
    p = _path_for(kind, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)
