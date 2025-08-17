# 📁 handlers/deviceinfo.py
import os
from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import t, get_user_lang

router = Router()

DEFAULT_DEVICEINFO_URL = "https://www.mediafire.com/file/91tl7ko41da8xh2/deviceinfo.apk/file"

def _get_deviceinfo_url(lang: str) -> str:
    # يحاول من الترجمة، ثم من ENV، ثم الافتراضي
    return (
        (t(lang, "deviceinfo_url") or "").strip()
        or os.getenv("DEVICEINFO_URL", "").strip()
        or DEFAULT_DEVICEINFO_URL
    )

@router.message(Command("deviceinfo"))
async def deviceinfo_handler(message: Message):
    lang = get_user_lang(message.from_user.id)

    url = _get_deviceinfo_url(lang)
    text = (
        f"📱 <b>{t(lang, 'device_info_app')}</b>\n\n"
        f"{t(lang, 'deviceinfo_text')}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_download_deviceinfo"), url=url)],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")],
    ])

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
