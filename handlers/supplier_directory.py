# handlers/supplier_directory.py
from __future__ import annotations

import os, json, math, logging, html
from datetime import datetime
from typing import Tuple, List, Optional
from importlib import import_module

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from lang import t, get_user_lang
from handlers.live_chat import LiveChat  # لمنع التضارب مع الدردشة الحية

ALLOW_SELF_RATE = (os.getenv("ALLOW_SELF_RATE", "0") == "1")

# هل المستخدم مورّد؟
try:
    from utils.suppliers import is_supplier as _is_supplier
    from utils.suppliers import set_supplier as _set_supplier
except Exception:
    _is_supplier = None
    _set_supplier = None

log = logging.getLogger(__name__)
router = Router(name="supplier_directory")

# ⛔️ اشتغل بالخاص فقط + عطّل أثناء جلسة لايف شات
router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
router.callback_query.filter(F.message.chat.type == "private", ~StateFilter(LiveChat.active))

# ===== إعدادات ومسارات =====
DATA_DIR = "data"
SUP_DIR = os.path.join(DATA_DIR, "suppliers")
PUB_FILE = os.path.join(DATA_DIR, "public_suppliers.json")
BAN_FILE = os.path.join(DATA_DIR, "supplier_banlist.json")
os.makedirs(SUP_DIR, exist_ok=True)

# تقييم بايزي
RATING_M = int(os.getenv("SUPPLIERS_RATING_M", "6"))
DEFAULT_GLOBAL_MEAN = float(os.getenv("SUPPLIERS_GLOBAL_MEAN", "4.0"))

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123,8371697148]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _now_iso() -> str:
    return datetime.utcnow().isoformat()

def _L(lang: str, key: str, en: str, ar: str) -> str:
    v = t(lang, key)
    if isinstance(v, str) and v and v != key:
        return v
    return ar if (lang or "ar").startswith("ar") else en

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

def _ratings_path(uid: int) -> str:
    return os.path.join(_user_folder(uid), "ratings.json")

