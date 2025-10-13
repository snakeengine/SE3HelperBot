# middlewares/force_join.py
from __future__ import annotations

import os, time, logging
from typing import Iterable, Tuple, Optional

from aiogram import BaseMiddleware, Bot
from aiogram.types import User, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter

log = logging.getLogger("middlewares.force_join")

# ---- لغة المستخدم ----
def _L(u: Optional[User]) -> str:
    try:
        from lang import get_user_lang  # لو عندك نظام لغات
        if u:
            v = (get_user_lang(u.id) or "").strip().lower()
            if v:
                return v
    except Exception:
        pass
    lc = (getattr(u, "language_code", None) or "").lower()
    return lc or "ar"

def _tr(lang: str, ar: str, en: str) -> str:
    return ar if lang.startswith("ar") else en

# ---- إعدادات القنوات والإدمن ----
def _parse_required() -> list[Tuple[str, Optional[str]]]:
    raw = os.getenv("REQUIRED_CHANNELS", "") or ""
    required: list[Tuple[str, Optional[str]]] = []
    for p in map(str.strip, raw.split(",")):
        if not p:
            continue
        invite = None
        if p.lstrip("-").isdigit():
            key = f"REQUIRED_INVITE_{p}"
            invite = os.getenv(key)
        required.append((p, invite))
    return required

def _load_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: set[int] = set()
    for p in map(str.strip, str(raw).split(",")):
        if p.isdigit():
            ids.add(int(p))
    if not ids:
        ids = {7360982123,8371697148}
    return ids

def _channel_public_url(identifier: str, invite_link: Optional[str]) -> Optional[str]:
    if identifier.startswith("@"):
        return f"https://t.me/{identifier[1:]}"
    if invite_link:
        return invite_link
    return None

async def _is_member(bot: Bot, user_id: int, chat: str | int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat, user_id=user_id)
    except (TelegramForbiddenError, TelegramBadRequest, Exception):
        return False
    status = getattr(member, "status", None)
    if status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR, ChatMemberStatus.MEMBER}:
        return True
    if status == ChatMemberStatus.RESTRICTED:
        return bool(getattr(member, "is_member", False))
    return False

def _build_markup(required: Iterable[Tuple[str, Optional[str]]], lang: Optional[str] = None) -> InlineKeyboardMarkup:
    lang = lang or "ar"
    rows: list[list[InlineKeyboardButton]] = []
    for ident, invite in required:
        url = _channel_public_url(ident, invite)
        if ident.startswith("@"):
            text = _tr(lang, f"اشترك في {ident}", f"Subscribe to {ident}")
        else:
            text = _tr(lang, "اشترك في القناة", "Join the channel")
        if url:
            rows.append([InlineKeyboardButton(text=text, url=url)])
    rows.append([InlineKeyboardButton(text=_tr(lang, "تحقّق", "Check"), callback_data="fj_check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

class ForceJoinMiddleware(BaseMiddleware):
    """
    يجبر المستخدم على الاشتراك قبل المتابعة (مع كاش وثروتل).
    """
    def __init__(self) -> None:
        super().__init__()
        self.required = _parse_required()
        self.admins = _load_admin_ids()
        self.include_admins = os.getenv("FORCE_JOIN_INCLUDE_ADMINS", "0").strip().lower() in {"1", "true", "yes"}

        self.cache_ttl = int(os.getenv("FJ_CACHE_TTL", "8"))
        self.prompt_ttl = int(os.getenv("FJ_PROMPT_TTL", "10"))

        self._cache: dict[tuple[int, str], tuple[bool, float]] = {}
        self._prompted_until: dict[int, float] = {}

        log.info("[FJ] required=%s admins=%s include_admins=%s", self.required, self.admins, self.include_admins)

    async def __call__(self, handler, event, data):
        if not self.required:
            return await handler(event, data)

        user: Optional[User] = None
        message: Optional[Message] = None
        if isinstance(event, Message):
            message, user = event, event.from_user
        elif isinstance(event, CallbackQuery):
            message, user = event.message, event.from_user
        else:
            user = data.get("event_from_user")

        if not message or message.chat.type != ChatType.PRIVATE:
            return await handler(event, data)
        if not user:
            return await handler(event, data)

        if (user.id in self.admins) and not self.include_admins:
            return await handler(event, data)

        bot: Bot = data["bot"]
        now = time.monotonic()
        lang = _L(user)

        for ident, _ in self.required:
            key = (user.id, str(ident))
            cached = self._cache.get(key)

            if cached and cached[1] > now:
                ok = cached[0]
            else:
                try:
                    ok = await _is_member(bot, user.id, ident)  # type: ignore
                except TelegramRetryAfter:
                    ok = False
                except Exception:
                    ok = False
                self._cache[key] = (ok, now + self.cache_ttl)

            if not ok:
                not_before = self._prompted_until.get(user.id, 0.0)
                if now >= not_before:
                    try:
                        kb = _build_markup(self.required, lang)
                        txt = _tr(lang,
                                  "للمتابعة، الرجاء الانضمام إلى القناة المطلوبة ثم اضغط تحقّق.",
                                  "To continue, please join the required channel then tap Check.")
                        await message.answer(txt, reply_markup=kb, disable_web_page_preview=True)
                    except Exception as e:
                        log.warning("[FJ] failed to prompt user %s: %s", user.id, e)
                    self._prompted_until[user.id] = now + self.prompt_ttl

                log.info("[FJ] blocked user %s for %s", user.id, ident)
                return  # امنع بقية الهاندلرز

        return await handler(event, data)

__all__ = ["ForceJoinMiddleware", "_parse_required", "_is_member", "_build_markup", "_L", "_tr"]
