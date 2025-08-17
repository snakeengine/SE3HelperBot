# handlers/promoter.py
from __future__ import annotations

import os, json, time, logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from lang import t, get_user_lang

router = Router(name="promoter")
log = logging.getLogger(__name__)

# ===== ملفات وإعدادات =====
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = DATA_DIR / "promoters.json"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

_DEFAULT_DAILY_LIMIT = 5  # حد افتراضي إذا لم يوجد في settings

# ===== I/O =====
def _load_store() -> Dict[str, Any]:
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"users": {}, "settings": {"daily_limit": _DEFAULT_DAILY_LIMIT}}

def _save_store(d: Dict[str, Any]) -> None:
    try:
        STORE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"[promoters] save failed: {e}")

def _get_daily_limit(d: Dict[str, Any] | None = None) -> int:
    """يقرأ الحد اليومي من التخزين (مع افتراضي)."""
    if d is None:
        d = _load_store()
    try:
        n = int(d.get("settings", {}).get("daily_limit", _DEFAULT_DAILY_LIMIT))
        return max(1, min(20, n))
    except Exception:
        return _DEFAULT_DAILY_LIMIT

def _now() -> int:
    return int(time.time())

# ===== API لـ start.py =====
def is_promoter(uid: int) -> bool:
    d = _load_store()
    u = d["users"].get(str(uid))
    return bool(u and u.get("status") == "approved")

# ===== ترجمة مبسطة =====
def L(uid: int) -> str:
    return get_user_lang(uid) or "en"

def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip(): return s
    except Exception:
        pass
    return fallback

# ===== حسابات حد/تبريد/حظر =====
def _attempts_last_24h(u: Dict[str, Any]) -> int:
    now = _now()
    attempts: List[int] = u.get("attempts", [])
    return sum(1 for ts in attempts if now - ts < 24*3600)

def _push_attempt(u: Dict[str, Any]) -> None:
    attempts: List[int] = u.setdefault("attempts", [])
    attempts.append(_now())
    cutoff = _now() - 24*3600
    u["attempts"] = [ts for ts in attempts if ts >= cutoff]

def _is_on_until(field: str, u: Dict[str, Any]) -> int:
    until = int(u.get(field, 0) or 0)
    return max(0, until - _now())

def _format_duration(sec: int, lang: str) -> str:
    m = sec // 60
    h = m // 60
    d = h // 24
    if d >= 1: return f"{d} " + _tf(lang, "prom.time.days", "يوم")
    if h >= 1: return f"{h} " + _tf(lang, "prom.time.hours", "ساعة")
    if m >= 1: return f"{m} " + _tf(lang, "prom.time.minutes", "دقيقة")
    return f"{sec} " + _tf(lang, "prom.time.seconds", "ثانية")

def _next_reject_ban_secs(rejects_count: int) -> int:
    if rejects_count <= 0: return 0
    if rejects_count == 1: return 24*3600
    if rejects_count == 2: return 7*24*3600
    return 30*24*3600

# ===== واجهة عامة =====
def prom_info_text(lang: str) -> str:
    return (
        f"📣 <b>{_tf(lang,'prom.title','برنامج المروّجين')}</b>\n\n"
        f"{_tf(lang,'prom.terms.lead','الشروط للانضمام:')}\n"
        f"• {_tf(lang,'prom.terms.1','لديك 5,000 متابع أو أكثر على منصّات التواصل.')}\n"
        f"• {_tf(lang,'prom.terms.2','الالتزام بالمنصّة ونشر/بث يومي أو رفع مقاطع عنها.')}\n"
        f"• {_tf(lang,'prom.terms.3','جدّية والتزام بالشروط.')}\n"
        f"• {_tf(lang,'prom.terms.4','إذا استوفيت الشروط سنمنحك اشتراكًا مجانيًا في التطبيق.')}\n\n"
        f"{_tf(lang,'prom.terms.ready_q','هل أنت جاهز للبدء؟')}"
    )

