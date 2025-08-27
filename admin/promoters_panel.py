# admin/promoters_panel.py
from __future__ import annotations

import os, json, time, logging
from pathlib import Path
from typing import Dict, Any, List

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode

from lang import t, get_user_lang

router = Router(name="promoters_panel")
log = logging.getLogger(__name__)

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = DATA_DIR / "promoters.json"   # مخزن المروّجين/الطلبات

# ===== صلاحيات الأدمن =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# لغة المستخدم (افتراضي EN لتفادي ظهور العربية لمن لم تُحفظ لغته)
def L(uid: int) -> str:
    return get_user_lang(uid) or "en"

def _now() -> int:
    return int(time.time())

# ========= I/O =========
def _load() -> Dict[str, Any]:
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"users": {}, "settings": {"daily_limit": 5}}

def _save(d: Dict[str, Any]):
    STORE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def _get_user(d, uid: str):
    u = d.setdefault("users", {}).setdefault(uid, {})
    u.setdefault("status", "pending")
    u.setdefault("submitted_at", _now())
    return u

# ========= ترجمة مرنة =========
def _safe_t(lang: str, key: str) -> str | None:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    return None

def _tf(lang: str, key: str, *fallbacks: str) -> str:
    """
    يحاول الترجمة بـ lang ثم en ثم ar. إن لم يجد:
      - إن مرّرنا بديلين (ar, en) سيرجع المناسب حسب اللغة.
      - إن مرّرنا بديلًا واحدًا سيُستخدم للجميع.
    """
    txt = _safe_t(lang, key) or _safe_t("en", key) or _safe_t("ar", key)
    if txt:
        return txt

    ar_fb = en_fb = generic = None
    if len(fallbacks) >= 2:
        ar_fb, en_fb = fallbacks[0], fallbacks[1]
        if len(fallbacks) >= 3:
            generic = fallbacks[2]
    elif len(fallbacks) == 1:
        generic = fallbacks[0]

    if lang.startswith("ar") and ar_fb:
        return ar_fb
    if lang.startswith("en") and en_fb:
        return en_fb
    for v in (en_fb, ar_fb, generic):
        if v:
            return v
    return key

async def _safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

async def _notify_user(cb: CallbackQuery, uid: int, text: str):
    try:
        await cb.bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass

# ========= إحصائيات =========
def _stats(d: Dict[str, Any]) -> Dict[str, int]:
    s = {"pending":0,"approved":0,"rejected":0,"on_hold":0,"more_info":0,"total":0,"banned":0,"promoters":0}
    now = _now()
    for u in d.get("users", {}).values():
        st = u.get("status")
        s["total"] += 1
        if st in s: s[st] += 1
        if u.get("banned_until",0) and u["banned_until"] > now: s["banned"] += 1
        if u.get("is_promoter"): s["promoters"] += 1
    return s

def _panel_text(lang: str) -> str:
    d = _load(); s = _stats(d); dl = int(d.get("settings", {}).get("daily_limit", 5))
    return (
        f"📊 <b>{_tf(lang,'promadm.title','إدارة المروّجين','Promoters Admin')}</b>\n\n"
        f"• {_tf(lang,'promadm.stats.pending','قيد المراجعة','Pending')}: <b>{s['pending']}</b>\n"
        f"• {_tf(lang,'promadm.stats.approved','الموافق عليهم','Approved')}: <b>{s['approved']}</b>\n"
        f"• {_tf(lang,'promadm.stats.rejected','المرفوضون','Rejected')}: <b>{s['rejected']}</b>\n"
        f"• {_tf(lang,'promadm.stats.hold','معلّق','On hold')}: <b>{s['on_hold']}</b>\n"
        f"• {_tf(lang,'promadm.stats.more','معلومات إضافية','More info')}: <b>{s['more_info']}</b>\n"
        f"• {_tf(lang,'promadm.stats.banned','محظورون (نشط)','Banned (active)')}: <b>{s['banned']}</b>\n"
        f"• {_tf(lang,'promadm.stats.promoters','المروّجون (مفعل)','Active promoters')}: <b>{s['promoters']}</b>\n"
        f"• {_tf(lang,'promadm.stats.total','الإجمالي','Total')}: <b>{s['total']}</b>\n\n"
        f"⚙️ {_tf(lang,'promadm.daily_limit','الحد اليومي للطلبات','Daily application limit')}: <code>{dl}</code>\n"
    )

