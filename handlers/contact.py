# 📁 handlers/contact.py
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from urllib.parse import quote, quote_plus
from lang import t, get_user_lang

router = Router()

def get_support_email() -> str:
    return os.getenv("SUPPORT_EMAIL", "support@example.com").strip()

def contact_menu_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_contact_email"), callback_data="contact_by_email")],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")]
    ])

def contact_back_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "back_to_contact"), callback_data="contact_menu")],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")]
    ])

@router.message(Command("contact"))
async def contact_handler(message: Message):
    lang = get_user_lang(message.from_user.id)
    await message.answer(
        t(lang, "contact_message"),
        reply_markup=contact_menu_kb(lang),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "contact_menu")
async def contact_menu_callback(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "contact_message"),
        reply_markup=contact_menu_kb(lang),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "contact_by_email")
async def contact_by_email(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    email = get_support_email()

    subject = t(lang, "email_subject_reseller")
    body    = t(lang, "email_body_template")
    su      = quote_plus(subject)
    bd      = quote_plus(body)

    gmail   = f"https://mail.google.com/mail/?view=cm&fs=1&to={email}&su={su}&body={bd}"
    outlook = f"https://outlook.live.com/owa/?path=/mail/action/compose&to={email}&subject={su}&body={bd}"
    mailto  = f"mailto:{email}?subject={quote(subject)}&body={quote(body)}"

    text = (
        f"📧 <b>{t(lang, 'official_email_title')}</b> <code>{email}</code>\n\n"
        f"{t(lang, 'email_instruction_line')}\n\n"
        f"<a href='{mailto}'>{t(lang, 'open_in_mail_app')}</a>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_open_gmail"),   url=gmail)],
        [InlineKeyboardButton(text=t(lang, "btn_open_outlook"), url=outlook)],
        [InlineKeyboardButton(text=t(lang, "back_to_contact"),  callback_data="contact_menu")],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"),     callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()
