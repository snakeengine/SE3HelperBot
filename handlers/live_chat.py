# handlers/live_chat.py
from __future__ import annotations
import os, json, time, logging, inspect
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from lang import t, get_user_lang
from aiogram.filters import Command

__all__ = ["router", "LiveChat"]

router = Router(name="live_chat")
log = logging.getLogger(__name__)

# =============== ANTI-CONFLICT PATCH ===============
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")
# لا تفعّل هذا الفلتر العام هنا حتى لا يؤثر على راوترات أخرى:
# router.message.filter(~F.text.startswith("/"), ~F.caption.startswith("/"))
router.callback_query.filter(F.data.startswith("live:") | (F.data == "bot:live"))
# ===================================================

# ----(optional) unified inbox binding ----
try:
    from utils import support_inbox as _inbox
except Exception:
    _inbox = None

def _inbox_call(fn: str, *a, **kw):
    """Call support_inbox.fn if available; ignore failures."""
    try:
        if _inbox and hasattr(_inbox, fn):
            getattr(_inbox, fn)(*a, **kw)
    except Exception:
        pass
# ----------------------------------------

ADMIN_ONLINE_TTL = int(os.getenv("ADMIN_ONLINE_TTL", "600"))  # 10 دقائق

ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID","")).split(",") if x.strip().isdigit()]
def _targets() -> list[int]:
    return [aid for aid in ADMIN_IDS]

# ---- Role-aware admin gate (works with or without roles.py) ----
try:
    from utils.roles import has_role_at_least as _has_role
    def _is_admin(uid: int) -> bool:
        # نسمح لمن دوره support أو أعلى (support/moderator/admin/superadmin/owner)
        return bool(_has_role(uid, "support"))
except Exception:
    def _is_admin(uid: int) -> bool:
        return uid in ADMIN_IDS
# ----------------------------------------------------------------

DATA = Path("data")
SESSIONS_FILE = DATA/"live_sessions.json"
RELAYS_FILE   = DATA/"live_relays.json"
ADMIN_ACTIVE  = DATA/"live_admin_active.json"
HISTORY_FILE  = DATA/"live_history.json"
RATINGS_FILE  = DATA/"live_ratings.json"
BLOCKLIST_FILE= DATA/"live_blocklist.json"
ADMIN_SEEN    = DATA/"admin_last_seen.json"
SESSION_TTL = 60*30
LIVE_CONFIG = DATA/"live_config.json"

def _now() -> float: return time.time()

def _load(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(p: Path, obj):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        log.warning("save %s failed: %s", p, e)

def _support_enabled() -> bool:
    cfg = _load(LIVE_CONFIG)
    return bool(cfg.get("enabled", True))

def _blocked(uid: int) -> bool:
    row = _load(BLOCKLIST_FILE).get(str(uid))
    if not row:
        return False
    if isinstance(row, dict):
        until = float(row.get("until", 0) or 0)
        if until and _now() > until:
            bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
            return False
        return True
    return bool(row)

def _L(uid: int) -> str:
    try:
        return (get_user_lang(uid) or "ar").lower()
    except Exception:
        return "ar"

def _tt(lang: str, key: str, ar: str, en: str) -> str:
    try:
        val = t(lang, key)
        if val and val != key:
            return val
    except Exception:
        pass
    return ar if (lang or "ar").startswith("ar") else en

def _get_session(uid: int) -> dict:
    return _load(SESSIONS_FILE).get(str(uid), {})

def _put_session(uid: int, data: dict):
    s = _load(SESSIONS_FILE); s[str(uid)] = data; _save(SESSIONS_FILE, s)

def _del_session(uid: int):
    s = _load(SESSIONS_FILE); s.pop(str(uid), None); _save(SESSIONS_FILE, s)

def _touch(uid: int):
    s = _get_session(uid)
    if s:
        s["last_ts"] = _now()
        _put_session(uid, s)

def _expired(sess: dict) -> bool:
    return (_now() - float(sess.get("last_ts", 0))) > SESSION_TTL

def _set_admin_active(admin_id: int, uid: int):
    m = _load(ADMIN_ACTIVE); m[str(admin_id)] = int(uid); _save(ADMIN_ACTIVE, m)

def _clear_admin_active(admin_id: int):
    m = _load(ADMIN_ACTIVE); 
    if str(admin_id) in m:
        m.pop(str(admin_id), None); _save(ADMIN_ACTIVE, m)

def _get_admin_active(admin_id: int) -> int | None:
    m = _load(ADMIN_ACTIVE); v = m.get(str(admin_id))
    try:
        return int(v) if v else None
    except Exception:
        return None

def _ensure_history(sid: str, uid: int, admin_id: int | None, start_ts: float):
    h = _load(HISTORY_FILE)
    if sid not in h:
        h[sid] = {"uid": uid, "admin_id": admin_id, "start_ts": start_ts}
        _save(HISTORY_FILE, h)

def _update_history(sid: str, **fields):
    h = _load(HISTORY_FILE); rec = h.get(sid) or {}
    rec.update(fields); h[sid] = rec; _save(HISTORY_FILE, h)

def _finish_history(sid: str, tag: str | None = None) -> dict:
    h = _load(HISTORY_FILE); rec = h.get(sid) or {}
    if rec:
        rec["end_ts"] = _now()
        rec["duration"] = max(0, int(rec["end_ts"] - float(rec.get("start_ts", _now()))))
        if tag: rec["tag"] = tag
        h[sid] = rec; _save(HISTORY_FILE, h)
    return rec

def _set_admin_rating(sid: str, stars: int):
    r = _load(RATINGS_FILE); row = r.get(sid) or {}
    row["admin_rating"] = int(stars); r[sid] = row; _save(RATINGS_FILE, r)

def _format_period(seconds: int) -> str:
    # تنسيق بسيط: أيام/ساعات/دقائق
    s = int(seconds)
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) or f"{s}s"

def _block_user(uid: int, seconds: int, reason: str | None = None):
    """يحظر المستخدم لمدة معيّنة بالثواني."""
    bl = _load(BLOCKLIST_FILE)
    bl[str(uid)] = {"until": _now() + max(1, int(seconds)), "reason": reason or ""}
    _save(BLOCKLIST_FILE, bl)

def _block_status(uid: int) -> tuple[bool, int, str | None]:
    """
    يرجع (is_blocked, remaining_seconds, reason).
    ينظّف الحظر المنتهي تلقائياً.
    """
    row = _load(BLOCKLIST_FILE).get(str(uid))
    if not row:
        return False, 0, None
    try:
        until = float(row.get("until", 0) or 0)
    except Exception:
        until = 0
    rem = max(0, int(until - _now()))
    if rem <= 0:
        bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
        return False, 0, None
    return True, rem, (row.get("reason") or None)