def _panel_kb(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📥 " + _tf(lang,"promadm.btn.pending","الطلبات المعلّقة","Pending requests"), callback_data="promadm:list:pending:1")],
        [
            InlineKeyboardButton(text="✅ " + _tf(lang,"promadm.btn.approved","الموافق عليهم","Approved"), callback_data="promadm:list:approved:1"),
            InlineKeyboardButton(text="❌ " + _tf(lang,"promadm.btn.rejected","المرفوضون","Rejected"), callback_data="promadm:list:rejected:1"),
        ],
        [
            InlineKeyboardButton(text="⏸ " + _tf(lang,"promadm.btn.hold","المعلّق","On hold"), callback_data="promadm:list:on_hold:1"),
            InlineKeyboardButton(text="✍️ " + _tf(lang,"promadm.btn.more","معلومات إضافية","More info"), callback_data="promadm:list:more_info:1"),
        ],
        [
            InlineKeyboardButton(text="🚫 " + _tf(lang,"promadm.btn.banned","المحظورون (نشط)","Banned (active)"), callback_data="promadm:list:banned:1"),
            InlineKeyboardButton(text="📣 " + _tf(lang,"promadm.btn.box","بوكس المروّجين","Promoters box"), callback_data="promadm:box:1"),
        ],
        [InlineKeyboardButton(text="🔎 " + _tf(lang,"promadm.btn.search","بحث ID","Search by ID"), callback_data="promadm:search")],
        [InlineKeyboardButton(text="⚙️ " + _tf(lang,"promadm.btn.settings","الإعدادات","Settings"), callback_data="promadm:settings")],
        [InlineKeyboardButton(text="🔄 " + _tf(lang,"promadm.btn.refresh","تحديث","Refresh"), callback_data="promadm:open")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع","Back"), callback_data="ah:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == "promadm:open")
async def open_panel(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang))
    await cb.answer()

# ========= القوائم مع صفحات =========
PAGE_SIZE = 10

def _filter_ids(status: str) -> List[str]:
    d = _load(); now = _now()
    users = d.get("users", {})
    ids = []
    for uid, u in users.items():
        st = u.get("status")
        if status == "banned":
            if u.get("banned_until",0) > now: ids.append(uid)
        elif status == "approved":
            if st == "approved": ids.append(uid)
        elif status == "rejected":
            if st == "rejected": ids.append(uid)
        elif status == "on_hold":
            if st == "on_hold": ids.append(uid)
        elif status == "more_info":
            if st == "more_info": ids.append(uid)
        elif status == "pending":
            if st == "pending": ids.append(uid)
        elif status == "promoters":
            if u.get("is_promoter"): ids.append(uid)
        else:
            ids.append(uid)
    ids.sort(key=lambda x: users[x].get("submitted_at",0), reverse=True)
    return ids

def _page(ids: List[str], page: int):
    start = (page-1)*PAGE_SIZE
    return ids[start:start+PAGE_SIZE], len(ids)

def _list_kb(lang: str, ids: List[str], page: int, total: int, list_key: str, back_cb: str) -> InlineKeyboardMarkup:
    rows = []
    for uid in ids:
        rows.append([InlineKeyboardButton(text=f"{uid}", callback_data=f"promadm:view:{uid}")])
    if total > PAGE_SIZE:
        pages = (total + PAGE_SIZE - 1)//PAGE_SIZE
        nav = []
        if page > 1: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"promadm:list:{list_key}:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="promadm:noop"))
        if page < pages: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"promadm:list:{list_key}:{page+1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع","Back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data.startswith("promadm:list:"))
