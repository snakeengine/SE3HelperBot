# services/notify.py
from __future__ import annotations
from typing import Iterable, Optional, Sequence, Dict, Any, List
import asyncio
import logging

from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardRemove, InlineKeyboardMarkup
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError

from services import admin_roles

log = logging.getLogger(__name__)

# ========= Helpers =========
def _dedupe_preserve_order(items: Iterable[int]) -> List[int]:
    seen = set()
    out: List[int] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def _chunk_text(text: str, limit: int = 4096) -> List[str]:
    """
    يقسّم النص إلى قطع <= 4096 مع تفضيل التقسيم على حدود الأسطر.
    """
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    buf = text
    while len(buf) > limit:
        cut = buf.rfind("\n", 0, limit)
        if cut < 0 or cut < limit // 2:
            cut = limit
        parts.append(buf[:cut])
        buf = buf[cut:].lstrip("\n")
    if buf:
        parts.append(buf)
    return parts

async def _targets(role: str) -> List[int]:
    try:
        ids = await admin_roles.get_admins(role)
    except Exception as e:
        log.warning("notify_role: failed to load admins for role %r: %s", role, e)
        return []
    if not ids:
        return []
    if not isinstance(ids, (list, tuple, set)):
        try:
            ids = list(ids)  # type: ignore
        except Exception:
            ids = [ids]  # type: ignore
    return _dedupe_preserve_order(int(x) for x in ids)

# ========= Public API =========
async def notify_role(
    bot: Bot,
    role: str,
    text: str,
    *,
    parse_mode: Optional[ParseMode] = None,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardRemove | None = None,
    disable_notification: bool = True,
    protect_content: bool = False,
    # خيارات متقدمة (اختيارية):
    concurrency: int = 8,
    base_delay_sec: float = 0.0,
) -> Dict[str, Any]:
    """
    يرسل نفس الرسالة لكل مستقبل مرتبط بـ role.
    - يتعامل مع 429 (RetryAfter) بالانتظار ثم إعادة المحاولة.
    - يتجاهل 403 (حظر/لا يمكن الإرسال) و 400 (بيانات غير صالحة) ويسجلها فقط.
    - يقسّم الرسالة تلقائيًا إذا تجاوزت حد تيليجرام 4096.
    - يرجّع تقريرًا إحصائيًا.

    Returns:
      {
        "role": <role>,
        "targets": <count>,
        "sent": <count>,
        "failed": <count>,
        "errors": [{"chat_id": ..., "error": "..."}, ...]
      }
    """
    ids = await _targets(role)
    if not ids:
        return {"role": role, "targets": 0, "sent": 0, "failed": 0, "errors": []}

    chunks = _chunk_text(text)
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    results: Dict[str, Any] = {"role": role, "targets": len(ids), "sent": 0, "failed": 0, "errors": []}

    async def _send_one(chat_id: int):
        nonlocal results
        async with sem:
            # انتظار بسيط بين الإرسال لتخفيف الضغط إذا رغبت
            if base_delay_sec > 0:
                await asyncio.sleep(base_delay_sec)

            for i, piece in enumerate(chunks):
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        await bot.send_message(
                            chat_id,
                            piece,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup if i == len(chunks) - 1 else None,
                            disable_notification=disable_notification,
                            protect_content=protect_content,
                        )
                        break  # أُرسلت هذه القطعة
                    except TelegramRetryAfter as e:
                        # 429 — التزم بوقت الانتظار ثم أعد المحاولة
                        wait_s = max(1, int(getattr(e, "retry_after", 1)))
                        log.info("notify_role: 429 for %s, waiting %ss", chat_id, wait_s)
                        await asyncio.sleep(wait_s)
                        continue
                    except TelegramForbiddenError as e:
                        # 403 — المستخدم حظر البوت أو لا يمكن الإرسال
                        log.debug("notify_role: 403 for %s: %s", chat_id, e)
                        results["errors"].append({"chat_id": chat_id, "error": "FORBIDDEN"})
                        return  # لا تكمل بقية الأجزاء
                    except TelegramBadRequest as e:
                        # 400 — غالبًا parse_mode/markup خاطئ
                        log.warning("notify_role: 400 for %s: %s", chat_id, e)
                        results["errors"].append({"chat_id": chat_id, "error": f"BAD_REQUEST:{e}"})
                        return
                    except Exception as e:
                        # أخطاء عابرة أخرى — سجّل واستسلم لهذه الجهة
                        log.warning("notify_role: send failed for %s (attempt %s): %s", chat_id, attempt, e)
                        results["errors"].append({"chat_id": chat_id, "error": f"EXCEPTION:{e}"})
                        return
            # إذا وصلنا هنا فكل القطع وصلت
            results["sent"] += 1

    await asyncio.gather(*[_send_one(cid) for cid in ids])

    results["failed"] = results["targets"] - results["sent"]
    return results
