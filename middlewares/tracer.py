# middlewares/tracer.py
from __future__ import annotations
import logging
from aiogram import BaseMiddleware
from aiogram.types import Update

def _desc_update(upd: Update) -> tuple[str, int | None, str | None]:
    if upd.message:
        u = upd.message.from_user
        return "message", (u.id if u else None), (upd.message.text or upd.message.caption)
    if upd.edited_message:
        u = upd.edited_message.from_user
        return "edited_message", (u.id if u else None), (upd.edited_message.text or upd.edited_message.caption)
    if upd.callback_query:
        u = upd.callback_query.from_user
        return "callback", (u.id if u else None), (upd.callback_query.data)
    if upd.my_chat_member:
        u = upd.my_chat_member.from_user
        return "my_chat_member", (u.id if u else None), None
    if upd.chat_member:
        u = upd.chat_member.from_user
        return "chat_member", (u.id if u else None), None
    if upd.channel_post:
        return "channel_post", None, None
    if upd.edited_channel_post:
        return "edited_channel_post", None, None
    # fallback
    return "other", None, None

class TracerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        kind, uid, payload = _desc_update(event)
        logging.info(f"[TRACE] enter {kind} uid={uid} payload={payload!r}")
        res = await handler(event, data)
        logging.info(f"[TRACE] exit  {kind}")
        return res
