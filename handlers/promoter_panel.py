# handlers/promoter_panel.py
from __future__ import annotations

import os, json, time, logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ContentType
)
    # ContentType import is correct for aiogram v3
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.base import StorageKey

from lang import t, get_user_lang

router = Router(name="promoter_panel")
log = logging.getLogger(__name__)

# ===== ملفات وإعدادات =====
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = DATA_DIR / "promoters.json"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

DEFAULT_SUB_DAYS = 30  # افتراضي عند التفعيل اليدوي

# ===== أدوات عامة =====
def _now() -> int:
    return int(time.time())

def L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip(): return s
    except Exception:
        pass
    return fallback

def _format_duration(sec: int, lang: str) -> str:
    sec = max(0, int(sec))
    m = sec // 60
    h = m // 60
    d = h // 24
    if d >= 1: return f"{d} " + _tf(lang, "prom.time.days", "يوم")
    if h >= 1: return f"{h} " + _tf(lang, "prom.time.hours", "ساعة")
    if m >= 1: return f"{m} " + _tf(lang, "prom.time.minutes", "دقيقة")
    return f"{sec} " + _tf(lang, "prom.time.seconds", "ثانية")

def _ts_to_str(ts: Optional[int]) -> str:
    if not ts: return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(ts))) + " UTC"
    except Exception:
        return "—"

# ===== I/O =====
def _load() -> Dict[str, Any]:
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"users": {}}

def _save(d: Dict[str, Any]) -> None:
    try:
        STORE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"[promoter_panel] save failed: {e}")

def _u(d: Dict[str, Any], uid: int | str) -> Dict[str, Any]:
    return d.setdefault("users", {}).setdefault(str(uid), {
        "status": "none",
        "name": "-",
        "links": [],
        "telegram": {"declared": "-", "real": None, "match": False},
        "app_id": None,
        "subscription": {"status": "none", "started_at": 0, "expires_at": 0, "remind_before_h": 24},
        "activities": []
    })

def _is_promoter(uid: int) -> bool:
    d = _load()
    u = d.get("users", {}).get(str(uid))
    return bool(u and u.get("status") == "approved")

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ===== لوحات وأزرار =====
def _panel_text(lang: str, u: Dict[str, Any]) -> str:
    sub = u.get("subscription", {}) or {}
    expires_in = max(0, int(sub.get("expires_at", 0) or 0) - _now())
    st = sub.get("status", "none")
    if st == "active":
        sub_line = _tf(lang, "promp.sub.active", "نشط") + f" — {_tf(lang,'promp.sub.left','تبقّى')}: <b>{_format_duration(expires_in, lang)}</b>"
    elif st == "pending":
        sub_line = _tf(lang, "promp.sub.pending", "بانتظار التفعيل")
    elif st == "denied":
        sub_line = _tf(lang, "promp.sub.denied", "مرفوض")
    else:
        sub_line = _tf(lang, "promp.sub.none", "لا يوجد")

    links = u.get("links") or []
    links_s = "\n".join(f"• {x}" for x in links) if links else "—"
    tg = u.get("telegram", {}) or {}
    tg_decl = tg.get("declared") or "-"
    tg_real = tg.get("real") or "-"

    return (
        f"🧑‍💼 <b>{_tf(lang,'promp.title','لوحة المروّجين')}</b>\n\n"
        f"{_tf(lang,'promp.name','الاسم')}: <code>{u.get('name','-')}</code>\n"
        f"{_tf(lang,'promp.tg.real_label','تيليجرام')}: <code>{tg_real}</code> "
        f"({_tf(lang,'promp.tg.declared_label','المعلن')}: <code>{tg_decl}</code>)\n"
        f"{_tf(lang,'promp.links','الروابط')}:\n{links_s}\n"
        f"{_tf(lang,'promp.app_id','معرّف التطبيق')} : <code>{u.get('app_id') or '-'}</code>\n"
        f"{_tf(lang,'promp.sub','الاشتراك')}: {sub_line}\n"
        f"{_tf(lang,'promp.sub.exp','ينتهي في')}: <code>{_ts_to_str(sub.get('expires_at'))}</code>\n"
    )

