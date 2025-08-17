# 📁 handlers/download.py
import os
from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import t, get_user_lang

router = Router()

DEFAULT_APK_URL = "https://example.com/app-latest.apk"

def _get_download_url(lang: str) -> str:
    # يحاول من الترجمة، ثم من ENV، ثم الافتراضي
    url = (t(lang, "download_url") or "").strip()
    if not url:
        url = os.getenv("APK_URL", "").strip()
    if not url:
        url = DEFAULT_APK_URL
    return url

@router.message(Command("download"))
async def download_handler(message: Message):
    lang = get_user_lang(message.from_user.id)

    text = t(lang, "download_text") or "⬇️ Download the latest app."
    url = _get_download_url(lang)

    buttons = []
    # تحقق بسيط لصلاحية الرابط
    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
        buttons.append([InlineKeyboardButton(text=t(lang, "btn_download_app"), url=url)])

    buttons.append([InlineKeyboardButton(text=t(lang, "btn_check_device"), callback_data="check_device")])
    buttons.append([InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
