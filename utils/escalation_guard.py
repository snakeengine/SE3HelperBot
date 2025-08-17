# utils/escalation_guard.py
from __future__ import annotations

import os, json
from datetime import datetime, timedelta
from typing import Optional, Tuple
from aiogram import Bot
from lang import t, get_user_lang

# ===== مسارات البيانات (محايدة، بدون VIP) =====
DATA_DIR = "data"
BANS_FILE        = os.path.join(DATA_DIR, "escalation_bans.json")
STATE_FILE       = os.path.join(DATA_DIR, "escalation_state.json")

# ===== الإعدادات =====
WARN_THRESHOLD           = 3               # عند 3 محاولات خلال النافذة: تحذير
ATTEMPT_WINDOW_MINUTES   = 10              # نافذة احتساب المحاولات
BAN_STEPS_HOURS          = [1, 6, 12, 24]  # 1h → 6h → 12h → 24h (يثبت بعدها على 24h)
STRIKE_DECAY_DAYS        = 7               # ينخفض مستوى التصعيد درجة كل 7 أيام من دون مخالفات

os.makedirs(DATA_DIR, exist_ok=True)
for p, default in [(BANS_FILE, {}), (STATE_FILE, {})]:
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

# ---------- أدوات JSON ----------
def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _atomic_save(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _save(path, data):
    try:
        _atomic_save(path, data)
    except Exception:
        # لا نكسر المنطق إن فشل الحفظ
        pass

# ---------- وقت/تنسيق ----------
def _now():
    # نستخدم UTC لتوحيد الحساب
    return datetime.utcnow()

def _fmt(iso: str) -> str:
    """تنسيق ISO إلى عرض مختصر قابل للقراءة."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso or "N/A"

def _human_duration(seconds: int, lang: str) -> str:
    """عرض بسيط للمدة بالساعة/اليوم (AR/EN)."""
    h = max(1, seconds // 3600)
    if lang == "ar":
        if h < 24:
            return f"{h} ساعة"
        d = h // 24
        return f"{d} يوم"
    # EN (افتراضي)
    if h < 24:
        return f"{h}h"
    d = h // 24
    return f"{d}d"

def _decay_strike(state: dict) -> dict:
    """يُخفّض مستوى التصعيد تلقائيًا عند حلول موعد الانقاص."""
    now = _now()
    decay_at = state.get("decay_at")
    if state.get("strike", 0) > 0 and decay_at:
        try:
            if now >= datetime.fromisoformat(decay_at):
                state["strike"] = max(0, state.get("strike", 0) - 1)
                state["decay_at"] = (now + timedelta(days=STRIKE_DECAY_DAYS)).isoformat()
        except Exception:
            pass
    return state

# ---------- استعلام حالة الحظر ----------
def is_banned_now(user_id: int) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    يرجع (banned?, remaining_seconds, until_iso)
    """
    bans = _load(BANS_FILE, {})
    rec = bans.get(str(user_id))
    if not rec or "until" not in rec:
        return False, None, None
    try:
        until = datetime.fromisoformat(rec["until"])
        now = _now()
        if now < until:
            return True, int((until - now).total_seconds()), rec["until"]
    except Exception:
        pass
    # انتهى الحظر
    return False, None, None

# ---------- المنطق الرئيسي ----------
async def process_attempt(bot: Bot, user_id: int, lang: str | None = None, chat_id: int | None = None):
    """
    تُستدعى عندما يحاول مستخدم الدخول لميزة محجوبة.
    - عند وصول عدد المحاولات في النافذة إلى WARN_THRESHOLD ⇒ رسالة تحذير.
    - بعدها ⇒ حظر مؤقت بمدة تصاعدية: 1h → 6h → 12h → 24h (ثم يثبت على 24h).
    - تستخدم مفاتيح ترجمة عامة:
        • rate_warn: "Warning: you made {attempts} attempts in a short time.\nIf you continue, you will be temporarily banned for {duration}."
        • rate_banned: "You have been temporarily banned for {duration} due to repeated attempts.\nYou may try again after: {until}."
    """
    lang = lang or get_user_lang(user_id) or "en"
    send_to = chat_id or user_id

    state = _load(STATE_FILE, {})
    bans  = _load(BANS_FILE, {})

    # إذا كان محظورًا بالفعل — لا نعيد فرض شيء هنا (يُفضّل أن يتعامل النداء الأعلى مع الرد)
    banned, remaining, until_iso = is_banned_now(user_id)
    if banned:
        # رد اختياري سريع (يمكن حذف هذا البلوك لو تفضّل الصمت أثناء الحظر)
        try:
            txt = (t(lang, "rate_banned") or "⏱️ You are temporarily banned for {duration}. Try again after: {until}.") \
                .replace("{duration}", _human_duration(remaining or 0, lang)) \
                .replace("{until}", _fmt(until_iso or ""))
            await bot.send_message(send_to, txt, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
        return

    # سجلّ المستخدم في حالة الإساءة
    u = state.get(str(user_id), {
        "count": 0,
        "window_until": (_now() + timedelta(minutes=ATTEMPT_WINDOW_MINUTES)).isoformat(),
        "warned": False,
        "strike": 0,
        "decay_at": (_now() + timedelta(days=STRIKE_DECAY_DAYS)).isoformat(),
        "last_ban_at": None
    })

    # تطبيق الانقاص التلقائي
    u = _decay_strike(u)

    # إعادة ضبط النافذة إن انتهت
    try:
        if _now() >= datetime.fromisoformat(u["window_until"]):
            u["count"] = 0
            u["warned"] = False
            u["window_until"] = (_now() + timedelta(minutes=ATTEMPT_WINDOW_MINUTES)).isoformat()
    except Exception:
        u["window_until"] = (_now() + timedelta(minutes=ATTEMPT_WINDOW_MINUTES)).isoformat()

    # تسجيل المحاولة الحالية
    u["count"] += 1

    # 1) التحذير عند الوصول للحد
    if u["count"] == WARN_THRESHOLD and not u.get("warned", False):
        next_idx = min(u.get("strike", 0), len(BAN_STEPS_HOURS) - 1)
        next_seconds = int(BAN_STEPS_HOURS[next_idx] * 3600)
        text = (t(lang, "rate_warn") or "⚠️ Warning: you made {attempts} attempts. Continuing may lead to a temporary ban for {duration}.") \
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
        idx = min(u.get("strike", 0), len(BAN_STEPS_HOURS) - 1)
        seconds = int(BAN_STEPS_HOURS[idx] * 3600)
        until = _now() + timedelta(seconds=seconds)

        # سجلّ الحظر
        bans[str(user_id)] = {"until": until.isoformat()}
        _save(BANS_FILE, bans)

        # تصفير العداد ورفع مستوى التصعيد
        u["count"] = 0
        u["warned"] = False
        u["strike"] = min(u.get("strike", 0) + 1, len(BAN_STEPS_HOURS) - 1)
        u["last_ban_at"] = _now().isoformat()
        u["decay_at"] = (_now() + timedelta(days=STRIKE_DECAY_DAYS)).isoformat()
        state[str(user_id)] = u
        _save(STATE_FILE, state)

        # رسالة الحظر — تستخدم rate_banned
        text = (t(lang, "rate_banned") or "⏱️ You have been temporarily banned for {duration}. You may try again after: {until}.") \
            .replace("{duration}", _human_duration(seconds, lang)) \
            .replace("{until}", _fmt(until.isoformat()))
        try:
            await bot.send_message(send_to, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
        return

    # 3) أقل من حد التحذير → حفظ الحالة فقط
    state[str(user_id)] = u
    _save(STATE_FILE, state)

def on_manual_unban(user_id: int):
    """
    تُستدعى اختياريًا بعد إلغاء حظر يدوي.
    لا نُصفّر مستوى التصعيد؛ فقط نحدّث decay_at ليبدأ عدّ 7 أيام من جديد.
    """
    state = _load(STATE_FILE, {})
    u = state.get(str(user_id))
    if not u:
        return
    u["decay_at"] = (_now() + timedelta(days=STRIKE_DECAY_DAYS)).isoformat()
    state[str(user_id)] = u
    _save(STATE_FILE, state)
