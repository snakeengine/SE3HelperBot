# handlers/home_hero.py
from __future__ import annotations

import os, time, json
from typing import Optional
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from lang import get_user_lang

from lang import t, get_user_lang

# نستخدم الدوال من report.py بدل استدعاء report_cmd
from handlers.report import (
    _is_admin, load_settings, _bl_is_blocked, _next_allowed_dt,
    human_remaining, ReportState
)
import datetime

try:
    from utils.home_card_cfg import get_cfg
except Exception:
    def get_cfg() -> dict:
        return {}

# --- Feature flags guard (with safe fallback)
try:
    from utils.feature_flags import is_enabled
except Exception:
    def is_enabled(_name: str, *, user_id: int | None = None) -> bool:
        return True

router = Router(name="home_hero")

# امنع التفاعل أثناء الدردشة الحيّة + واحد-لواحد (خاص فقط)
try:
    from handlers.live_chat import LiveChat
except Exception:
    class LiveChat:
        active = None

router.message.filter(F.chat.type == "private", ~StateFilter(getattr(LiveChat, "active", None)))
router.callback_query.filter(F.message.chat.type == "private", ~StateFilter(getattr(LiveChat, "active", None)))

# --------- أدوار واقعية (مع fallbacks آمنة) ---------
try:
    from utils.suppliers import is_supplier as _is_supplier
except Exception:
    _is_supplier = None

try:
    from utils.vip_store import is_vip as _is_vip
except Exception:
    _is_vip = None

try:
    from handlers.promoter import is_promoter as _is_promoter
except Exception:
    def _is_promoter(_uid: int) -> bool: return False

# عدّاد البثوث النشطة لعرضه للجميع (زر عام)
try:
    from utils.promoter_live_store import count_active_lives as _count_live
except Exception:
    def _count_live() -> int: return 0

# --------- مصادر بيانات واجهة الإشعارات/المستخدمين ---------
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
USERBOX_FILE = DATA_DIR / "alerts_userbox.json"
KNOWN_USERS_FILE = DATA_DIR / "known_users.json"

def _k(lang: str, key: str, default: str) -> str:
    try:
        v = t(lang, key)
        if isinstance(v, str) and v.strip():
            return v
    except Exception:
        pass
    return default

def _count_known_users() -> Optional[int]:
    try:
        data = json.loads(KNOWN_USERS_FILE.read_text("utf-8"))
        if isinstance(data, dict):
            return len([k for k in data.keys() if str(k).isdigit()])
        if isinstance(data, list):
            return len(data)
    except Exception:
        pass
    return None

def _load_alert_counts(user_id: int, lang: str) -> tuple[int, int]:
    seen = ignored = deleted = set()
    try:
        box = (json.loads(USERBOX_FILE.read_text("utf-8"))).get(str(user_id)) or {}
        seen    = set(box.get("seen", []))
        ignored = set(box.get("ignored", []))
        deleted = set(box.get("deleted", []))
    except Exception:
        pass

    try:
        from utils.alerts_broadcast import get_active_alerts
        items = get_active_alerts(lang) or []
    except Exception:
        items = []

    kept_ids = [it["id"] for it in items if it["id"] not in ignored and it["id"] not in deleted]
    total  = len(kept_ids)
    unseen = len([i for i in kept_ids if i not in seen])
    return total, unseen

def _get_app_version() -> Optional[str]:
    try:
        from utils.version_info import get_version  # type: ignore
        v = get_version()
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:
        pass
    try:
        from utils.version_info import VERSION  # type: ignore
        if isinstance(VERSION, str) and VERSION.strip():
            return VERSION.strip()
    except Exception:
        pass
    for fname in ("VERSION", "version.txt"):
        p = Path(fname)
        if p.exists():
            try:
                v = p.read_text("utf-8").strip()
                if v:
                    return v
            except Exception:
                pass
    v = os.getenv("APP_VERSION")
    if v and v.strip():
        return v.strip()
    return None

# --------- ثوابت الكولباك ---------
CB = {
    "TOOLS": "tools",
    "APP_DOWNLOAD": "app:download",
    "TRUSTED_SUPPLIERS": "trusted_suppliers",
    "CHECK_DEVICE": "check_device",

    # VIP (زر واحد يتبدّل)
    "VIP_OPEN": "vip:open",
    "VIP_PANEL": "vip:open_tools",

    # المروّج (زر واحد يتبدّل)
    "PROMO_INFO": "prom:info",
    "PROMO_PANEL": "prom:panel",
    "PROMO_LIVE": "promp:live",

    # المورّد (زر واحد يتبدّل)
    "SUPPLIER_PUBLIC": "supplier_public",
    "SUPPLIER_PANEL":  "supplier_panel",

    "SECURITY_STATUS": "security_status",
    "SAFE_USAGE": "safe_usage:open",
    "SERVER_STATUS": "server_status",
    "LANG": "change_lang",
    "RESELLER_INFO": "reseller_info",
    "REWARDS": "rewards",
    "REPORT": "report:open",
}

