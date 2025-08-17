from __future__ import annotations
import os, json, logging
from pathlib import Path
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from lang import t, get_user_lang

router = Router(name="report_inbox")

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
THREADS_FILE = DATA_DIR / "report_threads.json"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _now_iso():
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()

def _load() -> dict:
    try:
        if THREADS_FILE.exists():
            d = json.loads(THREADS_FILE.read_text(encoding="utf-8"))
        else:
            d = {"threads": {}}
        d.setdefault("threads", {})
        return d
    except Exception as e:
        logging.error(f"[rin] load error: {e}")
        return {"threads": {}}

def _save(d: dict):
    THREADS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

# public helper يستدعيه report.py
def _touch_thread(user_id: int, user_name: str | None = None, last_text: str | None = None):
    d = _load()
    th = d["threads"].setdefault(str(user_id), {
        "user_id": user_id,
        "user_name": user_name or "",
        "status": "open",
        "last_text": "",
        "updated_at": _now_iso(),
    })
    if user_name:
        th["user_name"] = user_name
    if last_text:
        th["last_text"] = last_text
    th["updated_at"] = _now_iso()
    _save(d)

async def _safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

def _title(lang: str) -> str:
    return "📥 " + t(lang, "rin.title")

def _kb_list(lang: str) -> InlineKeyboardMarkup:
    d = _load()
    items = list(d["threads"].values())
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    kb = InlineKeyboardBuilder()
    if not items:
        kb.button(text=t(lang, "rin.empty"), callback_data="rin:nop")
    else:
        for th in items[:25]:
            uid = th.get("user_id")
            name = th.get("user_name") or f"#{uid}"
            status = th.get("status", "open")
            mark = "🟢" if status == "open" else "⚪️"
            kb.button(text=f"{mark} {name}", callback_data=f"rin:chat:{uid}")
    kb.adjust(1)
    kb.button(text="🔄 " + t(lang, "rin.refresh"), callback_data="rin:open")
    kb.button(text="⬅️ " + t(lang, "rin.back"), callback_data="ah:menu")
    kb.adjust(1)
    return kb.as_markup()

def _chat_text(lang: str, th: dict) -> str:
    uid = th.get("user_id")
    name = th.get("user_name") or f"#{uid}"
    status = th.get("status", "open")
    st_txt = t(lang, "rin.st_open") if status == "open" else t(lang, "rin.st_closed")
    last = th.get("last_text") or "-"
    upd = th.get("updated_at") or "-"
    return (
        f"👤 <b>{name}</b> (<code>{uid}</code>)\n"
        f"{t(lang, 'rin.status')}: <b>{st_txt}</b>\n"
        f"{t(lang, 'rin.last')}: <i>{last}</i>\n"
        f"{t(lang, 'rin.updated')}: <code>{upd}</code>"
    )

def _kb_chat(lang: str, th: dict) -> InlineKeyboardMarkup:
    uid = th.get("user_id")
    status = th.get("status", "open")
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 " + t(lang, "rin.reply"), callback_data=f"rin:reply:{uid}")
    if status == "open":
        kb.button(text="✅ " + t(lang, "rin.close"), callback_data=f"rin:close:{uid}")
    else:
        kb.button(text="♻️ " + t(lang, "rin.reopen"), callback_data=f"rin:reopen:{uid}")
    kb.button(text="⬅️ " + t(lang, "rin.back_list"), callback_data="rin:open")
    kb.adjust(2)
    return kb.as_markup()

class RinStates(StatesGroup):
    waiting_reply = State()

# ===== فتح قائمة الوارد =====
@router.callback_query(F.data == "rin:open")
async def rin_open(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    await _safe_edit(cb.message, _title(lang), _kb_list(lang))
    await cb.answer()

# ===== فتح محادثة =====
@router.callback_query(F.data.startswith("rin:chat:"))
async def rin_chat(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    d = _load()
    th = d["threads"].get(str(uid))
    if not th:
        return await cb.answer(t(lang, "rin.thread_missing"), show_alert=True)
    await _safe_edit(cb.message, _chat_text(lang, th), _kb_chat(lang, th))
    await cb.answer()

# ===== بدء الرد =====
@router.callback_query(F.data.startswith("rin:reply:"))
async def rin_reply_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    await state.update_data(reply_to=uid)
    await state.set_state(RinStates.waiting_reply)
    await cb.message.answer(t(lang, "rin.ask_reply"))
    await cb.answer()

# ===== استلام الرد وإرساله للمستخدم =====
@router.message(RinStates.waiting_reply)
async def rin_reply_send(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(t(lang, "admins_only"))
    st = await state.get_data()
    uid = st.get("reply_to")
    if not uid:
        return await m.reply(t(lang, "rin.thread_missing"))

    # ارسل الرسالة كما هي (تحفظ الميديا)
    try:
        await m.copy_to(chat_id=uid)
        # حدِّث الخيط
        d = _load()
        th = d["threads"].setdefault(str(uid), {"user_id": uid, "user_name": "", "status": "open"})
        content = (m.caption if (getattr(m, "caption", None)) else (m.text or "(media)"))
        th["last_text"] = content
        th["updated_at"] = _now_iso()
        _save(d)
        await m.reply(t(lang, "rin.sent_ok"))
    except Exception as e:
        logging.error(f"[rin] send to {uid} failed: {e}")
        await m.reply(t(lang, "rin.send_fail"))
    finally:
        await state.clear()

# ===== إغلاق / إعادة فتح =====
@router.callback_query(F.data.startswith("rin:close:"))
async def rin_close(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    d = _load()
    th = d["threads"].get(str(uid))
    if not th:
        return await cb.answer(t(lang, "rin.thread_missing"), show_alert=True)
    th["status"] = "closed"
    th["updated_at"] = _now_iso()
    _save(d)
    await _safe_edit(cb.message, _chat_text(lang, th), _kb_chat(lang, th))
    await cb.answer("✅")

@router.callback_query(F.data.startswith("rin:reopen:"))
async def rin_reopen(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    d = _load()
    th = d["threads"].get(str(uid))
    if not th:
        return await cb.answer(t(lang, "rin.thread_missing"), show_alert=True)
    th["status"] = "open"
    th["updated_at"] = _now_iso()
    _save(d)
    await _safe_edit(cb.message, _chat_text(lang, th), _kb_chat(lang, th))
    await cb.answer("✅")

@router.callback_query(F.data == "rin:nop")
async def rin_nop(cb: CallbackQuery):
    await cb.answer()
