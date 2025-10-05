# utils/roles.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Dict, List, Set

DATA = Path("data")
STORE = DATA / "roles.json"

# تراتبية الأدوار (من الأقل للأعلى)
HIERARCHY = ["viewer", "support", "moderator", "admin", "superadmin", "owner"]
LEVEL = {r: i for i, r in enumerate(HIERARCHY)}
VALID_ROLES: Set[str] = set(HIERARCHY)

def _load() -> Dict[str, List[str]]:
    try:
        if STORE.exists():
            return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(obj: Dict[str, List[str]]):
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, STORE)
    except Exception:
        pass

def _normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    aliases = {"sa": "superadmin", "super": "superadmin", "sup": "support", "mod": "moderator"}
    r = aliases.get(r, r)
    return r if r in VALID_ROLES else "viewer"

def list_roles(uid: int) -> List[str]:
    db = _load()
    return [r for r in db.get(str(uid), []) if r in VALID_ROLES]

def add_role(uid: int, role: str) -> None:
    db = _load()
    roles = set(db.get(str(uid), []))
    roles.add(_normalize_role(role))
    db[str(uid)] = sorted(roles, key=lambda x: LEVEL[x])
    _save(db)

def remove_role(uid: int, role: str) -> None:
    db = _load()
    roles = set(db.get(str(uid), []))
    r = _normalize_role(role)
    if r in roles:
        roles.remove(r)
        db[str(uid)] = sorted(roles, key=lambda x: LEVEL[x])
        _save(db)

def set_roles(uid: int, roles: List[str]) -> None:
    db = _load()
    rs = {_normalize_role(r) for r in roles if r}
    db[str(uid)] = sorted(rs, key=lambda x: LEVEL[x])
    _save(db)

def _highest(uid: int) -> str | None:
    roles = list_roles(uid)
    if not roles:
        return None
    # اختر أعلى دور حسب المستوى
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

# ── Seeding: عين ADMIN_IDS كـ support/admin تلقائياً (اختياري، آمن)
def _bootstrap_seed():
    admin_ids = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids = [int(x) for x in admin_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return
    db = _load()
    changed = False
    for uid in ids:
        roles = set(db.get(str(uid), []))
        if "admin" not in roles and "superadmin" not in roles and "owner" not in roles:
            roles.add("admin")  # يمكنك تغييره إلى "support" لو حاب
            db[str(uid)] = sorted(roles, key=lambda x: LEVEL[x])
            changed = True
    if changed:
        _save(db)

_bootstrap_seed()
