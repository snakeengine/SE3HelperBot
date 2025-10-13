# utils/router_guard.py
from __future__ import annotations
from typing import Iterable, Tuple
from aiogram import F, Router
from aiogram.filters import StateFilter

# حالة الدردشة الحيّة (نتحمل غيابها بأمان أثناء الاختبارات)
try:
    from handlers.live_chat import LiveChat  # StateGroup وفيه .active
except Exception:  # fallback آمن
    class _DummyState:
        active = object()
    LiveChat = _DummyState()  # type: ignore


def _as_prefixes(v: Iterable[str] | Tuple[str, ...]) -> Tuple[str, ...]:
    try:
        return tuple(str(x) for x in v if str(x))
    except Exception:
        return tuple()

def guard_router(
    router: Router,
    *,
    cb_prefixes: Iterable[str] | Tuple[str, ...] = (),
    private_only: bool = True,
) -> None:
    """
    يوقف هذا الراوتر عندما تكون حالة المستخدم LiveChat.active
    ويقيّد الكولباكات على بادئات محددة لمنع أي تضارب.
    - private_only: إن True يمنع الرسائل/الكولباكات خارج الخاص.
    - cb_prefixes: قائمة بادئات مسموحة (مثل "vip:", "shop:")
    """
    prefixes = _as_prefixes(cb_prefixes)

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

    # فلترة بادئات الكولباك (اختياري)
    if prefixes:
        router.callback_query.filter(
            F.data.func(lambda s: isinstance(s, str) and any(s.startswith(p) for p in prefixes))
        )
