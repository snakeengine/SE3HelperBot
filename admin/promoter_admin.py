# admin/promoter_admin.py
from __future__ import annotations

import os, json, logging, time
from pathlib import Path
from typing import Dict, Any, List, Tuple
from aiogram import Bot
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang

router = Router(name="promoter_admin")
log = logging.getLogger(__name__)

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = DATA_DIR / "promoters.json"   # نفس الملف الذي يستخدمه handlers/promoter.py

# ===== صلاحيات الأدمن =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    return fallback

def _now() -> int:
    return int(time.time())

def _human_dur(sec: int, lang: str) -> str:
    m = max(0, sec) // 60
    h = m // 60
    d = h // 24
    if d >= 1: return f"{d} " + _tf(lang, "prom.time.days", "يوم")
    if h >= 1: return f"{h} " + _tf(lang, "prom.time.hours", "ساعة")
    if m >= 1: return f"{m} " + _tf(lang, "prom.time.minutes", "دقيقة")
    return f"{max(0,sec)} " + _tf(lang, "prom.time.seconds", "ثانية")

async def _try_notify(bot: Bot, uid: int | str, text: str) -> None:
    try:
        await bot.send_message(int(uid), text, disable_web_page_preview=True)
    except Exception:
        # لو المستخدم حاظر البوت أو حدث خطأ — نتجاهله
        pass


def _migrate_store(d: Dict[str, Any]) -> Dict[str, Any]:
    changed = False
    users = d.setdefault("users", {})
    for uid, u in list(users.items()):
        # telegram -> dict
        tg = u.get("telegram")
        if not isinstance(tg, dict):
            if isinstance(tg, str):
                s = tg.strip()
                if s and not s.startswith("@"):
                    s = "@" + s
                u["telegram"] = {"declared": s or "-", "real": None, "match": False}
            else:
                u["telegram"] = {"declared": "-", "real": None, "match": False}
            changed = True

        # links -> list
        if isinstance(u.get("links"), str):
            u["links"] = [u["links"]]
            changed = True

        # ensure ints
        for k in ("banned_until", "cooldown_until", "submitted_at"):
            try:
                u[k] = int(u.get(k, 0) or 0)
            except Exception:
                u[k] = 0
                changed = True

    if changed:
        _save(d)
    return d

# ===== I/O =====
def _load() -> Dict[str, Any]:
    if STORE_FILE.exists():
        try:
            data = json.loads(STORE_FILE.read_text("utf-8"))
            return _migrate_store(data)  # ← إضافة هذه السطر
        except Exception:
            pass
    return {"users": {}, "settings": {"daily_limit": 5}}


def _save(d: Dict[str, Any]) -> None:
    STORE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

# ===== إحصاءات سريعة =====
def _stats(d: Dict[str, Any]) -> Dict[str, int]:
    s = {"pending":0,"approved":0,"rejected":0,"on_hold":0,"more_info":0,"total":0,"banned":0}
    now = _now()
    for u in d.get("users", {}).values():
        st = u.get("status", "none")
        s["total"] += 1
        if st in s: s[st] += 1
        if u.get("banned_until",0) and u["banned_until"] > now:
            s["banned"] += 1
    return s

# ===== لوحة الرئيسية =====
def _panel_text(lang: str) -> str:
    d = _load()
    s = _stats(d)
    dl = int(d.get("settings", {}).get("daily_limit", 5))
    return (
        f"📊 <b>{_tf(lang, 'promadm.title', 'إدارة المروّجين')}</b>\n\n"
        f"• {_tf(lang,'promadm.stats.pending','قيد المراجعة')}: <b>{s['pending']}</b>\n"
        f"• {_tf(lang,'promadm.stats.approved','الموافق عليهم')}: <b>{s['approved']}</b>\n"
        f"• {_tf(lang,'promadm.stats.rejected','المرفوضون')}: <b>{s['rejected']}</b>\n"
        f"• {_tf(lang,'promadm.stats.hold','معلّق')}: <b>{s['on_hold']}</b>\n"
        f"• {_tf(lang,'promadm.stats.more','معلومات إضافية')}: <b>{s['more_info']}</b>\n"
        f"• {_tf(lang,'promadm.stats.banned','محظورون (نشط)')}: <b>{s['banned']}</b>\n"
        f"• {_tf(lang,'promadm.stats.total','الإجمالي')}: <b>{s['total']}</b>\n\n"
        f"⚙️ {_tf(lang,'promadm.daily_limit','الحد اليومي للطلبات')}: <code>{dl}</code>\n"
    )

