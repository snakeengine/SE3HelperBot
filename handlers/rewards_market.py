# handlers/rewards_market.py
from __future__ import annotations

import os
import re
import logging
from typing import Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from lang import t, get_user_lang
from utils.rewards_store import (
    get_points, add_points, is_blocked, can_do
)
from .rewards_gate import require_membership  # احترام الاشتراك الإلزامي

# طلبات وإشعارات
from utils.rewards_orders import create_order, get_order, set_status
from utils.rewards_notify import (
    notify_admins_new_vip_order,
    notify_user_vip_submitted,
    notify_user_vip_approved,
    notify_user_vip_rejected,
)

# وضع الدردشة الحيّة
from handlers.live_chat import LiveChat

# ========= الراوتر + فلاتر عامة =========
router = Router(name="rewards_market")
# امنع التنفيذ أثناء جلسة الدردشة الحيّة، واشتغل بالخاص فقط
router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
router.callback_query.filter(
    F.message.chat.type == "private",
    ~StateFilter(LiveChat.active),
    F.data.func(lambda s: isinstance(s, str) and (s.startswith("rwd:") or s.startswith("rwdadm:")))
)

log = logging.getLogger(__name__)

# ========= كابتشا بشرية (اختياري) =========
try:
    from .human_check import require_human, ensure_human_then  # type: ignore
except Exception:
    async def require_human(msg_or_cb, level: str = "normal") -> bool:
        return True
    async def ensure_human_then(msg_or_cb, level: str, resume):
        if await require_human(msg_or_cb, level=level):
            await resume(msg_or_cb)
            return True
        return False

# ========= إعدادات عامة =========
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in _admin_env.split(",") if x.strip().isdigit()]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _fmt_hours_ar(hours: int) -> str:
    if hours < 24:
        return f"{hours} ساعة"
    days = hours // 24
    if days == 1:
        return "يوم"
    if days == 2:
        return "يومين"
    if 3 <= days <= 10:
        return f"{days} أيام"
    return f"{days} يومًا"

# ========= عناصر المتجر =========
COST_1H  = int(os.getenv("SHOP_VIP1H_COST",  "100"))
COST_1D  = int(os.getenv("SHOP_VIP1D_COST",  "500"))
COST_3D  = int(os.getenv("SHOP_VIP3D_COST",  "1000"))
COST_30D = int(os.getenv("SHOP_VIP30D_COST", "8000"))  # 30 يوم
# NEW: تكلفة الاستبدال (إن رغبت بتكلفة ثابتة)
COST_REDEEM = int(os.getenv("SHOP_REDEEM_COST", "0"))
ENABLE_REDEEM = (os.getenv("SHOP_REDEEM_ENABLED", "0").strip().lower() in {"1","true","yes","on"})

SHOP_ITEMS: Dict[str, Dict[str, Any]] = {
    "vip1h":  {"title_ar": f"اشتراك VIP • {_fmt_hours_ar(1)}",       "title_en": "VIP • 1 hour",   "cost": COST_1H,  "kind": "vip_hours", "hours": 1},
    "vip1d":  {"title_ar": f"اشتراك VIP • {_fmt_hours_ar(24)}",      "title_en": "VIP • 1 day",    "cost": COST_1D,  "kind": "vip_hours", "hours": 24},
    "vip3d":  {"title_ar": f"اشتراك VIP • {_fmt_hours_ar(72)}",      "title_en": "VIP • 3 days",   "cost": COST_3D,  "kind": "vip_hours", "hours": 72},
    "vip30d": {"title_ar": f"اشتراك VIP • {_fmt_hours_ar(24 * 30)}", "title_en": "VIP • 30 days",  "cost": COST_30D, "kind": "vip_hours", "hours": 24 * 30},

    # NEW: استبدال نقاط بدل اشتراك — يجبر المستخدم على تحديد اللعبة ويُبلّغ الإدارة
    "redeem": {"title_ar": "استبدال نقاط بدل اشتراك", "title_en": "Redeem points (no subscription)",
               "cost": COST_REDEEM, "kind": "redeem"},
}

