# handlers_supplier.py
from __future__ import annotations

import os, json, time
from typing import Dict, Any, Optional, Tuple

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.enums import ParseMode
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang

# اختياري: عند القبول نضيفه لقائمة المورّدين العمومية utils/suppliers.py
try:
    from utils.suppliers import set_supplier, is_supplier
except Exception:
    def set_supplier(_uid: int, _value: bool = True):  # noqa
        return
    def is_supplier(_uid: int) -> bool:  # noqa
        return False

router = Router(name="supplier_apply")

# ========= الإعدادات / المسارات =========
DATA_DIR = "data"
APPS_FILE = os.path.join(DATA_DIR, "supplier_apps.json")   # تخزين الطلبات
os.makedirs(DATA_DIR, exist_ok=True)

# ADMIN IDS من البيئة (توافق مع باقي المشروع)
def _load_admin_ids() -> list[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    out: list[int] = []
    for p in str(raw).split(","):
        p = p.strip()
        if p.isdigit():
            out.append(int(p))
    return out or [7360982123]

ADMIN_IDS = _load_admin_ids()
AUDIT_CHAT_ID = None
try:
    _ac = os.getenv("AUDIT_CHAT_ID", "").strip()
    if _ac:
        AUDIT_CHAT_ID = int(_ac)
except Exception:
    AUDIT_CHAT_ID = None

# ========= أدوات I/O =========
def _safe_load() -> Dict[str, Any]:
    try:
        with open(APPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def _safe_save(d: Dict[str, Any]) -> None:
    tmp = APPS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, APPS_FILE)

def _upsert_application(user_id: int, lang: str, payload: Dict[str, Any]) -> None:
    db = _safe_load()
    db[str(user_id)] = {
        "user_id": user_id,
        "lang": lang,
        "data": payload,
        "status": "pending",
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }
    _safe_save(db)

def _get_application(user_id: int) -> Optional[Dict[str, Any]]:
    return _safe_load().get(str(user_id))

def _set_status(user_id: int, status: str) -> None:
    db = _safe_load()
    rec = db.get(str(user_id))
    if not rec:
        return
    rec["status"] = status
    rec["updated_at"] = int(time.time())
    db[str(user_id)] = rec
    _safe_save(db)

# ========= مفاتيح الترجمة الآمنة =========
def _tr(lang: str, key: str, default: str) -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s and s != key:
            return s
    except Exception:
        pass
    return default

# ========= لوحات =========
def _confirm_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tr(lang, "apply.btn.submit", "✅ إرسال"), callback_data="sapply:confirm"),
        InlineKeyboardButton(text=_tr(lang, "apply.btn.cancel", "❌ إلغاء"), callback_data="sapply:cancel"),
    )
    return kb.as_markup()

def _admin_kb(user_id: int, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tr(lang, "admin.btn.approve", "✅ موافقة"), callback_data=f"sapply:approve:{user_id}"),
        InlineKeyboardButton(text=_tr(lang, "admin.btn.reject", "❌ رفض"),   callback_data=f"sapply:reject:{user_id}"),
    )
    kb.row(InlineKeyboardButton(text=_tr(lang, "admin.btn.ask", "✍️ طلب توضيح"), callback_data=f"sapply:ask:{user_id}"))
    return kb.as_markup()

# ========= الحالات =========
class SupplierApply(StatesGroup):
    FULL_NAME   = State()
    COUNTRY_CITY= State()
    CONTACT     = State()
    ANDROID_EXP = State()
    PORTFOLIO   = State()
    CONFIRM     = State()

class AdminAsk(StatesGroup):
    WAITING_QUESTION = State()