def _panel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪪 " + _tf(lang,"promp.btn.profile","معلوماتي / تعديل"), callback_data="promp:profile")],
        [InlineKeyboardButton(text="🎫 " + _tf(lang,"promp.btn.sub","اشتراكي"), callback_data="promp:sub")],
        [InlineKeyboardButton(text="🚀 " + _tf(lang,"promp.btn.activate","تفعيل الاشتراك (App ID)"), callback_data="promp:activate")],
        [InlineKeyboardButton(text="📤 " + _tf(lang,"promp.btn.proof","رفع إثبات نشاط"), callback_data="promp:proof")],
        [InlineKeyboardButton(text="🆘 " + _tf(lang,"promp.btn.support","دعم مباشر"), callback_data="promp:support")],
        [
            InlineKeyboardButton(text="⬅️ " + _tf(lang,"promp.btn.back","رجوع"), callback_data="back_to_menu"),
            InlineKeyboardButton(text="🔄 " + _tf(lang,"promp.btn.refresh","تحديث"), callback_data="promp:open"),
        ],
    ])

# ========= Helpers =========
def _fmt_links(links: list[str]) -> str:
    if not links:
        return "—"
    out = []
    for x in links:
        s = (x or "").strip()
        if not s:
            continue
        if s.startswith(("http://", "https://", "tg://")):
            out.append(f"• <a href=\"{s}\">{s}</a>")
        else:
            out.append(f"• {s}")
    return "\n".join(out) if out else "—"

def _chip(text: str) -> str:
    # شارة صغيرة للحالة
    return f"<span class=\"tg-spoiler\">{text}</span>"

def _status_chip(lang: str, status: str, left_s: str | None = None) -> str:
    s = (status or "none").lower()
    if s == "active":
        base = "✅ " + _tf(lang, "promp.sub.active", "نشط")
        if left_s:
            base += f" — {_tf(lang,'promp.sub.left','تبقّى')}: {left_s}"
        return _chip(base)
    if s == "pending":
        return _chip("⏳ " + _tf(lang, "promp.sub.pending", "بانتظار التفعيل"))
    if s == "denied":
        return _chip("❌ " + _tf(lang, "promp.sub.denied", "مرفوض"))
    return _chip("🚫 " + _tf(lang, "promp.sub.none", "لا يوجد"))

def _tg_line(lang: str, tg: dict) -> str:
    decl = tg.get("declared") or "-"
    real = tg.get("real") or "-"
    match = bool(tg.get("match"))
    mark = "✅" if match else "❗️"
    real_lbl = _tf(lang, "promp.tg.real_label", "المعرّف الفعلي على تيليجرام")
    decl_lbl = _tf(lang, "promp.tg.declared_label", "المعرّف المعلن على تيليجرام")
    return (
        f"{real_lbl}: <code>{real}</code> {mark}\n"
        f"({decl_lbl}: <code>{decl}</code>)"
    )

# ========= Profile Card =========
def _panel_text(lang: str, u: Dict[str, Any]) -> str:
    title = _tf(lang, "promp.title", "لوحة المروّجين")
    name_label = _tf(lang, "promp.name", "الاسم")
    links_label = _tf(lang, "promp.links", "الروابط")
    app_label = _tf(lang, "promp.app_id", "معرّف التطبيق")
    sub_label = _tf(lang, "promp.sub", "الاشتراك")
    exp_label = _tf(lang, "promp.sub.expires", "ينتهي في")

    # اشتراك
    sub = u.get("subscription", {}) or {}
    left = max(0, int(sub.get("expires_at", 0) or 0) - _now())
    left_s = _format_duration(left, lang) if left else None
    status = (sub.get("status") or "none").lower()
    chip = _status_chip(lang, status, left_s)
    expires_at = _ts_to_str(sub.get("expires_at"))

    # تيليجرام وروابط
    tg = u.get("telegram", {}) or {}
    tg_block = _tg_line(lang, tg)
    links_s = _fmt_links(u.get("links") or [])

    return (
        "🧑‍💼 <b>" + title + "</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{name_label}: <b>{u.get('name','-')}</b>\n"
        f"{tg_block}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{links_label}:\n{links_s}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{app_label}: <code>{u.get('app_id') or '-'}</code>\n"
        f"{sub_label}: {chip}\n"
        f"{exp_label}: <code>{expires_at}</code>\n"
    )

def _profile_text(lang: str, u: Dict[str, Any]) -> str:
    title = _tf(lang, "promp.profile", "الملف الشخصي")
    name_label = _tf(lang, "promp.name", "الاسم")
    links_label = _tf(lang, "promp.links", "الروابط")

    tg = u.get("telegram", {}) or {}
    tg_block = _tg_line(lang, tg)
    links_s = _fmt_links(u.get("links") or [])

    return (
        "🪪 <b>" + title + "</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{name_label}: <b>{u.get('name','-')}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{links_label}:\n{links_s}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{tg_block}\n"
    )