def _panel_kb(lang: str) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="📥 " + _tf(lang,"promadm.btn.pending","الطلبات المعلّقة"), callback_data="promadm:pending:1")],
        [InlineKeyboardButton(text="🔍 " + _tf(lang,"promadm.btn.search","بحث ID"), callback_data="promadm:search")],
        [InlineKeyboardButton(text="📦 " + _tf(lang,"promadm.btn.list","قائمة المروّجين"), callback_data="promadm:list:approved:1")],
        [
            InlineKeyboardButton(text="❌ " + _tf(lang,"promadm.btn.cancel","إلغاء مروّج"), callback_data="promadm:cancel"),
            InlineKeyboardButton(text="⛔ " + _tf(lang,"promadm.btn.block","حظر مروّج"),  callback_data="promadm:block"),
        ],
        [InlineKeyboardButton(text="♻️ " + _tf(lang,"promadm.btn.unblock","إزالة الحظر"), callback_data="promadm:unblock")],
        # زر إلغاء التبريد (ID) ⇦ سيعرض لوحة تحكم سريعة لهذا الـID
        [InlineKeyboardButton(text="🧊 " + _tf(lang,"promadm.btn.clear_cd_id","إلغاء التبريد (نشط)"),
                      callback_data="promadm:cdlist:1")],
        [InlineKeyboardButton(text="⚙️ " + _tf(lang,"promadm.btn.settings","الإعدادات"), callback_data="promadm:settings")],
        [InlineKeyboardButton(text="🔄 " + _tf(lang,"promadm.btn.refresh","تحديث"), callback_data="promadm:refresh")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="ah:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def _safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

# ===== فتح/تحديث اللوحة =====
@router.callback_query(F.data == "promadm:open")
async def open_panel(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang))
    await cb.answer()

