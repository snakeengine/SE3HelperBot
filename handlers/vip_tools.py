# handlers/vip_tools.py
from __future__ import annotations

import os, time, asyncio, logging, secrets
from contextlib import suppress
from typing import Dict, Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang

try:
    from utils.vip_store import is_vip, get_vip_meta, _now_ts, get_pending
except Exception:
    def is_vip(_): return False
    def get_vip_meta(_): return {}
    def get_pending(_): return {}
    def _now_ts(): return int(time.time())

router = Router(name="vip_tools")
logger = logging.getLogger(__name__)

REFRESH_SEC  = max(1, int(os.getenv("VIP_STATUS_REFRESH_SEC", "5")))
MAX_MINUTES  = max(1, int(os.getenv("VIP_STATUS_MAX_MIN", "120")))
MAX_SECONDS  = MAX_MINUTES * 60

# حاول استخدام لوحة VIP الرئيسية من handlers.vip
try:
    from handlers.vip import _vip_menu_kb as _vip_main_menu_kb  # type: ignore
except Exception:
    _vip_main_menu_kb = None

def _fallback_main_menu_kb(lang: str, *, is_member: bool, has_pending: bool):
    kb = InlineKeyboardBuilder()
    if is_member:
        kb.button(text="🛠️ " + t(lang, "vip.tools.title"), callback_data="vip:open_tools")
        kb.button(text=t(lang, "vip.btn.info"), callback_data="vip:info")
        kb.adjust(1)
    else:
        kb.button(text=t(lang, "vip.btn.apply"), callback_data="vip:apply")
        if has_pending:
            kb.button(text="📨 " + t(lang, "vip.btn.track"),  callback_data="vip:track")
            kb.button(text="⛔ " + t(lang, "vip.btn.cancel"), callback_data="vip:cancel")
        kb.adjust(1)
    return kb.as_markup()

def _fmt_ts(ts: Optional[int], *, date_only: bool = True) -> str:
    if not isinstance(ts, int): return "-"
    fmt = "%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S"
    try: return time.strftime(fmt, time.localtime(ts))
    except Exception: return "-"

# ====== إدارة شاشة الحالة ======
_running_tasks: Dict[int, asyncio.Task] = {}   # user_id -> task
_status_token: Dict[int, str] = {}             # user_id -> token
_status_msg_id: Dict[int, int] = {}            # user_id -> message_id (رسالة شاشة الحالة)

def _new_token(uid: int) -> str:
    tok = secrets.token_hex(8)
    _status_token[uid] = tok
    return tok

def _invalidate_token(uid: int) -> None:
    _status_token.pop(uid, None)

def _stop_status_loop(user_id: int):
    task = _running_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()

async def _delete_status_message(cb: CallbackQuery):
    """يحذف رسالة شاشة الحالة إن وُجدت."""
    uid = cb.from_user.id
    mid = _status_msg_id.pop(uid, None)
    if mid:
        with suppress(Exception):
            await cb.bot.delete_message(chat_id=cb.message.chat.id, message_id=mid)

# ---------- لوحات ----------
def _kb_vip_tools(lang: str):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="💬 " + t(lang, "vip.tools.priority_support"), callback_data="viptool:support"),
        InlineKeyboardButton(text="🧰 " + t(lang, "vip.tools.utilities"),        callback_data="viptool:utils"),
    )
    kb.row(InlineKeyboardButton(text="📅 " + t(lang, "vip.tools.status"),        callback_data="viptool:status"))
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "vip.back_to_menu"),        callback_data="viptool:back"))
    return kb.as_markup()

def _kb_status_view(lang: str):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="↩️ " + t(lang, "vip.back"),          callback_data="vip:open_tools"))
    kb.row(InlineKeyboardButton(text="🏠 " + t(lang, "vip.back_to_menu"),  callback_data="viptool:back"))
    return kb.as_markup()

# ---------- فتح قائمة أدوات VIP ----------
async def _open_tools_after_cleanup(cb: CallbackQuery):
    uid = cb.from_user.id
    _invalidate_token(uid)
    _stop_status_loop(uid)
    await _delete_status_message(cb)

    lang = get_user_lang(uid) or "en"
    if not is_vip(uid):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)

    title = "👑 " + t(lang, "vip.tools.title")
    desc  = t(lang, "vip.tools.desc")
    # أرسل «رسالة جديدة» بدل تعديل رسالة الحالة (حتى لا تعود الحلقة القديمة)
    with suppress(TelegramBadRequest):
        await cb.message.delete()
    await cb.message.answer(f"<b>{title}</b>\n{desc}", reply_markup=_kb_vip_tools(lang), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "vip:open_tools")
async def open_vip_tools(cb: CallbackQuery):
    await _open_tools_after_cleanup(cb)

@router.callback_query(F.data == "vip:open")
async def open_vip_tools_alias(cb: CallbackQuery):
    await _open_tools_after_cleanup(cb)

# ---------- عناصر بسيطة ----------
async def _cleanup_then_send(cb: CallbackQuery, text_key: str):
    uid = cb.from_user.id
    _invalidate_token(uid)
    _stop_status_loop(uid)
    await _delete_status_message(cb)

    lang = get_user_lang(uid) or "en"
    if not is_vip(uid):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)
    await cb.message.answer(t(lang, text_key), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "viptool:support")