def _fmt_dur(sec: int, lang: str) -> str:
    """تنسيق مختصر للمدة المتبقّية (أيام/ساعات/دقائق/ثوانٍ)."""
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}" + (" يوم" if lang.startswith("ar") else "d"))
    if h: parts.append(f"{h}" + (" ساعة" if lang.startswith("ar") else "h"))
    if m and not d: parts.append(f"{m}" + (" دقيقة" if lang.startswith("ar") else "m"))
    if s and not d and not h: parts.append(f"{s}" + (" ثانية" if lang.startswith("ar") else "s"))
    return " ".join(parts) or ("ثوانٍ" if lang.startswith("ar") else "secs")

def _get_strikes(uid: int) -> int:
    bl = _load(BLOCKLIST_FILE)
    row = bl.get(str(uid)) or {}
    return int(row.get("strikes", 0))

def _put_block(uid: int, seconds: int, reason: str | None = None):
    bl = _load(BLOCKLIST_FILE)
    row = bl.get(str(uid)) or {}
    strikes = int(row.get("strikes", 0)) + 1
    until = _now() + max(0, int(seconds))
    bl[str(uid)] = {"until": until, "reason": reason or "", "strikes": strikes}
    _save(BLOCKLIST_FILE, bl)

def _clear_block(uid: int):
    bl = _load(BLOCKLIST_FILE)
    if str(uid) in bl:
        bl.pop(str(uid), None)
        _save(BLOCKLIST_FILE, bl)

# (اختياري) تصعيد تلقائي إن أردت — مثال: ×2 لكل ضربة
def _auto_penalty_seconds(base_seconds: int, strikes_after: int) -> int:
    # strike1=1x, strike2=2x, strike3=4x, ...
    factor = 2 ** max(0, strikes_after-1)
    return int(base_seconds * factor)

def _set_user_rating(sid: str, stars: int):
    r = _load(RATINGS_FILE); row = r.get(sid) or {}
    row["user_rating"] = int(stars); r[sid] = row; _save(RATINGS_FILE, r)

def _touch_admin(admin_id: int):
    m = _load(ADMIN_SEEN)
    row = m.get(str(admin_id))
    if isinstance(row, dict):
        row["ts"] = _now()
    else:
        row = {"online": True, "ts": _now()}
    m[str(admin_id)] = row
    _save(ADMIN_SEEN, m)

def _set_admin_online(admin_id: int, online: bool):
    m = _load(ADMIN_SEEN)
    row = m.get(str(admin_id)) or {}
    row["online"] = bool(online)
    row["ts"] = _now()
    m[str(admin_id)] = row
    _save(ADMIN_SEEN, m)

def _any_admin_online() -> bool:
    m = _load(ADMIN_SEEN)
    now = _now()
    any_online = False
    dirty = False

    for k, v in m.items():
        if isinstance(v, dict):
            ts = float(v.get("ts", 0) or 0)
            online = bool(v.get("online", False))
            # أونلاين فقط إذا ضمن النافذة الزمنية
            if online and ts and (now - ts) <= ADMIN_ONLINE_TTL:
                any_online = True
            elif online and ts and (now - ts) > ADMIN_ONLINE_TTL:
                m[k]["online"] = False
                dirty = True
        else:
            # شكل قديم: قيمة = آخر ظهور (ts)
            try:
                if (now - float(v)) <= ADMIN_ONLINE_TTL:
                    any_online = True
                else:
                    dirty = True
            except Exception:
                pass

    if dirty:
        _save(ADMIN_SEEN, m)
    return any_online

def _live_available() -> bool:
    """الدردشة متاحة فقط إذا كانت مفعّلة ويوجد إدمن أونلاين."""
    try:
        return _support_enabled() and _any_admin_online()
    except Exception:
        return False


def _admin_is_online(aid: int) -> bool:
    m = _load(ADMIN_SEEN).get(str(aid))
    if isinstance(m, dict):
        ts = float(m.get("ts", 0) or 0)
        online = bool(m.get("online", False))
        return online and ts and (_now() - ts) <= ADMIN_ONLINE_TTL
    try:
        return (_now() - float(m)) <= ADMIN_ONLINE_TTL
    except Exception:
        return False

async def _notify_admins_t(bot, key: str, ar: str, en: str, build_kb=None, **fmt):
    for aid in _targets():
        # أرسل إشعار فقط للإدمن الأونلاين
        if not _admin_is_online(aid):
            continue
        try:
            alang = _L(aid)
            text = _tt(alang, key, ar, en).format(**fmt)
            kb = None
            if build_kb:
                res = build_kb(alang)
                if inspect.isawaitable(res):
                    res = await res
                kb = res
            await bot.send_message(aid, text, reply_markup=kb)
        except Exception as e:
            log.warning("[live] notify %s failed: %s", aid, e)


def _sid_pack(s: str) -> str:
    return str(s).replace(":", "~")

def _sid_unpack(s: str) -> str:
    return str(s).replace("~", ":")

def _parse_uid_sid(data: str) -> tuple[int, str]:
    parts = data.split(":")
    uid = int(parts[2]); sid_packed = ":".join(parts[3:])
    return uid, _sid_unpack(sid_packed)

def _parse_uid_sid_tag(data: str) -> tuple[int, str, str]:
    parts = data.split(":")
    uid = int(parts[2]); tag = parts[-1]
    sid_packed = ":".join(parts[3:-1])
    return uid, _sid_unpack(sid_packed), tag

def _parse_uid_sid_stars(data: str) -> tuple[int, str, int]:
    parts = data.split(":")
    uid = int(parts[2]); stars = int(parts[-1])
    sid_packed = ":".join(parts[3:-1])
    return uid, _sid_unpack(sid_packed), stars

# ================== UI ==================
def _kb_user_actions(lang: str, sid: str) -> InlineKeyboardMarkup:
    psid = _sid_pack(sid)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang,"live.btn.end","❌ إنهاء الدردشة","❌ End chat"), callback_data="live:end_self"),
        InlineKeyboardButton(text=_tt(lang,"live.btn.rate","⭐ تقييم","⭐ Rate"), callback_data=f"live:rateopen:{psid}")
    ]])

def _kb_user_rate_choices(psid: str, lang: str) -> InlineKeyboardMarkup:
    stars = [InlineKeyboardButton(text=f"{i}⭐", callback_data=f"live:urate:{psid}:{i}") for i in range(1,6)]
    back  = InlineKeyboardButton(text=("⬅️ رجوع" if lang.startswith("ar") else "⬅️ Back"), callback_data=f"live:rateclose:{psid}")
    return InlineKeyboardMarkup(inline_keyboard=[stars,[back]])

def _kb_user_wait(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang, "live.btn.cancel", "❌ إلغاء الدردشة", "❌ Cancel chat"), callback_data="live:cancel")
    ]])

def _kb_user_end(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang, "live.btn.end", "❌ إنهاء الدردشة", "❌ End chat"), callback_data="live:end_self")
    ]])

