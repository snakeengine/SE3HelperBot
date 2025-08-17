# handlers/supplier_directory.py
from __future__ import annotations

import os, json, math, logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from lang import t, get_user_lang

# هل المستخدم مورّد؟
try:
    from utils.suppliers import is_supplier as _is_supplier
    from utils.suppliers import set_supplier as _set_supplier
except Exception:
    _is_supplier = None
    _set_supplier = None

log = logging.getLogger(__name__)
router = Router(name="supplier_directory")

# ===== إعدادات ومسارات =====
DATA_DIR = "data"
SUP_DIR = os.path.join(DATA_DIR, "suppliers")
PUB_FILE = os.path.join(DATA_DIR, "public_suppliers.json")
BAN_FILE = os.path.join(DATA_DIR, "supplier_banlist.json")
os.makedirs(SUP_DIR, exist_ok=True)

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _now_iso() -> str:
    return datetime.utcnow().isoformat()

def _L(lang: str, key: str, en: str, ar: str) -> str:
    """ترجمة مع fallback لو المفتاح ناقص."""
    v = t(lang, key)
    if v and v != key:
        return v
    return ar if lang == "ar" else en

# ================= Banlist =================
def _load_ban() -> set[int]:
    try:
        with open(BAN_FILE, "r", encoding="utf-8") as f:
            arr = json.load(f)
            return set(int(x) for x in arr)
    except Exception:
        return set()

def _save_ban(s: set[int]):
    with open(BAN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(s)), f, ensure_ascii=False, indent=2)

def _is_banned(uid: int) -> bool:
    try:
        return int(uid) in _load_ban()
    except Exception:
        return False

def _ban(uid: int):
    s = _load_ban(); s.add(int(uid)); _save_ban(s)

def _unban(uid: int):
    s = _load_ban(); s.discard(int(uid)); _save_ban(s)