def prom_info_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=_tf(lang, "prom.btn.ready", "أنا جاهز ✅"), callback_data="prom:apply")
    b.button(text=_tf(lang, "prom.btn.cancel", "إلغاء"), callback_data="back_to_menu")
    b.adjust(2)
    return b.as_markup()

def _admin_review_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.approve","✅ موافقة"), callback_data=f"prom:adm:approve:{uid}"),
            InlineKeyboardButton(text=_tf(lang,"prom.adm.reject","❌ رفض"), callback_data=f"prom:adm:reject:{uid}"),
        ],
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.more","✍️ معلومات إضافية"), callback_data=f"prom:adm:more:{uid}"),
            InlineKeyboardButton(text=_tf(lang,"prom.adm.hold","⏸️ تعليق"), callback_data=f"prom:adm:hold:{uid}"),
        ],
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.ban","🚫 حظر"), callback_data=f"prom:adm:ban:{uid}"),
            InlineKeyboardButton(text=_tf(lang,"prom.adm.unban","♻️ إزالة الحظر"), callback_data=f"prom:adm:unban:{uid}"),
        ],
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.delete","🗑 حذف الطلب"), callback_data=f"prom:adm:delete:{uid}"),
        ],
    ])

def _ban_menu_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_tf(lang, "prom.adm.ban1d", "حظر 1 يوم"), callback_data=f"prom:adm:ban_do:{uid}:1"),
            InlineKeyboardButton(text=_tf(lang, "prom.adm.ban7d", "حظر 7 أيام"), callback_data=f"prom:adm:ban_do:{uid}:7"),
            InlineKeyboardButton(text=_tf(lang, "prom.adm.ban30d", "حظر 30 يوم"), callback_data=f"prom:adm:ban_do:{uid}:30"),
        ],
        [InlineKeyboardButton(text=_tf(lang,"prom.adm.back","⬅️ رجوع"), callback_data=f"prom:adm:back:{uid}")]
    ])

# ===== الحالات =====
class PromApply(StatesGroup):
    name = State()
    links = State()
    tg    = State()
    proof = State()
    more  = State()

# ===== فحوصات قبل التقديم =====
def _precheck_message(u: Dict[str, Any], lang: str) -> Tuple[bool, str | None]:
    # موافَق = لديه لوحة
    if u.get("status") == "approved":
        return False, _tf(lang, "prom.err.already_approved", "أنت مروّج مُعتمد بالفعل. استخدم لوحة المروّجين.")
    if u.get("status") in {"pending", "on_hold", "more_info"}:
        return False, _tf(lang, "prom.err.already_pending", "لديك طلب سابق قيد المعالجة. انتظر قرار الإدارة أو أرسل المعلومات المطلوبة.")

    # حظر مباشر
    ban_left = _is_on_until("banned_until", u)
    if ban_left > 0:
        return False, _tf(lang, "prom.err.banned", "تم حظرك مؤقتًا. تبقّى: ") + _format_duration(ban_left, lang)

    # تبريد/حد
    cd_left = _is_on_until("cooldown_until", u)
    if cd_left > 0:
        return False, _tf(lang, "prom.err.cooldown", "لا يمكنك التقديم الآن. تبقّى: ") + _format_duration(cd_left, lang)

    # حد يومي ديناميكي
    daily_limit = _get_daily_limit()
    if _attempts_last_24h(u) >= daily_limit:
        u["cooldown_until"] = _now() + 24*3600
        return False, _tf(lang, "prom.err.daily_limit", f"وصلت للحد اليومي ({daily_limit})، تم إيقاف التقديم ليوم واحد.")

    return True, None

