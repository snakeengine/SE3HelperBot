# handlers/language.py
from __future__ import annotations

import os
from typing import List, Tuple

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeChat
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang, set_user_lang
from handlers.persistent_menu import make_bottom_kb

router = Router()

# ===== إعدادات اللغات =====
SUPPORTED_LOCALES = ("en", "ar")
DEFAULT_LOCALE = "en"

SHOW_MENU_ON_LANG_CHANGE = (os.getenv("SHOW_MENU_ON_LANG_CHANGE") or "0").strip().lower() not in {
    "0", "false", "no", "off", ""
}

# ===== تحميل قائمة الأدمن من .env =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

# ===== ترجمة آمنة مع fallback محلي =====
def _tt(lang: str, key: str, fb: str) -> str:
    """إذا كانت الترجمة مفقودة/فارغة/ترجع نفس المفتاح -> استخدم fb."""
    try:
        v = t(lang, key)
        if isinstance(v, str):
            v = v.strip()
            if v and v != key:
                return v
    except Exception:
        pass
    return fb

def _loc(lang: str, ar: str, en: str) -> str:
    return ar if lang == "ar" else en

# ===== أوامر البوت حسب اللغة (مع fallbacks) =====
def _public_commands(lang: str) -> List[BotCommand]:
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    pairs: List[Tuple[str, str]] = [
        ("start",    _tt(lang, "cmd_start",    _loc(lang, "ابدأ البوت", "Start the bot"))),
        ("sections", _tt(lang, "cmd_sections", _loc(lang, "الأقسام السريعة", "Quick sections"))),
        ("rewards",  _tt(lang, "cmd_rewards",  _loc(lang, "الجوائز", "Open rewards"))),
        ("help",     _tt(lang, "cmd_help",     _loc(lang, "المساعدة والقائمة", "Help & menu"))),
        ("about",    _tt(lang, "cmd_about",    _loc(lang, "عن الخدمة", "About"))),
        ("alerts",   _tt(lang, "cmd_alerts",   _loc(lang, "التنبيهات", "Alerts"))),
        ("report",   _tt(lang, "cmd_report",   _loc(lang, "الإبلاغ والدعم", "Report / Support"))),
        ("language", _tt(lang, "cmd_language", _loc(lang, "تغيير اللغة", "Change language"))),
    ]
    # تجاهل أي عنصر وصفه فاضي بعد الفلترة
    return [BotCommand(command=c, description=d) for c, d in pairs if c and d and d.strip()]

def _admin_extra_commands(lang: str) -> List[BotCommand]:
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    desc = _tt(lang, "cmd_admin_center", _loc(lang, "لوحة الإدارة", "Admin center"))
    return [BotCommand(command="admin", description=desc)] if desc.strip() else []

async def update_user_commands(bot, chat_id: int, lang: str) -> None:
    """يضبط أوامر هذه الدردشة فقط، ويتجاهل الوصف الفارغ بدون أن يكرّش."""
    is_admin = int(chat_id) in ADMIN_IDS
    cmds = _public_commands(lang)
    if is_admin:
        cmds += _admin_extra_commands(lang)

    # امسح أوامر هذه المحادثة ثم اضبط الجديدة
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:
        pass

    try:
        await bot.set_my_commands(commands=cmds, scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception as e:
        # سجل الخطأ فقط بدون تعطيل التفاعل
        import logging
        logging.getLogger(__name__).warning(f"set_my_commands failed: {e}")

# ===== لوحات المفاتيح =====
def language_keyboard(display_lang: str, selected_lang: str) -> InlineKeyboardMarkup:
    display_lang = display_lang if display_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    selected_lang = selected_lang if selected_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE

    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if selected_lang == "en" else "") + _tt(display_lang, "btn_lang_en", "English"),
                callback_data="set_lang_en"
            ),
            InlineKeyboardButton(
                text=("✅ " if selected_lang == "ar" else "") + _tt(display_lang, "btn_lang_ar", "العربية"),
                callback_data="set_lang_ar"
            ),
        ],
        [InlineKeyboardButton(text=_tt(display_lang, "back_to_menu", _loc(display_lang, "رجوع", "Back")), callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== مساعد: تعديل ذكي مع fallback =====
async def smart_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    try:
        if message.text is not None:
            return await message.edit_text(
                text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True
            )
        if message.caption is not None:
            return await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="HTML")
        return await message.answer(text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "there is no text in the message to edit" in msg or "message is not modified" in msg:
            return await message.answer(text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)
        raise

# ===== الأوامر/الكولباكات =====
@router.message(Command("language"))
async def language_command(message: Message):
    lang = get_user_lang(message.from_user.id) or DEFAULT_LOCALE
    await message.answer(
        _tt(lang, "choose_language", _loc(lang, "اختر لغتك:", "Choose your language:")),
        reply_markup=language_keyboard(display_lang=lang, selected_lang=lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )

@router.callback_query(F.data == "change_lang")
async def change_lang(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id) or DEFAULT_LOCALE
    await smart_edit(
        callback.message,
        _tt(lang, "choose_language", _loc(lang, "اختر لغتك:", "Choose your language:")),
        language_keyboard(display_lang=lang, selected_lang=lang),
    )
    await callback.answer()

@router.callback_query(F.data.in_({"set_lang_en", "set_lang_ar"}))
async def set_language_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_lang = "en" if callback.data.endswith("_en") else "ar"

    set_user_lang(user_id, new_lang)
    await update_user_commands(callback.message.bot, callback.message.chat.id, new_lang)

    await smart_edit(
        callback.message,
        _tt(new_lang, "language_changed", _loc(new_lang, "تم تغيير اللغة ✅", "Language changed ✅")),
        language_keyboard(display_lang=new_lang, selected_lang=new_lang),
    )

    if SHOW_MENU_ON_LANG_CHANGE:
        await callback.message.answer(
            _tt(new_lang, "menu.keyboard_ready", _loc(new_lang, "تم تجهيز القائمة بالأسفل ⬇️", "Menu ready ⬇️")),
            reply_markup=make_bottom_kb(new_lang),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    await callback.answer()
