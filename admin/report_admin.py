# admin/report_admin.py
from __future__ import annotations

import os, json, logging
from pathlib import Path

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from lang import t, get_user_lang

"""
لوحة إدارة البلاغات:
- تمكين/تعطيل البلاغات
- ضبط مدة التبريد (أيام)
- حظر/فكّ حظر مستخدمين
- عرض/تفريغ قائمة المحظورين

الزر الأساسي في لوحة الأدمن: callback_data="ra:open"
"""

router = Router(name="report_admin")
log = logging.getLogger(__name__)

# ====== ملفات التخزين ======
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "report_settings.json"

DEFAULTS = {"enabled": True, "cooldown_days": 3, "banned": []}

# ====== صلاحيات الأدمن ======
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def L(uid: int) -> str:
    return get_user_lang(uid) or "en"

# ====== ترجمة مع fallback ======
def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = t(lang, key)
    except Exception:
        s = None
    return fallback if not s or s == key else s

# ====== I/O ======
def _load() -> dict:
    try:
        if SETTINGS_FILE.exists():
            with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                d = json.load(f)
        else:
            d = DEFAULTS.copy()
    except Exception as e:
        log.error(f"[report_admin] load error: {e}")
        d = DEFAULTS.copy()

    # sanity
    d.setdefault("enabled", True)
    d.setdefault("cooldown_days", 3)
    d.setdefault("banned", [])
    if not isinstance(d["banned"], list):
        d["banned"] = []
    return d

def _save(d: dict):
    try:
        with SETTINGS_FILE.open("w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[report_admin] save error: {e}")

async def _safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

# ====== الواجهة ======
def _panel_text(lang: str) -> str:
    st = _load()
    status = _tf(lang, "ra.enabled_on", "مُفعّل") if st["enabled"] else _tf(lang, "ra.enabled_off", "مُعطّل")
    return (
        f"🛠 <b>{_tf(lang, 'ra.title', 'إدارة البلاغات')}</b>\n\n"
        f"• {_tf(lang,'ra.status','الحالة')}: <b>{status}</b>\n"
        f"• {_tf(lang,'ra.cooldown_days','مدة التبريد (أيام)')}: <code>{st['cooldown_days']}</code>\n"
        f"• {_tf(lang,'ra.banned_count','عدد المحظورين')}: <code>{len(st['banned'])}</code>\n"
    )

def _panel_kb(lang: str) -> InlineKeyboardMarkup:
    st = _load()
    toggle_txt = ("🟢 " + _tf(lang, "ra.btn_disable", "إيقاف البلاغات")) if st["enabled"] \
                 else ("🔴 " + _tf(lang, "ra.btn_enable", "تشغيل البلاغات"))
    rows = [
        [
            InlineKeyboardButton(text=toggle_txt,                              callback_data="ra:toggle"),
            InlineKeyboardButton(text="⏱ " + _tf(lang,"ra.btn_cooldown","تغيير التبريد"), callback_data="ra:cooldown"),
        ],
        [
            InlineKeyboardButton(text="🚫 " + _tf(lang,"ra.btn_ban","حظر مستخدم"),    callback_data="ra:ban"),
            InlineKeyboardButton(text="♻️ " + _tf(lang,"ra.btn_unban","رفع الحظر"),   callback_data="ra:unban"),
        ],
        [InlineKeyboardButton(text="📋 " + _tf(lang,"ra.btn_banned_list","قائمة المحظورين"), callback_data="ra:banned")],
        [InlineKeyboardButton(text="🔄 " + _tf(lang,"ra.btn_refresh","تحديث اللوحة"), callback_data="ra:refresh")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"ra.btn_back","رجوع"), callback_data="ah:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ====== حالات الإدخال ======
class RAStates(StatesGroup):
    waiting_userid_ban = State()
    waiting_userid_unban = State()
    waiting_cooldown = State()

# ====== فتح اللوحة ======
@router.callback_query(F.data == "ra:open")
async def ra_open(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang))
    await cb.answer()

@router.callback_query(F.data == "ra:refresh")
async def ra_refresh(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang))
    await cb.answer("✅")

# ====== تمكين/تعطيل ======
@router.callback_query(F.data == "ra:toggle")
async def ra_toggle(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    st = _load()
    st["enabled"] = not st.get("enabled", True)
    _save(st)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang))
    await cb.answer("✅")