@router.callback_query(F.data == "promadm:refresh")
async def refresh_panel(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await _safe_edit(cb.message, _panel_text(lang), _panel_kb(lang))
    await cb.answer("✅")

# ===== ترقيم صفحات =====
PAGE_SIZE = 10

def _slice(ids: List[str], page: int) -> Tuple[List[str], int, int]:
    total = len(ids)
    pages = (total + PAGE_SIZE - 1)//PAGE_SIZE if total else 1
    page = max(1, min(page, pages))
    start = (page-1)*PAGE_SIZE
    end = start + PAGE_SIZE
    return ids[start:end], page, pages

# ===== قائمة المستخدمين ذوي "التبريد" =====
def _cooldown_ids(d: Dict[str, Any]) -> List[str]:
    now = _now()
    ids = []
    for uid, u in d.get("users", {}).items():
        if int(u.get("cooldown_until", 0) or 0) > now:
            ids.append(uid)
    # الأحدث أولاً (أقرب انتهاء تبريد في الأعلى مفيد)
    ids.sort(key=lambda x: d["users"][x].get("cooldown_until", 0), reverse=True)
    return ids

def _fmt_left_h(sec: int) -> str:
    # عرض بالساعات التقريبية
    h = max(0, sec // 3600)
    return f"{h}h"

def _cdlist_kb(lang: str, page: int, pages: int, ids: List[str], d: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    now = _now()
    for uid in ids:
        u = d["users"][uid]
        left = max(0, int(u.get("cooldown_until", 0)) - now)
        left_s = _fmt_left_h(left)
        st = u.get("status", "-")
        # زر المستخدم يفتح لوحة التحكم السريعة مباشرة
        rows.append([InlineKeyboardButton(
            text=f"🧊 {uid} • {left_s} • {st}",
            callback_data=f"promadm:qmenu:{uid}"
        )])
    # تنقل
    nav = []
    if pages > 1:
        if page > 1: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"promadm:cdlist:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="promadm:noop"))
        if page < pages: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"promadm:cdlist:{page+1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="promadm:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== المعلّقون =====
def _list_pending_ids(d: Dict[str,Any]) -> List[str]:
    return [uid for uid,u in d.get("users", {}).items() if u.get("status")=="pending"]

def _pending_kb(lang: str, page: int, pages: int, ids: List[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🆕 {uid}", callback_data=f"promadm:view:{uid}")] for uid in ids]
    nav = []
    if pages > 1:
        if page > 1: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"promadm:pending:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="promadm:noop"))
        if page < pages: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"promadm:pending:{page+1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="promadm:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data.startswith("promadm:pending:"))
async def show_pending(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    page = int(cb.data.split(":")[-1])
    d = _load()
    ids_all = sorted(_list_pending_ids(d), key=lambda x: d["users"][x].get("submitted_at",0), reverse=True)
    ids, page, pages = _slice(ids_all, page)
    if not ids:
        await cb.message.answer(_tf(lang,"promadm.none_pending","لا توجد طلبات معلّقة."))
        return await cb.answer()
    text = "📥 <b>" + _tf(lang,"promadm.pending_title","الطلبات المعلّقة") + "</b>"
    await cb.message.answer(text, reply_markup=_pending_kb(lang, page, pages, ids), parse_mode="HTML")
    await cb.answer()

# ===== بطاقة مستخدم + إجراءات =====
def _user_view_text(lang: str, uid: str) -> str:
    d = _load()
    u = d.get("users", {}).get(uid)
    if not u:
        return _tf(lang,"promadm.user_not_found","غير موجود.")

    # --- تطبيع الحقول القديمة/المتنوعة ---
    # telegram قد يكون نصّاً قديماً
    tg_raw = u.get("telegram", {})
    if isinstance(tg_raw, dict):
        tg = tg_raw
    else:
        # حوّله إلى dict متوافق
        if isinstance(tg_raw, str):
            s = tg_raw.strip()
            if s and not s.startswith("@"):
                s = "@" + s
            tg = {"declared": s or "-", "real": None, "match": False}
        else:
            tg = {"declared": "-", "real": None, "match": False}

    # الروابط قد تكون نصّاً واحداً قديماً
    links_raw = u.get("links") or []
    if isinstance(links_raw, str):
        links = [links_raw]
    elif isinstance(links_raw, list):
        links = links_raw
    else:
        links = []

    # أزمنة رقمية مضمونة
    def _int(v): 
        try:
            return int(v or 0)
        except Exception:
            return 0

    now = _now()
    banned_left   = max(0, _int(u.get("banned_until"))   - now)
    cooldown_left = max(0, _int(u.get("cooldown_until")) - now)

    tg_decl  = tg.get("declared") or "-"
    tg_real  = tg.get("real") or "-"
    tg_match = "✅" if tg.get("match") else "❗️"

    ban_line = _tf(lang,"promadm.not_banned","غير محظور")
    if banned_left > 0:
        ban_line = _tf(lang,"promadm.banned_left","محظور - تبقّى") + f": <code>{banned_left//3600}h</code>"

    cd_line = _tf(lang,"promadm.no_cooldown","لا يوجد تبريد")
    if cooldown_left > 0:
        cd_line = _tf(lang,"promadm.cooldown_left","تبريد - تبقّى") + f": <code>{cooldown_left//3600}h</code>"

    links_str = "\n".join(f"• {x}" for x in links) if links else "—"

    return (
        f"🪪 <b>{_tf(lang,'promadm.user_card','بطاقة طلب')}</b>\n"
        f"ID: <code>{uid}</code> — <a href='tg://user?id={uid}'>[open chat]</a>\n"
        f"{_tf(lang,'promadm.state','الحالة')}: <b>{u.get('status','-')}</b>\n"
        f"{_tf(lang,'promadm.name','الاسم')}: <code>{u.get('name','-')}</code>\n"
        f"{_tf(lang,'promadm.links','الروابط')}:\n{links_str}\n"
        f"Telegram: <code>{tg_real}</code> (declared: <code>{tg_decl}</code>) {tg_match}\n"
        f"{_tf(lang,'promadm.ban','الحظر')}: {ban_line}\n"
        f"{_tf(lang,'promadm.cooldown','التبريد')}: {cd_line}\n"
    )


def _user_actions_kb(lang: str, uid: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.approve","✅ موافقة"), callback_data=f"prom:adm:approve:{uid}"),
            InlineKeyboardButton(text=_tf(lang,"prom.adm.reject","❌ رفض"), callback_data=f"prom:adm:reject:{uid}"),
        ],
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.more","✍️ معلومات إضافية"), callback_data=f"prom:adm:more:{uid}"),
            InlineKeyboardButton(text=_tf(lang,"prom.adm.hold","⏸️ تعليق"), callback_data=f"prom:adm:hold:{uid}"),
        ],
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.ban","🚫 حظر"), callback_data=f"prom:adm:ban:{uid}"),
            InlineKeyboardButton(text=_tf(lang,"prom.adm.unban","♻️ إزالة الحظر"), callback_data=f"prom:adm:unban:{uid}"),
        ],
        [
            InlineKeyboardButton(text=_tf(lang,"prom.adm.clear_cd","🧊 إلغاء التبريد"), callback_data=f"promadm:cdclear:{uid}")
        ],
        [InlineKeyboardButton(text=_tf(lang,"prom.adm.delete","🗑 حذف الطلب"), callback_data=f"prom:adm:delete:{uid}")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="promadm:open")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data.startswith("promadm:view:"))
async def view_user(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    uid = cb.data.split(":")[-1]
    await cb.message.answer(_user_view_text(lang, uid), reply_markup=_user_actions_kb(lang, uid),
                            parse_mode="HTML", disable_web_page_preview=True)
    await cb.answer()

# ===== القوائم (الموافق عليهم / المحظورون / …) =====
def _filter_ids(d: Dict[str,Any], flt: str) -> List[str]:
    now = _now()
    users = d.get("users", {})
    if flt == "approved":
        return [uid for uid,u in users.items() if u.get("status")=="approved"]
    if flt == "banned":
        return [uid for uid,u in users.items() if u.get("banned_until",0) > now]
    if flt == "hold":
        return [uid for uid,u in users.items() if u.get("status")=="on_hold"]
    if flt == "more":
        return [uid for uid,u in users.items() if u.get("status")=="more_info"]
    return list(users.keys())

def _list_kb(lang: str, flt: str, page: int, pages: int, ids: List[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"👤 {uid}", callback_data=f"promadm:view:{uid}")] for uid in ids]
    rows.append([
        InlineKeyboardButton(text="✅", callback_data="promadm:list:approved:1"),
        InlineKeyboardButton(text="⛔", callback_data="promadm:list:banned:1"),
        InlineKeyboardButton(text="⏸️", callback_data="promadm:list:hold:1"),
        InlineKeyboardButton(text="✍️", callback_data="promadm:list:more:1"),
    ])
    nav = []
    if pages > 1:
        if page > 1: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"promadm:list:{flt}:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="promadm:noop"))
        if page < pages: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"promadm:list:{flt}:{page+1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="promadm:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data.startswith("promadm:list:"))
async def show_list(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    _, _, flt, page_s = cb.data.split(":")
    page = int(page_s)
    d = _load()
    ids_all = sorted(_filter_ids(d, flt), key=lambda x: d["users"][x].get("submitted_at",0), reverse=True)
    ids, page, pages = _slice(ids_all, page)
    if not ids:
        await cb.message.answer(_tf(lang, "promadm.empty_list", "القائمة فارغة."))
        return await cb.answer()
    title = {
        "approved": _tf(lang,"promadm.list.approved","الموافق عليهم"),
        "banned":   _tf(lang,"promadm.list.banned","محظورون (نشط)"),
        "hold":     _tf(lang,"promadm.list.hold","معلّقون"),
        "more":     _tf(lang,"promadm.list.more","بحاجة معلومات"),
    }.get(flt, "List")
    await cb.message.answer("📦 <b>"+title+"</b>", reply_markup=_list_kb(lang, flt, page, pages, ids), parse_mode="HTML")
    await cb.answer()

# ===== بحث و إعدادات وعمليات مباشرة =====
class PAStates(StatesGroup):
    waiting_uid       = State()
    waiting_daily     = State()
    waiting_cancel    = State()
    waiting_block_uid = State()
    waiting_unblock   = State()
    waiting_cdclear   = State()   # لإلغاء التبريد بالـ ID

# --- بحث ID
@router.callback_query(F.data == "promadm:search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(PAStates.waiting_uid)
    await cb.message.answer(_tf(lang,"promadm.ask_uid","أرسل رقم ID للمستخدم:"))
    await cb.answer()

@router.message(PAStates.waiting_uid)
async def search_show(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = (m.text or "").strip()
    d = _load()
    if uid not in d.get("users", {}):
        return await m.reply(_tf(lang,"promadm.user_not_found","غير موجود."))
    await state.clear()
    await m.answer(_user_view_text(lang, uid), reply_markup=_user_actions_kb(lang, uid),
                   parse_mode="HTML", disable_web_page_preview=True)

# --- إعدادات
def _settings_text(lang: str) -> str:
    d = _load()
    dl = int(d.get("settings", {}).get("daily_limit", 5))
    return f"⚙️ <b>{_tf(lang,'promadm.settings','إعدادات المروّجين')}</b>\n\n" \
           f"• {_tf(lang,'promadm.daily_limit','الحد اليومي للطلبات')}: <code>{dl}</code>\n"

def _settings_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_tf(lang,"promadm.set_daily","تغيير الحد اليومي"), callback_data="promadm:set_daily")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="promadm:open")],
    ])

