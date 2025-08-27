# 📁 handlers/reseller.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from lang import t, get_user_lang

# نحاول استيراد دالة فتح نموذج التقديم الحقيقي
# (تأكد أن ملف الفلو محفوظ مثل: handlers/reseller_apply.py)
try:
    from handlers.reseller_apply import open_apply as _open_apply  # type: ignore
except Exception:
    _open_apply = None  # fallback لو الملف غير موجود بعد

router = Router(name="reseller")

CB_BACK_MENU = "back_to_menu"       # يرجع للهاندلر العام في start.py
CB_APPLY_IN_BOT = "apply_reseller"  # فتح نموذج التقديم داخل البوت (نفس الكولباك الذي يلتقطه فلو التقديم)

# ---------- Helpers ----------
def _is_media_message(m: Message) -> bool:
    return bool(
        getattr(m, "photo", None) or getattr(m, "animation", None) or
        getattr(m, "video", None) or getattr(m, "document", None)
    )

async def _smart_show(cb: CallbackQuery, text: str, *, reply_markup=None):
    """
    يعدّل الرسالة إن كانت نصية، أو يرسل رسالة جديدة إن كانت وسائط.
    يمنع خطأ: Bad Request: there is no text in the message to edit
    """
    m = cb.message
    if _is_media_message(m):
        return await m.answer(
            text, reply_markup=reply_markup,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    try:
        return await m.edit_text(
            text, reply_markup=reply_markup,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except TelegramBadRequest:
        # احتياط: إذا فشل التعديل لأي سبب (ليس نصًا/غير مُعدّل)، أرسل رسالة جديدة
        return await m.answer(
            text, reply_markup=reply_markup,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )

# ---------- UI ----------
def _terms_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t(lang, "btn_apply_in_bot"), callback_data=CB_APPLY_IN_BOT)],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=CB_BACK_MENU)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ---------- Handlers ----------
@router.callback_query(F.data == "reseller_info")
async def reseller_info_callback(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        f"<b>{t(lang, 'reseller_terms_title')}</b>\n\n"
        f"{t(lang, 'reseller_terms_warning')}\n\n"
        f"{t(lang, 'reseller_terms_points')}"
    )
    await _smart_show(cb, text, reply_markup=_terms_keyboard(lang))
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
        parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )

@router.callback_query(F.data == CB_APPLY_IN_BOT)
async def reseller_apply_in_bot(cb: CallbackQuery, state: FSMContext):
    """
    يفتح فلو التقديم الحقيقي إن كان handlers.reseller_apply.open_apply متاحًا.
    وإلا يعرض رسالة مؤقتة.
    """
    lang = get_user_lang(cb.from_user.id) or "en"
    if _open_apply:
        # سلّم التنفيذ لفلو التقديم الحقيقي
        await _open_apply(cb, state)
    else:
        # fallback لو ملف فلو التقديم لم يُضمَّن بعد
        await cb.message.answer(t(lang, "reseller.apply.soon") or "Opening soon.")
    await cb.answer()