def _load_pub(uid: int) -> dict:
    try:
        with open(_pub_path(uid), "r", encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("languages", "")
                d.setdefault("whatsapp", "")
                return d
    except Exception:
        pass
    return {
        "user_id": uid,
        "username": "",
        "name": "",
        "country": "",
        "languages": "",
        "contact": "",     # @user أو رقم
        "whatsapp": "",
        "channel": "",
        "bio": "",
        "status": "draft", # draft|pending|approved|hidden
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

# ================= تقييمات =================
def _load_ratings(uid: int) -> dict:
    p = _ratings_path(uid)
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("by"), dict):
                return d
    except Exception:
        pass
    return {"by": {}}

def _save_ratings(uid: int, d: dict):
    p = _ratings_path(uid)
    d.setdefault("by", {})
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def _aggregate_rating(uid: int) -> Tuple[int, int, float]:
    d = _load_ratings(uid)
    items = list((d.get("by") or {}).values())
    stars = [int(x.get("stars", 0)) for x in items if isinstance(x, dict) and str(x.get("stars","")).isdigit()]
    c = len(stars); s = sum(stars)
    avg = (s / c) if c else 0.0
    return s, c, avg

def _all_ratings_stats() -> Tuple[int, int, float]:
    total_sum = 0; total_cnt = 0
    try:
        for name in os.listdir(SUP_DIR):
            if not name.isdigit(): continue
            s, c, _ = _aggregate_rating(int(name))
            total_sum += s; total_cnt += c
    except Exception:
        pass
    if total_cnt == 0:
        return 0, 0, DEFAULT_GLOBAL_MEAN
    return total_sum, total_cnt, total_sum / total_cnt

def _bayesian_score(avg: float, cnt: int, C: float, m: int) -> float:
    return (C * m + avg * cnt) / (m + cnt) if (m + cnt) else C

def _band(avg: float) -> str:
    if avg >= 4.5:  return "excellent"
    if avg >= 3.5:  return "good"
    if avg >= 2.5:  return "average"
    if avg >= 1.5:  return "weak"
    return "poor"

def _band_label(lang: str, code: str) -> str:
    mapping = {
        "excellent": _L(lang, "rate.excellent", "Excellent", "ممتاز"),
        "good":      _L(lang, "rate.good",      "Good",      "جيّد"),
        "average":   _L(lang, "rate.average",   "Average",   "متوسط"),
        "weak":      _L(lang, "rate.weak",      "Weak",      "ضعيف"),
        "poor":      _L(lang, "rate.poor",      "Poor",      "سيّئ"),
    }
    return mapping.get(code, "-")

def _stars_bar(avg: float, /) -> str:
    filled = int(round(avg))
    filled = max(0, min(5, filled))
    return "★" * filled + "☆" * (5 - filled)

# ================= بناء وتجديد الدليل العام =================
def _rebuild_public_directory():
    items_tmp: List[dict] = []
    for name in os.listdir(SUP_DIR):
        up = os.path.join(SUP_DIR, name, "pub.json")
        if not os.path.isfile(up):
            continue
        try:
            with open(up, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("status") == "approved" and d.get("visible"):
                uid = int(d.get("user_id"))
                s, c, avg = _aggregate_rating(uid)
                items_tmp.append({
                    "user_id": uid,
                    "username": d.get("username"),
                    "name": d.get("name"),
                    "country": d.get("country"),
                    "languages": d.get("languages", ""),
                    "contact": d.get("contact"),
                    "whatsapp": d.get("whatsapp", ""),
                    "channel": d.get("channel"),
                    "bio": d.get("bio"),
                    "verified": True,
                    "updated_at": d.get("updated_at"),
                    "rating_raw_sum": s,
                    "rating_raw_count": c,
                    "rating_raw_avg": avg,
                })
        except Exception:
            continue

    total_sum, total_cnt, C = _all_ratings_stats()
    m = RATING_M
    for it in items_tmp:
        c = int(it["rating_raw_count"]); avg = float(it["rating_raw_avg"])
        b = _bayesian_score(avg, c, C, m)
        it["rating"] = {
            "sum": it["rating_raw_sum"],
            "count": c,
            "avg": round(avg, 2),
            "bayes": round(b, 3),
            "band": _band(avg),
        }

    items_tmp.sort(key=lambda x: (-x.get("rating", {}).get("bayes", 0.0),
                                  -x.get("rating", {}).get("count", 0),
                                  (x.get("updated_at") or "")),
                   reverse=False)

    items: List[dict] = [{k: v for k, v in it.items() if not k.startswith("rating_raw_")} for it in items_tmp]
    with open(PUB_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

# ================= حالات التعديل =================
class PubStates(StatesGroup):
    name = State()
    country = State()
    languages = State()
    contact = State()
    whatsapp = State()
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
    name = html.escape(d.get("name", "") or "")
    country = html.escape(d.get("country", "") or "")
    languages = html.escape((d.get("languages") or "").strip())
    contact = html.escape(d.get("contact", "") or "")
    whatsapp = html.escape((d.get("whatsapp") or "").strip())
    channel = html.escape((d.get("channel") or "").strip())
    bio = html.escape((d.get("bio") or "").strip())

    lines = [
        f"🧾 <b>{_L(lang,'spub_title','Supplier public card','بطاقة المورد العامة')}</b>",
        f"{_L(lang,'spub_field_name','Name','الاسم')}: <b>{name}</b>",
        f"{_L(lang,'spub_field_country','Country','الدولة')}: <b>{country}</b>",
    ]
    if languages:
        lines.append(f"{_L(lang,'spub_field_languages','Languages','اللغات')}: <b>{languages}</b>")
    lines += [f"{_L(lang,'spub_field_contact','Telegram','تيليجرام')}: <code>{contact}</code>"]
    if whatsapp:
        lines.append(f"{_L(lang,'spub_field_whatsapp','WhatsApp','واتساب')}: <code>{whatsapp}</code>")
    lines.append(f"{_L(lang,'spub_field_channel','Channel','القناة/المجموعة')}: <code>{channel}</code>")

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

    await msg.answer(
        _card(lang, d),
        reply_markup=_kb_supplier(lang, d.get("status","draft"), d.get("visible", False)),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

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
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        await cb.message.answer(
            _card(lang, d),
            reply_markup=_kb_supplier(lang, d.get("status","draft"), d.get("visible", False)),
            parse_mode=ParseMode.HTML,
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

# ✅ المهم: استخدم StateFilter بدل كتابة PubStates مباشرة
@router.message(StateFilter(
    PubStates.name, PubStates.country, PubStates.languages,
    PubStates.contact, PubStates.whatsapp, PubStates.channel, PubStates.bio
))
async def spub_save_field(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    field = (await state.get_data()).get("spub_field")
    value = (msg.text or "").strip()

    d = _load_pub(msg.from_user.id)
    # حماية بسيطة لو صار field = None لسبب ما
    if not field:
        await state.clear()
        return await msg.answer(_L(lang, "spub_err_try_again", "Something went wrong. Try again.", "حدث خطأ. حاول مرة أخرى."))

    d[field] = value
    _save_pub(msg.from_user.id, d)

    if d.get("status") == "approved" and d.get("visible"):
        _rebuild_public_directory()

    await state.clear()
    await msg.answer(_L(lang, "spub_saved", "Saved ✅", "تم الحفظ ✅"))
    await msg.answer(
        _card(lang, d),
        reply_markup=_kb_supplier(lang, d.get("status","draft"), d.get("visible", False)),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
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

    d["status"] = "pending"; d["visible"] = False
    d["username"] = cb.from_user.username or d.get("username","")
    _save_pub(cb.from_user.id, d)

    await cb.message.edit_text(
        _card(lang, d),
        reply_markup=_kb_supplier(lang, d["status"], d["visible"]),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    await cb.answer(_L(lang, "spub_submitted_ok", "Sent for admin review ✅", "تم الإرسال للمراجعة ✅"))

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
    # إرسال إشعار للأدمنين
    for aid in ADMIN_IDS:
        try:
            await cb.message.bot.send_message(aid, f"🆕 <b>Supplier directory request</b>\nUser: <code>{cb.from_user.id}</code> @{cb.from_user.username or ''}\n\n{_card(lang, d)}",
                                              reply_markup=kb_adm, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass

# إخفاء ذاتي للمورد
@router.callback_query(F.data == "spub:unpublish")
async def spub_unpublish(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    d = _load_pub(cb.from_user.id)
    d["status"] = "hidden"; d["visible"] = False
    _save_pub(cb.from_user.id, d)
    _rebuild_public_directory()
    await cb.message.edit_text(
        _card(lang, d),
        reply_markup=_kb_supplier(lang, d["status"], d["visible"]),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    await cb.answer(_L(lang, "spub_hidden_ok", "Unpublished.", "تم الإخفاء."))

# ================= واجهة المستخدم العامة (قائمة + بروفايل + تقييم) =================
PUB_PER_PAGE = 6

def _read_public_items():
    try:
        with open(PUB_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        items = []
    items.sort(key=lambda x: (-float(((x.get("rating") or {}).get("bayes")) or 0.0),
                              -int(((x.get("rating") or {}).get("count")) or 0),
                              x.get("updated_at","")), reverse=False)
    return items

def _shorten(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"

def _btn_text_with_country(it: dict, lang: str) -> str:
    uid = it.get("user_id")
    name = _shorten(it.get("name") or f"#{uid}", 22)
    country = _shorten(it.get("country") or "", 18)
    rating = it.get("rating") or {}
    avg = float(rating.get("avg") or 0.0)
    cnt = int(rating.get("count") or 0)
    star = f" ⭐{avg:.1f}" if cnt > 0 else " ⭐—"
    return (f"• {name}{star}  —  🌍 {country}" if country else f"• {name}{star}")

def _kb_public_list(lang: str, page: int, total_pages: int, items: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for it in items:
        uid = it.get("user_id")
        text = _btn_text_with_country(it, lang)
        rows.append([InlineKeyboardButton(text=text, callback_data=f"td:view:{uid}:{page}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"td:list:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"td:list:{page+1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="td:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _profile_text(lang: str, it: dict, viewer_id: Optional[int] = None) -> str:
    name = html.escape(it.get("name", "") or "")
    country = html.escape((it.get("country") or "").strip())
    languages = html.escape((it.get("languages") or "").strip())
    bio = html.escape((it.get("bio") or "").strip())
    rating = (it.get("rating") or {})
    avg = float(rating.get("avg") or 0.0)
    cnt = int(rating.get("count") or 0)
    band = _band_label(lang, (rating.get("band") or _band(avg)))

    lines = [f"👤 <b>{name}</b> {'✅' if it.get('verified') else ''}"]
    if country:   lines.append(f"🌍 { _L(lang,'spub_field_country','Country','الدولة') }: {country}")
    if languages: lines.append(f"🗣 { _L(lang,'spub_field_languages','Languages','اللغات') }: {languages}")
    if bio:       lines.append(f"📝 {bio}")

    if cnt:
        lines.append(f"\n{_L(lang,'rating','Rating','التقييم')}: {_stars_bar(avg)}  {avg:.1f}/5  ({cnt}) — {band}")
    else:
        lines.append(f"\n{_L(lang,'rating.none','No ratings yet','لا تقييمات بعد')}")

    if viewer_id:
        by = (_load_ratings(int(it.get("user_id"))).get("by") or {})
        my = by.get(str(viewer_id))
        if my:
            lines.append(_L(lang, "rating.yours", "Your rating:", "تقييمك:") + f" {my.get('stars')} ⭐")

    lines.append("")
    lines.append(_L(lang, "td_profile_hint",
                    "Use the buttons below to contact or rate this supplier.",
                    "استخدم الأزرار بالأسفل للتواصل مع هذا المورد أو تقييمه."))
    return "\n".join(lines)

def _kb_profile(lang: str, it: dict, page: int, viewer_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    # صفّ تقييم النجوم
    uid = int(it.get("user_id", 0))
    if viewer_id != uid:
        rows.append([
            InlineKeyboardButton(text="⭐1", callback_data=f"td:rate:{uid}:1:{page}"),
            InlineKeyboardButton(text="⭐2", callback_data=f"td:rate:{uid}:2:{page}"),
            InlineKeyboardButton(text="⭐3", callback_data=f"td:rate:{uid}:3:{page}"),
            InlineKeyboardButton(text="⭐4", callback_data=f"td:rate:{uid}:4:{page}"),
            InlineKeyboardButton(text="⭐5", callback_data=f"td:rate:{uid}:5:{page}"),
        ])
        by = (_load_ratings(uid).get("by") or {})
        if str(viewer_id) in by:
            rows.append([InlineKeyboardButton(text=_L(lang, "rating.remove", "Remove my rating", "حذف تقييمي"),
                                              callback_data=f"td:rate_del:{uid}:{page}")])

    # أزرار التواصل
    contact  = (it.get("contact")  or "").strip()
    whatsapp = (it.get("whatsapp") or "").strip()
    channel  = (it.get("channel")  or "").strip()

    line: list[InlineKeyboardButton] = []
    if contact:
        if contact.startswith("@"):
            line.append(InlineKeyboardButton(text=_L(lang, "td_contact", "Contact", "مراسلة"),
                                             url=f"https://t.me/{contact[1:]}"))
        else:
            line.append(InlineKeyboardButton(text=_L(lang, "td_contact", "Contact", "مراسلة"),
                                             url=f"tg://user?id={uid}"))
    if whatsapp:
        wurl = whatsapp if whatsapp.startswith("http") else f"https://wa.me/{whatsapp.lstrip('+').replace(' ', '')}"
        line.append(InlineKeyboardButton(text=_L(lang, "td_whatsapp", "WhatsApp", "واتساب"), url=wurl))
    if channel:
        url = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
        line.append(InlineKeyboardButton(text=_L(lang, "td_channel", "Channel", "القناة"), url=url))
    if line:
        rows.append(line)

    rows.append([InlineKeyboardButton(text=_L(lang, "td_back_list", "« Back to list", "« الرجوع للقائمة"),
                                      callback_data=f"td:list:{page}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="td:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _render_public_list(target, lang: str, page: int):
    items = _read_public_items()
    total_pages = max(1, math.ceil(len(items)/PUB_PER_PAGE))
    page = max(1, min(page, total_pages))
    view = items[(page-1)*PUB_PER_PAGE : page*PUB_PER_PAGE]

    header = f"📇 <b>{_L(lang,'td_title','Trusted suppliers','الموردون الموثوقون')}</b>\n"
    if not items:
        header += "\n" + _L(lang,"td_empty","No suppliers published yet.","لا يوجد موردون منشورون حالياً.")
        text = header
    else:
        header += _L(lang,"td_pick_supplier","Choose a supplier from the buttons below to view their profile.","اختر مورّدًا من الأزرار بالأسفل لعرض ملفه.")
        text = header

    kb = _kb_public_list(lang, page, total_pages, view)

    if isinstance(target, Message):
        return await target.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        return await target.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@router.callback_query(F.data == "td:home")
async def td_home_cb(cb: CallbackQuery):
    """
    رجوع للقائمة الرئيسية مع احترام لغة المستخدم + Fallback آمن.
    """
    # احصل لغة المستخدم
    try:
        from lang import get_user_lang as _get_user_lang, t as _t
    except Exception:
        _get_user_lang = lambda _uid: "en"
        _t = lambda _lang, _key: _key

    lang = (_get_user_lang(cb.from_user.id) or "en").lower()
    is_ar = lang.startswith("ar")

    def L(ar: str, en: str) -> str:
        return ar if is_ar else en

    # حاول حذف الرسالة الحالية (لو قابلة للحذف)
    try:
        await cb.message.delete()
    except Exception:
        pass

    # جرّب مرشّحات/هاندلرز بيتك المختلفة لاستدعاء الواجهة
    from importlib import import_module
    candidates = [
        ("handlers.start", "cmd_start"),
        ("handlers.start", "start"),
        ("handlers.start", "open_home"),
        ("handlers.home_menu", "cmd_start"),
        ("handlers.home_menu", "open_home"),
        ("handlers.home_hero", "open_home"),
        ("handlers.persistent_menu", "open_menu"),
        ("handlers.persistent_menu", "show_menu"),
        ("handlers.persistent_menu", "main_menu"),
    ]

    for mod_name, fn_name in candidates:
        try:
            mod = import_module(mod_name)
            fn = getattr(mod, fn_name, None)
            if not callable(fn):
                continue

            # المحاولة 1: الاستدعاء التقليدي
            try:
                await fn(cb.message)
                await cb.answer(L("تم ✔️", "Done ✔️"))
                return
            except TypeError:
                pass

            # المحاولة 2: بعض المشاريع تقبل lang أو locale
            try:
                await fn(cb.message, lang=lang)
                await cb.answer(L("تم ✔️", "Done ✔️"))
                return
            except TypeError:
                try:
                    await fn(cb.message, locale=lang)
                    await cb.answer(L("تم ✔️", "Done ✔️"))
                    return
                except TypeError:
                    # غير مدعوم — جرّب التالي
                    continue
        except Exception:
            continue

    # Fallback مترجم لو ما لقينا أي هاندلر
    try:
        await cb.message.answer(
            L("✅ تم الرجوع للقائمة. أرسل /start لإظهار الواجهة.",
              "✅ Back to the menu. Send /start to open the home screen.")
        )
    except Exception:
        pass

    await cb.answer(L("تم ✔️", "Done ✔️"))

# زر الواجهة لفتح القائمة العامة
@router.callback_query(F.data == "trusted_suppliers")
async def open_trusted_suppliers(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        _rebuild_public_directory()
    except Exception:
        pass
    await _render_public_list(cb.message, lang, 1)
    await cb.answer()

# ترقيم القائمة العامة
@router.callback_query(F.data.regexp(r"^td:list(?::\d+)?$"))
async def td_list_cb(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    parts = (cb.data or "").split(":")
    page = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
    await _render_public_list(cb.message, lang, page)
    await cb.answer()

# عرض بروفايل مورد
@router.callback_query(F.data.regexp(r"^td:view:\d+(:\d+)?$"))
async def td_view_cb(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    parts = cb.data.split(":")
    uid = int(parts[2])
    page = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 1

    items = _read_public_items()
    it = next((x for x in items if int(x.get("user_id", 0)) == uid), None)
    if not it:
        return await cb.answer(_L(lang, "td_not_found", "Supplier not found.", "المورد غير موجود."), show_alert=True)

    text = _profile_text(lang, it, viewer_id=cb.from_user.id)
    kb = _kb_profile(lang, it, page, viewer_id=cb.from_user.id)

    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()

# ===== تقييم: إضافة/حذف =====
@router.callback_query(F.data.regexp(r"^td:rate:\d+:(1|2|3|4|5)(:\d+)?$"))
async def td_rate_set(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    parts = cb.data.split(":")
    uid = int(parts[2]); stars = int(parts[3]); page = int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else 1

    if not ALLOW_SELF_RATE and uid == cb.from_user.id:
        return await cb.answer(_L(lang, "rating.self", "You cannot rate yourself.", "لا يمكنك تقييم نفسك."), show_alert=True)

    items = _read_public_items()
    if not any(int(x.get("user_id",0)) == uid for x in items):
        return await cb.answer(_L(lang, "td_not_found", "Supplier not found.", "المورد غير موجود."), show_alert=True)

    d = _load_ratings(uid)
    by = d.get("by") or {}
    by[str(cb.from_user.id)] = {"stars": int(stars), "ts": _now_iso()}
    d["by"] = by
    _save_ratings(uid, d)
    _rebuild_public_directory()

    try:
        await td_view_cb(CallbackQuery.model_construct(data=f"td:view:{uid}:{page}", from_user=cb.from_user, message=cb.message))
    except Exception:
        pass
    await cb.answer(_L(lang, "rating.saved", "Rating saved ✅", "تم حفظ التقييم ✅"))

@router.callback_query(F.data.regexp(r"^td:rate_del:\d+(:\d+)?$"))
async def td_rate_del(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    parts = cb.data.split(":")
    uid = int(parts[2]); page = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 1

    d = _load_ratings(uid)
    by = d.get("by") or {}
    if str(cb.from_user.id) in by:
        by.pop(str(cb.from_user.id), None)
        d["by"] = by
        _save_ratings(uid, d)
        _rebuild_public_directory()
        try:
            await td_view_cb(CallbackQuery.model_construct(data=f"td:view:{uid}:{page}", from_user=cb.from_user, message=cb.message))
        except Exception:
            pass
        return await cb.answer(_L(lang, "rating.removed", "Your rating was removed.", "تم حذف تقييمك."))
    await cb.answer("OK")

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

    header = f"📇 <b>{t(lang,'sd_title')}</b>\n{t(lang,'sd_current_status')}: <b>{html.escape(status)}</b>"
    if not all_items:
        header += f"\n\n{t(lang,'sd_no_results')}"
    kb = _kb_admin_list(lang, status, page, total_pages, page_items)

    if isinstance(target, Message):
        return await target.answer(header, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        return await target.edit_text(header, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@router.message(Command("supdir"))
async def cmd_supdir(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    await _render_admin_list(msg, lang, "pending", 1)

@router.callback_query(F.data.regexp(r"^sd:list:(published|pending|hidden|banned):\d+$"))
async def sd_list_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_L("en","admins_only","Admins only.","خاص بالأدمن."), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    _, _, status, page_s = cb.data.split(":")
    await _render_admin_list(cb.message, lang, status, int(page_s))
    await cb.answer()

@router.callback_query(F.data.regexp(r"^sd:view:\d+$"))
async def sd_view_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_L("en","admins_only","Admins only.","خاص بالأدمن."), show_alert=True)
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
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^spubadm:(approve|hide|delete|ban|unban|demote):\d+$"))
async def spub_admin_actions(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_L("en","admins_only","Admins only.","خاص بالأدمن."), show_alert=True)
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
        _ban(uid); d["status"] = "hidden"; d["visible"] = False; changed = True
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
        try: await cb.message.edit_text(_card(lang, d), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except: pass
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass

# ================= أزرار عامة مساعدة =================
@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()
