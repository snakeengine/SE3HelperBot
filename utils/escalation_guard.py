# utils/escalation_guard.py
from __future__ import annotations

import os, json, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from aiogram import Bot

# ترجمة ولغة المستخدم (مع fallback آمن)
try:
    from lang import t, get_user_lang  # type: ignore
except Exception:  # fallbacks
    def t(_lang: str, key: str) -> str:  # type: ignore
        return ""
    def get_user_lang(_uid: int) -> str:  # type: ignore
        return "en"

# ===== مسارات البيانات (محايدة) =====
DATA_DIR = Path(os.getenv("ESC_GUARD_DIR", "data"))
BANS_FILE  = DATA_DIR / "escalation_bans.json"
STATE_FILE = DATA_DIR / "escalation_state.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ===== إعدادات قابلة للتهيئة عبر البيئة =====
WARN_THRESHOLD         = int(os.getenv("ESC_WARN_THRESHOLD", "3"))
ATTEMPT_WINDOW_MINUTES = int(os.getenv("ESC_ATTEMPT_WINDOW_MIN", "10"))
# سلسلة الحظر التصاعدي بالساعة (مثال: "1,6,12,24")
BAN_STEPS_HOURS = [int(x) for x in (os.getenv("ESC_BAN_STEPS", "1,6,12,24").split(",")) if x.strip().isdigit()] or [1,6,12,24]
STRIKE_DECAY_DAYS      = int(os.getenv("ESC_STRIKE_DECAY_DAYS", "7"))

# ===== قفل للكتابة الذرّية =====
_LOCK = threading.Lock()

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _iso_utc(dt: datetime) -> str:
    """UTC ISO-8601 مع Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def _from_iso(s: str) -> datetime:
    # دعم كلٍ من Z و +00:00
    s = (s or "").strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        # إن فشل التحويل، ارجع الآن (حتى لا نكسر المنطق)
        return _utcnow()

def _human_duration(seconds: int, lang: str) -> str:
    seconds = max(0, int(seconds))
    h = max(1, seconds // 3600)
    if lang == "ar":
        if h < 24:
            return f"{h} ساعة"
        d = h // 24
        return f"{d} يوم"
    if h < 24:
        return f"{h}h"
    d = h // 24
    return f"{d}d"

def _fmt_utc(iso_s: str) -> str:
    try:
        dt = _from_iso(iso_s)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso_s or "N/A"

# ===== I/O آمن =====
def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        try:
            f.flush(); os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp, path)

def _read_json(path: Path, default):
    try:
        if path.exists():
            raw = path.read_text("utf-8")
            obj = json.loads(raw or "{}")
            return obj if isinstance(obj, dict) else default
    except Exception:
        pass
    return default

def _save(path: Path, data: Dict[str, Any]) -> None:
    with _LOCK:
        try:
            _atomic_write(path, data)
        except Exception:
            try:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

# أنشئ الملفات الفارغة عند أول تشغيل
for p in (BANS_FILE, STATE_FILE):
    if not p.exists():
        _save(p, {})

# ===== عمليات مساعدة على الحالة =====
def _decay_strike(u: Dict[str, Any]) -> Dict[str, Any]:
    """
    يُخفّض مستوى التصعيد تلقائيًا عند حلول موعد الانقاص.
    ويجدّد موعد الانقاص لاحقًا.
    """
    now = _utcnow()
    strike = int(u.get("strike", 0))
    decay_at_iso = u.get("decay_at")
    if strike > 0 and decay_at_iso:
        try:
            if now >= _from_iso(decay_at_iso):
                u["strike"] = max(0, strike - 1)
                u["decay_at"] = _iso_utc(now + timedelta(days=STRIKE_DECAY_DAYS))
        except Exception:
            u["decay_at"] = _iso_utc(now + timedelta(days=STRIKE_DECAY_DAYS))
    elif strike >= 0 and not decay_at_iso:
        u["decay_at"] = _iso_utc(now + timedelta(days=STRIKE_DECAY_DAYS))
    return u

def _ensure_user_state(state: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    now = _utcnow()
    key = str(user_id)
    u = state.get(key) or {}
    # init defaults
    u.setdefault("count", 0)
    u.setdefault("window_until", _iso_utc(now + timedelta(minutes=ATTEMPT_WINDOW_MINUTES)))
    u.setdefault("warned", False)
    u.setdefault("strike", 0)
    u.setdefault("decay_at", _iso_utc(now + timedelta(days=STRIKE_DECAY_DAYS)))
    u.setdefault("last_ban_at", None)
    state[key] = u
    return u

def _reset_window(u: Dict[str, Any]) -> None:
    now = _utcnow()
    u["count"] = 0
    u["warned"] = False
    u["window_until"] = _iso_utc(now + timedelta(minutes=ATTEMPT_WINDOW_MINUTES))

# ===== واجهات عامة =====
def is_banned_now(user_id: int) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    يرجع (banned?, remaining_seconds, until_iso)
    """
    bans = _read_json(BANS_FILE, {})
    rec = bans.get(str(user_id))
    if not rec:
        return False, None, None
    try:
        until_iso = rec.get("until")
        until = _from_iso(until_iso)
        now = _utcnow()
        if now < until:
            return True, int((until - now).total_seconds()), _iso_utc(until)
    except Exception:
        pass
    return False, None, None