# ====== قائمة المحظورين ======
@router.callback_query(F.data == "ra:banned")
async def ra_banned(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    st = _load()
    ids = st.get("banned", [])
    if not ids:
        await cb.message.answer(_tf(lang, "ra.no_banned", "لا يوجد مستخدمون محظورون."))
        return await cb.answer()

    head = "📋 " + _tf(lang, "ra.banned_list_title", "قائمة المحظورين")
    body = "\n".join(f"• <code>{uid}</code>" for uid in ids[:50])
    if len(ids) > 50:
        body += f"\n… (+{len(ids)-50})"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 " + _tf(lang,"ra.btn_unban_all","رفع الحظر عن الجميع"), callback_data="ra:unban_all")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"ra.btn_back","رجوع"), callback_data="ra:open")],
    ])
    await cb.message.answer(f"{head}\n\n{body}", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "ra:unban_all")
async def ra_unban_all(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    st = _load()
    st["banned"] = []
    _save(st)
    await cb.answer(_tf(lang, "ra.saved", "تم الحفظ ✅"), show_alert=True)

# ====== حظر ======
@router.callback_query(F.data == "ra:ban")
async def ra_ban_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(RAStates.waiting_userid_ban)
    await cb.message.answer(_tf(lang, "ra.ask_user_id_ban", "أرسل رقم معرف المستخدم (ID) لحظره:"))
    await cb.answer()

# قبول أرقام فقط داخل الحالة
@router.message(StateFilter(RAStates.waiting_userid_ban), F.text.regexp(r"^\d{3,15}$"))
async def ra_ban_save_ok(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = int(m.text.strip())
    st = _load()
    if uid not in st["banned"]:
        st["banned"].append(uid)
        _save(st)
    await state.clear()
    await m.reply(_tf(lang, "ra.saved", "تم الحفظ ✅"))

# أي شيء آخر داخل الحالة (غير رقم) → رسالة خطأ
@router.message(StateFilter(RAStates.waiting_userid_ban))
async def ra_ban_save_invalid(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    await m.reply(_tf(lang, "ra.invalid_user_id", "المعرّف غير صالح، أرسل رقمًا فقط."))

# ====== رفع الحظر ======
@router.callback_query(F.data == "ra:unban")
async def ra_unban_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(RAStates.waiting_userid_unban)
    await cb.message.answer(_tf(lang, "ra.ask_user_id_unban", "أرسل رقم معرف المستخدم (ID) لرفع الحظر:"))
    await cb.answer()

@router.message(StateFilter(RAStates.waiting_userid_unban), F.text.regexp(r"^\d{3,15}$"))
async def ra_unban_save_ok(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = int(m.text.strip())
    st = _load()
    st["banned"] = [x for x in st["banned"] if x != uid]
    _save(st)
    await state.clear()
    await m.reply(_tf(lang, "ra.saved", "تم الحفظ ✅"))

@router.message(StateFilter(RAStates.waiting_userid_unban))
async def ra_unban_save_invalid(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    await m.reply(_tf(lang, "ra.invalid_user_id", "المعرّف غير صالح، أرسل رقمًا فقط."))

# ====== تغيير مدة التبريد ======
@router.callback_query(F.data == "ra:cooldown")
async def ra_cooldown_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(RAStates.waiting_cooldown)
    await cb.message.answer(_tf(lang, "ra.ask_cooldown_days", "أرسل عدد الأيام للتبريد (0 لإلغاء التبريد):"))
    await cb.answer()

@router.message(StateFilter(RAStates.waiting_cooldown), F.text.regexp(r"^\d{1,3}$"))
async def ra_cooldown_save_ok(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    days = int(m.text.strip())
    if days < 0 or days > 365:
        return await m.reply(_tf(lang, "ra.invalid_number", "رقم غير صالح. أدخل 0 - 365."))
    st = _load()
    st["cooldown_days"] = days
    _save(st)
    await state.clear()
    await m.reply(_tf(lang, "ra.saved", "تم الحفظ ✅"))

@router.message(StateFilter(RAStates.waiting_cooldown))
async def ra_cooldown_save_invalid(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    await m.reply(_tf(lang, "ra.invalid_number", "رقم غير صالح. أدخل 0 - 365."))

# ====== خروج بالأوامر أثناء أي حالة (يدعم /start) ======
@router.message(StateFilter(RAStates.waiting_userid_ban), F.text.regexp(r"^/"))
@router.message(StateFilter(RAStates.waiting_userid_unban), F.text.regexp(r"^/"))
@router.message(StateFilter(RAStates.waiting_cooldown), F.text.regexp(r"^/"))
async def ra_any_state_command_exit(m: Message, state: FSMContext):
    await state.clear()
    try:
        # استدعاء شاشة البداية مباشرة إن توفرت
        from handlers.start import start_handler
        await start_handler(m, state)
    except Exception:
        await m.reply("تم الإلغاء والعودة للصفحة الرئيسية ✅ /start")
