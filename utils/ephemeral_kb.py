# utils/ephemeral_kb.py
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

_STORE = Path("data/ephemeral_kb.json")
_STORE.parent.mkdir(parents=True, exist_ok=True)

def _now() -> int: return int(time.time())

def _load() -> Dict[str, Any]:
    try:
        if _STORE.exists():
            return json.loads(_STORE.read_text("utf-8")) or {"users": {}}
    except Exception:
        pass
    return {"users": {}}

def _save(d: Dict[str, Any]) -> None:
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
    rec = {
        "owner": str(owner),
        "opened_at": _now(),
        "last_touch": _now(),
        "expires_at": _now() + max(1, int(ttl_sec)),
        "allow_prefixes": list(allow_prefixes or []),
        "allow_texts": list(allow_texts or []),
        "close_on_any_message": bool(close_on_any_message),
        "close_on_unmatched_callback": bool(close_on_unmatched_callback),
        "allow_any_callbacks": bool(allow_any_callbacks),
        "meta": meta or {},
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
    rec = dict(rec)  # نسخة
    exp = int(rec.get("expires_at", 0) or 0)
    rec["_expired"] = bool(exp and _now() > exp)
    return rec

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
    rec["last_touch"] = _now()
    if isinstance(extend_sec, int) and extend_sec > 0:
        rec["expires_at"] = max(int(rec.get("expires_at", 0) or 0), _now()) + extend_sec
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
    text = (text or "").strip()
    if text.startswith("/"):
        return True
    if rec.get("close_on_any_message", False):
        allowed = set(rec.get("allow_texts") or [])
        return text not in allowed
    return False

def _allowed_by_prefixes(rec: Dict[str, Any], data: str) -> bool:
    for p in (rec.get("allow_prefixes") or []):
        try:
            if data.startswith(str(p)):
                return True
        except Exception:
            pass
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
        rec = d.get("users", {}).get(k) or {}
        if int(rec.get("expires_at", 0) or 0) and now > int(rec["expires_at"]):
            d["users"].pop(k, None)
            changed = True
    if changed:
        _save(d)

__all__ = [
    "open_panel", "get", "is_active", "touch", "close_panel",
    "should_close_on_message", "should_close_on_callback",
    "is_allowed_cb", "cleanup_all",
]