# --------- أزرار القائمة الرئيسية ---------
def _build_main_kb(
    lang: str,
    *,
    is_vip: bool,
    is_promoter: bool,
    is_supplier: bool,
    unseen_alerts: int = 0,
):
    kb = InlineKeyboardBuilder(); row = kb.row

    # السطر 1 — شراء/تنشيط
    row(
        InlineKeyboardButton(
            text="🛒 " + _k(lang, "btn_sevip_buy",
                       "شراء/تنشيط اشتراك SEVIP" if lang == "ar" else "Buy/Activate SEVIP"),
            callback_data="shop:sevip"
        )
    )

    # السطر 2
    row(
        InlineKeyboardButton(
            text="🛍️ " + (
                _k(lang, "btn_supplier_panel", "لوحة المورّد" if lang == "ar" else "Supplier Panel")
                if is_supplier else
                _k(lang, "btn_be_supplier_long", "كيف تصبح مورّدًا؟" if lang == "ar" else "Become a supplier?")
            ),
            callback_data=(CB["SUPPLIER_PUBLIC"] if is_supplier else CB["RESELLER_INFO"])
        ),
        InlineKeyboardButton(
            text="📥 " + _k(lang, "btn_download", "تثبيت تطبيق ثعبان" if lang == "ar" else "Download App"),
            callback_data=CB["APP_DOWNLOAD"]
        ),
    )

    # السطر 3
    row(
        InlineKeyboardButton(
            text="📬 " + (
                (_k(lang, "btn_alerts_inbox", "صندوق الإشعارات" if lang == "ar" else "Alerts Inbox")
                 + (f" ({unseen_alerts})" if unseen_alerts > 0 else ""))
            ),
            callback_data="ibox:list:0:a"
        ),
        InlineKeyboardButton(
            text="🎁 " + _k(lang, "btn_rewards", "الجوائز" if lang == "ar" else "Rewards"),
            callback_data=CB["REWARDS"]
        ),
    )

    # السطر 4
    row(
        InlineKeyboardButton(
            text="🎛️ " + _k(lang, "btn_game_tools", " أدوات الألعاب" if lang == "ar" else "Game Tools"),
            callback_data=CB["TOOLS"]
        ),
        InlineKeyboardButton(
            text="📱 " + _k(lang, "btn_check_device", "تحقق من جهازك" if lang == "ar" else "Check your device"),
            callback_data=CB["CHECK_DEVICE"]
        ),
    )

    # السطر 5
    row(
        InlineKeyboardButton(
            text="🏷️ " + _k(lang, "btn_trusted_suppliers", "المورّدون الموثوقون" if lang == "ar" else "Official suppliers"),
            callback_data=CB["TRUSTED_SUPPLIERS"]
        ),
        InlineKeyboardButton(
            text="🧠 " + _k(lang, "btn_safe_usage", "دليل الاستخدام الآمن" if lang == "ar" else "Safe Usage Guide"),
            callback_data=CB["SAFE_USAGE"]
        ),
    )

    # السطر 6
    row(
        InlineKeyboardButton(
            text="🌐 " + _k(lang, "btn_lang", "اللغة" if lang == "ar" else "Change Language"),
            callback_data=CB["LANG"]
        ),
        InlineKeyboardButton(
            text="📞 " + _k(lang, "btn_contact", "الدعم" if lang == "ar" else "Support"),
            callback_data=CB["REPORT"]
        ),
    )

    # السطر 7 — بث + المروّج
    live_n = _count_live()
    live_label = _k(lang, "btn_promoter_live", "بث مباشر للمروّجين" if lang == "ar" else "Promoters Live")
    if live_n > 0:
        live_label = f"{live_label} ({live_n})"

    if is_promoter:
        row(
            InlineKeyboardButton(text="🎥 " + live_label, callback_data=CB["PROMO_LIVE"]),
            InlineKeyboardButton(
                text="📣 " + _k(lang, "btn_promoter_panel", "لوحة المروّجين" if lang == "ar" else "Promoter Panel"),
                callback_data=CB["PROMO_PANEL"]
            ),
        )
    else:
        row(
            InlineKeyboardButton(text="🎥 " + live_label, callback_data=CB["PROMO_LIVE"]),
            InlineKeyboardButton(
                text="📣 " + _k(lang, "btn_be_promoter", "كيف تصبح مُروّجًا؟" if lang == "ar" else "Become a promoter?"),
                callback_data=CB["PROMO_INFO"]
            ),
        )

        # السطر 8 — زر SEVIP المجاني بالترويج
        row(
            InlineKeyboardButton(
                text=("🎟️ الحصول على اشتراك مجانًا" if lang == "ar" else "🎟️ Get SEVIP for free"),
                callback_data="promo:open",   # ✅ بدل free:open:{lang}
            )
        )

    return kb.as_markup()

# ===== إعدادات العرض =====
cfg = get_cfg()
THEME    = str(cfg.get("theme","neo"))
DENSITY  = str(cfg.get("density","compact"))
SEPARATOR= str(cfg.get("sep","soft"))
ICON_SET = str(cfg.get("icons","modern"))
SHOW_BULLETS = bool(cfg.get("show_bullets", True))
SHOW_TIP     = bool(cfg.get("show_tip", True))
SHOW_VERSION = bool(cfg.get("show_version", True))
SHOW_USERS   = bool(cfg.get("show_users", True))
SHOW_ALERTS  = bool(cfg.get("show_alerts", True))
try:
    from utils.vip_store import get_vip_meta as _get_vip_meta
except Exception:
    _get_vip_meta = None

