# handlers/support_inbox_admin.py
from __future__ import annotations
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
# دمج الجسر للبلاغات عند الردّ:
try:
    from handlers.report import set_thread_open as _open_report_session  # سيُعرّف لديك
except Exception:
    _open_report_session = None

router = Router(name="support_inbox_admin")

ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID","")).split(",") if x.strip().isdigit()]
def _is_admin(uid: int) -> bool: return (int(uid) in ADMIN_IDS)

def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = _t(lang, key)
        return fallback if not s or s == key else s
    except Exception:
        return fallback

# ====== شاشة رئيسية ======
def _home_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 " + _tf(lang,"inbox.next_report","التالي (بلاغ)"),
                              callback_data="sin:next:report"),
         InlineKeyboardButton(text="💬 " + _tf(lang,"inbox.next_chat","التالي (دردشة)"),
                              callback_data="sin:next:chat")],
        [InlineKeyboardButton(text="📥 " + _tf(lang,"inbox.list_reports","قائمة الانتظار (بلاغ)"),
                              callback_data="sin:list:report"),
         InlineKeyboardButton(text="📥 " + _tf(lang,"inbox.list_chats","قائمة الانتظار (دردشة)"),
                              callback_data="sin:list:chat")],
        [InlineKeyboardButton(text="🔄 " + _tf(lang,"inbox.refresh","تحديث"), callback_data="sin:home")]
    ])

async def _render_home(msg_or_cb, lang: str):
    c = get_counts()
    text = (
        "📬 <b>Support Inbox</b>\n"
        f"• Reports — waiting: <b>{c['report']['waiting']}</b>, assigned: <b>{c['report']['assigned']}</b>, total: {c['report']['total']}\n"
        f"• Live chat — waiting: <b>{c['chat']['waiting']}</b>, assigned: <b>{c['chat']['assigned']}</b>, total: {c['chat']['total']}\n"
        "\n" + _tf(lang,"inbox.help","اختر “التالي” لفتح أول تذكرة بانتظارك.")
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

# ====== فتح التالي ======
def _ticket_kb(uid: int, src: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ " + _tf(lang,"inbox.reply","ردّ"), callback_data=f"sin:reply:{src}:{uid}")],
        [InlineKeyboardButton(text="⏭️ " + _tf(lang,"inbox.skip","تخطي"), callback_data=f"sin:skip:{src}:{uid}"),
         InlineKeyboardButton(text="✅ " + _tf(lang,"inbox.close","إغلاق"), callback_data=f"sin:close:{src}:{uid}")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"inbox.back","رجوع"), callback_data="sin:home")]
    ])

async def _open_next(cb: CallbackQuery, src: str):
    lang = get_user_lang(cb.from_user.id) or "en"
    rec = claim_next(cb.from_user.id, src)
    if not rec:
        return await cb.answer(_tf(lang,"inbox.empty","لا توجد عناصر بانتظارك"), show_alert=True)
    uid = rec["uid"]
    text = (f"👤 <b>UID</b>: <code>{uid}</code>\n"
            f"• Source: <b>{src}</b>\n"
            f"• New msgs: <b>{rec.get('count',0)}</b>\n"
            f"• Preview: {rec.get('preview','-')}")
    await cb.message.edit_text(text, reply_markup=_ticket_kb(uid, src, lang))
    await cb.answer()

@router.callback_query(F.data.in_(["sin:next:report","sin:next:chat"]))
async def next_any(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src = cb.data.split(":")
    await _open_next(cb, src)

# ====== قائمة الانتظار المختصرة ======
@router.callback_query(F.data.in_(["sin:list:report","sin:list:chat"]))
async def list_wait(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src = cb.data.split(":")
    lang = get_user_lang(cb.from_user.id) or "en"
    total, items = list_waiting(src, limit=10, offset=0)
    if not items:
        return await cb.answer(_tf(lang,"inbox.empty","لا توجد عناصر بانتظارك"), show_alert=True)
    lines = [f"📥 <b>{src} — waiting {total}</b>"]
    for it in items:
        lines.append(f"• <code>{it['uid']}</code> · {it.get('count',0)} · {it.get('preview','-')[:40]}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_home_kb(lang))
    await cb.answer()

# ====== الردّ ======
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
    await cb.message.answer(_tf(lang,"inbox.reply_prompt","أرسل الرسالة التي تريد إرسالها للمستخدم (نص/ميديا)."))

@router.message(InboxState.waiting_reply)
async def do_reply(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id): return
    data = await state.get_data(); await state.clear()
    uid, src = int(data["uid"]), data["src"]
    # أرسل النسخة للمستخدم
    try:
        await m.copy_to(chat_id=uid)
    except Exception:
        await m.bot.send_message(uid, (m.text or ""))
    # افتح الجسر للبلاغات بعد أول رد
    if src == "report" and _open_report_session:
        try: _open_report_session(uid, admin_id=m.from_user.id)
        except Exception: pass
    mark_replied(uid, src)
    lang = get_user_lang(m.from_user.id) or "en"
    await m.reply(_tf(lang,"inbox.sent_ok","تم الإرسال ✅"))

# ====== تخطي/إغلاق ======
@router.callback_query(F.data.startswith("sin:skip:"))
async def cb_skip(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src, uid = cb.data.split(":"); uid = int(uid)
    release(uid, src)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(_tf(lang,"inbox.skipped","تمت إعادة العنصر لقائمة الانتظار."), reply_markup=_home_kb(lang))
    await cb.answer()

@router.callback_query(F.data.startswith("sin:close:"))
async def cb_close(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): return await cb.answer()
    _, _, src, uid = cb.data.split(":"); uid = int(uid)
    close(uid, src)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(_tf(lang,"inbox.closed","تم إغلاق التذكرة وإزالتها."), reply_markup=_home_kb(lang))
    await cb.answer()
