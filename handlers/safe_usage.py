# 📁 handlers/safe_usage.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router()

# ثبّت نفس الاسم المستخدم في الأزرار
SAFE_USAGE_CB = "safe_usage:open"   # المستخدم في زر القائمة
BACK_CB = "back_to_menu"

def safe_usage_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_CB)]
    ])

# تعديل ذكي: يحاول edit_text أو edit_caption، ولو ما ينفع يرسل رسالة جديدة
async def _smart_edit_or_send(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    try:
        if message.text is not None:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        if message.caption is not None:
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        # لا نص ولا وصف → أرسل جديد
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if ("there is no text in the message to edit" in msg or
            "message is not modified" in msg or
            "message can't be edited" in msg):
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        raise

async def _build_text(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    lang = get_user_lang(user_id) or "en"
    return t(lang, "safe_usage_guide"), safe_usage_keyboard(lang)

# 🧠 زر "دليل الاستخدام الآمن"
# ندعم كلا القيمتين تحسباً: "safe_usage" و "safe_usage:open"
@router.callback_query(F.data.in_({"safe_usage", "safe_usage:open"}))
async def safe_usage_callback(callback: CallbackQuery):
    text, kb = await _build_text(callback.from_user.id)
    await _smart_edit_or_send(callback.message, text, kb)
    await callback.answer()

# 🧠 أمر نصي اختياري: /safe
@router.message(Command("safe"))
async def safe_usage_command(message: Message):
    text, kb = await _build_text(message.from_user.id)
    await message.answer(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
