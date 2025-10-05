# handlers/rewards_gate.py
from __future__ import annotations

import os
import time
import asyncio
import logging
from typing import List, Tuple, Union, Dict

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, ChatMemberUpdated
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
    # Aiogram v3 statuses:
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest

from utils.rewards_flags import is_global_paused, is_user_paused
from lang import t, get_user_lang
from utils.rewards_store import (
    set_blocked, is_blocked, add_points, ensure_user, mark_warn, get_points
)
from aiogram.filters import StateFilter
from handlers.live_chat import LiveChat


router = Router(name="rewards_gate")
# امنع التنفيذ أثناء جلسة الدردشة الحيّة، واشتغل بالخاص فقط
router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
router.callback_query.filter(F.message.chat.type == "private", ~StateFilter(LiveChat.active))

# امنع أي رسائل/كولباكات خاصة أثناء جلسة الدردشة الحيّة،
# وحصّر كولباكات هذا الملف على بادئة rwd:gate:
router.message.filter(
    F.chat.type == "private",
    ~StateFilter(LiveChat.active)
)
router.callback_query.filter(
    F.message.chat.type == "private",
    ~StateFilter(LiveChat.active),
    F.data.func(lambda s: isinstance(s, str) and s.startswith("rwd:gate:"))
)

# ملاحظة: chat_member updates لا نقيّدها لأنها تأتي من القنوات/السوبرجروبات
# وليست جزءًا من محادثة المستخدم الخاصة، وبالتالي ما تتأثر بـ LiveChat.
log = logging.getLogger(__name__)

# ---------------------- إعداد إشعار الأدمن ----------------------
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in _admin_env.split(",") if x.strip().isdigit()]

async def _notify_admins(bot, text: str):
    """
    يحاول الإرسال عبر utils.admin_notify.notify_admins إن وُجد؛
    وإلا يرسل مباشرة إلى ADMIN_IDS.
    """
    try:
        from utils.admin_notify import notify_admins  # type: ignore
        await notify_admins(bot, text)
        return
    except Exception:
        pass
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, text)
        except Exception:
            pass

# ---------------------- الإعدادات ----------------------
def _parse_channels(value: str) -> List[Union[int, str]]:
    items: List[Union[int, str]] = []
    for raw in (value or "").split(","):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("@"):
            items.append(s)  # username
        else:
            try:
                items.append(int(s))
            except Exception:
                pass
    return items

# مثال REWARDS_CHANNELS: "@SnakeEngine,-1001234567890"
REQUIRED_CHANNELS = _parse_channels(os.getenv("REWARDS_CHANNELS", ""))

LEAVE_DEDUCT_DEFAULT = int(os.getenv("REWARDS_LEAVE_DEDUCT", "50"))
GRACE_SECONDS        = int(os.getenv("REWARDS_GRACE_SECONDS", "120"))   # مهلة السماح
MEMBERSHIP_TTL       = int(os.getenv("REWARDS_RECHECK_TTL", "60"))      # كاش فحص الاشتراك
ESCALATE             = os.getenv("REWARDS_DEDUCT_ESCALATE", "").strip() # "20,50,100"
DEDUCT_SEQ           = [int(x) for x in ESCALATE.split(",") if x.strip().isdigit()]
SKIP_ADMINS          = int(os.getenv("REWARDS_SKIP_ADMINS", "1"))       # إعفاء الأدمن

# تنبيه مبكّر وحدّ السلوك مع الرصيد الصفري:
PREWARN_ON_LEAVE = int(os.getenv("REWARDS_PREWARN", "1"))        # 1=فعّال
WARN_ZERO_BAL    = int(os.getenv("REWARDS_WARN_ZERO_BAL", "0"))  # 0=لا تنبّه إن الرصيد صفر

# ✅ مفاتيح كتم إشعارات الأدمن (افتراضيًا متوقفة)
NOTIFY_LEAVE      = int(os.getenv("REWARDS_NOTIFY_LEAVE", "0"))        # إشعار "Leave detected"
NOTIFY_JOIN_BACK  = int(os.getenv("REWARDS_NOTIFY_JOIN_BACK", "0"))    # إشعار "User re-subscribed"

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

