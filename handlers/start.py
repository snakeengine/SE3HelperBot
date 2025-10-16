# handlers/start.py
from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from utils.rewards_store import register_referral

from utils.known_users import add_known_user
from lang import t, get_user_lang

# بطاقة الترحيب الجديدة (Hero Pro)
from handlers.home_hero import render_home_card

# ===== إعدادات عامة =====
VIP_PUBLIC_APPLY = os.getenv("VIP_PUBLIC_APPLY", "1").strip() not in ("0", "false", "False", "")

router = Router(name="start")

# 👇 خاص فقط لتقليل التعارض
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

# 👇 منع فتح القوائم أثناء الدردشة الحيّة
try:
    from handlers.live_chat import LiveChat
except Exception:
    class LiveChat:  # fallback آمن
        active = None

async def _is_live_active(state: FSMContext) -> bool:
    try:
        if not state:
            return False
        cur = await state.get_state()  # aiogram v3: coroutine
        want = getattr(LiveChat, "active", None)
        # بعض البيئات قد لا تملك .state لو fallback، نتأكد بأمان:
        target = getattr(want, "state", None)
        return bool(target and cur == target)
    except Exception:
        return False
# ===== استيرادات اختيارية مع fallback =====
try:
    from utils.user_stats import log_user
except Exception:
    def log_user(_user_id: int) -> None: return

try:
    from utils.maintenance_state import is_enabled as load_maintenance_mode
except Exception:
    def load_maintenance_mode() -> bool: return False

try:
    from handlers.update_announcements import send_update_if_needed
except Exception:
    async def send_update_if_needed(message: Message) -> None: return

try:
    from handlers.language import update_user_commands
except Exception:
    async def update_user_commands(bot, chat_id: int, lang: str) -> None: return

try:
    from utils.suppliers import is_supplier as _is_supplier_ext
except Exception:
    _is_supplier_ext = None

try:
    from utils.vip_store import is_vip as _is_vip, add_pending
except Exception:
    def _is_vip(_uid: int) -> bool: return False
    def add_pending(*_a, **_k): return None

try:
    from handlers.promoter import is_promoter as _is_promoter
except Exception:
    def _is_promoter(_uid: int) -> bool: return False

try:
    from handlers.vip import _admin_review_kb, ADMIN_IDS as _VIP_ADMIN_IDS
except Exception:
    _VIP_ADMIN_IDS = set()
    def _admin_review_kb(*_a, **_k):
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        return InlineKeyboardBuilder().as_markup()

# (اختياري) خريطة CB بسيطة للاستهلاك من ملفات أخرى إن احتاجت
CB = {
    "BOT_OPEN": "bot:open",
    "TRUSTED_SUPPLIERS": "trusted_suppliers",
    "VIP_BUY_INTERNAL": "shop:sevip",
}

def _L(uid: int) -> str:
    try:
        return get_user_lang(uid) or "ar"
    except Exception:
        return "ar"

def _fb(lang: str, ar: str, en: str) -> str:
    return en if str(lang).startswith("en") else ar

def _tt(lang: str, key: str, ar_fallback: str, en_fallback: str) -> str:
    try:
        v = t(lang, key)
        if isinstance(v, str) and v.strip() and v != key:
            return v
    except Exception:
        pass
    return _fb(lang, ar_fallback, en_fallback)

# ===== إعدادات الأدمن =====
def _load_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    ids |= set(_VIP_ADMIN_IDS) if _VIP_ADMIN_IDS else set()
    if not ids:
        ids = {7360982123}
    return ids

ADMIN_IDS = _load_admin_ids()

# ===== نموذج مستخدم =====
@dataclass
class UserMini:
    user_id: int
    first_name: str
    username: str | None
    role: str   # "user" | "supplier"
    lang: str   # "ar" | "en"

async def _get_user_mini(tg_user) -> UserMini:
    lang = get_user_lang(tg_user.id) or "en"
    role = "supplier" if (_is_supplier_ext and _is_supplier_ext(tg_user.id)) else "user"
    return UserMini(
        user_id=tg_user.id,
        first_name=tg_user.first_name or ("ضيف" if lang == "ar" else "Guest"),
        username=tg_user.username,
        lang=lang,
        role=role,
    )

