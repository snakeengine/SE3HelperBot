# middlewares/force_start.py
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Callable, Any, Dict, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update

# ===== إعدادات =====
REQUIRE_START = False          # اجعلها True إذا أردت إجبار /start قبل أي شيء
PRIVATE_ONLY   = True          # طبّق المنع في الخاص فقط (يُنصح به)

# ملف تذكّر من بدأ البوت
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STARTED_FILE = DATA_DIR / "started_users.json"

def _load_started() -> dict:
    try:
        with open(STARTED_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _save_started(d: dict) -> None:
    tmp = STARTED_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STARTED_FILE)

def _has_started(uid: int) -> bool:
    d = _load_started()
    return str(uid) in d

def _mark_started(uid: int) -> None:
    d = _load_started()
    d[str(uid)] = True
    _save_started(d)

def _is_start_message(msg: Message | None) -> bool:
    if not msg:
        return False
    text = (msg.text or msg.caption or "").strip()
    if not text:
        return False
    first = text.split()[0]  # يدعم /start و /start@BotName ومعه payload
    return first.startswith("/start")

def _chat_type_of(evt: Message | CallbackQuery | None) -> str:
    try:
        if isinstance(evt, Message):
            return getattr(evt.chat, "type", "private")
        if isinstance(evt, CallbackQuery) and evt.message:
            return getattr(evt.message.chat, "type", "private")
    except Exception:
        pass
    return "private"

class ForceStartMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        state = data.get("state")

        # ===== رسائل المستخدم =====
        if isinstance(event, Message):
            uid = getattr(getattr(event, "from_user", None), "id", None)
            chat_type = _chat_type_of(event)

            # /start: اسمح دائمًا + نظّف الحالة + علّم المستخدم أنه بدأ
            if _is_start_message(event):
                if uid is not None:
                    _mark_started(uid)
                if state:
                    try: await state.clear()
                    except Exception: pass
                return await handler(event, data)

            # إذا الحجب في الخاص فقط وكان الحدث ليس خاصًا → مرّر
            if PRIVATE_ONLY and chat_type != "private":
                return await handler(event, data)

            # إن كان مطلوب /start ولم يبدأ المستخدم بعد
            if REQUIRE_START and uid is not None and not _has_started(uid):
                try:
                    await event.answer("🚫 هذا البوت مقيّد. أرسل /start أولًا.\n🚫 This bot is restricted. Please send /start first.")
                except Exception:
                    pass
                return

            return await handler(event, data)

        # ===== أزرار الكولباك =====
        if isinstance(event, CallbackQuery):
            uid = getattr(getattr(event, "from_user", None), "id", None)
            chat_type = _chat_type_of(event)
            cbdata = (event.data or "")

            # start:* يسمح بالبدء من زر
            if cbdata.startswith("start:"):
                if uid is not None:
                    _mark_started(uid)
                if state:
                    try: await state.clear()
                    except Exception: pass
                return await handler(event, data)

            if PRIVATE_ONLY and chat_type != "private":
                return await handler(event, data)

            if REQUIRE_START and uid is not None and not _has_started(uid):
                try:
                    await event.answer("🚫 هذا البوت مقيّد. أرسل /start أولًا.\n🚫 This bot is restricted. Please send /start first.", show_alert=True)
                except Exception:
                    pass
                return

            return await handler(event, data)

        # أي نوع آخر من التحديثات
        return await handler(event, data)
