# handlers/promoter_panel.py
from __future__ import annotations

import os, json, time, logging
from pathlib import Path
from typing import Any, Dict, Optional

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    Message, CallbackQuery, ContentType,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

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

# ===== أدوات عامة =====
def _now() -> int: return int(time.time())
def L(uid: int) -> str: return (get_user_lang(uid) or "ar").strip().lower()

def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    return fallback

def _format_duration(sec: int, lang: str) -> str:
    sec = max(0, int(sec)); m = sec // 60; h = m // 60; d = h // 24
    if d >= 1: return f"{d} " + (_tf(lang,"prom.time.days","يوم" if lang=="ar" else "d"))
    if h >= 1: return f"{h} " + (_tf(lang,"prom.time.hours","ساعة" if lang=="ar" else "h"))
    if m >= 1: return f"{m} " + (_tf(lang,"prom.time.minutes","دقيقة" if lang=="ar" else "m"))
    return f"{sec} " + (_tf(lang,"prom.time.seconds","ثانية" if lang=="ar" else "s"))

def _duration_short(sec: int, lang: str) -> str:
    sec = max(0, int(sec)); m = sec // 60; h = m // 60; d = h // 24
    if d >= 1: return f"{d}{_tf(lang,'prom.time.short.days','ي' if lang=='ar' else 'd')}"
    if h >= 1: return f"{h}{_tf(lang,'prom.time.short.hours','س' if lang=='ar' else 'h')}"
    if m >= 1: return f"{m}{_tf(lang,'prom.time.short.minutes','د' if lang=='ar' else 'm')}"
    return f"{sec}{_tf(lang,'prom.time.short.seconds','ث' if lang=='ar' else 's')}"

def _since_phrase(start_ts: int, lang: str) -> str:
    sec = max(0, _now() - int(start_ts or 0))
    lead = _tf(lang, "promp.live.since", "منذ" if lang=="ar" else "since")
    if sec < 60:
        unit = _tf(lang, "prom.time.seconds", "ثانية" if lang=="ar" else "s")
        return f"{lead} {sec} {unit}" if lang=="ar" else f"{sec} {unit} ago"
    mins = sec // 60
    if mins < 60:
        unit = _tf(lang, "prom.time.minutes", "دقيقة" if lang=="ar" else "min")
        return f"{lead} {mins} {unit}" if lang=="ar" else f"{mins} {unit} ago"
    hrs = mins // 60
    if hrs < 24:
        unit = _tf(lang, "prom.time.hours", "ساعة" if lang=="ar" else "h")
        return f"{lead} {hrs} {unit}" if lang=="ar" else f"{hrs} {unit} ago"
    days = hrs // 24
    unit = _tf(lang, "prom.time.days", "يوم" if lang=="ar" else "d")
    return f"{lead} {days} {unit}" if lang=="ar" else f"{days} {unit} ago"

def _ts_to_str(ts: Optional[int]) -> str:
    if not ts: return "—"
    try: return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(ts))) + " UTC"
    except Exception: return "—"

def _is_http_url(s: str) -> bool:
    return isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))

# ===== I/O =====
def _load() -> Dict[str, Any]:
    if STORE_FILE.exists():
        try: return json.loads(STORE_FILE.read_text("utf-8"))
        except Exception: pass
    return {"users": {}}

def _save(d: Dict[str, Any]) -> None:
    try: STORE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e: log.warning(f"[promoter_panel] save failed: {e}")

def _u(d: Dict[str, Any], uid: int | str) -> Dict[str, Any]:
    return d.setdefault("users", {}).setdefault(str(uid), {
        "status": "approved",
        "name": "-",
        "links": [],          # يدوية
        "auto_links": [],     # تُملأ تلقائيًا من تفاصيل البث
        "telegram": {"declared": "-", "real": None, "match": False},
        "app_id": None,
        "subscription": {"status": "none", "started_at": 0, "expires_at": 0, "remind_before_h": 24},
        "activities": []
    })

def _is_promoter(uid: int) -> bool:
    d = _load(); u = d.get("users", {}).get(str(uid))
    return bool(u and u.get("status") == "approved")

def _is_admin(uid: int) -> bool: return uid in ADMIN_IDS

# ========= Links merge/dedupe =========
def _merged_links(u: Dict[str, Any]) -> list[str]:
    manual = [x for x in (u.get("links") or []) if x and isinstance(x, str)]
    auto   = [x for x in (u.get("auto_links") or []) if x and isinstance(x, str)]
    seen = set()
    out = []
    for s in manual + auto:
        k = s.strip()
        if not k or k in seen: continue
        seen.add(k); out.append(k)
    return out[:10]  # حدّ علوي منطقي

def _add_auto_link(u: Dict[str, Any], url: str) -> None:
    if not _is_http_url(url): return
    arr = u.setdefault("auto_links", [])
    if url not in arr:
        arr.insert(0, url)
        del arr[10:]  # حافظ على آخر 10 روابط

# ========= Helpers للعرض =========
def _fmt_links(links: list[str]) -> str:
    if not links: return "—"
    out = []
    for x in links:
        s = (x or "").strip()
        if not s: continue
        if s.startswith(("http://","https://","tg://")): out.append(f"• <a href=\"{s}\">{s}</a>")
        else: out.append(f"• {s}")
    return "\n".join(out) if out else "—"

def _fmt_links_short(links: list[str], limit: int = 2) -> str:
    items = []
    for x in (links or []):
        s = (x or "").strip()
        if not s: continue
        if s.startswith(("http://","https://","tg://")):
            text = s if len(s) <= 60 else (s[:57] + "…")
            items.append(f"<a href=\"{s}\">{text}</a>")
        else:
            items.append(s)
        if len(items) >= limit: break
    return " · ".join(items) if items else "—"

def _chip(text: str) -> str: return f"<span class=\"tg-spoiler\">{text}</span>"

def _tg_line(lang: str, tg: dict) -> str:
    decl = tg.get("declared") or "-"; real = tg.get("real") or "-"; match = bool(tg.get("match"))
    mark = "✅" if match else "❗️"
    real_lbl = _tf(lang, "promp.tg.real_label", "المعرّف الفعلي على تيليجرام" if lang=="ar" else "Actual Telegram label")
    decl_lbl = _tf(lang, "promp.tg.declared_label", "المعرّف المعلن على تيليجرام" if lang=="ar" else "Declared Telegram label")
    return f"{real_lbl}: <code>{real}</code> {mark}\n({decl_lbl}: <code>{decl}</code>)"

def _panel_text(lang: str, u: Dict[str, Any]) -> str:
    title = _tf(lang, "promp.title", "لوحة المروّجين" if lang=="ar" else "Promoters Panel")
    name_label = _tf(lang, "promp.name", "الاسم" if lang=="ar" else "Name")
    links_label = _tf(lang, "promp.links", "الروابط" if lang=="ar" else "Links")
    app_label = _tf(lang, "promp.app_id", "معرّف التطبيق" if lang=="ar" else "App ID")
    sub_label = _tf(lang, "promp.sub", "الاشتراك" if lang=="ar" else "Subscription")
    exp_label = _tf(lang, "promp.sub.expires", "ينتهي في" if lang=="ar" else "Expires at")
    sub = u.get("subscription", {}) or {}
    left = max(0, int(sub.get("expires_at", 0) or 0) - _now()); left_s = _format_duration(left, lang) if left else None
    chip = _chip(("✅ " + _tf(lang,"promp.sub.active","نشط" if lang=="ar" else "Active")) + (f" — {(_tf(lang,'promp.sub.left','تبقّى' if lang=='ar' else 'Left'))}: {left_s}" if left_s else "")) if (sub.get("status")=="active") else _chip("🚫 "+_tf(lang,"promp.sub.none","لا يوجد" if lang=="ar" else "None"))
    expires_at = _ts_to_str(sub.get("expires_at"))
    tg = u.get("telegram", {}) or {}; tg_block = _tg_line(lang, tg)
    links_s = _fmt_links(_merged_links(u))
    return ("🧑‍💼 <b>"+title+"</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{name_label}: <b>{u.get('name','-')}</b>\n"
            f"{tg_block}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{links_label}:\n{links_s}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{app_label}: <code>{u.get('app_id') or '-'}</code>\n"
            f"{sub_label}: {chip}\n"
            f"{exp_label}: <code>{expires_at}</code>\n")

