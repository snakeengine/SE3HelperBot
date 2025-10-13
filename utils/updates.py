from __future__ import annotations

# 📁 utils/updates.py


import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Iterable
from pathlib import Path
import threading

# ===== ملف الحالة (يدعم override عبر env) =====
_ENV_PATH = (os.getenv("APP_UPDATE_FILE") or "").strip()
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "update.json"
UPDATE_PATH: Path = (Path(_ENV_PATH).expanduser().resolve() if _ENV_PATH else _DEFAULT_PATH)
UPDATE_PATH.parent.mkdir(parents=True, exist_ok=True)

ALLOWED_LANGS = ("en", "ar")
DEFAULT_LANG = "en"

# قفل آمن للقراءة/الكتابة داخل العملية (thread-safe)
_LOCK = threading.RLock()

# ============ I/O ============

def _safe_load(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _safe_save(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

# ============ Core state helpers ============

def _coerce_user_ids(xs: Iterable[Any]) -> list[int]:
    out: list[int] = []
    for x in xs or []:
        try:
            v = int(x)
            if v not in out:
                out.append(v)
        except Exception:
            continue
    return out

def _empty_state() -> dict:
    return {
        "active": False,
        "message": {"en": "", "ar": ""},
        "notified_users": [],
        "active_until": None,   # ISO8601 string or None
        "duration_days": None   # int days or None
    }

def load_update_info() -> dict:
    with _LOCK:
        data = _safe_load(UPDATE_PATH, None)
        if not data:
            data = _empty_state()
            _safe_save(UPDATE_PATH, data)

        msgs = data.get("message") or {}
        data["message"] = {
            "en": str(msgs.get("en") or ""),
            "ar": str(msgs.get("ar") or ""),
        }
        data["notified_users"] = _coerce_user_ids(data.get("notified_users") or [])
        data["active_until"]   = data.get("active_until", None)
        data["duration_days"]  = data.get("duration_days", None)
        data["active"]         = bool(data.get("active", False))
        return data

def save_update_info(data: dict):
    with _LOCK:
        data["notified_users"] = _coerce_user_ids(data.get("notified_users") or [])
        msgs = data.get("message") or {}
        data["message"] = {"en": str(msgs.get("en") or ""), "ar": str(msgs.get("ar") or "")}
        _safe_save(UPDATE_PATH, data)

# ============ Duration parsing ============

def _set_active_until_by_days(data: dict, days: Optional[int]):
    if days is None:
        data["duration_days"] = None
        data["active_until"] = None
    else:
        d = max(int(days), 0)
        data["duration_days"] = d
        data["active_until"] = (_now_utc() + timedelta(days=d)).isoformat()

def parse_duration_to_days(s: Optional[str]) -> Optional[int]:
    """
    '7d' → 7   |  '48h' → 2  |  '90m' → 0 (أقل من يوم)
    'none'/None → None       |  رقم خام = أيام
    """
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in ("none", "off", "no", "0", ""):
        return None
    try:
        if s.endswith("d"):
            return max(int(s[:-1]), 0)
        if s.endswith("h"):
            return max(int(s[:-1]), 0) // 24
        if s.endswith("m"):
            return max(int(s[:-1]), 0) // (24 * 60)
        return max(int(s), 0)
    except Exception:
        return None

# ============ High-level API ============

def set_messages(en: str = "", ar: str = ""):
    data = load_update_info()
    data["message"] = {"en": en or "", "ar": ar or ""}
    data["notified_users"] = []  # إعادة الإرسال للجميع عند تغيير النص
    save_update_info(data)

def set_message_for(lang: str, text: str):
    """تحديث رسالة لغة واحدة فقط + تفريغ إشعارات المستخدمين."""
    lang = (lang or DEFAULT_LANG).lower()
    if lang not in ALLOWED_LANGS:
        return
    data = load_update_info()
    msgs = data.get("message", {})
    msgs[lang] = text or ""
    data["message"] = msgs
    data["notified_users"] = []
    save_update_info(data)

def set_active(active: bool):
    data = load_update_info()
    data["active"] = bool(active)
    if not active:
        data["duration_days"] = None
        data["active_until"] = None
    save_update_info(data)

def set_duration_days(days: Optional[int]):
    """يضبط مدة الإعلان بالأيام ويحسب active_until. None = بلا انتهاء."""
    data = load_update_info()
    _set_active_until_by_days(data, days)
    save_update_info(data)

def set_duration_str(s: Optional[str]):
    """نفس set_duration_days لكن يقبل '7d'/'48h'/'90m'/'none'."""
    set_duration_days(parse_duration_to_days(s))

def set_active_until(dt: Optional[datetime]):
    data = load_update_info()
    if dt is None:
        data["active_until"] = None
        data["duration_days"] = None
    else:
        dt_utc = dt.astimezone(timezone.utc)
        data["active_until"] = dt_utc.isoformat()
        delta = dt_utc - _now_utc()
        data["duration_days"] = max(delta.days, 0)
    save_update_info(data)

def reset_updates():
    """إيقاف الإعلان ومسح الإشعارات والنصوص."""
    save_update_info(_empty_state())

# ----- إشعارات المستخدمين -----

def was_user_notified(user_id: int) -> bool:
    data = load_update_info()
    notified = set(int(x) for x in (data.get("notified_users") or []))
    return int(user_id) in notified

def mark_user_notified(user_id: int):
    data = load_update_info()
    s = set(int(x) for x in (data.get("notified_users") or []))
    s.add(int(user_id))
    data["notified_users"] = list(s)
    save_update_info(data)

def should_notify_user(user_id: int) -> bool:
    """مساعد: يُفيد قبل الإرسال—True إذا لم يُخطَر من قبل."""
    return not was_user_notified(user_id)

def clear_notified():
    data = load_update_info()
    data["notified_users"] = []
    save_update_info(data)

# ----- قراءة النص -----

def get_update_text(lang_code: str) -> str:
    data = load_update_info()
    msgs = data.get("message", {}) or {}
    lang = (lang_code or DEFAULT_LANG).lower()
    if lang not in ALLOWED_LANGS:
        lang = DEFAULT_LANG
    txt = (msgs.get(lang) or msgs.get(DEFAULT_LANG) or "").strip()
    return txt

# ----- حالة التفعيل والوقت المتبقي -----

def remaining_time_str() -> str:
    """
    نص مبسّط عن الوقت المتبقي حتى انتهاء الإعلان (مثال: 2d 5h)،
    أو '—' إن لم يُحدَّد أو انتهى.
    """
    data = load_update_info()
    au = data.get("active_until")
    if not au:
        return "—"
    try:
        until = datetime.fromisoformat(au.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return "—"
    delta = until - _now_utc()
    if delta.total_seconds() <= 0:
        return "—"
    days = delta.days
    hours = delta.seconds // 3600
    mins = (delta.seconds % 3600) // 60
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if mins and not days: parts.append(f"{mins}m")
    return " ".join(parts) or "≤1m"

def is_active() -> bool:
    """
    نشط إذا active=True ولم ينتهِ active_until (إن كان محددًا).
    ينطفئ تلقائيًا عند انتهاء الوقت.
    """
    data = load_update_info()
    if not data.get("active"):
        return False
    au = data.get("active_until")
    if not au:
        return True
    try:
        until = datetime.fromisoformat(au.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return True  # اعتبره نشطًا إذا صيغة التاريخ غير صالحة
    if _now_utc() >= until:
        data["active"] = False
        save_update_info(data)
        return False
    return True

# ----- ملخص إداري (اختياري) -----

def get_state() -> Dict[str, Any]:
    """حالة خام للاستخدام الإداري/الاختبارات."""
    data = load_update_info()
    return {
        "active": bool(data.get("active", False)),
        "active_until": data.get("active_until"),
        "duration_days": data.get("duration_days"),
        "notified_count": len(data.get("notified_users") or []),
        "messages": data.get("message") or {},
    }

def get_admin_summary(lang: str = "en") -> str:
    """
    نص HTML مُترجَم لعرض الحالة داخل لوحة أدمن.
    """
    try:
        from lang import t as _t  # تأجيل الاستيراد
    except Exception:
        def _t(_l, k): return k

    st = get_state()
    msgs = st["messages"]
    remaining = remaining_time_str()
    status_txt = _t(lang, "update_admin_active") if st["active"] else _t(lang, "update_admin_inactive")
    msg_en = (msgs.get("en") or _t(lang, "update_admin_not_set")).strip()
    msg_ar = (msgs.get("ar") or _t(lang, "update_admin_not_set")).strip()

    return (
        f"<b>{_t(lang, 'update_admin_title')}</b>\n\n"
        f"• {_t(lang, 'update_admin_status')}: {status_txt}\n"
        f"• {_t(lang, 'update_admin_remaining')}: <code>{remaining}</code>\n"
        f"• {_t(lang, 'update_admin_notified_count')}: <code>{st['notified_count']}</code>\n\n"
        f"<b>{_t(lang, 'update_admin_message')}</b>\n"
        f"EN: <i>{msg_en}</i>\n"
        f"AR: <i>{msg_ar}</i>"
    )

# ===== واجهات راحة إضافية لا تكسر التوافق =====

def activate(*, en: str = "", ar: str = "", duration_days: Optional[int] = None):
    """تفعيل سريع مع ضبط النص والمدة (إن وُجدت)."""
    data = load_update_info()
    data["active"] = True
    data["message"] = {"en": en or data["message"].get("en", ""), "ar": ar or data["message"].get("ar", "")}
    data["notified_users"] = []
    _set_active_until_by_days(data, duration_days)
    save_update_info(data)

def deactivate():
    """إيقاف سريع (يعادل set_active(False))"""
    set_active(False)