# ======== واجهة المتجر ========
def _kb_market(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for item_id, it in SHOP_ITEMS.items():
        # ✅ اخفِ خيار الاستبدال إذا غير مفعّل
        if item_id == "redeem" and not ENABLE_REDEEM:
            continue
        title = it["title_ar"] if lang.startswith("ar") else it["title_en"]
        cost = it["cost"]
        label = f"💎 {title} • {cost}"
        kb.row(InlineKeyboardButton(text=label, callback_data=f"rwd:mkt:buy:{item_id}"))
    kb.row(InlineKeyboardButton(text=t(lang, "market.back", "⬅️ رجوع"), callback_data="rwd:hub"))
    return kb


async def _show_market(msg_or_cb: Message | CallbackQuery):
    """يعرض قائمة المتجر (مفصولة لاستخدامها مع ensure_human_then)."""
    uid = msg_or_cb.from_user.id
    lang = _L(uid)

    if await require_membership(msg_or_cb) is False:
        return
    if is_blocked(uid):
        txt = t(lang, "market.locked", "⚠️ لا يمكنك استخدام المتجر الآن. اشترك بالقنوات المطلوبة أولًا.")
        if isinstance(msg_or_cb, CallbackQuery):
            return await msg_or_cb.answer(txt, show_alert=True)
        return await msg_or_cb.answer(txt)

    title = t(lang, "market.title", "🛍️ المتجر — اختر عنصرًا")
    kb = _kb_market(lang).as_markup()
    if isinstance(msg_or_cb, CallbackQuery):
        try:
            await msg_or_cb.message.edit_text(title, reply_markup=kb)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
    else:
        await msg_or_cb.answer(title, reply_markup=kb)

async def open_market(msg_or_cb: Message | CallbackQuery):
    """يعرض المتجر مع كابتشا خفيفة واستئناف تلقائي عند الحاجة."""
    await ensure_human_then(msg_or_cb, level="normal", resume=_show_market)

@router.callback_query(F.data == "rwd:hub:market")
async def cb_open_market(cb: CallbackQuery):
    await open_market(cb)

# ======== تأكيد قبل الخصم ========
def _kb_confirm(lang: str, item_id: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=t(lang, "market.confirm", "✅ تأكيد"), callback_data=f"rwd:mkt:cfm:{item_id}"),
        InlineKeyboardButton(text=t(lang, "market.cancel", "✖️ إلغاء"), callback_data="rwd:hub:market"),
    )
    return kb

@router.callback_query(F.data.startswith("rwd:mkt:buy:"))
async def cb_buy_item(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    item_id = cb.data.split(":")[-1]
    it = SHOP_ITEMS.get(item_id)
    if not it:
        return await cb.answer(t(lang, "market.unavailable", "هذا الخيار غير متاح حاليًا."), show_alert=True)


    # عضوية + كابتشا خفيفة + تبريد
    if await require_membership(cb) is False:
        return
    if not await require_human(cb, level="normal"):
        return
    if is_blocked(uid):
        return await cb.answer(t(lang, "market.locked", "⚠️ لا يمكنك استخدام المتجر الآن."), show_alert=True)
    if not can_do(uid, f"mkt_buy_{item_id}", cooldown_sec=3):
        return await cb.answer(t(lang, "common.too_fast", "⏳ حاول بعد قليل."), show_alert=False)

    title = it["title_ar"] if lang.startswith("ar") else it["title_en"]
    cost = it["cost"]
    bal = get_points(uid)

    txt = (
        t(lang, "market.confirm_title", "تأكيد الشراء") + "\n" +
        t(lang, "market.you_will_get", "ستحصل على") + f": <b>{title}</b>\n" +
        t(lang, "market.price", "السعر") + f": <b>{cost}</b>\n" +
        t(lang, "market.balance", "رصيدك") + f": <b>{bal}</b>\n" +
        t(lang, "market.ask_confirm", "هل تريد المتابعة؟")
    )
    try:
        await cb.message.edit_text(txt, reply_markup=_kb_confirm(lang, item_id).as_markup(), disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

# ======== FSM: شراء VIP (بعد الخصم) ========
class BuyStates(StatesGroup):
    wait_app = State()       # معرّف تطبيق الثعبان
    wait_details = State()   # تفاصيل إضافية

# ======== FSM: استبدال النقاط (يجبر نوع اللعبة) ========
class RedeemStates(StatesGroup):
    wait_game = State()      # نوع/اسم اللعبة
    wait_details = State()   # تفاصيل إضافية

# --- اكتشاف الإلغاء بشكل مرن (AR/EN) ---
_CANCEL_WORDS = {"إلغاء", "الغاء", "cancel", "رجوع"}  # الأساسية

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _is_cancel(txt: str, lang: str) -> bool:
    n = _norm(txt)
    try:
        lbl_ar = _norm(t("ar", "market.cancel_refund", "إلغاء واسترجاع"))
        lbl_en = _norm(t("en", "market.cancel_refund", "Cancel & refund"))
    except Exception:
        lbl_ar, lbl_en = _norm("إلغاء واسترجاع"), _norm("Cancel & refund")

    if n in {_norm(w) for w in _CANCEL_WORDS}:
        return True
    if n == lbl_ar or n == lbl_en:
        return True
    if n.startswith("cancel"):  # يقبل "cancel & refund" وغيرها
        return True
    if "إلغاء" in txt or "الغاء" in txt:
        return True
    return False

def _cancel_rk(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "market.cancel_refund", "إلغاء واسترجاع"))]],
        resize_keyboard=True, one_time_keyboard=True, selective=True
    )