@router.callback_query(F.data == "promadm:settings")
async def open_settings(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await cb.message.answer(_settings_text(lang), reply_markup=_settings_kb(lang), parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data == "promadm:set_daily")
async def set_daily_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(PAStates.waiting_daily)
    await cb.message.answer(_tf(lang,"promadm.ask_daily","أرسل رقم الحد اليومي (1-20):"))
    await cb.answer()

@router.message(PAStates.waiting_daily)
async def set_daily_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    try:
        n = int((m.text or "").strip())
        if n < 1 or n > 20: raise ValueError
    except Exception:
        return await m.reply(_tf(lang,"promadm.err_number","رقم غير صالح."))
    d = _load()
    d.setdefault("settings", {})["daily_limit"] = n
    _save(d)
    await state.clear()
    await m.reply(_tf(lang,"promadm.saved","تم الحفظ ✅"))

# --- إلغاء مروّج (إزالة الحالة)
@router.callback_query(F.data == "promadm:cancel")
async def cancel_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(PAStates.waiting_cancel)
    await cb.message.answer(_tf(lang, "promadm.ask_uid_cancel", "أرسل ID لإلغاء صفة المروّج عنه:"))
    await cb.answer()

@router.message(PAStates.waiting_cancel)
async def cancel_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = (m.text or "").strip()
    d = _load()
    u = d.get("users", {}).get(uid)
    if not u:
        return await m.reply(_tf(lang, "promadm.user_not_found", "غير موجود."))
    u["status"] = "deleted"
    u["removed_at"] = _now()
    _save(d)
    await state.clear()
    await _try_notify(m.bot, uid, _tf(lang, "prom.user.cancelled", "تم إلغاء صفة المروّج عنك."))
    await m.reply(_tf(lang,"promadm.user.cancelled","تم إلغاء صفة المروّج ✅"))

# --- حظر مروّج
def _ban_kb(uid: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1d",  callback_data=f"promadm:ban:{uid}:86400"),
            InlineKeyboardButton(text="7d",  callback_data=f"promadm:ban:{uid}:604800"),
            InlineKeyboardButton(text="30d", callback_data=f"promadm:ban:{uid}:2592000"),
        ],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="promadm:open")]
    ])

