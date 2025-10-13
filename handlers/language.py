from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/language.py


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

# ===== Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø§Ù„Ù„ØºØ§Øª =====
SUPPORTED_LOCALES = ("en", "ar")
DEFAULT_LOCALE = "en"

SHOW_MENU_ON_LANG_CHANGE = (os.getenv("SHOW_MENU_ON_LANG_CHANGE") or "0").strip().lower() not in {
    "0", "false", "no", "off", ""
}

# ===== ØªØ­Ù…ÙŠÙ„ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø£Ø¯Ù…Ù† Ù…Ù† .env =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids()
if not ADMIN_IDS:
    ADMIN_IDS = get_admin_ids()

# ===== ØªØ±Ø¬Ù…Ø© Ø¢Ù…Ù†Ø© Ù…Ø¹ fallback Ù…Ø­Ù„ÙŠ =====
def _tt(lang: str, key: str, fb: str) -> str:
    """Ø¥Ø°Ø§ ÙƒØ§Ù†Øª Ø§Ù„ØªØ±Ø¬Ù…Ø© Ù…ÙÙ‚ÙˆØ¯Ø©/ÙØ§Ø±ØºØ©/ØªØ±Ø¬Ø¹ Ù†ÙØ³ Ø§Ù„Ù…ÙØªØ§Ø­ -> Ø§Ø³ØªØ®Ø¯Ù… fb."""
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

# ===== Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø¨ÙˆØª Ø­Ø³Ø¨ Ø§Ù„Ù„ØºØ© (Ù…Ø¹ fallbacks) =====
def _public_commands(lang: str) -> List[BotCommand]:
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    pairs: List[Tuple[str, str]] = [
        ("start",    _tt(lang, "cmd_start",    _loc(lang, "Ø§Ø¨Ø¯Ø£ Ø§Ù„Ø¨ÙˆØª", "Start the bot"))),
        ("sections", _tt(lang, "cmd_sections", _loc(lang, "Ø§Ù„Ø£Ù‚Ø³Ø§Ù… Ø§Ù„Ø³Ø±ÙŠØ¹Ø©", "Quick sections"))),
        ("rewards",  _tt(lang, "cmd_rewards",  _loc(lang, "Ø§Ù„Ø¬ÙˆØ§Ø¦Ø²", "Open rewards"))),
        ("help",     _tt(lang, "cmd_help",     _loc(lang, "Ø§Ù„Ù…Ø³Ø§Ø¹Ø¯Ø© ÙˆØ§Ù„Ù‚Ø§Ø¦Ù…Ø©", "Help & menu"))),
        ("about",    _tt(lang, "cmd_about",    _loc(lang, "Ø¹Ù† Ø§Ù„Ø®Ø¯Ù…Ø©", "About"))),
        ("alerts",   _tt(lang, "cmd_alerts",   _loc(lang, "Ø§Ù„ØªÙ†Ø¨ÙŠÙ‡Ø§Øª", "Alerts"))),
        ("report",   _tt(lang, "cmd_report",   _loc(lang, "Ø§Ù„Ø¥Ø¨Ù„Ø§Øº ÙˆØ§Ù„Ø¯Ø¹Ù…", "Report / Support"))),
        ("language", _tt(lang, "cmd_language", _loc(lang, "ØªØºÙŠÙŠØ± Ø§Ù„Ù„ØºØ©", "Change language"))),
    ]
    # ØªØ¬Ø§Ù‡Ù„ Ø£ÙŠ Ø¹Ù†ØµØ± ÙˆØµÙÙ‡ ÙØ§Ø¶ÙŠ Ø¨Ø¹Ø¯ Ø§Ù„ÙÙ„ØªØ±Ø©
    return [BotCommand(command=c, description=d) for c, d in pairs if c and d and d.strip()]

def _admin_extra_commands(lang: str) -> List[BotCommand]:
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    desc = _tt(lang, "cmd_admin_center", _loc(lang, "Ù„ÙˆØ­Ø© Ø§Ù„Ø¥Ø¯Ø§Ø±Ø©", "Admin center"))
    return [BotCommand(command="admin", description=desc)] if desc.strip() else []

