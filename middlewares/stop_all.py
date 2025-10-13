# middlewares/stop_all.py
import json, os
from pathlib import Path
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
FLAGS_FILE = DATA_DIR / "shop_flags.json"

def _get_flags() -> dict:
    try:
        if FLAGS_FILE.exists():
            return json.loads(FLAGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _admins() -> set[int]:
    raw = os.getenv("ADMIN_IDS","")
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}

class StopAllMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]], event: Any, data: Dict[str, Any]) -> Any:
        flags = _get_flags()
        stop_all = bool(flags.get("stop_all", False)) or (os.getenv("STOP_ALL","0") == "1")
        if not stop_all:
            return await handler(event, data)

        uid = None
        if hasattr(event, "from_user") and event.from_user:
            uid = event.from_user.id
        elif getattr(event, "message", None) and event.message.from_user:
            uid = event.message.from_user.id
        elif getattr(event, "callback_query", None) and event.callback_query.from_user:
            uid = event.callback_query.from_user.id
        elif getattr(event, "chat_join_request", None) and event.chat_join_request.from_user:
            uid = event.chat_join_request.from_user.id
        elif getattr(event, "chat_member", None) and event.chat_member.from_user:
            uid = event.chat_member.from_user.id

        if uid and uid in _admins():
            return await handler(event, data)
        return  # ابتلاع التحديث بصمت
