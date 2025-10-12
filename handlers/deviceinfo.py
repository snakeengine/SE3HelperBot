# 📁 handlers/deviceinfo.py
import os
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router()

DEFAULT_DEVICEINFO_URL = "https://www.mediafire.com/file/gjd3dx7ztdlbtdl/SE_2.0.6.apk/file"

def _get_deviceinfo_url(lang: str) -> str:
    # يحاول من الترجمة، ثم من ENV، ثم الافتراضي
    return (
        (t(lang, "deviceinfo_url") or "").strip()
        or os.getenv("DEVICEINFO_URL", "").strip()
        or DEFAULT_DEVICEINFO_URL
    )

def _build_text(lang: str) -> str:
    title = t(lang, "device_info_app") or "Device Info App"
    body  = t(lang, "deviceinfo_text") or "Get full device info to help support."
    return f"📱 <b>{title}</b>\n\n{body}"

def _build_kb(lang: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_download_deviceinfo") or "Download", url=url)],
        [InlineKeyboardButton(text=t(lang, "back_to_menu") or "⬅️ Back", callback_data="back_to_menu")],
    ])

async def _safe_edit_or_answer(message: Message, text: str, kb: InlineKeyboardMarkup):
    """يحاول edit، ولو فشل (لا نص/غير قابل للتعديل) يرسل رسالة جديدة."""
    try:
        if message.text is not None:
            return await message.edit_text(
                text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
        if message.caption is not None:
            return await message.edit_caption(
                caption=text, reply_markup=kb, parse_mode=ParseMode.HTML
            )
        # لا نص ولا كابشن
        return await message.answer(
            text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        low = str(e).lower()
        if ("there is no text in the message to edit" in low
            or "message can't be edited" in low
            or "message is not modified" in low):
            return await message.answer(
                text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
        raise

# أمر نصي: /deviceinfo أو /device_info
@router.message(Command(commands=["deviceinfo", "device_info"]))
async def deviceinfo_cmd(message: Message):
    lang = get_user_lang(message.from_user.id) or "en"
    url  = _get_deviceinfo_url(lang)
    await message.answer(
        _build_text(lang),
        reply_markup=_build_kb(lang, url),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# دعم الفتح من زر إنلاين إن أحببت تستخدم callback_data="deviceinfo" أو "deviceinfo:open"
@router.callback_query(F.data.in_({"deviceinfo", "deviceinfo:open"}))
async def deviceinfo_cb(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    url  = _get_deviceinfo_url(lang)
    await _safe_edit_or_answer(cb.message, _build_text(lang), _build_kb(lang, url))
    await cb.answer()
