# middlewares/admin_only.py
from __future__ import annotations
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from utils.admin_access import get_admin_ids

_AR = "هذا بوت خاص بالأدمن فقط."
_EN = "This bot is private (admins only)."

class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, msg_ar: str = _AR, msg_en: str = _EN):
        self._msg_ar = msg_ar
        self._msg_en = msg_en
        self._admins = get_admin_ids()

    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Any,
        data: dict,
    ) -> Any:
        bot = data.get("bot")

        chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
        user = getattr(event, "from_user", None) or getattr(getattr(event, "message", None), "from_user", None)

        # نغادر أي محادثة ليست private (group/supergroup/channel)
        if chat and getattr(chat, "type", None) != "private":
            try:
                await bot.leave_chat(chat.id)
            except Exception:
                pass
            return

        # في الخاص: اسمح فقط للأدمن
        if user and user.id not in self._admins:
            text = self._msg_ar if (getattr(user, "language_code", "") or "").startswith("ar") else self._msg_en
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(text)
            except Exception:
                pass
            return

        return await handler(event, data)
