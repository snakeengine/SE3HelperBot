# middlewares/auto_subscribe.py
from __future__ import annotations
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from typing import Callable, Awaitable, Dict, Any
from pathlib import Path
import json

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
SUBS_FILE = DATA_DIR / "alerts_subs.json"

def _load() -> dict:
    try:
        return json.loads(SUBS_FILE.read_text("utf-8"))
    except Exception:
        return {}

def _save(d: dict):
    SUBS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

class AutoSubscribeMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        uid = None
        if isinstance(event, Message):
            if event.chat and event.chat.type != "private":
                return await handler(event, data)
            uid = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            if event.message and event.message.chat and event.message.chat.type != "private":
                return await handler(event, data)
            uid = event.from_user.id if event.from_user else None

        if uid:
            subs = _load()
            # إن لم يكن المستخدم قد ألغى الاشتراك صراحةً، اعتبره مشتركًا
            if subs.get(str(uid)) is not False:
                if subs.get(str(uid)) is not True:
                    subs[str(uid)] = True
                    _save(subs)

        return await handler(event, data)
