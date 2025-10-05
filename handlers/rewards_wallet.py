# handlers/rewards_wallet.py
from __future__ import annotations

import re
import logging
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUser,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatType
from aiogram.types import MessageOriginUser  # لفحص forward_origin

from lang import t, get_user_lang
from utils.rewards_flags import is_global_paused, is_user_paused
from utils.rewards_store import ensure_user, add_points, is_blocked, can_do

# ✅ بوابة الاشتراك الإلزامي
from .rewards_gate import require_membership

# ✅ منع التضارب مع الدردشة الحيّة
from handlers.live_chat import LiveChat

# --- settings ---
import os
MIN_TRANSFER_POINTS = int(os.getenv("WALLET_MIN_TRANSFER", "100"))  # الحد الأدنى للتحويل

# ✅ فحص مكافحة الغش + الاستئناف بعد النجاح (مع Fallbackات آمنة)
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

# ===== Router (تعريف واحد فقط) =====
router = Router(name="rewards_wallet")
# اشتغل بالخاص فقط + لا تعمل أثناء LiveChat.active
router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
router.callback_query.filter(F.message.chat.type == "private", ~StateFilter(LiveChat.active))

log = logging.getLogger(__name__)

# ===================== Helpers =====================

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _points_of(uid: int) -> int:
    u = ensure_user(uid)
    try:
        return int(u.get("points", 0))
    except Exception:
        return 0

async def _safe_edit(cb: CallbackQuery, *, text: str, kb=None, wp: bool = True):
    """يحاول تعديل نفس الرسالة. إذا لم يتغير شيء نعرض تنبيه بسيط بدل الكراش."""
    if not cb.message:
        await cb.answer(text, show_alert=True)
        return
    try:
        await cb.message.edit_text(
            text,
            reply_markup=(kb.as_markup() if hasattr(kb, "as_markup") else kb),
            disable_web_page_preview=wp,
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await cb.answer(t(_L(cb.from_user.id), "wallet.already_here", "أنت بالفعل في هذه الشاشة."), show_alert=False)
        else:
            raise

def _kb_wallet(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=t(lang, "wallet.send_points", "🔁 تحويل نقاط"), callback_data="rwd:wal:tx"))
    kb.row(InlineKeyboardButton(text=t(lang, "wallet.back_home", "⬅️ رجوع"), callback_data="rwd:hub"))
    return kb

def _kb_tx_confirm(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=t(lang, "wallet.confirm", "✅ تأكيد"), callback_data="rwd:wal:tx:confirm"),
        InlineKeyboardButton(text=t(lang, "wallet.cancel", "✖️ إلغاء"), callback_data="rwd:wal:tx:cancel"),
    )
    return kb

def _wallet_text(uid: int, lang: str) -> str:
    bal = _points_of(uid)
    txt = t(lang, "wallet.title", "💳 محفظتي") + "\n"
    txt += t(lang, "wallet.balance", "الرصيد الحالي: {pts} نقطة").format(pts=bal)
    return txt

def _tx_intro_text(lang: str) -> str:
    # يشرح جميع الطرق المضمونة
    return t(
        lang,
        "wallet.tx_intro_username",
        "أرسل معرّف تيليجرام الحقيقي للمستلم بصيغة @username أو رابط t.me/username.\n"
        "إن لم يعمل @username، استخدم زر «📇 اختيار مستلم» أدناه أو قم بإعادة توجيه أي رسالة من المستلم هنا.\n"
        "يمكنك أيضًا إدخال User ID الرقمي عند الحاجة.\n"
        "مثال: @SnakeEngine أو https://t.me/SnakeEngine"
    )

def _tx_amount_text(lang: str, display: str) -> str:
    base = t(
        lang,
        "wallet.tx_amount_username",
        "أدخل المبلغ (عدد صحيح أكبر من 0) لإرساله إلى {who}."
    ).format(who=display)
    hint = t(lang, "wallet.min_hint", "(الحد الأدنى {n} نقطة)").format(n=MIN_TRANSFER_POINTS)
    return f"{base}\n{hint}"

def _tx_summary_text(lang: str, display: str, amount: int) -> str:
    return t(
        lang,
        "wallet.tx_summary_username",
        "تأكيد التحويل: {amt} نقطة إلى {who}.\nاضغط تأكيد لإتمام العملية."
    ).format(amt=amount, who=display)

# === تطبيع @username أو t.me/username بصورة صحيحة ===
_username_re = re.compile(r"^(?:@|https?://t\.me/|http://t\.me/|t\.me/)?(?P<u>[A-Za-z0-9_]{5,32})$")

