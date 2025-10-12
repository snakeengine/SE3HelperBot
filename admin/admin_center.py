# admin/admin_center.py
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Callable, Dict, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from lang import t, get_user_lang
from services import admin_roles

router = Router(name="admin_center")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

# ========== تخزين ==========
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
PREFS_FILE = DATA_DIR / "admin_center_prefs.json"

# مفاتيح افتراضية شائعة — تقدر تغيّرها وتضيف غيرها بأوامر النص
DEFAULT_KEYS = ["reports", "support", "sales", "vip", "security", "marketing", "ops"]
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

def _parse_int(raw: str) -> int:
    s = (raw or "").strip().translate(_AR_DIGITS)
    s = "".join(ch for ch in s if ch.isdigit())
    return int(s) if s else 0

def _load_prefs() -> dict:
    try:
        if PREFS_FILE.exists():
            d = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        else:
            d = {}
    except Exception:
        d = {}
    d.setdefault("targets", {})     # {key: user_id}
    d.setdefault("known_keys", list(DEFAULT_KEYS))
    return d

def _save_prefs(d: dict) -> None:
    tmp = PREFS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PREFS_FILE)

PREFS = _load_prefs()

# ========== i18n صغيرة ==========
def _tx(lang: str, key: str, ar_fallback: str, en_fallback: str) -> str:
    try:
        s = t(lang, key)
        if s and s != key:
            return s
    except Exception:
        pass
    return ar_fallback if lang.lower().startswith("ar") else en_fallback

# ========== صلاحية الأدمن ==========
async def _is_admin(uid: int) -> bool:
    ids = set(await admin_roles.get_admins("default")) | set(await admin_roles.get_admins("reports"))
    return int(uid) in ids

# ========== Registry للـ bindings ==========
# register_binding("reports", lambda user_id: setattr(report_mod, "ADMIN_ALERT_CHAT_ID", user_id))
_BINDINGS: Dict[str, Callable[[Optional[int]], None]] = {}

def register_binding(key: str, apply_fn: Callable[[Optional[int]], None]) -> None:
    """تسجيل ربط لميزة اسمها key. يتم تطبيق الهدف الحالي عليها فورًا (إن وُجد)."""
    _BINDINGS[key] = apply_fn
    try:
        curr = int(PREFS["targets"].get(key) or 0) or None
    except Exception:
        curr = None
    try:
        apply_fn(curr)
    except Exception:
        pass

def apply_target(key: str, user_id: Optional[int]) -> None:
    """تحديث الهدف وتطبيقه على الربطات المسجلة."""
    if user_id is not None and user_id <= 0:
        user_id = None
    PREFS["targets"][key] = user_id
    _save_prefs(PREFS)
    fn = _BINDINGS.get(key)
    if fn:
        try:
            fn(user_id)
        except Exception:
            pass

def current_target(key: str) -> Optional[int]:
    v = PREFS["targets"].get(key)
    try:
        return int(v) if v is not None else None
    except Exception:
        return None

def ensure_key(key: str) -> None:
    if key not in PREFS["known_keys"]:
        PREFS["known_keys"].append(key)
        _save_prefs(PREFS)

# ========== FSM ==========
class SetKeyState(StatesGroup):
    waiting_key = State()

class SetIdState(StatesGroup):
    waiting_id = State()

# ========== كيبورد ==========
def _kb_keys(lang: str) -> InlineKeyboardMarkup:
    rows = []
    keys = PREFS.get("known_keys", [])
    # نعرض كل مفتاح كزر يفتح لوحة ضبط الهدف للمفتاح المختار
    for k in keys:
        rows.append([InlineKeyboardButton(text=f"🔧 {k}", callback_data=f"ac:key:{k}")])
    # صف أخير لإضافة مفتاح جديد
    rows.append([InlineKeyboardButton(text=_tx(lang, "ac.add_key", "➕ إضافة مفتاح", "➕ Add key"),
                                      callback_data="ac:addkey")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _kb_target_controls(lang: str, key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_tx(lang,"ac.use_me","استخدام معرفي","Use my ID"),
                                 callback_data=f"ac:set:{key}:use_me"),
            InlineKeyboardButton(text=_tx(lang,"ac.use_reply","استخدام المُرَدّ عليه","Use replied"),
                                 callback_data=f"ac:set:{key}:use_reply"),
        ],
        [
            InlineKeyboardButton(text=_tx(lang,"ac.enter_id","إدخال ID يدوي","Enter ID manually"),
                                 callback_data=f"ac:set:{key}:enter"),
            InlineKeyboardButton(text=_tx(lang,"ac.clear","مسح الهدف","Clear target"),
                                 callback_data=f"ac:set:{key}:clear"),
        ],
        [
            InlineKeyboardButton(text=_tx(lang,"ac.back","⬅️ رجوع للمفاتيح","⬅️ Back to keys"),
                                 callback_data="ac:back")
        ]
    ])

