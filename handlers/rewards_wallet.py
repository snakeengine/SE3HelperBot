from __future__ import annotations

# handlers/rewards_wallet.py


import re
import math
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

# عمولة (قابلة للتهيئة)
FEE_PERCENT = float(os.getenv("WALLET_FEE_PERCENT", "2.5"))  # % من قيمة التحويل
FEE_MIN     = float(os.getenv("WALLET_FEE_MIN", "0"))        # حد أدنى للعمولة بالنقاط
FEE_MAX     = float(os.getenv("WALLET_FEE_MAX", "0"))        # حد أقصى للعمولة بالنقاط (0 = بلا سقف)
FEE_SINK_ID = int(os.getenv("WALLET_FEE_SINK", "0") or 0)    # إن أردت تجميع العمولة في حساب

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

def L(lang: str, ar: str, en: str) -> str:
    return ar if str(lang).startswith("ar") else en

def _is_self_chat(bot, uid: int) -> bool:
    try:
        return int(uid) == int(bot.id)
    except Exception:
        return False

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _points_of(uid: int) -> int:
    u = ensure_user(uid)
    try:
        return int(u.get("points", 0))
    except Exception:
        return 0

def _ceil(x: float) -> int:
    return int(math.ceil(x))

def _calc_fee(amount: int) -> int:
    """
    يحسب العمولة وفق:
      fee = amount * (FEE_PERCENT/100) ثم يطبّق حد أدنى/أقصى إن تم ضبطهما.
    ترجع عددًا صحيحًا (تقريب للأعلى حتى لا تكون العمولة كسور).
    """
    fee = _ceil(amount * max(FEE_PERCENT, 0.0) / 100.0)
    if FEE_MIN > 0:
        fee = max(fee, _ceil(FEE_MIN))
    if FEE_MAX > 0:
        fee = min(fee, _ceil(FEE_MAX))
    return max(0, min(fee, amount - 1))  # لا نسمح بأن تلتهم العمولة كامل المبلغ

def _fee_hint(lang: str) -> str:
    # لا تعرض شيئًا إذا لم تكن هناك عمولة فعالة
    if FEE_PERCENT <= 0 and FEE_MIN <= 0 and FEE_MAX <= 0:
        return ""

    # ابن وصف العمولة لكل لغة
    parts_ar, parts_en = [], []
    if FEE_PERCENT > 0:
        parts_ar.append(f"{FEE_PERCENT:g}%")
        parts_en.append(f"{FEE_PERCENT:g}%")
    if FEE_MIN > 0:
        parts_ar.append(f"حد أدنى {_ceil(FEE_MIN)}")
        parts_en.append(f"min {_ceil(FEE_MIN)}")
    if FEE_MAX > 0:
        parts_ar.append(f"حد أقصى {_ceil(FEE_MAX)}")
        parts_en.append(f"max {_ceil(FEE_MAX)}")

    desc_ar = " + ".join(parts_ar)
    desc_en = " + ".join(parts_en)

    return L(lang, f"(تُطبَّق عمولة: {desc_ar})", f"(fee applies: {desc_en})")


def _fee_pct_str(lang: str) -> str:
    pct = max(FEE_PERCENT, 0.0)
    return L(lang, f"(٪{pct:g}‏: عمولة تُطبق)", f"(fee: {pct:g}%)")

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
    kb.row(InlineKeyboardButton(text=L(lang, "🔁 تحويل نقاط", "🔁 Transfer points"), callback_data="rwd:wal:tx"))
    kb.row(InlineKeyboardButton(text=L(lang, "⬅️ رجوع", "⬅️ Back"), callback_data="rwd:hub"))
    return kb

def _kb_tx_confirm(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=L(lang, "✅ تأكيد", "✅ Confirm"), callback_data="rwd:wal:tx:confirm"),
        InlineKeyboardButton(text=L(lang, "✖️ إلغاء", "✖️ Cancel"), callback_data="rwd:wal:tx:cancel"),
    )
    return kb

def _pick_user_rk(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text=L(lang, "📇 اختيار مستلم", "📇 Pick recipient"),
            request_user=KeyboardButtonRequestUser(request_id=1, user_is_bot=False)
        )],[KeyboardButton(text=L(lang, "إلغاء", "Cancel"))]],
        resize_keyboard=True,
        one_time_keyboard=True,
        selective=True
    )