# ===== فتح الشروط =====
@router.callback_query(F.data == "prom:info")
async def prom_info(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    await cb.message.answer(prom_info_text(lang), reply_markup=prom_info_kb(lang), parse_mode=ParseMode.HTML)
    await cb.answer()

# ===== بدء التقديم =====
@router.callback_query(F.data == "prom:apply")
async def prom_apply_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    store = _load_store()
    u = store["users"].setdefault(str(cb.from_user.id), {
        "status": "none",
        "rejects": 0,
        "attempts": [],
        "cooldown_until": 0,
        "banned_until": 0,
    })

    ok, msg = _precheck_message(u, lang)
    if not ok:
        _save_store(store)
        return await cb.message.answer(msg)

    _save_store(store)
    await state.set_state(PromApply.name)
    await cb.message.answer(_tf(lang, "prom.ask.name", "أرسل اسمك كما يظهر على قناتك/منصّتك:"))
    await cb.answer()

@router.message(PromApply.name, F.text.len() >= 2)
async def prom_save_name(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    await state.update_data(name=m.text.strip())
    await state.set_state(PromApply.links)
    await m.answer(_tf(lang, "prom.ask.links", "أرسل روابط حساباتك (تيك توك/يوتيوب/فيسبوك…)، كل رابط بسطر منفصل."))

@router.message(PromApply.links, F.text)
async def prom_save_links(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    links = [s.strip() for s in (m.text or "").splitlines() if s.strip()]
    if not links:
        return await m.answer(_tf(lang, "prom.err.links", "أرسل رابطًا واحدًا على الأقل."))
    await state.update_data(links=links)
    await state.set_state(PromApply.tg)
    # نعرض معرفه الحقيقي للمقارنة
    real = ("@" + m.from_user.username) if m.from_user.username else _tf(lang, "prom.tg.no_username", "لا يوجد @username في حسابك.")
    await m.answer(_tf(lang, "prom.ask.tg", "أرسل معرّف تيليجرام الخاص بك (مثل @username).") + f"\n{_tf(lang,'prom.tg.yours','معرّفك الحالي:')} {real}")

@router.message(PromApply.tg, F.text.regexp(r"^@?[A-Za-z0-9_]{5,}$"))
async def prom_save_tg(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    declared = m.text.strip()
    if not declared.startswith("@"):
        declared = "@" + declared
    real = ("@" + m.from_user.username) if m.from_user.username else None
    match = (real is not None) and (real.lower() == declared.lower())

    await state.update_data(tg_declared=declared, tg_real=real, tg_match=match)
    await state.set_state(PromApply.proof)
    if match:
        await m.answer(_tf(lang, "prom.ask.proof", "أرسل صورة أو فيديو قصير يثبت أنك صاحب المحتوى."))
    else:
        await m.answer(_tf(lang, "prom.tg.mismatch", "تحذير: المعرّف الذي أرسلته لا يطابق معرف حسابك الحالي. يمكنك المتابعة لكن سيظهر للأدمن كتحذير."))

@router.message(PromApply.tg)
async def prom_save_tg_invalid(m: Message):
    lang = L(m.from_user.id)
    await m.answer(_tf(lang, "prom.err.tg", "المعرّف غير صالح. مثال: @MyChannel"))

@router.message(PromApply.proof, F.photo | F.video)
async def prom_save_proof(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    data = await state.get_data()
    photo_ids: List[str] = [p.file_id for p in m.photo] if m.photo else []
    video_ids: List[str] = [m.video.file_id] if m.video else []

    store = _load_store()
    uid = str(m.from_user.id)
    u = store["users"].setdefault(uid, {"status":"none","rejects":0,"attempts":[],"cooldown_until":0,"banned_until":0})

    ok, msg = _precheck_message(u, lang)
    if not ok:
        _save_store(store)
        return await m.answer(msg)

    _push_attempt(u)
    store["users"][uid] = {
        **u,
        "status": "pending",
        "submitted_at": _now(),
        "name": data.get("name"),
        "links": data.get("links", []),
        "telegram": {
            "declared": data.get("tg_declared"),
            "real": data.get("tg_real"),
            "match": bool(data.get("tg_match")),
        },
        "proof": {"photos": photo_ids, "videos": video_ids},
    }
    _save_store(store)
    await state.clear()

    # إشعار الأدمنين
    tg_decl = store["users"][uid]["telegram"]["declared"]
    tg_real = store["users"][uid]["telegram"]["real"]
    tg_match = store["users"][uid]["telegram"]["match"]

    tg_line = f"✈️ تيليجرام: "
    if tg_real:
        tg_line += f"<a href='https://t.me/{tg_real[1:]}'>{tg_real}</a> "
    tg_line += f"(declared: <code>{tg_decl}</code>) "
    tg_line += "✅" if tg_match else "❗️"

    attempts_now = _attempts_last_24h(store["users"][uid])
    daily_limit = _get_daily_limit(store)

    txt = (
        f"🆕 <b>طلب مروّج جديد</b>\n"
        f"👤 ID: <code>{uid}</code> — <a href='tg://user?id={uid}'>[open chat]</a>\n"
        f"🔥 الاسم: <code>{store['users'][uid]['name']}</code>\n"
        f"🔗 الروابط:\n" + ("\n".join(f"• {x}" for x in store['users'][uid]['links']) or "—") + "\n" +
        tg_line + "\n"
        f"🧮 Attempts(24h): <code>{attempts_now}/{daily_limit}</code>\n"
    )

    for admin_id in ADMIN_IDS:
        try:
            await m.bot.send_message(admin_id, txt, reply_markup=_admin_review_kb(int(uid), lang),
                                     parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            if photo_ids:
                await m.bot.send_photo(admin_id, photo_ids[-1], caption="📎 Proof")
            elif video_ids:
                await m.bot.send_video(admin_id, video_ids[0], caption="📎 Proof")
        except Exception:
            pass

    await m.answer(_tf(lang, "prom.submitted", "تم إرسال طلبك. سيتم مراجعته من قبل الإدارة ✅"))

@router.message(PromApply.proof)
async def prom_save_proof_invalid(m: Message):
    lang = L(m.from_user.id)
    await m.answer(_tf(lang, "prom.err.proof", "أرسل صورة أو فيديو كإثبات."))

# ===== أدوات مشتركة =====
def _get_app(uid: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    store = _load_store()
    u = store["users"].get(str(uid))
    return store, u

def _adm_only(cb_or_msg) -> bool:
    return cb_or_msg.from_user.id in ADMIN_IDS

# ===== قرارات الأدمن =====
@router.callback_query(F.data.startswith("prom:adm:approve:"))
async def adm_approve(cb: CallbackQuery):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    store, u = _get_app(uid)
    if not u: return await cb.answer("Not found.", show_alert=True)
    u["status"] = "approved"
    u["cooldown_until"] = 0
    _save_store(store)
    try:
        await cb.bot.send_message(uid, _tf(lang, "prom.user.approved", "تمت الموافقة على طلبك 🎉. تم تفعيل لوحة المروّجين لك."))
    except Exception:
        pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))

@router.callback_query(F.data.startswith("prom:adm:reject:"))
async def adm_reject(cb: CallbackQuery):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    store, u = _get_app(uid)
    if not u: return await cb.answer("Not found.", show_alert=True)
    u["status"] = "rejected"
    u["rejects"] = int(u.get("rejects", 0) or 0) + 1
    ban_secs = _next_reject_ban_secs(u["rejects"])
    u["cooldown_until"] = _now() + ban_secs if ban_secs > 0 else 0
    _save_store(store)
    try:
        msg = _tf(lang, "prom.user.rejected", "تم رفض طلبك.") + " " + \
              _tf(lang, "prom.user.cooldown", "يمكنك التقديم بعد: ") + _format_duration(ban_secs, lang)
        await cb.bot.send_message(uid, msg)
    except Exception:
        pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))

@router.callback_query(F.data.startswith("prom:adm:more:"))
async def adm_more_info(cb: CallbackQuery, state: FSMContext):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    store, u = _get_app(uid)
    if not u: return await cb.answer("Not found.", show_alert=True)
    u["status"] = "more_info"
    _save_store(store)
    try:
        await cb.bot.send_message(uid, _tf(lang, "prom.user.more", "نحتاج معلومات إضافية. أرسل التفاصيل هنا."))
    except Exception:
        pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))

@router.callback_query(F.data.startswith("prom:adm:hold:"))
async def adm_hold(cb: CallbackQuery):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    store, u = _get_app(uid)
    if not u: return await cb.answer("Not found.", show_alert=True)
    u["status"] = "on_hold"
    _save_store(store)
    try:
        await cb.bot.send_message(uid, _tf(lang, "prom.user.hold", "تم تعليق طلبك مؤقتًا."))
    except Exception:
        pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))