@router.message(Command("adm_cancel"))
async def adm_cancel(m: Message, state: FSMContext):
    await state.clear()
    l = get_user_lang(m.from_user.id) or "ar"
    await m.reply("تم إلغاء العملية." if l.startswith("ar") else "Operation canceled.")

# ========== أوامر عامة ==========
@router.message(Command("adm_center"))
async def adm_center(m: Message):
    if not await _is_admin(m.from_user.id):
        l = get_user_lang(m.from_user.id) or "en"
        return await m.reply(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."))
    l = get_user_lang(m.from_user.id) or "ar"
    # قائمة المفاتيح
    await m.reply(_tx(l,"ac.header","⚙️ مركز الإدارة — اختر مفتاحًا لإسناد مستلم","⚙️ Admin Center — choose a key to assign a receiver"),
                  reply_markup=_kb_keys(l))

@router.callback_query(F.data == "ac:back")
async def ac_back(cb: CallbackQuery):
    if not await _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "ar"
    try:
        await cb.message.edit_text(_tx(l,"ac.header","⚙️ مركز الإدارة — اختر مفتاحًا لإسناد مستلم","⚙️ Admin Center — choose a key to assign a receiver"),
                                   reply_markup=_kb_keys(l))
    except Exception:
        await cb.message.answer(_tx(l,"ac.header","⚙️ مركز الإدارة — اختر مفتاحًا لإسناد مستلم","⚙️ Admin Center — choose a key to assign a receiver"),
                                reply_markup=_kb_keys(l))
    await cb.answer()

@router.callback_query(F.data == "ac:addkey")
async def ac_addkey(cb: CallbackQuery, state: FSMContext):
    if not await _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "ar"
    await state.set_state(SetKeyState.waiting_key)
    await cb.message.reply(_tx(l,"ac.ask_key","أرسل اسم المفتاح (أحرف/أرقام/شرطة سفلية).","Send the key name (letters/numbers/underscore)."))
    await cb.answer()

@router.message(SetKeyState.waiting_key)
async def ac_setkey(m: Message, state: FSMContext):
    if not await _is_admin(m.from_user.id):
        l = get_user_lang(m.from_user.id) or "en"
        return await m.reply(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."))
    key = (m.text or "").strip()
    l = get_user_lang(m.from_user.id) or "ar"
    if not key or len(key) > 40 or not all(ch.isalnum() or ch == "_" for ch in key):
        return await m.reply(_tx(l,"ac.bad_key","⚠️ مفتاح غير صالح. استخدم أحرف/أرقام/_.","⚠️ Invalid key. Use letters/numbers/_."))
    ensure_key(key)
    await state.clear()
    await m.reply(_tx(l,"ac.key_added",f"✅ تمت إضافة المفتاح: {key}","✅ Key added: {key}"))

@router.callback_query(F.data.startswith("ac:key:"))
async def ac_open_key(cb: CallbackQuery):
    if not await _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    key = cb.data.split(":")[2]
    l = get_user_lang(cb.from_user.id) or "ar"
    cur = current_target(key)
    head = _tx(l,"ac.key_header",
               f"🔑 المفتاح: <b>{key}</b>\nالمستلم الحالي: <code>{cur or '-'}</code>",
               f"🔑 Key: <b>{key}</b>\nCurrent receiver: <code>{cur or '-'}</code>")
    try:
        await cb.message.edit_text(head, reply_markup=_kb_target_controls(l, key))
    except Exception:
        await cb.message.answer(head, reply_markup=_kb_target_controls(l, key))
    await cb.answer()

# ضبط المستلم لمفتاح معيّن
@router.callback_query(F.data.startswith("ac:set:"))
async def ac_set_target(cb: CallbackQuery, state: FSMContext):
    if not await _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    _, _, key, action = cb.data.split(":")
    l = get_user_lang(cb.from_user.id) or "ar"

    if action == "use_me":
        apply_target(key, cb.from_user.id)
        return await cb.answer(_tx(l,"ac.saved","تم الحفظ ✅","Saved ✅"), show_alert=True)

    if action == "use_reply":
        # يجب الضغط كـ ردّ
        target_id = None
        try:
            if cb.message and cb.message.reply_to_message and cb.message.reply_to_message.from_user:
                target_id = cb.message.reply_to_message.from_user.id
        except Exception:
            target_id = None
        if not target_id:
            return await cb.answer(_tx(l,"ac.reply_hint","⤴️ استخدم الزر كـ رد على رسالة الشخص المستهدف.","⤴️ Use this button as a reply to the target user's message."),
                                   show_alert=True)
        apply_target(key, target_id)
        return await cb.answer(_tx(l,"ac.saved","تم الحفظ ✅","Saved ✅"), show_alert=True)

    if action == "enter":
        await state.set_state(SetIdState.waiting_id)
        await state.update_data(key=key)
        await cb.message.reply(_tx(l,"ac.ask_id","أرسل الـ ID الرقمي للمستلم:","Send the numeric user ID to receive:"))
        return await cb.answer()

    if action == "clear":
        apply_target(key, None)
        return await cb.answer(_tx(l,"ac.cleared","تم المسح ✅","Cleared ✅"), show_alert=True)

@router.message(SetIdState.waiting_id, Command("adm_cancel"))
async def ac_enter_id(m: Message, state: FSMContext):
    if not await _is_admin(m.from_user.id):
        l = get_user_lang(m.from_user.id) or "en"
        return await m.reply(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."))
    data = await state.get_data()
    key = data.get("key")
    l = get_user_lang(m.from_user.id) or "ar"
    raw = (m.text or "").strip()
    try:
        val = int(raw)
        if val <= 0:
            raise ValueError
    except Exception:
        return await m.reply(_tx(l,"ac.bad_id","⚠️ ID غير صالح. أرسل رقمًا صحيحًا.","⚠️ Invalid ID. Send a valid number."))
    apply_target(key, val)
    await state.clear()
    await m.reply(_tx(l,"ac.saved_full",f"تم ضبط مستلم '{key}' على: {val} ✅",f"Receiver for '{key}' set to: {val} ✅"))

# ========== أوامر نصية سريعة ==========
@router.message(Command("adm_set"))
async def cmd_adm_set(m: Message):
    """ /adm_set <key> <ID>  — يضيف المفتاح تلقائيًا لو غير موجود """
    if not await _is_admin(m.from_user.id):
        l = get_user_lang(m.from_user.id) or "en"
        return await m.reply(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."))
    parts = (m.text or "").split()
    if len(parts) < 3:
        return await m.reply("Usage: /adm_set <key> <ID>")
    key, raw = parts[1], parts[2]
    ensure_key(key)
    try:
        val = int(raw);  assert val > 0
    except Exception:
        return await m.reply("Bad ID.")
    apply_target(key, val)
    await m.reply(f"✅ {key} -> {val}")

@router.message(Command("adm_get"))
async def cmd_adm_get(m: Message):
    """ /adm_get [key] """
    if not await _is_admin(m.from_user.id):
        l = get_user_lang(m.from_user.id) or "en"
        return await m.reply(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."))
    parts = (m.text or "").split()
    if len(parts) >= 2:
        key = parts[1]
        val = current_target(key)
        return await m.reply(f"{key}: {val or '-'}")
    # بدون مفتاح: نعرض الكل
    lines = []
    for k in PREFS.get("known_keys", []):
        v = current_target(k)
        lines.append(f"{k}: {v or '-'}")
    await m.reply("\n".join(lines))

@router.message(Command("adm_keys"))
async def cmd_adm_keys(m: Message):
    """ /adm_keys — يعرض قائمة المفاتيح المعروفة """
    if not await _is_admin(m.from_user.id):
        l = get_user_lang(m.from_user.id) or "en"
        return await m.reply(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."))
    keys = PREFS.get("known_keys", [])
    await m.reply("Keys: " + ", ".join(keys))

# ======== ربط تلقائي لملف report (اختياري إن وُجد) ========
try:
    from handlers import report as report_mod
    def _apply_report(uid: Optional[int]) -> None:
        try:
            report_mod.ADMIN_ALERT_CHAT_ID = int(uid or 0)
        except Exception:
            report_mod.ADMIN_ALERT_CHAT_ID = 0
    register_binding("reports", _apply_report)
except Exception:
    # لو report غير موجود الآن، ممكن تسجّل الربط لاحقًا من أي مكان:
    #   from admin.admin_center import register_binding
    #   register_binding("reports", your_apply_fn)
    pass
