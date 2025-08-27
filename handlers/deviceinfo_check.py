# 📁 handlers/deviceinfo_check.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router()

DEVICEINFO_URL = "https://www.mediafire.com/file/91tl7ko41da8xh2/deviceinfo.apk/file"

async def _safe_edit_or_answer(message: Message, text: str, kb: InlineKeyboardMarkup):
    """يحاول تعديل الرسالة الحالية, وإن لم يمكن يرسل رسالة جديدة."""
    try:
        if message.text is not None:
            return await message.edit_text(
                text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
        if message.caption is not None:
            return await message.edit_caption(
                caption=text, reply_markup=kb, parse_mode=ParseMode.HTML
            )
        # لا نص ولا كابشن (مثلاً ميديا بدون تعليق) → أرسل رسالة جديدة
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

@router.callback_query(F.data == "check_device")
async def check_device_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)

    message_text = (
        f"<b>{t(lang, 'check_device_title')}</b>\n\n"
        f"{t(lang, 'check_device_note')}\n\n"
        f"{t(lang, 'check_device_step')}\n"
        f"<a href='{DEVICEINFO_URL}'>📥 Device Info Tool</a>\n\n"
        f"{t(lang, 'check_device_howto')}\n\n"
        f"{t(lang, 'abi_64_supported')}\n"
        f"{t(lang, 'abi_32_not_supported')}\n\n"
        f"{t(lang, 'check_device_result')}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_download_deviceinfo"), url=DEVICEINFO_URL)],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")],
    ])

    await _safe_edit_or_answer(callback.message, message_text, keyboard)
    await callback.answer()
