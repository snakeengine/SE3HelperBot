from __future__ import annotations

# handlers/force_join_auto.py

import logging
from typing import Optional, Iterable, Tuple

from aiogram import Router, F
from aiogram.types import ChatMemberUpdated, ChatJoinRequest, CallbackQuery, User
from aiogram.enums import ChatType, ChatMemberStatus

from middlewares.force_join import _parse_required, _is_member, _build_markup

router = Router(name="force_join_auto")

def _L_from_user(u: Optional[User]) -> str:
    try:
        from lang import get_user_lang  # type: ignore
        if u:
            lng = (get_user_lang(u.id) or "").strip().lower()
            if lng:
                return lng
    except Exception:
        pass
    lc = (getattr(u, "language_code", None) or "").lower()
    return lc or "ar"

def _tr(lang: str, ar: str, en: str) -> str:
    return ar if lang.startswith("ar") else en

async def _joined_all_required(bot, user_id: int) -> bool:
    for ident, _ in _parse_required():
        ok = await _is_member(bot, user_id, ident)  # type: ignore
        if not ok:
            return False
    return True

async def _open_home_or_ping(bot, user_id: int, lang: str):
    # حاول فتح الواجهة الرئيسية (لو عندك دالة لهذا الغرض)
    opener = None
    try:
        from handlers.start import open_home as opener  # type: ignore
    except Exception:
        try:
            from handlers.start import show_home as opener  # type: ignore
        except Exception:
            opener = None

    if opener:
        try:
            await opener(bot=bot, user_id=user_id)  # type: ignore[arg-type]
            return
        except TypeError:
            try:
                await opener(user_id)  # type: ignore[misc]
                return
            except Exception:
                pass
        except Exception:
            pass

    # Fallback: رسالة نجاح مترجمة
    try:
        await bot.send_message(
            user_id,
            _tr(lang, "✅ تم التحقّق تلقائيًا — أهلاً بك! القائمة باتت متاحة الآن.",
                      "✅ Verified automatically — welcome! The menu is now available.")
        )
    except Exception as e:
        logging.warning(f"[FJ-AUTO] failed to DM user {user_id}: {e}")

@router.callback_query(F.data == "fj_check")
async def fj_check(cb: CallbackQuery):
    uid = cb.from_user.id
    bot = cb.bot
    lang = _L_from_user(cb.from_user)

    if await _joined_all_required(bot, uid):
        try:
            await cb.answer(_tr(lang, "تم التحقّق ✅", "Verified ✅"), show_alert=False)
        except Exception:
            pass
        await _open_home_or_ping(bot, uid, lang)
        try:
            await cb.message.delete()
        except Exception:
            pass
        return

    # ما زال غير مشترك—أعد نفس اللوحة بلغة المستخدم
    try:
        await cb.answer(_tr(lang, "لسه ما اشتركت بالقناة المطلوبة.", "You still haven’t joined the required channel."), show_alert=True)
    except Exception:
        pass
    try:
        await cb.message.edit_reply_markup(reply_markup=_build_markup(_parse_required(), lang))
    except Exception:
        pass

@router.chat_member()
async def auto_unlock_on_join(ev: ChatMemberUpdated):
    chat = ev.chat
    if chat.type not in {ChatType.CHANNEL, ChatType.SUPERGROUP}:
        return

    new_status = ev.new_chat_member.status
    if new_status not in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return

    user = ev.new_chat_member.user
    if not user or user.is_bot:
        return

    # هل التشات هذا ضمن المطلوب؟
    identifiers = set()
    username = getattr(chat, "username", None)
    if username:
        identifiers.add(f"@{username}")
    identifiers.add(str(chat.id))

    required_idents = {ident for ident, _ in _parse_required()}
    if identifiers.isdisjoint(required_idents):
        return

    if await _joined_all_required(ev.bot, user.id):
        lang = _L_from_user(user)
        logging.info(f"[FJ-AUTO] user {user.id} completed required joins — unlocking.")
        await _open_home_or_ping(ev.bot, user.id, lang)

@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest):
    # اتركها فارغة/اختيارية
    pass