@router.callback_query(F.data == "promadm:block")
async def block_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(PAStates.waiting_block_uid)
    await cb.message.answer(_tf(lang,"promadm.ask_uid_block","أرسل ID لحظر المستخدم:"))
    await cb.answer()

@router.message(PAStates.waiting_block_uid)
async def block_pick_duration(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = (m.text or "").strip()
    d = _load()
    if uid not in d.get("users", {}):
        return await m.reply(_tf(lang,"promadm.user_not_found","غير موجود."))
    await state.clear()
    await m.reply(_tf(lang,"promadm.pick_block","اختر مدة الحظر:"), reply_markup=_ban_kb(uid, lang))

@router.callback_query(F.data.startswith("promadm:ban:"))
async def block_apply(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    _,_, uid, sec = cb.data.split(":")
    sec = int(sec)
    d = _load()
    if uid not in d.get("users", {}):
        return await cb.answer(_tf(lang,"promadm.user_not_found","غير موجود."), show_alert=True)
    d["users"][uid]["banned_until"] = _now() + sec
    _save(d)
    await _try_notify(cb.bot, uid, _tf(lang, "prom.user.banned", "تم حظرك مؤقتًا. المدة: ") + _human_dur(sec, lang))
    await cb.answer(_tf(lang,"promadm.user.banned","تم الحظر ✅"), show_alert=True)

# --- إزالة الحظر
@router.callback_query(F.data == "promadm:unblock")
async def unblock_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(PAStates.waiting_unblock)
    await cb.message.answer(_tf(lang,"promadm.ask_uid_unblock","أرسل ID لإزالة الحظر:"))
    await cb.answer()

@router.message(PAStates.waiting_unblock)
async def unblock_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = (m.text or "").strip()
    d = _load()
    if uid not in d.get("users", {}):
        return await m.reply(_tf(lang,"promadm.user_not_found","غير موجود."))
    d["users"][uid]["banned_until"] = 0
    _save(d)
    await state.clear()
    await _try_notify(m.bot, uid, _tf(lang, "prom.user.unbanned", "تمت إزالة الحظر عنك ✅"))
    await m.reply(_tf(lang,"promadm.user.unblocked","تمت إزالة الحظر ✅"))

# --- إلغاء التبريد من بطاقة المستخدم
@router.callback_query(F.data.startswith("promadm:cdclear:"))
async def clear_cooldown_inline(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)

    uid = cb.data.split(":")[-1]
    d = _load()
    u = d.get("users", {}).get(uid)
    if not u:
        return await cb.answer(_tf(lang, "promadm.user_not_found", "غير موجود."), show_alert=True)

    u["cooldown_until"] = 0
    _save(d)

    # إشعار المستخدم
    await _try_notify(cb.bot, uid, _tf(lang, "prom.user.cd_cleared", "تم رفع التبريد عنك، يمكنك التقديم الآن ✅"))

    await cb.answer(_tf(lang, "promadm.cooldown_cleared", "تم إلغاء التبريد ✅"), show_alert=True)

# ===== لوحة تحكم سريعة بعد إدخال ID في زر (إلغاء التبريد ID) =====
def _quick_actions_kb(lang: str, uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧊 " + _tf(lang,"promadm.q.clear","إلغاء التبريد"), callback_data=f"promadm:q:clear:{uid}"),
            InlineKeyboardButton(text="♻️ " + _tf(lang,"promadm.q.unblock","إزالة الحظر"),  callback_data=f"promadm:q:unblock:{uid}"),
        ],
        [
            InlineKeyboardButton(text="⛔ 1d",  callback_data=f"promadm:q:ban:{uid}:86400"),
            InlineKeyboardButton(text="⛔ 7d",  callback_data=f"promadm:q:ban:{uid}:604800"),
            InlineKeyboardButton(text="⛔ 30d", callback_data=f"promadm:q:ban:{uid}:2592000"),
        ],
        [
            InlineKeyboardButton(text="❌ " + _tf(lang,"promadm.q.cancel","إلغاء مروّج"), callback_data=f"promadm:q:cancel:{uid}"),
            InlineKeyboardButton(text="👁 " + _tf(lang,"promadm.q.view","عرض البطاقة"),   callback_data=f"promadm:view:{uid}"),
        ],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promadm.btn.back","رجوع"), callback_data="promadm:open")],
    ])