def _tx_intro_text(lang: str) -> str:
    return L(
        lang,
        # ——— عربي ———
        "أرسل مُعرّف تيليجرام الحقيقي للمستلم بصيغة @username أو رابط t.me/username.\n"
        "إذا لم يعمل @username، استخدم زر «📇 اختيار مستلم» بالأسفل أو أعد توجيه أي رسالة من المستلم هنا.\n"
        "يمكنك أيضًا إدخال User ID الرقمي عند الحاجة.\n"
        "مثال: @SnakeEngine أو https://t.me/SnakeEngine\n"
        f"{_fee_pct_str(lang)}",
        # ——— English ———
        "Send the recipient’s real Telegram identifier as @username or a t.me/username link.\n"
        "If @username doesn’t resolve, use the “📇 Pick recipient” button below or forward any message from the recipient here.\n"
        "You can also input the numeric User ID when needed.\n"
        "Example: @SnakeEngine or https://t.me/SnakeEngine\n"
        f"{_fee_pct_str(lang)}"
    )

def _tx_amount_text(lang: str, display: str) -> str:
    base = L(
        lang,
        "أدخل المبلغ (عدد صحيح أكبر من 0) لإرساله إلى {who}.",
        "Enter an integer amount (>0) to send to {who}."
    ).format(who=display)
    hint = L(
        lang,
        f"(الحد الأدنى {MIN_TRANSFER_POINTS} نقطة)",
        f"(minimum {MIN_TRANSFER_POINTS} points)"
    )
    fee = _fee_hint(lang)
    return "\n".join([base, hint, fee] if fee else [base, hint])

def _tx_summary_text(lang: str, display: str, amount: int, fee: int, net: int) -> str:
    # يظهر المبلغ، العمولة، الصافي
    return L(
        lang,
        "تأكيد التحويل: {amt} نقطة إلى {who}.\nالعمولة: {fee} نقطة — صافي المستلم: {net} نقطة.\nاضغط تأكيد لإتمام العملية.",
        "Confirm transfer: {amt} points to {who}.\nFee: {fee} points — Recipient net: {net} points.\nTap Confirm to complete."
    ).format(amt=amount, who=display, fee=fee, net=net)

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

_RESERVED_BAD_IDS = {5, 777000, 1087968824}  # 5=خطأ شائع, 777000=Telegram, 1087968824=GroupAnonymBot وغيره

async def _resolve_user_identifier(bot, raw: str) -> Tuple[int, str]:
    """
    يرجع (user_id, display) من:
    - @username / t.me/username → فقط لو المستخدم بدأ محادثة مع البوت (get_chat PRIVATE)
    - رقم User ID               → نقبله فقط بعد التحقق عبر get_chat وأنه PRIVATE وليس بوتًا/قناة/مجموعة
    """
    raw = (raw or "").strip()

    # @username / t.me/username
    uname = _normalize_username(raw)
    if uname:
        try:
            chat = await bot.get_chat(f"@{uname}")
            if chat.type == ChatType.PRIVATE and not getattr(chat, "is_bot", False):
                display = f"@{uname}"
                return int(chat.id), display
            raise ValueError("username_is_not_user")
        except Exception as e:
            raise ValueError("username_not_resolvable") from e

    # رقم ID
    if raw.isdigit():
        try:
            uid = int(raw)
            # فلترة IDs المعروفة/الصغيرة جدًا
            if uid in _RESERVED_BAD_IDS or uid <= 10_000_000:
                raise ValueError("id_suspect")

            chat = await bot.get_chat(uid)
            if chat.type == ChatType.PRIVATE and not getattr(chat, "is_bot", False):
                disp = f"ID#{uid}"
                # إن وُجد username نفضّله لعرض أوضح
                try:
                    if getattr(chat, "username", None):
                        disp = f"@{chat.username}"
                except Exception:
                    pass
                return uid, disp
            raise ValueError("id_not_private")
        except ValueError:
            raise
        except Exception as e:
            # فشلنا نتحقق من الـID
            raise ValueError("id_not_resolvable") from e

    # أي صيغة أخرى غير مدعومة
    raise ValueError("target_invalid")

# ===================== Public API =====================

