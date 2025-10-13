# handlers/supplier_vault.py
from __future__ import annotations

import os, json, io, datetime
from typing import Any

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from aiogram.enums import ParseMode
from lang import t, get_user_lang

# مورّد فقط: نعتمد على ملف utils/suppliers
try:
    from utils.suppliers import is_supplier as _is_supplier
except Exception:
    _is_supplier = lambda _uid: False

router = Router(name="supplier_vault")

# ========= التخزين =========
ROOT = os.path.join("data", "suppliers")
os.makedirs(ROOT, exist_ok=True)

def _udir(uid: int) -> str:
    p = os.path.join(ROOT, str(uid))
    os.makedirs(p, exist_ok=True)
    return p

def _pf(uid: int) -> str: return os.path.join(_udir(uid), "profile.json")
def _kf(uid: int) -> str: return os.path.join(_udir(uid), "keys.json")
def _af(uid: int) -> str: return os.path.join(_udir(uid), "acts.json")

def _load_json(path: str, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

def _save_json(path: str, data: Any):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ========= ترجمات سريعة مع Fallback =========
def _L(lang: str, key: str, en: str, ar: str) -> str:
    v = t(lang, key)
    if v and v != key:
        return v
    return ar if lang == "ar" else en

# ========= حالات FSM =========
class Prof(StatesGroup):
    name = State()
    contact = State()
    note = State()

class Keys(StatesGroup):
    add = State()

class Acts(StatesGroup):
    add_product = State()
    add_customer = State()
    add_note = State()

# ========= كيبورد عام =========
def _kb_back(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_L(lang,"back_to_menu","« Back","« رجوع"), callback_data="back_to_menu")]
    ])

# ========= ملفي =========
def _profile_default(uid: int, fu) -> dict:
    return {
        "display_name": fu.first_name or str(uid),
        "contact": f"@{fu.username}" if fu.username else str(uid),
        "note": "",
        "created_at": datetime.datetime.utcnow().isoformat()
    }

def _kb_profile(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_L(lang,"sp_edit_name","Edit name","تعديل الاسم"), callback_data="sp:edit:name"),
            InlineKeyboardButton(text=_L(lang,"sp_edit_contact","Edit contact","تعديل جهة الاتصال"), callback_data="sp:edit:contact"),
        ],
        [InlineKeyboardButton(text=_L(lang,"sp_edit_note","Edit note","تعديل الملاحظة"), callback_data="sp:edit:note")],
        [InlineKeyboardButton(text=_L(lang,"back_to_menu","« Back","« رجوع"), callback_data="back_to_menu")],
    ])

async def _render_profile(target, uid: int, fu):
    lang = get_user_lang(uid) or "en"
    prof = _load_json(_pf(uid), _profile_default(uid, fu))

    text = (
        f"👤 <b>{_L(lang,'sp_profile_title','Supplier profile','ملف المورد')}</b>\n\n"
        f"• {_L(lang,'sp_name','Name','الاسم')}: <b>{prof.get('display_name','')}</b>\n"
        f"• {_L(lang,'sp_contact','Contact','جهة الاتصال')}: <code>{prof.get('contact','')}</code>\n"
        f"• {_L(lang,'sp_note','Note','ملاحظة')}:\n<code>{prof.get('note','') or '-'}</code>"
    )

    if isinstance(target, Message):
        return await target.answer(text, reply_markup=_kb_profile(lang), parse_mode=ParseMode.HTML)
    else:
        return await target.edit_text(text, reply_markup=_kb_profile(lang), parse_mode=ParseMode.HTML)

@router.callback_query(F.data.in_({"supplier_profile","my_profile"}))
async def open_profile(cb: CallbackQuery, state: FSMContext):
    if not _is_supplier(cb.from_user.id):
        return await cb.answer(_L("en","sup_only","Suppliers only.","هذه الميزة للموردين فقط."), show_alert=True)
    await state.clear()
    await _render_profile(cb.message, cb.from_user.id, cb.from_user)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^sp:edit:(name|contact|note)$"))