@router.callback_query(F.data == "promadm:cdclear_id")
async def cdclear_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)
    await state.set_state(PAStates.waiting_cdclear)
    await cb.message.answer(_tf(lang, "promadm.ask_uid_cdclear", "أرسل ID لإلغاء التبريد عنه:"))
    await cb.answer()

@router.message(PAStates.waiting_cdclear)
async def cdclear_prompt_actions(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))
    uid = (m.text or "").strip()
    d = _load()
    if uid not in d.get("users", {}):
        return await m.reply(_tf(lang, "promadm.user_not_found", "غير موجود."))
    await state.clear()
    # نعرض اللوحة السريعة بكل الأوامر — الـcallbacks تحمل الـID بالكامل
    await m.reply(_user_view_text(lang, uid), reply_markup=_quick_actions_kb(lang, uid),
                  parse_mode="HTML", disable_web_page_preview=True)
    
@router.callback_query(F.data.startswith("promadm:cdlist:"))
async def show_cooldown_list(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang,"admins_only","هذه الأداة للأدمن فقط."), show_alert=True)

    page = int(cb.data.split(":")[-1])
    d = _load()
    ids_all = _cooldown_ids(d)
    if not ids_all:
        await cb.message.answer(_tf(lang, "promadm.cdlist.empty", "لا يوجد مستخدمون حاليًا تحت التبريد."))
        return await cb.answer()

    ids, page, pages = _slice(ids_all, page)
    title = "🧊 <b>" + _tf(lang, "promadm.cdlist.title", "التبريد النشط") + "</b>"
    await cb.message.answer(title, reply_markup=_cdlist_kb(lang, page, pages, ids, d), parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data.startswith("promadm:qmenu:"))