def _profile_text(lang: str, u: Dict[str, Any]) -> str:
    title = _tf(lang, "promp.profile", "الملف الشخصي" if lang=="ar" else "Profile")
    name_label = _tf(lang, "promp.name", "الاسم" if lang=="ar" else "Name")
    links_label = _tf(lang, "promp.links", "الروابط" if lang=="ar" else "Links")
    tg = u.get("telegram", {}) or {}; tg_block = _tg_line(lang, tg)
    links_s = _fmt_links(_merged_links(u))
    return ("🪪 <b>"+title+"</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{name_label}: <b>{u.get('name','-')}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{links_label}:\n{links_s}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{tg_block}\n")

def _profile_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ " + _tf(lang,"promp.edit.name","تعديل الاسم" if lang=="ar" else "Edit name"),
                              callback_data="promp:edit:name"),
         InlineKeyboardButton(text="🔗 " + _tf(lang,"promp.edit.links","تعديل الروابط" if lang=="ar" else "Edit links"),
                              callback_data="promp:edit:links")],
        [InlineKeyboardButton(text="✈️ " + _tf(lang,"promp.edit.tg","تعديل معرف تيليجرام" if lang=="ar" else "Edit Telegram"),
                              callback_data="promp:edit:tg")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back"),
                              callback_data="promp:open")],
    ])

# ========= الاشتراك =========
def _sub_text(lang: str, u: Dict[str, Any]) -> str:
    sub = u.get("subscription", {}) or {}
    st = (sub.get("status") or "none").lower()
    friendly = {
        "active": _tf(lang,"promp.sub.active","نشط" if lang=="ar" else "Active"),
        "pending": _tf(lang,"promp.sub.pending","بانتظار التفعيل" if lang=="ar" else "Pending"),
        "denied": _tf(lang,"promp.sub.denied","مرفوض" if lang=="ar" else "Denied"),
        "none": _tf(lang,"promp.sub.none","لا يوجد" if lang=="ar" else "None"),
    }.get(st, st)
    started = _ts_to_str(sub.get("started_at"))
    expires = _ts_to_str(sub.get("expires_at"))
    left = max(0, int(sub.get("expires_at", 0) or 0) - _now())
    left_s = _format_duration(left, lang)
    rb = int(sub.get("remind_before_h", 24) or 24)
    return (
        f"🎫 <b>{_tf(lang,'promp.sub.title','تفاصيل الاشتراك' if lang=='ar' else 'Subscription')}</b>\n\n"
        f"{_tf(lang,'promp.sub.status','الحالة' if lang=='ar' else 'Status')}: <b>{friendly}</b>\n"
        f"{_tf(lang,'promp.sub.started','بدأ في' if lang=='ar' else 'Started')}: <code>{started}</code>\n"
        f"{_tf(lang,'promp.sub.expires','ينتهي في' if lang=='ar' else 'Expires')}: <code>{expires}</code>\n"
        f"{_tf(lang,'promp.sub.left','الوقت المتبقي' if lang=='ar' else 'Time left')}: <b>{left_s}</b>\n"
        f"{_tf(lang,'promp.sub.remind','تنبيه قبل الانتهاء' if lang=='ar' else 'Remind before end')}: <code>{rb}h</code>\n"
    )

def _sub_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 24h", callback_data="promp:remind:24"),
         InlineKeyboardButton(text="🔔 48h", callback_data="promp:remind:48"),
         InlineKeyboardButton(text="🔔 72h", callback_data="promp:remind:72"),
         InlineKeyboardButton(text="🔕 " + _tf(lang,"promp.remind.off","إيقاف" if lang=="ar" else "Off"),
                              callback_data="promp:remind:0")],
        [InlineKeyboardButton(text="📨 " + _tf(lang,"promp.sub.renew","طلب تجديد" if lang=="ar" else "Request renewal"),
                              callback_data="promp:renew")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back"),
                              callback_data="promp:open")],
    ])

def _renew_menu_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7d",  callback_data=f"promp:adm:renew:{uid}:7"),
         InlineKeyboardButton(text="30d", callback_data=f"promp:adm:renew:{uid}:30"),
         InlineKeyboardButton(text="60d", callback_data=f"promp:adm:renew:{uid}:60"),
         InlineKeyboardButton(text="90d", callback_data=f"promp:adm:renew:{uid}:90")],
        [InlineKeyboardButton(text=_tf(lang,"promp.renew.custom","مدة مخصصة" if lang=="ar" else "Custom duration"),
                              callback_data=f"promp:adm:renew_custom:{uid}")],
    ])

def _apply_extend_seconds(u: Dict[str, Any], add_seconds: int) -> int:
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

class SupportUser(StatesGroup):
    chatting = State()

class SupportAdmin(StatesGroup):
    chatting = State()

class RenewAdmin(StatesGroup):
    wait_days = State()

class LiveStart(StatesGroup):
    pick_platform      = State()
    ask_platform_name  = State()
    ask_handle         = State()
    ask_title          = State()
    ask_duration       = State()
    ask_duration_custom = State()
    ask_display        = State()

# ===== منصات وعرضها =====
_PLAT_ICONS = {
    "youtube":"▶️","tiktok":"🎵","telegram":"✈️",
    "instagram":"📸","facebook":"📘","twitch":"🎮",
    "other":"🧩",
}
def _plat_icon(p:str)->str: return _PLAT_ICONS.get((p or "").lower(),"🔗")

def _plat_label(lang:str,p:str)->str:
    p=(p or "").lower()
    fallback_ar={"youtube":"يوتيوب","tiktok":"تيك توك","telegram":"تيليجرام","instagram":"إنستغرام","facebook":"فيسبوك","twitch":"تويتش","other":"أخرى"}
    fallback_en={"youtube":"YouTube","tiktok":"TikTok","telegram":"Telegram","instagram":"Instagram","facebook":"Facebook","twitch":"Twitch","other":"Other"}
    fb = (fallback_ar if lang=="ar" else fallback_en).get(p, p.capitalize() or "Link")
    return _tf(lang, f"plat.{p}", fb)

def _plat_label_custom(lang: str, platform: str, *, rec: dict | None = None, name: str | None = None) -> str:
    p = (platform or "").lower()
    if p == "other":
        label = name or (rec and (rec.get("platform_name") or rec.get("display_platform")))
        if label and str(label).strip():
            return str(label)
        return _tf(lang, "plat.other", "أخرى" if lang=="ar" else "Other")
    return _plat_label(lang, p)

def _live_platforms_kb(lang: str) -> InlineKeyboardMarkup:
    platforms = ["youtube","tiktok","twitch","telegram","instagram","facebook","other"]
    kb = InlineKeyboardBuilder()
    for p in platforms:
        kb.add(InlineKeyboardButton(text=f"{_plat_icon(p)} {_plat_label(lang,p)}", callback_data=f"promp:live:plat:{p}"))
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=_tf(lang,"promp.btn.back","⬅️ رجوع" if lang=="ar" else "⬅️ Back"), callback_data="promp:open"))
    return kb.as_markup()