# ---------------------- كاش ----------------------
_channel_title_cache: Dict[Union[int, str], str] = {}
_membership_cache: Dict[tuple[int, Union[int, str]], tuple[bool, int]] = {}
_leave_pending: Dict[tuple[int, Union[int, str]], int] = {}  # (uid, channel)->ts

async def _get_channel_title(bot, channel: Union[int, str]) -> str:
    if channel in _channel_title_cache:
        return _channel_title_cache[channel]
    try:
        chat = await bot.get_chat(channel)
        title = chat.title or (channel if isinstance(channel, str) else str(channel))
    except Exception:
        title = (channel if isinstance(channel, str) else str(channel))
    _channel_title_cache[channel] = title
    return title

async def _is_member_of(bot, user_id: int, channel: Union[int, str]) -> bool:
    key = (user_id, channel)
    now = int(time.time())
    cached = _membership_cache.get(key)
    if cached and now - cached[1] < MEMBERSHIP_TTL:
        return cached[0]
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        ok = member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        ok = False
    _membership_cache[key] = (ok, now)
    return ok

async def check_membership(bot, user_id: int) -> Tuple[bool, List[Union[int, str]]]:
    if SKIP_ADMINS and user_id in ADMIN_IDS:
        return True, []
    if not REQUIRED_CHANNELS:
        return True, []
    missing = []
    for ch in REQUIRED_CHANNELS:
        if not await _is_member_of(bot, user_id, ch):
            missing.append(ch)
    return (len(missing) == 0), missing

# ---------------------- كيبورد الانضمام ----------------------
def _channel_url(ch: Union[int, str]) -> str:
    if isinstance(ch, int):
        return f"https://t.me/c/{str(ch)[4:]}" if str(ch).startswith("-100") else f"https://t.me/{ch}"
    uname = ch[1:] if isinstance(ch, str) and ch.startswith("@") else str(ch)
    return f"https://t.me/{uname}"

async def join_keyboard(bot, lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for ch in REQUIRED_CHANNELS:
        try:
            title = await _get_channel_title(bot, ch)
        except Exception:
            title = str(ch)
        btn_txt = t(lang, "rewards.gate.join_named", "اشترك في {name}").format(name=title or str(ch))
        kb.row(InlineKeyboardButton(text=btn_txt, url=_channel_url(ch)))
    kb.row(
        InlineKeyboardButton(text=t(lang, "rewards.gate.ive_joined", "✅ اشتركت / تحقق"), callback_data="rwd:gate:recheck")
    )
    kb.row(InlineKeyboardButton(text=t(lang, "common.close", "إغلاق"), callback_data="rwd:gate:close"))
    return kb

# ---------------------- واجهة الإلزام ----------------------
async def require_membership(msg_or_cb: Message | CallbackQuery) -> bool:
    uid = msg_or_cb.from_user.id
    lang = _L(uid)

    if is_global_paused() or is_user_paused(uid):
        txt = t(lang, "rewards.paused", "⏸️ نظام الجوائز متوقف مؤقتًا من الإدارة.")
        if isinstance(msg_or_cb, Message):
            await msg_or_cb.answer(txt)
        else:
            await msg_or_cb.answer(txt, show_alert=True)
        return False

    ok, missing = await check_membership(msg_or_cb.bot, uid)
    if ok:
        set_blocked(uid, False)
        return True

    set_blocked(uid, True)
    text = t(lang, "rewards.gate.required", "الاشتراك بالقنوات إلزامي لاستخدام الجوائز.")
    if missing:
        lines = []
        for ch in missing:
            title = await _get_channel_title(msg_or_cb.bot, ch)
            lines.append(f"• {title}")
        if lines:
            text += "\n" + t(lang, "rewards.gate.missing_list", "القنوات المطلوبة التي لم تشترك بها:") + "\n" + "\n".join(lines)
    kb_markup = (await join_keyboard(msg_or_cb.bot, lang)).as_markup()

    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text, reply_markup=kb_markup, disable_web_page_preview=True)
    else:
        try:
            if msg_or_cb.message:
                await msg_or_cb.message.edit_text(text, reply_markup=kb_markup, disable_web_page_preview=True)
            else:
                await msg_or_cb.answer(text, show_alert=True)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await msg_or_cb.answer(
                    t(lang, "rewards.gate.still_missing", "لم نرصد اشتراكك بعد. تأكد ثم اضغط \"تحقق\" مرة أخرى."),
                    show_alert=True
                )
            else:
                raise
    return False

