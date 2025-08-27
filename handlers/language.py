# handlers/language.py
from __future__ import annotations

import os
from typing import List

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeChat
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

# ⬅️ استخدم التخزين المركزي للغة من lang.py
from lang import t, get_user_lang, set_user_lang
from handlers.persistent_menu import make_bottom_kb  # لإظهار الكيبورد السفلي مباشرة

router = Router()

# ===== إعدادات اللغات =====
SUPPORTED_LOCALES = ("en", "ar")
DEFAULT_LOCALE = "en"

# تحكم بإظهار رسالة الكيبورد السفلي بعد تغيير اللغة (من .env)
SHOW_MENU_ON_LANG_CHANGE = (os.getenv("SHOW_MENU_ON_LANG_CHANGE") or "0").strip().lower() not in {
    "0", "false", "no", "off", ""
}

# ===== تحميل قائمة الأدمن من .env =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

# ===== أوامر البوت حسب اللغة =====
def _public_commands(lang: str) -> List[BotCommand]:
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    return [
        BotCommand(command="start",     description=t(lang, "cmd_start")),
        BotCommand(command="sections",  description=t(lang, "cmd_sections")),
        BotCommand(command="help",      description=t(lang, "cmd_help")),
        BotCommand(command="about",     description=t(lang, "cmd_about")),
        BotCommand(command="alerts",    description=t(lang, "cmd_alerts")),
        BotCommand(command="report",    description=t(lang, "cmd_report")),
        BotCommand(command="language",  description=t(lang, "cmd_language")),
    ]

def _admin_extra_commands(lang: str) -> List[BotCommand]:
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    return [
        BotCommand(command="admin", description=t(lang, "cmd_admin_center")),
    ]

async def update_user_commands(bot, chat_id: int, lang: str) -> None:
    is_admin = int(chat_id) in ADMIN_IDS
    cmds = _public_commands(lang)
    if is_admin:
        cmds += _admin_extra_commands(lang)

    # امسح أوامر هذه المحادثة ثم اضبطها
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:
        pass

    await bot.set_my_commands(
        commands=cmds,
        scope=BotCommandScopeChat(chat_id=chat_id)
    )

# ===== لوحات المفاتيح =====
def language_keyboard(display_lang: str, selected_lang: str) -> InlineKeyboardMarkup:
    display_lang = display_lang if display_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    selected_lang = selected_lang if selected_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE

    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if selected_lang == "en" else "") + t(display_lang, "btn_lang_en"),
                callback_data="set_lang_en"
            ),
            InlineKeyboardButton(
                text=("✅ " if selected_lang == "ar" else "") + t(display_lang, "btn_lang_ar"),
                callback_data="set_lang_ar"
            ),
        ],
        [InlineKeyboardButton(text=t(display_lang, "back_to_menu"), callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== مساعد: تعديل ذكي مع fallback =====
async def smart_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """
    يحاول تعديل نفس الرسالة إن كان فيها نص/وصف، وإلا يرسل رسالة جديدة.
    كما يتعامل مع أخطاء 'there is no text in the message to edit' و 'message is not modified'.
    """
    try:
        if message.text is not None:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        if message.caption is not None:
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        # لا نص ولا وصف → أرسل رسالة جديدة
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "there is no text in the message to edit" in msg or "message is not modified" in msg:
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        raise

# ===== الأوامر/الكولباكات =====
@router.message(Command("language"))
async def language_command(message: Message):
    lang = get_user_lang(message.from_user.id) or DEFAULT_LOCALE
    await message.answer(
        t(lang, "choose_language"),
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
        t(lang, "choose_language"),
        language_keyboard(display_lang=lang, selected_lang=lang),
    )
    await callback.answer()

@router.callback_query(F.data.in_({"set_lang_en", "set_lang_ar"}))
async def set_language_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_lang = "en" if callback.data.endswith("_en") else "ar"

    # احفظ اللغة وحدث أوامر هذه الدردشة
    set_user_lang(user_id, new_lang)
    await update_user_commands(callback.message.bot, callback.message.chat.id, new_lang)

    # عدّل رسالة اختيار اللغة
    await smart_edit(
        callback.message,
        t(new_lang, "language_changed"),
        language_keyboard(display_lang=new_lang, selected_lang=new_lang),
    )

    # (اختياري) أرسل الكيبورد السفلي فورًا باللغة الجديدة
    if SHOW_MENU_ON_LANG_CHANGE:
        await callback.message.answer(
            t(new_lang, "menu.keyboard_ready") or ("تم تجهيز القائمة بالأسفل ⬇️" if new_lang == "ar" else "Menu ready ⬇️"),
            reply_markup=make_bottom_kb(new_lang),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    await callback.answer()