def _make_url(platform: str, handle: str) -> str:
    p=(platform or "").lower().strip(); h=(handle or "").strip()
    if h.startswith("http"): return h
    if p=="youtube":   return f"https://www.youtube.com/{h.lstrip('@')}"
    if p=="tiktok":    return f"https://www.tiktok.com/@{h.lstrip('@')}"
    if p=="instagram": return f"https://www.instagram.com/{h.lstrip('@')}"
    if p=="facebook":  return f"https://www.facebook.com/{h}"
    if p=="telegram":  return f"https://t.me/{h.lstrip('@')}"
    if p=="twitch":    return f"https://www.twitch.tv/{h.lstrip('@')}"
    return h

# ===== مخزن البث =====
try:
    from utils.promoter_live_store import (
        start_live as live_start,
        end_live as live_end,
        get_user_active as live_get_user_active,
        list_active as live_list_active,
        count_active_lives as live_count_active,
    )
except Exception:
    def live_start(uid:int, **kw): return {"id":"0","user_id":uid,**kw,"started_at":_now(),"expires_at":_now()+24*3600}
    def live_end(live_id:str): return None
    def live_get_user_active(uid:int): return None
    def live_list_active(platform=None, page=1, per_page=50): return [], 1, 0
    def live_count_active(platform=None): return 0

DURATION_MIN_H = 0.5
DURATION_MAX_H = 24.0

def _parse_duration_to_hours(s: str) -> Optional[float]:
    if not s: return None
    txt = s.strip().lower().replace(" ", "").replace(",", ".")
    if txt.endswith("m"):
        try: val = float(txt[:-1]) / 60.0
        except Exception: return None
    elif txt.endswith("h"):
        try: val = float(txt[:-1])
        except Exception: return None
    else:
        try: val = float(txt)
        except Exception: return None
    if val < DURATION_MIN_H or val > DURATION_MAX_H:
        return None
    return val

# ===== لوحة المروّج =====
def _panel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪪 " + _tf(lang,"promp.btn.profile","معلوماتي / تعديل" if lang=="ar" else "My profile / Edit"), callback_data="promp:profile")],
        [InlineKeyboardButton(text="🎫 " + _tf(lang,"promp.btn.sub","اشتراكي" if lang=="ar" else "My subscription"), callback_data="promp:sub")],
        [InlineKeyboardButton(text="🚀 " + _tf(lang,"promp.btn.activate","تفعيل الاشتراك (App ID)" if lang=="ar" else "Activate (App ID)"), callback_data="promp:activate")],
        [InlineKeyboardButton(text="📤 " + _tf(lang,"promp.btn.proof","رفع إثبات نشاط" if lang=="ar" else "Upload activity proof"), callback_data="promp:proof")],
        [InlineKeyboardButton(text="🆘 " + _tf(lang,"promp.btn.support","دعم مباشر" if lang=="ar" else "Direct support"), callback_data="promp:support")],
        [InlineKeyboardButton(text="🎥 " + _tf(lang,"promp.btn.live","بدء بث مباشر" if lang=="ar" else "Start Live"), callback_data="promp:live:start")],
        [InlineKeyboardButton(text="⬅️ " + _tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back"), callback_data="back_to_menu"),
         InlineKeyboardButton(text="🔄 " + _tf(lang,"promp.btn.refresh","تحديث" if lang=="ar" else "Refresh"), callback_data="promp:open")],
    ])

