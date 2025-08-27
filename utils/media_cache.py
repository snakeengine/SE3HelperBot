# utils/media_cache.py
from __future__ import annotations
import hashlib, os
from pathlib import Path
from typing import Optional

_CACHE_DIR = Path(os.getenv("MEDIA_CACHE_DIR", "cache/media"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_EXT = {"gif": "gif", "png": "png"}

def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()

def build_key(kind: str, payload: dict) -> str:
    """
    kind: 'gif' أو 'png'
    payload: كل النصوص + المقاسات + dpr + fps + seconds + lang
    """
    buf = repr(sorted(payload.items())).encode("utf-8")
    return f"{kind}_{_sha1(buf)}"

def get(kind: str, key: str) -> Optional[bytes]:
    ext = _EXT.get(kind, "bin")
    f = _CACHE_DIR / f"{key}.{ext}"
    return f.read_bytes() if f.exists() else None

def put(kind: str, key: str, data: bytes) -> str:
    ext = _EXT.get(kind, "bin")
    f = _CACHE_DIR / f"{key}.{ext}"
    f.write_bytes(data)
    return str(f)