THEME      = (os.getenv("HOME_CARD_THEME")    or THEME).strip().lower()
DENSITY    = (os.getenv("HOME_CARD_DENSITY")  or DENSITY).strip().lower()
SEPARATOR  = (os.getenv("HOME_CARD_SEP")      or SEPARATOR).strip().lower()
ICON_SET   = (os.getenv("HOME_CARD_ICONS")    or ICON_SET).strip().lower()
SHOW_BULLETS   = (os.getenv("HOME_SHOW_BULLETS", "1") not in {"0","false","False"}) if "HOME_SHOW_BULLETS" in os.environ else SHOW_BULLETS
SHOW_TIP       = (os.getenv("HOME_SHOW_TIP", "1") not in {"0","false","False"})     if "HOME_SHOW_TIP" in os.environ else SHOW_TIP
SHOW_VERSION   = (os.getenv("HOME_SHOW_VERSION", "1") not in {"0","false","False"}) if "HOME_SHOW_VERSION" in os.environ else SHOW_VERSION
SHOW_USERS     = (os.getenv("HOME_SHOW_USERS", "1") not in {"0","false","False"})   if "HOME_SHOW_USERS" in os.environ else SHOW_USERS
SHOW_ALERTS    = (os.getenv("HOME_SHOW_ALERTS", "1") not in {"0","false","False"})  if "HOME_SHOW_ALERTS" in os.environ else SHOW_ALERTS

_LAST_UID: Optional[int] = None


def user_lang_from_update(event) -> str:
    # fallback سريع لو ما كانت محفوظة
    tl = getattr(getattr(event, "from_user", None), "language_code", "") or "en"
    return (tl or "en")[:2]

def _cfg_bool(d: dict, primary: str, alt: str, default: bool) -> bool:
    val = d.get(primary, d.get(alt, default))
    if isinstance(val, bool): return val
    if isinstance(val, str):  return val.lower() not in {"0","false","off"}
    return bool(val)

def _apply_runtime_cfg() -> dict:
    global THEME, DENSITY, SEPARATOR, ICON_SET
    global SHOW_BULLETS, SHOW_TIP, SHOW_VERSION, SHOW_USERS, SHOW_ALERTS

    d = get_cfg()
    THEME     = str(d.get("theme", THEME))
    DENSITY   = str(d.get("density", DENSITY))
    SEPARATOR = str(d.get("sep", SEPARATOR))
    ICON_SET  = str(d.get("icons", ICON_SET))

    SHOW_BULLETS = _cfg_bool(d, "bullets", "show_bullets", SHOW_BULLETS)
    SHOW_TIP     = _cfg_bool(d, "tip", "show_tip", SHOW_TIP)
    SHOW_VERSION = _cfg_bool(d, "version", "show_version", SHOW_VERSION)
    SHOW_USERS   = _cfg_bool(d, "users", "show_users", SHOW_USERS)
    SHOW_ALERTS  = _cfg_bool(d, "alerts", "show_alerts", SHOW_ALERTS)
    return d

def _icon(kind: str) -> str:
    if ICON_SET == "classic":
        mapping = {"title":"🐍","hello":"👋","vip":"👑","role":"⭐","lang":"🌐","alerts":"🔔","users":"👥","ver":"⚙️","sep":"—","ok":"🟢","warn":"⚠️"}
    elif ICON_SET == "minimal":
        mapping = {k:"" for k in ["title","hello","vip","role","lang","alerts","users","ver","sep","ok","warn"]}
    else:
        mapping = {"title":"🐍","hello":"👋","vip":"👑","role":"⭐","lang":"🌐","alerts":"🔔","users":"👥","ver":"⚙️","sep":"⎯","ok":"🟢","warn":"⚠️"}
    return mapping.get(kind, "")

def _line() -> str:
    if SEPARATOR == "hard": return "━" * (20 if DENSITY=="compact" else 28)
    if SEPARATOR == "dots": return "· " * (14 if DENSITY=="compact" else 18)
    if SEPARATOR == "line": return "—" * (22 if DENSITY=="compact" else 30)
    return "⎯" * (18 if DENSITY=="compact" else 26)

def _pad() -> str:
    return "" if DENSITY=="compact" else ("\n" if DENSITY=="normal" else "\n")

def _chip(label: str, value: str, icon: str="") -> str:
    return (icon + (" " if icon else "")) + f"<code>{label}: {value}</code>"

def _fmt_vip_badge(lang: str, user_id: int, is_vip: bool) -> str:
    if not user_id:
        user_id = _LAST_UID or 0
    yes = "نعم" if lang=="ar" else "Yes"
    no  = "لا"  if lang=="ar" else "No"
    if not is_vip:
        return f"{_icon('vip')} <code>VIP: {no}</code>"
    try:
        from utils.vip_store import get_vip_meta as _get_vip_meta_local  # lazy
        meta = _get_vip_meta_local(user_id) or {}
        exp = meta.get("expiry_ts")
        if isinstance(exp, int):
            exp_s = time.strftime("%d-%m-%Y", time.localtime(exp))
            return f"{_icon('vip')} <code>VIP: {yes} · {exp_s}</code>"
    except Exception:
        pass
    return f"{_icon('vip')} <code>VIP: {yes}</code>"