CATEGORIES = {
    "app": ("مشاكل التطبيق", "App issues"),
    "pay": ("مشاكل الدفع", "Payment issues"),
    "ask": ("استفسارات عامة", "General questions"),
    "prom": ("أريد أن أصبح مُروّجًا", "Become a promoter"),
    "sup": ("أريد أن أصبح مورّدًا", "Become a supplier"),
    "other": ("أخرى", "Other"),
}
def _cat_label(lang: str, code: str) -> str:
    ar, en = CATEGORIES.get(code, CATEGORIES["other"])
    return ar if lang.startswith("ar") else en

def _kb_pre_live(lang: str) -> InlineKeyboardMarkup:
    rows = [[("app","🛠️"), ("pay","💳")],
            [("ask","❓"), ("prom","📣")],
            [("sup","🛍️"), ("other","📝")]]
    ik = []
    for pair in rows:
        row = []
        for code, icon in pair:
            row.append(InlineKeyboardButton(text=f"{icon} {_cat_label(lang, code)}", callback_data=f"live:cat:{code}"))
        ik.append(row)
    # ⬅️ مهم: Namespace محلي للدردشة فقط لتجنب التعارض مع أي back عام
    ik.append([InlineKeyboardButton(text=("⬅️ رجوع" if lang.startswith("ar") else "⬅️ Back"),
                                    callback_data="live:back")])
    return InlineKeyboardMarkup(inline_keyboard=ik)

def _pre_header(lang: str) -> str:
    if lang == "ar":
        return ("💬 <b>الدردشة الحيّة</b>\nاختر نوع طلبك أولًا للحصول على مساعدة أسرع:")
    return ("💬 <b>Live chat</b>\nPlease pick a category first for faster help:")

def _cat_hint(lang: str, code: str) -> str:
    if lang == "ar":
        mapping = {
            "app": "• ثبّت آخر نسخة من التطبيق (زر <b>تثبيت تطبيق ثعبان</b> في القائمة)\n• أرفق صورة/فيديو للمشكلة + نوع جهازك وأندرويد.",
            "pay": "• أرفق لقطة شاشة لعملية الدفع ورقم الطلب (إن وجد) + اسم البائع.\n• يمكن فتح تذكرة أيضًا بـ /report.",
            "ask": "• اكتب سؤالك بإيجاز. إن كان عن الأمان، راجع «دليل الاستخدام الآمن».",
            "prom": "• اطلع أولًا على شروط ونصائح المروّجين من «كيف تصبح مُروّجًا؟».",
            "sup": "• للتقديم كمورّد استخدم «كيف تصبح مورّدًا؟» من القائمة واقرأ الشروط.",
            "other": "• صف مشكلتك بإيجاز واذكر أي تفاصيل مفيدة (صور/روابط/خطوات).",
        }
    else:
        mapping = {
            "app": "• Make sure you installed the latest app (see “Download App”).\n• Attach a screenshot/video + your device model & Android.",
            "pay": "• Attach a payment screenshot and order ID (if any) + seller name.\n• You can also open a ticket via /report.",
            "ask": "• Ask briefly. For safety questions, check “Safe Usage Guide”.",
            "prom": "• Read “Become a promoter?” first for requirements.",
            "sup": "• Use “Become a supplier?” in the menu and review the requirements.",
            "other": "• Describe your issue briefly and add useful details (images/links/steps).",
        }
    return mapping.get(code, mapping["other"])

def _terms_text(lang: str) -> str:
    if lang == "ar":
        return ("📜 <b>شروط الدردشة</b>\n"
                "1) كن محترمًا وتحدّث عن موضوع واحد فقط.\n"
                "2) لا تشارك بيانات حسّاسة أو أكواد شراء علنًا.\n"
                "3) أرفق لقطات/تفاصيل واضحة لتسريع الحل.\n"
                "4) قد تُستخدم المحادثة لتحسين جودة الخدمة.\n\n"
                "بالضغط على «أوافق وابدأ»، سيتم فتح دردشة مع الدعم.")
    return ("📜 <b>Chat terms</b>\n"
            "1) Be respectful and stick to one topic.\n"
            "2) Don’t share sensitive data publicly.\n"
            "3) Provide clear screenshots/details for faster help.\n"
            "4) Chat may be used to improve service quality.\n\n"
            "By tapping “Agree & Start”, we’ll open a chat with support.")

def _kb_terms(lang: str, code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("✅ أوافق وابدأ" if lang=="ar" else "✅ Agree & Start"),
                              callback_data=f"live:start:{code}")],
        [InlineKeyboardButton(text=("⬅️ اختيار نوع آخر" if lang=="ar" else "⬅️ Pick another"),
                              callback_data="live:pre")]
    ])

@router.callback_query(F.data == "live:back")
async def cb_live_back(cb: CallbackQuery):
    # نحذف رسالة قائمة الدردشة فقط بدون لمس أي راوتر آخر
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()

def _kb_blocked(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=("⟳ تحديث الوقت" if lang.startswith("ar") else "⟳ Refresh"),
                             callback_data="live:brefresh")
    ]])