def _profile_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ " + _tf(lang,"promp.edit.name","تعديل الاسم"), callback_data="promp:edit:name"),
            InlineKeyboardButton(text="🔗 " + _tf(lang,"promp.edit.links","تعديل الروابط"), callback_data="promp:edit:links"),
        ],
        [InlineKeyboardButton(text="✈️ " + _tf(lang,"promp.edit.tg","تعديل معرف تيليجرام"), callback_data="promp:edit:tg")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promp.btn.back","رجوع"), callback_data="promp:open")],
    ])

def _sub_text(lang: str, u: Dict[str, Any]) -> str:
    sub = u.get("subscription", {}) or {}
    st = sub.get("status", "none")
    started = _ts_to_str(sub.get("started_at"))
    expires = _ts_to_str(sub.get("expires_at"))
    left = max(0, int(sub.get("expires_at", 0) or 0) - _now())
    left_s = _format_duration(left, lang)
    rb = int(sub.get("remind_before_h", 24) or 24)
    friendly = {
        "active": _tf(lang,"promp.sub.active","نشط"),
        "pending": _tf(lang,"promp.sub.pending","بانتظار التفعيل"),
        "denied": _tf(lang,"promp.sub.denied","مرفوض"),
        "none": _tf(lang,"promp.sub.none","لا يوجد"),
    }.get(st, st)
    return (
        f"🎫 <b>{_tf(lang,'promp.sub.title','تفاصيل الاشتراك')}</b>\n\n"
        f"{_tf(lang,'promp.sub.status','الحالة')}: <b>{friendly}</b>\n"
        f"{_tf(lang,'promp.sub.started','بدأ في')}: <code>{started}</code>\n"
        f"{_tf(lang,'promp.sub.expires','ينتهي في')}: <code>{expires}</code>\n"
        f"{_tf(lang,'promp.sub.left','الوقت المتبقي')}: <b>{left_s}</b>\n"
        f"{_tf(lang,'promp.sub.remind','تنبيه قبل الانتهاء')}: <code>{rb}h</code>\n"
    )

def _sub_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔔 24h", callback_data="promp:remind:24"),
            InlineKeyboardButton(text="🔔 48h", callback_data="promp:remind:48"),
            InlineKeyboardButton(text="🔔 72h", callback_data="promp:remind:72"),
            InlineKeyboardButton(text="🔕 " + _tf(lang,"promp.remind.off","إيقاف"), callback_data="promp:remind:0"),
        ],
        [InlineKeyboardButton(text="📨 " + _tf(lang,"promp.sub.renew","طلب تجديد"), callback_data="promp:renew")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promp.btn.back","رجوع"), callback_data="promp:open")],
    ])

# === تجديد الاشتراك: أدوات مساعدة ===
def _renew_menu_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="7d",  callback_data=f"promp:adm:renew:{uid}:7"),
            InlineKeyboardButton(text="30d", callback_data=f"promp:adm:renew:{uid}:30"),
            InlineKeyboardButton(text="60d", callback_data=f"promp:adm:renew:{uid}:60"),
            InlineKeyboardButton(text="90d", callback_data=f"promp:adm:renew:{uid}:90"),
        ],
        [InlineKeyboardButton(text=_tf(lang, "promp.renew.custom", "مدة مخصصة"), callback_data=f"promp:adm:renew_custom:{uid}")],
    ])

def _apply_extend_seconds(u: Dict[str, Any], add_seconds: int) -> int:
    """يمدّد الاشتراك: من تاريخ الانتهاء إن كان نشطًا، أو من الآن إن كان منتهيًا. يعيد expires_at الجديد."""
    sub = u.setdefault("subscription", {})
    now = _now()
    expires_at = int(sub.get("expires_at", 0) or 0)
    base_ts = expires_at if (sub.get("status") == "active" and expires_at > now) else now
    new_expires = base_ts + max(0, int(add_seconds))
    sub["status"] = "active"
    if not int(sub.get("started_at", 0) or 0):
        sub["started_at"] = now
    sub["expires_at"] = new_expires
    return new_expires


# ===== حالات FSM =====
class EditProfile(StatesGroup):
    name  = State()
    links = State()
    tg    = State()

class Activate(StatesGroup):
    appid = State()

class ProofState(StatesGroup):
    wait = State()

# دعم مباشر (مستخدم/أدمن)
class SupportUser(StatesGroup):
    chatting = State()

class SupportAdmin(StatesGroup):
    chatting = State()

