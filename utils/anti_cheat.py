from __future__ import annotations

# utils/anti_cheat.py

import os, time, random, string
from typing import Tuple, Optional, Dict, Any

# تخزين المستخدمين الحالي
from utils.rewards_store import ensure_user, get_user as _get_user, _put_user as _set_user

# دعم اللغة
try:
    from lang import t as _t, get_user_lang as _get_user_lang
except Exception:
    def _t(_lang: str, _key: str) -> str:  # type: ignore
        return ""
    def _get_user_lang(_uid: int) -> str:  # type: ignore
        return "ar"

def _lang(uid: int) -> str:
    lg = (_get_user_lang(uid) or "ar").strip().lower()
    return "ar" if lg == "ar" else "en"

def _tf(uid: int, key: str, ar_fallback: str, en_fallback: str, **fmt) -> str:
    lg = _lang(uid)
    try:
        s = _t(lg, key)
        if isinstance(s, str) and s.strip():
            try:
                return s.format(**fmt) if fmt else s
            except Exception:
                return s
    except Exception:
        pass
    base = ar_fallback if lg == "ar" else en_fallback
    try:
        return base.format(**fmt) if fmt else base
    except Exception:
        return base

# ===== إعدادات قابلة للتهيئة عبر ENV =====
def _intenv(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, "").strip() or default)
        return int(v)
    except Exception:
        return default

CAPTCHA_TTL_OK_SEC       = _intenv("CAPTCHA_TTL_OK_SEC",       7 * 24 * 3600)  # 7 أيام
CAPTCHA_TTL_OK_SEC_HIGH  = _intenv("CAPTCHA_TTL_OK_SEC_HIGH",  3 * 24 * 3600)  # 3 أيام
CAPTCHA_MAX_FAILS        = _intenv("CAPTCHA_MAX_FAILS",        5)
RISK_REQ_CAPTCHA         = _intenv("RISK_REQ_CAPTCHA",         2)
COOLDOWN_BAN_SEC         = _intenv("COOLDOWN_BAN_SEC",         60 * 30)        # 30 دقيقة
CAPTCHA_MIN_GAP_SEC      = _intenv("CAPTCHA_MIN_GAP_SEC",      8)              # منع توليد متكرر بسرعة
CAPTCHA_OPTIONS_COUNT    = max(3, _intenv("CAPTCHA_OPTIONS",   6))             # عدد الخيارات

EMOJIS = ["😀","😎","🤖","🐱","🍩","🍉","🚗","🛵","🎲","🧩","🎯","🧠","⚙️","🪙","💎"]

def _now() -> int:
    return int(time.time())

