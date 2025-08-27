# admin/report_admin.py
from __future__ import annotations

import os, json, logging, time
from pathlib import Path

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from lang import t, get_user_lang
import time
from aiogram.utils.keyboard import InlineKeyboardBuilder


"""
لوحة إدارة البلاغات:
- تمكين/تعطيل البلاغات
- ضبط مدة التبريد (أيام)
- حظر/فكّ حظر (مؤقّت/دائم) + عرض القوائم (متكاملة مع handlers/report.py)
- مسح التبريد لمستخدم معيّن
"""

router = Router(name="report_admin")
log = logging.getLogger(__name__)

# ====== ملفات التخزين ======
DATA_DIR       = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE  = DATA_DIR / "report_settings.json"    # القديمة (تتضمن banned[])
BLOCKLIST_FILE = DATA_DIR / "report_blocklist.json"   # الجديدة للحظر المؤقّت/الدائم
STATE_FILE     = DATA_DIR / "report_users.json"       # تبريد المستخدمين {"last": {uid: iso}}

DEFAULTS = {"enabled": True, "cooldown_days": 3, "banned": []}

# ====== صلاحيات الأدمن ======
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()] or [7360982123]

def is_admin(uid: int) -> bool: return uid in ADMIN_IDS
def L(uid: int) -> str: return get_user_lang(uid) or "en"

# ====== ترجمة مع fallback ======
def _tf(lang: str, key: str, fallback: str) -> str:
    try: s = t(lang, key)
    except Exception: s = None
    return fallback if not s or s == key else s

# ====== I/O ======
def _load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"[report_admin] load {p} error: {e}")
    return json.loads(json.dumps(default))

def _save_json(p: Path, data):
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error(f"[report_admin] save {p} error: {e}")