@router.callback_query(F.data == "live:brefresh")
async def cb_block_refresh(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    blocked, remain, _ = _block_status(uid)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "⛔ تم حظرك من الدردشة الحيّة.\nالوقت المتبقّي: {rem}",
                  "⛔ You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            pass
        return await cb.answer()
    # لم يعد محظوراً → نرجع لشاشة ما قبل الدردشة
    try:
        await cb.message.edit_text(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
    except Exception:
        try:
            await cb.message.answer(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
        except Exception:
            pass
    await cb.answer(_tt(lang, "live.unblocked", "تم رفع الحظر. يمكنك البدء الآن.", "Ban lifted. You can start now."))

@router.callback_query(F.data.in_({"bot:live", "live:pre"}))
async def cb_open_pre(cb: CallbackQuery):
    lang = _L(cb.from_user.id)

    # 🔒 حظر: اعرض رسالة تفصيلية مع الوقت المتبقّي
    blocked, remain, _ = _block_status(cb.from_user.id)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "⛔ تم حظرك من الدردشة الحيّة.\nالوقت المتبقّي: {rem}",
                  "⛔ You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            try:
                await cb.message.answer(txt, reply_markup=_kb_blocked(lang))
            except Exception:
                pass
        return await cb.answer()

    # ⛔ غير متاحة الآن
    if not _live_available():
        try:
            await cb.message.edit_text(
                _tt(lang, "live.unavailable",
                    "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                    "❕ Live chat is currently unavailable. Please try later.")
            )
        except Exception:
            try:
                await cb.message.answer(
                    _tt(lang, "live.unavailable",
                        "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                        "❕ Live chat is currently unavailable. Please try later.")
                )
            except Exception:
                pass
        return await cb.answer()

    # ✅ متاحة → اعرض شاشة التصنيفات
    try:
        await cb.message.edit_text(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
    except Exception:
        try:
            await cb.message.answer(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("live:cat:"))
async def cb_pick_category(cb: CallbackQuery):
    lang = _L(cb.from_user.id)

    # 🔒 حظر
    blocked, remain, _ = _block_status(cb.from_user.id)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "⛔ تم حظرك من الدردشة الحيّة.\nالوقت المتبقّي: {rem}",
                  "⛔ You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            try:
                await cb.message.answer(txt, reply_markup=_kb_blocked(lang))
            except Exception:
                pass
        return await cb.answer()

    # ⛔ غير متاحة
    if not _live_available():
        try:
            await cb.message.edit_text(
                _tt(lang, "live.unavailable",
                    "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                    "❕ Live chat is currently unavailable. Please try later.")
            )
        except Exception:
            try:
                await cb.message.answer(
                    _tt(lang, "live.unavailable",
                        "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                        "❕ Live chat is currently unavailable. Please try later.")
                )
            except Exception:
                pass
        return await cb.answer()

    # ✅ أعرض الشروط حسب التصنيف
    code = cb.data.split(":")[2]
    title = _cat_label(lang, code)
    text = f"🗂️ <b>{title}</b>\n{_cat_hint(lang, code)}\n\n{_terms_text(lang)}"
    try:
        await cb.message.edit_text(text, reply_markup=_kb_terms(lang, code), parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        try:
            await cb.message.answer(text, reply_markup=_kb_terms(lang, code), parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
    await cb.answer()


class LiveChat(StatesGroup):
    active = State()   # حالة المستخدم
    admin  = State()   # وضع الإدمن المعزول للرد
    block_wait = State()  # الإدمن ينتظر إدخال مدة الحظر المخصصة


@router.callback_query(F.data.startswith("live:start:"))
async def cb_start_live_after_terms(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = _L(uid)
    category = cb.data.split(":")[2]

    # 🔒 محظور → رسالة مع وقت متبقّي + زر تحديث
    blocked, remain, _ = _block_status(uid)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "⛔ تم حظرك من الدردشة الحيّة.\nالوقت المتبقّي: {rem}",
                  "⛔ You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            try:
                await cb.message.answer(txt, reply_markup=_kb_blocked(lang))
            except Exception:
                pass
        return await cb.answer()

    # ⛔ لا إدمن أونلاين أو الدعم مقفول
    if not _live_available():
        await cb.message.edit_text(
            _tt(lang, "live.unavailable",
                "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                "❕ Live chat is currently unavailable. Please try later.")
        )
        return await cb.answer()

    # ✅ افتح الطلب وادخل قائمة الانتظار
    sid  = f"{uid}:{int(_now())}"
    sess = {"status":"waiting","start_ts":_now(),"last_ts":_now(),"queue":[],"admin_id":None,"sid":sid,"category":category}
    _put_session(uid, sess)
    _ensure_history(sid, uid, None, sess["start_ts"])
    _update_history(sid, category=category)

    preview = f"[{_cat_label(lang, category)}] " + _tt(lang, "live.inbox.new", "طلب دردشة جديد", "New live chat request")
    _inbox_call("enqueue", "live", uid, preview)

    await state.set_state(LiveChat.active)
    await cb.message.edit_text(
        _tt(lang, "live.opened",
            "💬 تم فتح طلب دردشة.\nالرجاء الانتظار حتى ينضم الدعم…",
            "💬 Chat request opened.\nPlease wait for support to join…"),
        reply_markup=_kb_user_wait(lang)
    )
    await cb.answer()

    def _mk(alang: str):
        return _kb_admin_request(uid, alang)

    await _notify_admins_t(
        cb.bot,
        "live.admin.notify.request",
        "🆕 طلب دردشة حيّة\n• المستخدم: {name} @{username}\n• المعرّف: {uid}\n• الفئة: {cat}",
        "🆕 Live chat request\n• User: {name} @{username}\n• ID: {uid}\n• Category: {cat}",
        build_kb=_mk,
        name=cb.from_user.full_name,
        username=cb.from_user.username or "-",
        uid=uid,
        cat=_cat_label(_L(cb.from_user.id), category)
    )


def _kb_admin_request(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang, "live.admin.join", "✅ انضم للدردشة", "✅ Join chat"), callback_data=f"live:accept:{uid}"),
        InlineKeyboardButton(text=_tt(lang, "live.admin.decline", "🚫 رفض", "🚫 Decline"), callback_data=f"live:decline:{uid}")
    ]])

def _kb_admin_controls(uid: int, lang: str, sid: str) -> InlineKeyboardMarkup:
    psid = _sid_pack(sid)
    stars = [InlineKeyboardButton(text=f"{i}⭐", callback_data=f"live:arate:{uid}:{psid}:{i}") for i in range(1, 6)]
    tags  = [
        InlineKeyboardButton(text=_tt(lang,"live.tag.solved","✅ محلولة","✅ Solved"), callback_data=f"live:atag:{uid}:{psid}:solved"),
        InlineKeyboardButton(text=_tt(lang,"live.tag.follow","⏳ متابعة","⏳ Follow-up"), callback_data=f"live:atag:{uid}:{psid}:follow"),
        InlineKeyboardButton(text=_tt(lang,"live.tag.bug","🐞 عيب","🐞 Bug"), callback_data=f"live:atag:{uid}:{psid}:bug"),
    ]
    # أزرار الحظر السريعة
    blocks = [
        InlineKeyboardButton(text="🚫 1h",  callback_data=f"live:ablock:{uid}:{psid}:3600"),
        InlineKeyboardButton(text="🚫 24h", callback_data=f"live:ablock:{uid}:{psid}:86400"),
        InlineKeyboardButton(text="🚫 7d",  callback_data=f"live:ablock:{uid}:{psid}:604800"),
        InlineKeyboardButton(text="⛔ دائم", callback_data=f"live:ablock:{uid}:{psid}:0"),
    ]
    custom = InlineKeyboardButton(
        text=("⏱️ حظر مُخصص" if lang.startswith("ar") else "⏱️ Custom block"),
        callback_data=f"live:ablock_custom:{uid}:{psid}"
    )

    # زر رفع الحظر
    unban_btn = InlineKeyboardButton(
        text=("🔓 رفع الحظر" if lang.startswith("ar") else "🔓 Unban"),
        callback_data=f"live:aunblock:{uid}:{psid}"
    )

    return InlineKeyboardMarkup(inline_keyboard=[
        stars, tags,
        blocks,
        [custom],
        [unban_btn],  # ← هذا الصف الجديد
        [InlineKeyboardButton(text=_tt(lang,"live.btn.info","ℹ️ معلومات","ℹ️ Info"), callback_data=f"live:ainfo:{uid}:{psid}"),
         InlineKeyboardButton(text=_tt(lang,"live.btn.end.red","🔴 إنهاء الدردشة","🔴 End chat"), callback_data=f"live:end:{uid}:{psid}")]
    ])


def _set_support_enabled(flag: bool):
    cfg = _load(LIVE_CONFIG)
    cfg["enabled"] = bool(flag)
    _save(LIVE_CONFIG, cfg)

async def _close_all_sessions(bot):
    s = _load(SESSIONS_FILE)
    for suid, row in list(s.items()):
        try:
            uid = int(suid)
        except Exception:
            continue

        # علّم التذكرة في الصندوق
        _inbox_call("resolve", "live", uid, status="disabled")

        # بلّغ المستخدم
        try:
            await bot.send_message(
                uid,
                _tt(_L(uid),
                    "live.disabled.user",
                    "⛔ تم إيقاف الدردشة الحيّة مؤقتًا. جرّب لاحقًا.",
                    "⛔ Live chat is temporarily disabled. Please try later.")
            )
        except Exception:
            pass

        # بلّغ الإدمن الماسك الجلسة
        aid = row.get("admin_id")
        if aid:
            try:
                await bot.send_message(
                    aid,
                    _tt(_L(aid),
                        "live.disabled.admin",
                        "تم إنهاء الجلسة بسبب إيقاف الدردشة.",
                        "Session ended because live chat was disabled.")
                )
            except Exception:
                pass

        s.pop(suid, None)

    _save(SESSIONS_FILE, s)



@router.callback_query(F.data.startswith("live:ablock:"))
async def cb_admin_block_quick(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)

    uid, sid, seconds = _parse_uid_sid_stars(cb.data)  # استعملنا نفس البارسر: آخر جزء كأنه "نجوم" لكن هنا ثواني
    # ملاحظة: فوق استعملنا live:ablock:{uid}:{psid}:{seconds} لذلك الدالة تعمل تمام
    seconds = int(seconds)
    # تصعيد تلقائي (اختياري):
    strikes_after = _get_strikes(uid) + 1
    if seconds > 0:
        seconds = _auto_penalty_seconds(seconds, strikes_after)

    # دوّن الحظر
    _put_block(uid, seconds if seconds>0 else 10*365*24*3600, reason="quick")  # 0 = دائم → 10 سنوات مثلاً

    # أنهِ الجلسة لو موجودة
    sess = _get_session(uid)
    if sess:
        _del_session(uid)
    try:
        await state.clear()
    except Exception:
        pass

    # وسم + إشعارات
    _update_history(sid, tag="blocked")
    lang_user = _L(uid)
    period = "permanent" if seconds==0 else _format_period(seconds)
    try:
        await cb.bot.send_message(uid,
            _tt(lang_user, "live.blocked.msg",
                f"⛔ تم حظرك من الدردشة لمدة: {period}.",
                f"⛔ You have been blocked from live chat for: {period}."))
    except Exception:
        pass

    alang = _L(cb.from_user.id)
    try:
        await cb.message.edit_text(
            _tt(alang, "live.admin.blocked.ok",
                f"⛔ تم حظر المستخدم {uid} ({period}) وإنهاء الجلسة.",
                f"⛔ User {uid} blocked ({period}) and session ended."),
            reply_markup=None
        )
    except Exception:
        pass

    await _notify_admins_t(cb.bot,
        "live.admin.notify.block",
        "⛔ حظر الإدمن {admin_id} المستخدم {uid} لمدة {period}\nSID={sid}",
        "⛔ Admin {admin_id} blocked user {uid} for {period}\nSID={sid}",
        admin_id=cb.from_user.id, uid=uid, sid=sid, period=period)

    await cb.answer("Blocked")

@router.callback_query(F.data.startswith("live:aunblock:"))
async def cb_admin_unblock(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)

    # نفس تنسيق live:aunblock:{uid}:{psid} → نستخدم البارسر العام
    uid, sid = _parse_uid_sid(cb.data)

    # لو المستخدم غير محظور، نخبر الإدمن بشكل ودّي
    was_blocked, _, _ = _block_status(uid)
    _clear_block(uid)

    alang = _L(cb.from_user.id)
    msg_admin = ("🔓 تم رفع الحظر عن المستخدم {uid}."
                 if alang.startswith("ar") else
                 "🔓 Unban completed for user {uid}.")
    try:
        await cb.message.edit_text(msg_admin.format(uid=uid),
                                   reply_markup=_kb_admin_controls(uid, alang, sid))
    except Exception:
        pass

    # أخبر المستخدم أنه تم رفع الحظر
    try:
        await cb.bot.send_message(
            uid,
            _tt(_L(uid),
                "live.unblocked",
                "✅ تم رفع الحظر. يمكنك فتح دردشة جديدة من «الدعم».",
                "✅ Your ban was lifted. You can start a new chat from Support.")
        )
    except Exception:
        pass

    # إشعار لباقي الإدمنز الأونلاين
    await _notify_admins_t(
        cb.bot,
        "live.admin.notify.unblock",
        "🔓 رفع الإدمن {admin_id} الحظر عن المستخدم {uid} | SID={sid}",
        "🔓 Admin {admin_id} unblocked user {uid} | SID={sid}",
        admin_id=cb.from_user.id, uid=uid, sid=sid
    )

    # رد قصير لواجهة الزر
    await cb.answer("Unblocked" if not alang.startswith("ar") else "تم رفع الحظر")

@router.message(Command("unban"))
async def cmd_unban(m: Message):
    if not _is_admin(m.from_user.id):
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        return await m.reply("استخدم: /unban <uid>\nExample: /unban 123456789")
    uid = int(parts[1])
    was_blocked, _, _ = _block_status(uid)
    _clear_block(uid)
    await m.reply(("🔓 تم رفع الحظر عن " if _L(m.from_user.id).startswith("ar") else "🔓 Unbanned ") + str(uid))
    try:
        await m.bot.send_message(uid,
            _tt(_L(uid),
                "live.unblocked",
                "✅ تم رفع الحظر. يمكنك فتح دردشة جديدة من «الدعم».",
                "✅ Your ban was lifted. You can start a new chat from Support."))
    except Exception:
        pass


@router.callback_query(F.data.startswith("live:ablock_custom:"))
async def cb_admin_block_custom_open(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    # خزّن الهدف في FSM ثم اطلب من الإدمن إدخال الثواني|سبب (السبب اختياري)
    parts = cb.data.split(":")
    uid = int(parts[2]); sid = _sid_unpack(parts[3])
    await state.update_data(block_target_uid=uid, block_target_sid=sid)
    await state.set_state(LiveChat.block_wait)
    await cb.message.answer("⏱️ أرسل مدة الحظر بالثواني، ويمكن إضافة سبب بعد فاصلة عمودية:\nمثال: `3600|سبام`\nExample: `86400|spam`", parse_mode="Markdown")
    await cb.answer()

@router.message(StateFilter(LiveChat.block_wait))
async def admin_block_custom_apply(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    text = (m.text or "").strip()
    if not text:
        return await m.reply("أرسل الثواني أو `seconds|reason`.")
    try:
        if "|" in text:
            s, reason = text.split("|", 1)
            seconds = int(s.strip())
            reason = reason.strip()
        else:
            seconds = int(text)
            reason = ""
    except Exception:
        return await m.reply("تنسيق غير صحيح. مثال: `3600|سبام`", parse_mode="Markdown")

    data = await state.get_data()
    uid = int(data.get("block_target_uid"))
    sid = data.get("block_target_sid")

    # تصعيد تلقائي (اختياري)
    strikes_after = _get_strikes(uid) + 1
    if seconds > 0:
        seconds = _auto_penalty_seconds(seconds, strikes_after)

    _put_block(uid, seconds if seconds>0 else 10*365*24*3600, reason=reason or "custom")

    # إنهِ أي جلسة
    if _get_session(uid):
        _del_session(uid)

    await state.clear()

    period = "permanent" if seconds==0 else _format_period(seconds)
    try:
        await m.bot.send_message(uid,
            _tt(_L(uid), "live.blocked.msg",
                f"⛔ تم حظرك من الدردشة لمدة: {period}.",
                f"⛔ You have been blocked from live chat for: {period}."))
    except Exception:
        pass

    _update_history(sid, tag="blocked")
    await m.reply(f"تم الحظر: UID={uid} | {period} | reason={reason or '-'}")
    await _notify_admins_t(m.bot,
        "live.admin.notify.block",
        "⛔ حظر الإدمن {admin_id} المستخدم {uid} لمدة {period}\nSID={sid}\nسبب: {reason}",
        "⛔ Admin {admin_id} blocked user {uid} for {period}\nSID={sid}\nReason: {reason}",
        admin_id=m.from_user.id, uid=uid, sid=sid, period=period, reason=(reason or "-"))

@router.callback_query(F.data == "live:cancel")
async def cb_user_cancel(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id; lang = _L(uid)
    if _get_session(uid): _del_session(uid)
    await state.clear()
    _inbox_call("resolve", "live", uid, status="canceled")
    await cb.message.edit_text(_tt(lang,"live.canceled","تم إلغاء طلب الدردشة.","Chat request canceled."))
    await _notify_admins_t(cb.bot,"live.admin.notify.user_canceled","⚪️ ألغى المستخدم طلب الدردشة (UID:{uid})","⚪️ Live chat canceled by user (UID:{uid})", uid=uid)
    await cb.answer()

@router.callback_query(F.data.startswith("live:accept:"))
async def cb_admin_accept(cb: CallbackQuery, state: FSMContext):
    if not _support_enabled():
        return await cb.answer("Live chat is disabled.", show_alert=True)
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid  = int(cb.data.split(":")[-1])
    user_lang = _L(uid)
    sess = _get_session(uid)
    if not sess or _expired(sess):
        _del_session(uid)
        return await cb.answer(_tt(user_lang,"live.expired","انتهت/غير موجودة.","Expired/Not found"), show_alert=True)

    sess["status"] = "active"; sess["admin_id"] = cb.from_user.id
    _put_session(uid, sess)
    _set_admin_active(cb.from_user.id, uid)
    _ensure_history(sess["sid"], uid, cb.from_user.id, sess["start_ts"])
    _touch_admin(cb.from_user.id)

    # ✅ أدخل الإدمن في وضع الرد المعزول
    await state.set_state(LiveChat.admin)

    # صندوق الوارد: وسم كـ "قيد المعالجة"
    _inbox_call("assign", "live", uid, admin_id=cb.from_user.id)

    try:
        await cb.bot.send_message(
            uid,
            _tt(user_lang,"live.joined.user","✅ انضمّ أحد أعضاء فريق الدعم إلى الدردشة. يمكنك التحدّث الآن.","✅ A support team member has joined. You can talk now."),
            reply_markup=_kb_user_actions(user_lang, sess["sid"])
        )
    except Exception:
        pass

    relays = _load(RELAYS_FILE); delivered = False
    for mid in (sess.get("queue") or []):
        for tgt in _targets():
            try:
                cp = await cb.bot.copy_message(
                    chat_id=tgt, from_chat_id=uid, message_id=mid,
                    reply_markup=_kb_admin_controls(uid, _L(tgt), sess["sid"])
                )
                relays[f"{tgt}:{cp.message_id}"] = uid
                delivered = True
            except Exception as e1:
                try:
                    fwd = await cb.bot.forward_message(chat_id=tgt, from_chat_id=uid, message_id=mid)
                    relays[f"{tgt}:{fwd.message_id}"] = uid
                    delivered = True
                except Exception as e2:
                    log.warning("deliver backlog to %s failed: %s | %s", tgt, e1, e2)
    if delivered: _save(RELAYS_FILE, relays)

    admin_lang = _L(cb.from_user.id)
    cat = sess.get("category","-")
    try:
        await cb.message.edit_text(
            _tt(admin_lang, "live.admin.joined.banner","🟢 انضممت للدردشة مع المستخدم {uid}. الفئة: {cat}",
                "🟢 Joined chat with user {uid}. Category: {cat}").format(uid=uid, cat=_cat_label(admin_lang, cat)),
            reply_markup=_kb_admin_controls(uid, admin_lang, sess["sid"])
        )
    except Exception:
        pass

    await _notify_admins_t(cb.bot,
        "live.admin.notify.joined",
        "🟢 انضم الإدمن {admin_id} للدردشة\nSID={sid}\nUID={uid}\nالفئة: {cat}",
        "🟢 Admin {admin_id} joined chat\nSID={sid}\nUID={uid}\nCategory: {cat}",
        admin_id=cb.from_user.id, sid=sess["sid"], uid=uid, cat=_cat_label("ar" if admin_lang=="ar" else "en", cat)
    )
    await cb.answer("Joined")

@router.callback_query(F.data.startswith("live:decline:"))
async def cb_admin_decline(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid  = int(cb.data.split(":")[-1]); lang = _L(uid)
    _touch_admin(cb.from_user.id)
    if _get_session(uid): _del_session(uid)
    _inbox_call("resolve", "live", uid, status="declined")
    try:
        await cb.bot.send_message(uid, _tt(lang,"live.declined","عذرًا، لا يتوفر دعم الآن. حاول لاحقًا.","Sorry, support is unavailable now. Please try later."))
    except Exception:
        pass
    # خروج من وضع الإدمن لو كان بداخله
    try: await state.clear()
    except Exception: pass
    await _notify_admins_t(cb.bot,"live.admin.notify.declined","🚫 تم رفض الدردشة للمستخدم {uid} من الإدمن {admin_id}","🚫 Chat declined for user {uid} by admin {admin_id}", uid=uid, admin_id=cb.from_user.id)
    await cb.answer("Declined")

@router.callback_query(F.data == "live:end_self")
async def cb_end_self(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id; lang = _L(uid)
    sess = _get_session(uid); sid = sess.get("sid") if sess else None
    admin_id = (sess or {}).get("admin_id")
    if sess: _del_session(uid)
    await state.clear()
    _inbox_call("resolve", "live", uid, status="ended_by_user")
    try:
        await cb.message.edit_text(_tt(lang,"live.ended.user","تم إنهاء الدردشة. شكرًا لك.","Chat ended. Thank you."))
    except Exception:
        pass
    if sid:
        _finish_history(sid)
        await _notify_admins_t(cb.bot,"live.admin.notify.ended_by_user","🔴 أنهى المستخدم الدردشة | SID={sid} | UID={uid}","🔴 Chat ended by user | SID={sid} | UID={uid}", sid=sid, uid=uid)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"live:urate:{_sid_pack(sid)}:{i}") for i in range(1,6)]])
        try:
            await cb.bot.send_message(uid, _tt(lang,"live.rate.ask","قيّم تجربتك مع الدعم:","Rate your support experience:"), reply_markup=kb)
        except Exception:
            pass
    # نظّف ربط الإدمن بالمستخدم
    if admin_id: _clear_admin_active(admin_id)
    await cb.answer()

@router.callback_query(F.data.startswith("live:end:"))
async def cb_admin_end(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid = _parse_uid_sid(cb.data)
    user_lang = _L(uid)
    sess  = _get_session(uid)
    if sess: _del_session(uid)
    _inbox_call("resolve", "live", uid, status="ended_by_admin")
    try:
        await cb.bot.send_message(uid, _tt(user_lang,"live.ended.support","تم إنهاء الدردشة من جهة الدعم.","Chat has been ended by support."))
    except Exception:
        pass
    summary = _finish_history(sid) or {}
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"live:urate:{_sid_pack(sid)}:{i}") for i in range(1,6)]])
    try:
        await cb.bot.send_message(uid, _tt(user_lang,"live.rate.ask","قيّم تجربتك مع الدعم:","Rate your support experience:"), reply_markup=kb)
    except Exception:
        pass
    dur = int(summary.get("duration", 0)); tag = summary.get("tag", "-")
    await _notify_admins_t(cb.bot,"live.admin.notify.ended_by_admin","🔴 أنهى الإدمن {admin_id} الدردشة\n• SID: {sid}\n• UID: {uid}\n• المدة: {dur}s\n• الوسم: {tag}","🔴 Chat ended by admin {admin_id}\n• SID: {sid}\n• UID: {uid}\n• Duration: {dur}s\n• Tag: {tag}", admin_id=cb.from_user.id, sid=(sid or "-"), uid=uid, dur=dur, tag=tag)
    # خروج من وضع الإدمن + فك الربط
    try: await state.clear()
    except Exception: pass
    _clear_admin_active(cb.from_user.id)
    await cb.answer("Ended")

@router.callback_query(F.data.startswith("live:arate:"))
async def cb_admin_rate(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid, stars = _parse_uid_sid_stars(cb.data)
    _set_admin_rating(sid, int(stars))
    await cb.answer(f"Rated {stars}⭐")
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_admin_controls(int(uid), _L(cb.from_user.id), sid))
    except Exception:
        pass
    await _notify_admins_t(cb.bot,"live.admin.notify.admin_rating","🛠️ قيّم الإدمن {admin_id} جلسة {sid}: {stars}⭐ (UID {uid})","🛠️ Admin {admin_id} rated chat {sid}: {stars}⭐ (UID {uid})", admin_id=cb.from_user.id, sid=sid, stars=stars, uid=uid)

@router.callback_query(F.data.startswith("live:atag:"))
async def cb_admin_tag(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid, tag = _parse_uid_sid_tag(cb.data)
    h  = _load(HISTORY_FILE).get(sid) or {"uid": uid}
    h["tag"] = tag; _update_history(sid, **h)
    await cb.answer("Tagged")
    await _notify_admins_t(cb.bot,"live.admin.notify.tag","🏷️ تم تعيين وسم: {tag} | SID={sid} | UID={uid}","🏷️ Tag set: {tag} | SID: {sid} | UID: {uid}", tag=tag, sid=sid, uid=uid)

@router.callback_query(F.data.startswith("live:ainfo:"))
async def cb_admin_info(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid = _parse_uid_sid(cb.data)
    h  = _load(HISTORY_FILE).get(sid) or {}
    dur = int(max(0, (_now()-float(h.get("start_ts",_now()))) if not h.get("end_ts") else h.get("duration",0)))
    rr  = _load(RATINGS_FILE).get(sid) or {}
    tag = h.get("tag","-"); cat = h.get("category","-")
    alang = _L(cb.from_user.id)
    text = _tt(alang, "live.admin.info.text",
        "ℹ️ <b>معلومات</b>\n• UID: <code>{uid}</code>\n• SID: <code>{sid}</code>\n• المدة: <code>{dur}s</code>\n• الوسم: <code>{tag}</code>\n• الفئة: <code>{cat}</code>\n• التقييمات → إدمن: <code>{ar}</code> | مستخدم: <code>{ur}</code>",
        "ℹ️ <b>Info</b>\n• UID: <code>{uid}</code>\n• SID: <code>{sid}</code>\n• Duration: <code>{dur}s</code>\n• Tag: <code>{tag}</code>\n• Category: <code>{cat}</code>\n• Ratings → admin: <code>{ar}</code> | user: <code>{ur}</code>"
    ).format(uid=uid, sid=sid, dur=dur, tag=tag, cat=cat, ar=rr.get('admin_rating','-'), ur=rr.get('user_rating','-'))
    try: await cb.message.answer(text, parse_mode="HTML")
    except Exception: pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:rateopen:"))
async def cb_rate_open(cb: CallbackQuery):
    psid = cb.data.split(":")[2]
    lang = _L(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_user_rate_choices(psid, lang))
    except Exception:
        pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:rateclose:"))
async def cb_rate_close(cb: CallbackQuery):
    sid = _sid_unpack(cb.data.split(":")[2])
    lang = _L(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_user_actions(lang, sid))
    except Exception:
        pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:urate:"))
async def cb_user_rate(cb: CallbackQuery):
    parts = cb.data.split(":")
    sid = _sid_unpack(":".join(parts[2:-1]))
    stars = int(parts[-1])
    _set_user_rating(sid, stars)
    lang = _L(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_user_actions(lang, sid))
    except Exception:
        pass
    await cb.answer("Thanks!")
    await _notify_admins_t(cb.bot,"live.admin.notify.user_rating","⭐ تقييم المستخدم للجلسة {sid}: {stars}⭐","⭐ User rating for chat {sid}: {stars}⭐", sid=sid, stars=stars)

@router.message(StateFilter(LiveChat.active), ~F.text.startswith("/"), ~F.caption.startswith("/"))
async def user_live_message(m: Message, state: FSMContext):
    uid = m.from_user.id
    lang = _L(uid)

    # ✋ قاطع عام: إذا الدعم مقفول عالميًا، نقفل الجلسة (إن وجدت) ونبلغ المستخدم
    if not _support_enabled():
        if _get_session(uid):
            _del_session(uid)
            await state.clear()
        return await m.answer(
            _tt(lang, "live.unavailable",
                "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                "❕ Live chat is currently unavailable. Please try later.")
        )

    # محظور؟
    if _blocked(uid):
        return

    # لا توجد جلسة؟
    sess = _get_session(uid)
    if not sess:
        return

    # منتهية؟
    if _expired(sess):
        _del_session(uid)
        await state.clear()
        _inbox_call("resolve", "live", uid, status="expired")
        return await m.answer(
            _tt(lang, "live.expired.msg",
                "⏳ انتهت الجلسة. ابدأ واحدة جديدة من (الدعم).",
                "⏳ Session expired. Start a new one from Support.")
        )

    _touch(uid)

    # لا يزال في الانتظار → خزّن الرسائل مؤقتًا
    if sess.get("status") == "waiting":
        q = list(sess.get("queue") or [])
        q.append(m.message_id)
        sess["queue"] = q
        _put_session(uid, sess)

        preview = (m.caption or m.text or f"({m.content_type})")[:200]
        _inbox_call("update", "live", uid, preview)

        return await m.answer(
            _tt(lang, "live.queue.received",
                "✅ تم استلام رسالتك. سنرد بعد انضمام الدعم.\n(لا زلت في قائمة الانتظار)",
                "✅ We got your message. We'll reply once support joins.\n(You are still in the queue)"),
            reply_markup=_kb_user_wait(lang)
        )

    # نشطة → Relay إلى الإدمنز
    relays = _load(RELAYS_FILE)
    delivered = False
    for tgt in _targets():
        try:
            cp = await m.bot.copy_message(
                chat_id=tgt,
                from_chat_id=m.chat.id,
                message_id=m.message_id,
                reply_markup=_kb_admin_controls(uid, _L(tgt), sess["sid"])
            )
            relays[f"{tgt}:{cp.message_id}"] = uid
            delivered = True
        except Exception as e1:
            try:
                fwd = await m.bot.forward_message(
                    chat_id=tgt,
                    from_chat_id=m.chat.id,
                    message_id=m.message_id
                )
                relays[f"{tgt}:{fwd.message_id}"] = uid
                delivered = True
            except Exception as e2:
                if m.text:
                    msg = await m.bot.send_message(tgt, f"👤 #{uid}:\n{m.text}")
                    relays[f"{tgt}:{msg.message_id}"] = uid
                    delivered = True
                else:
                    log.warning("copy/forward user->%s failed: %s | %s", tgt, e1, e2)

    if delivered:
        _save(RELAYS_FILE, relays)
        await m.answer(
            _tt(lang, "live.tip.end",
                "للإنهاء أو التقييم استخدم الأزرار أدناه.",
                "Use the buttons below to end or rate."),
            reply_markup=_kb_user_actions(lang, sess["sid"])
        )


# 1) الإدمن وهو يردّ Reply على رسالة المستخدم (يسمح دائمًا)
@router.message(F.reply_to_message)
async def admin_reply_in_private(m: Message):
    if not _is_admin(m.from_user.id):
        return
    if m.text and m.text.startswith('/'):
        return
    delivered = await _relay_admin_reply(m)
    if delivered:
        return

# 2) الإدمن وهو في وضع LiveChat.admin → أي رسالة ترسل للمستخدم النشط
@router.message(StateFilter(LiveChat.admin))
async def admin_message_in_private(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return

    # خروج من وضع الرد المعزول
    if m.text in {"/exit_admin", "/exit", "/leave"}:
        await state.clear()
        return await m.reply("تم الخروج من وضع الردّ ✅")

    # حالة الإدمن الشخصية (لا تؤثر على القاطع العالمي)
    if m.text == "/online":
        _set_admin_online(m.from_user.id, True)
        return await m.reply("You are ONLINE ✅")

    if m.text == "/offline":
        _set_admin_online(m.from_user.id, False)
        return await m.reply("You are OFFLINE ⛔")

    # لو كان ردًا على رسالة، سيعالجه هاندلر الرد
    if m.reply_to_message:
        return

    # إرسال إلى الجلسة النشطة المرتبطة بهذا الإدمن
    delivered = await _send_to_active(m)
    if not delivered:
        await m.reply(
            "⚠️ لا توجد جلسة نشطة مرتبطة بك.\n"
            "استخدم زر ✅ انضم للدردشة، أو اخرج بـ /exit_admin."
        )


# --- Helpers to deliver admin messages ---
async def _relay_admin_reply(m: Message) -> bool:
    _touch_admin(m.from_user.id)
    rel = _load(RELAYS_FILE)
    ref = m.reply_to_message.message_id if m.reply_to_message else None
    key = f"{m.chat.id}:{ref}" if ref is not None else None
    uid = rel.get(key) if key else None
    if not uid:
        return False

    s = _get_session(int(uid))
    if not s or s.get("status") != "active":
        try:
            await m.reply("⚠️ Session not active.")
        except Exception:
            pass
        return False

    try:
        await m.bot.copy_message(
            chat_id=int(uid),
            from_chat_id=m.chat.id,
            message_id=m.message_id,
            reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
        )
        return True
    except Exception as e:
        log.warning("copy admin->user failed: %s", e)
        try:
            if m.text:
                await m.bot.send_message(
                    int(uid),
                    m.text,
                    reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
                )
                return True
        except Exception as e2:
            log.warning("send admin->user failed: %s", e2)
        return False

async def _send_to_active(m: Message) -> bool:
    _touch_admin(m.from_user.id)
    aid = m.from_user.id
    uid = _get_admin_active(aid)
    if not uid:
        try:
            await m.reply("⚠️ لا توجد جلسة مفعّلة لك الآن.\n"
                          "➜ إمّا اضغط «✅ انضم للدردشة»، أو **رد** (Reply) على إحدى رسائل المستخدم.")
        except Exception:
            pass
        return False

    s = _get_session(int(uid))
    if not s or s.get("status") != "active":
        try:
            await m.reply("⚠️ الجلسة ليست نشطة.\n"
                          "إنتهت/أُغلقت. اطلب من المستخدم فتح طلب جديد أو انضم ثانية.")
        except Exception:
            pass
        return False

    # حاول النسخ أولاً، ثم فولباك لنص فقط
    try:
        await m.bot.copy_message(
            chat_id=int(uid),
            from_chat_id=m.chat.id,
            message_id=m.message_id,
            reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
        )
        return True
    except Exception as e:
        log.warning("copy admin(no-reply)->user failed: %s", e)
        try:
            if m.text:
                await m.bot.send_message(
                    int(uid),
                    m.text,
                    reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
                )
                return True
            else:
                await m.reply("⚠️ لم أستطع إعادة توجيه هذا النوع من الرسائل.\n"
                              "جرّب إرسال نص، أو **رد** على رسالة المستخدم لإعادة التوجيه التلقائي.")
        except Exception as e2:
            log.warning("send admin(no-reply)->user failed: %s", e2)
        return False

# ===== أوامر حالة أونلاين الإدمن =====
@router.message(Command("live_off"))
async def cmd_live_off(m: Message):
    if not _is_admin(m.from_user.id): return
    _set_support_enabled(False)
    await _close_all_sessions(m.bot)
    await m.reply("🔕 Live chat disabled globally. All sessions closed.")

@router.message(Command("live_on"))
async def cmd_live_on(m: Message):
    if not _is_admin(m.from_user.id): return
    _set_support_enabled(True)
    await m.reply("🔔 Live chat enabled globally.")