def _normalize_username(raw: str) -> Optional[str]:
    raw = (raw or "").strip()

    # رابط t.me/username[/...][?...] -> استخرج الجزء الأول بعد t.me/
    if "t.me/" in raw:
        try:
            after = raw.split("t.me/", 1)[1]
            after = after.split("/", 1)[0]
            after = after.split("?", 1)[0]
            after = after.split("#", 1)[0]
            raw = after
        except Exception:
            pass

    if raw.startswith("@"):
        raw = raw[1:]

    if _username_re.fullmatch(raw):
        return raw
    return None

async def _resolve_user_identifier(bot, raw: str) -> Tuple[int, str]:
    """
    يرجع (user_id, display) من:
    - @username / t.me/username → يعمل فقط إن كان المستخدم بدأ محادثة مع البوت
    - رقم User ID               → يقبل مباشرة (display = ID#)
    """
    raw = (raw or "").strip()

    uname = _normalize_username(raw)
    if uname:
        try:
            chat = await bot.get_chat(f"@{uname}")
            if chat.type == ChatType.PRIVATE:
                display = f"@{uname}"
                return int(chat.id), display
            else:
                raise ValueError("username_is_not_user")
        except Exception as e:
            raise ValueError("username_not_resolvable") from e

    if raw.isdigit():
        return int(raw), f"ID#{raw}"

    raise ValueError("target_invalid")

# ============ Reply Keyboard (Request User) ============
def _pick_user_rk(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text=t(lang, "wallet.pick_user", "📇 اختيار مستلم"),
                request_user=KeyboardButtonRequestUser(
                    request_id=1,
                    user_is_bot=False  # 👈 لا تسمح باختيار بوت
                )
            )
        ], [
            KeyboardButton(text=t(lang, "wallet.cancel_rk", "إلغاء"))
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
        selective=True
    )

# ===================== Public API =====================

async def open_wallet(event: Message | CallbackQuery, edit: bool = True):
    uid = event.from_user.id
    lang = _L(uid)

    # ✅ تحقق الاشتراك الإلزامي
    if await require_membership(event) is False:
        return

    # احترام الإيقاف الإداري العام/الشخصي
    if is_global_paused() or is_user_paused(uid):
        txt = t(lang, "rewards.paused", "⏸️ نظام الجوائز متوقف مؤقتًا من الإدارة.")
        if isinstance(event, CallbackQuery):
            await event.answer(txt, show_alert=True)
        else:
            await event.answer(txt)
        return

    if is_blocked(uid):
        txt = t(lang, "wallet.locked",
                "⚠️ لا يمكنك استخدام المحفظة الآن. اشترك بالقنوات المطلوبة أولًا ثم عُد إلى الجوائز.")
        if isinstance(event, CallbackQuery):
            await event.answer(txt, show_alert=True)
        else:
            await event.answer(txt)
        return

    text = _wallet_text(uid, lang)
    kb = _kb_wallet(lang)

    if isinstance(event, CallbackQuery) and edit:
        await _safe_edit(event, text=text, kb=kb)
    elif isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=kb.as_markup())
    else:
        await event.answer(text, reply_markup=kb.as_markup())

# ===================== States =====================

class TxStates(StatesGroup):
    wait_target = State()
    wait_amount = State()
    confirm = State()

# ===================== Handlers =====================

@router.callback_query(F.data == "rwd:hub:wallet")
async def cb_open_wallet_from_hub(cb: CallbackQuery):
    await open_wallet(cb, edit=True)

@router.message(Command("wallet"))
async def cmd_wallet(msg: Message):
    await open_wallet(msg, edit=False)

@router.callback_query(F.data == "rwd:wal:back")
async def cb_wallet_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await open_wallet(cb, edit=True)

