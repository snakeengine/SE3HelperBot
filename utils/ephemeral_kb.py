# utils/ephemeral_kb.py
from __future__ import annotations

import json, time, os, threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

# ===== إعدادات ومسار التخزين =====
# يمكنك override عبر EPHEMERAL_KB_PATH (مثال: /data/ephemeral_kb.json)
_EP_PATH = (os.getenv("EPHEMERAL_KB_PATH") or "data/ephemeral_kb.json").strip()
_STORE = Path(_EP_PATH)
_STORE.parent.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()

def _now() -> int:
    return int(time.time())

# ===== I/O آمِن وذرّي =====
def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + f".{int(time.time()*1000)}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            # بعض بيئات الحاويات لا تدعم fsync — تجاهل بأمان
            pass
    os.replace(tmp, path)

def _read_json_safe(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            raw = path.read_text("utf-8")
            obj = json.loads(raw or "{}")
            if isinstance(obj, dict):
                return obj
    except Exception:
        # في حال تلف الملف نعيد خريطة افتراضية
        pass
    return {"users": {}}

def _gc(d: Dict[str, Any]) -> Dict[str, Any]:
    """تنظيف السجلات المنتهية قبل الإرجاع/الحفظ."""
    users = d.get("users") or {}
    now = _now()
    kept: Dict[str, Any] = {}
    for k, rec in users.items():
        try:
            exp = int(rec.get("expires_at", 0) or 0)
        except Exception:
            exp = 0
        if exp and now > exp:
            continue
        kept[k] = rec
    d["users"] = kept
    return d

def _load() -> Dict[str, Any]:
    with _LOCK:
        d = _read_json_safe(_STORE)
        if "users" not in d or not isinstance(d["users"], dict):
            d["users"] = {}
        # نظّف المنتهي أثناء التحميل
        d = _gc(d)
        return d

def _save(d: Dict[str, Any]) -> None:
    with _LOCK:
        # تنظيف قبل الحفظ لتقليل الحجم
        d = _gc(d)
        try:
            _atomic_write_json(_STORE, d)
        except Exception:
            # لا نرفع استثناءً حتى لا يعطّل مسار البوت
            try:
                _STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

# -------- API --------

def open_panel(
    uid: int,
    *,
    owner: str,
    ttl_sec: int = 600,
    allow_prefixes: Iterable[str] = (),
    allow_texts: Iterable[str] = (),
    close_on_any_message: bool = False,
    close_on_unmatched_callback: bool = True,
    allow_any_callbacks: bool = False,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    افتح/حدّث جلسة لوحة مؤقتة لِمستخدم.
    - owner: اسم المالك، مثال "qs"
    - ttl_sec: مدة الصلاحية
    - allow_prefixes: بادئات الكولباكات المسموح بها
    - allow_texts: نصوص رسائل (ReplyKeyboard) المسموح بها
    - close_on_any_message: اغلق عند أي رسالة لا تطابق allow_texts
    - close_on_unmatched_callback: اغلق عند كولباك خارج allow_prefixes
    - allow_any_callbacks: اسمح بكل الكولباكات (لن تُغلق بسبب الكولباكات)
    """
    d = _load()
    now = _now()
    rec = {
        "owner": str(owner),
        "opened_at": now,
        "last_touch": now,
        "expires_at": now + max(1, int(ttl_sec)),
        "allow_prefixes": list(allow_prefixes or []),
        "allow_texts": list(allow_texts or []),
        "close_on_any_message": bool(close_on_any_message),
        "close_on_unmatched_callback": bool(close_on_unmatched_callback),
        "allow_any_callbacks": bool(allow_any_callbacks),
        "meta": dict(meta or {}),
    }
    d.setdefault("users", {})[str(uid)] = rec
    _save(d)
    return rec

def get(uid: int) -> Optional[Dict[str, Any]]:
    """
    أرجع السجل كما هو (حتى لو منتهي) مع حقل خاص _expired لتسهيل قرار الإغلاق.
    """
    d = _load()
    rec = d.get("users", {}).get(str(uid))
    if not rec:
        return None
    # نسخة آمنة مع إشارة انتهاء
    out = dict(rec)
    try:
        exp = int(out.get("expires_at", 0) or 0)
    except Exception:
        exp = 0
    out["_expired"] = bool(exp and _now() > exp)
    return out

def is_active(uid: int, owner: str | None = None) -> bool:
    rec = get(uid)
    if not rec or rec.get("_expired"):
        return False
    return (owner is None) or (str(rec.get("owner")) == str(owner))

def touch(uid: int, *, extend_sec: int | None = None) -> None:
    d = _load()
    rec = d.get("users", {}).get(str(uid))
    if not rec:
        return
    now = _now()
    rec["last_touch"] = now
    if isinstance(extend_sec, int) and extend_sec > 0:
        try:
            exp = int(rec.get("expires_at", 0) or 0)
        except Exception:
            exp = 0
        rec["expires_at"] = max(exp, now) + int(extend_sec)
    d["users"][str(uid)] = rec
    _save(d)

def close_panel(uid: int) -> None:
    d = _load()
    d.get("users", {}).pop(str(uid), None)
    _save(d)

# -------- قرارات الإغلاق للميدلوير --------

def should_close_on_message(uid: int, text: str) -> bool:
    """
    أغلق عند:
      - انتهاء الصلاحية
      - رسالة أمر تبدأ بـ '/' (ينتقل لقسم آخر)
      - لو close_on_any_message=True ولم تكن الرسالة ضمن allow_texts
    """
    rec = get(uid)
    if not rec:
        return False
    if rec.get("_expired"):
        return True
    t = (text or "").strip()
    if t.startswith("/"):
        return True
    if rec.get("close_on_any_message", False):
        allowed = set(rec.get("allow_texts") or [])
        return t not in allowed
    return False

def _allowed_by_prefixes(rec: Dict[str, Any], data: str) -> bool:
    data = str(data or "")
    for p in (rec.get("allow_prefixes") or []):
        try:
            if data.startswith(str(p)):
                return True
        except Exception:
            continue
    return False

def should_close_on_callback(uid: int, data: str) -> bool:
    """
    أغلق عند:
      - انتهاء الصلاحية
      - كولباك لا يطابق أي بادئة مسموحة (إلا إذا allow_any_callbacks=True)
    """
    rec = get(uid)
    if not rec:
        return False
    if rec.get("_expired"):
        return True
    if rec.get("allow_any_callbacks", False):
        return False
    return not _allowed_by_prefixes(rec, data)

# اختياري: دالة مساعدة لو حبيت تفحص السماح سريعًا
def is_allowed_cb(uid: int, data: str) -> bool:
    rec = get(uid)
    if not rec or rec.get("_expired"):
        return False
    if rec.get("allow_any_callbacks", False):
        return True
    return _allowed_by_prefixes(rec, data)

def cleanup_all() -> None:
    d = _load()
    users = list((d.get("users") or {}).keys())
    changed = False
    now = _now()
    for k in users:
        rec = (d.get("users") or {}).get(k) or {}
        try:
            exp = int(rec.get("expires_at", 0) or 0)
        except Exception:
            exp = 0
        if exp and now > exp:
            (d.get("users") or {}).pop(k, None)
            changed = True
    if changed:
        _save(d)

__all__ = [
    "open_panel", "get", "is_active", "touch", "close_panel",
    "should_close_on_message", "should_close_on_callback",
    "is_allowed_cb", "cleanup_all",
]
