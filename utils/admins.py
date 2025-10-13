# utils/admins.py
from __future__ import annotations

import os, json, threading
from pathlib import Path

# حاول أخذ BASE من utils.paths، وإلا استخدم data/
try:
    from utils.paths import BASE as _BASE
except Exception:
    _BASE = Path("data")

_DATA_DIR = Path(os.getenv("DATA_DIR") or _BASE or Path("data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ملف التخزين الموّحد
_ADM_FILE = _DATA_DIR / "admins.json"
_LOCK = threading.Lock()

def _parse_ids(s: str) -> list[int]:
    out: list[int] = []
    for p in (s or "").replace(";", ",").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except Exception:
            pass
    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set(); uniq = []
    for x in out:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq

def _load() -> dict:
    try:
        if _ADM_FILE.exists():
            return json.loads(_ADM_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    # fallback من البيئة
    owners_env = os.getenv("OWNER_IDS", "") or os.getenv("OWNERS", "")
    admins_env = os.getenv("ADMIN_IDS", "") or os.getenv("ADMIN_ID", "")
    owners = _parse_ids(owners_env)
    admins = _parse_ids(admins_env)
    for oid in owners:
        if oid not in admins:
            admins.append(oid)
    return {"owners": owners, "admins": admins}

def _save(d: dict) -> None:
    try:
        _ADM_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ADM_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _ADM_FILE)
    except Exception:
        pass

def get_owner_ids() -> list[int]:
    with _LOCK:
        d = _load()
    return [int(x) for x in (d.get("owners") or []) if str(x).isdigit()]

def get_admin_ids() -> list[int]:
    with _LOCK:
        d = _load()
    owners = set(int(x) for x in (d.get("owners") or []) if str(x).isdigit())
    admins: list[int] = []
    for x in (d.get("admins") or []):
        try:
            xi = int(x)
        except Exception:
            continue
        if xi not in admins:
            admins.append(xi)
    for oid in owners:
        if oid not in admins:
            admins.append(oid)
    return admins

def list_admins() -> list[int]:
    return get_admin_ids()

def is_admin(user_id: int | str) -> bool:
    try:
        uid = int(user_id)
    except Exception:
        return False
    return uid in get_admin_ids()

def add_admin(user_id: int | str, *, owner: bool = False) -> bool:
    try:
        uid = int(user_id)
    except Exception:
        return False
    with _LOCK:
        d = _load()
        admins = [int(x) for x in (d.get("admins") or []) if str(x).isdigit()]
        owners = [int(x) for x in (d.get("owners") or []) if str(x).isdigit()]
        changed = False
        if uid not in admins:
            admins.append(uid); changed = True
        if owner and uid not in owners:
            owners.append(uid); changed = True
        if changed:
            d["admins"] = admins
            d["owners"] = owners
            _save(d)
        return changed

def remove_admin(user_id: int | str) -> bool:
    try:
        uid = int(user_id)
    except Exception:
        return False
    with _LOCK:
        d = _load()
        admins = [int(x) for x in (d.get("admins") or []) if str(x).isdigit()]
        if uid in admins:
            admins = [x for x in admins if x != uid]
            d["admins"] = admins
            _save(d)
            return True
        return False

# متغيرات جاهزة للاستخدام/التوافق
ADMIN_IDS = get_admin_ids()
OWNER_IDS = get_owner_ids()

# aliases للتوافق الخلفي مع ملفات قديمة
ADMINS = ADMIN_IDS
OWNERS = OWNER_IDS
