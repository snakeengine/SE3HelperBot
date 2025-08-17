# 📁 handlers/about.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import t, get_user_lang

router = Router()

def _tr(lang: str, key: str, default: str) -> str:
    val = t(lang, key)
    return val if val != key else default

def about_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_contact_email"), callback_data="contact_by_email")],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"),      callback_data="back_to_menu")],
    ])

# أمر /about
@router.message(Command("about"))
async def about_handler(message: Message):
    lang = get_user_lang(message.from_user.id) or "en"
    text = _tr(lang, "about_text", "ℹ️ About this bot.")
    await message.answer(
        text,
        reply_markup=about_keyboard(lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

# (اختياري) لو استُخدم كزر كولباك مستقبلًا
@router.callback_query(F.data == "about")
async def about_callback(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    text = _tr(lang, "about_text", "ℹ️ About this bot.")
    await cb.message.edit_text(
        text,
        reply_markup=about_keyboard(lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await cb.answer()
