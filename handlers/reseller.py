# 📁 handlers/reseller.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import t, get_user_lang

router = Router(name="reseller")

CB_BACK_MENU = "back_to_menu"      # رجوع للقائمة
CB_APPLY_IN_BOT = "apply_reseller" # فتح نموذج التقديم داخل البوت

def _terms_keyboard(lang: str) -> InlineKeyboardMarkup:
    # فقط زر التقديم داخل البوت + الرجوع
    rows = [
        [InlineKeyboardButton(text=t(lang, "btn_apply_in_bot"), callback_data=CB_APPLY_IN_BOT)],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=CB_BACK_MENU)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == "reseller_info")
async def reseller_info_callback(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        f"<b>{t(lang, 'reseller_terms_title')}</b>\n\n"
        f"{t(lang, 'reseller_terms_warning')}\n\n"
        f"{t(lang, 'reseller_terms_points')}"
    )
    await cb.message.edit_text(
        text, reply_markup=_terms_keyboard(lang),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await cb.answer()

@router.message(Command("reseller"))
async def reseller_cmd(msg: Message):
    lang = get_user_lang(msg.from_user.id) or "en"
    text = (
        f"<b>{t(lang, 'reseller_terms_title')}</b>\n\n"
        f"{t(lang, 'reseller_terms_warning')}\n\n"
        f"{t(lang, 'reseller_terms_points')}"
    )
    await msg.answer(
        text, reply_markup=_terms_keyboard(lang),
        parse_mode="HTML", disable_web_page_preview=True
    )

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(cb: CallbackQuery):
    # أعِد نفس شاشة الشروط (أو صِلها بقائمة رئيسية إن وجدت)
    await reseller_info_callback(cb)