def _hero_html(
    lang: str,
    *,
    first_name: str,
    role_label: str,
    is_vip: bool,
    alerts_total: int,
    alerts_unseen: int,
    users_count: Optional[int],
    app_ver: Optional[str],
    lang_label: str,
) -> str:
    title  = _k(lang, "home_title_plain", "مرحبًا بك في محرك الثعبان" if lang=="ar" else "Welcome to Snake Engine")
    pitch  = _k(lang, "pitch_plain", "منصة قوية لتعديل ألعاب أندرويد — بدون روت وبدون حظر." if lang=="ar" else "Powerful Android modding — no root, no bans.")
    safety = _k(lang, "safety_plain", "الأمان أولًا: خصائص وقائية، محاكي معزول، لا أدوات خطرة." if lang=="ar" else "Safety-first: protective features, sandboxed emulator, no risky tools.")
    cta    = _k(lang, "cta_plain", "ابدأ الآن — اختر أداتك:" if lang=="ar" else "Start now — choose your tool:")
    ok_alert = _k(lang, "hero.status.ok", "لا إشعارات" if lang=="ar" else "All caught up")

    vip_badge   = _fmt_vip_badge(lang, 0, is_vip)
    role_chip   = _chip(_k(lang,"hero.badge.role","الدور" if lang=="ar" else "Role"), role_label, _icon("role"))
    lang_chip   = _chip(_k(lang,"hero.badge.lang","اللغة" if lang=="ar" else "Lang"), lang_label, _icon("lang"))
    ver_chip    = _chip(_k(lang,"hero.badge.version","الإصدار" if lang=="ar" else "Version"), (app_ver or "-"), _icon("ver")) if (SHOW_VERSION and app_ver) else ""
    users_chip  = _chip(_k(lang,"hero.badge.users","المستخدمون" if lang=="ar" else "Users"), str(users_count), _icon("users")) if (SHOW_USERS and isinstance(users_count,int)) else ""
    alerts_chip = (f"{_icon('ok')} <i>{ok_alert}</i>" if (SHOW_ALERTS and alerts_total==0)
                   else (_chip(_k(lang,"hero.badge.alerts","الإشعارات" if lang=="ar" else "Alerts"), f"{alerts_unseen}/{alerts_total}", _icon('alerts')) if SHOW_ALERTS else ""))

    if lang == "ar":
        bullets = ["• الأمان أولًا؛ حماية وقائية وتجنّب أدوات خطرة.","• تحديثات دقيقة؛ ألعاب وتذكيرات دورية.","• دعم سريع؛ إجابات موثوقة."]
        tip = "💡 استخدم القائمة السفلية للأقسام السريعة ⬇️"
    else:
        bullets = ["• Safety first; protective features.","• Precise updates; games & periodic reminders.","• Fast support; reliable answers."]
        tip = "💡 Use the bottom menu for quick sections ⬇️"

    L = _line(); P = _pad()

    top = "  ".join([x for x in (alerts_chip, lang_chip, vip_badge, role_chip) if x])
    bot = "  ".join([x for x in (ver_chip, users_chip) if x])
    parts = [
        f"{_icon('title')} <b>{title}</b>",
        L,
        f"{_icon('hello')} <b>{first_name}</b>",
        f"• {pitch}",
        f"• {safety}",
        P,
        top,
    ]
    if bot: parts.append(bot)
    if SHOW_BULLETS: parts += [L, *bullets]
    if SHOW_TIP: parts += ["", tip]
    parts += ["", cta]
    return "\n".join([p for p in parts if p is not None and str(p).strip()!=""])


def _pick_latest_unseen(uid: int, lang: str):
    """يرجع (id, preview_text) لأحدث إشعار غير مقروء وغير متجاهَل/محذوف، أو None."""
    try:
        from utils.alerts_broadcast import get_active_alerts
        items = get_active_alerts(lang) or []
    except Exception:
        items = []
    st = _ubox_get(uid)
    seen, ignored, deleted = set(st["seen"]), set(st["ignored"]), set(st["deleted"])
    # الأحدث أولًا
    items.sort(key=lambda x: int(x.get("ts", 0)), reverse=True)
    for it in items:
        aid = str(it.get("id"))
        if aid in ignored or aid in deleted or aid in seen:
            continue
        # نص مختصر للعرض (نفس ترميز HTML لرسالة الواجهة)
        body = it.get("text") or it.get("text_ar") or it.get("text_en") or "-"
        preview = _truncate(body, 160)
        return aid, preview
    return None

# --------- العرض ---------
async def render_home_card(message: Message, *, lang: str | None = None):
    _lang = (lang or get_user_lang(message.from_user.id) or "en").strip().lower()
    if _lang not in {"ar", "en"}:
        _lang = "en"

    uid = message.from_user.id
    is_sup = bool(_is_supplier and _is_supplier(uid))
    is_vip = bool(_is_vip and _is_vip(uid))
    is_prom = bool(_is_promoter and _is_promoter(uid))

    total, unseen = _load_alert_counts(uid, _lang)
    users_count = _count_known_users()
    app_ver = _get_app_version()
    lang_label = "AR" if _lang == "ar" else "EN"

    roles = []
    roles.append("مورّد" if (_lang=="ar" and is_sup) else ("Supplier" if is_sup else ("مستخدم" if _lang=="ar" else "User")))
    if is_sup and not is_prom:
        pass
    elif is_prom:
        roles.append("مروّج" if _lang=="ar" else "Promoter")
    role_label = " · ".join(roles)

    first_name = message.from_user.first_name or ("ضيف" if _lang=="ar" else "Guest")

    _apply_runtime_cfg()

    global _LAST_UID
    _LAST_UID = uid

    text = _hero_html(
        _lang,
        first_name=first_name,
        role_label=role_label,
        is_vip=is_vip,
        alerts_total=total,
        alerts_unseen=unseen,
        users_count=users_count,
        app_ver=app_ver,
        lang_label=lang_label,
    )

    await message.answer(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=_build_main_kb(
            _lang,
            is_vip=is_vip,
            is_promoter=is_prom,
            is_supplier=is_sup,
            unseen_alerts=unseen  # ← العدد غير المقروء المحسوب مسبقًا
        ),  
    )

# ========= Fallback ذكي لقائمة الإشعارات (منظم/صفحات/فلاتر) =========
_INB_PAGE_SIZE = 5

