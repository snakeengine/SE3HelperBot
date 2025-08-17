# 📁 handlers/safe_usage.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from lang import t, get_user_lang

router = Router()

# ثبّت نفس الاسم المستخدم في الأزرار
SAFE_USAGE_CB = "safe_usage:open"   # ← هذا هو المستخدم في زر القائمة
BACK_CB = "back_to_menu"

def safe_usage_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_CB)]
    ])

async def send_safe_usage(user_id: int, send_func):
    lang = get_user_lang(user_id) or "en"
    await send_func(
        t(lang, "safe_usage_guide"),
        reply_markup=safe_usage_keyboard(lang),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# 🧠 زر "دليل الاستخدام الآمن"
# ندعم كلا القيمتين تحسباً: "safe_usage" و "safe_usage:open"
@router.callback_query(F.data.in_({"safe_usage", "safe_usage:open"}))
async def safe_usage_callback(callback: CallbackQuery):
    await send_safe_usage(callback.from_user.id, callback.message.edit_text)
    await callback.answer()

# 🧠 أمر نصي اختياري: /safe
@router.message(Command("safe"))
async def safe_usage_command(message: Message):
    await send_safe_usage(message.from_user.id, message.answer)
