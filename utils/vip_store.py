# utils/vip_store.py
from __future__ import annotations

import json, os, tempfile, time
from typing import Dict, Any, Optional, List

# ================= paths =================
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
VIP_FILE = os.path.join(DATA_DIR, "vip_users.json")
PENDING_FILE = os.path.join(DATA_DIR, "vip_pending.json")
BLOCK_FILE = os.path.join(DATA_DIR, "vip_blocklist.json")

# ================= IO helpers =================
def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def _safe_read(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _safe_write(path: str, obj: Any):
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(prefix="vip_", suffix=".json", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

# ================= time helpers =================
def _now_ts() -> int:
    return int(time.time())

def _days_to_sec(days: int) -> int:
    return max(0, int(days)) * 86400

# ================= normalization =================
def normalize_app_id(app_id: str) -> str:
    return (app_id or "").strip().lower()

# ================= raw VIP store =================
def _load_vip_raw() -> Dict[str, Any]:
    return _safe_read(VIP_FILE) or {"users": {}}

def _save_vip_raw(d: Dict[str, Any]):
    d.setdefault("users", {})
    _safe_write(VIP_FILE, d)

# ================= notify flags helpers =================
def _default_notify_flags() -> Dict[str, bool]:
    # d1: 1 day, h12: 12 hours, h6: 6 hours, h1: 1 hour
    return {"d1": False, "h12": False, "h6": False, "h1": False}

def _reset_notify_flags(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta["notified"] = _default_notify_flags()
    return meta

def get_notify_flags(user_id: int) -> Dict[str, bool]:
    data = _load_vip_raw()
    meta = (data.get("users") or {}).get(str(user_id)) or {}
    nf = meta.get("notified") or {}
    # ensure keys exist
    for k in ("d1", "h12", "h6", "h1"):
        nf.setdefault(k, False)
    return nf

def set_notify_flag(user_id: int, key: str) -> bool:
    if key not in ("d1", "h12", "h6", "h1"):
        return False
    data = _load_vip_raw()
    users = data.get("users") or {}
    meta = users.get(str(user_id))
    if not meta:
        return False
    nf = meta.get("notified") or {}
    nf[key] = True
    meta["notified"] = nf
    users[str(user_id)] = meta
    data["users"] = users
    _save_vip_raw(data)
    return True

# ================= public helpers =================
def list_vips() -> Dict[str, Any]:
    """يعيد كامل قاعدة VIP (للاطلاع/العرض)."""
    return _load_vip_raw()

def get_vip_meta(user_id: int) -> Optional[Dict[str, Any]]:
    """معلومات مشترك واحدة (قد تتضمن expiry_ts)."""
    data = _load_vip_raw()
    return (data.get("users") or {}).get(str(user_id))

def is_vip(user_id: int) -> bool:
    """
    يعتبر المستخدم VIP إذا كان موجودًا ولم ينتهِ الاشتراك.
    - لو لا يوجد expiry_ts => اشتراك غير منتهٍ (دائم) => True.
    - لو يوجد expiry_ts => يجب أن يكون > الآن.
    """
    meta = get_vip_meta(user_id)
    if not meta:
        return False
    exp = meta.get("expiry_ts")
    if exp is None:
        return True
    try:
        return int(exp) > _now_ts()
    except Exception:
        return False

def set_vip_expiry(user_id: int, expiry_ts: int) -> bool:
    """ضبط تاريخ الانتهاء مباشرة (ثواني Unix) + إعادة تهيئة أعلام التذكير."""
    data = _load_vip_raw()
    users = data.get("users") or {}
    meta = users.get(str(user_id))
    if not meta:
        return False
    meta["expiry_ts"] = int(expiry_ts)
    _reset_notify_flags(meta)
    users[str(user_id)] = meta
    data["users"] = users
    _save_vip_raw(data)
    return True

# ============= إضافة/تمديد بالثواني (حقيقي) =============
def add_vip_seconds(user_id: int, app_id: str, *, seconds: int, added_by: Optional[int] = None) -> None:
    """
    إضافة/تحديث اشتراك بمدة حقيقية بالثواني.
    إن كان لديه انتهاء مستقبلي، نراكم من الانتهاء؛ وإلا من الآن.
    يعاد ضبط أعلام التذكير.
    """
    data = _load_vip_raw()
    users = data.setdefault("users", {})
    now = _now_ts()

    old = users.get(str(user_id)) or {}
    base = int(old.get("expiry_ts") or 0)
    start_from = base if base > now else now
    expiry_ts = start_from + max(1, int(seconds))

    meta = dict(old)
    meta.update({
        "app_id": normalize_app_id(app_id),
        "added_by": added_by,
        "ts": now,
        "expiry_ts": expiry_ts,
    })
    _reset_notify_flags(meta)

    users[str(user_id)] = meta
    _save_vip_raw(data)

def extend_vip_seconds(user_id: int, seconds: int) -> bool:
    """تمديد الاشتراك بعدد ثوانٍ (يتراكم من الانتهاء أو الآن) + إعادة تهيئة أعلام التذكير."""
    data = _load_vip_raw()
    users = data.get("users") or {}
    meta = users.get(str(user_id))
    if not meta:
        return False
    now = _now_ts()
    base = int(meta.get("expiry_ts") or 0)
    start_from = base if base > now else now
    meta["expiry_ts"] = start_from + max(1, int(seconds))
    _reset_notify_flags(meta)
    users[str(user_id)] = meta
    _save_vip_raw(data)
    return True

# ============= واجهات قديمة (أيام) للإبقاء على التوافق =============
def add_vip(user_id: int, app_id: str, added_by: Optional[int] = None, days: int | None = None):
    """
    إضافة/تحديث VIP. لو days=None لن يُضبط expiry_ts (اشتراك دائم).
    عند تحديد days، تُحول إلى ثواني وتُسند لـ add_vip_seconds.
    """
    if days is None:
        data = _load_vip_raw()
        meta = {
            "app_id": normalize_app_id(app_id),
            "added_by": added_by,
            "ts": _now_ts(),
            # اشتراك دائم: لا expiry_ts => ولا حاجة لأعلام التذكير
        }
        data["users"][str(user_id)] = meta
        _save_vip_raw(data)
        return
    add_vip_seconds(user_id, app_id, seconds=_days_to_sec(days), added_by=added_by)

def extend_vip_days(user_id: int, days: int) -> bool:
    return extend_vip_seconds(user_id, _days_to_sec(days))

# ============= إزالة/بحث =============
def remove_vip(user_id: int):
    data = _load_vip_raw()
    (data.get("users") or {}).pop(str(user_id), None)
    _save_vip_raw(data)

def find_uid_by_app(app_id: str) -> Optional[int]:
    app = normalize_app_id(app_id)
    data = _load_vip_raw()
    for uid, meta in (data.get("users") or {}).items():
        if normalize_app_id((meta or {}).get("app_id", "")) == app:
            try:
                return int(uid)
            except Exception:
                return None
    return None

def remove_vip_by_app(app_id: str) -> bool:
    app = normalize_app_id(app_id)
    data = _load_vip_raw()
    users = data.get("users") or {}
    for uid, meta in list(users.items()):
        if normalize_app_id((meta or {}).get("app_id", "")) == app:
            users.pop(uid, None)
            data["users"] = users
            _save_vip_raw(data)
            return True
    return False

def search_vips_by_app_prefix(prefix: str) -> Dict[int, str]:
    out: Dict[int, str] = {}
    pref = normalize_app_id(prefix)
    if not pref:
        return out
    data = _load_vip_raw()
    for uid, meta in (data.get("users") or {}).items():
        app = normalize_app_id((meta or {}).get("app_id", ""))
        if app.startswith(pref):
            try:
                out[int(uid)] = app
            except Exception:
                pass
    return out

# ============= Pending requests =============
def add_pending(user_id: int, app_id: str, ticket_id: str | None = None):
    data = _safe_read(PENDING_FILE) or {"items": {}}
    data.setdefault("items", {})
    data["items"][str(user_id)] = {
        "app_id": app_id,
        "ts": _now_ts(),
    }
    if ticket_id:
        data["items"][str(user_id)]["ticket_id"] = ticket_id
    _safe_write(PENDING_FILE, data)

def pop_pending(user_id: int) -> Optional[Dict[str, Any]]:
    data = _safe_read(PENDING_FILE) or {"items": {}}
    it = (data.get("items") or {}).pop(str(user_id), None)
    _safe_write(PENDING_FILE, data)
    return it

def get_pending(user_id: int) -> Optional[Dict[str, Any]]:
    data = _safe_read(PENDING_FILE) or {"items": {}}
    return (data.get("items") or {}).get(str(user_id))

# ============= Blocklist & bulk ops =============
def _read_block() -> dict:
    return _safe_read(BLOCK_FILE) or {"blocked": {}}

def _write_block(d: dict):
    _safe_write(BLOCK_FILE, d)

def add_block(user_id: int, reason: str | None = None):
    d = _read_block()
    d.setdefault("blocked", {})
    d["blocked"][str(user_id)] = {"reason": reason or "", "ts": int(time.time())}
    _write_block(d)
    # إزالة من VIP إن وُجد
    try:
        data = _safe_read(VIP_FILE) or {"users": {}}
        (data.get("users") or {}).pop(str(user_id), None)
        _safe_write(VIP_FILE, data)
    except Exception:
        pass

def is_blocked(user_id: int) -> bool:
    d = _read_block()
    return str(user_id) in (d.get("blocked") or {})

def remove_block(user_id: int):
    d = _read_block()
    (d.get("blocked") or {}).pop(str(user_id), None)
    _write_block(d)

def list_blocked() -> dict:
    return _read_block()

def remove_all_vips() -> int:
    data = _safe_read(VIP_FILE) or {"users": {}}
    cnt = len(data.get("users") or {})
    data["users"] = {}
    _safe_write(VIP_FILE, data)
    return cnt

# ============= Expiration maintenance =============
def purge_expired() -> List[int]:
    """
    يحذف كل المشتركين الذين انتهت صلاحيتهم الآن أو قبل الآن.
    يعيد قائمة الـ UIDs التي تم حذفها (لاستخدامها في الإشعارات).
    """
    data = _load_vip_raw()
    users = data.get("users") or {}
    now = _now_ts()
    expired: List[int] = []
    changed = False

    for uid, meta in list(users.items()):
        exp = (meta or {}).get("expiry_ts")
        if exp is not None:
            try:
                if int(exp) <= now:
                    expired.append(int(uid))
                    users.pop(uid, None)
                    changed = True
            except Exception:
                try:
                    expired.append(int(uid))
                except Exception:
                    pass
                users.pop(uid, None)
                changed = True

    if changed:
        data["users"] = users
        _save_vip_raw(data)

    return expired