_APP_RE = re.compile(r"^@?[A-Za-z0-9_\.]{3,64}$")

def _normalize_app_id(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    if _APP_RE.match(s):
        return s.lstrip("@")
    return None

# ======== تأكيد الشراء → خصم → مسار VIP أو Redeem ========
@router.callback_query(F.data.startswith("rwd:mkt:cfm:"))
async def cb_confirm_buy(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = _L(uid)
    item_id = cb.data.split(":")[-1]
    it = SHOP_ITEMS.get(item_id)
    if not it:
        return await cb.answer(t(lang, "market.unavailable", "هذا الخيار غير متاح حاليًا."), show_alert=True)

    # عضوية + كابتشا أقوى + منع النقر المكرر
    if await require_membership(cb) is False:
        return
    if not await require_human(cb, level="high"):
        return
    if not can_do(uid, f"mkt_cfm_{item_id}", cooldown_sec=3):
        return await cb.answer(t(lang, "common.too_fast", "⏳ حاول بعد قليل."), show_alert=False)

    cost = int(it["cost"])
    bal = get_points(uid)
    if bal < cost:
        return await cb.answer(t(lang, "market.no_balance", "رصيدك لا يكفي لإتمام الشراء."), show_alert=True)

    # خصم فوري قبل جمع البيانات (يسجّل في السجل تلقائيًا)
    add_points(uid, -cost, reason=f"market_buy_{item_id}", typ="buy")

    # NEW: فرع الاستبدال — اجمع نوع اللعبة ثم التفاصيل
    if it.get("kind") == "redeem":
        await state.clear()
        await state.set_state(RedeemStates.wait_game)
        await state.update_data(item_id=item_id, cost=cost)

        ask_game = t(lang, "market.redeem.ask_game",
                     "اكتب نوع/اسم اللعبة التي تريد استبدال نقاطك لها (مثال: PUBG، Free Fire، Fortnite...).")
        try:
            await cb.message.edit_text(ask_game, disable_web_page_preview=True)
        except TelegramBadRequest:
            await cb.message.answer(ask_game, disable_web_page_preview=True)
        await cb.message.answer(
            t(lang, "market.redeem.tip_game", "أرسل اسم اللعبة الآن أو اختر «إلغاء واسترجاع»."),
            reply_markup=_cancel_rk(lang)
        )
        return

    # المسار الحالي للاشتراك VIP كما هو: خزّن سياق الطلب ثم اطلب معرّف التطبيق
    await state.clear()
    await state.set_state(BuyStates.wait_app)
    await state.update_data(item_id=item_id, cost=cost, hours=int(it.get("hours", 0)))

    tip = t(
        lang, "market.vip.ask_app",
        "اذهب إلى تطبيق محرك الثعبان، في أعلى الواجهة (الزاوية اليسرى) ستجد <b>معرّف التطبيق</b> الخاص بك. انسخه وأرسله هنا."
    )
    try:
        await cb.message.edit_text(tip, disable_web_page_preview=True)
    except TelegramBadRequest:
        await cb.message.answer(tip, disable_web_page_preview=True)
    await cb.message.answer(
        t(lang, "market.vip.ask_app_tip", "أرسل المعرّف الآن أو اختر «إلغاء واسترجاع»."),
        reply_markup=_cancel_rk(lang)
    )
    await cb.answer()

# ======== استلام معرّف التطبيق (VIP) → ثم التفاصيل ========
@router.message(BuyStates.wait_app)
async def buy_get_app(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="market_refund_cancel", typ="refund")
        await state.clear()
        return await msg.answer(t(lang, "market.vip.cancelled_refund", "تم الإلغاء واستُرجعت نقاطك."),
                                reply_markup=ReplyKeyboardRemove())

    app_id = _normalize_app_id(txt)
    if not app_id:
        return await msg.reply(
            t(lang, "market.vip.invalid_app", "صيغة المعرّف غير صحيحة. اكتب @username أو اسمًا بدون @."),
            reply_markup=_cancel_rk(lang)
        )

    await state.update_data(app_id=app_id)
    await state.set_state(BuyStates.wait_details)

    ask = t(lang, "market.vip.ask_details",
            "أرسل تفاصيل الاشتراك المطلوبة (مثال: اللعبة/الوضع، ملاحظات إضافية).")
    tip = t(lang, "market.vip.details_tip", "يمكنك كتابة أي تفاصيل تساعدنا على التفعيل بشكل صحيح.")
    await msg.answer(ask)
    await msg.answer(tip, reply_markup=_cancel_rk(lang))

# ======== استلام تفاصيل (VIP) → إنشاء طلب Pending + إشعارات ========
@router.message(BuyStates.wait_details)
async def buy_get_details(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="market_refund_cancel", typ="refund")
        await state.clear()
        await msg.answer(t(lang, "market.vip.cancelled_refund", "تم الإلغاء واستُرجعت نقاطك."),
                         reply_markup=ReplyKeyboardRemove())
        for aid in ADMIN_IDS:
            try:
                await msg.bot.send_message(aid, f"↩️ استرجاع: المستخدم <code>{uid}</code> ألغى العملية أثناء جمع التفاصيل.")
            except Exception:
                pass
        return

    data = await state.get_data()
    await state.clear()

    item_id = data.get("item_id")
    cost = int(data.get("cost", 0))
    hours = int(data.get("hours", 0))
    app_id = data.get("app_id") or "-"
    tg_username = (msg.from_user.username or "").lstrip("@")

    # إنشاء طلب Pending (VIP)
    oid = create_order(uid, kind="vip", payload={
        "hours": hours,
        "app": app_id,
        "details": txt,
        "tg_username": tg_username,
        "cost": cost,
    })

    # إشعار المستخدم + الأدمن
    await notify_user_vip_submitted(msg.bot, uid, oid, hours, cost)
    await notify_admins_new_vip_order(msg.bot, oid, uid, hours, app_id, txt, cost)

    # رسالة إضافية للأدمن تتضمن Username بشكل واضح
    extra = f"ℹ️ VIP order #{oid}\n• User: <code>{uid}</code>{(' — @' + tg_username) if tg_username else ''}\n• AppID: <code>{app_id}</code>"
    for aid in ADMIN_IDS:
        try:
            await msg.bot.send_message(aid, extra, disable_web_page_preview=True)
        except Exception:
            pass

# ======== (REDEEM) استلام نوع اللعبة → التفاصيل → إنشاء الطلب وإشعار الأدمن ========
@router.message(RedeemStates.wait_game)
async def redeem_get_game(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="redeem_refund_cancel", typ="refund")
        await state.clear()
        return await msg.answer(t(lang, "market.redeem.cancelled_refund", "تم الإلغاء واستُرجعت نقاطك."),
                                reply_markup=ReplyKeyboardRemove())

    # إلزام كتابة لعبة واضحة
    game = txt
    if len(game) < 2:
        return await msg.reply(
            t(lang, "market.redeem.invalid_game", "من فضلك اكتب اسم اللعبة بشكل واضح."),
            reply_markup=_cancel_rk(lang)
        )

    await state.update_data(game=game)
    await state.set_state(RedeemStates.wait_details)

    ask = t(lang, "market.redeem.ask_details",
            "أرسل تفاصيل إضافية (مثال: النظام/السيرفر/ملاحظات تهم التنفيذ).")
    tip = t(lang, "market.redeem.details_tip", "تفاصيل أكثر تساعد الإدارة على تنفيذ الاستبدال.")
    await msg.answer(ask)
    await msg.answer(tip, reply_markup=_cancel_rk(lang))

@router.message(RedeemStates.wait_details)
async def redeem_get_details(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="redeem_refund_cancel", typ="refund")
        await state.clear()
        return await msg.answer(t(lang, "market.redeem.cancelled_refund", "تم الإلغاء واستُرجعت نقاطك."),
                                reply_markup=ReplyKeyboardRemove())

    data = await state.get_data()
    await state.clear()

    cost = int(data.get("cost", 0))
    game = data.get("game") or "-"
    tg_username = (msg.from_user.username or "").lstrip("@")

    # إنشاء طلب Pending لنوع redeem
    oid = create_order(uid, kind="redeem", payload={
        "game": game,
        "details": txt,
        "tg_username": tg_username,
        "cost": cost,
    })

    # إشعار المستخدم
    await msg.answer(
        t(lang, "market.redeem.submitted",
          f"✅ تم إرسال طلب الاستبدال #{oid}.\nاللعبة: {game}\nسيتم المراجعة والتنفيذ قريبًا."),
        reply_markup=ReplyKeyboardRemove()
    )

    # إشعار الأدمن — يتضمن نوع اللعبة صراحةً
    admin_text = (
        f"🆕 طلب استبدال نقاط #{oid}\n"
        f"• User: <code>{uid}</code>{(' — @' + tg_username) if tg_username else ''}\n"
        f"• Game: <b>{game}</b>\n"
        f"• Details: {txt or '-'}\n"
        f"• Cost: {cost}"
    )
    for aid in ADMIN_IDS:
        try:
            await msg.bot.send_message(aid, admin_text, disable_web_page_preview=True)
        except Exception:
            pass

# ======== (أدمن) قبول/رفض طلب VIP ========
async def _grant_vip_hours_bridge(bot, uid: int, hours: int, reason: str = "rewards_approved") -> bool:
    """جسر اختياري لتفعيل VIP إن توفرت وحدة الإدارة المناسبة."""
    try:
        from admin.vip_manager import grant_vip_hours
        ok = await grant_vip_hours(bot, uid, hours, reason=reason)  # يجب أن ترجع True/False
        return bool(ok)
    except Exception as e:
        log.warning(f"[VIP BRIDGE] not available / failed: {e}")
        return False

@router.callback_query(F.data.startswith("rwdadm:vip:approve:"))
async def approve_vip_order(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only", show_alert=True)

    oid = int(cb.data.split(":")[-1])
    row = get_order(oid)
    if not row:
        return await cb.answer("Order not found", show_alert=True)
    if row.get("status") != "pending":
        return await cb.answer("Already decided", show_alert=True)

    set_status(oid, "approved", admin_id=cb.from_user.id)
    p = row.get("payload", {}) or {}
    uid = int(row["uid"])
    hours = int(p.get("hours") or 0)
    app = str(p.get("app") or "-")
    details = str(p.get("details") or "-")

    ok = await _grant_vip_hours_bridge(cb.bot, uid, hours, reason="market_approved")
    if not ok:
        try:
            await cb.message.answer(
                f"ℹ️ تمت الموافقة على #{oid} للمستخدم {uid} ({_fmt_hours_ar(hours)}). "
                f"لم يتم التفعيل الآلي — فعِّله يدويًا إن لزم."
            )
        except Exception:
            pass

    await notify_user_vip_approved(cb.bot, uid, oid, hours, app_id=app, details=details)
    try:
        await cb.message.edit_reply_markup()  # إزالة الأزرار
    except Exception:
        pass
    await cb.answer("✅ Approved", show_alert=True)

@router.callback_query(F.data.startswith("rwdadm:vip:reject:"))
async def reject_vip_order(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only", show_alert=True)

    oid = int(cb.data.split(":")[-1])
    row = get_order(oid)
    if not row:
        return await cb.answer("Order not found", show_alert=True)
    if row.get("status") != "pending":
        return await cb.answer("Already decided", show_alert=True)

    p = row.get("payload", {}) or {}
    uid = int(row["uid"])
    cost = int(p.get("cost") or 0)

    # ردّ النقاط ثم علّم الطلب مرفوض
    if cost > 0:
        add_points(uid, +cost, reason="vip_order_refund", typ="refund")
    set_status(oid, "rejected", admin_id=cb.from_user.id)

    await notify_user_vip_rejected(cb.bot, uid, oid, refunded=cost)
    try:
        await cb.message.edit_reply_markup()
    except Exception:
        pass
    await cb.answer("❌ Rejected & refunded", show_alert=True)
