# handlers/home_hero.py
from __future__ import annotations

import os, time, json
from typing import Optional
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang
from aiogram.filters import StateFilter
from handlers.report import report_cmd  # لفتح فلو البلاغ مباشرة
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# نستخدم الدوال من report.py بدل استدعاء report_cmd
from handlers.report import (
    _is_admin, load_settings, _bl_is_blocked, _next_allowed_dt,
    human_remaining, ReportState
)
from lang import t, get_user_lang
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
        # لو ما فيه ملف الأعلام، اعتبر كل شيء مفعّل
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
    "PROMO_LIVE": "promp:live",     # ← بث مباشر للمروّجين (قائمة عامة أيضًا)

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

# --------- أزرار القائمة الرئيسية (2×2 دائماً) ---------
def _build_main_kb(lang: str, *, is_vip: bool, is_promoter: bool, is_supplier: bool):
    kb = InlineKeyboardBuilder(); row = kb.row

    # السطر 1 — شراء/تنشيط (منفرد)
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
            text="📬 " + _k(lang, "btn_alerts_inbox", "صندوق الإشعارات" if lang == "ar" else "Alerts Inbox"),
            callback_data="inb:back"
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

    # السطر 7 — بث + (لوحة المروّجين أو كيف تصبح مروّجًا)
    live_n = _count_live()
    live_label = _k(lang, "btn_promoter_live", "بث مباشر للمروّجين" if lang == "ar" else "Promoters Live")
    if live_n > 0:
        live_label = f"{live_label} ({live_n})"

    if is_promoter:
        row(
            InlineKeyboardButton(text="🎥 " + live_label, callback_data=CB["PROMO_LIVE"]),
            InlineKeyboardButton(text="📣 " + _k(lang, "btn_promoter_panel", "لوحة المروّجين" if lang == "ar" else "Promoter Panel"),
                                 callback_data=CB["PROMO_PANEL"]),
        )
    else:
        row(
            InlineKeyboardButton(text="🎥 " + live_label, callback_data=CB["PROMO_LIVE"]),
            InlineKeyboardButton(text="📣 " + _k(lang, "btn_be_promoter", "كيف تصبح مُروّجًا؟" if lang == "ar" else "Become a promoter?"),
                                 callback_data=CB["PROMO_INFO"]),
        )

    return kb.as_markup()


# ===== (الإعدادات الحالية كقيم أولية – سنقوم بتطبيق override ديناميكي لاحقًا) =====
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
        reply_markup=_build_main_kb(_lang, is_vip=is_vip, is_promoter=is_prom, is_supplier=is_sup),
    )

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
            callback_data="bot:live"  # يتوافق مع live_chat.py
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
    """
    يفتح قناة البلاغ مباشرة (تفعيل حالة FSM) ويحوّل بطاقة الدعم نفسها
    إلى نص "أرسل وصف مشكلتك..." باللغة الصحيحة — بدون رسائل إضافية.
    """
    lang = (get_user_lang(cb.from_user.id) or "en").lower()
    ar = lang.startswith("ar")

    # === نفس فحوص report_cmd ولكن دون إرسال رسالة جديدة ===
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

    # فعّل حالة انتظار نص البلاغ
    await state.set_state(ReportState.waiting_text)

    # نص المطالبة حسب اللغة (مع دعم الترجمة من lang.t)
    prompt_ar = "✍️ أرسل وصف مشكلتك بالتفصيل. يمكنك أيضًا إرسال صورة/فيديو مع تعليق."
    prompt_en = "✍️ Describe your issue in detail. You may also send a photo/video with a caption."
    prompt = t(lang, "report.prompt") or (prompt_ar if ar else prompt_en)

    # حوّل بطاقة الدعم الحالية إلى نص المطالبة (بدون كيبورد)
    try:
        await cb.message.edit_text(prompt, reply_markup=None)
    except TelegramBadRequest:
        # لو ما ينفع التعديل (مثلاً كانت وسائط)، احذف الكيبورد وأرسل النص مرّة واحدة
        try:
            await cb.message.edit_reply_markup(None)
        except Exception:
            pass
        await cb.message.answer(prompt)

    await cb.answer()


# ======== Feature-gates: نمنع قبل التنفيذ عندما يكون التبويب مقفول ========
# ملاحظة: هذه الهاندلرات تُطابق فقط عند التعطيل؛ عند التفعيل لا تُطابق ويكمل للملفات الأصلية.

# شراء/تنشيط VIP من زر القائمة
@router.callback_query(lambda q: q.data == "shop:sevip" and not is_enabled("vip", user_id=q.from_user.id))
async def _gate_vip(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# تحميل التطبيق
@router.callback_query(lambda q: q.data == CB["APP_DOWNLOAD"] and not is_enabled("download", user_id=q.from_user.id))
async def _gate_download(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# الجوائز
@router.callback_query(lambda q: q.data == CB["REWARDS"] and not is_enabled("rewards", user_id=q.from_user.id))
async def _gate_rewards(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# أدوات الألعاب
@router.callback_query(lambda q: q.data == CB["TOOLS"] and not is_enabled("tools", user_id=q.from_user.id))
async def _gate_tools(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# تحقّق من جهازك
@router.callback_query(lambda q: q.data == CB["CHECK_DEVICE"] and not is_enabled("check", user_id=q.from_user.id))
async def _gate_check(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# الموردون الموثوقون / دليل الموردين
@router.callback_query(lambda q: q.data == CB["TRUSTED_SUPPLIERS"] and not is_enabled("suppliers", user_id=q.from_user.id))
async def _gate_suppliers(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# دليل الاستخدام الآمن
@router.callback_query(lambda q: q.data == CB["SAFE_USAGE"] and not is_enabled("safe_usage", user_id=q.from_user.id))
async def _gate_safe(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# اللغة
@router.callback_query(lambda q: q.data == CB["LANG"] and not is_enabled("language", user_id=q.from_user.id))
async def _gate_lang(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# الدعم / البلاغ
@router.callback_query(lambda q: q.data in {"support:report", "report", "report:open"} and not is_enabled("support", user_id=q.from_user.id))
async def _gate_support(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# الدردشة الحيّة (زر "bot:live" إن وجد)
@router.callback_query(lambda q: q.data == "bot:live" and not is_enabled("live", user_id=q.from_user.id))
async def _gate_live(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# المروّجون (لوحة/معلومات/بث مباشر)
@router.callback_query(lambda q: q.data in {CB["PROMO_PANEL"], CB["PROMO_INFO"], CB["PROMO_LIVE"]} and not is_enabled("promoters", user_id=q.from_user.id))
async def _gate_promoters(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

@router.callback_query(F.data == "back_to_menu")
async def _back_to_menu(cb: CallbackQuery):
    await render_home_card(cb.message)
    await cb.answer()

# حالة السيرفرات
@router.callback_query(lambda q: q.data == CB["SERVER_STATUS"] and not is_enabled("server_status", user_id=q.from_user.id))
async def _gate_server_status(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)

# صندوق الإشعارات (زر inb:back)
@router.callback_query(lambda q: q.data == "inb:back" and not is_enabled("alerts", user_id=q.from_user.id))
async def _gate_alerts(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_feature_disabled_msg(lang), show_alert=True)