# ---- Start transfer flow
@router.callback_query(F.data == "rwd:wal:tx")
async def cb_tx_start(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = _L(uid)

    # تحقق الاشتراك أولًا
    if await require_membership(cb) is False:
        return

    async def _start_flow(_ev: CallbackQuery | Message):
        # احترام الإيقاف الإداري
        if is_global_paused() or is_user_paused(uid):
            await cb.answer(t(lang, "rewards.paused", "⏸️ نظام الجوائز متوقف مؤقتًا من الإدارة."), show_alert=True)
            return

        if is_blocked(uid):
            await cb.answer(t(lang, "wallet.locked",
                              "⚠️ لا يمكنك استخدام المحفظة الآن. اشترك بالقنوات المطلوبة أولًا."), show_alert=True)
            return

        if not can_do(uid, "wal_tx", cooldown_sec=2):
            await cb.answer(t(lang, "common.too_fast", "⏳ حاول بعد قليل."), show_alert=False)
            return

        await state.clear()
        await state.set_state(TxStates.wait_target)
        await state.update_data(msg_owner_id=uid)

        # 1) شاشة التعليمات
        await _safe_edit(
            cb,
            text=_tx_intro_text(lang),
            kb=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text=t(lang, "wallet.back", "⬅️ رجوع"), callback_data="rwd:wal:back")
            )
        )
        # 2) ReplyKeyboard لطلب مستخدم مضمون
        await cb.message.answer(
            t(lang, "wallet.pick_user_tip", "أو اضغط «📇 اختيار مستلم» لمشاركة الحساب مباشرةً."),
            reply_markup=_pick_user_rk(lang)
        )

    # ✅ كابتشا خفيفة قبل البدء + استئناف تلقائي
    await ensure_human_then(cb, level="normal", resume=_start_flow)

# ---- Collect target (user_shared / forward / text)
@router.message(StateFilter(TxStates.wait_target))
async def tx_get_target_any(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)

    # إلغاء
    txt = (msg.text or "").strip() if msg.text else ""
    if txt in {"إلغاء", "الغاء", "Cancel", "cancel"}:
        await state.clear()
        await msg.answer(t(lang, "common.cancelled", "تم الإلغاء."), reply_markup=ReplyKeyboardRemove())
        return await open_wallet(msg, edit=False)

    # 1) مشاركة مستخدم (UserShared أو UsersShared)
    target_id: Optional[int] = None
    try:
        if getattr(msg, "user_shared", None):
            target_id = int(msg.user_shared.user_id)
        elif getattr(msg, "users_shared", None) and msg.users_shared.users:
            target_id = int(msg.users_shared.users[0].user_id)
    except Exception:
        target_id = None

    # 2) إعادة توجيه
    if not target_id:
        if getattr(msg, "forward_from", None):
            target_id = int(msg.forward_from.id)
        else:
            origin = getattr(msg, "forward_origin", None)
            if isinstance(origin, MessageOriginUser) and getattr(origin, "sender_user", None):
                target_id = int(origin.sender_user.id)

    # 3) نص: @username / t.me/username / ID
    display: Optional[str] = None
    if not target_id and txt:
        try:
            target_id, display = await _resolve_user_identifier(msg.bot, txt)
        except ValueError as e:
            code = str(e)
            if code == "username_is_not_user":
                return await msg.reply(
                    t(lang, "wallet.target_is_not_user",
                      "المعرف يعود لقناة/مجموعة وليس لحساب شخصي. رجاءً أرسل @username لشخص."),
                    reply_markup=_pick_user_rk(lang)
                )
            elif code in {"username_not_resolvable", "target_invalid"}:
                return await msg.reply(
                    t(lang, "wallet.target_username_not_found",
                      "لم أتمكّن من العثور على مستخدم بهذا المعرف. "
                      "إذا كان @username صحيحًا لكنه لم يبدَأ محادثة مع البوت، "
                      "اضغط «📇 اختيار مستلم» أو أعد توجيه رسالة من ذلك المستخدم هنا."),
                    reply_markup=_pick_user_rk(lang)
                )
            else:
                return await msg.reply(
                    t(lang, "wallet.target_invalid_username",
                      "أرسل @username صحيحًا أو رابط t.me/username (ويمكن إدخال ID رقمي عند الحاجة)."),
                    reply_markup=_pick_user_rk(lang)
                )

    if target_id:
        if target_id == uid:
            return await msg.reply(t(lang, "wallet.target_self", "لا يمكنك تحويل النقاط لنفسك."),
                                   reply_markup=ReplyKeyboardRemove())
        if not display:
            display = f"ID#{target_id}"
        await state.update_data(target_id=target_id, target_display=display)
        await state.set_state(TxStates.wait_amount)
        return await msg.answer(_tx_amount_text(lang, display), reply_markup=ReplyKeyboardRemove())

    # لم نتمكن من التعرف على المستلم
    await msg.reply(
        t(lang, "wallet.target_username_not_found",
          "لم أتمكّن من التعرّف على المستلم. استخدم «📇 اختيار مستلم» أو أعد توجيه رسالة من ذلك المستخدم."),
        reply_markup=_pick_user_rk(lang)
    )

