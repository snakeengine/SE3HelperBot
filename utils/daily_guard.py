# utils/daily_guard.py
from __future__ import annotations

import os
import time
from typing import Tuple

from lang import t, get_user_lang
from utils.rewards_store import ensure_user, add_points, mark_action

# إعدادات قابلة للضبط من البيئة
DEFAULT_DAILY_REWARD = int(os.getenv("DAILY_REWARD", "10"))
DEFAULT_INTERVAL_HOURS = int(os.getenv("DAILY_INTERVAL_HOURS", "24"))

# المفتاح الذي سنحفظ تحته ختم آخر مطالبة داخل last_actions
_DAILY_ACTION_KEY = "daily24"  # اسم واضح يخص نظام الـ 24 ساعة

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

def _get_last_claim_ts(uid: int) -> int:
    """
    نقرأ ختم آخر مطالبة من:
      1) last_actions[daily24] (الجديد)
      2) last_actions[daily]   (لو كان موجودًا قديمًا)
      3) last_claim            (توافقًا إن كانت موجودة من أنظمة أخرى)
    """
    u = ensure_user(uid)
    la = (u or {}).get("last_actions") or {}
    for k in (_DAILY_ACTION_KEY, "daily"):
        try:
            v = int(la.get(k) or 0)
            if v > 0:
                return v
        except Exception:
            pass
    try:
        return int((u or {}).get("last_claim") or 0)
    except Exception:
        return 0

def can_claim_daily(uid: int, interval_hours: int = DEFAULT_INTERVAL_HOURS) -> Tuple[bool, int]:
    """
    يرجع (مسموح؟, الثواني المتبقية) بناءً على ختم *فعلي* محفوظ في التخزين.
    """
    last = _get_last_claim_ts(uid)
    now = int(time.time())
    need = int(interval_hours * 3600)
    if last == 0 or (now - last) >= need:
        return True, 0
    return False, need - (now - last)

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

    # ✅ احفظ توقيت آخر مطالبة بشكل دائم داخل last_actions
    now_ts = int(time.time())
    mark_action(uid, _DAILY_ACTION_KEY, when=now_ts)

    # ملاحظة: لا حاجة لتغيير حقول أخرى مثل streak هنا، لأننا نستهدف فقط 24 ساعة حقيقية.
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
