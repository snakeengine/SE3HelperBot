# middlewares/force_start.py
from __future__ import annotations
from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from typing import Callable, Any, Dict, Awaitable

class ForceStartMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # في aiogram v3 الحدث نفسه يكون Message لرسائل المستخدم
        if isinstance(event, Message):
            txt = (event.text or "").strip().lower()
            # يشمل /start مع أي payload (deep-link)
            if txt.startswith("/start"):
                state = data.get("state")
                if state:
                    try:
                        await state.clear()
                    except Exception:
                        pass
        return await handler(event, data)