async def update_user_commands(bot, chat_id: int, lang: str) -> None:
    """ÙŠØ¶Ø¨Ø· Ø£ÙˆØ§Ù…Ø± Ù‡Ø°Ù‡ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© ÙÙ‚Ø·ØŒ ÙˆÙŠØªØ¬Ø§Ù‡Ù„ Ø§Ù„ÙˆØµÙ Ø§Ù„ÙØ§Ø±Øº Ø¨Ø¯ÙˆÙ† Ø£Ù† ÙŠÙƒØ±Ù‘Ø´."""
    is_admin = int(chat_id) in ADMIN_IDS
    cmds = _public_commands(lang)
    if is_admin:
        cmds += _admin_extra_commands(lang)

    # Ø§Ù…Ø³Ø­ Ø£ÙˆØ§Ù…Ø± Ù‡Ø°Ù‡ Ø§Ù„Ù…Ø­Ø§Ø¯Ø«Ø© Ø«Ù… Ø§Ø¶Ø¨Ø· Ø§Ù„Ø¬Ø¯ÙŠØ¯Ø©
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:
        pass

    try:
        await bot.set_my_commands(commands=cmds, scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception as e:
        # Ø³Ø¬Ù„ Ø§Ù„Ø®Ø·Ø£ ÙÙ‚Ø· Ø¨Ø¯ÙˆÙ† ØªØ¹Ø·ÙŠÙ„ Ø§Ù„ØªÙØ§Ø¹Ù„
        import logging
        logging.getLogger(__name__).warning(f"set_my_commands failed: {e}")

# ===== Ù„ÙˆØ­Ø§Øª Ø§Ù„Ù…ÙØ§ØªÙŠØ­ =====
def language_keyboard(display_lang: str, selected_lang: str) -> InlineKeyboardMarkup:
    display_lang = display_lang if display_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    selected_lang = selected_lang if selected_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE

    rows = [
        [
            InlineKeyboardButton(
                text=("âœ… " if selected_lang == "en" else "") + _tt(display_lang, "btn_lang_en", "English"),
                callback_data="set_lang_en"
            ),
            InlineKeyboardButton(
                text=("âœ… " if selected_lang == "ar" else "") + _tt(display_lang, "btn_lang_ar", "Ø§Ù„Ø¹Ø±Ø¨ÙŠØ©"),
                callback_data="set_lang_ar"
            ),
        ],
        [InlineKeyboardButton(text=_tt(display_lang, "back_to_menu", _loc(display_lang, "Ø±Ø¬ÙˆØ¹", "Back")), callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== Ù…Ø³Ø§Ø¹Ø¯: ØªØ¹Ø¯ÙŠÙ„ Ø°ÙƒÙŠ Ù…Ø¹ fallback =====
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

# ===== Ø§Ù„Ø£ÙˆØ§Ù…Ø±/Ø§Ù„ÙƒÙˆÙ„Ø¨Ø§ÙƒØ§Øª =====
@router.message(Command("language"))
async def language_command(message: Message):
    lang = get_user_lang(message.from_user.id) or DEFAULT_LOCALE
    await message.answer(
        _tt(lang, "choose_language", _loc(lang, "Ø§Ø®ØªØ± Ù„ØºØªÙƒ:", "Choose your language:")),
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
        _tt(lang, "choose_language", _loc(lang, "Ø§Ø®ØªØ± Ù„ØºØªÙƒ:", "Choose your language:")),
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
        _tt(new_lang, "language_changed", _loc(new_lang, "ØªÙ… ØªØºÙŠÙŠØ± Ø§Ù„Ù„ØºØ© âœ…", "Language changed âœ…")),
        language_keyboard(display_lang=new_lang, selected_lang=new_lang),
    )

    if SHOW_MENU_ON_LANG_CHANGE:
        await callback.message.answer(
            _tt(new_lang, "menu.keyboard_ready", _loc(new_lang, "ØªÙ… ØªØ¬Ù‡ÙŠØ² Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø¨Ø§Ù„Ø£Ø³ÙÙ„ â¬‡ï¸", "Menu ready â¬‡ï¸")),
            reply_markup=make_bottom_kb(new_lang),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    await callback.answer()

