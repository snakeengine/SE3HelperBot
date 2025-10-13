from __future__ import annotations

# handlers/force_join_auto.py

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, ChatMemberUpdated, User
from aiogram.enums import ChatType, ChatMemberStatus

from middlewares.force_join import _parse_required, _is_member, _build_markup, _L, _tr

router = Router(name="force_join_auto")

async def _joined_all(bot, user_id: int) -> bool:
    for ident, _ in _parse_required():
        ok = await _is_member(bot, user_id, ident)  # type: ignore
        if not ok:
            return False
    return True

async def _open_home_or_notify(bot, user_id: int, lang: str):
    # حاول استدعاء واجهة البداية إن وُجدت، وإلا رسالة ترحيب.
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
            await opener(bot=bot, user_id=user_id)  # نوع توقيع شائع
            return
        except TypeError:
            try:
                await opener(user_id)  # توقيع بديل
                return
            except Exception:
                pass
        except Exception:
            pass

    await bot.send_message(
        user_id,
        _tr(lang, "✅ تم التحقّق تلقائيًا — أهلاً بك! يمكنك المتابعة الآن.",
                    "✅ Verified automatically — welcome! You can continue now.")
    )

@router.callback_query(F.data == "fj_check")
async def on_check(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(cb.from_user)
    if await _joined_all(cb.bot, uid):
        try:
            await cb.answer(_tr(lang, "تم التحقّق ✅", "Verified ✅"), show_alert=False)
        except Exception:
            pass
        await _open_home_or_notify(cb.bot, uid, lang)
        try:
            await cb.message.delete()
        except Exception:
            pass
    else:
        try:
            await cb.answer(_tr(lang, "لم يتم العثور على الاشتراك بعد.", "You haven't joined yet."), show_alert=True)
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=_build_markup(_parse_required(), lang))
        except Exception:
            pass

@router.chat_member()
async def on_channel_join(ev: ChatMemberUpdated):
    chat = ev.chat
    if chat.type not in {ChatType.CHANNEL, ChatType.SUPERGROUP}:
        return

    new_status = ev.new_chat_member.status
    if new_status not in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return

    user: User = ev.new_chat_member.user
    if not user or user.is_bot:
        return

    # هل القناة التي تغيّرت ضمن المطلوب؟
    idents = {str(chat.id)}
    username = getattr(chat, "username", None)
    if username:
        idents.add(f"@{username}")

    required = {ident for ident, _ in _parse_required()}
    if idents.isdisjoint(required):
        return

    if await _joined_all(ev.bot, user.id):
        lang = _L(user)
        logging.info("[FJ-AUTO] user %s completed required joins", user.id)
        await _open_home_or_notify(ev.bot, user.id, lang)
