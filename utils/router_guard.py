# utils/router_guard.py
from __future__ import annotations
from aiogram import F, Router
from aiogram.filters import StateFilter

# حالة الدردشة الحيّة
from handlers.live_chat import LiveChat

def guard_router(
    router: Router,
    *,
    cb_prefixes: tuple[str, ...] = (),
    private_only: bool = True,
) -> None:
    """
    يوقف هذا الراوتر عندما تكون حالة المستخدم LiveChat.active
    ويقيّد الكولباكات على بادئات محددة لمنع أي تضارب.
    """
    # رسائل
    if private_only:
        router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
    else:
        router.message.filter(~StateFilter(LiveChat.active))

    # كولباكات
    if private_only:
        router.callback_query.filter(F.message.chat.type == "private", ~StateFilter(LiveChat.active))
    else:
        router.callback_query.filter(~StateFilter(LiveChat.active))

    # فلترة البادئات (اختياري لكن مهم لمنع التصادم)
    if cb_prefixes:
        router.callback_query.filter(
            F.data.func(lambda s: any((s or "").startswith(p) for p in cb_prefixes))
        )