@router.callback_query(F.data.startswith("prom:adm:delete:"))
async def adm_delete(cb: CallbackQuery):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    store = _load_store()
    if str(uid) in store["users"]:
        del store["users"][str(uid)]
        _save_store(store)
        try:
            await cb.bot.send_message(uid, _tf(lang, "prom.user.deleted", "تم حذف طلبك."))
        except Exception:
            pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))

# ===== الحظر/إزالة الحظر =====
@router.callback_query(F.data.startswith("prom:adm:ban:"))
async def adm_ban_menu(cb: CallbackQuery):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    await cb.message.reply(_tf(lang, "prom.adm.choose_ban", "اختر مدة الحظر:"), reply_markup=_ban_menu_kb(uid, lang))
    await cb.answer()

# ===== إلغاء التبريد (رفع الحظر الوقتي) =====
@router.callback_query(F.data.startswith("prom:adm:cdclear:"))
async def adm_clear_cooldown(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "ar"
    uid = int(cb.data.split(":")[-1])
    store = _load_store()
    u = store["users"].get(str(uid))
    if not u:
        return await cb.answer("Not found.", show_alert=True)

    u["cooldown_until"] = 0
    _save_store(store)
    try:
        await cb.bot.send_message(uid, _tf(lang, "prom.user.cooldown_cleared", "تمت إزالة التبريد ويمكنك التقديم الآن."))
    except Exception:
        pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))