# ========= أدوات مساعدة =========
def _preview_text(lang: str, data: Dict[str, Any]) -> str:
    return (
        f"🧾 <b>{_tr(lang,'apply.preview_title','مراجعة الطلب')}</b>\n\n"
        f"• {_tr(lang,'apply.q1','الاسم الكامل')}: <b>{data.get('full_name','-')}</b>\n"
        f"• {_tr(lang,'apply.q2','الدولة/المدينة')}: <b>{data.get('country_city','-')}</b>\n"
        f"• {_tr(lang,'apply.q3','وسيلة الاتصال')}: <code>{data.get('contact','-')}</code>\n"
        f"• {_tr(lang,'apply.q4','خبرة أندرويد')}: <b>{data.get('android_exp','-')}</b>\n"
        f"• {_tr(lang,'apply.q5','أعمال/روابط')}: <b>{data.get('portfolio','-')}</b>\n\n"
        f"{_tr(lang,'apply.confirm','هل تريد إرسال الطلب؟')}"
    )

async def _notify_admins(bot, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    # أرسل للإداريين
    for uid in ADMIN_IDS:
        try:
            await bot.send_message(uid, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
    # قناة تدقيق اختيارية
    if AUDIT_CHAT_ID:
        try:
            await bot.send_message(AUDIT_CHAT_ID, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass

# ========= المسار العام =========
@router.message(Command("apply_supplier"))
async def cmd_apply(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id) or "en"
    await message.answer(
        f"🧾 {_tr(lang,'apply.welcome','مرحبا! قدّم طلب الانضمام كمورّد.')}\n\n"
        f"{_tr(lang,'apply.note','أجب عن الأسئلة التالية بدقة.')}"
    )
    await message.answer(_tr(lang, "apply.q1", "ما اسمك الكامل؟"))
    await state.set_state(SupplierApply.FULL_NAME)

@router.message(SupplierApply.FULL_NAME)
async def q1(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id) or "en"
    await state.update_data(full_name=(message.text or "").strip())
    await message.answer(_tr(lang, "apply.q2", "ما الدولة/المدينة؟"))
    await state.set_state(SupplierApply.COUNTRY_CITY)

@router.message(SupplierApply.COUNTRY_CITY)
async def q2(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id) or "en"
    await state.update_data(country_city=(message.text or "").strip())
    await message.answer(_tr(lang, "apply.q3", "ضع وسيلة اتصال (تيليجرام/واتساب/بريد)."))
    await state.set_state(SupplierApply.CONTACT)

@router.message(SupplierApply.CONTACT)
async def q3(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id) or "en"
    await state.update_data(contact=(message.text or "").strip())
    await message.answer(_tr(lang, "apply.q4", "اذكر خبرتك مع أندرويد (سنوات/مجالات)."))
    await state.set_state(SupplierApply.ANDROID_EXP)

@router.message(SupplierApply.ANDROID_EXP)
async def q4(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id) or "en"
    await state.update_data(android_exp=(message.text or "").strip())
    await message.answer(_tr(lang, "apply.q5", "ارفق روابط لأعمال سابقة/بورتفوليو (إن وجدت)."))
    await state.set_state(SupplierApply.PORTFOLIO)

@router.message(SupplierApply.PORTFOLIO)
async def q5(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id) or "en"
    await state.update_data(portfolio=(message.text or "").strip())
    data = await state.get_data()
    await message.answer(_preview_text(lang, data), parse_mode=ParseMode.HTML, reply_markup=_confirm_kb(lang))
    await state.set_state(SupplierApply.CONFIRM)

@router.callback_query(F.data.in_({"sapply:confirm","sapply:cancel"}), SupplierApply.CONFIRM)
async def confirm_submit(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"

    if cb.data == "sapply:cancel":
        await cb.message.edit_reply_markup()
        await cb.message.answer(_tr(lang, "apply.cancelled", "تم إلغاء الطلب."))
        await state.clear()
        return await cb.answer()

    # إرسال الطلب
    payload = await state.get_data()
    await state.clear()

    _upsert_application(cb.from_user.id, lang, payload)

    text_admin = (
        f"🆕 <b>{_tr(lang,'admin.new_title','طلب مورّد جديد')}</b>\n\n"
        f"<b>ID:</b> <code>{cb.from_user.id}</code>\n"
        f"<b>Name:</b> {payload.get('full_name','-')}\n"
        f"<b>Country/City:</b> {payload.get('country_city','-')}\n"
        f"<b>Contact:</b> {payload.get('contact','-')}\n"
        f"<b>Android Exp:</b> {payload.get('android_exp','-')}\n"
        f"<b>Portfolio:</b> {payload.get('portfolio','-')}\n"
        f"<b>Status:</b> {_tr(lang,'status.pending','قيد المراجعة')}"
    )
    await _notify_admins(cb.bot, text_admin, kb=_admin_kb(cb.from_user.id, lang))

    await cb.message.edit_reply_markup()
    await cb.message.answer(_tr(lang, "apply.saved", "تم استلام طلبك وسيتم الرد قريباً."))
    await cb.answer()

# ========= مسار الأدمن =========
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

@router.callback_query(F.data.startswith("sapply:approve:"))
async def admin_approve(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        lang = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tr(lang, "sec.admin.only_admin", "للمشرفين فقط."), show_alert=True)

    try:
        user_id = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer("Bad payload", show_alert=True)

    app = _get_application(user_id)
    if not app:
        return await cb.answer("Not found", show_alert=True)

    _set_status(user_id, "approved")
    # أضفه كمورّد (عام)
    try:
        set_supplier(user_id, True)
    except Exception:
        pass

    lang_u = app.get("lang") or get_user_lang(user_id) or "en"
    try:
        await cb.bot.send_message(user_id, _tr(lang_u, "admin.approved.user", "✅ تم قبول طلبك كمورّد."))
    except Exception:
        pass

    await cb.message.answer(_tr(lang_u, "admin.done", "تم."))  # ملاحظة للأدمن
    await cb.answer(_tr(lang_u, "common.approved", "تمت الموافقة."))

@router.callback_query(F.data.startswith("sapply:reject:"))
async def admin_reject(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        lang = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tr(lang, "sec.admin.only_admin", "للمشرفين فقط."), show_alert=True)

    try:
        user_id = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer("Bad payload", show_alert=True)

    app = _get_application(user_id)
    if not app:
        return await cb.answer("Not found", show_alert=True)

    _set_status(user_id, "rejected")
    lang_u = app.get("lang") or get_user_lang(user_id) or "en"
    try:
        await cb.bot.send_message(user_id, _tr(lang_u, "admin.rejected.user", "❌ نأسف، تم رفض الطلب."))
    except Exception:
        pass

    await cb.message.answer(_tr(lang_u, "admin.done", "تم."))
    await cb.answer(_tr(lang_u, "common.rejected", "تم الرفض."))

@router.callback_query(F.data.startswith("sapply:ask:"))
async def admin_ask_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        lang = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tr(lang, "sec.admin.only_admin", "للمشرفين فقط."), show_alert=True)
    try:
        user_id = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer("Bad payload", show_alert=True)

    app = _get_application(user_id)
    if not app:
        return await cb.answer("Not found", show_alert=True)

    lang_admin = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(AdminAsk.WAITING_QUESTION)
    await state.update_data(ask_user_id=user_id)
    await cb.message.answer(_tr(lang_admin, "admin.ask.prompt", "أرسل سؤالك ليُرسل للمتقدّم."))
    await cb.answer()

@router.message(AdminAsk.WAITING_QUESTION)
async def admin_send_question(message: Message, state: FSMContext):
    data = await state.get_data()
    target_user = int(data.get("ask_user_id", 0))
    if not target_user:
        await message.answer("No user.")
        return await state.clear()

    lang_u = get_user_lang(target_user) or "en"
    q = (message.text or "").strip()
    if not q:
        return await message.answer("…")

    try:
        await message.bot.send_message(
            target_user,
            _tr(lang_u, "admin.ask.user", "📩 يوجد استفسار من الإدارة:\n{q}").format(q=q),
            parse_mode=ParseMode.HTML
        )
        await message.answer(_tr(lang_u, "admin.done", "تم."))
    except Exception:
        await message.answer("⚠️ Failed to send.")
    await state.clear()