def _build_banned_text_and_kb(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    st = _load_settings()
    legacy_ids = [int(x) for x in st.get("banned", []) if str(x).isdigit()]
    bl = _bl_read()

    lines = []
    uids: set[int] = set()

    if legacy_ids:
        lines.append("• <b>Legacy</b>:")
        for uid in legacy_ids:
            lines.append(f"  - <code>{uid}</code>")
            uids.add(uid)

    if bl:
        lines.append("• <b>Blocklist</b>:")
        now = time.time()
        for k, rec in bl.items():
            try:
                uid = int(k)
            except Exception:
                continue
            uids.add(uid)
            if rec is True:
                tag = "perm"
            else:
                until = float(rec.get("until", 0))
                tag = "expired" if until and now >= until else "temp"
            lines.append(f"  - <code>{uid}</code> ({tag})")

    if not lines:
        text = _tf(lang, "ra.no_banned", "لا يوجد مستخدمون محظورون.")
        kb_b = InlineKeyboardBuilder()
        kb_b.button(text=_tf(lang, "ra.btn_back", "رجوع"), callback_data="ra:open")
        return text, kb_b.as_markup()

    header = "📋 " + _tf(lang, "ra.banned_list_title", "قائمة المستخدمين المحظورين")
    text = header + "\n\n" + "\n".join(lines)

    kb_b = InlineKeyboardBuilder()
    # أزرار رفع الحظر فردياً (حتى 25 زرًا لتفادي التضخّم)
    for uid in sorted(uids)[:25]:
        kb_b.button(text=f"✅ Unban {uid}", callback_data=f"ra:unban_one:{uid}")
    kb_b.adjust(2)
    kb_b.row(InlineKeyboardButton(text="🧹 " + _tf(lang, "ra.btn_unban_all", "رفع الحظر عن الكل"), callback_data="ra:unban_all"))
    kb_b.row(InlineKeyboardButton(text="⬅️ " + _tf(lang, "ra.btn_back", "رجوع"), callback_data="ra:open"))
    return text, kb_b.as_markup()

# إعدادات قديمة
def _load_settings() -> dict:
    d = _load_json(SETTINGS_FILE, DEFAULTS.copy())
    d.setdefault("enabled", True)
    d.setdefault("cooldown_days", 3)
    d.setdefault("banned", [])
    if not isinstance(d["banned"], list): d["banned"] = []
    return d
def _save_settings(d: dict): _save_json(SETTINGS_FILE, d)

# بلوك ليست جديدة
def _bl_read() -> dict:  return _load_json(BLOCKLIST_FILE, {})
def _bl_write(d: dict):  _save_json(BLOCKLIST_FILE, d)
def _bl_unban(uid: int):
    d = _bl_read(); d.pop(str(uid), None); _bl_write(d)

# تبريد المستخدمين
def _state_read() -> dict: return _load_json(STATE_FILE, {"last": {}})
def _state_write(d: dict): _save_json(STATE_FILE, d)
def _cooldown_clear(uid: int):
    st = _state_read(); st.setdefault("last", {}).pop(str(uid), None); _state_write(st)

def _blocked_count() -> int:
    st = _load_settings()
    legacy = set(int(x) for x in st.get("banned", []) if str(x).isdigit())
    bl = _bl_read()
    return len(legacy) + len(bl.keys())

def _human_left(until_ts: float) -> str:
    rem = int(until_ts - time.time())
    if rem <= 0: return "expired"
    d, r = divmod(rem, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) if parts else f"{rem}s"

# ====== عرض اللوحة ======
async def _safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

def _panel_text(lang: str) -> str:
    st = _load_settings()
    status = _tf(lang, "ra.enabled_on", "مُفعّل") if st["enabled"] else _tf(lang, "ra.enabled_off", "مُعطّل")
    return (
        f"🛠 <b>{_tf(lang, 'ra.title', 'إدارة البلاغات')}</b>\n\n"
        f"• {_tf(lang,'ra.status','الحالة')}: <b>{status}</b>\n"
        f"• {_tf(lang,'ra.cooldown_days','مدة التبريد (أيام)')}: <code>{st['cooldown_days']}</code>\n"
        f"• {_tf(lang,'ra.banned_count','عدد المحظورين')}: <code>{_blocked_count()}</code>\n"
        f"<i>القائمة القديمة (banned[]) ما تزال مدعومة، لكن يُفضل الحظر من الأزرار/الأوامر الجديدة.</i>"
    )

def _panel_kb(lang: str) -> InlineKeyboardMarkup:
    st = _load_settings()
    toggle_txt = ("🟢 " + _tf(lang, "ra.btn_disable", "إيقاف البلاغات")) if st["enabled"] \
                 else ("🔴 " + _tf(lang, "ra.btn_enable", "تشغيل البلاغات"))
    rows = [
        [
            InlineKeyboardButton(text=toggle_txt, callback_data="ra:toggle"),
            InlineKeyboardButton(text="⏱ " + _tf(lang,"ra.btn_cooldown","تغيير التبريد"), callback_data="ra:cooldown"),
        ],
        [
            InlineKeyboardButton(text="🚫 " + _tf(lang,"ra.btn_ban","حظر (uid ساعات|perm)"), callback_data="ra:ban"),
            InlineKeyboardButton(text="♻️ " + _tf(lang,"ra.btn_unban","رفع الحظر"), callback_data="ra:unban"),
        ],
        [InlineKeyboardButton(text="🧽 " + _tf(lang,"ra.btn_clearcd","مسح تبريد مستخدم"), callback_data="ra:clearcd")],
        [InlineKeyboardButton(text="📋 " + _tf(lang,"ra.btn_banned_list","قائمة المحظورين"), callback_data="ra:banned")],
        [InlineKeyboardButton(text="🔄 " + _tf(lang,"ra.btn_refresh","تحديث اللوحة"), callback_data="ra:refresh")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"ra.btn_back","رجوع"), callback_data="ah:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ====== حالات الإدخال ======
class RAStates(StatesGroup):
    waiting_ban = State()         # "<uid> <hours|perm>"
    waiting_unban = State()       # "<uid>"
    waiting_cooldown = State()
    waiting_clearcd = State()     # "<uid>"

# ====== فتح/تحديث اللوحة ======
@router.callback_query(F.data == "ra:open")
async def ra_open(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang)); await cb.answer()

@router.callback_query(F.data == "ra:refresh")
async def ra_refresh(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang)); await cb.answer("✅")

# ====== تمكين/تعطيل ======
@router.callback_query(F.data == "ra:toggle")
async def ra_toggle(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    st = _load_settings(); st["enabled"] = not st.get("enabled", True); _save_settings(st)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang)); await cb.answer("✅")

# ====== قائمة المحظورين (قديمة + جديدة) ======
@router.callback_query(F.data == "ra:banned")
async def ra_banned(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)

    text, kb = _build_banned_text_and_kb(lang)
    await _safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(F.data == "ra:unban_all")
async def ra_unban_all(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)

    _bl_write({})  # الجديدة
    st = _load_settings()
    st["banned"] = []  # القديمة
    _save_settings(st)

    # حدّث العرض
    text, kb = _build_banned_text_and_kb(lang)
    await _safe_edit(cb.message, text, kb)
    await cb.answer(_tf(lang, "ra.saved", "تم الحفظ ✅"), show_alert=True)


@router.callback_query(F.data.startswith("ra:unban_one:"))
async def ra_unban_one(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)

    try:
        uid = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer()

    # احذف من القائمتين
    _bl_unban(uid)
    st = _load_settings()
    st["banned"] = [x for x in st["banned"] if int(x) != uid]
    _save_settings(st)

    # أعِد رسم الشاشة برسالة محدثة
    text, kb = _build_banned_text_and_kb(lang)
    await _safe_edit(cb.message, text, kb)
    await cb.answer(_tf(lang, "ra.saved", "تم الحفظ ✅"), show_alert=True)