# دعم مباشر (مستخدم/أدمن)
class RenewAdmin(StatesGroup):
    wait_days = State()


# ===== فتح اللوحة =====
@router.callback_query(F.data.in_({"prom:panel", "promp:open"}))
async def open_panel(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not _is_promoter(cb.from_user.id):
        return await cb.answer(_tf(lang, "prom.not_approved", "هذه اللوحة للمروّجين الموافق عليهم فقط."), show_alert=True)
    d = _load(); u = _u(d, cb.from_user.id)
    await cb.message.answer(_panel_text(lang, u), reply_markup=_panel_kb(lang), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()

# ===== ملفي / تعديل =====
@router.callback_query(F.data == "promp:profile")
async def profile_view(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    d = _load(); u = _u(d, cb.from_user.id)
    await cb.message.answer(_profile_text(lang, u), reply_markup=_profile_kb(lang), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "promp:edit:name")
async def edit_name_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(EditProfile.name)
    await cb.message.answer(_tf(lang,"promp.ask.name","أرسل الاسم الجديد:"))
    await cb.answer()

@router.message(EditProfile.name, F.text.len() >= 2)
async def edit_name_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    d = _load(); u = _u(d, m.from_user.id)
    u["name"] = m.text.strip()
    _save(d)
    await state.clear()
    await m.answer(_tf(lang,"promp.ok","تم الحفظ ✅"))
    await m.answer(_profile_text(lang, u), reply_markup=_profile_kb(lang), parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "promp:edit:links")
async def edit_links_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(EditProfile.links)
    await cb.message.answer(_tf(lang,"promp.ask.links","أرسل الروابط، كل رابط في سطر منفصل:"))
    await cb.answer()

@router.message(EditProfile.links, F.text)
async def edit_links_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    links = [s.strip() for s in (m.text or "").splitlines() if s.strip()]
    d = _load(); u = _u(d, m.from_user.id)
    u["links"] = links
    _save(d)
    await state.clear()
    await m.answer(_tf(lang,"promp.ok","تم الحفظ ✅"))
    await m.answer(_profile_text(lang, u), reply_markup=_profile_kb(lang), parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "promp:edit:tg")
async def edit_tg_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(EditProfile.tg)
    await cb.message.answer(_tf(lang,"promp.ask.tg","أرسل معرف تيليجرام بالشكل @username:"))
    await cb.answer()

@router.message(EditProfile.tg, F.text.regexp(r"^@?[A-Za-z0-9_]{5,}$"))
async def edit_tg_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    tg = m.text.strip()
    if not tg.startswith("@"): tg = "@" + tg
    d = _load(); u = _u(d, m.from_user.id)
    tg_real = ("@" + m.from_user.username) if m.from_user.username else None
    u["telegram"] = {"declared": tg, "real": tg_real, "match": bool(tg_real and tg_real.lower() == tg.lower())}
    _save(d)
    await state.clear()
    await m.answer(_tf(lang,"promp.ok","تم الحفظ ✅"))
    await m.answer(_profile_text(lang, u), reply_markup=_profile_kb(lang), parse_mode=ParseMode.HTML)

@router.message(EditProfile.tg)
async def edit_tg_invalid(m: Message):
    lang = L(m.from_user.id)
    await m.answer(_tf(lang,"prom.err.tg","المعرّف غير صالح. مثال: @MyChannel"))

# ===== الاشتراك =====
@router.callback_query(F.data == "promp:sub")
async def sub_view(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    d = _load(); u = _u(d, cb.from_user.id)
    await cb.message.answer(_sub_text(lang, u), reply_markup=_sub_kb(lang), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data.startswith("promp:remind:"))
async def sub_set_remind(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    hours = int(cb.data.split(":")[-1])
    d = _load(); u = _u(d, cb.from_user.id)
    u.setdefault("subscription", {})["remind_before_h"] = max(0, hours)
    _save(d)
    await cb.answer(_tf(lang,"promp.saved","تم الحفظ ✅"), show_alert=False)

# طلب تجديد من المستخدم (بدون مدة ثابتة)
@router.callback_query(F.data == "promp:renew")
async def sub_request_renew(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    # أرسل لكل الأدمنين طلبًا مع أزرار مدد سريعة + مدة مخصصة
    for admin_id in ADMIN_IDS:
        try:
            head = _tf(lang, "promp.renew.head", "🔁 طلب تجديد")
            await cb.bot.send_message(
                admin_id,
                f"{head} — {_tf(lang,'promp.renew.user_id','المستخدم')}: <code>{cb.from_user.id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=_renew_menu_kb(cb.from_user.id, lang)
            )
        except Exception:
            pass
    await cb.answer(_tf(lang, "promp.renew.sent", "تم إرسال طلب التجديد إلى الإدارة ✅"), show_alert=True)

# ===== تفعيل الاشتراك (App ID) =====
@router.callback_query(F.data == "promp:activate")
async def activate_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(Activate.appid)
    await cb.message.answer(_tf(lang,"promp.ask.appid","أرسل App ID الخاص بتطبيق \"ثعبان\" لتفعيل اشتراكك:"))
    await cb.answer()

@router.message(Activate.appid, F.text)
async def activate_receive(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    appid = m.text.strip()
    d = _load(); u = _u(d, m.from_user.id)
    u["app_id"] = appid
    sub = u.setdefault("subscription", {})
    sub["status"] = "pending"
    sub["requested_at"] = _now()
    _save(d)
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تفعيل 30d", callback_data=f"promp:adm:activate:{m.from_user.id}:30"),
            InlineKeyboardButton(text="✅ تفعيل 90d", callback_data=f"promp:adm:activate:{m.from_user.id}:90"),
        ],
        [InlineKeyboardButton(text="❌ رفض", callback_data=f"promp:adm:deny:{m.from_user.id}")],
    ])
    txt = (
        f"🚀 <b>{_tf(L(m.from_user.id),'promp.adm.activate_req','طلب تفعيل اشتراك مروّج')}</b>\n"
        f"{_tf(L(m.from_user.id),'promp.user_id','المستخدم')}: <code>{m.from_user.id}</code> — "
        f"<a href='tg://user?id={m.from_user.id}'>{_tf(L(m.from_user.id),'promp.open_chat','فتح المحادثة')}</a>\n"
        f"{_tf(L(m.from_user.id),'promp.app_id','معرّف التطبيق')} : <code>{appid}</code>\n"
    )
    for admin_id in ADMIN_IDS:
        try:
            await m.bot.send_message(admin_id, txt, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception: pass

    await m.answer(_tf(lang,"promp.activate.sent","تم استلام App ID وسيتم تفعيل اشتراكك بعد مراجعة الإدارة ✅"))

@router.callback_query(F.data.startswith("promp:adm:activate:"))
async def adm_activate(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    parts = cb.data.split(":")  # promp:adm:activate:<uid>:<days>
    uid = parts[-2]; days = int(parts[-1])
    d = _load()
    u = d.get("users", {}).get(uid)
    if not u: return await cb.answer(_tf(L(cb.from_user.id),"common.not_found","Not found."), show_alert=True)
    start = _now()
    expires = start + days * 24 * 3600
    sub = u.setdefault("subscription", {})
    sub.update({"status":"active","started_at":start,"expires_at":expires})
    _save(d)
    try:
        lang = L(int(uid))
        await cb.bot.send_message(int(uid),
            _tf(lang,"promp.sub.activated","تم تفعيل اشتراكك ✅") +
            f"\n{_tf(lang,'promp.sub.expires','ينتهي في')}: {_ts_to_str(expires)}"
        )
    except Exception: pass
    await cb.answer(_tf(L(cb.from_user.id),"common.done","Done ✅"), show_alert=True)

@router.callback_query(F.data.startswith("promp:adm:deny:"))
async def adm_deny(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    uid = cb.data.split(":")[-1]
    d = _load()
    u = d.get("users", {}).get(uid)
    if not u: return await cb.answer(_tf(L(cb.from_user.id),"common.not_found","Not found."), show_alert=True)
    sub = u.setdefault("subscription", {})
    sub["status"] = "denied"
    _save(d)
    try:
        lang = L(int(uid))
        await cb.bot.send_message(int(uid), _tf(lang,"promp.sub.denied_msg","عذرًا، رُفض طلب تفعيل الاشتراك."))
    except Exception: pass
    await cb.answer(_tf(L(cb.from_user.id),"common.denied","Denied"), show_alert=True)

# تجديد سريع من الأدمن: promp:adm:renew:<uid>:<days>
@router.callback_query(F.data.startswith("promp:adm:renew:"))
async def adm_renew_quick(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    parts = cb.data.split(":")  # promp:adm:renew:<uid>:<days>
    uid = parts[-2]
    days = int(parts[-1])
    d = _load()
    u = d.get("users", {}).get(uid)
    if not u:
        return await cb.answer(_tf(L(cb.from_user.id),"common.not_found","Not found."), show_alert=True)

    new_expires = _apply_extend_seconds(u, days * 24 * 3600)
    _save(d)

    # أخطر المستخدم
    try:
        lang_user = L(int(uid))
        await cb.bot.send_message(
            int(uid),
            _tf(lang_user, "promp.renew.approved", "تم تجديد اشتراكك ✅") +
            f"\n{_tf(lang_user, 'promp.sub.expires', 'ينتهي في')}: {_ts_to_str(new_expires)}"
        )
    except Exception:
        pass

    await cb.answer(_tf(L(cb.from_user.id),"common.ok","OK ✅"), show_alert=True)

# بدء المدة المخصصة: promp:adm:renew_custom:<uid>
@router.callback_query(F.data.startswith("promp:adm:renew_custom:"))
async def adm_renew_custom_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    await state.set_state(RenewAdmin.wait_days)
    await state.update_data(target_uid=uid)
    await cb.message.answer(_tf(L(cb.from_user.id),
        "promp.renew.custom.ask",
        "أدخل مدة التجديد (أيام) مثل 45 أو 120. يمكنك أيضًا استخدام h للساعات مثل 12h:"
    ))
    await cb.answer()

# استقبال المدة المخصصة من الأدمن
@router.message(RenewAdmin.wait_days)
async def adm_renew_custom_value(m: Message, state: FSMContext):
    if m.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    if not uid:
        await state.clear()
        return

    s = (m.text or "").strip().lower()
    seconds = 0
    try:
        if s.endswith("h"):
            hours = int(s[:-1])
            seconds = hours * 3600
        elif s.endswith("d"):
            days = int(s[:-1])
            seconds = days * 24 * 3600
        else:
            # اعتبره أيامًا إذا لم يُذكر لاحقة
            days = int(s)
            seconds = days * 24 * 3600
    except Exception:
        return await m.reply(_tf(L(m.from_user.id), "promp.renew.custom.invalid", "قيمة غير صالحة. أعد المحاولة."))

    if seconds <= 0:
        return await m.reply(_tf(L(m.from_user.id), "promp.renew.custom.invalid", "قيمة غير صالحة. أعد المحاولة."))

    d = _load()
    u = d.get("users", {}).get(str(uid))
    if not u:
        await state.clear()
        return await m.reply(_tf(L(m.from_user.id),"common.not_found","Not found."))

    new_expires = _apply_extend_seconds(u, seconds)
    _save(d)
    await state.clear()

    # أخطر المستخدم
    try:
        lang_user = L(int(uid))
        await m.bot.send_message(
            int(uid),
            _tf(lang_user, "promp.renew.approved", "تم تجديد اشتراكك ✅") +
            f"\n{_tf(lang_user, 'promp.sub.expires', 'ينتهي في')}: {_ts_to_str(new_expires)}"
        )
    except Exception:
        pass

    await m.reply(_tf(L(m.from_user.id), "promp.renew.custom.done", "تم التجديد ✅"))


# ===== إثبات نشاط =====
@router.callback_query(F.data == "promp:proof")
async def proof_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(ProofState.wait)
    await cb.message.answer(_tf(lang,"promp.proof.ask","أرسل صورة/فيديو أو رابط يثبت نشاطك (بث مباشر/فيديو جديد)..."))
    await cb.answer()

@router.message(ProofState.wait, F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO, ContentType.TEXT}))
async def proof_receive(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    d = _load(); u = _u(d, m.from_user.id)
    item: Dict[str, Any] = {"t": _now(), "kind": m.content_type}
    if m.photo:
        item["photo"] = m.photo[-1].file_id
    if m.video:
        item["video"] = m.video.file_id
        item["caption"] = m.caption or ""
    if m.text and not (m.text.startswith("/")):
        item["text"] = m.text
    u.setdefault("activities", []).append(item)
    _save(d)
    await state.clear()
    # إخطار الأدمن
    txt = f"{_tf(lang,'promp.proof.head','📣 إثبات نشاط')} {_tf(lang,'promp.user_id','المستخدم')}: <code>{m.from_user.id}</code>\n"
    for admin_id in ADMIN_IDS:
        try:
            if m.photo:
                await m.bot.send_photo(admin_id, m.photo[-1].file_id, caption=txt, parse_mode=ParseMode.HTML)
            elif m.video:
                await m.bot.send_video(admin_id, m.video.file_id, caption=txt, parse_mode=ParseMode.HTML)
            else:
                await m.bot.send_message(admin_id, txt + (m.text or ""), parse_mode=ParseMode.HTML)
        except Exception: pass
    await m.answer(_tf(lang,"promp.proof.ok","شكرًا! تم إرسال الإثبات للإدارة ✅"))

# ====== دعم مباشر (محادثة ثنائية) ======
ACTIVE_SUPPORT: dict[int, int] = {}  # user_id -> admin_id
ADMIN_ACTIVE: dict[int, int] = {}    # admin_id -> user_id

def _claim_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=_tf(lang, "promp.support.claim", "استلام المحادثة ↩️"),
            callback_data=f"promp:support:claim:{uid}"
        )
    ]])

def _admin_controls_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=_tf(lang, "promp.support.end", "إنهاء المحادثة 🛑"),
            callback_data=f"promp:support:end:{uid}"
        )
    ]])

