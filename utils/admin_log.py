# utils/admin_log.py
from __future__ import annotations

import os
from typing import Optional, Iterable, Sequence, Union

from aiogram import Bot
from aiogram.enums import ParseMode

# اختياري: الاستفادة من utils.admin_access إن كان موجوداً
try:
    from utils.admin_access import get_admin_ids, get_admin_channel_id
except Exception:
    def get_admin_ids() -> set[int]:
        raw = (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")).strip()
        ids: set[int] = set()
        for p in raw.replace(";", ",").replace("\n", ",").split(","):
            p = p.strip()
            if p and p.lstrip("-").isdigit():
                ids.add(int(p))
        return ids or {7360982123}

    def get_admin_channel_id() -> Optional[int]:
        val = os.getenv("ADMIN_LOG_CHAT_ID") or os.getenv("ADMIN_CHANNEL_ID") or os.getenv("ADMIN_CHANNEL")
        if not val:
            return None
        v = val.strip()
        if v.startswith("@"):
            return v  # type: ignore[return-value]
        return int(v) if v.lstrip("-").isdigit() else None


# ================== إعدادات من البيئة ==================
def _parse_thread_id() -> Optional[int]:
    v = (os.getenv("ADMIN_LOG_THREAD_ID") or "").strip()
    if v and v.isdigit():
        return int(v)
    return None

def _parse_bool(name: str, default: bool) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default

ADMIN_LOG_CHAT: Optional[Union[int, str]] = get_admin_channel_id()
ADMIN_LOG_THREAD_ID: Optional[int] = _parse_thread_id()
ADMIN_LOG_SILENT = _parse_bool("ADMIN_LOG_SILENT", True)               # كتم الإشعارات افتراضياً
ADMIN_LOG_DISABLE_PREVIEW = _parse_bool("ADMIN_LOG_DISABLE_PREVIEW", True)
ADMIN_LOG_DM_ALL = _parse_bool("ADMIN_LOG_DM_ALL", True)               # إن لم توجد قناة: أرسل DM لكل الإدمنز


# ================== أدوات داخلية ==================
TG_MAX_TEXT = 4096

def _chunks(s: str, size: int = TG_MAX_TEXT) -> Iterable[str]:
    for i in range(0, len(s), size):
        yield s[i:i + size]

async def _send_message(
    bot: Bot,
    chat: Union[int, str],
    text: str,
    *,
    parse_mode: Optional[Union[ParseMode, str]],
    disable_web_page_preview: bool,
    message_thread_id: Optional[int],
    disable_notification: bool,
) -> None:
    kwargs = dict(
        chat_id=chat,
        text=text,
        disable_web_page_preview=disable_web_page_preview,
        disable_notification=disable_notification,
    )
    if parse_mode:
        kwargs["parse_mode"] = parse_mode  # type: ignore[assignment]
    if message_thread_id is not None:
        kwargs["message_thread_id"] = message_thread_id  # type: ignore[assignment]
    await bot.send_message(**kwargs)  # type: ignore[arg-type]


# ================== الواجهة العامة ==================
async def admin_log(
    bot: Bot,
    text: str,
    *,
    parse_mode: Optional[Union[ParseMode, str]] = ParseMode.HTML,
    disable_web_page_preview: bool = ADMIN_LOG_DISABLE_PREVIEW,
    thread_id: Optional[int] = None,
    silent: bool = ADMIN_LOG_SILENT,
) -> None:
    """
    يرسل لوج للإدارة:
      1) إن كانت ADMIN_LOG_CHAT محددة → يُرسل إليها (ويدعم thread).
      2) وإلا يرسل DM لكل المدراء (أو لأوّل مدير إن ADMIN_LOG_DM_ALL=False).

    • يقسم الرسالة تلقائياً إذا تجاوزت 4096 حرف.
    • لن يرفع استثناء — أي خطأ سيتم تجاهله بهدوء.
    """
    try:
        if ADMIN_LOG_CHAT is not None:
            for part in _chunks(text):
                await _send_message(
                    bot,
                    ADMIN_LOG_CHAT,
                    part,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                    message_thread_id=(thread_id if thread_id is not None else ADMIN_LOG_THREAD_ID),
                    disable_notification=silent,
                )
            return

        # لا توجد قناة—أرسل خاص للإدمنز
        admins = sorted(get_admin_ids())
        targets: Sequence[int] = admins if ADMIN_LOG_DM_ALL else (admins[:1] if admins else [])
        for uid in targets:
            for part in _chunks(text):
                await _send_message(
                    bot,
                    uid,
                    part,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                    message_thread_id=None,
                    disable_notification=silent,
                )
    except Exception:
        # لا نوقف المنطق لو فشل اللوج
        pass


async def admin_log_to(
    bot: Bot,
    chat_id: Union[int, str],
    text: str,
    *,
    parse_mode: Optional[Union[ParseMode, str]] = ParseMode.HTML,
    disable_web_page_preview: bool = True,
    thread_id: Optional[int] = None,
    silent: bool = True,
) -> None:
    """
    إرسال لوج لوجهة محددة (ID أو @username) بغض النظر عن الإعدادات العامة.
    """
    try:
        for part in _chunks(text):
            await _send_message(
                bot,
                chat_id,
                part,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                message_thread_id=thread_id,
                disable_notification=silent,
            )
    except Exception:
        pass


async def admin_log_exception(
    bot: Bot,
    where: str,
    exc: Exception,
    *,
    note: Optional[str] = None,
) -> None:
    """
    إرسال استثناء بصيغة موحّدة.
    """
    extra = f"\n\n<b>Note:</b> {note}" if note else ""
    msg = (
        f"🚨 <b>AdminLog</b>\n"
        f"<b>Where:</b> {where}\n"
        f"<b>Error:</b> <code>{type(exc).__name__}: {exc}</code>{extra}"
    )
    await admin_log(bot, msg)
