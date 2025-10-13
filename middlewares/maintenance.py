# middlewares/maintenance.py
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from typing import Callable, Dict, Any, Awaitable, Iterable
import os

from utils.maintenance_state import is_enabled

def _load_admin_ids() -> set[int]:
    # توافق مع ADMIN_IDS أو ADMIN_ID
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    # fallback الافتراضي (نفس الذي وضعته في bot.py)
    if not ids:
        ids = {7360982123,8371697148}
    return ids

DEFAULT_NOTICE = (
    "🚧 The bot is currently under maintenance.\n"
    "🚧 البوت تحت الصيانة حالياً.\n\n"
    "الرجاء المحاولة لاحقاً. Please try again later."
)

class MaintenanceMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: Iterable[int] | None = None, notice_text: str | None = None):
        super().__init__()
        self.admin_ids = set(admin_ids) if admin_ids else _load_admin_ids()
        self.notice_text = notice_text or DEFAULT_NOTICE

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # استخرج user_id من الرسائل والأزرار
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        if is_enabled():
            # السماح للأدمن فقط أثناء الصيانة
            if not user_id or user_id not in self.admin_ids:
                try:
                    if isinstance(event, Message):
                        await event.answer(self.notice_text)
                    elif isinstance(event, CallbackQuery):
                        # نرسل إشعاراً في الشات ونغلق السبنر
                        if event.message:
                            await event.message.answer(self.notice_text)
                        await event.answer()
                except Exception:
                    pass
                return  # إيقاف السلسلة هنا للمستخدمين العاديين

        return await handler(event, data)
