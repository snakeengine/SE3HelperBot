# handlers/start.py
from __future__ import annotations

import os
from dataclasses import dataclass

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import StateFilter

from lang import t, get_user_lang

# ===== إعداد تشغيل VIP العامة =====
VIP_PUBLIC_APPLY = os.getenv("VIP_PUBLIC_APPLY", "1").strip() not in ("0", "false", "False", "")

router = Router(name="start")

# ===== استيرادات اختيارية مع fallback حتى لا يفشل الراوتر =====
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
    from handlers.safe_usage import SAFE_USAGE_CB
except Exception:
    SAFE_USAGE_CB = "safe_usage:open"

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
    def add_pending(*args, **kwargs): return None

# ⇩⇩ برنامج المروّجين
try:
    from handlers.promoter import is_promoter as _is_promoter, PROMOTER_INFO_CB, PROMOTER_PANEL_CB
except Exception:
    def _is_promoter(_uid: int) -> bool: return False
    PROMOTER_INFO_CB = "prom:info"
    PROMOTER_PANEL_CB = "prom:panel"

# لإرسال لوحة مراجعة طلب VIP للأدمنين
try:
    from handlers.vip import _admin_review_kb, ADMIN_IDS as _VIP_ADMIN_IDS, _is_valid_app_id as _vip_is_valid_app_id
except Exception:
    _VIP_ADMIN_IDS = set()
    def _admin_review_kb(*args, **kwargs):
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        return InlineKeyboardBuilder().as_markup()
    import re as _re
    _NUMERIC_RX = _re.compile(r"^\d{4,10}$")
    _GENERIC_RX = _re.compile(r"^[A-Za-z0-9._\\-]{3,80}$")
    def _vip_is_valid_app_id(text: str) -> bool:
        s = (text or "").strip()
        return bool(_NUMERIC_RX.fullmatch(s) or _GENERIC_RX.fullmatch(s))

# ===== إعدادات عامة =====
RESELLER_INFO_CB = "reseller_info"  # زر معلومات كيف تصبح مورّدًا

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

# ترجمة آمنة مع fallback
def _t_safe(lang: str, key: str, fallback: str) -> str:
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip():
            return val
    except Exception:
        pass
    return fallback

# ===== نموذج مستخدم مبسّط =====
@dataclass
class UserMini:
    user_id: int
    first_name: str
    username: str | None
    role: str           # "user" | "supplier" | "pending" | "banned"
    lang: str           # "ar" | "en"

async def _get_user_mini(tg_user) -> UserMini:
    lang = get_user_lang(tg_user.id) or "ar"
    role = "supplier" if (_is_supplier_ext and _is_supplier_ext(tg_user.id)) else "user"
    return UserMini(
        user_id=tg_user.id,
        first_name=tg_user.first_name or ("ضيف" if lang == "ar" else "Guest"),
        username=tg_user.username,
        role=role,
        lang=lang,
    )

def _role_key(role: str) -> str:
    return {
        "supplier": "role_supplier",
        "pending": "role_pending",
        "banned": "role_banned",
        "user": "role_user",
    }.get(role, "role_user")

def _maintenance_notice(lang: str) -> str:
    try:
        txt = t(lang, "maintenance_active")
        if isinstance(txt, str) and txt.strip(): return txt
    except Exception:
        pass
    try:
        txt = t(lang, "maintenance.notice")
        if isinstance(txt, str) and txt.strip(): return txt
    except Exception:
        pass
    return (
        "🚧 The bot is currently under maintenance.\n"
        "🚧 البوت تحت الصيانة حالياً.\n\n"
        "الرجاء المحاولة لاحقاً. Please try again later."
    )

# ===== التقاط حمولة /start للديب-لينك vip:<APP_ID> =====
def _parse_start_payload(message_text: str) -> str | None:
    if not message_text:
        return None
    parts = message_text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if payload.startswith("vip:"):
        return payload[4:].strip()
    if payload.startswith("vip-"):
        return payload[4:].strip()
    return None

# ===== نص الواجهة =====
def build_home_caption(u: UserMini) -> str:
    uname = f"@{u.username}" if u.username else f"ID:{u.user_id}"
    return (
        f"<b>{t(u.lang, 'home_title')}</b>\n"
        f"{t(u.lang, 'hello').format(name=u.first_name, uname=uname)}\n"
        f"{t(u.lang, _role_key(u.role))}\n\n"
        f"{t(u.lang, 'pitch')}\n"
        f"{t(u.lang, 'safety')}\n\n"
        f"{t(u.lang, 'cta')}"
    )

