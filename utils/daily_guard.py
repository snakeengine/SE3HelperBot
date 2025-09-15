# utils/daily_guard.py
from __future__ import annotations

import os
import time
from typing import Tuple

from lang import t, get_user_lang
from utils.rewards_store import ensure_user, add_points

# إعدادات قابلة للضبط من البيئة
DEFAULT_DAILY_REWARD = int(os.getenv("DAILY_REWARD", "10"))
DEFAULT_INTERVAL_HOURS = int(os.getenv("DAILY_INTERVAL_HOURS", "24"))

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tt(lang: str, key: str, fb: str) -> str:
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fb

def _fmt_remaining(sec: int, lang: str) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def can_claim_daily(uid: int, interval_hours: int = DEFAULT_INTERVAL_HOURS) -> Tuple[bool, int]:
    """يرجع (مسموح؟, الثواني المتبقية)."""
    u = ensure_user(uid)
    last = int(u.get("last_claim") or 0)
    now = int(time.time())
    gap = now - last
    need = int(interval_hours * 3600)
    if last == 0 or gap >= need:
        return True, 0
    return False, need - gap

def try_claim_daily(
    uid: int,
    amount: int | None = None,
    interval_hours: int | None = None
) -> Tuple[bool, str]:
    """
    يحاول إضافة مكافأة يومية مع مهلة 24 ساعة حقيقية (قابلة للتعديل).
    يرجع (success, message).
    """
    amount = int(amount or DEFAULT_DAILY_REWARD)
    interval_hours = int(interval_hours or DEFAULT_INTERVAL_HOURS)

    ok, remaining = can_claim_daily(uid, interval_hours=interval_hours)
    lang = _L(uid)

    if not ok:
        msg = _tt(
            lang, "rewards.daily.wait",
            "لقد أخذت نقاط اليوم بالفعل. المتبقي: {time}"
        ).format(time=_fmt_remaining(remaining, lang))
        return False, msg

    # أضف النقاط وسجّل العملية
    add_points(uid, amount, typ="daily", reason="daily")
    # ثبّت التوقيت الأخير — (حتى لو كانت add_points لا تحدّثه)
    try:
        ensure_user(uid)["last_claim"] = int(time.time())
    except Exception:
        pass

    msg = _tt(
        lang, "rewards.daily.ok",
        "أُضيفت {amount} نقطة ✅"
    ).format(amount=amount)
    return True, msg

# للتوافق مع كود قديم كان يستدعي daily_claim ويرجع (ok, awarded)
def daily_claim(uid: int, amount: int | None = None) -> Tuple[bool, int]:
    amount = int(amount or DEFAULT_DAILY_REWARD)
    ok, _ = try_claim_daily(uid, amount=amount, interval_hours=DEFAULT_INTERVAL_HOURS)
    return ok, (amount if ok else 0)