# ================= تخزين بطاقة المورد =================
def _user_folder(uid: int) -> str:
    p = os.path.join(SUP_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p

def _pub_path(uid: int) -> str:
    return os.path.join(_user_folder(uid), "pub.json")

def _load_pub(uid: int) -> dict:
    try:
        with open(_pub_path(uid), "r", encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                # ترقية قديمة: ضمّن الحقول الجديدة لو ناقصة
                d.setdefault("languages", "")
                d.setdefault("whatsapp", "")
                return d
    except Exception:
        pass
    # قالب افتراضي
    return {
        "user_id": uid,
        "username": "",
        "name": "",
        "country": "",
        "languages": "",  # NEW
        "contact": "",    # Telegram: @username أو رقم
        "whatsapp": "",   # NEW
        "channel": "",
        "bio": "",
        "status": "draft",      # draft|pending|approved|hidden
        "visible": False,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

def _save_pub(uid: int, data: dict):
    data["updated_at"] = _now_iso()
    with open(_pub_path(uid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _delete_pub(uid: int):
    try:
        os.remove(_pub_path(uid))
    except Exception:
        pass

# ================= بناء وتجديد الدليل العام =================
def _rebuild_public_directory():
    items = []
    for name in os.listdir(SUP_DIR):
        up = os.path.join(SUP_DIR, name, "pub.json")
        if not os.path.isfile(up):
            continue
        try:
            with open(up, "r", encoding="utf-8") as f:
                d = json.load(f)
            # ننشر فقط الموافق عليه والمرئي
            if d.get("status") == "approved" and d.get("visible"):
                items.append({
                    "user_id": d.get("user_id"),
                    "username": d.get("username"),
                    "name": d.get("name"),
                    "country": d.get("country"),
                    "languages": d.get("languages", ""),  # NEW
                    "contact": d.get("contact"),
                    "whatsapp": d.get("whatsapp", ""),    # NEW
                    "channel": d.get("channel"),
                    "bio": d.get("bio"),
                    "verified": True,
                    "updated_at": d.get("updated_at"),
                })
        except Exception:
            continue
    with open(PUB_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

# ================= حالات التعديل =================
class PubStates(StatesGroup):
    name = State()
    country = State()
    languages = State()  # NEW
    contact = State()
    whatsapp = State()   # NEW
    channel = State()
    bio = State()

# ================= واجهة المورد =================
def _kb_supplier(lang: str, status: str, visible: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=_L(lang, "spub_btn_edit_name", "Edit name", "تعديل الاسم"), callback_data="spub:edit:name"),
            InlineKeyboardButton(text=_L(lang, "spub_btn_edit_country", "Edit country", "تعديل الدولة"), callback_data="spub:edit:country"),
        ],
        [
            InlineKeyboardButton(text=_L(lang, "spub_btn_edit_languages", "Edit languages", "تعديل اللغات"), callback_data="spub:edit:languages"),
            InlineKeyboardButton(text=_L(lang, "spub_btn_edit_contact", "Edit Telegram", "تعديل تيليجرام"), callback_data="spub:edit:contact"),
        ],
        [
            InlineKeyboardButton(text=_L(lang, "spub_btn_edit_whatsapp", "Edit WhatsApp", "تعديل واتساب"), callback_data="spub:edit:whatsapp"),
            InlineKeyboardButton(text=_L(lang, "spub_btn_edit_channel", "Edit channel", "تعديل القناة"), callback_data="spub:edit:channel"),
        ],
        [InlineKeyboardButton(text=_L(lang, "spub_btn_edit_bio", "Edit bio", "تعديل النبذة"), callback_data="spub:edit:bio")],
    ]
    if status in ("draft", "hidden", "pending"):
        rows.append([InlineKeyboardButton(text=_L(lang, "spub_btn_submit", "Submit for listing ✅", "إرسال للمراجعة ✅"), callback_data="spub:submit")])
    if status == "approved" and visible:
        rows.append([InlineKeyboardButton(text=_L(lang, "spub_btn_unpublish", "Unpublish ⛔", "إخفاء من الدليل ⛔"), callback_data="spub:unpublish")])
    rows.append([InlineKeyboardButton(text=_L(lang, "back_to_menu", "« Back", "« رجوع"), callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _card(lang: str, d: dict) -> str:
    lines = [
        f"🧾 <b>{_L(lang,'spub_title','Supplier public card','بطاقة المورد العامة')}</b>",
        f"{_L(lang,'spub_field_name','Name','الاسم')}: <b>{d.get('name','')}</b>",
        f"{_L(lang,'spub_field_country','Country','الدولة')}: <b>{d.get('country','')}</b>",
    ]
    langs = (d.get("languages") or "").strip()
    if langs:
        lines.append(f"{_L(lang,'spub_field_languages','Languages','اللغات')}: <b>{langs}</b>")
    lines += [
        f"{_L(lang,'spub_field_contact','Telegram','تيليجرام')}: <code>{d.get('contact','')}</code>",
    ]
    whats = (d.get("whatsapp") or "").strip()
    if whats:
        lines.append(f"{_L(lang,'spub_field_whatsapp','WhatsApp','واتساب')}: <code>{whats}</code>")
    lines.append(f"{_L(lang,'spub_field_channel','Channel','القناة/المجموعة')}: <code>{d.get('channel','')}</code>")

    bio = (d.get("bio") or "").strip()
    if bio:
        lines.append(f"{_L(lang,'spub_field_bio','Bio','النبذة')}: {bio}")
    lines.append("")

    st_map = {
        "draft": _L(lang,"spub_status_draft","Status: draft (not submitted)","الحالة: مسودة (غير مُرسلة)"),
        "pending": _L(lang,"spub_status_pending","Status: pending review","الحالة: قيد المراجعة"),
        "approved": _L(lang,"spub_status_approved","Status: published ✅","الحالة: منشور ✅"),
        "hidden": _L(lang,"spub_status_hidden","Status: hidden","الحالة: مخفي"),
    }
    lines.append(st_map.get(d.get("status","draft"), ""))

    if _is_banned(d.get("user_id")):
        lines.append("🚫 " + _L(lang, "spub_status_banned", "User is banned from publishing.", "المستخدم محظور من النشر."))
    return "\n".join(lines)

# أمر مباشر لفتح لوحة المورد
@router.message(Command("supplier_public"))
async def supplier_public_cmd(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    if not _is_supplier or not _is_supplier(msg.from_user.id):
        return await msg.answer(_L(lang, "sup_only", "Suppliers only.", "هذه الميزة للموردين فقط."))

    d = _load_pub(msg.from_user.id)
    d["username"] = msg.from_user.username or d.get("username","")
    _save_pub(msg.from_user.id, d)

    await msg.answer(_card(lang, d), reply_markup=_kb_supplier(lang, d.get("status","draft"), d.get("visible", False)))

# فتح لوحة المورد من زر الواجهة
@router.callback_query(F.data == "supplier_public")
async def supplier_public_cb(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not _is_supplier or not _is_supplier(cb.from_user.id):
        return await cb.answer(_L(lang, "sup_only", "Suppliers only.", "هذه الميزة للموردين فقط."), show_alert=True)

    d = _load_pub(cb.from_user.id)
    d["username"] = cb.from_user.username or d.get("username", "")
    _save_pub(cb.from_user.id, d)

    try:
        await cb.message.edit_text(
            _card(lang, d),
            reply_markup=_kb_supplier(lang, d.get("status","draft"), d.get("visible", False)),
            disable_web_page_preview=True
        )
    except Exception:
        await cb.message.answer(
            _card(lang, d),
            reply_markup=_kb_supplier(lang, d.get("status","draft"), d.get("visible", False)),
            disable_web_page_preview=True
        )
    await cb.answer()

# تحرير الحقول
@router.callback_query(F.data.regexp(r"^spub:edit:(name|country|languages|contact|whatsapp|channel|bio)$"))
async def spub_edit(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    field = cb.data.split(":")[2]
    prompts = {
        "name":      _L(lang,"spub_ask_name","Send display name:","أرسل الاسم المعروض:"),
        "country":   _L(lang,"spub_ask_country","Send country:","أرسل الدولة:"),
        "languages": _L(lang,"spub_ask_languages","Send languages (comma separated):","أرسل اللغات (مفصولة بفواصل):"),
        "contact":   _L(lang,"spub_ask_contact","Send Telegram (@user / phone):","أرسل تيليجرام (@user / رقم):"),
        "whatsapp":  _L(lang,"spub_ask_whatsapp","Send WhatsApp (link or phone):","أرسل واتساب (رابط أو رقم):"),
        "channel":   _L(lang,"spub_ask_channel","Send channel/group link or @handle:","أرسل رابط القناة/المجموعة أو المعرف:"),
        "bio":       _L(lang,"spub_ask_bio","Send short bio (plain text):","أرسل نبذة قصيرة (نص):"),
    }
    await state.update_data(spub_field=field)
    await state.set_state(getattr(PubStates, field))
    await cb.message.answer(prompts[field])
    await cb.answer()

@router.message(PubStates.name)
@router.message(PubStates.country)
@router.message(PubStates.languages)
@router.message(PubStates.contact)
@router.message(PubStates.whatsapp)
@router.message(PubStates.channel)
@router.message(PubStates.bio)
async def spub_save_field(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    data = await state.get_data()
    field = data.get("spub_field")
    value = (msg.text or "").strip()

    d = _load_pub(msg.from_user.id)
    d[field] = value
    _save_pub(msg.from_user.id, d)

    # ✅ NEW: حدّث قائمة الموردين فورًا إذا كانت البطاقة منشورة
    if d.get("status") == "approved" and d.get("visible"):
        _rebuild_public_directory()

    await state.clear()
    await msg.answer(_L(lang, "spub_saved", "Saved ✅", "تم الحفظ ✅"))
    await msg.answer(
        _card(lang, d),
        reply_markup=_kb_supplier(lang, d.get("status","draft"), d.get("visible", False))
    )

# إرسال للمراجعة
@router.callback_query(F.data == "spub:submit")
async def spub_submit(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"

    if _is_banned(cb.from_user.id):
        return await cb.answer(_L(lang, "spub_banned", "You are banned from publishing.", "أنت محظور من النشر."), show_alert=True)

    d = _load_pub(cb.from_user.id)
    required_ok = all([(d.get("name") or "").strip(), (d.get("country") or "").strip(), (d.get("contact") or "").strip()])
    if not required_ok:
        return await cb.answer(_L(lang, "spub_fill_required", "Please fill name, country and contact first.", "يرجى إكمال الاسم، الدولة، وجهة الاتصال أولًا."), show_alert=True)

    d["status"] = "pending"
    d["visible"] = False
    d["username"] = cb.from_user.username or d.get("username","")
    _save_pub(cb.from_user.id, d)

    await cb.message.edit_text(_card(lang, d), reply_markup=_kb_supplier(lang, d["status"], d["visible"]))
    await cb.answer(_L(lang, "spub_submitted_ok", "Sent for admin review ✅", "تم الإرسال للمراجعة ✅"))

    # إشعار الأدمنين
    adm_text = (
        f"🆕 <b>Supplier directory request</b>\n"
        f"User: <code>{cb.from_user.id}</code> @{cb.from_user.username or ''}\n\n"
        f"{_card(lang, d)}"
    )
    kb_adm = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_L(lang,"spub_adm_approve","Approve & publish ✅","اعتماد ونشر ✅"), callback_data=f"spubadm:approve:{cb.from_user.id}"),
        InlineKeyboardButton(text=_L(lang,"spub_adm_hide","Hide ⛔","إخفاء ⛔"), callback_data=f"spubadm:hide:{cb.from_user.id}"),
    ],[
        InlineKeyboardButton(text=_L(lang,"spub_adm_delete","Delete 🗑️","حذف 🗑️"), callback_data=f"spubadm:delete:{cb.from_user.id}"),
        InlineKeyboardButton(text=_L(lang,"spub_adm_ban","Ban 🚫","حظر 🚫"), callback_data=f"spubadm:ban:{cb.from_user.id}"),
        InlineKeyboardButton(text=_L(lang,"spub_adm_unban","Unban ✅","إلغاء الحظر ✅"), callback_data=f"spubadm:unban:{cb.from_user.id}"),
    ],[
        InlineKeyboardButton(text=_L(lang,"spub_adm_demote","Demote supplier ⬇️","إلغاء مورد ⬇️"), callback_data=f"spubadm:demote:{cb.from_user.id}"),
    ]])
    for aid in ADMIN_IDS:
        try:
            await cb.message.bot.send_message(aid, adm_text, reply_markup=kb_adm, disable_web_page_preview=True)
        except Exception:
            pass

# إخفاء ذاتي للمورد
@router.callback_query(F.data == "spub:unpublish")
async def spub_unpublish(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    d = _load_pub(cb.from_user.id)
    d["status"] = "hidden"
    d["visible"] = False
    _save_pub(cb.from_user.id, d)
    _rebuild_public_directory()
    await cb.message.edit_text(_card(lang, d), reply_markup=_kb_supplier(lang, d["status"], d["visible"]))
    await cb.answer(_L(lang, "spub_hidden_ok", "Unpublished.", "تم الإخفاء."))

# ================= واجهة المستخدم العامة =================
PUB_PER_PAGE = 6

def _read_public_items():
    try:
        with open(PUB_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        items = []
    items.sort(key=lambda x: x.get("updated_at",""), reverse=True)
    return items

def _kb_public_list(lang: str, page: int, total_pages: int, items: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for it in items:
        name = it.get("name","")
        contact = (it.get("contact") or "").strip()
        whatsapp = (it.get("whatsapp") or "").strip()
        channel = (it.get("channel") or "").strip()

        # عنوان
        rows.append([InlineKeyboardButton(text=f"• {name}", callback_data="noop")])

        line_btns = []
        if contact:
            if contact.startswith("@"):
                line_btns.append(InlineKeyboardButton(text=_L(lang,"td_contact","Contact","مراسلة"),
                                                      url=f"https://t.me/{contact[1:]}"))
            else:
                uid = it.get("user_id")
                if uid:
                    line_btns.append(InlineKeyboardButton(text=_L(lang,"td_contact","Contact","مراسلة"),
                                                          url=f"tg://user?id={uid}"))
        if whatsapp:
            wurl = whatsapp if whatsapp.startswith("http") else f"https://wa.me/{whatsapp.lstrip('+').replace(' ','')}"
            line_btns.append(InlineKeyboardButton(text=_L(lang,"td_whatsapp","WhatsApp","واتساب"), url=wurl))
        if channel:
            url = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
            line_btns.append(InlineKeyboardButton(text=_L(lang,"td_channel","Channel","القناة"), url=url))
        if line_btns:
            rows.append(line_btns)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"td:list:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"td:list:{page+1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text=t(lang,"back_to_menu"), callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _format_item_block(lang: str, it: dict, idx: int) -> str:
    # نص مفصل لكل مورد داخل الرسالة
    lines = [
        f"{idx}. <b>{it.get('name','')}</b>",
    ]
    if it.get("country"):
        lines.append(f"   🌍 { _L(lang,'spub_field_country','Country','الدولة') }: {it.get('country')}")
    if (it.get('languages') or '').strip():
        lines.append(f"   🗣 { _L(lang,'spub_field_languages','Languages','اللغات') }: {it.get('languages')}")
    if (it.get('bio') or '').strip():
        lines.append(f"   📝 {it.get('bio')}")
    return "\n".join(lines)

async def _render_public_list(target, lang: str, page: int):
    items = _read_public_items()
    total_pages = max(1, math.ceil(len(items)/PUB_PER_PAGE))
    page = max(1, min(page, total_pages))
    view = items[(page-1)*PUB_PER_PAGE : page*PUB_PER_PAGE]

    header = f"📇 <b>{_L(lang,'td_title','Trusted suppliers','الموردون الموثوقون')}</b>"
    if not items:
        header += "\n\n" + _L(lang,"td_empty","No suppliers published yet.","لا يوجد موردون منشورون حالياً.")
        text = header
    else:
        header += "\n" + _L(lang,"td_hint","Tap a contact/WhatsApp/channel below to reach a supplier.","اضغط على مراسلة/واتساب/القناة للتواصل مع المورد.")
        blocks = [ _format_item_block(lang, it, i+1+(page-1)*PUB_PER_PAGE) for i, it in enumerate(view) ]
        text = header + "\n\n" + "\n\n".join(blocks)

    kb = _kb_public_list(lang, page, total_pages, view)

    if isinstance(target, Message):
        return await target.answer(text, reply_markup=kb, disable_web_page_preview=True)
    else:
        return await target.edit_text(text, reply_markup=kb, disable_web_page_preview=True)

# زر الواجهة لفتح القائمة العامة
@router.callback_query(F.data == "trusted_suppliers")
async def open_trusted_suppliers(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await _render_public_list(cb.message, lang, 1)
    await cb.answer()

# ترقيم القائمة العامة
@router.callback_query(F.data.regexp(r"^td:list:\d+$"))
async def td_list_cb(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    page = int(cb.data.split(":")[2])
    await _render_public_list(cb.message, lang, page)
    await cb.answer()

# ================= إدارة الأدمن =================
PER_PAGE = 5

def _iter_cards():
    for name in os.listdir(SUP_DIR):
        up = os.path.join(SUP_DIR, name, "pub.json")
        if os.path.isfile(up):
            try:
                with open(up, "r", encoding="utf-8") as f:
                    d = json.load(f)
                d.setdefault("languages","")
                d.setdefault("whatsapp","")
                yield d
            except Exception:
                continue

def _by_status(status: str):
    if status == "banned":
        ids = _load_ban()
        return [{"user_id": i, "status": "banned"} for i in sorted(ids)]
    items = []
    for d in _iter_cards():
        if status == "published":
            if d.get("status") == "approved" and d.get("visible"):
                items.append(d)
        elif d.get("status") == status:
            items.append(d)
    items.sort(key=lambda x: x.get("updated_at",""), reverse=True)
    return items

def _kb_admin_list(lang: str, status: str, page: int, total_pages: int, items: list[dict]) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text=t(lang,"sd_btn_published").format(n=len(_by_status("published"))), callback_data="sd:list:published:1"),
        InlineKeyboardButton(text=t(lang,"sd_btn_pending").format(n=len(_by_status("pending"))), callback_data="sd:list:pending:1"),
        InlineKeyboardButton(text=t(lang,"sd_btn_hidden").format(n=len(_by_status("hidden"))), callback_data="sd:list:hidden:1"),
        InlineKeyboardButton(text=t(lang,"sd_btn_banned").format(n=len(_by_status("banned"))), callback_data="sd:list:banned:1"),
    ]]
    for it in items:
        uid = it.get("user_id")
        title = it.get("name") or f"UID {uid}"
        rows.append([InlineKeyboardButton(text=f"{title} (#{uid})", callback_data=f"sd:view:{uid}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"sd:list:{status}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"sd:list:{status}:{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _render_admin_list(target, lang: str, status: str, page: int):
    all_items = _by_status(status)
    total_pages = max(1, math.ceil(len(all_items)/PER_PAGE))
    page = max(1, min(page, total_pages))
    page_items = all_items[(page-1)*PER_PAGE: (page)*PER_PAGE]

    header = f"📇 <b>{t(lang,'sd_title')}</b>\n{t(lang,'sd_current_status')}: <b>{status}</b>"
    if not all_items:
        header += f"\n\n{t(lang,'sd_no_results')}"
    kb = _kb_admin_list(lang, status, page, total_pages, page_items)

    if isinstance(target, Message):
        return await target.answer(header, reply_markup=kb, disable_web_page_preview=True)
    else:
        return await target.edit_text(header, reply_markup=kb, disable_web_page_preview=True)

@router.message(Command("supdir"))
async def cmd_supdir(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    await _render_admin_list(msg, lang, "pending", 1)

@router.callback_query(F.data.regexp(r"^sd:list:(published|pending|hidden|banned):\d+$"))
async def sd_list_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    _, _, status, page_s = cb.data.split(":")
    await _render_admin_list(cb.message, lang, status, int(page_s))
    await cb.answer()

@router.callback_query(F.data.regexp(r"^sd:view:\d+$"))
async def sd_view_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    uid = int(cb.data.split(":")[2])

    d = _load_pub(uid)
    text = _card(lang, d)

    rows = [[
        InlineKeyboardButton(text=_L(lang,"spub_adm_approve","Approve & publish ✅","اعتماد ونشر ✅"), callback_data=f"spubadm:approve:{uid}"),
        InlineKeyboardButton(text=_L(lang,"spub_adm_hide","Hide ⛔","إخفاء ⛔"), callback_data=f"spubadm:hide:{uid}"),
    ],[
        InlineKeyboardButton(text=_L(lang,"spub_adm_delete","Delete 🗑️","حذف 🗑️"), callback_data=f"spubadm:delete:{uid}"),
        InlineKeyboardButton(text=_L(lang,"spub_adm_ban","Ban 🚫","حظر 🚫"), callback_data=f"spubadm:ban:{uid}"),
        InlineKeyboardButton(text=_L(lang,"spub_adm_unban","Unban ✅","إلغاء الحظر ✅"), callback_data=f"spubadm:unban:{uid}"),
    ],[
        InlineKeyboardButton(text=_L(lang,"spub_adm_demote","Demote supplier ⬇️","إلغاء مورد ⬇️"), callback_data=f"spubadm:demote:{uid}"),
    ],[
        InlineKeyboardButton(text="« Back", callback_data="sd:list:pending:1"),
    ]]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), disable_web_page_preview=True)
    await cb.answer()

# إجراءات الأدمن
@router.callback_query(F.data.regexp(r"^spubadm:(approve|hide|delete|ban|unban|demote):\d+$"))
async def spub_admin_actions(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _, action, uid_s = cb.data.split(":")
    uid = int(uid_s)
    lang = get_user_lang(cb.from_user.id) or "en"

    d = _load_pub(uid)
    changed = False

    if action == "approve":
        d["status"] = "approved"; d["visible"] = True; changed = True
        try: await cb.message.bot.send_message(uid, _L(lang,"spub_published_ok","Your card is now published ✅","تم نشر بطاقتك في الدليل ✅"))
        except: pass

    elif action == "hide":
        d["status"] = "hidden"; d["visible"] = False; changed = True
        try: await cb.message.bot.send_message(uid, _L(lang,"spub_hidden_ok","Your card was hidden.","تم إخفاء بطاقتك."))
        except: pass

    elif action == "delete":
        _delete_pub(uid); changed = True
        try: await cb.message.bot.send_message(uid, _L(lang,"sd_user_deleted","Your public card was removed.","تم حذف بطاقتك العامة."))
        except: pass
        await cb.answer(_L(lang,"sd_admin_deleted_ok","Deleted.","تم الحذف."))
        _rebuild_public_directory()
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass
        return

    elif action == "ban":
        _ban(uid)
        d["status"] = "hidden"; d["visible"] = False; changed = True
        if _set_supplier:
            try: _set_supplier(uid, False)
            except Exception: pass
        try: await cb.message.bot.send_message(uid, _L(lang,"sd_user_banned_notice","You were banned from publishing.","تم حظرك من النشر."))
        except: pass
        await cb.answer(_L(lang,"sd_admin_banned_ok","Banned.","تم الحظر."))

    elif action == "unban":
        _unban(uid)
        await cb.answer(_L(lang,"sd_admin_unbanned_ok","Unbanned.","تم إلغاء الحظر."))
        try: await cb.message.bot.send_message(uid, _L(lang,"sd_user_unbanned_notice","Your publishing ban was removed.","تم إلغاء حظر النشر."))
        except: pass

    elif action == "demote":
        if _set_supplier:
            try: _set_supplier(uid, False)
            except Exception: pass
        await cb.answer(_L(lang,"sd_admin_demoted_ok","Supplier access removed.","تم إلغاء اعتماد المورد."))

    if changed:
        _save_pub(uid, d)
        _rebuild_public_directory()
        try: await cb.message.edit_text(_card(lang, d), disable_web_page_preview=True)
        except: pass
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass

# ================= أزرار عامة مساعدة =================
@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()
