from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/support_inbox_admin.py

import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from lang import get_user_lang, t as _t

from utils.support_inbox import (
    get_counts, claim_next, list_waiting, release, close, mark_replied
)
# Ø¯Ù…Ø¬ Ø§Ù„Ø¬Ø³Ø± Ù„Ù„Ø¨Ù„Ø§ØºØ§Øª Ø¹Ù†Ø¯ Ø§Ù„Ø±Ø¯Ù‘:
try:
    from handlers.report import set_thread_open as _open_report_session  # Ø³ÙŠÙØ¹Ø±Ù‘Ù Ù„Ø¯ÙŠÙƒ
except Exception:
    _open_report_session = None

router = Router(name="support_inbox_admin")

ADMIN_IDS = get_admin_ids()
def _is_admin(uid: int) -> bool: return (int(uid) in ADMIN_IDS)

def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = _t(lang, key)
        return fallback if not s or s == key else s
    except Exception:
        return fallback

# ====== Ø´Ø§Ø´Ø© Ø±Ø¦ÙŠØ³ÙŠØ© ======
def _home_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ðŸ“ " + _tf(lang,"inbox.next_report","Ø§Ù„ØªØ§Ù„ÙŠ (Ø¨Ù„Ø§Øº)"),
                              callback_data="sin:next:report"),
         InlineKeyboardButton(text="ðŸ’¬ " + _tf(lang,"inbox.next_chat","Ø§Ù„ØªØ§Ù„ÙŠ (Ø¯Ø±Ø¯Ø´Ø©)"),
                              callback_data="sin:next:chat")],
        [InlineKeyboardButton(text="ðŸ“¥ " + _tf(lang,"inbox.list_reports","Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø± (Ø¨Ù„Ø§Øº)"),
                              callback_data="sin:list:report"),
         InlineKeyboardButton(text="ðŸ“¥ " + _tf(lang,"inbox.list_chats","Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø± (Ø¯Ø±Ø¯Ø´Ø©)"),
                              callback_data="sin:list:chat")],
        [InlineKeyboardButton(text="ðŸ”„ " + _tf(lang,"inbox.refresh","ØªØØ¯ÙŠØ«"), callback_data="sin:home")]
    ])

async def _render_home(msg_or_cb, lang: str):
    c = get_counts()
    text = (
        "ðŸ“¬ <b>Support Inbox</b>\n"
        f"â€¢ Reports â€” waiting: <b>{c['report']['waiting']}</b>, assigned: <b>{c['report']['assigned']}</b>, total: {c['report']['total']}\n"
        f"â€¢ Live chat â€” waiting: <b>{c['chat']['waiting']}</b>, assigned: <b>{c['chat']['assigned']}</b>, total: {c['chat']['total']}\n"
        "\n" + _tf(lang,"inbox.help","Ø§Ø®ØªØ± â€œØ§Ù„ØªØ§Ù„ÙŠâ€ Ù„ÙØªØ Ø£ÙˆÙ„ ØªØ°ÙƒØ±Ø© Ø¨Ø§Ù†ØªØ¸Ø§Ø±Ùƒ.")
    )
    kb = _home_kb(lang)
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.reply(text, reply_markup=kb)
    else:
        await msg_or_cb.message.edit_text(text, reply_markup=kb)

@router.message(Command("inbox"))
async def inbox_cmd(m: Message):
    if not _is_admin(m.from_user.id): return
    lang = get_user_lang(m.from_user.id) or "en"
    await _render_home(m, lang)

@router.callback_query(F.data == "sin:home")
async def inbox_home(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    lang = get_user_lang(cb.from_user.id) or "en"
    await _render_home(cb, lang); await cb.answer()

# ====== ÙØªØ Ø§Ù„ØªØ§Ù„ÙŠ ======
def _ticket_kb(uid: int, src: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="âœ‰ï¸ " + _tf(lang,"inbox.reply","Ø±Ø¯Ù‘"), callback_data=f"sin:reply:{src}:{uid}")],
        [InlineKeyboardButton(text="âï¸ " + _tf(lang,"inbox.skip","ØªØ®Ø·ÙŠ"), callback_data=f"sin:skip:{src}:{uid}"),
         InlineKeyboardButton(text="âœ… " + _tf(lang,"inbox.close","Ø¥ØºÙ„Ø§Ù‚"), callback_data=f"sin:close:{src}:{uid}")],
        [InlineKeyboardButton(text="â¬…ï¸ " + _tf(lang,"inbox.back","Ø±Ø¬ÙˆØ¹"), callback_data="sin:home")]
    ])