@router.callback_query(F.data.in_({"prom:panel", "promp:open"}))
async def open_panel(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not _is_promoter(cb.from_user.id):
        return await cb.answer(_tf(lang, "prom.not_approved", "هذه اللوحة للمروّجين الموافق عليهم فقط." if lang=="ar" else "Promoters only."), show_alert=True)
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
    await cb.message.answer(_tf(lang,"promp.ask.name","أرسل الاسم الجديد:" if lang=="ar" else "Send new name:"))
    await cb.answer()

@router.message(EditProfile.name, F.text.len() >= 2)
async def edit_name_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    d = _load(); u = _u(d, m.from_user.id)
    u["name"] = (m.text or "").strip()
    _save(d)
    await state.clear()
    await m.answer(_tf(lang,"promp.ok","تم الحفظ ✅" if lang=="ar" else "Saved ✅"))
    await m.answer(_profile_text(lang, u), reply_markup=_profile_kb(lang), parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "promp:edit:links")
async def edit_links_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(EditProfile.links)
    await cb.message.answer(_tf(lang,"promp.ask.links","أرسل الروابط، كل رابط في سطر منفصل:" if lang=="ar" else "Send links, one per line:"))
    await cb.answer()

@router.message(EditProfile.links, F.text)
async def edit_links_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    links = [s.strip() for s in (m.text or "").splitlines() if s.strip()]
    d = _load(); u = _u(d, m.from_user.id)
    u["links"] = links
    _save(d)
    await state.clear()
    await m.answer(_tf(lang,"promp.ok","تم الحفظ ✅" if lang=="ar" else "Saved ✅"))
    await m.answer(_profile_text(lang, u), reply_markup=_profile_kb(lang), parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "promp:edit:tg")
async def edit_tg_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(EditProfile.tg)
    await cb.message.answer(_tf(lang,"promp.ask.tg","أرسل معرف تيليجرام بالشكل @username:" if lang=="ar" else "Send Telegram @username:"))
    await cb.answer()

@router.message(EditProfile.tg, F.text.regexp(r"^@?[A-Za-z0-9_]{5,}$"))
async def edit_tg_save(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    tg = (m.text or "").strip()
    if not tg.startswith("@"): tg = "@" + tg
    d = _load(); u = _u(d, m.from_user.id)
    tg_real = ("@" + m.from_user.username) if m.from_user.username else None
    u["telegram"] = {"declared": tg, "real": tg_real, "match": bool(tg_real and tg_real.lower() == tg.lower())}
    _save(d)
    await state.clear()
    await m.answer(_tf(lang,"promp.ok","تم الحفظ ✅" if lang=="ar" else "Saved ✅"))
    await m.answer(_profile_text(lang, u), reply_markup=_profile_kb(lang), parse_mode=ParseMode.HTML)

@router.message(EditProfile.tg)
async def edit_tg_invalid(m: Message):
    lang = L(m.from_user.id)
    await m.answer(_tf(lang,"prom.err.tg","المعرّف غير صالح. مثال: @MyChannel" if lang=="ar" else "Invalid handle. Example: @MyChannel"))

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
    await cb.answer(_tf(lang,"promp.saved","تم الحفظ ✅" if lang=="ar" else "Saved ✅"), show_alert=False)

@router.callback_query(F.data == "promp:renew")
async def sub_request_renew(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    for admin_id in ADMIN_IDS:
        try:
            head = _tf(lang, "promp.renew.head", "🔁 طلب تجديد" if lang=="ar" else "🔁 Renewal request")
            await cb.bot.send_message(
                admin_id,
                f"{head} — {_tf(lang,'promp.renew.user_id','المستخدم' if lang=='ar' else 'User')}: <code>{cb.from_user.id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=_renew_menu_kb(cb.from_user.id, lang)
            )
        except Exception:
            pass
    await cb.answer(_tf(lang, "promp.renew.sent", "تم إرسال طلب التجديد إلى الإدارة ✅" if lang=="ar" else "Renewal request sent ✅"), show_alert=True)

# ===== تفعيل الاشتراك (App ID) =====
@router.callback_query(F.data == "promp:activate")
async def activate_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(Activate.appid)
    await cb.message.answer(_tf(lang,"promp.ask.appid","أرسل App ID الخاص بالتطبيق لتفعيل اشتراكك:" if lang=="ar" else "Send the App ID to activate your subscription:"))
    await cb.answer()

@router.message(Activate.appid, F.text)
async def activate_receive(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    appid = (m.text or "").strip()
    d = _load(); u = _u(d, m.from_user.id)
    u["app_id"] = appid
    sub = u.setdefault("subscription", {})
    sub["status"] = "pending"; sub["requested_at"] = _now()
    _save(d); await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تفعيل 30d", callback_data=f"promp:adm:activate:{m.from_user.id}:30"),
         InlineKeyboardButton(text="✅ تفعيل 90d", callback_data=f"promp:adm:activate:{m.from_user.id}:90")],
        [InlineKeyboardButton(text="❌ رفض", callback_data=f"promp:adm:deny:{m.from_user.id}")],
    ])
    txt = (
        f"🚀 <b>{_tf(lang,'promp.adm.activate_req','طلب تفعيل اشتراك مروّج' if lang=='ar' else 'Promoter activation request')}</b>\n"
        f"{_tf(lang,'promp.user_id','المستخدم' if lang=='ar' else 'User')}: <code>{m.from_user.id}</code> — "
        f"<a href='tg://user?id={m.from_user.id}'>{_tf(lang,'promp.open_chat','فتح المحادثة' if lang=='ar' else 'Open chat')}</a>\n"
        f"{_tf(lang,'promp.app_id','معرّف التطبيق' if lang=='ar' else 'App ID')} : <code>{appid}</code>\n"
    )
    for admin_id in ADMIN_IDS:
        try: await m.bot.send_message(admin_id, txt, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception: pass
    await m.answer(_tf(lang,"promp.activate.sent","تم استلام App ID وسيتم التفعيل بعد مراجعة الإدارة ✅" if lang=="ar" else "App ID received, admin will activate soon ✅"))

@router.callback_query(F.data.startswith("promp:adm:activate:"))
async def adm_activate(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    parts = cb.data.split(":")  # promp:adm:activate:<uid>:<days>
    uid = parts[-2]; days = int(parts[-1])
    d = _load(); u = d.get("users", {}).get(uid)
    if not u: return await cb.answer(_tf(L(cb.from_user.id),"common.not_found","Not found."), show_alert=True)
    start = _now(); expires = start + days * 24 * 3600
    sub = u.setdefault("subscription", {}); sub.update({"status":"active","started_at":start,"expires_at":expires})
    _save(d)
    try:
        lang = L(int(uid))
        await cb.bot.send_message(int(uid),
            _tf(lang,"promp.sub.activated","تم تفعيل اشتراكك ✅" if lang=="ar" else "Your subscription is active ✅") +
            f"\n{_tf(lang,'promp.sub.expires','ينتهي في' if lang=='ar' else 'Expires at')}: {_ts_to_str(expires)}"
        )
    except Exception: pass
    await cb.answer(_tf(L(cb.from_user.id),"common.done","Done ✅"), show_alert=True)

@router.callback_query(F.data.startswith("promp:adm:deny:"))
async def adm_deny(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    uid = cb.data.split(":")[-1]
    d = _load(); u = d.get("users", {}).get(uid)
    if not u: return await cb.answer(_tf(L(cb.from_user.id),"common.not_found","Not found."), show_alert=True)
    sub = u.setdefault("subscription", {}); sub["status"] = "denied"; _save(d)
    try:
        lang = L(int(uid))
        await cb.bot.send_message(int(uid), _tf(lang,"promp.sub.denied_msg","عذرًا، رُفض طلب التفعيل." if lang=="ar" else "Sorry, activation request was denied."))
    except Exception: pass
    await cb.answer(_tf(L(cb.from_user.id),"common.denied","Denied"), show_alert=True)

@router.callback_query(F.data.startswith("promp:adm:renew:"))
async def adm_renew_quick(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    parts = cb.data.split(":")  # promp:adm:renew:<uid>:<days>
    uid = parts[-2]; days = int(parts[-1])
    d = _load(); u = d.get("users", {}).get(uid)
    if not u: return await cb.answer(_tf(L(cb.from_user.id),"common.not_found","Not found."), show_alert=True)
    new_expires = _apply_extend_seconds(u, days * 24 * 3600); _save(d)
    try:
        lang_user = L(int(uid))
        await cb.bot.send_message(
            int(uid),
            _tf(lang_user, "promp.renew.approved", "تم تجديد اشتراكك ✅" if lang_user=="ar" else "Your subscription was renewed ✅") +
            f"\n{_tf(lang_user, 'promp.sub.expires', 'ينتهي في' if lang_user=='ar' else 'Expires at')}: {_ts_to_str(new_expires)}"
        )
    except Exception: pass
    await cb.answer(_tf(L(cb.from_user.id),"common.ok","OK ✅"), show_alert=True)

@router.callback_query(F.data.startswith("promp:adm:renew_custom:"))
async def adm_renew_custom_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer(_tf(L(cb.from_user.id),"common.admins_only","Admins only."), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    await state.set_state(RenewAdmin.wait_days); await state.update_data(target_uid=uid)
    await cb.message.answer(_tf(L(cb.from_user.id),"promp.renew.custom.ask",
        "أدخل مدة التجديد (أيام) مثل 45 أو 120. يمكنك أيضًا استخدام h للساعات مثل 12h:" if L(cb.from_user.id)=="ar"
        else "Enter renewal duration, e.g. 45 or 120 (days). You can also use hours with 'h' like 12h:"))
    await cb.answer()

@router.message(RenewAdmin.wait_days)
async def adm_renew_custom_value(m: Message, state: FSMContext):
    if m.from_user.id not in ADMIN_IDS: return
    data = await state.get_data(); uid = data.get("target_uid")
    if not uid: await state.clear(); return
    s = (m.text or "").strip().lower(); seconds = 0
    try:
        if s.endswith("h"): seconds = int(s[:-1]) * 3600
        elif s.endswith("d"): seconds = int(s[:-1]) * 24 * 3600
        else: seconds = int(s) * 24 * 3600
    except Exception:
        return await m.reply(_tf(L(m.from_user.id), "promp.renew.custom.invalid", "قيمة غير صالحة. أعد المحاولة." if L(m.from_user.id)=="ar" else "Invalid value. Try again."))
    if seconds <= 0:
        return await m.reply(_tf(L(m.from_user.id), "promp.renew.custom.invalid", "قيمة غير صالحة. أعد المحاولة." if L(m.from_user.id)=="ar" else "Invalid value. Try again."))
    d = _load(); u = d.get("users", {}).get(str(uid))
    if not u: await state.clear(); return await m.reply(_tf(L(m.from_user.id),"common.not_found","Not found."))
    new_expires = _apply_extend_seconds(u, seconds); _save(d); await state.clear()
    try:
        lang_user = L(int(uid))
        await m.bot.send_message(
            int(uid),
            _tf(lang_user, "promp.renew.approved", "تم تجديد اشتراكك ✅" if lang_user=="ar" else "Your subscription was renewed ✅") +
            f"\n{_tf(lang_user, 'promp.sub.expires', 'ينتهي في' if lang_user=='ar' else 'Expires at')}: {_ts_to_str(new_expires)}"
        )
    except Exception: pass
    await m.reply(_tf(L(m.from_user.id), "promp.renew.custom.done", "تم التجديد ✅" if L(m.from_user.id)=="ar" else "Renewed ✅"))

# ===== إثبات نشاط =====
@router.callback_query(F.data == "promp:proof")
async def proof_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(ProofState.wait)
    await cb.message.answer(_tf(lang,"promp.proof.ask","أرسل صورة/فيديو أو رابط يثبت نشاطك (بث مباشر/فيديو جديد)..." if lang=="ar" else "Send a photo/video/link that proves your activity…"))
    await cb.answer()

@router.message(ProofState.wait, F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO, ContentType.TEXT}))
async def proof_receive(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    d = _load(); u = _u(d, m.from_user.id)
    item: Dict[str, Any] = {"t": _now(), "kind": m.content_type}
    if m.photo: item["photo"] = m.photo[-1].file_id
    if m.video: item["video"] = m.video.file_id; item["caption"] = m.caption or ""
    if m.text and not (m.text.startswith("/")): item["text"] = m.text
    u.setdefault("activities", []).append(item); _save(d); await state.clear()
    txt = f"{_tf(lang,'promp.proof.head','📣 إثبات نشاط' if lang=='ar' else '📣 Activity proof')} {_tf(lang,'promp.user_id','المستخدم' if lang=='ar' else 'User')}: <code>{m.from_user.id}</code>\n"
    for admin_id in ADMIN_IDS:
        try:
            if m.photo: await m.bot.send_photo(admin_id, m.photo[-1].file_id, caption=txt, parse_mode=ParseMode.HTML)
            elif m.video: await m.bot.send_video(admin_id, m.video.file_id, caption=txt, parse_mode=ParseMode.HTML)
            else: await m.bot.send_message(admin_id, txt + (m.text or ""), parse_mode=ParseMode.HTML)
        except Exception: pass
    await m.answer(_tf(lang,"promp.proof.ok","شكرًا! تم إرسال الإثبات للإدارة ✅" if lang=="ar" else "Thanks! Your proof was sent to admins ✅"))

# ====== دعم مباشر ======
ACTIVE_SUPPORT: dict[int, int] = {}
ADMIN_ACTIVE: dict[int, int] = {}

def _claim_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tf(lang, "promp.support.claim", "استلام المحادثة ↩️" if lang=="ar" else "Claim chat ↩️"),
                             callback_data=f"promp:support:claim:{uid}")
    ]])

def _admin_controls_kb(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tf(lang, "promp.support.end", "إنهاء المحادثة 🛑" if lang=="ar" else "End chat 🛑"),
                             callback_data=f"promp:support:end:{uid}")
    ]])

