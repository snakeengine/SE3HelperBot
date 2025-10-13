# utils/filters_common.py
from __future__ import annotations
from aiogram.filters import BaseFilter
from aiogram.types import Message

class NotCommand(BaseFilter):
    """يمرر الرسائل التي ليست أوامر سلاش (لا تبدأ بـ /)."""
    async def __call__(self, msg: Message) -> bool:
        ents = msg.entities or []
        # اعتبرها أمرًا فقط لو أول كيان bot_command وبالأوفست 0
        return not any(e.type == "bot_command" and e.offset == 0 for e in ents)