async def open_quick_for_user(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang,"admins_only","هذه الأداة للأدمن فقط."), show_alert=True)
    uid = cb.data.split(":")[-1]
    d = _load()
    if uid not in d.get("users", {}):
        return await cb.answer(_tf(lang,"promadm.user_not_found","غير موجود."), show_alert=True)

    await cb.message.answer(
        _user_view_text(lang, uid),
        reply_markup=_quick_actions_kb(lang, uid),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await cb.answer()


# تنفيذ أوامر اللوحة السريعة
@router.callback_query(F.data.startswith("promadm:q:"))
async def quick_ops(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang,"admins_only","هذه الأداة للأدمن فقط."), show_alert=True)

    parts = cb.data.split(":")  # promadm:q:<op>:<uid>[:<sec>]
    op = parts[2]
    uid = parts[3]

    d = _load()
    if uid not in d.get("users", {}):
        return await cb.answer(_tf(lang,"promadm.user_not_found","غير موجود."), show_alert=True)

    if op == "clear":
        d["users"][uid]["cooldown_until"] = 0
        _save(d)
        await _try_notify(cb.bot, uid, _tf(lang, "prom.user.cd_cleared", "تم رفع التبريد عنك، يمكنك التقديم الآن ✅"))
        return await cb.answer(_tf(lang,"promadm.cooldown_cleared","تم إلغاء التبريد ✅"), show_alert=True)

    if op == "unblock":
        d["users"][uid]["banned_until"] = 0
        _save(d)
        await _try_notify(cb.bot, uid, _tf(lang, "prom.user.unbanned", "تمت إزالة الحظر عنك ✅"))
        return await cb.answer(_tf(lang,"promadm.user.unblocked","تمت إزالة الحظر ✅"), show_alert=True)

    if op == "ban":
        sec = int(parts[4])
        d["users"][uid]["banned_until"] = _now() + sec
        _save(d)
        await _try_notify(cb.bot, uid, _tf(lang, "prom.user.banned", "تم حظرك مؤقتًا. المدة: ") + _human_dur(sec, lang))
        return await cb.answer(_tf(lang,"promadm.user.banned","تم الحظر ✅"), show_alert=True)

    if op == "cancel":
        d["users"][uid]["status"] = "deleted"
        d["users"][uid]["removed_at"] = _now()
        _save(d)
        await _try_notify(cb.bot, uid, _tf(lang, "prom.user.cancelled", "تم إلغاء صفة المروّج عنك."))
        return await cb.answer(_tf(lang,"promadm.user.cancelled","تم إلغاء صفة المروّج ✅"), show_alert=True)

    await cb.answer("OK")
