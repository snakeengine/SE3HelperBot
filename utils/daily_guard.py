# utils/daily_guard.py
from __future__ import annotations

import os
import time
from typing import Tuple, Optional

from lang import t, get_user_lang
from utils.rewards_store import ensure_user, add_points, mark_action

# إعدادات قابلة للضبط من البيئة
_DEFAULT_DAILY_REWARD = int(os.getenv("DAILY_REWARD", "10"))
_DEFAULT_INTERVAL_HOURS = int(os.getenv("DAILY_INTERVAL_HOURS", "24"))

# المفتاح الذي سنحفظ تحته ختم آخر مطالبة داخل last_actions
_DAILY_ACTION_KEY = "daily24"  # اسم واضح يخص نظام الـ 24 ساعة

def _L(uid: int) -> str:
    try:
        return (get_user_lang(uid) or "ar").strip().lower()
    except Exception:
        return "ar"

def _tt(lang: str, key: str, fb_ar: str, fb_en: str, **fmt) -> str:
    """ترجمة مع fallback مخصّص للّغتين."""
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val.format(**fmt) if fmt else val
    except Exception:
        pass
    base = fb_ar if lang.startswith("ar") else fb_en
    try:
        return base.format(**fmt) if fmt else base
    except Exception:
        return base

def _fmt_remaining(sec: int, lang: str) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def _sanitize_interval_hours(v: Optional[int]) -> int:
    """نضمن قيمة بينية صحيحة ≥ 1 ساعة (وإلا نستخدم الافتراضي)."""
    try:
        vv = int(v or _DEFAULT_INTERVAL_HOURS)
    except Exception:
        vv = _DEFAULT_INTERVAL_HOURS
    return max(1, vv)

def _get_last_claim_ts(uid: int) -> int:
    """
    نقرأ ختم آخر مطالبة من مصادر متوافقة:
      1) last_actions[daily24] (الجديد)
      2) last_actions[daily]   (قديم)
      3) last_claim            (توافقًا إن كانت موجودة)
    """
    u = ensure_user(uid)
    la = (u or {}).get("last_actions") or {}
    for k in (_DAILY_ACTION_KEY, "daily"):
        try:
            v = int(la.get(k) or 0)
            if v > 0:
                return v
        except Exception:
            continue
    try:
        return int((u or {}).get("last_claim") or 0)
    except Exception:
        return 0

def can_claim_daily(uid: int, interval_hours: int = _DEFAULT_INTERVAL_HOURS) -> Tuple[bool, int]:
    """
    يرجع (مسموح؟, الثواني المتبقية) بناءً على ختم محفوظ في التخزين.
    """
    interval_hours = _sanitize_interval_hours(interval_hours)
    last = _get_last_claim_ts(uid)
    now = int(time.time())
    need = int(interval_hours * 3600)
    if last == 0 or (now - last) >= need:
        return True, 0
    return False, need - (now - last)

def get_remaining_seconds(uid: int, interval_hours: int | None = None) -> int:
    """مساعدة: ترجع الثواني المتبقية حتى المطالبة التالية."""
    interval_hours = _sanitize_interval_hours(interval_hours)
    ok, rem = can_claim_daily(uid, interval_hours=interval_hours)
    return 0 if ok else int(rem)

def next_claim_at(uid: int, interval_hours: int | None = None) -> int:
    """مساعدة: توقيت (epoch) موعد المطالبة التالية، 0 إن كانت متاحة الآن."""
    interval_hours = _sanitize_interval_hours(interval_hours)
    last = _get_last_claim_ts(uid)
    if last <= 0:
        return 0
    return int(last + interval_hours * 3600)

def set_last_claim_ts(uid: int, ts: int | None = None) -> None:
    """
    أداة فحص/إدارية: ضبط ختم آخر مطالبة يدويًا داخل last_actions[daily24].
    مفيدة للاختبارات أو لإصلاحات يدوية.
    """
    when = int(ts or time.time())
    mark_action(uid, _DAILY_ACTION_KEY, when=when)

def try_claim_daily(
    uid: int,
    amount: int | None = None,
    interval_hours: int | None = None
) -> Tuple[bool, str]:
    """
    يحاول إضافة مكافأة يومية ضمن مهلة 24 ساعة (قابلة للتعديل).
    يرجع (success, message).
    """
    amount = int(amount or _DEFAULT_DAILY_REWARD)
    interval_hours = _sanitize_interval_hours(interval_hours)

    ok, remaining = can_claim_daily(uid, interval_hours=interval_hours)
    lang = _L(uid)

    if not ok:
        msg = _tt(
            lang, "rewards.daily.wait",
            fb_ar="لقد أخذت نقاط اليوم بالفعل. المتبقي: {time}",
            fb_en="You already claimed today. Time left: {time}",
            time=_fmt_remaining(remaining, lang),
        )
        return False, msg

    # أضف النقاط وسجّل العملية
    add_points(uid, amount, typ="daily", reason="daily")

    # ✅ احفظ توقيت آخر مطالبة داخل last_actions لضمان الاعتماد على التخزين الدائم
    now_ts = int(time.time())
    mark_action(uid, _DAILY_ACTION_KEY, when=now_ts)

    # رسالة نجاح
    msg = _tt(
        lang, "rewards.daily.ok",
        fb_ar="أُضيفت {amount} نقطة ✅",
        fb_en="{amount} points added ✅",
        amount=amount,
    )
    return True, msg

# للتوافق مع كود قديم كان يستدعي daily_claim ويرجع (ok, awarded)
def daily_claim(uid: int, amount: int | None = None) -> Tuple[bool, int]:
    amount = int(amount or _DEFAULT_DAILY_REWARD)
    ok, _ = try_claim_daily(uid, amount=amount, interval_hours=_DEFAULT_INTERVAL_HOURS)
    return ok, (amount if ok else 0)
