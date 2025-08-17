# utils/admin_log.py
from __future__ import annotations

import os
from typing import Optional, Iterable
from aiogram import Bot
from aiogram.enums import ParseMode

# .env:
# ADMIN_LOG_CHAT_ID   = -1001234567890   (اختياري: قناة/مجموعة)
# ADMIN_LOG_THREAD_ID = 123              (اختياري: ثريد داخل المنتدى)
# ADMIN_ID            = 7360982123       (إلزامي كبديل لو ما فيه قناة)

def _parse_chat_id(val: Optional[str]) -> Optional[int | str]:
    if not val:
        return None
    v = val.strip()
    # اسم مستخدم قناة عام مثل @mychannel
    if v.startswith("@"):
        return v
    try:
        return int(v)
    except Exception:
        # لو قيمة غير رقمية بدون @ نعيدها نصًا (قد تعمل لبعض البوتات/البروكسي)
        return v

ADMIN_LOG_CHAT_ID = _parse_chat_id(os.getenv("ADMIN_LOG_CHAT_ID"))
ADMIN_LOG_THREAD_ID = None
try:
    _th = os.getenv("ADMIN_LOG_THREAD_ID", "").strip()
    ADMIN_LOG_THREAD_ID = int(_th) if _th else None
except Exception:
    ADMIN_LOG_THREAD_ID = None

ADMIN_ID = int(os.getenv("ADMIN_ID", "7360982123"))  # غيّره عند الحاجة

# حدود تيليجرام
TG_MAX_TEXT = 4096

def _chunks(s: str, size: int = TG_MAX_TEXT) -> Iterable[str]:
    for i in range(0, len(s), size):
        yield s[i:i + size]

async def admin_log(
    bot: Bot,
    text: str,
    *,
    parse_mode: Optional[ParseMode | str] = ParseMode.HTML,
    disable_web_page_preview: bool = True,
    thread_id: Optional[int] = None,
) -> None:
    """
    يرسل لوج إلى:
      - ADMIN_LOG_CHAT_ID (+ ADMIN_LOG_THREAD_ID إن وُجد)
      - وإلا يرسل إلى ADMIN_ID بالخاص.

    • يقسم الرسالة تلقائياً إذا تجاوزت 4096 حرف.
    • parse_mode افتراضي HTML (يمكن تمرير None لتعطيله).
    • لن يرفع استثناءً عند الفشل.
    """
    target = ADMIN_LOG_CHAT_ID if ADMIN_LOG_CHAT_ID is not None else ADMIN_ID
    topic_id = thread_id if thread_id is not None else ADMIN_LOG_THREAD_ID

    try:
        for part in _chunks(text, TG_MAX_TEXT):
            # بعض إصدارات aiogram تستخدم reply_to_message_thread_id لمواضيع المنتديات
            kwargs = dict(
                chat_id=target,
                text=part,
                disable_web_page_preview=disable_web_page_preview,
            )
            if parse_mode:
                kwargs["parse_mode"] = parse_mode  # type: ignore
            if topic_id is not None:
                kwargs["message_thread_id"] = topic_id  # type: ignore

            await bot.send_message(**kwargs)  # type: ignore[arg-type]
    except Exception:
        # لا نوقف المنطق لو فشل اللوج
        pass

async def admin_log_exception(
    bot: Bot,
    where: str,
    exc: Exception,
    *,
    note: str | None = None,
) -> None:
    """
    اختصار لإرسال استثناء بصيغة موحدة.
    """
    extra = f"\n\n<b>Note:</b> {note}" if note else ""
    msg = f"🚨 <b>AdminLog</b>\n<b>Where:</b> {where}\n<b>Error:</b> <code>{type(exc).__name__}: {exc}</code>{extra}"
    await admin_log(bot, msg)