# ---- Collect amount
@router.message(StateFilter(TxStates.wait_amount))
async def tx_get_amount(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)

    raw = (msg.text or "").strip()
    if not raw.isdigit():
        await msg.reply(t(lang, "wallet.amount_invalid", "أدخل مبلغًا صحيحًا (عدد صحيح أكبر من 0)."))
        return

    amount = int(raw)
    if amount <= 0:
        await msg.reply(t(lang, "wallet.amount_invalid", "أدخل مبلغًا صحيحًا (عدد صحيح أكبر من 0)."))
        return

    # ✅ تحقق الحد الأدنى
    if amount < MIN_TRANSFER_POINTS:
        await msg.reply(
            t(lang, "wallet.err_min_transfer", "الحد الأدنى للتحويل هو {n} نقطة.").format(n=MIN_TRANSFER_POINTS)
        )
        return

    bal = _points_of(uid)
    if amount > bal:
        await msg.reply(t(lang, "wallet.amount_too_high", "المبلغ يتجاوز رصيدك ({bal}).").format(bal=bal))
        return

    data = await state.get_data()
    display = data.get("target_display") or f"ID#{data.get('target_id')}"

    await state.update_data(amount=amount)
    await state.set_state(TxStates.confirm)

    kb = _kb_tx_confirm(lang)
    await msg.answer(_tx_summary_text(lang, display, amount), reply_markup=kb.as_markup())

# ---- Confirm or cancel
@router.callback_query(F.data == "rwd:wal:tx:cancel")
async def tx_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await open_wallet(cb, edit=True)

@router.callback_query(F.data == "rwd:wal:tx:confirm")
async def tx_confirm(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = _L(uid)

    # ✅ منع النقر السريع المتكرر
    if not can_do(uid, "wal_tx_confirm_rate", cooldown_sec=5):
        await cb.answer(t(lang, "common.too_fast", "⏳ حاول بعد قليل."), show_alert=False)
        return

    # تحقق الاشتراك أولًا
    if await require_membership(cb) is False:
        await state.clear()
        return

    async def _do_confirm(_ev: CallbackQuery | Message):
        # احترام الإيقاف الإداري قبل التنفيذ
        if is_global_paused() or is_user_paused(uid):
            await cb.answer(t(lang, "rewards.paused", "⏸️ نظام الجوائز متوقف مؤقتًا من الإدارة."), show_alert=True)
            await state.clear()
            return

        data = await state.get_data()
        target_id: Optional[int] = data.get("target_id")
        target_display: str = data.get("target_display") or (f"ID#{target_id}" if target_id else "?")
        amount: Optional[int] = data.get("amount")

        if not target_id or not amount:
            await cb.answer(t(lang, "wallet.flow_reset", "انتهت الجلسة. ابدأ التحويل من جديد."), show_alert=True)
            await state.clear()
            return

        # ✅ تحقق الحد الأدنى مرة أخرى (أمان)
        if int(amount) < MIN_TRANSFER_POINTS:
            await cb.answer(
                t(lang, "wallet.err_min_transfer", "الحد الأدنى للتحويل هو {n} نقطة.").format(n=MIN_TRANSFER_POINTS),
                show_alert=True
            )
            await state.clear()
            return

        # تحقق الرصيد مرة ثانية
        if _points_of(uid) < int(amount):
            await cb.answer(t(lang, "wallet.amount_too_high", "المبلغ يتجاوز رصيدك."), show_alert=True)
            await state.clear()
            return

        # نفّذ التحويل في مخزن النقاط (يسجّل السجل تلقائيًا)
        ensure_user(target_id)
        add_points(uid, -abs(int(amount)), reason="wallet_transfer_out", typ="send")
        add_points(target_id, +abs(int(amount)), reason="wallet_transfer_in", typ="recv")

        await state.clear()

        await cb.answer(t(lang, "wallet.tx_done_toast", "تم تحويل النقاط بنجاح ✅"), show_alert=False)
        await _safe_edit(cb, text=_wallet_text(uid, lang), kb=_kb_wallet(lang))

        # إشعار المستلم (قد يفشل إن لم يبدأ محادثة مع البوت — لا مشكلة)
        try:
            await cb.bot.send_message(
                chat_id=target_id,
                text=t(
                    _L(target_id),
                    "wallet.tx_in_notify_username",
                    "📥 وصلك {amt} نقطة من المستخدم {who}."
                ).format(amt=amount, who=f"@{cb.from_user.username}" if cb.from_user.username else uid)
            )
        except Exception:
            pass

    # ✅ كابتشا أقوى عند التنفيذ + استئناف تلقائي
    await ensure_human_then(cb, level="high", resume=_do_confirm)

# ===================== Optional shortcuts =====================

@router.callback_query(F.data == "rwd:wal")
async def cb_open_wallet_short(cb: CallbackQuery):
    await open_wallet(cb, edit=True)