async def prof_edit_pick(cb: CallbackQuery, state: FSMContext):
    if not _is_supplier(cb.from_user.id):
        return await cb.answer(_L("en","sup_only","Suppliers only.","هذه الميزة للموردين فقط."), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    which = cb.data.split(":")[2]
    await state.clear()
    if which == "name":
        await state.set_state(Prof.name)
        ask = _L(lang,"sp_ask_name","Send new display name:","أرسل الاسم المعروض الجديد:")
    elif which == "contact":
        await state.set_state(Prof.contact)
        ask = _L(lang,"sp_ask_contact","Send contact (e.g., @user / phone):","أرسل جهة الاتصال (مثلاً @user / رقم):")
    else:
        await state.set_state(Prof.note)
        ask = _L(lang,"sp_ask_note","Send note (plain text):","أرسل الملاحظة (نص فقط):")
    await cb.message.answer(ask, reply_markup=_kb_back(lang))
    await cb.answer()

@router.message(Prof.name)
async def prof_set_name(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    p = _load_json(_pf(msg.from_user.id), _profile_default(msg.from_user.id, msg.from_user))
    p["display_name"] = (msg.text or "").strip()[:64]
    _save_json(_pf(msg.from_user.id), p)
    await state.clear()
    await msg.answer(_L(lang,"sp_ok","Saved ✅","تم الحفظ ✅"))
    await _render_profile(msg, msg.from_user.id, msg.from_user)

@router.message(Prof.contact)
async def prof_set_contact(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    p = _load_json(_pf(msg.from_user.id), _profile_default(msg.from_user.id, msg.from_user))
    p["contact"] = (msg.text or "").strip()[:64]
    _save_json(_pf(msg.from_user.id), p)
    await state.clear()
    await msg.answer(_L(lang,"sp_ok","Saved ✅","تم الحفظ ✅"))
    await _render_profile(msg, msg.from_user.id, msg.from_user)

@router.message(Prof.note)
async def prof_set_note(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    p = _load_json(_pf(msg.from_user.id), _profile_default(msg.from_user.id, msg.from_user))
    p["note"] = (msg.text or "").strip()[:2000]
    _save_json(_pf(msg.from_user.id), p)
    await state.clear()
    await msg.answer(_L(lang,"sp_ok","Saved ✅","تم الحفظ ✅"))
    await _render_profile(msg, msg.from_user.id, msg.from_user)

# ========= مفاتيحي =========
PAGE = 10

def _kb_keys(lang: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_L(lang,"sk_add","➕ Add keys","➕ إضافة مفاتيح"), callback_data="sk:add")],
        [
            InlineKeyboardButton(text="«", callback_data=f"sk:page:{max(1,page-1)}"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="»", callback_data=f"sk:page:{page+1}"),
        ],
        [
            InlineKeyboardButton(text=_L(lang,"sk_export","📤 Export TXT","📤 تصدير TXT"), callback_data="sk:export"),
            InlineKeyboardButton(text=_L(lang,"sk_clear","🗑 Clear all","🗑 حذف الكل"), callback_data="sk:clear"),
        ],
        [InlineKeyboardButton(text=_L(lang,"back_to_menu","« Back","« رجوع"), callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _toggle_status(s: str) -> str:
    return "used" if s != "used" else "new"

def _fmt_key_row(i: int, k: dict) -> str:
    icon = "✅" if k.get("status") == "new" else "✔️"
    return f"{i}. {icon} <code>{k.get('code','')}</code>"

def _paginate(items, page):
    total_pages = max(1, (len(items) + PAGE - 1)//PAGE)
    page = max(1, min(page, total_pages))
    start = (page-1)*PAGE
    return items[start:start+PAGE], page, total_pages

async def _render_keys(target, uid: int, page: int = 1):
    lang = get_user_lang(uid) or "en"
    keys = _load_json(_kf(uid), [])
    page_items, page, total_pages = _paginate(keys, page)

    lines = [f"🔑 <b>{_L(lang,'sk_title','My keys','مفاتيحي')}</b> — {_L(lang,'sk_hint','tap a key below to toggle status or delete.','انقر على المفتاح للتبديل أو الحذف.')}\n"]
    if not keys:
        lines.append(_L(lang,"sk_empty","No keys saved yet.","لا توجد مفاتيح محفوظة بعد."))
    else:
        for idx, item in enumerate(page_items, start=(page-1)*PAGE+1):
            lines.append(_fmt_key_row(idx, item))

    kb = _kb_keys(lang, page, total_pages)

    # أزرار لكل عنصر (صفين لكل مفتاح: تبديل / حذف)
    ik = kb.inline_keyboard
    for idx, _item in enumerate(page_items, start=(page-1)*PAGE+1):
        ik.insert(-3, [  # قبل صف التنقل
            InlineKeyboardButton(text=_L(lang,"sk_toggle","Toggle","تبديل"), callback_data=f"sk:toggle:{idx}"),
            InlineKeyboardButton(text=_L(lang,"sk_delete","Delete","حذف"), callback_data=f"sk:del:{idx}"),
        ])

    if isinstance(target, Message):
        return await target.answer("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        return await target.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)

@router.callback_query(F.data.in_({"supplier_keys","my_keys"}))
async def open_keys(cb: CallbackQuery, state: FSMContext):
    if not _is_supplier(cb.from_user.id):
        return await cb.answer(_L("en","sup_only","Suppliers only.","هذه الميزة للموردين فقط."), show_alert=True)
    await state.clear()
    await _render_keys(cb.message, cb.from_user.id, 1)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^sk:page:\d+$"))
async def sk_page(cb: CallbackQuery):
    page = int(cb.data.split(":")[2])
    await _render_keys(cb.message, cb.from_user.id, page)
    await cb.answer()

@router.callback_query(F.data == "sk:add")
async def sk_add(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(Keys.add)
    hint = _L(lang,"sk_add_hint",
              "Send keys (one per line). I will ignore duplicates.",
              "أرسل المفاتيح (سطر لكل مفتاح). سأتجاهل المكرر.")
    await cb.message.answer(hint, reply_markup=_kb_back(lang))
    await cb.answer()

@router.message(Keys.add)
async def sk_add_save(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "")
    cand = [x.strip() for x in raw.replace("\r","").split("\n") if x.strip()]
    keys = _load_json(_kf(msg.from_user.id), [])
    existing = {k.get("code") for k in keys}
    added = 0
    for code in cand:
        if code in existing: continue
        keys.append({"code": code, "status": "new", "added_at": datetime.datetime.utcnow().isoformat()})
        existing.add(code)
        added += 1
    _save_json(_kf(msg.from_user.id), keys)
    await state.clear()
    await msg.answer(_L(lang,"sk_added","Added: ","تمت الإضافة: ") + str(added))
    await _render_keys(msg, msg.from_user.id, 1)

@router.callback_query(F.data.regexp(r"^sk:toggle:\d+$"))
async def sk_toggle(cb: CallbackQuery):
    idx = int(cb.data.split(":")[2]) - 1
    keys = _load_json(_kf(cb.from_user.id), [])
    if 0 <= idx < len(keys):
        keys[idx]["status"] = _toggle_status(keys[idx].get("status","new"))
        _save_json(_kf(cb.from_user.id), keys)
    await _render_keys(cb.message, cb.from_user.id, 1)
    await cb.answer("OK")

@router.callback_query(F.data.regexp(r"^sk:del:\d+$"))
async def sk_del(cb: CallbackQuery):
    idx = int(cb.data.split(":")[2]) - 1
    keys = _load_json(_kf(cb.from_user.id), [])
    if 0 <= idx < len(keys):
        keys.pop(idx)
        _save_json(_kf(cb.from_user.id), keys)
    await _render_keys(cb.message, cb.from_user.id, 1)
    await cb.answer("OK")

@router.callback_query(F.data == "sk:clear")
async def sk_clear(cb: CallbackQuery):
    _save_json(_kf(cb.from_user.id), [])
    await _render_keys(cb.message, cb.from_user.id, 1)
    await cb.answer("OK")

@router.callback_query(F.data == "sk:export")
async def sk_export(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    keys = _load_json(_kf(cb.from_user.id), [])
    buf = io.StringIO()
    for k in keys:
        buf.write(f"{k.get('code','')}\n")
    buf.seek(0)
    path = os.path.join(_udir(cb.from_user.id), "keys_export.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    await cb.message.answer_document(FSInputFile(path), caption=_L(lang,"sk_exported","Exported.","تم التصدير."))
    await cb.answer("OK")

# ========= تفعيلاتي =========
def _kb_acts(lang: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_L(lang,"sa_add","➕ Add activation","➕ إضافة تفعيل"), callback_data="sa:add")],
        [
            InlineKeyboardButton(text="«", callback_data=f"sa:page:{max(1,page-1)}"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="»", callback_data=f"sa:page:{page+1}"),
        ],
        [
            InlineKeyboardButton(text=_L(lang,"sa_export","📤 Export TXT","📤 تصدير TXT"), callback_data="sa:export"),
            InlineKeyboardButton(text=_L(lang,"sa_clear","🗑 Clear all","🗑 حذف الكل"), callback_data="sa:clear"),
        ],
        [InlineKeyboardButton(text=_L(lang,"back_to_menu","« Back","« رجوع"), callback_data="back_to_menu")],
    ])

def _fmt_act_row(i: int, a: dict) -> str:
    ts = a.get("ts","")[:19].replace("T"," ")
    return f"{i}. <b>{a.get('product','')}</b> — {a.get('customer','')} <i>({ts})</i>"

async def _render_acts(target, uid: int, page: int = 1):
    lang = get_user_lang(uid) or "en"
    acts = _load_json(_af(uid), [])
    page_items, page, total_pages = _paginate(acts, page)

    lines = [f"📋 <b>{_L(lang,'sa_title','My activations','تفعيلاتي')}</b>\n"]
    if not acts:
        lines.append(_L(lang,"sa_empty","No activations yet.","لا توجد تفعيلات بعد."))
    else:
        for idx, item in enumerate(page_items, start=(page-1)*PAGE+1):
            lines.append(_fmt_act_row(idx, item))

    kb = _kb_acts(lang, page, total_pages)

    # أزرار حذف لكل عنصر
    for idx, _ in enumerate(page_items, start=(page-1)*PAGE+1):
        kb.inline_keyboard.insert(-3, [
            InlineKeyboardButton(text=_L(lang,"sa_delete","Delete","حذف"), callback_data=f"sa:del:{idx}")
        ])

    if isinstance(target, Message):
        return await target.answer("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        return await target.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)

@router.callback_query(F.data.in_({"supplier_acts","my_acts"}))
async def open_acts(cb: CallbackQuery, state: FSMContext):
    if not _is_supplier(cb.from_user.id):
        return await cb.answer(_L("en","sup_only","Suppliers only.","هذه الميزة للموردين فقط."), show_alert=True)
    await state.clear()
    await _render_acts(cb.message, cb.from_user.id, 1)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^sa:page:\d+$"))
async def sa_page(cb: CallbackQuery):
    page = int(cb.data.split(":")[2])
    await _render_acts(cb.message, cb.from_user.id, page)
    await cb.answer()

@router.callback_query(F.data == "sa:add")
async def sa_add(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(Acts.add_product)
    await cb.message.answer(_L(lang,"sa_ask_product","Send product/app name:","أرسل اسم المنتج/التطبيق:"),
                            reply_markup=_kb_back(lang))
    await cb.answer()

@router.message(Acts.add_product)
async def sa_add_product(msg: Message, state: FSMContext):
    await state.update_data(product=(msg.text or "").strip()[:100])
    lang = get_user_lang(msg.from_user.id) or "en"
    await state.set_state(Acts.add_customer)
    await msg.answer(_L(lang,"sa_ask_customer","Send customer or device id:","أرسل العميل أو معرّف الجهاز:"),
                     reply_markup=_kb_back(lang))

@router.message(Acts.add_customer)
async def sa_add_customer(msg: Message, state: FSMContext):
    await state.update_data(customer=(msg.text or "").strip()[:120])
    lang = get_user_lang(msg.from_user.id) or "en"
    await state.set_state(Acts.add_note)
    await msg.answer(_L(lang,"sa_ask_note","Optional note (or '-' to skip):","ملاحظة اختيارية (أو '-' للتخطي):"),
                     reply_markup=_kb_back(lang))

@router.message(Acts.add_note)
async def sa_add_note(msg: Message, state: FSMContext):
    d = await state.get_data()
    product = d.get("product","")
    customer = d.get("customer","")
    note = (msg.text or "").strip()
    if note == "-": note = ""

    acts = _load_json(_af(msg.from_user.id), [])
    acts.append({
        "product": product, "customer": customer, "note": note,
        "ts": datetime.datetime.utcnow().isoformat()
    })
    _save_json(_af(msg.from_user.id), acts)

    await state.clear()
    lang = get_user_lang(msg.from_user.id) or "en"
    await msg.answer(_L(lang,"sa_saved","Saved ✅","تم الحفظ ✅"))
    await _render_acts(msg, msg.from_user.id, 1)

@router.callback_query(F.data.regexp(r"^sa:del:\d+$"))
async def sa_del(cb: CallbackQuery):
    idx = int(cb.data.split(":")[2]) - 1
    acts = _load_json(_af(cb.from_user.id), [])
    if 0 <= idx < len(acts):
        acts.pop(idx)
        _save_json(_af(cb.from_user.id), acts)
    await _render_acts(cb.message, cb.from_user.id, 1)
    await cb.answer("OK")

@router.callback_query(F.data == "sa:clear")
async def sa_clear(cb: CallbackQuery):
    _save_json(_af(cb.from_user.id), [])
    await _render_acts(cb.message, cb.from_user.id, 1)
    await cb.answer("OK")

@router.callback_query(F.data == "sa:export")
async def sa_export(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    acts = _load_json(_af(cb.from_user.id), [])
    buf = io.StringIO()
    for a in acts:
        ts = a.get("ts","")[:19].replace("T"," ")
        line = f"{ts}\t{a.get('product','')}\t{a.get('customer','')}\t{a.get('note','')}\n"
        buf.write(line)
    buf.seek(0)
    path = os.path.join(_udir(cb.from_user.id), "activations_export.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    await cb.message.answer_document(FSInputFile(path), caption=_L(lang,"sa_exported","Exported.","تم التصدير."))
    await cb.answer("OK")

# زر وهمي
@router.callback_query(F.data == "noop")
async def _noop(cb: CallbackQuery):
    await cb.answer()
