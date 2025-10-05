# utils/admins.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Iterable
from utils.admin_roles import load_roles

_DATA = Path("data"); _DATA.mkdir(parents=True, exist_ok=True)
_STORE = _DATA / "admin_ids.json"

def _load_file() -> set[int]:
    try:
        if _STORE.exists():
            arr = json.loads(_STORE.read_text(encoding="utf-8")) or []
            return {int(x) for x in arr if str(x).isdigit()}
    except Exception:
        pass
    return set()

def _save_file(ids: Iterable[int]) -> None:
    _STORE.write_text(
        json.dumps(sorted({int(x) for x in ids}), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

_OWNER_ENV = os.getenv("OWNER_IDS") or os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID","")
OWNERS: set[int] = {int(x) for x in _OWNER_ENV.split(",") if x.strip().isdigit()}

ADMIN_IDS: set[int] = set(OWNERS) | _load_file()

def is_admin(uid: int) -> bool:
    return int(uid) in ADMIN_IDS

def list_admins() -> list[int]:
    return sorted(ADMIN_IDS)

def add_admin(uid: int) -> tuple[bool, str]:
    uid = int(uid)
    if uid in ADMIN_IDS:
        return False, "already"
    ADMIN_IDS.add(uid)
    _save_file(ADMIN_IDS - OWNERS)
    return True, "added"

def remove_admin(uid: int) -> tuple[bool, str]:
    uid = int(uid)
    if uid in OWNERS:
        return False, "owner_protected"
    if uid not in ADMIN_IDS:
        return False, "not_found"
    ADMIN_IDS.discard(uid)
    _save_file(ADMIN_IDS - OWNERS)
    return True, "removed"

def is_admin(user_id: int) -> bool:
    try:
        if int(user_id) in set(ADMIN_IDS):
            return True
    except Exception:
        pass
    try:
        roles = load_roles()
        return int(user_id) in set(roles.get("default", []))
    except Exception:
        return False