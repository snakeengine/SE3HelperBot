# handlers/server_status.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from pathlib import Path
from datetime import datetime, timezone
import json
import os

from lang import t, get_user_lang

router = Router()

# ===== إعدادات الأدمن =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def L(user_id: int) -> str:
    return get_user_lang(user_id) or "en"

# ===== المسارات والبيانات =====
DATA_DIR = Path("data")
STATUS_FILE = DATA_DIR / "server_status.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# حالة افتراضية
DEFAULT_STATUS = {
    "main": True,     # الخدمة الأساسية
    "conn": True,     # الاتصال / الشبكة
    "maint": False,   # وضع الصيانة
    "note": ""        # ملاحظة عامة
}

# زر الرجوع (من لوحة الأدمن نرجع للـ Admin Hub)
BACK_USER = "back_to_menu"
BACK_ADMIN = "ah:menu"

# ===== أدوات مساعدة =====
def load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def icon(ok: bool) -> str:
    return "✅" if ok else "❌"

def status_line(ok: bool, ok_txt: str, err_txt: str) -> str:
    return f"{icon(ok)} {ok_txt if ok else err_txt}"

# ===== edit آمن لتفادي message is not modified =====
async def safe_edit(message: Message, text: str, kb: InlineKeyboardMarkup):
    try:
        await message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

# ===== عرض المستخدم =====
def build_user_text(lang: str) -> str:
    st = load_json(STATUS_FILE, DEFAULT_STATUS)
    title = t(lang, "server_status_title")

    note = (st.get("note") or "").strip()
    if not note:
        note = t(lang, "server_no_note")

    lines = [
        f"<b>📊 {title}</b>",
        "",
        status_line(st.get("main", False), t(lang, "server_main_ok"), t(lang, "server_main_error")),
        status_line(st.get("conn", False), t(lang, "server_conn_ok"), t(lang, "server_conn_error")),
        "",
        f"📝 {t(lang, 'server_note')}: <i>{note}</i>",
        "",
        f"🔁 {t(lang, 'server_check_frequency')}",
        f"⏱️ {now_utc_str()}",
    ]
    if st.get("maint", False):
        lines.append("")
        lines.append(f"🛠️ {t(lang, 'maint_mode_active')}")
    return "\n".join(lines)

def build_user_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "refresh_btn"),  callback_data="server_status:refresh")],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_USER)],
    ])

# ===== لوحة الأدمن =====
def _mark(cur: bool, val: bool) -> str:
    return "●" if cur == val else "○"

def build_admin_text(lang: str) -> str:
    return "🛠 " + t(lang, "server_admin_title")

def build_admin_kb(lang: str) -> InlineKeyboardMarkup:
    st = load_json(STATUS_FILE, DEFAULT_STATUS)
    kb = InlineKeyboardBuilder()

    # تحديث
    kb.button(text="🔄 " + t(lang, "refresh_btn"), callback_data="server_status:adm_refresh")
    kb.adjust(1)

    # MAIN
    kb.button(text=f"{t(lang, 'server_admin_main')}: {icon(st.get('main', False))}", callback_data="server_status:nop")
    kb.adjust(1)
    kb.button(text=f"{_mark(st.get('main', False), True)} ON",  callback_data="server_status:adm:main:on")
    kb.button(text=f"{_mark(st.get('main', False), False)} OFF", callback_data="server_status:adm:main:off")
    kb.adjust(2)

    # CONN
    kb.button(text=f"{t(lang, 'server_admin_conn')}: {icon(st.get('conn', False))}", callback_data="server_status:nop")
    kb.adjust(1)
    kb.button(text=f"{_mark(st.get('conn', False), True)} ON",  callback_data="server_status:adm:conn:on")
    kb.button(text=f"{_mark(st.get('conn', False), False)} OFF", callback_data="server_status:adm:conn:off")
    kb.adjust(2)

    # MAINT
    kb.button(text=f"{t(lang, 'server_admin_maint')}: {icon(st.get('maint', False))}", callback_data="server_status:nop")
    kb.adjust(1)
    kb.button(text=f"{_mark(st.get('maint', False), True)} ON",  callback_data="server_status:adm:maint:on")
    kb.button(text=f"{_mark(st.get('maint', False), False)} OFF", callback_data="server_status:adm:maint:off")
    kb.adjust(2)

    # تعديل الملاحظة
    kb.button(text="✏️ " + t(lang, "server_admin_edit_note"), callback_data="server_status:adm_note")
    kb.adjust(1)

    # رجوع
    kb.button(text="⬅️ " + t(lang, "admin_hub_btn_close"), callback_data=BACK_ADMIN)
    kb.adjust(1)

    return kb.as_markup()

# ===== FSM لتعديل الملاحظة =====
class EditServerNote(StatesGroup):
    waiting_for_note = State()

# ===== هاندلرات العرض للمستخدم =====
@router.callback_query(F.data.in_({"server_status", "server_status:open"}))
async def open_server_status(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    await safe_edit(cb.message, build_user_text(lang), build_user_kb(lang))
    await cb.answer()

@router.callback_query(F.data == "server_status:refresh")
async def refresh_server_status(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    await safe_edit(cb.message, build_user_text(lang), build_user_kb(lang))
    await cb.answer("✅")

@router.message(Command("server_status"))
async def server_status_cmd(msg: Message):
    lang = L(msg.from_user.id)
    await msg.answer(build_user_text(lang), reply_markup=build_user_kb(lang), parse_mode="HTML", disable_web_page_preview=True)

# ===== هاندلرات لوحة الأدمن =====
@router.callback_query(F.data == "server_status:admin")
async def server_admin_open(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not _is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    await safe_edit(cb.message, build_admin_text(lang), build_admin_kb(lang))
    await cb.answer()

@router.callback_query(F.data == "server_status:adm_refresh")
async def server_admin_refresh(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not _is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    await safe_edit(cb.message, build_admin_text(lang), build_admin_kb(lang))
    await cb.answer("✅")

@router.callback_query(F.data.startswith("server_status:adm:"))
async def server_admin_toggle(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not _is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)

    # server_status:adm:<field>:<on|off>
    parts = cb.data.split(":")
    if len(parts) != 4:
        return await cb.answer()
    _, _, field, onoff = parts

    if field not in {"main", "conn", "maint"}:
        return await cb.answer()

    st = load_json(STATUS_FILE, DEFAULT_STATUS)
    st[field] = (onoff == "on")
    save_json(STATUS_FILE, st)

    await safe_edit(cb.message, build_admin_text(lang), build_admin_kb(lang))
    await cb.answer("✅")

@router.callback_query(F.data == "server_status:adm_note")
async def server_admin_note_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not _is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only"), show_alert=True)
    await state.set_state(EditServerNote.waiting_for_note)
    await cb.message.answer(t(lang, "server_admin_send_new_note"))  # أرسل الملاحظة الآن (أرسل '-' لمسحها)
    await cb.answer()

@router.message(EditServerNote.waiting_for_note)
async def server_admin_note_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not _is_admin(m.from_user.id):
        return await m.reply(t(lang, "admins_only"))
    text = (m.text or "").strip()
    st = load_json(STATUS_FILE, DEFAULT_STATUS)
    st["note"] = "" if text == "-" else text
    save_json(STATUS_FILE, st)
    await state.clear()
    await m.reply(t(lang, "server_admin_note_saved"))

@router.callback_query(F.data == "server_status:nop")
async def server_nop(cb: CallbackQuery):
    await cb.answer()