async def process_attempt(bot: Bot, user_id: int, lang: str | None = None, chat_id: int | None = None):
    """
    تُستدعى عندما يحاول مستخدم الدخول لميزة محجوبة.
    - عند وصول عدد المحاولات في النافذة إلى WARN_THRESHOLD ⇒ تحذير.
    - بعدها ⇒ حظر مؤقت بمدة تصاعدية: 1h → 6h → 12h → 24h (ثم يثبت على 24h).
    مفاتيح الترجمة المقترحة:
        • rate_warn   : "⚠️ Warning: you made {attempts} attempts. Continuing may lead to a temporary ban for {duration}."
        • rate_banned : "⏱️ You have been temporarily banned for {duration}. You may try again after: {until}."
    """
    lang = (lang or get_user_lang(user_id) or "en").strip().lower()
    send_to = chat_id or user_id

    # لو محظور حالياً، نبلّغه ونوقف
    banned, remaining, until_iso = is_banned_now(user_id)
    if banned:
        try:
            txt = (t(lang, "rate_banned") or
                   "⏱️ You are temporarily banned for {duration}. Try again after: {until}.") \
                  .replace("{duration}", _human_duration(remaining or 0, lang)) \
                  .replace("{until}", _fmt_utc(until_iso or ""))
            await bot.send_message(send_to, txt, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
        return

    # تحميل وتحديث الحالة
    state = _read_json(STATE_FILE, {})
    bans  = _read_json(BANS_FILE, {})
    u = _ensure_user_state(state, user_id)
    u = _decay_strike(u)

    # إعادة فتح نافذة جديدة لو انتهت
    try:
        if _utcnow() >= _from_iso(u["window_until"]):
            _reset_window(u)
    except Exception:
        _reset_window(u)

    # سجل المحاولة
    u["count"] = int(u.get("count", 0)) + 1

    # 1) تحذير عند الوصول للحد
    if u["count"] == WARN_THRESHOLD and not u.get("warned", False):
        next_idx = min(int(u.get("strike", 0)), len(BAN_STEPS_HOURS) - 1)
        next_seconds = int(BAN_STEPS_HOURS[next_idx] * 3600)
        text = (t(lang, "rate_warn") or
                "⚠️ Warning: you made {attempts} attempts. Continuing may lead to a temporary ban for {duration}.") \
                .replace("{attempts}", str(u["count"])) \
                .replace("{duration}", _human_duration(next_seconds, lang))
        try:
            await bot.send_message(send_to, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
        u["warned"] = True
        state[str(user_id)] = u
        _save(STATE_FILE, state)
        return

    # 2) بعد التحذير: حظر تصاعدي
    if u["count"] > WARN_THRESHOLD:
        idx = min(int(u.get("strike", 0)), len(BAN_STEPS_HOURS) - 1)
        seconds = int(BAN_STEPS_HOURS[idx] * 3600)
        until = _utcnow() + timedelta(seconds=seconds)

        # سجّل الحظر
        bans[str(user_id)] = {"until": _iso_utc(until)}
        _save(BANS_FILE, bans)

        # تصفير النافذة وزيادة مستوى التصعيد
        _reset_window(u)
        u["strike"] = min(int(u.get("strike", 0)) + 1, len(BAN_STEPS_HOURS) - 1)
        u["last_ban_at"] = _iso_utc(_utcnow())
        u["decay_at"] = _iso_utc(_utcnow() + timedelta(days=STRIKE_DECAY_DAYS))
        state[str(user_id)] = u
        _save(STATE_FILE, state)

        text = (t(lang, "rate_banned") or
                "⏱️ You have been temporarily banned for {duration}. You may try again after: {until}.") \
                .replace("{duration}", _human_duration(seconds, lang)) \
                .replace("{until}", _fmt_utc(_iso_utc(until)))
        try:
            await bot.send_message(send_to, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
        return

    # 3) أقل من حد التحذير → حفظ فقط
    state[str(user_id)] = u
    _save(STATE_FILE, state)

def on_manual_unban(user_id: int):
    """
    تُستدعى اختياريًا بعد إلغاء حظر يدوي.
    لا نُصفّر strike؛ فقط نحدّث decay_at ليبدأ عدّ 7 أيام من جديد.
    """
    state = _read_json(STATE_FILE, {})
    key = str(user_id)
    u = state.get(key)
    if not u:
        return
    u["decay_at"] = _iso_utc(_utcnow() + timedelta(days=STRIKE_DECAY_DAYS))
    state[key] = u
    _save(STATE_FILE, state)

# (اختياري) أدوات مساعدة للإدارة
def admin_unban(user_id: int) -> bool:
    bans = _read_json(BANS_FILE, {})
    key = str(user_id)
    if key in bans:
        bans.pop(key, None)
        _save(BANS_FILE, bans)
        on_manual_unban(user_id)
        return True
    return False

def admin_ban_for(user_id: int, seconds: int) -> str:
    bans = _read_json(BANS_FILE, {})
    until = _utcnow() + timedelta(seconds=max(60, int(seconds)))
    bans[str(user_id)] = {"until": _iso_utc(until)}
    _save(BANS_FILE, bans)
    return _iso_utc(until)

__all__ = [
    "is_banned_now",
    "process_attempt",
    "on_manual_unban",
    "admin_unban",
    "admin_ban_for",
]
