from aiogram import BaseMiddleware
from aiogram.types import Update
from typing import Callable, Awaitable, Dict, Any

from lang import get_user_lang
from utils.alerts_broadcast import track_user

class SeenUserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        try:
            if event.message and event.message.from_user:
                uid = event.message.from_user.id
                lang = (get_user_lang(uid) or (event.message.from_user.language_code or "ar")).split("-")[0]
                track_user(uid, lang)
            elif event.callback_query and event.callback_query.from_user:
                uid = event.callback_query.from_user.id
                lang = (get_user_lang(uid) or (event.callback_query.from_user.language_code or "ar")).split("-")[0]
                track_user(uid, lang)
            elif event.chat_member and event.chat_member.from_user:
                uid = event.chat_member.from_user.id
                lang = (get_user_lang(uid) or "ar").split("-")[0]
                track_user(uid, lang)
        except Exception:
            pass
        return await handler(event, data)
