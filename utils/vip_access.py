# utils/vip_access.py
from typing import Callable, Awaitable, Any
from aiogram.types import Message, CallbackQuery
import os

# مصدر الحقيقة لعضوية VIP
try:
    from utils.vip_store import is_vip
except Exception:
    def is_vip(_uid: int) -> bool:
        return False

def _load_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    if not ids:
        ids = {7360982123}
    return ids

ADMIN_IDS = _load_admin_ids()

def has_vip_or_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or is_vip(user_id)

def vip_required(reply_func: Callable[[Any, str], Awaitable[Any]] | None = None, key: str = "vip.required"):
    """
    ديكوريتر للاستخدام على الهاندلرز:
    - إن لم يكن VIP/أدمن → يرسل رسالة رفض باستخدام مفتاح ترجمة.
    - يعمل لكل من Message و CallbackQuery.
    """
    async def _default_reply(evt, text: str):
        if isinstance(evt, Message):
            await evt.answer(text)
        elif isinstance(evt, CallbackQuery):
            await evt.answer(text, show_alert=True)

    async def send(evt, text: str):
        if reply_func:
            await reply_func(evt, text)
        else:
            await _default_reply(evt, text)

    def _decorator(func):
        async def _wrapper(evt, *args, **kwargs):
            user_id = None
            try:
                if isinstance(evt, Message):
                    user_id = evt.from_user.id
                    from lang import get_user_lang, t
                    lang = get_user_lang(user_id) or "en"
                    if not has_vip_or_admin(user_id):
                        return await send(evt, t(lang, key))
                elif isinstance(evt, CallbackQuery):
                    user_id = evt.from_user.id
                    from lang import get_user_lang, t
                    lang = get_user_lang(user_id) or "en"
                    if not has_vip_or_admin(user_id):
                        return await send(evt, t(lang, key))
            except Exception:
                # لو فشل أي شيء، نكتفي بالتحقق المباشر
                if not has_vip_or_admin(user_id or 0):
                    return await send(evt, "This feature is for VIP members.")
            return await func(evt, *args, **kwargs)
        return _wrapper
    return _decorator