async def _clear_state_for(bot, storage, user_id: int):
    try:
        key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
        await storage.set_state(key, None); await storage.set_data(key, {})
    except Exception: pass

async def _end_chat(bot, uid: int, admin_id: int, lang_user: str, lang_admin: str, storage):
    ACTIVE_SUPPORT.pop(uid, None); ADMIN_ACTIVE.pop(admin_id, None)
    await _clear_state_for(bot, storage, uid); await _clear_state_for(bot, storage, admin_id)
    try: await bot.send_message(uid, _tf(lang_user, "promp.support.closed_user", "تم إنهاء المحادثة." if lang_user=="ar" else "Chat ended."))
    except Exception: pass
    try: await bot.send_message(admin_id, _tf(lang_admin, "promp.support.closed_admin", "تم إنهاء المحادثة مع المستخدم." if lang_admin=="ar" else "Chat with the user was ended."))
    except Exception: pass

@router.callback_query(F.data == "promp:support")
async def support_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if cb.from_user.id in ADMIN_IDS:
        return await cb.answer(_tf(lang, "promp.support.self_forbidden","لا يمكنك بدء محادثة دعم من حساب الأدمن." if lang=="ar" else "You can't start support from an admin account."), show_alert=True)
    await state.set_state(SupportUser.chatting)
    await cb.message.answer(_tf(lang, "promp.support.ask","أرسل رسالتك للدعم الآن… أرسل /cancel للإلغاء." if lang=="ar" else "Send your support message now… Type /cancel to cancel."))
    await cb.answer()

