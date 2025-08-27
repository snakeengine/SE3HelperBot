# handlers/about.py
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router()

def _get_download_url(lang: str) -> str:
    url = (t(lang, "download_url") or "").strip()
    if not url:
        url = os.getenv("APK_URL", "").strip()
    if not url:
        url = "https://example.com/app-latest.apk"
    return url

def _main_menu_kb(lang: str) -> InlineKeyboardMarkup:
    download_url = _get_download_url(lang)
    rows = [
        [InlineKeyboardButton(text=f"📥 {t(lang, 'btn_download')}", url=download_url)],
        [InlineKeyboardButton(text=f"🧰 {t(lang, 'btn_tools')}", callback_data="tools")],
        [InlineKeyboardButton(text=f"📦 {t(lang, 'btn_reseller_info')}", callback_data="reseller_info")],
        [InlineKeyboardButton(text=t(lang, "btn_security"), callback_data="security_status")],
        [InlineKeyboardButton(text=t(lang, "btn_safe_usage"), callback_data="safe_usage")],
        [InlineKeyboardButton(text=f"🌐 {t(lang, 'btn_lang')}", callback_data="change_lang")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# تعديل/إرسال بأمان (يعالج الحالات: بدون نص، كابشن وسائط، لا يمكن التعديل)
async def _safe_edit_or_answer(message, text: str, reply_markup: InlineKeyboardMarkup):
    if not (text or "").strip():
        text = "…"
    try:
        if message.text is not None:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        if message.caption is not None:
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        # رسالة وسائط بدون نص/كابشن → أرسل جديدة
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        low = str(e).lower()
        if ("no text in the message to edit" in low
            or "message can't be edited" in low
            or "message is not modified" in low):
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        raise

# /about
@router.message(Command("about"))
async def about_handler(message: Message):
    lang = get_user_lang(message.from_user.id)
    about_text = t(lang, "about_text") or "ℹ️ About this bot."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")]]
    )
    await message.answer(about_text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# زر الرجوع للقائمة الرئيسية (آمن)
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    start_text = t(lang, "start_intro") or "👋 Welcome!"
    await _safe_edit_or_answer(callback.message, start_text, _main_menu_kb(lang))
    await callback.answer()
