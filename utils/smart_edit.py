# utils/smart_edit.py
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

async def smart_edit(message: Message, text: str, reply_markup=None):
    """
    يحاول تعديل النص إن وجد، وإلا يجرّب تعديل الكابشن،
    ولو ما ينفع يرسل رسالة جديدة كحل أخير.
    """
    try:
        # لو الرسالة نصيّة
        if getattr(message, "text", None) is not None:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

        # لو الرسالة ميديا (صورة/فيديو/ملف/أنيميشن) جرّب تعديل الكابشن
        if any([
            getattr(message, "photo", None),
            getattr(message, "video", None),
            getattr(message, "document", None),
            getattr(message, "animation", None),
        ]):
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )

        # لو ما قدر يحدد، جرّب كابشن ثم أرسل رسالة جديدة
        try:
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest:
            pass

        # إرسال جديد
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    except TelegramBadRequest as e:
        # fallback عام لأي منع تعديل (لا يوجد نص، لا يمكن تعديل…الخ)
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