# تخزين بسيط لحالة المستخدم
try:
    import threading as _th
    _U_LOCK = _th.Lock()
except Exception:
    class _Dummy:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    _U_LOCK = _Dummy()

def _ubox_load() -> dict:
    try:
        return json.loads(USERBOX_FILE.read_text("utf-8"))
    except Exception:
        return {}

def _ubox_save(db: dict) -> None:
    tmp = USERBOX_FILE.with_suffix(USERBOX_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USERBOX_FILE)

def _ubox_get(uid: int) -> dict:
    with _U_LOCK:
        db = _ubox_load()
        s = db.get(str(uid)) or {}
        s.setdefault("seen", []); s.setdefault("ignored", []); s.setdefault("deleted", [])
        return s

def _ubox_put(uid: int, s: dict) -> None:
    with _U_LOCK:
        db = _ubox_load()
        db[str(uid)] = s
        _ubox_save(db)

async def _safe_edit_text(msg_or_cb, text: str, *, reply_markup=None):
    msg = msg_or_cb.message if isinstance(msg_or_cb, CallbackQuery) else msg_or_cb
    try:
        await msg.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            await msg.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)

def _fmt_time(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except Exception:
        return ""

def _truncate(s: str, n: int = 60) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[:n-1] + "…")

def _fetch_items(uid: int, lang: str):
    try:
        from utils.alerts_broadcast import get_active_alerts
        items = get_active_alerts(lang) or []
    except Exception:
        items = []
    st = _ubox_get(uid)
    seen, ignored, deleted = set(st["seen"]), set(st["ignored"]), set(st["deleted"])
    for it in items:
        it["_seen"] = it["id"] in seen
        it["_ignored"] = it["id"] in ignored
        it["_deleted"] = it["id"] in deleted
    return items, st

def _apply_filter(items: list[dict], flt: str):
    if flt == "u":
        base = [x for x in items if not x.get("_deleted") and not x.get("_ignored") and not x.get("_seen")]
    elif flt == "i":
        base = [x for x in items if x.get("_ignored") and not x.get("_deleted")]
    elif flt == "d":
        base = [x for x in items if x.get("_deleted")]
    else:
        base = [x for x in items if not x.get("_deleted") and not x.get("_ignored")]
    now = int(time.time())
    base.sort(key=lambda x: ((0 if not x.get("_seen") else 1), -int(x.get("ts", now))))
    return base

def _list_header(lang: str, flt: str, total: int, unseen: int) -> str:
    bell = "🔔"
    if str(lang).lower().startswith("ar"):
        title = f"{bell} إشعاراتك"
        filt_map = {"a": "الكل", "u": "غير المفتوحة", "i": "المتجاهلة", "d": "المحذوفة"}
        return f"{title}\nفلتر: {filt_map.get(flt,'الكل')} · غير المفتوحة: {unseen} · الكل: {total}\nاختر عنصرًا لعرضه:"
    else:
        title = f"{bell} Your alerts"
        filt_map = {"a": "All", "u": "Unopened", "i": "Ignored", "d": "Deleted"}
        return f"{title}\nFilter: {filt_map.get(flt,'All')} · Unopened: {unseen} · Total: {total}\nPick one to view:"

def _list_kb(lang: str, page: int, pages: int, flt: str, page_items: list[dict]):
    kb = InlineKeyboardBuilder()

    # عناصر القائمة (تسمية عامة، لا نعرض نص الإشعار في الزر)
    for idx, it in enumerate(page_items, start=1 + page*_INB_PAGE_SIZE):
        kind = (it.get("kind") or "").strip()
        kind_label = t(lang, f"alerts.type.{kind}") or (kind or ("إشعار" if lang == "ar" else "Alert"))
        when = _fmt_time(it.get("ts", int(time.time())))
        new_badge = " 🆕" if not it.get("_seen") else ""
        if str(lang).lower().startswith("ar"):
            label = f"🔔 إشعار #{idx} • {kind_label} • {when}{new_badge}"
        else:
            label = f"🔔 Alert #{idx} • {kind_label} • {when}{new_badge}"
        kb.button(text=label, callback_data=f"ibox:open:{it['id']}:{page}:{flt}")
    if page_items:
        kb.adjust(1)

    # تنقّل
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=("« السابق" if lang == "ar" else "« Prev"),
                                        callback_data=f"ibox:list:{page-1}:{flt}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text=("التالي »" if lang == "ar" else "Next »"),
                                        callback_data=f"ibox:list:{page+1}:{flt}"))
    if nav:
        kb.row(*nav)

    # فلاتر
    kb.row(
        InlineKeyboardButton(text=("الكل" if lang=="ar" else "All"), callback_data="ibox:list:0:a"),
        InlineKeyboardButton(text=("غير المفتوحة" if lang=="ar" else "Unopened"), callback_data="ibox:list:0:u"),
    )
    kb.row(
        InlineKeyboardButton(text=("المتجاهلة" if lang=="ar" else "Ignored"), callback_data="ibox:list:0:i"),
        InlineKeyboardButton(text=("المحذوفة" if lang=="ar" else "Deleted"), callback_data="ibox:list:0:d"),
    )

    # عمليات جماعية + رجوع
    kb.row(
        InlineKeyboardButton(
            text=("✔️ تحديد الظاهرة كمقروءة" if lang=="ar" else "✔️ Mark shown as read"),
            callback_data=f"ibox:bulk:markread:{page}:{flt}"
        )
    )
    kb.row(InlineKeyboardButton(text=("⬅️ رجوع" if lang=="ar" else "⬅️ Back"),
                                callback_data="back_to_menu"))
    return kb.as_markup()

