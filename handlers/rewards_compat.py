# handlers/rewards_compat.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message

# منع التضارب مع الدردشة الحيّة
from handlers.live_chat import LiveChat

from .rewards_hub import open_hub

router = Router(name="rewards_compat")
# امنع التنفيذ أثناء جلسة الدردشة الحيّة، واشتغل بالخاص فقط
router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
router.callback_query.filter(F.message.chat.type == "private", ~StateFilter(LiveChat.active))

# نعالج فقط في الخاص، ونُلغي أثناء جلسة الدردشة الحيّة
router.message.filter(
    F.chat.type == "private",
    ~StateFilter(LiveChat.active)
)

@router.message(Command("rewards"))
async def cmd_rewards(m: Message):
    # compatibility: افتح الهَب الجديد
    await open_hub(m)