# ===== لوحة البداية =====
def build_start_keyboard(lang: str, role: str = "user", vip_member: bool = False, *, user_id: int | None = None):
    kb = InlineKeyboardBuilder()

    def row(*buttons: InlineKeyboardButton):
        kb.row(*buttons)

    def header(text: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data="ui:sep")

    if role == "supplier":
        row(header("🔧 " + _t_safe(lang, "sec_supplier_title", "أدوات المورّد")))
        row(
            InlineKeyboardButton(text="🗂 " + _t_safe(lang, "btn_my_profile", "ملفي"),     callback_data="my_profile"),
            InlineKeyboardButton(text="🔑 " + _t_safe(lang, "btn_my_keys", "مفاتيحي"),     callback_data="my_keys"),
        )
        row(
            InlineKeyboardButton(text="🧾 " + _t_safe(lang, "btn_my_activations", "تفعيلاتي"), callback_data="my_acts"),
            InlineKeyboardButton(text="🪪 " + _t_safe(lang, "btn_supplier_public", "بطاقتي"),   callback_data="supplier_public"),
        )

    row(header("🧭 " + _t_safe(lang, "sec_user_title", "القائمة العامة")))
    row(
        InlineKeyboardButton(text="🧰 " + _t_safe(lang, "btn_tools", "أدوات"),    callback_data="tools"),
        InlineKeyboardButton(text="📥 " + _t_safe(lang, "btn_download", "تحميل تطبيق الثعبان"), callback_data="app:download"),
    )

    if role != "supplier":
        row(
            InlineKeyboardButton(text="📦 " + _t_safe(lang, "btn_be_supplier_short", "كن مورّدًا"), callback_data=RESELLER_INFO_CB),
            InlineKeyboardButton(text="🏷️ " + _t_safe(lang, "btn_trusted_suppliers", "الموردون الموثوقون"), callback_data="trusted_suppliers"),
        )
    else:
        row(
            InlineKeyboardButton(text="🏷️ " + _t_safe(lang, "btn_trusted_suppliers", "الموردون الموثوقون"), callback_data="trusted_suppliers"),
            InlineKeyboardButton(text="📱 " + _t_safe(lang, "btn_check_device", "تحقق من جهازك"),              callback_data="check_device"),
        )

    # VIP
    if VIP_PUBLIC_APPLY:
        if not vip_member:
            row(InlineKeyboardButton(text=t(lang, "btn_vip_subscribe"), callback_data="vip:open"))
        else:
            row(InlineKeyboardButton(text="👑 " + t(lang, "btn_vip_panel"), callback_data="vip:open_tools"))

    # الأمان + الدليل
    row(
        InlineKeyboardButton(text=_t_safe(lang, "btn_security", "حالة الأمان"),   callback_data="security_status"),
        InlineKeyboardButton(text=_t_safe(lang, "btn_safe_usage", "دليل الاستخدام الآمن"), callback_data=SAFE_USAGE_CB),
    )
    row(
        InlineKeyboardButton(text="📊 " + _t_safe(lang, "btn_server_status", "حالة السيرفرات"), callback_data="server_status"),
        InlineKeyboardButton(text="🌐 " + _t_safe(lang, "btn_lang", "تغيير اللغة"),              callback_data="change_lang"),
    )

    # --- برنامج المروّجين ---
    approved_promoter = False
    try:
        if user_id is not None:
            approved_promoter = _is_promoter(user_id)
    except Exception:
        approved_promoter = False

    if not approved_promoter:
        # يظهر زر "كيف تصبح مروّجًا؟" لمن لم تتم الموافقة عليهم
        row(InlineKeyboardButton(text=_t_safe(lang, "btn_be_promoter", "كيف تصبح مروّجًا؟"), callback_data=PROMOTER_INFO_CB))
    else:
        # بعد الموافقة يظهر زر "لوحة المروّجين"
        row(InlineKeyboardButton(text=_t_safe(lang, "btn_promoter_panel", "لوحة المروّجين"), callback_data=PROMOTER_PANEL_CB))

    return kb.as_markup()

@router.callback_query(F.data == "ui:sep")
async def _ignore_section_sep(cb: CallbackQuery):
    await cb.answer()

# ======================== /start ========================
# 1) /start خارج أي حالة
@router.message(CommandStart(), StateFilter(None))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await _serve_home(message, state)

# 2) /start داخل أي حالة (fallback مضمون)
@router.message(~StateFilter(None), F.text.regexp(r"^/start(\s|$)"))
async def start_handler_in_state(message: Message, state: FSMContext):
    await state.clear()
    await _serve_home(message, state)

async def _serve_home(message: Message, state: FSMContext):
    log_user(message.from_user.id)

    user = await _get_user_mini(message.from_user)
    vip_member = _is_vip(user.user_id)
    await update_user_commands(message.bot, message.chat.id, user.lang)

    if load_maintenance_mode() and (message.from_user.id not in ADMIN_IDS):
        await message.answer(
            _maintenance_notice(user.lang),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if VIP_PUBLIC_APPLY:
        payload_app_id = _parse_start_payload(message.text or "")
        if payload_app_id and _vip_is_valid_app_id(payload_app_id):
            add_pending(user.user_id, payload_app_id)
            lang = user.lang or "en"
            for admin_id in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"{t(lang, 'vip.admin.new_request_title')}\n"
                        f"👤 {t(lang,'vip.admin.user')}: <code>{user.user_id}</code>\n"
                        f"🆔 {t(lang,'vip.admin.app_id')}: <code>{payload_app_id}</code>\n\n"
                        f"{t(lang,'vip.admin.instructions')}",
                        reply_markup=_admin_review_kb(user.user_id, payload_app_id, lang),
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            await message.answer(t(lang, "vip.apply.sent"))

    await send_update_if_needed(message)

    await message.answer(
        build_home_caption(user),
        reply_markup=build_start_keyboard(user.lang, user.role, vip_member=vip_member, user_id=user.user_id),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

# ===== زر رجوع عام =====
@router.callback_query(F.data.in_({"back_to_menu", "home"}))
async def back_to_menu_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await _get_user_mini(callback.from_user)
    vip_member = _is_vip(user.user_id)
    await update_user_commands(callback.message.bot, callback.message.chat.id, user.lang)

    await callback.message.edit_text(
        build_home_caption(user),
        reply_markup=build_start_keyboard(user.lang, user.role, vip_member=vip_member, user_id=user.user_id),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await callback.answer()
