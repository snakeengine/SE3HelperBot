# middlewares/ephemeral_kb.py
from __future__ import annotations
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from utils.ephemeral_kb import (
    get, close_panel, should_close_on_callback, should_close_on_message
)

ZERO_WIDTH = "\u2060"  # نص غير مرئي لتفريغ الكيبورد بدون تشويش

class EphemeralKBGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            if isinstance(event, Message):
                uid = event.from_user.id
                active = get(uid)
                if active and should_close_on_message(uid, event.text or ""):
                    await event.answer(ZERO_WIDTH, reply_markup=ReplyKeyboardRemove())
                    close_panel(uid)
            elif isinstance(event, CallbackQuery):
                uid = event.from_user.id
                active = get(uid)
                if active and event.data:
                    if should_close_on_callback(uid, event.data):
                        chat_id = event.message.chat.id
                        await event.message.bot.send_message(chat_id, ZERO_WIDTH, reply_markup=ReplyKeyboardRemove())
                        close_panel(uid)
        except Exception:
            pass
        return await handler(event, data)