# ===== واجهة الترحيب: كل العرض عبر بطاقة Hero Pro =====
async def _send_welcome_single_message(
    *,
    target_msg,      # Message أو CallbackQuery.message
    lang: str,
    user: UserMini,
    vip_real: bool,
    promoter_real: bool,
    vip_member: bool,
):
    await render_home_card(target_msg, lang=lang)

# ======================== /start ========================
@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    # لو فيه جلسة دردشة حية نشطة — لا تفتح القائمة، اطلب إنهاء الدردشة أولًا
    if await _is_live_active(state):
        lang = get_user_lang(message.from_user.id) or "ar"
        txt = ("⚠️ لديك جلسة دردشة حيّة مفتوحة.\n"
               "يرجى إنهاء الدردشة من الزر «❌ إنهاء الدردشة» أولًا للعودة للقائمة.")
        if lang != "ar":
            txt = "⚠️ You have an active live chat.\nPlease end the chat first (❌ End chat) to go back to the menu."
        await message.answer(txt)
        return

    await state.clear()

    # إخفاء أي لوحة رد سابقة (التبويبات /sections مثلاً)
    try:
        rm = await message.answer("\u2063", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass

    await _serve_home(message)

# في حال كان فيه أي حالة أخرى غير LiveChat، /start يلغيها ويعيدك للقائمة
@router.message(~StateFilter(None), F.text.regexp(r"^/start(\s|$)"))
async def start_handler_in_state(message: Message, state: FSMContext):
    if await _is_live_active(state):
        lang = get_user_lang(message.from_user.id) or "ar"
        txt = ("⚠️ لديك جلسة دردشة حيّة مفتوحة.\n"
               "يرجى إنهاء الدردشة من الزر «❌ إنهاء الدردشة» أولًا للعودة للقائمة.")
        if lang != "ar":
            txt = "⚠️ You have an active live chat.\nPlease end the chat first (❌ End chat) to go back to the menu."
        await message.answer(txt)
        return

    await state.clear()
    try:
        rm = await message.answer("\u2063", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass
    await _serve_home(message)

async def _serve_home(message: Message):
    user = await _get_user_mini(message.from_user)

    # صيانة
    if load_maintenance_mode() and (message.from_user.id not in ADMIN_IDS):
        await message.answer(
            (t(user.lang, "maintenance_active") or
             "🚧 The bot is currently under maintenance.\n🚧 البوت تحت الصيانة حالياً.\n\nالرجاء المحاولة لاحقاً. Please try again later."),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    # أعلام (موجودة للتوافق)
    try:
        vip_real = bool(_is_vip and _is_vip(user.user_id))
    except Exception:
        vip_real = False
    try:
        promoter_real = bool(_is_promoter and _is_promoter(user.user_id))
    except Exception:
        promoter_real = False

    await _send_welcome_single_message(
        target_msg=message,
        lang=user.lang,
        user=user,
        vip_real=vip_real,
        promoter_real=promoter_real,
        vip_member=vip_real,
    )

    # خلفية: سجل/قوائم/أوامر/إعلانات
    asyncio.create_task(asyncio.to_thread(log_user, message.from_user.id))
    asyncio.create_task(asyncio.to_thread(add_known_user, message.from_user.id))
    asyncio.create_task(update_user_commands(message.bot, message.chat.id, user.lang))
    asyncio.create_task(send_update_if_needed(message))

    # Deep-link VIP (vip:<app_id>)
    if VIP_PUBLIC_APPLY:
        parts = (message.text or "").strip().split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else None
        if payload and (payload.startswith("vip:") or payload.startswith("vip-")):
            app_id = payload[4:].strip()

            async def _vip_bg():
                try:
                    add_pending(user.user_id, app_id)
                    for admin_id in _load_admin_ids():
                        try:
                            await message.bot.send_message(
                                admin_id,
                                f"{t(user.lang, 'vip.admin.new_request_title')}\n"
                                f"👤 {t(user.lang,'vip.admin.user')}: <code>{user.user_id}</code>\n"
                                f"🆔 {t(user.lang,'vip.admin.app_id')}: <code>{app_id}</code>\n\n"
                                f"{t(user.lang,'vip.admin.instructions')}",
                                reply_markup=_admin_review_kb(user.user_id, app_id, user.lang),
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass
                    try:
                        await message.answer(t(user.lang, "vip.apply.sent"))
                    except Exception:
                        pass
                except Exception:
                    pass

            asyncio.create_task(_vip_bg())

    # ===== إحالات: ref_<inviter> =====
    try:
        parts2 = (message.text or "").strip().split(maxsplit=1)
        p2 = parts2[1].strip() if len(parts2) > 1 else ""
    except Exception:
        p2 = ""

    inviter = None
    if p2.startswith("ref_"):
        try:
            inviter = int(p2.split("ref_", 1)[1])
        except Exception:
            inviter = None

    if inviter and inviter != user.user_id:
        res = register_referral(inviter, user.user_id)
        if res.get("ok"):
            # إشعار المنضم (بلغة المنضم)
            lang_joiner = get_user_lang(user.user_id) or "ar"
            try:
                await message.answer(
                    (t(lang_joiner, "rwd.ref.joiner_award") or
                     ("🎉 Join bonus added: +{n} points."
                      if str(lang_joiner).startswith("en")
                      else "🎉 تمت إضافة مكافأة الانضمام: +{n} نقطة.")
                    ).format(n=int(res.get("joiner_awarded") or 0))
                )
            except Exception:
                pass

            # عند كل 5 دعوات ناجحة: إشعار الداعي
            inviter_aw = int(res.get("inviter_awarded") or 0)
            if inviter_aw > 0:
                lang_inviter = get_user_lang(inviter) or "ar"
                try:
                    await message.bot.send_message(
                        inviter,
                        (t(lang_inviter, "rwd.ref.inviter_milestone") or
                         ("👥 Congrats! You've reached {count} successful invites.\n🎁 Milestone reward: +{n} points."
                          if str(lang_inviter).startswith("en")
                          else "👥 تهانينا! وصلت إلى {count} دعوة ناجحة.\n🎁 مكافأة المستوى: +{n} نقاط.")
                        ).format(
                            count=int(res.get("inviter_ref_count") or 0),
                            n=inviter_aw
                        )
                    )
                except Exception:
                    pass


# ===== زر رجوع عام =====
@router.callback_query(F.data.in_({"back_to_menu", "home"}))
async def back_to_menu_handler(callback: CallbackQuery, state: FSMContext):
    # لا نعرض القائمة أثناء الدردشة الحيّة
    if await _is_live_active(state):
        lang = get_user_lang(callback.from_user.id) or "ar"
        txt = ("⚠️ لديك جلسة دردشة حيّة مفتوحة.\n"
               "يرجى إنهاء الدردشة من الزر «❌ إنهاء الدردشة» أولًا للعودة للقائمة.")
        if lang != "ar":
            txt = "⚠️ You have an active live chat.\nPlease end the chat first (❌ End chat) to go back to the menu."
        await callback.answer()
        try:
            await callback.message.answer(txt)
        except Exception:
            pass
        return

    await state.clear()
    try:
        rm = await callback.message.answer("\u2063", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass

    user = await _get_user_mini(callback.from_user)

    try:
        vip_real = bool(_is_vip and _is_vip(user.user_id))
    except Exception:
        vip_real = False
    try:
        promoter_real = bool(_is_promoter and _is_promoter(user.user_id))
    except Exception:
        promoter_real = False

    await _send_welcome_single_message(
        target_msg=callback.message,
        lang=user.lang,
        user=user,
        vip_real=vip_real,
        promoter_real=promoter_real,
        vip_member=vip_real,
    )

    asyncio.create_task(update_user_commands(callback.message.bot, callback.message.chat.id, user.lang))
    await callback.answer()