async def _clear_state_for(bot, storage, user_id: int):
    """تفريغ حالة FSM لطرف آخر (User/Admin)."""
    try:
        key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
        await storage.set_state(key, None)
        await storage.set_data(key, {})
    except Exception:
        pass

async def _end_chat(bot, uid: int, admin_id: int, lang_user: str, lang_admin: str, storage):
    ACTIVE_SUPPORT.pop(uid, None)
    ADMIN_ACTIVE.pop(admin_id, None)
    # امسح حالات FSM للطرفين
    await _clear_state_for(bot, storage, uid)
    await _clear_state_for(bot, storage, admin_id)
    # أبلغ الطرفين
    try:
        await bot.send_message(uid, _tf(lang_user, "promp.support.closed_user", "تم إنهاء المحادثة."))
    except Exception:
        pass
    try:
        await bot.send_message(admin_id, _tf(lang_admin, "promp.support.closed_admin", "تم إنهاء المحادثة مع المستخدم."))
    except Exception:
        pass

@router.callback_query(F.data == "promp:support")
async def support_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    # لا تسمح ببدء المحادثة من حساب أدمن (لمنع محادثة النفس)
    if cb.from_user.id in ADMIN_IDS:
        return await cb.answer(
            _tf(lang, "promp.support.self_forbidden",
                "لا يمكنك بدء محادثة دعم من حساب الأدمن. استخدم حسابًا آخر للاختبار."),
            show_alert=True
        )
    await state.set_state(SupportUser.chatting)
    await cb.message.answer(
        _tf(lang, "promp.support.ask",
            "أرسل رسالتك للدعم الآن (نص/صورة/فيديو/ملف). أرسل /cancel لإلغاء.")
    )
    await cb.answer()