# ---------------------- أوامر مساعدة ----------------------
@router.message(Command("rewards_join"))
async def cmd_rewards_join(m: Message):
    lang = _L(m.from_user.id)
    await m.answer(
        t(lang, "rewards.gate.required", "الاشتراك بالقنوات إلزامي لاستخدام الجوائز."),
        reply_markup=(await join_keyboard(m.bot, lang)).as_markup(),
        disable_web_page_preview=True
    )

@router.callback_query(F.data == "rwd:gate:close")
async def cb_gate_close(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        await cb.answer("OK", show_alert=False)

@router.callback_query(F.data == "rwd:gate:recheck")
async def cb_gate_recheck(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return
    try:
        from . import rewards_hub as _hub
        await _hub.open_hub(cb, edit=True)
    except Exception:
        await cb.answer("OK", show_alert=False)

# ---------------------- حساب قيمة الخصم ----------------------
def _calc_deduct(uid: int) -> int:
    u = ensure_user(uid)
    warns = int(u.get("warns", 0))
    if DEDUCT_SEQ:
        idx = warns if warns < len(DEDUCT_SEQ) else len(DEDUCT_SEQ) - 1
        return int(DEDUCT_SEQ[idx])
    return LEAVE_DEDUCT_DEFAULT

# ---------------------- تنبيه مبكّر عند المغادرة ----------------------
async def _send_preleave_notice(bot, uid: int, channel: Union[int, str]):
    if not PREWARN_ON_LEAVE:
        return
    # إن عاد فورًا لا داعي للتنبيه
    if await _is_member_of(bot, uid, channel):
        return

    ensure_user(uid)
    try:
        bal = int(get_points(uid))
    except Exception:
        bal = 0

    lang = _L(uid)
    title = await _get_channel_title(bot, channel)
    deduct = abs(_calc_deduct(uid))

    if bal <= 0 and not WARN_ZERO_BAL:
        text = t(
            lang,
            "rewards.gate.left_pre_nodeduct",
            "ℹ️ غادرت قناة إلزامية ({name}). سيتم إيقاف الجوائز حتى تعود للاشتراك."
        ).format(name=title)
    else:
        text = t(
            lang,
            "rewards.gate.left_pre",
            "⚠️ لقد غادرت قناة إلزامية ({name}). لديك {grace} ثوانٍ للعودة قبل خصم {deduct} نقطة وإيقاف الجوائز."
        ).format(name=title, grace=GRACE_SECONDS, deduct=deduct)

    try:
        await bot.send_message(
            chat_id=uid,
            text=text,
            reply_markup=(await join_keyboard(bot, lang)).as_markup(),
            disable_web_page_preview=True
        )
    except Exception:
        pass

# ---------------------- مهلة السماح والخصم ----------------------
async def _apply_grace_and_deduct(bot, uid: int, channel: Union[int, str], leave_ts: int):
    await asyncio.sleep(max(0, GRACE_SECONDS))

    if _leave_pending.get((uid, channel)) != leave_ts:
        return

    if await _is_member_of(bot, uid, channel):
        return  # عاد خلال المهلة

    ensure_user(uid)

    try:
        bal = int(get_points(uid))
    except Exception:
        bal = 0

    title  = await _get_channel_title(bot, channel)
    lang   = _L(uid)
    deduct = abs(_calc_deduct(uid))

    # إقفال الجوائز دائمًا بعد ثبوت المغادرة
    set_blocked(uid, True)
    mark_warn(uid, "left_required_channel")

    if bal <= 0:
        # لا خصم لعدم وجود رصيد — إشعار أدمن اختياري
        if NOTIFY_LEAVE:
            try:
                await _notify_admins(
                    bot,
                    (
                        "🚫 <b>Leave detected</b>\n"
                        f"• User: <a href='tg://user?id={uid}'>{uid}</a>\n"
                        f"• Channel: <b>{title}</b>\n"
                        "• Deducted: <b>0</b> pts (no balance)\n"
                        "• Rewards blocked."
                    )
                )
            except Exception:
                pass
        return

    if deduct > 0:
        add_points(uid, -deduct, reason="left_required_channel", typ="penalty")

    try:
        await bot.send_message(
            chat_id=uid,
            text=t(
                lang,
                "rewards.gate.left_warn",
                "⚠️ تم رصد خروجك من قناة إلزامية ({name}). حُذِف {deduct} نقطة وتم إغلاق الجوائز حتى تعود للاشتراك."
            ).format(name=title, deduct=deduct),
            reply_markup=(await join_keyboard(bot, lang)).as_markup(),
            disable_web_page_preview=True
        )
    except Exception:
        pass

    # إشعار الأدمن — اختياري
    if NOTIFY_LEAVE:
        try:
            await _notify_admins(
                bot,
                (
                    "🚫 <b>Leave detected</b>\n"
                    f"• User: <a href='tg://user?id={uid}'>{uid}</a>\n"
                    f"• Channel: <b>{title}</b>\n"
                    f"• Deducted: <b>{deduct}</b> pts\n"
                    "• Rewards blocked."
                )
            )
        except Exception:
            pass

# ---------------------- مراقبة تغيّرات العضوية ----------------------
@router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated):
    """
    - عند الانضمام: فكّ الحظر وأرسل ترحيب مع زر فتح الجوائز + (إشعار أدمن اختياري).
    - عند المغادرة: تنبيه مبكّر + مهلة سماح ثم خصم/إقفال + (إشعار أدمن اختياري).
    """
    chat_id = event.chat.id
    if not REQUIRED_CHANNELS:
        return
    configured_ids = {c for c in REQUIRED_CHANNELS if isinstance(c, int)}
    if configured_ids and chat_id not in configured_ids:
        return

    user = event.new_chat_member.user
    uid = user.id
    if SKIP_ADMINS and uid in ADMIN_IDS:
        return

    new_status = event.new_chat_member.status

    # ===== عاد أو اشترك
    if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        _leave_pending.pop((uid, chat_id), None)
        was_blocked = is_blocked(uid)
        set_blocked(uid, False)
        if was_blocked:
            lang = _L(uid)
            try:
                kb = InlineKeyboardBuilder()
                kb.row(
                    InlineKeyboardButton(
                        text=t(lang, "rewards.gate.open_rewards_btn", "🎉 Open Rewards"),
                        callback_data="rwd:hub",
                    )
                )
                await event.bot.send_message(
                    chat_id=uid,
                    text=t(lang, "rewards.gate.joined_back", "🎉 تم تفعيل الجوائز مجددًا بعد اشتراكك."),
                    reply_markup=kb.as_markup(),
                )
            except Exception:
                pass
            # إشعار الأدمن بعودة الاشتراك — اختياري
            if NOTIFY_JOIN_BACK:
                try:
                    title = await _get_channel_title(event.bot, chat_id)
                    await _notify_admins(
                        event.bot,
                        (
                            "✅ <b>User re-subscribed</b>\n"
                            f"• User: <a href='tg://user?id={uid}'>{uid}</a>\n"
                            f"• Channel: <b>{title}</b>\n"
                            "• Rewards unlocked."
                        )
                    )
                except Exception:
                    pass
        return

    # ===== غادر القناة
    if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        leave_ts = int(time.time())
        _leave_pending[(uid, chat_id)] = leave_ts
        # تنبيه مبكّر
        asyncio.create_task(_send_preleave_notice(event.bot, uid, chat_id))
        # ثم مهلة السماح والخصم
        asyncio.create_task(_apply_grace_and_deduct(event.bot, uid, chat_id, leave_ts))
