# handlers/vip_tools.py
from __future__ import annotations

import os, time, asyncio, logging
from typing import Dict, Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang

try:
    from utils.vip_store import is_vip, get_vip_meta, _now_ts
except Exception:
    def is_vip(_): return False
    def get_vip_meta(_): return {}
    def _now_ts(): return int(time.time())

router = Router(name="vip_tools")
logger = logging.getLogger(__name__)

# إعدادات البيئة للعدّ الحي
REFRESH_SEC = max(1, int(os.getenv("VIP_STATUS_REFRESH_SEC", "5")))
MAX_MINUTES = max(1, int(os.getenv("VIP_STATUS_MAX_MIN", "120")))
MAX_SECONDS = MAX_MINUTES * 60

# ---------- لوحات ----------
def _kb_vip_tools(lang: str):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="💬 " + t(lang, "vip.tools.priority_support"), callback_data="viptool:support"),
        InlineKeyboardButton(text="🧰 " + t(lang, "vip.tools.utilities"),        callback_data="viptool:utils"),
    )
    kb.row(InlineKeyboardButton(text="📅 " + t(lang, "vip.tools.status"),        callback_data="viptool:status"))
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "vip.back_to_menu"),        callback_data="vip:open"))
    return kb.as_markup()

# ---------- فتح قائمة أدوات VIP ----------
@router.callback_query(F.data == "vip:open_tools")
async def open_vip_tools(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_vip(cb.from_user.id):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)
    title = "👑 " + t(lang, "vip.tools.title")
    desc  = t(lang, "vip.tools.desc")
    try:
        await cb.message.edit_text(f"<b>{title}</b>\n{desc}", reply_markup=_kb_vip_tools(lang), parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        await cb.message.answer(f"<b>{title}</b>\n{desc}", reply_markup=_kb_vip_tools(lang), parse_mode=ParseMode.HTML)
    await cb.answer()

# آلياس لو زرّك يرسل vip:open بدلاً من vip:open_tools
@router.callback_query(F.data == "vip:open")
async def open_vip_tools_alias(cb: CallbackQuery):
    await open_vip_tools(cb)

# ---------- عناصر بسيطة ----------
@router.callback_query(F.data == "viptool:support")
async def vip_support(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_vip(cb.from_user.id):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)
    await cb.message.answer(t(lang, "vip.tools.support_msg"), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "viptool:utils")
async def vip_utils(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_vip(cb.from_user.id):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)
    await cb.message.answer(t(lang, "vip.tools.utils_msg"), parse_mode=ParseMode.HTML)
    await cb.answer()

# ---------- حالة الاشتراك (عدّ حي) ----------
_running_tasks: Dict[int, asyncio.Task] = {}  # message_id -> task

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

async def _safe_edit(msg: Message, text: str):
    try:
        return await msg.edit_text(text, parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return msg
        try:
            return await msg.answer(text, parse_mode=ParseMode.HTML)
        except Exception:
            raise

async def _loop_status(msg: Message, user_id: int):
    lang = get_user_lang(user_id) or "en"
    started = _now_ts()
    while True:
        meta = get_vip_meta(user_id) or {}
        exp  = meta.get("expiry_ts")
        if not isinstance(exp, int):  # دائم
            await _safe_edit(msg, _status_text(lang, None, 0))
            break

        now = _now_ts()
        left = exp - now
        if left <= 0:
            await _safe_edit(
                msg,
                "❗ " + t(lang, "vip.status.expired_now") + "\n" + t(lang, "vip.status.contact_support")
            )
            break

        await _safe_edit(msg, _status_text(lang, exp, left))

        if _now_ts() - started >= MAX_SECONDS:
            break
        await asyncio.sleep(REFRESH_SEC)

    _running_tasks.pop(msg.message_id, None)

@router.callback_query(F.data == "viptool:status")
async def vip_status_live(cb: CallbackQuery):
    uid  = cb.from_user.id
    lang = get_user_lang(uid) or "en"
    if not is_vip(uid):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)

    meta = get_vip_meta(uid) or {}
    exp  = meta.get("expiry_ts")
    text = _status_text(lang, exp if isinstance(exp, int) else None, max(0, (exp or 0) - _now_ts()))

    sent = await cb.message.answer(text, parse_mode=ParseMode.HTML)

    # لا نشغّل عداد لمدى الحياة أو المنتهي
    if not isinstance(exp, int) or exp - _now_ts() <= 0:
        return await cb.answer()

    old = _running_tasks.get(sent.message_id)
    if old and not old.done():
        old.cancel()

    _running_tasks[sent.message_id] = asyncio.create_task(_loop_status(sent, uid))
    await cb.answer()