@router.message(SupportUser.chatting, F.text == "/cancel")
async def support_cancel_user(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    uid = m.from_user.id; admin_id = ACTIVE_SUPPORT.get(uid)
    await state.clear()
    if admin_id:
        ADMIN_ACTIVE.pop(admin_id, None); ACTIVE_SUPPORT.pop(uid, None)
        try: await m.bot.send_message(admin_id, _tf(lang, "promp.support.user_left", "المستخدم أنهى المحادثة." if lang=="ar" else "User ended the chat."))
        except Exception: pass
    await m.answer(_tf(lang, "promp.cancel", "تم الإلغاء." if lang=="ar" else "Cancelled."))

@router.message(SupportUser.chatting)
async def support_user_message(m: Message, state: FSMContext):
    lang_user = L(m.from_user.id); uid = m.from_user.id; admin_id = ACTIVE_SUPPORT.get(uid)
    if admin_id:
        if admin_id == uid: return
        try:
            copy_kwargs = dict(parse_mode=ParseMode.HTML)
            if m.caption: copy_kwargs["caption"] = m.caption
            await m.copy_to(admin_id, **copy_kwargs)
        except Exception: pass
        return
    recipients = [a for a in ADMIN_IDS if a != uid]
    if not recipients:
        await m.answer(_tf(lang_user, "promp.support.no_admins", "لا يوجد أعضاء دعم متاحون حاليًا." if lang_user=="ar" else "No support agents available right now."))
        return
    for a in recipients:
        adm_lang = L(a)
        head = (f"🆘 <b>{_tf(adm_lang,'promp.support.head','رسالة دعم من مروّج' if adm_lang=='ar' else 'Support message from promoter')}</b>\n"
                f"{_tf(adm_lang,'promp.user_id','المستخدم' if adm_lang=='ar' else 'User')}: <code>{uid}</code>")
        try:
            await m.bot.send_message(a, head, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            copy_kwargs = dict(parse_mode=ParseMode.HTML, reply_markup=_claim_kb(uid, adm_lang))
            if m.caption: copy_kwargs["caption"] = m.caption
            await m.copy_to(a, **copy_kwargs)
        except Exception: pass
    await m.answer(_tf(lang_user, "promp.support.wait_admin", "تم إرسال رسالتك. بانتظار انضمام أحد أعضاء الدعم…" if lang_user=="ar" else "Message sent. Waiting for a support agent…"))

@router.callback_query(F.data.startswith("promp:support:claim:"))
async def support_claim(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer(_tf(L(cb.from_user.id),'common.admins_only','Admins only.'), show_alert=True)
    lang_admin = L(cb.from_user.id); uid = int(cb.data.split(":")[-1])
    if uid == cb.from_user.id:
        return await cb.answer(_tf(lang_admin, "promp.support.self_claim", "لا يمكنك استلام محادثة مع نفسك." if lang_admin=="ar" else "You can't claim a chat with yourself."), show_alert=True)
    if uid in ACTIVE_SUPPORT:
        other = ACTIVE_SUPPORT[uid]
        if other == cb.from_user.id:
            return await cb.answer(_tf(lang_admin, "promp.support.already_yours", "هذه الجلسة لديك بالفعل." if lang_admin=="ar" else "Already yours."), show_alert=True)
        else:
            return await cb.answer(_tf(lang_admin, "promp.support.already_taken", "تم استلام الجلسة من أدمن آخر." if lang_admin=="ar" else "Already taken."), show_alert=True)
    ACTIVE_SUPPORT[uid] = cb.from_user.id; ADMIN_ACTIVE[cb.from_user.id] = uid
    await state.set_state(SupportAdmin.chatting); await state.update_data(with_uid=uid)
    lang_user = L(uid)
    try: await cb.bot.send_message(uid, _tf(lang_user, "promp.support.agent_joined", "انضمّ أحد أعضاء الدعم للمحادثة." if lang_user=="ar" else "A support agent joined the chat."))
    except Exception: pass
    try:
        await cb.message.answer(_tf(lang_admin, "promp.support.claimed", f"تم استلام الجلسة مع المستخدم <code>{uid}</code>." if lang_admin=="ar" else f"Chat with <code>{uid}</code> claimed."),
                                reply_markup=_admin_controls_kb(uid, lang_admin), parse_mode=ParseMode.HTML)
    except Exception: pass
    await cb.answer(_tf(lang_admin, "promp.support.you_are_live", "أنت الآن في محادثة مباشرة. أرسل رسالتك." if lang_admin=="ar" else "You're live. Send your messages."), show_alert=False)

@router.callback_query(F.data.startswith("promp:support:end:"))
async def support_end_btn(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer(_tf(L(cb.from_user.id),'common.admins_only','Admins only.'), show_alert=True)
    uid = int(cb.data.split(":")[-1]); admin_id = cb.from_user.id
    if ACTIVE_SUPPORT.get(uid) != admin_id:
        return await cb.answer(_tf(L(cb.from_user.id),'promp.support.not_yours','هذه الجلسة ليست لك.' if L(cb.from_user.id)=="ar" else "This session is not yours."), show_alert=True)
    await _end_chat(cb.bot, uid, admin_id, L(uid), L(admin_id), state.storage)
    await cb.answer(_tf(L(cb.from_user.id),'common.ok','OK'))

@router.message(SupportAdmin.chatting)
async def support_admin_message(m: Message, state: FSMContext):
    if m.from_user.id not in ADMIN_IDS: return
    data = await state.get_data(); uid = data.get("with_uid")
    if not uid: return
    if uid == m.from_user.id:
        await m.answer(_tf(L(m.from_user.id), "promp.support.self_echo", "هذه محادثة مع نفسك؛ الرسائل لن تُوجَّه." if L(m.from_user.id)=="ar" else "This would echo to yourself; use another account."))
        return
    if (m.text or "").strip().lower() in {"/end", "/cancel"}:
        await _end_chat(m.bot, uid, m.from_user.id, L(uid), L(m.from_user.id), state.storage); return
    try: await m.copy_to(uid, caption=m.caption, parse_mode=ParseMode.HTML)
    except Exception: pass

# ===== حمايات عامة =====
@router.message(EditProfile.name)
@router.message(EditProfile.links)
@router.message(EditProfile.tg)
@router.message(Activate.appid)
@router.message(ProofState.wait)
@router.message(SupportUser.chatting)
async def guard_text(_m: Message):
    pass

# =====================  LIVE STREAMS  =====================

# زر البث العام للجميع
@router.callback_query(F.data == "promp:live")
async def live_public_entry(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    text, kb = _render_public_list(lang, "all", 1)
    await cb.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()

# بدء البث من داخل لوحة المروّج
@router.callback_query(F.data == "promp:live:start")
async def live_start_entry(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not _is_promoter(cb.from_user.id):
        text, kb = _render_public_list(lang, "all", 1)
        await cb.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return await cb.answer()

    mine = live_get_user_active(cb.from_user.id)
    if mine:
        platform = (mine.get("platform") or "").lower()
        plat_human = _plat_label_custom(lang, platform, rec=mine)
        url = _make_url(platform, mine.get("handle",""))
        ends = _ts_to_str(mine.get("expires_at"))
        txt = (
            f"🎥 <b>{_tf(lang,'promp.live.now','بثك الآن' if lang=='ar' else 'Your live now')}</b>\n"
            f"{_plat_icon(platform)} <a href='{url}'>{plat_human}</a>\n"
            f"🔗 <code>{mine.get('handle','')}</code>\n"
            f"📝 {(mine.get('title') or '—')}\n"
            f"⏱ <code>{_ts_to_str(mine.get('started_at'))}</code>\n"
            f"⌛️ <code>{_tf(lang,'promp.live.ends','ينتهي' if lang=='ar' else 'Ends')}: {ends}</code>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔴 "+_tf(lang,"promp.live.end","إنهاء البث" if lang=="ar" else "End live"), callback_data=f"promp:live:end:{mine['id']}")],
            [InlineKeyboardButton(text="⬅️ "+_tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back"), callback_data="promp:open")],
        ])
        await cb.message.answer(txt, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        return await cb.answer()

    await state.set_state(LiveStart.pick_platform)
    await cb.message.answer(_tf(lang,"promp.live.pick","اختر المنصة:" if lang=="ar" else "Pick a platform:"), reply_markup=_live_platforms_kb(lang))
    await cb.answer()

# اختيار المنصة
@router.callback_query(F.data.regexp(r"^promp:live:plat:(\w+)$"))
async def live_pick_platform(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    plat = cb.data.split(":")[-1].lower()

    if plat == "other":
        await state.update_data(platform="other")
        await state.set_state(LiveStart.ask_platform_name)
        ask = _tf(lang, "promp.live.ask_other_name",
                  "اكتب اسم المنصّة (مثال: Trovo / Kick / …)" if lang=="ar"
                  else "Type the platform name (e.g., Trovo / Kick / …)")
        await cb.message.answer(f"{_plat_icon('other')} <b>{_plat_label_custom(lang,'other')}</b>\n{ask}", parse_mode=ParseMode.HTML)
        return await cb.answer()

    await state.update_data(platform=plat)
    await state.set_state(LiveStart.ask_handle)
    hint = _tf(lang,"promp.live.ask_handle",
               "أرسل اسم المستخدم أو رابط القناة/البث (مثال: @myuser أو https://…)" if lang=="ar"
               else "Send the @handle or full channel/live URL:")
    await cb.message.answer(f"{_plat_icon(plat)} <b>{_plat_label(lang,plat)}</b>\n{hint}", parse_mode=ParseMode.HTML)
    await cb.answer()

@router.message(LiveStart.ask_platform_name, F.text.len() >= 2)
async def live_other_platform_name(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    name = (m.text or "").strip()
    await state.update_data(platform_name=name)
    await state.set_state(LiveStart.ask_handle)
    hint = _tf(lang, "promp.live.ask_other_url",
               "أرسل رابط البث الكامل (مثال: https://example.com/…)" if lang=="ar"
               else "Send the full live URL (e.g., https://example.com/…)")
    await m.answer(hint)

# استقبال المعرّف/الرابط
@router.message(LiveStart.ask_handle, F.text.len() >= 3)
async def live_set_handle(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    data = await state.get_data()
    plat = (data.get("platform") or "").lower()
    handle = (m.text or "").strip()

    if plat == "other":
        if not (handle.startswith("http://") or handle.startswith("https://")):
            return await m.answer(
                _tf(lang, "promp.live.other.url_required",
                    "⚠️ رجاءً أرسل رابطًا كاملاً يبدأ بـ http:// أو https://"
                    if lang=="ar" else
                    "⚠️ Please send a full URL starting with http:// or https://")
            )

    await state.update_data(handle=handle)
    await state.set_state(LiveStart.ask_title)
    await m.answer(_tf(lang, "promp.live.ask_title",
                       "أرسل عنوانًا للبث (اختياري) — أرسل «-» لتخطي."
                       if lang=="ar" else
                       "Send a title (optional) — send '-' to skip."))

# استقبال العنوان → اختيار المدة
@router.message(LiveStart.ask_title, F.text)
async def live_ask_duration(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    title = (m.text or "").strip()
    if title == "-": title = ""
    await state.update_data(title=title)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30m", callback_data="promp:live:dur:30m"),
         InlineKeyboardButton(text="1h",  callback_data="promp:live:dur:1h"),
         InlineKeyboardButton(text="2h",  callback_data="promp:live:dur:2h")],
        [InlineKeyboardButton(text="4h",  callback_data="promp:live:dur:4h"),
         InlineKeyboardButton(text="8h",  callback_data="promp:live:dur:8h"),
         InlineKeyboardButton(text="12h", callback_data="promp:live:dur:12h")],
        [InlineKeyboardButton(text=_tf(lang,"promp.live.dur.custom","مدة مخصّصة" if lang=="ar" else "Custom duration"), callback_data="promp:live:dur:custom")],
        [InlineKeyboardButton(text=_tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back"), callback_data="promp:open")],
    ])
    await state.set_state(LiveStart.ask_duration)
    msg = _tf(lang,"promp.live.dur.ask","اختر مدة البث (من 30 دقيقة حتى 24 ساعة):" if lang=="ar" else "Choose live duration (30m to 24h):")
    await m.answer(msg, reply_markup=kb)

# المدّة الجاهزة
@router.callback_query(F.data.regexp(r"^promp:live:dur:([0-9]+(?:\.[0-9]+)?[hm])$"))
async def live_pick_duration(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    token = cb.data.split(":")[-1]
    hours = _parse_duration_to_hours(token)
    if hours is None:
        return await cb.answer(_tf(lang,"promp.live.dur.invalid","المدّة يجب أن تكون بين 30 دقيقة و24 ساعة." if lang=="ar" else "Duration must be between 30 minutes and 24 hours."), show_alert=True)
    await state.update_data(ttl_hours=hours)

    d = _load(); u = _u(d, cb.from_user.id)
    suggested = (u.get("name") or cb.from_user.full_name or f"User {cb.from_user.id}")
    await state.set_state(LiveStart.ask_display)
    ask = _tf(lang,"promp.live.ask_display","اكتب الاسم الذي سيظهر للمستخدمين (أرسل «-» لاستخدام الافتراضي)" if lang=="ar" else "Send the display name (send '-' to use default)")
    await cb.message.answer(f"{ask}\n<code>{suggested}</code>", parse_mode=ParseMode.HTML)
    await cb.answer()

# المدّة المخصّصة
@router.callback_query(F.data == "promp:live:dur:custom")
async def live_duration_custom(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    await state.set_state(LiveStart.ask_duration_custom)
    ask = _tf(lang,"promp.live.dur.custom.ask","أرسل المدة مثل: 30m, 1h, 1.5h, 90m (المسموح 30m–24h)." if lang=="ar" else "Send duration like: 30m, 1h, 1.5h, 90m (allowed 30m–24h).")
    await cb.message.answer(ask)
    await cb.answer()

@router.message(LiveStart.ask_duration_custom, F.text)
async def live_duration_custom_value(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    hours = _parse_duration_to_hours(m.text or "")
    if hours is None:
        return await m.answer(_tf(lang,"promp.live.dur.custom.invalid","قيمة غير صالحة. استخدم 30m..24h مثل 30m/1h/1.5h/90m." if lang=="ar" else "Invalid value. Use 30m..24h, e.g., 30m/1h/1.5h/90m."))
    await state.update_data(ttl_hours=hours)
    d = _load(); u = _u(d, m.from_user.id)
    suggested = (u.get("name") or m.from_user.full_name or f"User {m.from_user.id}")
    await state.set_state(LiveStart.ask_display)
    ask = _tf(lang,"promp.live.ask_display","اكتب الاسم الذي سيظهر للمستخدمين (أرسل «-» لاستخدام الافتراضي)" if lang=="ar" else "Send the display name (send '-' to use default)")
    await m.answer(f"{ask}\n<code>{suggested}</code>", parse_mode=ParseMode.HTML)

# استقبال اسم العرض → تشغيل البث
@router.message(LiveStart.ask_display, F.text)
async def live_do_start(m: Message, state: FSMContext):
    data = await state.get_data()
    platform = (data.get("platform") or "").lower()
    platform_name = (data.get("platform_name") or "").strip() if platform == "other" else None
    handle = data.get("handle")
    title = data.get("title") or ""
    ttl_hours = float(data.get("ttl_hours") or 24)
    disp = (m.text or "").strip()

    d = _load(); u = _u(d, m.from_user.id)
    display_name = (u.get("name") or m.from_user.full_name or f"User {m.from_user.id}") if (disp == "-" or not disp) else disp

    # حفظ الرابط تلقائيًا في auto_links لظهوره للمستخدمين
    url = _make_url(platform, handle or "")
    if _is_http_url(url):
        _add_auto_link(u, url)
        _save(d)  # احفظ فورًا قبل الإرسال

    rec = live_start(
        m.from_user.id,
        platform=platform,
        handle=handle,
        title=title,
        display_name=display_name,
        ttl_hours=ttl_hours,
        platform_name=platform_name,
    )
    await state.clear()

    lang = L(m.from_user.id)
    plat_human = _plat_label_custom(lang, platform, rec=rec, name=platform_name)
    txt = (
        f"🎥 <b>{_tf(lang,'promp.live.started','تم تشغيل البث ✅' if lang=='ar' else 'Live started ✅')}</b>\n"
        f"👤 {display_name}\n{_plat_icon(platform)} <a href='{url}'>{plat_human}</a>\n"
        f"📝 {(title or '—')}\n"
        f"⏱ <code>{_ts_to_str(rec.get('started_at'))}</code>\n"
        f"⌛️ <code>{_tf(lang,'promp.live.ends','ينتهي' if lang=='ar' else 'Ends')}: {_ts_to_str(rec.get('expires_at'))}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 "+(_tf(lang,"promp.live.end","إنهاء البث" if lang=="ar" else "End live")), callback_data=f"promp:live:end:{rec['id']}")],
        [InlineKeyboardButton(text="⬅️ "+(_tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back")), callback_data="promp:open")],
    ])
    await m.answer(txt, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

    adm_txt = (
        f"📣 LIVE\n"
        f"UID: <code>{m.from_user.id}</code>\n"
        f"👤 {display_name}\n"
        f"{_plat_icon(platform)} {plat_human} — <code>{handle}</code>\n"
        f"📝 {(title or '—')}\n"
        f"⌛️ {_tf(L(m.from_user.id),'promp.live.ends','ينتهي' if lang=='ar' else 'Ends')}: {_ts_to_str(rec.get('expires_at'))}"
    )
    for admin_id in ADMIN_IDS:
        try:
            kb_admin = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔴 " + _tf(L(admin_id), "promp.live.end", "إنهاء البث" if L(admin_id)=="ar" else "End live"),
                    callback_data=f"promp:live:end:{rec['id']}"
                ),
            ]])
            await m.bot.send_message(
                admin_id,
                adm_txt,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
                reply_markup=kb_admin
            )
        except Exception:
            pass

# إنهاء البث
@router.callback_query(F.data.regexp(r"^promp:live:end:(.+)$"))
async def live_end_handler(cb: CallbackQuery):
    lang_admin = L(cb.from_user.id)
    live_id = cb.data.split(":")[-1]

    rec = live_end(live_id)
    if not rec:
        return await cb.answer(
            _tf(lang_admin, "promp.live.not_found",
                "البث غير موجود أو منتهٍ." if lang_admin=="ar" else "Live not found or already ended."),
            show_alert=True
        )

    uid = int(rec.get("user_id") or 0)
    if uid and uid != cb.from_user.id:
        try:
            lang_user = L(uid)
            plat = (rec.get("platform") or "").lower()
            handle = rec.get("handle") or ""
            title = rec.get("title") or "—"
            plat_human = _plat_label_custom(lang_user, plat, rec=rec)
            msg_user = (
                f"🔴 { _tf(lang_user,'promp.live.ended.by_admin','تم إنهاء البث من قبل الإدارة.' if lang_user=='ar' else 'Your live was ended by the admin.') }\n"
                f"{_plat_icon(plat)} {plat_human} — <code>{handle}</code>\n"
                f"📝 {title}"
            )
            await cb.bot.send_message(uid, msg_user, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass

    await cb.answer(
        _tf(lang_admin, "promp.live.ended",
            "تم إنهاء البث." if lang_admin=="ar" else "Live ended."),
        show_alert=True
    )

# =========== القائمة العامة ===========

def _truncate(s: str, n: int) -> str:
    s=(s or "").strip(); return s if len(s)<=n else s[:n-1]+"…"

def _group_by_promoter(items: list[dict]) -> list[dict]:
    grouped: dict[int, dict] = {}
    for r in items:
        uid = int(r.get("user_id") or 0)
        if not uid: continue
        g = grouped.setdefault(uid, {"user_id": uid, "name": r.get("display_name") or f"#{uid}", "streams": []})
        g["streams"].append(r)
    out=[]
    for g in grouped.values():
        plats = {str(x.get("platform","")).lower() for x in g["streams"]}
        g["icons"] = "".join(_PLAT_ICONS.get(p,"🔗") for p in plats)
        g["streams"].sort(key=lambda x:int(x.get("started_at",0)), reverse=True)
        g["since_ts"] = min(int(x.get("started_at",0) or 0) for x in g["streams"]) if g["streams"] else _now()
        out.append(g)
    out.sort(key=lambda g:int(g["streams"][0].get("started_at",0)), reverse=True)
    return out

def _render_public_list(lang: str, _platform_ignored: str, page: int):
    items,_,_ = live_list_active(None, page=1, per_page=200)
    groups=_group_by_promoter(items)
    per_page=6; total=len(groups); pages=max(1,(total+per_page-1)//per_page); page=max(1,min(page,pages))
    start=(page-1)*per_page; shown=groups[start:start+per_page]

    title=_tf(lang,"promp.live.title","بث مباشر للمروّجين" if lang=="ar" else "Promoters Live")
    head=f"🎥 <b>{title}</b>\n{_tf(lang,'promp.live.count','المباشر الآن' if lang=='ar' else 'Live now')}: <b>{total}</b>\n"

    if total==0:
        kb=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 "+_tf(lang,"promp.btn.refresh","تحديث" if lang=="ar" else "Refresh"), callback_data="promp:live"),
        ],[
            InlineKeyboardButton(text=_tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back"), callback_data="back_to_menu")
        ]])
        return head+"\n"+(_tf(lang,"promp.live.none","لا يوجد بث مباشر حاليًا." if lang=="ar" else "No live streams right now.")), kb

    kb=InlineKeyboardBuilder()
    for g in shown:
        name=_truncate(g["name"],22)
        since_short=_duration_short(max(0,_now()-int(g.get("since_ts",_now()))), lang)
        icons=g["icons"] or "🔴"
        btn_txt = f"👤 {name} · ⏱ {since_short} · {icons}"
        kb.row(InlineKeyboardButton(text=btn_txt, callback_data=f"promp:live:view:{g['user_id']}:all:{page}"))

    nav=[]
    if page>1: nav.append(InlineKeyboardButton(text="« "+_tf(lang,"promp.nav.prev","السابق" if lang=="ar" else "Prev"), callback_data=f"promp:live:list:all:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="noop"))
    if page<pages: nav.append(InlineKeyboardButton(text=_tf(lang,"promp.nav.next","التالي" if lang=="ar" else "Next")+" »", callback_data=f"promp:live:list:all:{page+1}"))
    kb.row(*nav)
    kb.row(
        InlineKeyboardButton(text="🔄 "+_tf(lang,"promp.btn.refresh","تحديث" if lang=="ar" else "Refresh"), callback_data=f"promp:live:list:all:{page}"),
        InlineKeyboardButton(text="⬅️ "+_tf(lang,"promp.btn.back","رجوع" if lang=="ar" else "Back"), callback_data="back_to_menu")
    )
    return head, kb.as_markup()

# استبدل الدالة كاملة
def _render_promoter_detail(lang: str, uid: int, platform_ctx: str, page_ctx: int):
    items, _, _ = live_list_active(None, page=1, per_page=200)
    items = [r for r in items if int(r.get("user_id") or 0) == uid]

    store = _load()
    u = store.get("users", {}).get(str(uid)) or {}

    # نعتمد فقط على الروابط القادمة من اللايف بنفسه (وليس روابط البروفايل)
    live_links = _collect_live_links(items)
    links_short = _fmt_links_short(live_links, limit=3)

    if not items:
        txt = _tf(
            lang, "promp.live.none_for_user",
            "هذا المروّج ليس على البث الآن." if lang == "ar" else "This promoter is not live now."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="⬅️ " + _tf(lang, "promp.btn.back", "رجوع" if lang == "ar" else "Back"),
                callback_data=f"promp:live:list:{platform_ctx}:{page_ctx}"
            )
        ]])
        return txt, kb

    name = items[0].get("display_name") or u.get("name") or f"#{uid}"
    title_lbl = _tf(lang, "promp.live.details", "تفاصيل البث" if lang == "ar" else "Live details")
    pro_hdr   = _tf(lang, "promp.live.promoter", "المروّج" if lang == "ar" else "Promoter")
    ends_lbl  = _tf(lang, "promp.live.ends", "ينتهي" if lang == "ar" else "Ends")
    open_lbl  = _tf(lang, "promp.live.open", "فتح البث" if lang == "ar" else "Open stream")
    invalid_link_lbl = _tf(lang, "promp.live.invalid_link", "رابط غير صالح" if lang == "ar" else "Invalid link")
    links_lbl = _tf(lang, "promp.links", "الروابط" if lang == "ar" else "Links")

    txt_lines = [f"👤 <b>{name}</b>", f"🎥 <b>{title_lbl}</b>"]
    kb = InlineKeyboardBuilder()

    for r in items:
        p = (r.get("platform") or "").lower()
        raw_handle = r.get("handle", "") or ""
        url = _make_url(p, raw_handle)
        started = int(r.get("started_at") or 0)
        since = _since_phrase(started, lang)
        stream_title = r.get("title") or "—"
        ends = _ts_to_str(r.get("expires_at"))
        plat_human = _plat_label_custom(lang, p, rec=r)

        txt_lines.append(
            f"{_plat_icon(p)} <b>{plat_human}</b>\n"
            f"📝 {stream_title}\n"
            f"⏱ {since}\n"
            f"⌛️ {ends_lbl}: {ends}"
        )

        if _is_http_url(url):
            kb.row(InlineKeyboardButton(text=f"{_plat_icon(p)} {open_lbl} – {plat_human}", url=url))
        else:
            # لا نضع زر URL إن لم يكن صالحًا، ونذكر القيمة كنص فقط
            txt_lines.append(f"🔗 <code>{raw_handle or '—'}</code>")
            kb.row(InlineKeyboardButton(text=f"{_plat_icon(p)} {invalid_link_lbl}", callback_data="noop"))

    # بطاقة المروّج — بدون تيليجرام (خصوصية) وبروابط اللايف فقط
    txt_lines.append("\n" + f"🪪 <b>{pro_hdr}</b>")
    if live_links:
        txt_lines.append(f"🔗 {links_lbl}: {links_short}")

    kb.row(InlineKeyboardButton(
        text="⬅️ " + _tf(lang, "promp.btn.back", "رجوع" if lang == "ar" else "Back"),
        callback_data=f"promp:live:list:{platform_ctx}:{page_ctx}"
    ))
    kb.row(InlineKeyboardButton(
        text="🔄 " + _tf(lang, "promp.btn.refresh", "تحديث" if lang == "ar" else "Refresh"),
        callback_data=f"promp:live:view:{uid}:{platform_ctx}:{page_ctx}"
    ))

    return "\n\n".join(txt_lines), kb.as_markup()


# ضعها مع بقية الـ helpers
def _collect_live_links(items: list[dict]) -> list[str]:
    """يرجع فقط الروابط http/https المرسلة وقت فتح اللايف (من handle إن كان URL)."""
    out, seen = [], set()
    for r in items:
        h = (r.get("handle") or "").strip()
        if h.startswith(("http://", "https://")) and h not in seen:
            out.append(h); seen.add(h)
    return out


@router.callback_query(F.data.regexp(r"^promp:live:list:([a-z]+|\ball\b):(\d+)$"))
async def live_public_list_nav(cb: CallbackQuery):
    lang=L(cb.from_user.id); parts=cb.data.split(":"); platform=parts[-2]; page=int(parts[-1])
    text, kb = _render_public_list(lang, platform, page)
    await cb.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^promp:live:view:(\d+):([a-z]+|\ball\b):(\d+)$"))
async def live_public_view_promoter(cb: CallbackQuery):
    lang=L(cb.from_user.id); _,_,_, uid_s, platform_ctx, page_ctx = cb.data.split(":")
    uid=int(uid_s); text,kb=_render_promoter_detail(lang, uid, platform_ctx, int(page_ctx))
    await cb.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=False); await cb.answer()

@router.callback_query(F.data == "noop")
async def _noop(cb: CallbackQuery):
    await cb.answer()