async def _open_next(cb: CallbackQuery, src: str):
    lang = get_user_lang(cb.from_user.id) or "en"
    rec = claim_next(cb.from_user.id, src)
    if not rec:
        return await cb.answer(_tf(lang,"inbox.empty","Ù„Ø§ ØªÙˆØ¬Ø¯ Ø¹Ù†Ø§ØµØ± Ø¨Ø§Ù†ØªØ¸Ø§Ø±Ùƒ"), show_alert=True)
    uid = rec["uid"]
    text = (f"ðŸ‘¤ <b>UID</b>: <code>{uid}</code>\n"
            f"â€¢ Source: <b>{src}</b>\n"
            f"â€¢ New msgs: <b>{rec.get('count',0)}</b>\n"
            f"â€¢ Preview: {rec.get('preview','-')}")
    await cb.message.edit_text(text, reply_markup=_ticket_kb(uid, src, lang))
    await cb.answer()

@router.callback_query(F.data.in_(["sin:next:report","sin:next:chat"]))
async def next_any(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src = cb.data.split(":")
    await _open_next(cb, src)

# ====== Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø± Ø§Ù„Ù…Ø®ØªØµØ±Ø© ======
@router.callback_query(F.data.in_(["sin:list:report","sin:list:chat"]))
async def list_wait(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src = cb.data.split(":")
    lang = get_user_lang(cb.from_user.id) or "en"
    total, items = list_waiting(src, limit=10, offset=0)
    if not items:
        return await cb.answer(_tf(lang,"inbox.empty","Ù„Ø§ ØªÙˆØ¬Ø¯ Ø¹Ù†Ø§ØµØ± Ø¨Ø§Ù†ØªØ¸Ø§Ø±Ùƒ"), show_alert=True)
    lines = [f"ðŸ“¥ <b>{src} â€” waiting {total}</b>"]
    for it in items:
        lines.append(f"â€¢ <code>{it['uid']}</code> Â· {it.get('count',0)} Â· {it.get('preview','-')[:40]}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_home_kb(lang))
    await cb.answer()

# ====== Ø§Ù„Ø±Ø¯Ù‘ ======
class InboxState(StatesGroup):
    waiting_reply = State()

@router.callback_query(F.data.startswith("sin:reply:"))
async def start_reply(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src, uid = cb.data.split(":"); uid = int(uid)
    await state.set_state(InboxState.waiting_reply)
    await state.update_data(uid=uid, src=src)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer()
    await cb.message.answer(_tf(lang,"inbox.reply_prompt","Ø£Ø±Ø³Ù„ Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ø§Ù„ØªÙŠ ØªØ±ÙŠØ¯ Ø¥Ø±Ø³Ø§Ù„Ù‡Ø§ Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… (Ù†Øµ/Ù…ÙŠØ¯ÙŠØ§)."))

@router.message(InboxState.waiting_reply)
async def do_reply(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id): return
    data = await state.get_data(); await state.clear()
    uid, src = int(data["uid"]), data["src"]
    # Ø£Ø±Ø³Ù„ Ø§Ù„Ù†Ø³Ø®Ø© Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù…
    try:
        await m.copy_to(chat_id=uid)
    except Exception:
        await m.bot.send_message(uid, (m.text or ""))
    # Ø§ÙØªØ Ø§Ù„Ø¬Ø³Ø± Ù„Ù„Ø¨Ù„Ø§ØºØ§Øª Ø¨Ø¹Ø¯ Ø£ÙˆÙ„ Ø±Ø¯
    if src == "report" and _open_report_session:
        try: _open_report_session(uid, admin_id=m.from_user.id)
        except Exception: pass
    mark_replied(uid, src)
    lang = get_user_lang(m.from_user.id) or "en"
    await m.reply(_tf(lang,"inbox.sent_ok","ØªÙ… Ø§Ù„Ø¥Ø±Ø³Ø§Ù„ âœ…"))

# ====== ØªØ®Ø·ÙŠ/Ø¥ØºÙ„Ø§Ù‚ ======
@router.callback_query(F.data.startswith("sin:skip:"))
async def cb_skip(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src, uid = cb.data.split(":"); uid = int(uid)
    release(uid, src)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(_tf(lang,"inbox.skipped","ØªÙ…Øª Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„Ø¹Ù†ØµØ± Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø±."), reply_markup=_home_kb(lang))
    await cb.answer()

@router.callback_query(F.data.startswith("sin:close:"))
async def cb_close(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src, uid = cb.data.split(":"); uid = int(uid)
    close(uid, src)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(_tf(lang,"inbox.closed","ØªÙ… Ø¥ØºÙ„Ø§Ù‚ Ø§Ù„ØªØ°ÙƒØ±Ø© ÙˆØ¥Ø²Ø§Ù„ØªÙ‡Ø§."), reply_markup=_home_kb(lang))
    await cb.answer()