# إلغاء من جهة المروّج
@router.message(SupportUser.chatting, F.text == "/cancel")
async def support_cancel_user(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    uid = m.from_user.id
    admin_id = ACTIVE_SUPPORT.get(uid)

    await state.clear()
    if admin_id:
        ADMIN_ACTIVE.pop(admin_id, None)
        ACTIVE_SUPPORT.pop(uid, None)
        try:
            await m.bot.send_message(admin_id, _tf(lang, "promp.support.user_left", "المستخدم أنهى المحادثة."))
        except Exception:
            pass

    await m.answer(_tf(lang, "promp.cancel", "تم الإلغاء."))

# رسائل المروّج أثناء الجلسة
@router.message(SupportUser.chatting)
async def support_user_message(m: Message, state: FSMContext):
    lang_user = L(m.from_user.id)
    uid = m.from_user.id
    admin_id = ACTIVE_SUPPORT.get(uid)

    # إن كانت الجلسة مستلمة — وجّه للأدمن فقط
    if admin_id:
        # حماية إضافية: لا توجّه للأدمن لو كان هو نفس الشخص
        if admin_id == uid:
            return
        try:
            copy_kwargs = dict(parse_mode=ParseMode.HTML)
            if m.caption:
                copy_kwargs["caption"] = m.caption
            await m.copy_to(admin_id, **copy_kwargs)
        except Exception:
            pass
        return

    # لم تُستلم بعد: أرسل لجميع الأدمن (عدا نفس المستخدم إن كان أدمن)
    recipients = [a for a in ADMIN_IDS if a != uid]
    if not recipients:
        await m.answer(_tf(lang_user, "promp.support.no_admins",
                           "لا يوجد أعضاء دعم متاحون حاليًا."))
        return

    for a in recipients:
        adm_lang = L(a)
        head = (
            f"🆘 <b>{_tf(adm_lang,'promp.support.head','رسالة دعم من مروّج')}</b>\n"
            f"{_tf(adm_lang,'promp.user_id','المستخدم')}: <code>{uid}</code>"
        )
        try:
            await m.bot.send_message(
                a,
                head,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            copy_kwargs = dict(
                parse_mode=ParseMode.HTML,
                reply_markup=_claim_kb(uid, adm_lang),
            )
            if m.caption:
                copy_kwargs["caption"] = m.caption

            await m.copy_to(a, **copy_kwargs)
        except Exception:
            # تجاهل أخطاء الإرسال لأدمن معيّن
            pass

    await m.answer(_tf(lang_user, "promp.support.wait_admin",
                       "تم إرسال رسالتك. بانتظار انضمام أحد أعضاء الدعم…"))

# أدمن يضغط "استلام المحادثة"
@router.callback_query(F.data.startswith("promp:support:claim:"))
async def support_claim(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        lang_admin = L(cb.from_user.id)
        return await cb.answer(_tf(lang_admin,'common.admins_only','Admins only.'), show_alert=True)

    lang_admin = L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])

    # منع استلام محادثة مع النفس
    if uid == cb.from_user.id:
        return await cb.answer(
            _tf(lang_admin, "promp.support.self_claim", "لا يمكنك استلام محادثة مع نفسك. جرّب بحساب آخر."),
            show_alert=True
        )

    if uid in ACTIVE_SUPPORT:
        other = ACTIVE_SUPPORT[uid]
        if other == cb.from_user.id:
            return await cb.answer(_tf(lang_admin, "promp.support.already_yours", "هذه الجلسة لديك بالفعل."), show_alert=True)
        else:
            return await cb.answer(_tf(lang_admin, "promp.support.already_taken", "تم استلام الجلسة من أدمن آخر."), show_alert=True)

    # اربط الجلسة
    ACTIVE_SUPPORT[uid] = cb.from_user.id
    ADMIN_ACTIVE[cb.from_user.id] = uid

    # اضبط حالة الأدمن محادثة
    await state.set_state(SupportAdmin.chatting)
    await state.update_data(with_uid=uid)

    lang_user = L(uid)
    try:
        await cb.bot.send_message(uid, _tf(lang_user, "promp.support.agent_joined", "انضمّ أحد أعضاء الدعم للمحادثة."))
    except Exception:
        pass
    try:
        await cb.message.answer(
            _tf(lang_admin, "promp.support.claimed", f"تم استلام الجلسة مع المستخدم <code>{uid}</code>."),
            reply_markup=_admin_controls_kb(uid, lang_admin),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    await cb.answer(_tf(lang_admin, "promp.support.you_are_live", "أنت الآن في محادثة مباشرة. أرسل رسالتك."), show_alert=False)

# زر إنهاء المحادثة من الأدمن
@router.callback_query(F.data.startswith("promp:support:end:"))
async def support_end_btn(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer(_tf(L(cb.from_user.id),'common.admins_only','Admins only.'), show_alert=True)

    uid = int(cb.data.split(":")[-1])
    admin_id = cb.from_user.id
    if ACTIVE_SUPPORT.get(uid) != admin_id:
        return await cb.answer(_tf(L(cb.from_user.id),'promp.support.not_yours','هذه الجلسة ليست لك.'), show_alert=True)

    await _end_chat(cb.bot, uid, admin_id, L(uid), L(admin_id), state.storage)
    await cb.answer(_tf(L(cb.from_user.id),'common.ok','OK'))

# رسائل الأدمن أثناء الجلسة
@router.message(SupportAdmin.chatting)
async def support_admin_message(m: Message, state: FSMContext):
    if m.from_user.id not in ADMIN_IDS:
        return

    data = await state.get_data()
    uid = data.get("with_uid")
    if not uid:
        return

    # لو الأدمن == المستخدم (حماية مضاعفة)
    if uid == m.from_user.id:
        await m.answer(_tf(L(m.from_user.id), "promp.support.self_echo",
                           "هذه محادثة مع نفسك؛ الرسائل لن تُوجَّه. استخدم حسابًا آخر للاختبار."))
        return

    # أوامر إنهاء
    if (m.text or "").strip().lower() in {"/end", "/cancel"}:
        await _end_chat(m.bot, uid, m.from_user.id, L(uid), L(m.from_user.id), state.storage)
        return

    try:
        await m.copy_to(uid, caption=m.caption, parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ===== حمايات عامة =====
@router.message(EditProfile.name)
@router.message(EditProfile.links)
@router.message(EditProfile.tg)
@router.message(Activate.appid)
@router.message(ProofState.wait)
@router.message(SupportUser.chatting)
async def guard_text(_m: Message):
    # ممر آمن لأي محتوى غير متوقع في هذه الحالات
    pass
