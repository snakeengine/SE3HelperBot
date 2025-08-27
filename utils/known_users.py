# utils/known_users.py
from __future__ import annotations
import json
from pathlib import Path

USERS_PATH = Path("data/users.json")

def _ensure_file():
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not USERS_PATH.exists():
        USERS_PATH.write_text("[]", encoding="utf-8")

def add_known_user(uid: int) -> None:
    _ensure_file()
    try:
        data = json.loads(USERS_PATH.read_text(encoding="utf-8") or "[]")
        if isinstance(data, dict):
            key = str(uid)
            if key not in data:
                data[key] = {}
        else:
            # قائمة
            if uid not in data:
                data.append(uid)
        USERS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # fallback آمن: اكتب كقائمة
        USERS_PATH.write_text(json.dumps([uid], ensure_ascii=False, indent=2), encoding="utf-8")