def _wallet_text(uid: int, lang: str) -> str:
    bal = _points_of(uid)
    title = L(lang, "💳 محفظتي", "💳 My Wallet")
    line  = L(lang, "الرصيد الحالي: {pts} نقطة", "Current balance: {pts} points").format(pts=bal)
    return f"{title}\n{line}"

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
        origin = getattr(msg, "forward_origin", None)
        # Telegram 6.9+: MessageOriginUser
        if isinstance(origin, MessageOriginUser) and getattr(origin, "sender_user", None):
            cand = int(origin.sender_user.id)
            # تجاهل رسائل مُعادة من نفس البوت/قنوات/مجموعات/IDs مشبوهة
            if cand not in _RESERVED_BAD_IDS and cand != msg.bot.id and cand > 10_000_000:
                target_id = cand

        # النسخة القديمة forward_from
        if not target_id and getattr(msg, "forward_from", None):
            try:
                cand = int(msg.forward_from.id)
                if (msg.forward_from.is_bot is False) and cand not in _RESERVED_BAD_IDS and cand != msg.bot.id and cand > 10_000_000:
                    target_id = cand
            except Exception:
                pass

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
            elif code in {"username_not_resolvable", "id_not_resolvable", "id_not_private", "id_suspect", "target_invalid"}:
                return await msg.reply(
                    t(lang, "wallet.target_username_not_found",
                      "لم أتمكّن من العثور على مستخدم بهذا المعرف. "
                      "استخدم زر «📇 اختيار مستلم» أو أعد توجيه رسالة من ذلك المستخدم هنا."),
                    reply_markup=_pick_user_rk(lang)
                )
            else:
                return await msg.reply(
                    t(lang, "wallet.target_invalid_username",
                      "أرسل @username صحيحًا أو رابط t.me/username. "
                      "يمكن إدخال User ID فقط إذا كان صحيحًا ويمكنني التعرف عليه."),
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

    # حساب العمولة + الصافي
    fee = _calc_fee(amount)
    net = amount - fee
    if net <= 0:
        await msg.reply(t(lang, "wallet.net_zero", "المبلغ قليل جدًا بعد تطبيق العمولة. زِد المبلغ من فضلك."))
        return

    data = await state.get_data()
    display = data.get("target_display") or f"ID#{data.get('target_id')}"

    await state.update_data(amount=amount, fee=fee, net=net)
    await state.set_state(TxStates.confirm)

    kb = _kb_tx_confirm(lang)
    await msg.answer(_tx_summary_text(lang, display, amount, fee, net), reply_markup=kb.as_markup())

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
        fee: Optional[int]    = data.get("fee")
        net: Optional[int]    = data.get("net")

        if not target_id or not amount:
            await cb.answer(t(lang, "wallet.flow_reset", "انتهت الجلسة. ابدأ التحويل من جديد."), show_alert=True)
            await state.clear()
            return

        # أمان: أعد حساب العمولة لحظة التنفيذ
        amount  = int(amount)
        fee_now = _calc_fee(amount)
        net_now = amount - fee_now
        if net_now <= 0:
            await cb.answer(t(lang, "wallet.net_zero", "المبلغ قليل جدًا بعد تطبيق العمولة."), show_alert=True)
            await state.clear()
            return

        # تحقق الرصيد مرة ثانية
        if _points_of(uid) < amount:
            await cb.answer(t(lang, "wallet.amount_too_high", "المبلغ يتجاوز رصيدك."), show_alert=True)
            await state.clear()
            return

        # نفّذ التحويل في مخزن النقاط (يسجّل السجل تلقائيًا)
        ensure_user(target_id)
        # 1) خصم كامل amount من المرسل
        add_points(uid, -abs(amount), reason="wallet_transfer_out", typ="send")
        # 2) إضافة الصافي للمستلم
        add_points(target_id, +abs(net_now), reason="wallet_transfer_in", typ="recv")
        # 3) تحويل العمولة إلى الحوض إن تم ضبطه
        if FEE_SINK_ID and fee_now > 0:
            ensure_user(FEE_SINK_ID)
            add_points(FEE_SINK_ID, +abs(fee_now), reason="wallet_fee", typ="fee")

        await state.clear()

        # إشعار فوري للمرسل
        await cb.answer(t(lang, "wallet.tx_done_toast", "تم تحويل النقاط بنجاح ✅"), show_alert=False)
        try:
            await _safe_edit(
                cb,
                text=(
                    L(lang,
                      "تم إرسال {amt} نقطة إلى {who}.\nالعمولة: {fee} — صافي المستلم: {net}.\n\n{bal}",
                      "Sent {amt} points to {who}.\nFee: {fee} — Recipient net: {net}.\n\n{bal}",
                    ).format(
                        amt=amount,
                        who=target_display,
                        fee=fee_now,
                        net=net_now,
                        bal=L(lang, "الرصيد الحالي: {pts} نقطة", "Current balance: {pts} points").format(pts=_points_of(uid)),
                    )
                ),
                kb=_kb_wallet(lang)
            )
        except Exception:
            pass

        # إشعار المستلم بلغته
        try:
            await cb.bot.send_message(
                chat_id=target_id,
                text=t(
                    _L(target_id),
                    "wallet.tx_in_notify_username",
                    "📥 وصلك {amt} نقطة من المستخدم {who}."
                ).format(amt=net_now, who=f"@{cb.from_user.username}" if cb.from_user.username else uid)
            )
        except Exception:
            pass

    # ✅ كابتشا أقوى عند التنفيذ + استئناف تلقائي
    await ensure_human_then(cb, level="high", resume=_do_confirm)

# ===================== Optional shortcuts =====================

@router.callback_query(F.data == "rwd:wal")
async def cb_open_wallet_short(cb: CallbackQuery):
    await open_wallet(cb, edit=True)
