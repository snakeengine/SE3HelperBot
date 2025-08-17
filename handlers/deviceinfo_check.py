# 📁 handlers/deviceinfo_check.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from lang import t, get_user_lang

router = Router()

DEVICEINFO_URL = "https://www.mediafire.com/file/91tl7ko41da8xh2/deviceinfo.apk/file"

@router.callback_query(F.data == "check_device")
async def check_device_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)

    message = (
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

    await callback.message.edit_text(
        message,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()
