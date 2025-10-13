from __future__ import annotations

import json, os, logging
from typing import Set, Dict, Any, Tuple

log = logging.getLogger("utils.admins")

DATA_DIR = os.getenv("DATA_DIR", "/data")
STORE_PATH = os.path.join(DATA_DIR, "admins.json")

# ---------- أدوات داخلية ----------
def _parse_ids_env(name: str) -> Set[int]:
    raw = os.getenv(name, "") or ""
    out: Set[int] = set()
    for p in map(str.strip, str(raw).split(",")):
        if p.isdigit():
            out.add(int(p))
    return out

def _load_store() -> Dict[str, Any]:
    try:
        if os.path.exists(STORE_PATH):
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                # طبّع القيم إلى ints
                data["owners"] = [int(x) for x in data.get("owners", [])]
                data["admins"] = [int(x) for x in data.get("admins", [])]
                return data
    except Exception as e:
        log.warning("[ADMIN] failed reading %s: %s", STORE_PATH, e)
    return {"owners": [], "admins": []}

def _save_store(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"owners": sorted(set(map(int, data.get("owners", [])))),
                 "admins": sorted(set(map(int, data.get("admins", []))))},
                f, ensure_ascii=False, indent=2
            )
    except Exception as e:
        log.warning("[ADMIN] failed writing %s: %s", STORE_PATH, e)

def _effective_sets() -> Tuple[Set[int], Set[int]]:
    """يرجع (owners, admins) الفعليين = ENV/STORE مع دمج مالكين ضمن الإدمن."""
    store = _load_store()
    env_owners = _parse_ids_env("OWNERS")
    env_admins = _parse_ids_env("ADMIN_IDS")
    owners = set(env_owners or store.get("owners", []))
    if not owners:
        # لو ما فيه مالكين محددين، اعتبر ADMIN_IDS كبديل
        owners = set(env_admins or [])
    admins = set(env_admins) | set(store.get("admins", [])) | set(owners)
    return owners, admins

# ---------- واجهة حديثة ----------
def get_owner_ids() -> Set[int]:
    owners, _ = _effective_sets()
    return owners

def get_admin_ids() -> Set[int]:
    _, admins = _effective_sets()
    return admins

def is_admin(user_id: int | str) -> bool:
    try:
        uid = int(user_id)
    except Exception:
        return False
    return uid in get_admin_ids()

def export_admins_to_store() -> None:
    """يحفظ الحالة الحالية (effective) إلى ملف /data/admins.json"""
    owners, admins = _effective_sets()
    _save_store({"owners": list(owners), "admins": list(admins)})
    log.info("[ADMIN] EXPORT OWNERS=%s ADMIN_IDS=%s", sorted(owners), sorted(admins))

# ---------- واجهة توافقية قديمة (مطابقة للأسماء المستوردة في المشروع) ----------
def list_admins() -> Dict[str, list]:
    owners, admins = _effective_sets()
    return {
        "owners": sorted(owners),
        "admins": sorted(admins),
    }

def add_admin(user_id: int | str) -> Dict[str, list]:
    """يضيف إدمن إلى المخزن الدائم (لا يزيل مالك/إدمن من ENV)."""
    try:
        uid = int(user_id)
    except Exception:
        raise ValueError("invalid user id")
    data = _load_store()
    admins = set(map(int, data.get("admins", [])))
    admins.add(uid)
    data["admins"] = sorted(admins)
    # لا نعبث بالمالكين هنا
    _save_store(data)
    return list_admins()

def remove_admin(user_id: int | str) -> Dict[str, list]:
    """يزيل الإدمن فقط من المخزن الدائم (لا يمكن إزالة مالك لو جاي من ENV/owners)."""
    try:
        uid = int(user_id)
    except Exception:
        raise ValueError("invalid user id")
    data = _load_store()
    admins = set(map(int, data.get("admins", [])))
    admins.discard(uid)
    data["admins"] = sorted(admins)
    _save_store(data)
    return list_admins()

# متغيّرات توافقية مع الكود القديم
def _refresh_globals() -> None:
    global OWNERS, ADMIN_IDS
    OWNERS = get_owner_ids()
    ADMIN_IDS = get_admin_ids()

_refresh_globals()  # عند الاستيراد

# مخرجات لوج مريحة عند بداية التشغيل (اختياري أن تستدعى من main)
def log_current_admins() -> None:
    log.info("[ADMIN] OWNERS=%s | ADMIN_IDS=%s | store=%s",
             sorted(get_owner_ids()), sorted(get_admin_ids()), STORE_PATH)