@router.callback_query(F.data.startswith("prom:adm:ban_do:"))
async def adm_ban_do(cb: CallbackQuery):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    parts = cb.data.split(":")  # prom:adm:ban_do:<uid>:<days>
    uid = int(parts[-2]); days = int(parts[-1])
    store, u = _get_app(uid)
    if not u: return await cb.answer("Not found.", show_alert=True)
    secs = days * 24 * 3600
    u["banned_until"] = _now() + secs
    _save_store(store)
    try:
        await cb.bot.send_message(uid, _tf(lang, "prom.user.banned", "تم حظرك مؤقتًا. المدة: ") + _format_duration(secs, lang))
    except Exception:
        pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))

@router.callback_query(F.data.startswith("prom:adm:unban:"))
async def adm_unban(cb: CallbackQuery):
    if not _adm_only(cb): return await cb.answer("Admins only.", show_alert=True)
    lang = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    store, u = _get_app(uid)
    if not u: return await cb.answer("Not found.", show_alert=True)
    u["banned_until"] = 0
    _save_store(store)
    try:
        await cb.bot.send_message(uid, _tf(lang, "prom.user.unbanned", "تمت إزالة الحظر عنك. يمكنك التقديم من جديد."))
    except Exception:
        pass
    await cb.answer(_tf(lang, "prom.saved", "تم الحفظ ✅"))

# ===== التقاط معلومات إضافية للمستخدم (عند more_info) =====
@router.message(F.text)
async def _maybe_capture_more_info(m: Message):
    d = _load_store()
    u = d["users"].get(str(m.from_user.id))
    if not u or u.get("status") != "more_info":
        return
    extra = u.setdefault("extra_messages", [])
    extra.append({"t": _now(), "text": m.text})
    _save_store(d)
    for admin_id in ADMIN_IDS:
        try:
            await m.bot.send_message(admin_id, f"✍️ إضافي من <code>{m.from_user.id}</code>:\n{m.text}", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    await m.answer(_tf(L(m.from_user.id), "prom.user.more.ok", "تم استلام المعلومات الإضافية ✅"))

# ثابتات للاستخدام من start.py
PROMOTER_INFO_CB = "prom:info"
PROMOTER_PANEL_CB = "prom:panel"