async def show_list(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    _, _, list_key, page_s = cb.data.split(":")
    page = int(page_s)
    ids_full = _filter_ids(list_key)
    ids, total = _page(ids_full, page)
    title_map = {
        "pending": "📥 " + _tf(lang,"promadm.pending_title","الطلبات المعلّقة","Pending requests"),
        "approved":"✅ " + _tf(lang,"promadm.approved_title","الموافق عليهم","Approved"),
        "rejected":"❌ " + _tf(lang,"promadm.rejected_title","المرفوضون","Rejected"),
        "on_hold": "⏸ " + _tf(lang,"promadm.hold_title","المعلّق","On hold"),
        "more_info":"✍️ " + _tf(lang,"promadm.more_title","معلومات إضافية","More info"),
        "banned": "🚫 " + _tf(lang,"promadm.banned_title","المحظورون (نشط)","Banned (active)"),
        "promoters":"📣 " + _tf(lang,"promadm.box_title","بوكس المروّجين","Promoters box"),
    }
    text = f"<b>{title_map.get(list_key, list_key)}</b>"
    await cb.message.answer(text, reply_markup=_list_kb(lang, ids, page, total, list_key, "promadm:open"), parse_mode="HTML")
    await cb.answer()

# ========= بطاقة المستخدم + أزرار =========
def _user_view_text(lang: str, uid: str) -> str:
    d = _load(); u = d.get("users", {}).get(uid)
    if not u:
        return _tf(lang,"promadm.user_not_found","غير موجود.","Not found.")
    tg = u.get("telegram", {}) or {}
    tg_decl = tg.get("declared") or "-"
    tg_real = tg.get("real") or "-"
    tg_match = "✅" if tg.get("match") else "❗️"
    banned_left = max(0, int(u.get("banned_until",0)) - _now())
    ban_line = _tf(lang,"promadm.not_banned","غير محظور","Not banned")
    if banned_left > 0:
        ban_line = _tf(lang,"promadm.banned_left","محظور - تبقّى","Banned - left") + f": <code>{banned_left//3600}h</code>"
    links = u.get("links") or []
    if isinstance(links, str):
        links = [links]
    links_str = "\n".join(f"• {x}" for x in links) if links else "—"
    promoter_badge = "👑" if u.get("is_promoter") else "—"
    return (
        f"🪪 <b>{_tf(lang,'promadm.user_card','بطاقة طلب','Request card')}</b>\n"
        f"ID: <code>{uid}</code> — <a href='tg://user?id={uid}'>{_tf(lang,'promadm.open_chat','فتح المحادثة','Open chat')}</a>\n"
        f"{_tf(lang,'promadm.state','الحالة','Status')}: <b>{u.get('status','-')}</b> | "
        f"{_tf(lang,'promadm.is_promoter','مروّج','Promoter')}: <b>{promoter_badge}</b>\n"
        f"{_tf(lang,'promadm.name','الاسم','Name')}: <code>{u.get('name','-')}</code>\n"
        f"{_tf(lang,'promadm.links','الروابط','Links')}:\n{links_str}\n"
        f"{_tf(lang,'promadm.tg.real_label','تيليجرام','Telegram')}: <code>{tg_real}</code> "
        f"({_tf(lang,'promadm.tg.declared_label','المعلن','declared')}: <code>{tg_decl}</code>) {tg_match}\n"
        f"{_tf(lang,'promadm.ban','الحظر','Ban')}: {ban_line}\n"
    )

def _user_actions_kb(lang: str, uid: str) -> InlineKeyboardMarkup:
    ban_row = [
        InlineKeyboardButton(text="🚫 1d", callback_data=f"prom:adm:ban1:{uid}"),
        InlineKeyboardButton(text="🚫 7d", callback_data=f"prom:adm:ban7:{uid}"),
        InlineKeyboardButton(text="🚫 30d", callback_data=f"prom:adm:ban30:{uid}"),
    ]
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tf(lang,"prom.adm.approve","✅ موافقة","✅ Approve"), callback_data=f"prom:adm:approve:{uid}"),
        InlineKeyboardButton(text=_tf(lang,"prom.adm.reject","❌ رفض","❌ Reject"), callback_data=f"prom:adm:reject:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text=_tf(lang,"prom.adm.more","✍️ معلومات إضافية","✍️ Request more info"), callback_data=f"prom:adm:more:{uid}"),
        InlineKeyboardButton(text=_tf(lang,"prom.adm.hold","⏸️ تعليق","⏸️ Put on hold"), callback_data=f"prom:adm:hold:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text=_tf(lang,"prom.adm.promote","👑 منح لقب مروّج","👑 Promote"), callback_data=f"prom:adm:promote:{uid}"),
        InlineKeyboardButton(text=_tf(lang,"prom.adm.demote","🗑 إلغاء المروّج","🗑 Demote"), callback_data=f"prom:adm:demote:{uid}"),
    )
    kb.row(*ban_row)
    kb.row(
        InlineKeyboardButton(text=_tf(lang,"prom.adm.unban","♻️ إزالة الحظر","♻️ Unban"), callback_data=f"prom:adm:unban:{uid}"),
        InlineKeyboardButton(text=_tf(lang,"prom.adm.delete","🗑 حذف الطلب","🗑 Delete"), callback_data=f"prom:adm:delete:{uid}"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع","Back"), callback_data="promadm:open"))
    return kb.as_markup()

@router.callback_query(F.data.startswith("promadm:view:"))
async def view_user(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    uid = cb.data.split(":")[-1]
    await cb.message.answer(_user_view_text(lang, uid), reply_markup=_user_actions_kb(lang, uid),
                            parse_mode="HTML", disable_web_page_preview=True)
    await cb.answer()

# ========= بوكس المروّجين =========
@router.callback_query(F.data.startswith("promadm:box:"))
async def promoters_box(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang,"common.admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    page = int(cb.data.split(":")[-1])
    ids_full = _filter_ids("promoters")
    ids, total = _page(ids_full, page)
    rows = []
    for uid in ids:
        rows.append([InlineKeyboardButton(text=f"👑 {uid}", callback_data=f"promadm:view:{uid}")])
    if not ids:
        rows.append([InlineKeyboardButton(text=_tf(lang,"promadm.none_box","لا يوجد مروّجون حالياً","No promoters currently"), callback_data="promadm:noop")])
    if total > PAGE_SIZE:
        pages = (total + PAGE_SIZE - 1)//PAGE_SIZE
        nav = []
        if page > 1: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"promadm:box:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="promadm:noop"))
        if page < pages: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"promadm:box:{page+1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع","Back"), callback_data="promadm:open")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await cb.message.answer("📣 <b>"+_tf(lang,"promadm.box_title","بوكس المروّجين","Promoters box")+"</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()

# ========= بحث وإعدادات =========
class PAStates(StatesGroup):
    waiting_uid = State()
    waiting_daily = State()

@router.callback_query(F.data == "promadm:search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    await state.set_state(PAStates.waiting_uid)
    await cb.message.answer(_tf(lang,"promadm.ask_uid","أرسل رقم ID للمستخدم:","Send the user ID:"))
    await cb.answer()

@router.message(PAStates.waiting_uid)
async def search_show(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."))
    uid = (m.text or "").strip()
    d = _load()
    if uid not in d.get("users", {}):
        return await m.reply(_tf(lang,"promadm.user_not_found","غير موجود.","Not found."))
    await state.clear()
    await m.answer(_user_view_text(lang, uid), reply_markup=_user_actions_kb(lang, uid),
                   parse_mode="HTML", disable_web_page_preview=True)

def _settings_text(lang: str) -> str:
    d = _load(); dl = int(d.get("settings", {}).get("daily_limit", 5))
    return f"⚙️ <b>{_tf(lang,'promadm.settings','إعدادات المروّجين','Promoters settings')}</b>\n\n" \
           f"• {_tf(lang,'promadm.daily_limit','الحد اليومي للطلبات','Daily application limit')}: <code>{dl}</code>\n"

def _settings_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_tf(lang,"promadm.set_daily","تغيير الحد اليومي","Change daily limit"), callback_data="promadm:set_daily")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع","Back"), callback_data="promadm:open")],
    ])

@router.callback_query(F.data == "promadm:settings")
async def open_settings(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    await cb.message.answer(_settings_text(lang), reply_markup=_settings_kb(lang), parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data == "promadm:set_daily")
async def set_daily_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    await state.set_state(PAStates.waiting_daily)
    await cb.message.answer(_tf(lang,"promadm.ask_daily","أرسل رقم الحد اليومي (1-20):","Send the daily limit (1-20):"))
    await cb.answer()

@router.message(PAStates.waiting_daily)
async def set_daily_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."))
    try:
        n = int((m.text or "").strip())
        if n < 1 or n > 20: raise ValueError
    except Exception:
        return await m.reply(_tf(lang,"promadm.err_number","رقم غير صالح.","Invalid number."))
    d = _load()
    d.setdefault("settings", {})["daily_limit"] = n
    _save(d)
    await state.clear()
    await m.reply(_tf(lang,"promadm.saved","تم الحفظ ✅","Saved ✅"))

@router.callback_query(F.data == "promadm:noop")
async def noop(cb: CallbackQuery):
    await cb.answer()

# ========= إجراءات الأدمن =========
@router.callback_query(F.data.regexp(r"^prom:adm:(approve|reject|hold|more):\d+$"))
async def action_basic(cb: CallbackQuery):
    lang_admin = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang_admin, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    _, _, act, uid = cb.data.split(":")
    d = _load(); u = _get_user(d, uid)

    # نستخدم لغة المستخدم المستقبِل
    user_lang = L(int(uid))

    status_map = {
        "approve": ("approved", "prom.user.approved",
                    "✅ تمّت الموافقة على طلبك كمروّج.", "✅ Your promoter application was approved."),
        "reject":  ("rejected", "prom.user.rejected",
                    "❌ تم رفض طلبك.", "❌ Your application was rejected."),
        "hold":    ("on_hold",  "prom.user.hold",
                    "⏸ تم تعليق طلبك مؤقتًا.", "⏸ Your application has been put on hold."),
        "more":    ("more_info","prom.user.more",
                    "✍️ نحتاج معلومات إضافية لطلبك.", "✍️ We need more information for your application."),
    }
    new_status, user_key, ar_fb, en_fb = status_map[act]
    u["status"] = new_status
    _save(d)

    try:
        await _notify_user(cb, int(uid), _tf(user_lang, user_key, ar_fb, en_fb))
    except Exception:
        pass
    await cb.answer(_tf(lang_admin, "common.done", "تم ✅","Done ✅"))

@router.callback_query(F.data.regexp(r"^prom:adm:(promote|demote):\d+$"))
async def action_promote(cb: CallbackQuery):
    lang_admin = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang_admin, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    _, _, act, uid = cb.data.split(":")
    d = _load(); u = _get_user(d, uid)

    user_lang = L(int(uid))
    if act == "promote":
        u["is_promoter"] = True
        txt = _tf(user_lang, "prom.user.promoted",
                  "👑 تم منحك لقب «مروّج» وتم تفعيل لوحة المروّجين.",
                  "👑 You’ve been granted the Promoter role. Your panel is now enabled.")
    else:
        u["is_promoter"] = False
        txt = _tf(user_lang, "prom.user.demoted",
                  "🗑 تم إلغاء لقب «مروّج» لديك وتعطيل لوحتك.",
                  "🗑 Your Promoter role has been removed and your panel disabled.")
    _save(d)
    try:
        await _notify_user(cb, int(uid), txt)
    except Exception:
        pass
    await cb.answer(_tf(lang_admin, "common.done", "تم ✅","Done ✅"))

@router.callback_query(F.data.regexp(r"^prom:adm:ban(1|7|30):\d+$"))
async def action_ban(cb: CallbackQuery):
    lang_admin = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang_admin, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    _, _, ban_s, uid = cb.data.split(":")
    days = int(ban_s.replace("ban",""))
    d = _load(); u = _get_user(d, uid)

    u["banned_until"] = _now() + days*24*3600
    _save(d)
    user_lang = L(int(uid))
    try:
        await _notify_user(
            cb, int(uid),
            _tf(user_lang, "prom.user.banned",
                f"🚫 تم حظرك لمدة {days} يومًا.",
                f"🚫 You have been banned for {days} day{'s' if days != 1 else ''}.")
        )
    except Exception:
        pass
    await cb.answer(_tf(lang_admin, "common.done", "تم ✅","Done ✅"))

@router.callback_query(F.data.regexp(r"^prom:adm:unban:\d+$"))
async def action_unban(cb: CallbackQuery):
    lang_admin = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang_admin, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    _, _, _, uid = cb.data.split(":")
    d = _load(); u = _get_user(d, uid)

    u["banned_until"] = 0
    _save(d)
    user_lang = L(int(uid))
    try:
        await _notify_user(cb, int(uid), _tf(user_lang, "prom.user.unbanned",
                                             "♻️ تم إزالة الحظر عن حسابك.",
                                             "♻️ Your ban has been lifted."))
    except Exception:
        pass
    await cb.answer(_tf(lang_admin, "common.done", "تم ✅","Done ✅"))

@router.callback_query(F.data.regexp(r"^prom:adm:delete:\d+$"))
async def action_delete(cb: CallbackQuery):
    lang_admin = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang_admin, "common.admins_only", "هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)
    _, _, _, uid = cb.data.split(":")
    d = _load()
    d.get("users", {}).pop(uid, None)
    _save(d)
    user_lang = L(int(uid))
    try:
        await _notify_user(cb, int(uid), _tf(user_lang, "prom.user.deleted",
                                             "🗑 تم حذف طلبك.",
                                             "🗑 Your application has been deleted."))
    except Exception:
        pass
    await cb.answer(_tf(lang_admin, "common.done", "تم ✅","Done ✅"))
