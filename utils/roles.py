from __future__ import annotations

# utils/roles.py

import os, json
from pathlib import Path
from typing import Dict, List, Set

# استخدم مخزن البيانات الموحّد
try:
    from utils.paths import BASE
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "data")).resolve()
    BASE.mkdir(parents=True, exist_ok=True)

STORE: Path = BASE / "roles.json"

# تراتبية الأدوار (من الأقل للأعلى)
HIERARCHY: List[str] = ["viewer", "support", "moderator", "admin", "superadmin", "owner"]
LEVEL: Dict[str, int] = {r: i for i, r in enumerate(HIERARCHY)}
VALID_ROLES: Set[str] = set(HIERARCHY)

ALIASES: Dict[str, str] = {
    "sa": "superadmin",
    "super": "superadmin",
    "sup": "support",
    "mod": "moderator",
    "adm": "admin",
    "owner": "owner",
    "root": "owner",
}

# ---------- IO helpers ----------

def _normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    r = ALIASES.get(r, r)
    return r if r in VALID_ROLES else "viewer"

def _load() -> Dict[str, List[str]]:
    try:
        if STORE.exists():
            data = json.loads(STORE.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                # تنظيف القيم إلى أدوار صحيحة ومرتّبة
                clean: Dict[str, List[str]] = {}
                for k, v in data.items():
                    roles = {_normalize_role(x) for x in (v or []) if isinstance(x, str)}
                    clean[str(int(k)) if str(k).lstrip("-").isdigit() else str(k)] = \
                        sorted(roles, key=lambda x: LEVEL[x])
                return clean
    except Exception:
        pass
    return {}

def _save(obj: Dict[str, List[str]]) -> None:
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, STORE)
    except Exception:
        # لا نكسر التنفيذ إذا فشلت الكتابة
        pass

# ---------- Public API ----------

def list_roles(uid: int) -> List[str]:
    db = _load()
    return [r for r in db.get(str(int(uid)), []) if r in VALID_ROLES]

def add_role(uid: int, role: str) -> None:
    db = _load()
    key = str(int(uid))
    roles = set(db.get(key, []))
    roles.add(_normalize_role(role))
    db[key] = sorted(roles, key=lambda x: LEVEL[x])
    _save(db)

def remove_role(uid: int, role: str) -> None:
    db = _load()
    key = str(int(uid))
    roles = set(db.get(key, []))
    r = _normalize_role(role)
    if r in roles:
        roles.remove(r)
        db[key] = sorted(roles, key=lambda x: LEVEL[x])
        _save(db)

def set_roles(uid: int, roles: List[str]) -> None:
    db = _load()
    key = str(int(uid))
    rs = {_normalize_role(r) for r in (roles or []) if r}
    db[key] = sorted(rs, key=lambda x: LEVEL[x])
    _save(db)

def _highest(uid: int) -> str | None:
    roles = list_roles(uid)
    if not roles:
        return None
    return sorted(roles, key=lambda x: LEVEL[x])[-1]

def has_role(uid: int, role: str) -> bool:
    return _normalize_role(role) in set(list_roles(uid))

def has_role_at_least(uid: int, role: str) -> bool:
    """هل يمتلك المستخدم هذا الدور أو أعلى؟"""
    want = _normalize_role(role)
    top = _highest(uid)
    if not top:
        return False
    return LEVEL[top] >= LEVEL[want]

# ---------- Optional bootstrap from env ----------
def _bootstrap_seed() -> None:
    """
    يعين ADMIN_IDS/ADMIN_ID كـ 'admin' تلقائيًا إن لم يكن لديهم دور.
    لا يغيّر من لديهم superadmin/owner.
    """
    env_val = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids = [int(x) for x in str(env_val).replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()]
    if not ids:
        return
    db = _load()
    changed = False
    for uid in ids:
        key = str(uid)
        roles = set(db.get(key, []))
        if not roles.intersection({"admin", "superadmin", "owner"}):
            roles.add("admin")
            db[key] = sorted(roles, key=lambda x: LEVEL[x])
            changed = True
    if changed:
        _save(db)

_bootstrap_seed()