async def vip_support(cb: CallbackQuery):
    await _cleanup_then_send(cb, "vip.tools.support_msg")

@router.callback_query(F.data == "viptool:utils")
async def vip_utils(cb: CallbackQuery):
    await _cleanup_then_send(cb, "vip.tools.utils_msg")

# ---------- نصوص حالة الاشتراك ----------
def _fmt_left(left: int) -> str:
    left = max(0, int(left))
    d, r = divmod(left, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)

def _status_text(lang: str, exp: Optional[int], left: int) -> str:
    if not isinstance(exp, int):
        return "👑 <b>" + t(lang, "vip.tools.status_title") + "</b>\n" + t(lang, "vip.status.lifetime")
    exp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))
    return (
        "👑 <b>" + t(lang, "vip.tools.status_title") + "</b>\n"
        f"🗓️ {t(lang,'vip.expires_on')}: <b>{exp_str}</b>\n"
        f"⏳ {t(lang,'vip.status.time_left')}: <b>{_fmt_left(left)}</b>\n"
        f"🔄 {t(lang,'vip.status.auto_refresh')} ({REFRESH_SEC}s)"
    )

async def _safe_edit(msg: Message, text: str, *, reply_markup=None) -> Optional[Message]:
    try:
        edited = await msg.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return edited
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            with suppress(Exception):
                if reply_markup is not None:
                    await msg.edit_reply_markup(reply_markup=reply_markup)
            return msg
        return None
    except Exception:
        return None

async def _loop_status(msg: Message, user_id: int, token: str):
    lang = get_user_lang(user_id) or "en"
    started = _now_ts()
    try:
        while True:
            if _status_token.get(user_id) != token:
                break

            meta = get_vip_meta(user_id) or {}
            exp  = meta.get("expiry_ts")

            if not isinstance(exp, int):
                await _safe_edit(msg, _status_text(lang, None, 0), reply_markup=_kb_status_view(lang))
                break

            left = exp - _now_ts()
            if left <= 0:
                await _safe_edit(
                    msg,
                    "❗ " + t(lang, "vip.status.expired_now") + "\n" + t(lang, "vip.status.contact_support"),
                    reply_markup=_kb_status_view(lang),
                )
                break

            new_msg = await _safe_edit(msg, _status_text(lang, exp, left), reply_markup=_kb_status_view(lang))
            if new_msg is None:
                break
            msg = new_msg

            if _now_ts() - started >= MAX_SECONDS:
                break
            await asyncio.sleep(REFRESH_SEC)
    except asyncio.CancelledError:
        pass
    finally:
        _running_tasks.pop(user_id, None)
        if _status_token.get(user_id) == token:
            _invalidate_token(user_id)
        _status_msg_id.pop(user_id, None)

# ---------- عرض حالة الاشتراك ----------
@router.callback_query(F.data == "viptool:status")
async def vip_status_live(cb: CallbackQuery):
    uid  = cb.from_user.id
    lang = get_user_lang(uid) or "en"
    if not is_vip(uid):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)

    meta = get_vip_meta(uid) or {}
    exp  = meta.get("expiry_ts")
    text = _status_text(lang, exp if isinstance(exp, int) else None, max(0, (exp or 0) - _now_ts()))

    # أبطِل القديمة وأوقفها واحذف رسالتها
    _invalidate_token(uid)
    _stop_status_loop(uid)
    await _delete_status_message(cb)

    token = _new_token(uid)

    # عدّل نفس الرسالة إن أمكن؛ إن فشل، أرسل رسالة جديدة
    edited = await _safe_edit(cb.message, text, reply_markup=_kb_status_view(lang))
    if edited is None:
        edited = await cb.message.answer(text, reply_markup=_kb_status_view(lang), parse_mode=ParseMode.HTML)

    # خزّن message_id للحذف لاحقًا
    _status_msg_id[uid] = edited.message_id

    if not isinstance(exp, int) or exp - _now_ts() <= 0:
        return await cb.answer()

    _running_tasks[uid] = asyncio.create_task(_loop_status(edited, uid, token))
    await cb.answer()

# ---------- رجوع للقائمة الرئيسية ----------
@router.callback_query(F.data == "viptool:back")
async def vip_tool_back(cb: CallbackQuery):
    uid  = cb.from_user.id
    lang = get_user_lang(uid) or "en"

    _invalidate_token(uid)
    _stop_status_loop(uid)
    await _delete_status_message(cb)

    member  = is_vip(uid)
    pending = get_pending(uid)
    header  = [t(lang, "vip.panel_title")]
    if member:
        meta = get_vip_meta(uid) or {}
        expiry_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
        if expiry_str != "-":
            header.append(f"🗓️ {t(lang,'vip.expires_on')}: {expiry_str}")

    kb = _vip_main_menu_kb(lang, is_member=member, has_pending=bool(pending)) if _vip_main_menu_kb \
         else _fallback_main_menu_kb(lang, is_member=member, has_pending=bool(pending))

    # احذف رسالة الحالة/الحالية ثم أرسل لوحة جديدة (رسالة جديدة)
    with suppress(TelegramBadRequest):
        await cb.message.delete()
    await cb.message.answer(
        "\n".join(header) + "\n" + (t(lang, "vip.menu.subscribed") if member else t(lang, "vip.menu.not_subscribed")),
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await cb.answer()
