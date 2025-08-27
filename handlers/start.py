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

from utils.known_users import add_known_user
from lang import t, get_user_lang

# بطاقة الترحيب الجديدة (Hero Pro)
from handlers.home_hero import render_home_card

# ===== إعدادات عامة =====
VIP_PUBLIC_APPLY = os.getenv("VIP_PUBLIC_APPLY", "1").strip() not in ("0", "false", "False", "")

router = Router(name="start")

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
    role: str   # "user" | "supplier" | "pending" | "banned"
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
    await render_home_card(target_msg)

# ======================== /start ========================
@router.message(CommandStart(), StateFilter(None))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    # إخفاء أي لوحة رد سابقة (التبويبات /sections مثلاً)
    try:
        rm = await message.answer("\u2063", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass

    await _serve_home(message)

@router.message(~StateFilter(None), F.text.regexp(r"^/start(\s|$)"))
async def start_handler_in_state(message: Message, state: FSMContext):
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

    # أعلام (موجودة للتوافق؛ البطاقة نفسها تقرأ الحالة داخليًا عند الحاجة)
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

    # خلفية: سجل المستخدم، قائمة معروفة، أوامر السلاش، إعلانات
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

# ===== زر رجوع عام =====
@router.callback_query(F.data.in_({"back_to_menu", "home"}))
async def back_to_menu_handler(callback: CallbackQuery, state: FSMContext):
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
