from __future__ import annotations

# handlers/rewards_hub.py


from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang
from utils.rewards_store import get_points, ensure_user, can_do
from utils.daily_guard import try_claim_daily  # ✅ المطالبة اليومية (24 ساعة حقيقية)
from .rewards_gate import require_membership
# أعلى الملف مع الاستيرادات
from aiogram.filters import StateFilter
from handlers.live_chat import LiveChat


# ✅ كابتشا بشرية + الاستئناف بعد النجاح (مع Fallbackات آمنة)
try:
    from handlers.human_check import require_human, ensure_human_then  # type: ignore
except Exception:
    async def require_human(msg_or_cb, level: str = "normal") -> bool:
        return True
    async def ensure_human_then(msg_or_cb, level: str, resume):  # يكمّل فورًا كبديل
        if await require_human(msg_or_cb, level=level):
            await resume(msg_or_cb)
            return True
        return False

router = Router(name="rewards_hub")
# امنع التنفيذ أثناء جلسة الدردشة الحيّة، واشتغل بالخاص فقط
router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
router.callback_query.filter(F.message.chat.type == "private", ~StateFilter(LiveChat.active))

# امنع التداخل مع الدردشة الحيّة + احصر الكولباكات على rwd:
router.message.filter(
    F.chat.type == "private",
    ~StateFilter(LiveChat.active)
)
router.callback_query.filter(
    F.message.chat.type == "private",
    ~StateFilter(LiveChat.active),
    F.data.func(lambda s: isinstance(s, str) and s.startswith("rwd:"))
)

# ===================== Helpers =====================

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tt(lang: str, key: str, fallback: str) -> str:
    """ترجمة آمنة: إن رجع t() نفس المفتاح أو نصًا فارغًا -> استخدم fallback."""
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fallback

def _hub_kb(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tt(lang, "rewards.hub.wallet",  "👛 محفظتي"), callback_data="rwd:hub:wallet"),
        InlineKeyboardButton(text=_tt(lang, "rewards.hub.market",  "🎁 المتجر"),  callback_data="rwd:hub:market"),
    )
    kb.row(InlineKeyboardButton(text=_tt(lang, "rewards.hub.profile", "👤 ملفي"), callback_data="rwd:hub:profile"))
    kb.row(InlineKeyboardButton(text=_tt(lang, "rewards.hub.how",    "ℹ️ شرح الاستخدام"), callback_data="rwd:hub:how"))
    kb.row(InlineKeyboardButton(text=_tt(lang, "rewards.hub.daily",  "🎯 نقاط يومية"),     callback_data="rwd:hub:daily"))
    return kb

# ===================== Profile Bridge =====================

async def _open_profile_via_module(msg_or_cb: Message | CallbackQuery, edit: bool = False) -> bool:
    """
    يحاول فتح بروفايل الجوائز من rewards_profile_pro بعد التحقق من العضوية.
    يرجع True إذا تم التعامل (سواء نجح/فشل مع بوابة العضوية)، وFalse للعودة لـHub.
    """
    if await require_membership(msg_or_cb) is False:
        return True  # تم منع المستخدم بواسطة بوابة الاشتراك

    try:
        from . import rewards_profile_pro as _pro
    except Exception:
        return False  # لا توجد وحدة البروفايل

    try:
        if hasattr(_pro, "open_profile"):
            await _pro.open_profile(msg_or_cb, edit=edit)
        elif hasattr(_pro, "show_profile"):
            await _pro.show_profile(msg_or_cb, edit=edit)
        elif hasattr(_pro, "open"):
            await _pro.open(msg_or_cb, edit=edit)
        else:
            return False
        return True
    except Exception:
        # أي خطأ داخلي -> ارجع للـHub
        return False

# ===================== Hub =====================

async def open_hub(msg_or_cb: Message | CallbackQuery, edit: bool = False):
    """نحاول أولًا فتح البروفايل؛ عند الفشل نعرض الهَب التقليدي."""
    # 👇 افتح البروفايل مباشرة
    opened = await _open_profile_via_module(msg_or_cb, edit=edit)
    if opened:
        return

    # الهَب التقليدي (fallback)
    uid = msg_or_cb.from_user.id
    lang = _L(uid)
    if await require_membership(msg_or_cb) is False:
        return

    ensure_user(uid)
    pts = get_points(uid)
    title = _tt(lang, "rewards.hub.title",   "🎉 أهلاً بك في الجوائز!")
    bal   = _tt(lang, "rewards.hub.balance", "رصيدك الحالي: {points}").format(points=pts)
    text = f"{title}\n{bal}"

    kb = _hub_kb(lang).as_markup()
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text, reply_markup=kb)
    else:
        if edit and msg_or_cb.message:
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
        else:
            await msg_or_cb.answer(text)

# ===================== Routes =====================

@router.message(Command("rewards_hub"))
async def cmd_rewards_hub(m: Message):
    await open_hub(m)

@router.callback_query(F.data == "rwd:hub")
async def cb_hub_root(cb: CallbackQuery):
    await open_hub(cb, edit=True)

@router.callback_query(F.data == "rwd:hub:profile")
async def cb_open_profile(cb: CallbackQuery):
    await _open_profile_via_module(cb, edit=True)

@router.callback_query(F.data == "rwd:hub:how")
async def cb_how(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    if await require_membership(cb) is False:
        return
    text = _tt(
        lang, "rewards.hub.how_text",
        "• اشترك بالقنوات الإلزامية.\n• اجمع نقاطك من المهام والمتجر.\n• استخدم رصيدك للشراء أو التحويل."
    )
    await cb.message.edit_text(text, reply_markup=_hub_kb(lang).as_markup())

@router.callback_query(F.data == "rwd:hub:daily")
async def cb_daily(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)

    # 1) تحقق الاشتراك الإلزامي
    if await require_membership(cb) is False:
        return

    # 2) تبريد بسيط حتى لا يضغط بسرعة
    if not can_do(uid, "daily_click", cooldown_sec=20):
        return await cb.answer(_tt(lang, "common.slow_down", "تمهل قليلًا.."), show_alert=True)

    # 3) ✅ كابتشا + استئناف تلقائي بعد النجاح
    async def _do_daily(_ev: CallbackQuery | Message):
        ok, msg = try_claim_daily(uid)  # يرجع (success, رسالة مترجمة)
        await cb.answer(msg, show_alert=not ok)
        await open_hub(cb, edit=True)

    await ensure_human_then(cb, level="normal", resume=_do_daily)

@router.callback_query(F.data == "rwd:hub:market")
async def cb_open_market(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return

    async def _go(_ev: CallbackQuery | Message):
        from . import rewards_market as _mkt
        await _mkt.open_market(cb)

    await ensure_human_then(cb, level="normal", resume=_go)

@router.callback_query(F.data == "rwd:hub:wallet")
async def cb_open_wallet(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return
    from . import rewards_wallet as _w
    await _w.open_wallet(cb)
