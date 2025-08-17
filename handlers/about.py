# handlers/about.py
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import t, get_user_lang

router = Router()

def _get_download_url(lang: str) -> str:
    """
    يحاول جلب الرابط من الترجمة (download_url)،
    ثم من متغير البيئة APK_URL، ثم رابط افتراضي آمن.
    """
    url = (t(lang, "download_url") or "").strip()
    if not url:
        url = os.getenv("APK_URL", "").strip()
    if not url:
        url = "https://example.com/app-latest.apk"
    return url

def _main_menu_kb(lang: str) -> InlineKeyboardMarkup:
    """
    القائمة الرئيسية بدون أي عناصر VIP.
    """
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

# /about
@router.message(Command("about"))
async def about_handler(message: Message):
    lang = get_user_lang(message.from_user.id)
    about_text = t(lang, "about_text") or "ℹ️ About this bot."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")]]
    )
    await message.answer(about_text, reply_markup=keyboard, parse_mode="HTML")

# زر الرجوع للقائمة الرئيسية
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    start_text = t(lang, "start_intro") or "👋 Welcome!"
    await callback.message.edit_text(start_text, reply_markup=_main_menu_kb(lang), parse_mode="HTML")
    await callback.answer()
