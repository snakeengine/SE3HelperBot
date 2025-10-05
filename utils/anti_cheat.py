# utils/anti_cheat.py
from __future__ import annotations
import time, random, string
from typing import Tuple, Optional, Dict, Any

# تخزين المستخدمين الحالي
from utils.rewards_store import ensure_user, get_user as _get_user, _put_user as _set_user

# دعم اللغة
try:
    from lang import t as _t, get_user_lang as _get_user_lang
except Exception:
    # fallbacks آمنة إن لم تتوفر وحدة الترجمة
    def _t(_lang: str, _key: str) -> str:  # type: ignore
        return ""
    def _get_user_lang(_uid: int) -> str:  # type: ignore
        return "ar"

def _lang(uid: int) -> str:
    lg = (_get_user_lang(uid) or "ar").strip().lower()
    return "ar" if lg == "ar" else "en"

def _tf(uid: int, key: str, ar_fallback: str, en_fallback: str, **fmt) -> str:
    """يحاول قراءة النص من lang.t وإلا يرجع fallback مناسب للّغة، مع format للمتغيرات."""
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

# إعدادات عامة
CAPTCHA_TTL_OK_SEC = 7 * 24 * 3600        # مدة صلاحية التحقق (7 أيام)
CAPTCHA_TTL_OK_SEC_HIGH = 3 * 24 * 3600   # للحالات الحساسة (3 أيام)
CAPTCHA_MAX_FAILS = 5                     # أقصى عدد محاولات فاشلة قبل التجميد المؤقت
RISK_REQ_CAPTCHA = 2                      # لو المخاطرة >=2 يطلب كابتشا حتى لو حديث
COOLDOWN_BAN_SEC = 60 * 30                # تجميد 30 دقيقة عند كثرة الفشل

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
    abuse.setdefault("captcha", {})  # token, answer_idx, asked_at, opts
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
    """لو حاب تزود أسباب للمخاطرة لاحقًا (سلسلة تحويلات…الخ)."""
    if name in ("transfer_spam","invite_spree"):
        inc_risk(uid, 1)

def is_temporarily_banned(uid: int) -> bool:
    _, abuse = _u(uid)
    return _now() < int(abuse.get("ban_until", 0))

def _new_token(n: int = 6) -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))

def need_captcha(uid: int, level: str = "normal") -> bool:
    """يقرر إن كان يلزم كابتشا الآن."""
    u, abuse = _u(uid)
    # تجميد مؤقت
    if _now() < int(abuse.get("ban_until", 0)):
        return True

    ok_ttl = CAPTCHA_TTL_OK_SEC if level != "high" else CAPTCHA_TTL_OK_SEC_HIGH
    if _now() - int(abuse.get("captcha_passed_at", 0)) <= ok_ttl and int(abuse.get("risk", 0)) < RISK_REQ_CAPTCHA:
        return False
    return True

def build_captcha(uid: int) -> Tuple[str, list[str], int, str]:
    """يرجع: (النص, الخيارات, index الصحيح, token) ويحفظها في المستخدم.
       النص يُولَّد حسب لغة المستخدم (ar/en)."""
    u, abuse = _u(uid)
    target = random.choice(EMOJIS)
    opts = random.sample(EMOJIS, k=6)
    if target not in opts:
        opts[random.randrange(0, len(opts))] = target
    random.shuffle(opts)
    answer_idx = opts.index(target)
    token = _new_token()
    abuse["captcha"] = {
        "token": token,
        "answer_idx": answer_idx,
        "target": target,
        "opts": opts,
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
    return text, opts, answer_idx, token

def try_captcha(uid: int, token: str, answer_idx: int) -> bool:
    u, abuse = _u(uid)
    data = abuse.get("captcha", {})
    if not data or data.get("token") != token:
        # توكن قديم/غير صحيح
        inc_risk(uid, 1)
        return False
    correct = int(data.get("answer_idx", -1)) == int(answer_idx)
    if correct:
        abuse["captcha_passed_at"] = _now()
        abuse["fails"] = 0
        abuse["risk"] = max(0, int(abuse.get("risk", 0)) - 1)
    else:
        abuse["fails"] = int(abuse.get("fails", 0)) + 1
        abuse["risk"] = int(abuse.get("risk", 0)) + 1
        if abuse["fails"] >= CAPTCHA_MAX_FAILS:
            abuse["ban_until"] = _now() + COOLDOWN_BAN_SEC
            abuse["fails"] = 0
    # امسح التحدي الحالي
    abuse["captcha"] = {}
    u["abuse"] = abuse
    _set_user(uid, u)
    return correct