def _u(uid: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ensure_user(uid)
    u = _get_user(uid)
    abuse = u.setdefault("abuse", {})
    abuse.setdefault("risk", 0)
    abuse.setdefault("fails", 0)
    abuse.setdefault("captcha_passed_at", 0)
    abuse.setdefault("last_captcha", 0)
    abuse.setdefault("ban_until", 0)
    abuse.setdefault("captcha", {})  # token, answer_idx, asked_at, opts, target
    return u, abuse

def inc_risk(uid: int, delta: int = 1, reason: str = ""):
    u, abuse = _u(uid)
    abuse["risk"] = max(0, int(abuse.get("risk", 0)) + int(delta))
    u["abuse"] = abuse
    _set_user(uid, u)

def dec_risk(uid: int, delta: int = 1):
    u, abuse = _u(uid)
    abuse["risk"] = max(0, int(abuse.get("risk", 0)) - int(delta))
    u["abuse"] = abuse
    _set_user(uid, u)

def mark_event(uid: int, name: str):
    """سجل أسباب للمخاطرة (مثال: سلوك تحويلات متكرر)."""
    if name in ("transfer_spam","invite_spree"):
        inc_risk(uid, 1, reason=name)

def is_temporarily_banned(uid: int) -> bool:
    _, abuse = _u(uid)
    return _now() < int(abuse.get("ban_until", 0))

def _new_token(n: int = 6) -> str:
    pool = string.ascii_letters + string.digits
    return "".join(random.choice(pool) for _ in range(n))

def need_captcha(uid: int, level: str = "normal") -> bool:
    """يقرر إن كان يلزم كابتشا الآن."""
    u, abuse = _u(uid)
    if _now() < int(abuse.get("ban_until", 0)):
        return True

    ok_ttl = CAPTCHA_TTL_OK_SEC if level != "high" else CAPTCHA_TTL_OK_SEC_HIGH
    # إذا تحقّق مؤخرًا وكان الخطر منخفضًا → لا حاجة
    if _now() - int(abuse.get("captcha_passed_at", 0)) <= ok_ttl and int(abuse.get("risk", 0)) < RISK_REQ_CAPTCHA:
        return False
    return True

def build_captcha(uid: int) -> Tuple[str, list[str], int, str]:
    """
    يُرجع: (النص, الخيارات, index الصحيح, token) ويحفظها في المستخدم.
    """
    u, abuse = _u(uid)

    # منع توليد متكرر خلال ثوانٍ قليلة
    if _now() - int(abuse.get("last_captcha", 0)) < CAPTCHA_MIN_GAP_SEC:
        data = abuse.get("captcha") or {}
        opts = list(data.get("opts") or [])
        answer_idx = int(data.get("answer_idx", -1))
        token = data.get("token") or _new_token()
        target = data.get("target") or random.choice(EMOJIS)
    else:
        target = random.choice(EMOJIS)
        k = min(CAPTCHA_OPTIONS_COUNT, len(EMOJIS))
        # استخدم عيّنة مع ضمان وجود الهدف ضمن الخيارات
        opts = random.sample(EMOJIS, k=k)
        if target not in opts:
            opts[random.randrange(0, len(opts))] = target
        random.shuffle(opts)
        answer_idx = int(opts.index(target))
        token = _new_token()

    abuse["captcha"] = {
        "token": token,
        "answer_idx": int(answer_idx),
        "target": target,
        "opts": list(opts),
        "asked_at": _now(),
    }
    abuse["last_captcha"] = _now()
    u["abuse"] = abuse
    _set_user(uid, u)

    text = _tf(
        uid,
        "anti.captcha.text",
        "تحقق بسيط: اختر الإيموجي المطلوب للتأكيد أنك لست روبوت.\n\nالمطلوب: {target}",
        "Quick check: pick the requested emoji to confirm you're not a bot.\n\nTarget: {target}",
        target=target,
    )
    return text, opts, int(answer_idx), token

def try_captcha(uid: int, token: str, answer_idx: int) -> bool:
    u, abuse = _u(uid)
    data = abuse.get("captcha", {}) or {}
    # تحقق من الفهرس
    try:
        answer_idx = int(answer_idx)
    except Exception:
        answer_idx = -1

    # توكن غير صالح/منتهي
    if not data or data.get("token") != token:
        inc_risk(uid, 1, reason="captcha_token_mismatch")
        # امسح أي تحدّي قديم
        abuse["captcha"] = {}
        u["abuse"] = abuse
        _set_user(uid, u)
        return False

    correct = int(data.get("answer_idx", -1)) == answer_idx
    if correct:
        # نجاح → تصفير الفشل وتقليل المخاطرة بدرجتين
        abuse["captcha_passed_at"] = _now()
        abuse["fails"] = 0
        abuse["risk"] = max(0, int(abuse.get("risk", 0)) - 2)
    else:
        fails = int(abuse.get("fails", 0)) + 1
        abuse["fails"] = fails
        abuse["risk"] = int(abuse.get("risk", 0)) + 1
        if fails >= CAPTCHA_MAX_FAILS:
            abuse["ban_until"] = _now() + COOLDOWN_BAN_SEC
            abuse["fails"] = 0

    # امسح التحدي الحالي دائمًا بعد المحاولة
    abuse["captcha"] = {}
    u["abuse"] = abuse
    _set_user(uid, u)
    return bool(correct)