# ====== الحظر/فك الحظر ======
@router.callback_query(F.data == "ra:ban")
async def ra_ban_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(RAStates.waiting_ban)
    await cb.message.answer(
        _tf(lang, "ra.ask_ban", "أرسل: <code>UID ساعات</code> أو <code>UID perm</code>.\nمثال: <code>123456 24</code>"),
        parse_mode="HTML"
    )
    await cb.answer()

@router.message(StateFilter(RAStates.waiting_ban))
async def ra_ban_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))

    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[0].isdigit():
        return await m.reply(_tf(lang, "ra.bad_format", "صيغة غير صحيحة. مثال: 123456 24 أو 123456 perm"))
    uid = int(parts[0]); dur = parts[1].lower()

    if dur == "perm":
        bl = _bl_read(); bl[str(uid)] = True; _bl_write(bl)
        st = _load_settings(); st["banned"] = [x for x in st["banned"] if int(x) != uid]; _save_settings(st)
        await state.clear()
        return await m.reply(f"🚫 تم حظر <code>{uid}</code> دائمًا.", parse_mode="HTML")

    try:
        hours = max(1, int(dur))
    except Exception:
        return await m.reply(_tf(lang, "ra.invalid_number", "قيمة عدد الساعات غير صالحة."))

    until_ts = time.time() + hours * 3600
    bl = _bl_read(); bl[str(uid)] = {"until": until_ts}; _bl_write(bl)
    st = _load_settings(); st["banned"] = [x for x in st["banned"] if int(x) != uid]; _save_settings(st)
    await state.clear()
    await m.reply(f"🚫 تم حظر <code>{uid}</code> لمدة <b>{hours}</b> ساعة.", parse_mode="HTML")

@router.callback_query(F.data == "ra:unban")
async def ra_unban_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(RAStates.waiting_unban)
    await cb.message.answer(_tf(lang, "ra.ask_user_id_unban", "أرسل رقم معرف المستخدم (UID) لرفع الحظر:"))
    await cb.answer()

@router.message(StateFilter(RAStates.waiting_unban), F.text.regexp(r"^\d{3,15}$"))
async def ra_unban_save_ok(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = int(m.text.strip())
    _bl_unban(uid)
    st = _load_settings(); st["banned"] = [x for x in st["banned"] if int(x) != uid]; _save_settings(st)
    await state.clear()
    await m.reply(_tf(lang, "ra.saved", "تم الحفظ ✅"))

@router.message(StateFilter(RAStates.waiting_unban))
async def ra_unban_save_invalid(m: Message, state: FSMContext):
    lang = L(m.from_user.id); await m.reply(_tf(lang, "ra.invalid_user_id", "المعرّف غير صالح، أرسل رقمًا فقط."))

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
    st = _load_settings(); st["cooldown_days"] = days; _save_settings(st)
    await state.clear(); await m.reply(_tf(lang, "ra.saved", "تم الحفظ ✅"))

@router.message(StateFilter(RAStates.waiting_cooldown))
async def ra_cooldown_save_invalid(m: Message, state: FSMContext):
    lang = L(m.from_user.id); await m.reply(_tf(lang, "ra.invalid_number", "رقم غير صالح. أدخل 0 - 365."))

# ====== مسح تبريد مستخدم ======
@router.callback_query(F.data == "ra:clearcd")
async def ra_clearcd_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(RAStates.waiting_clearcd)
    await cb.message.answer(_tf(lang, "ra.ask_clearcd", "أرسل UID لمسح التبريد له:"))
    await cb.answer()

@router.message(StateFilter(RAStates.waiting_clearcd), F.text.regexp(r"^\d{3,15}$"))
async def ra_clearcd_ok(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = int(m.text.strip()); _cooldown_clear(uid)
    await state.clear(); await m.reply(_tf(lang, "ra.saved", "تم الحفظ ✅"))

@router.message(StateFilter(RAStates.waiting_clearcd))
async def ra_clearcd_invalid(m: Message, state: FSMContext):
    lang = L(m.from_user.id); await m.reply(_tf(lang, "ra.invalid_user_id", "المعرّف غير صالح، أرسل رقمًا فقط."))

# ====== خروج بالأوامر أثناء أي حالة ======
@router.message(StateFilter(RAStates.waiting_ban), F.text.regexp(r"^/"))
@router.message(StateFilter(RAStates.waiting_unban), F.text.regexp(r"^/"))
@router.message(StateFilter(RAStates.waiting_cooldown), F.text.regexp(r"^/"))
@router.message(StateFilter(RAStates.waiting_clearcd), F.text.regexp(r"^/"))
async def ra_any_state_command_exit(m: Message, state: FSMContext):
    await state.clear()
    try:
        from handlers.start import start_handler
        await start_handler(m, state)
    except Exception:
        await m.reply("تم الإلغاء والعودة للصفحة الرئيسية ✅ /start")