async def _render_list(cb_or_msg, uid: int, lang: str, *, page: int, flt: str):
    if not is_enabled("alerts", user_id=uid):
        return await (cb_or_msg.answer if isinstance(cb_or_msg, CallbackQuery) else cb_or_msg.reply)(
            _feature_disabled_msg(lang), show_alert=True if isinstance(cb_or_msg, CallbackQuery) else None
        )

    items, st = _fetch_items(uid, lang)
    total_active = len([x for x in items if not x.get("_deleted") and not x.get("_ignored")])
    unseen_active = len([x for x in items if not x.get("_deleted") and not x.get("_ignored") and not x.get("_seen")])

    vis = _apply_filter(items, flt)
    if not vis:
        empty = t(lang, "alerts.user.box.empty") or ("لا توجد إشعارات لهذا الفلتر." if lang=="ar" else "No alerts for this filter.")
        return await _safe_edit_text(cb_or_msg, empty)

    pages = max(1, (len(vis) + _INB_PAGE_SIZE - 1) // _INB_PAGE_SIZE)
    page = max(0, min(page, pages-1))
    start = page * _INB_PAGE_SIZE
    chunk = vis[start:start + _INB_PAGE_SIZE]

    header = _list_header(lang, flt, total_active, unseen_active)
    await _safe_edit_text(cb_or_msg, header, reply_markup=_list_kb(lang, page, pages, flt, chunk))

# ========== الهاندلرات ==========




@router.callback_query(F.data == "ibox:back")
async def ibox_back(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "ar"
    items, st = _fetch_items(cb.from_user.id, lang)
    vis = _apply_filter(items, "a")
    if not vis:
        empty = t(lang, "alerts.user.box.empty") or ("لا توجد إشعارات حالياً." if lang=="ar" else "No active alerts.")
        await _safe_edit_text(cb, empty)
        return await cb.answer()
    if len(vis) == 1:
        it = vis[0]
        if it["id"] not in st["seen"]:
            st["seen"].append(it["id"]); _ubox_put(cb.from_user.id, st)
        kb = InlineKeyboardBuilder()
        kb.button(text=("✔️ مقروء" if lang=="ar" else "✔️ Mark read"), callback_data=f"ibox:markread:{it['id']}:0:a")
        kb.button(text=("تجاهل 🙈" if lang=="ar" else "Ignore"), callback_data=f"ibox:ignore:{it['id']}:0:a")
        kb.button(text=("حذف 🗑️" if lang=="ar" else "Delete"), callback_data=f"ibox:delete:{it['id']}:0:a")
        kb.button(text=("◀️ رجوع" if lang=="ar" else "◀️ Back"), callback_data="ibox:list:0:a")
        kb.adjust(2,2)
        await _safe_edit_text(cb, it.get("text",""), reply_markup=kb.as_markup())
        return await cb.answer()
    await _render_list(cb, cb.from_user.id, lang, page=0, flt="a")
    await cb.answer()

@router.callback_query(F.data.regexp(r"^ibox:list:(\d+):(a|u|i|d)$"))
async def ibox_list_nav(cb: CallbackQuery):
    _, _, page, flt = cb.data.split(":")
    lang = get_user_lang(cb.from_user.id) or "ar"
    await _render_list(cb, cb.from_user.id, lang, page=int(page), flt=flt)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^ibox:open:.+:\d+:(a|u|i|d)$"))
async def ibox_open(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "ar"

    parts = cb.data.split(":")
    flt = parts[-1]
    page = int(parts[-2])
    aid = ":".join(parts[2:-2])

    def _get_all(_lang):
        try:
            from utils.alerts_broadcast import get_active_alerts
            return get_active_alerts(_lang) or []
        except Exception:
            return []

    items = _get_all(lang)
    it = next((x for x in items if str(x.get("id")) == str(aid)), None)
    if not it:
        for L in ("ar", "en"):
            if L == lang: continue
            items2 = _get_all(L)
            it = next((x for x in items2 if str(x.get("id")) == str(aid)), None)
            if it: break
    if not it:
        return await cb.answer(
            t(lang, "alerts.user.expired") or ("انتهت صلاحية الإشعار." if lang == "ar" else "Alert expired."),
            show_alert=True
        )

    st = _ubox_get(cb.from_user.id)
    if aid not in st["seen"]:
        st["seen"].append(aid); _ubox_put(cb.from_user.id, st)

    body = it.get("text") or it.get("text_ar") or it.get("text_en") or "-"

    kb = InlineKeyboardBuilder()
    kb.button(text=("✔️ مقروء" if lang=="ar" else "✔️ Mark read"), callback_data=f"ibox:markread:{aid}:{page}:{flt}")
    if it.get("_ignored"):
        kb.button(text=("استرجاع 👁️" if lang=="ar" else "Unignore"), callback_data=f"ibox:unignore:{aid}:{page}:{flt}")
    else:
        kb.button(text=("تجاهل 🙈" if lang=="ar" else "Ignore"), callback_data=f"ibox:ignore:{aid}:{page}:{flt}")
    if it.get("_deleted"):
        kb.button(text=("استرجاع ♻️" if lang=="ar" else "Restore"), callback_data=f"ibox:undelete:{aid}:{page}:{flt}")
    else:
        kb.button(text=("حذف 🗑️" if lang=="ar" else "Delete"), callback_data=f"ibox:delete:{aid}:{page}:{flt}")
    kb.button(text=("◀️ رجوع" if lang=="ar" else "◀️ Back"), callback_data=f"ibox:list:{page}:{flt}")
    kb.adjust(2,2)

    await _safe_edit_text(cb, body, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data.regexp(r"^ibox:markread:([^:]+):(\d+):(a|u|i|d)$"))
async def ibox_mark_read(cb: CallbackQuery):
    aid, page, flt = cb.data.split(":")[2], int(cb.data.split(":")[3]), cb.data.split(":")[4]
    lang = get_user_lang(cb.from_user.id) or "ar"
    st = _ubox_get(cb.from_user.id)
    if aid not in st["seen"]:
        st["seen"].append(aid); _ubox_put(cb.from_user.id, st)
    await _render_list(cb, cb.from_user.id, lang, page=page, flt=flt)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^ibox:ignore:([^:]+):(\d+):(a|u|i|d)$"))
async def ibox_ignore(cb: CallbackQuery):
    aid, page, flt = cb.data.split(":")[2], int(cb.data.split(":")[3]), cb.data.split(":")[4]
    lang = get_user_lang(cb.from_user.id) or "ar"
    st = _ubox_get(cb.from_user.id)
    if aid not in st["ignored"]:
        st["ignored"].append(aid); _ubox_put(cb.from_user.id, st)
    await _render_list(cb, cb.from_user.id, lang, page=page, flt=flt)
    await cb.answer("تم التجاهل" if lang=="ar" else "Ignored")

@router.callback_query(F.data.regexp(r"^ibox:unignore:([^:]+):(\d+):(a|u|i|d)$"))
async def ibox_unignore(cb: CallbackQuery):
    aid, page, flt = cb.data.split(":")[2], int(cb.data.split(":")[3]), cb.data.split(":")[4]
    lang = get_user_lang(cb.from_user.id) or "ar"
    st = _ubox_get(cb.from_user.id)
    if aid in st["ignored"]:
        st["ignored"].remove(aid); _ubox_put(cb.from_user.id, st)
    await _render_list(cb, cb.from_user.id, lang, page=page, flt=flt)
    await cb.answer("تم الاسترجاع" if lang=="ar" else "Restored")

@router.callback_query(F.data.regexp(r"^ibox:delete:([^:]+):(\d+):(a|u|i|d)$"))
async def ibox_delete(cb: CallbackQuery):
    aid, page, flt = cb.data.split(":")[2], int(cb.data.split(":")[3]), cb.data.split(":")[4]
    lang = get_user_lang(cb.from_user.id) or "ar"
    st = _ubox_get(cb.from_user.id)
    if aid not in st["deleted"]:
        st["deleted"].append(aid); _ubox_put(cb.from_user.id, st)
    await _render_list(cb, cb.from_user.id, lang, page=page, flt=flt)
    await cb.answer("تم الحذف" if lang=="ar" else "Deleted")

@router.callback_query(F.data.regexp(r"^ibox:undelete:([^:]+):(\d+):(a|u|i|d)$"))
async def ibox_undelete(cb: CallbackQuery):
    aid, page, flt = cb.data.split(":")[2], int(cb.data.split(":")[3]), cb.data.split(":")[4]
    lang = get_user_lang(cb.from_user.id) or "ar"
    st = _ubox_get(cb.from_user.id)
    if aid in st["deleted"]:
        st["deleted"].remove(aid); _ubox_put(cb.from_user.id, st)
    await _render_list(cb, cb.from_user.id, lang, page=page, flt=flt)
    await cb.answer("تم الاسترجاع" if lang=="ar" else "Restored")

@router.callback_query(F.data.regexp(r"^ibox:bulk:markread:(\d+):(a|u|i|d)$"))
async def ibox_bulk_markread(cb: CallbackQuery):
    page, flt = int(cb.data.split(":")[3]), cb.data.split(":")[4]
    lang = get_user_lang(cb.from_user.id) or "ar"
    items, st = _fetch_items(cb.from_user.id, lang)
    vis = _apply_filter(items, flt)
    pages = max(1, (len(vis) + _INB_PAGE_SIZE - 1) // _INB_PAGE_SIZE)
    page = max(0, min(page, pages-1))
    start = page * _INB_PAGE_SIZE
    chunk = vis[start:start + _INB_PAGE_SIZE]
    for it in chunk:
        if it["id"] not in st["seen"]:
            st["seen"].append(it["id"])
    _ubox_put(cb.from_user.id, st)
    await _render_list(cb, cb.from_user.id, lang, page=page, flt=flt)
    await cb.answer("تم التعليم كمقروء" if lang=="ar" else "Marked as read")

# --------- Aliases / fallbacks ---------
@router.callback_query(F.data == "supplier_panel")
async def _alias_supplier_panel(cb: CallbackQuery):
    try:
        await cb.answer()
        await cb.message.edit_text(
            "🛍️ لوحة المورّد غير متاحة مباشرة من هنا.\n"
            "استخدم زر «لوحة المورّد» من القائمة الرئيسية أو اذهب إلى «المورّدون الموثوقون».",
        )
    except Exception:
        pass

# ======== دعم: نص + أزرار (الدردشة الحيّة + فتح بلاغ) ========
def _support_text(lang: str) -> str:
    if str(lang).lower().startswith("ar"):
        return (
            "🆘 لفتح قناة الدعم اضغط على الأمر التالي ثم اتبع التعليمات:\n"
            "/report\n\n"
            "أو اختر <b>الدردشة الحيّة الآن</b> للتحدث فورًا مع أحد المشرفين .\n\n"
            "📎 أرفق لقطة شاشة لعملية الدفع + اسم البائع الخاص بك."
        )
    return (
        "🆘 To contact support, tap this command and follow the steps:\n"
        "/report\n\n"
        "Or choose <b>Live chat now</b> to talk directly with an admin .\n\n"
        "📎 Please attach a payment screenshot + your seller’s name."
    )

def _support_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=("💬 الدردشة الحيّة الآن" if lang=="ar" else "💬 Live chat now"),
            callback_data="bot:live"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text=("🆘 فتح بلاغ" if lang=="ar" else "🆘 Open report"),
            callback_data="support:report"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text=("⬅️ رجوع للقائمة" if lang=="ar" else "⬅️ Back to menu"),
            callback_data="back_to_menu"
        )
    )
    return kb.as_markup()

def _feature_disabled_msg(lang: str) -> str:
    return (t(lang, "feature.disabled")
            or ("❌ هذا القسم غير متاح حالياً." if lang == "ar" else "❌ This section is currently unavailable."))

@router.callback_query(F.data.in_({"report", "report:open"}))
async def _alias_open_report(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_enabled("support", user_id=cb.from_user.id):
        return await cb.answer(_feature_disabled_msg(lang), show_alert=True)

    try:
        await cb.message.answer(
            _support_text(lang),
            reply_markup=_support_kb(lang),
            disable_web_page_preview=True,
            parse_mode="HTML",
        )
    except Exception:
        pass
    await cb.answer()

@router.callback_query(F.data == "support:report")
async def _support_do_report(cb: CallbackQuery, state: FSMContext):
    lang = (get_user_lang(cb.from_user.id) or "en").lower()
    ar = lang.startswith("ar")

    is_admin = await _is_admin(cb.from_user.id)
    st = load_settings()

    if not st.get("enabled", True) and not is_admin:
        msg = t(lang, "report.disabled") or ("خدمة البلاغات متوقفة مؤقتاً." if ar else "Reporting is temporarily disabled.")
        return await cb.answer(msg, show_alert=True)

    if not is_admin:
        blocked, remain = _bl_is_blocked(cb.from_user.id)
        if blocked:
            msg = t(lang, "report.blocked") or (f"⛔ تم تقييد ميزة البلاغات لديك ({remain})." if ar else f"⛔ Reporting is restricted for you ({remain}).")
            return await cb.answer(msg, show_alert=True)

        nxt = _next_allowed_dt(cb.from_user.id)
        if nxt:
            now = datetime.datetime.now(datetime.timezone.utc)
            if now < nxt:
                remain = human_remaining(nxt - now)
                msg = (t(lang, "report.cooldown_wait") or
                      ("لديك بلاغ سابق. يرجى الانتظار {remaining} قبل إرسال بلاغ جديد."
                       if ar else
                       "You already have a report. Please wait {remaining} before sending another.")
                      ).format(remaining=remain)
                return await cb.answer(msg, show_alert=True)

    await state.set_state(ReportState.waiting_text)

    prompt_ar = "✍️ أرسل وصف مشكلتك بالتفصيل. يمكنك أيضًا إرسال صورة/فيديو مع تعليق."
    prompt_en = "✍️ Describe your issue in detail. You may also send a photo/video with a caption."
    prompt = t(lang, "report.prompt") or (prompt_ar if ar else prompt_en)

    try:
        await cb.message.edit_text(prompt, reply_markup=None)
    except TelegramBadRequest:
        try:
            await cb.message.edit_reply_markup(None)
        except Exception:
            pass
        await cb.message.answer(prompt)

    await cb.answer()

# ======== Feature-gates ========
@router.callback_query(lambda q: q.data == "shop:sevip" and not is_enabled("vip", user_id=q.from_user.id))
async def _gate_vip(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == CB["APP_DOWNLOAD"] and not is_enabled("download", user_id=q.from_user.id))
async def _gate_download(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == CB["REWARDS"] and not is_enabled("rewards", user_id=q.from_user.id))
async def _gate_rewards(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == CB["TOOLS"] and not is_enabled("tools", user_id=q.from_user.id))
async def _gate_tools(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == CB["CHECK_DEVICE"] and not is_enabled("check", user_id=q.from_user.id))
async def _gate_check(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == CB["TRUSTED_SUPPLIERS"] and not is_enabled("suppliers", user_id=q.from_user.id))
async def _gate_suppliers(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == CB["SAFE_USAGE"] and not is_enabled("safe_usage", user_id=q.from_user.id))
async def _gate_safe(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == CB["LANG"] and not is_enabled("language", user_id=q.from_user.id))
async def _gate_lang(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data in {"support:report", "report", "report:open"} and not is_enabled("support", user_id=q.from_user.id))
async def _gate_support(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == "bot:live" and not is_enabled("live", user_id=q.from_user.id))
async def _gate_live(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data in {CB["PROMO_PANEL"], CB["PROMO_INFO"], CB["PROMO_LIVE"]} and not is_enabled("promoters", user_id=q.from_user.id))
async def _gate_promoters(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(F.data == "back_to_menu")
async def _back_to_menu(cb: CallbackQuery):
    await render_home_card(cb.message)
    await cb.answer()

@router.callback_query(lambda q: q.data == CB["SERVER_STATUS"] and not is_enabled("server_status", user_id=q.from_user.id))
async def _gate_server_status(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(lambda q: q.data == "ibox:back" and not is_enabled("alerts", user_id=q.from_user.id))
async def _gate_alerts(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)
