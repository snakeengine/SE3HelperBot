# handlers/home_hero.py
from __future__ import annotations

import os, time
from typing import Optional
import json, os
from pathlib import Path
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang
from utils.home_card_cfg import get_cfg

router = Router(name="home_hero")

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

    # المورّد (زر واحد يتبدّل)
    "SUPPLIER_PUBLIC": "supplier_public",   # بطاقة/لوحة المورّد العامة
    "SUPPLIER_PANEL":  "supplier_panel",    # alias (نضع له fallback أدناه)

    "SECURITY_STATUS": "security_status",
    "SAFE_USAGE": "safe_usage:open",
    "SERVER_STATUS": "server_status",
    "LANG": "change_lang",
    "RESELLER_INFO": "reseller_info",       # كيف تصبح مورداً؟
    "BACK": "back_to_menu",
    "REWARDS": "rewards",               # ←← أضف هذا السطر

}

# --------- أزرار القائمة الرئيسية (2×2 دائماً) ---------
def _build_main_kb(lang: str, *, is_vip: bool, is_promoter: bool, is_supplier: bool):
    kb = InlineKeyboardBuilder()
    row = kb.row

    # صف 1 (2×2)
    row(
        InlineKeyboardButton(
            text="📥 " + _k(lang, "btn_download", "تحميل تطبيق الثعبان" if lang == "ar" else "Download App"),
            callback_data=CB["APP_DOWNLOAD"]
        ),
        InlineKeyboardButton(
            text="🎛️ " + _k(lang, "btn_game_tools", "أدوات وتعديلات الألعاب" if lang == "ar" else "Game Mods & Tools"),
            callback_data=CB["TOOLS"]
        ),
    )

    # صف 2 (2×2)
    row(
        InlineKeyboardButton(
            text="🏷️ " + _k(lang, "btn_trusted_suppliers", "المورّدون الموثوقون" if lang == "ar" else "Official suppliers"),
            callback_data=CB["TRUSTED_SUPPLIERS"]
        ),
        InlineKeyboardButton(
            text="📱 " + _k(lang, "btn_check_device", "تحقق من جهازك" if lang == "ar" else "Check your device"),
            callback_data=CB["CHECK_DEVICE"]
        ),
    )

    # صف 3 (2×2)
    row(
        InlineKeyboardButton(
            text="🧠 " + _k(lang, "btn_safe_usage", "دليل الاستخدام الآمن" if lang == "ar" else "Safe Usage Guide"),
            callback_data=CB["SAFE_USAGE"]
        ),
        InlineKeyboardButton(
            text="🛡️ " + _k(lang, "btn_security", "حالة الأمان" if lang == "ar" else "Security Status"),
            callback_data=CB["SECURITY_STATUS"]
        ),
    )

    # صف 4 (2×2)
    row(
        InlineKeyboardButton(
            text="📊 " + _k(lang, "btn_server_status", "حالة السيرفرات" if lang == "ar" else "Server Status"),
            callback_data=CB["SERVER_STATUS"]
        ),
        InlineKeyboardButton(
            text="🌐 " + _k(lang, "btn_lang", "تغيير اللغة" if lang == "ar" else "Change Language"),
            callback_data=CB["LANG"]
        ),
    )

    row(
        InlineKeyboardButton(
            text="🎁 " + _k(lang, "btn_rewards", "الجوائز" if lang == "ar" else "Rewards"),
            callback_data=CB["REWARDS"]
        )
    )
    # صف 5 — المورّد (زر كامل العرض يتبدّل)
    row(
        InlineKeyboardButton(
            text="🛍️ " + (
                _k(lang, "btn_supplier_panel", "لوحة المورّد" if lang == "ar" else "Supplier Panel")
                if is_supplier else
                _k(lang, "btn_be_supplier_long", "كيف تصبح مورّدًا؟" if lang == "ar" else "Become a supplier?")
            ),
            callback_data=(CB["SUPPLIER_PUBLIC"] if is_supplier else CB["RESELLER_INFO"])
        )
    )

    # صف 6 — المروّج (زر كامل العرض يتبدّل)
    row(
        InlineKeyboardButton(
            text="📣 " + (
                _k(lang, "btn_promoter_panel", "لوحة المروّجين" if lang == "ar" else "Promoter Panel")
                if is_promoter else
                _k(lang, "btn_be_promoter", "كيف تصبح مُروّجًا؟" if lang == "ar" else "Become a promoter?")
            ),
            callback_data=(CB["PROMO_PANEL"] if is_promoter else CB["PROMO_INFO"])
        )
    )

    # صف 7 — VIP (زر كامل العرض يتبدّل) — أسفل القائمة
    row(
        InlineKeyboardButton(
            text="👑 " + (
                _k(lang, "btn_vip_panel", "لوحة VIP" if lang == "ar" else "VIP Panel")
                if is_vip else
                _k(lang, "btn_vip_subscribe", "الاشتراك VIP" if lang == "ar" else "Subscribe VIP")
            ),
            callback_data=(CB["VIP_PANEL"] if is_vip else CB["VIP_OPEN"])
        )
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

# --- مفاتيح التحكم من .env (تبقى موجودة، لكن سنعمل override من cfg وقت التشغيل) ---
THEME      = (os.getenv("HOME_CARD_THEME")    or THEME).strip().lower()
DENSITY    = (os.getenv("HOME_CARD_DENSITY")  or DENSITY).strip().lower()
SEPARATOR  = (os.getenv("HOME_CARD_SEP")      or SEPARATOR).strip().lower()
ICON_SET   = (os.getenv("HOME_CARD_ICONS")    or ICON_SET).strip().lower()
SHOW_BULLETS   = (os.getenv("HOME_SHOW_BULLETS", "1") not in {"0","false","False"}) if "HOME_SHOW_BULLETS" in os.environ else SHOW_BULLETS
SHOW_TIP       = (os.getenv("HOME_SHOW_TIP", "1") not in {"0","false","False"})     if "HOME_SHOW_TIP" in os.environ else SHOW_TIP
SHOW_VERSION   = (os.getenv("HOME_SHOW_VERSION", "1") not in {"0","false","False"}) if "HOME_SHOW_VERSION" in os.environ else SHOW_VERSION
SHOW_USERS     = (os.getenv("HOME_SHOW_USERS", "1") not in {"0","false","False"})   if "HOME_SHOW_USERS" in os.environ else SHOW_USERS
SHOW_ALERTS    = (os.getenv("HOME_SHOW_ALERTS", "1") not in {"0","false","False"})  if "HOME_SHOW_ALERTS" in os.environ else SHOW_ALERTS

# --- متغيّر لحمل آخر UID لعرض تاريخ انتهاء VIP داخل _hero_html بدون تغيير توقيعه ---
_LAST_UID: Optional[int] = None

def _cfg_bool(d: dict, primary: str, alt: str, default: bool) -> bool:
    """يقرأ قيمة من cfg مع دعم اسمين للمفتاح (للتوافق): primary أو alt."""
    val = d.get(primary, d.get(alt, default))
    if isinstance(val, bool): return val
    if isinstance(val, str):  return val.lower() not in {"0","false","off"}
    return bool(val)

def _apply_runtime_cfg() -> dict:
    """يُطبّق إعدادات /home_ui على المتغيرات العالمية لحظياً (بدون حذف سطورك)."""
    global THEME, DENSITY, SEPARATOR, ICON_SET
    global SHOW_BULLETS, SHOW_TIP, SHOW_VERSION, SHOW_USERS, SHOW_ALERTS

    d = get_cfg()
    THEME     = str(d.get("theme", THEME))
    DENSITY   = str(d.get("density", DENSITY))
    SEPARATOR = str(d.get("sep", SEPARATOR))
    ICON_SET  = str(d.get("icons", ICON_SET))

    # دعم الاسمين: bullets / show_bullets ... إلخ
    SHOW_BULLETS = _cfg_bool(d, "bullets", "show_bullets", SHOW_BULLETS)
    SHOW_TIP     = _cfg_bool(d, "tip", "show_tip", SHOW_TIP)
    SHOW_VERSION = _cfg_bool(d, "version", "show_version", SHOW_VERSION)
    SHOW_USERS   = _cfg_bool(d, "users", "show_users", SHOW_USERS)
    SHOW_ALERTS  = _cfg_bool(d, "alerts", "show_alerts", SHOW_ALERTS)
    return d

def _icon(kind: str) -> str:
    if ICON_SET == "classic":
        mapping = {
            "title":"🐍","hello":"👋","vip":"👑","role":"⭐","lang":"🌐","alerts":"🔔",
            "users":"👥","ver":"⚙️","sep":"—","ok":"🟢","warn":"⚠️"
        }
    elif ICON_SET == "minimal":
        mapping = {k:"" for k in ["title","hello","vip","role","lang","alerts","users","ver","sep","ok","warn"]}
    else:  # modern (افتراضي)
        mapping = {
            "title":"🐍","hello":"👋","vip":"👑","role":"⭐","lang":"🌐","alerts":"🔔",
            "users":"👥","ver":"⚙️","sep":"⎯","ok":"🟢","warn":"⚠️"
        }
    return mapping.get(kind, "")

def _line() -> str:
    if SEPARATOR == "hard": return "━" * (20 if DENSITY=="compact" else 28)
    if SEPARATOR == "dots": return "· " * (14 if DENSITY=="compact" else 18)
    if SEPARATOR == "line": return "—" * (22 if DENSITY=="compact" else 30)
    return "⎯" * (18 if DENSITY=="compact" else 26)  # soft (افتراضي)

def _pad() -> str:
    return "" if DENSITY=="compact" else ("\n" if DENSITY=="normal" else "\n")

def _chip(label: str, value: str, icon: str="") -> str:
    return (icon + (" " if icon else "")) + f"<code>{label}: {value}</code>"

def _fmt_vip_badge(lang: str, user_id: int, is_vip: bool) -> str:
    # استخدم آخر UID إن مُرّر 0 (حتى لا نغيّر توقيع _hero_html)
    if not user_id:
        user_id = _LAST_UID or 0
    yes = "نعم" if lang=="ar" else "Yes"
    no  = "لا"  if lang=="ar" else "No"
    if not is_vip:
        return f"{_icon('vip')} <code>VIP: {no}</code>"
    # إن توفر تاريخ الانتهاء نعرضه
    try:
        if _get_vip_meta:
            meta = _get_vip_meta(user_id) or {}
            exp = meta.get("expiry_ts")
            if isinstance(exp, int):
                exp_s = time.strftime("%d-%m-%Y", time.localtime(exp))
                return f"{_icon('vip')} <code>VIP: {yes} · {exp_s}</code>"
    except Exception:
        pass
    return f"{_icon('vip')} <code>VIP: {yes}</code>"

# =======[ الدالة الرئيسية: توليد نص البطاقة حسب الثيم ]=======
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
    # نصوص أساسية
    title  = _k(lang, "home_title_plain", "مرحبًا بك في محرك الثعبان" if lang=="ar" else "Welcome to Snake Engine")
    pitch  = _k(lang, "pitch_plain", "منصة قوية لتعديل ألعاب أندرويد — بدون روت وبدون حظر." if lang=="ar" else "Powerful Android modding — no root, no bans.")
    safety = _k(lang, "safety_plain", "الأمان أولًا: خصائص وقائية، محاكي معزول، لا أدوات خطرة." if lang=="ar" else "Safety-first: protective features, sandboxed emulator, no risky tools.")
    cta    = _k(lang, "cta_plain", "ابدأ الآن — اختر أداتك:" if lang=="ar" else "Start now — choose your tool:")
    ok_alert = _k(lang, "hero.status.ok", "لا إشعارات" if lang=="ar" else "All caught up")

    vip_badge   = _fmt_vip_badge(lang, 0, is_vip)  # سيُستبدل بـ _LAST_UID
    role_chip   = _chip(_k(lang,"hero.badge.role","الدور" if lang=="ar" else "Role"), role_label, _icon("role"))
    lang_chip   = _chip(_k(lang,"hero.badge.lang","اللغة" if lang=="ar" else "Lang"), lang_label, _icon("lang"))
    ver_chip    = _chip(_k(lang,"hero.badge.version","الإصدار" if lang=="ar" else "Version"), (app_ver or "-"), _icon("ver")) if (SHOW_VERSION and app_ver) else ""
    users_chip  = _chip(_k(lang,"hero.badge.users","المستخدمون" if lang=="ar" else "Users"), str(users_count), _icon("users")) if (SHOW_USERS and isinstance(users_count,int)) else ""
    alerts_chip = (f"{_icon('ok')} <i>{ok_alert}</i>" if (SHOW_ALERTS and alerts_total==0)
                   else (_chip(_k(lang,"hero.badge.alerts","الإشعارات" if lang=="ar" else "Alerts"), f"{alerts_unseen}/{alerts_total}", _icon('alerts')) if SHOW_ALERTS else ""))

    if lang == "ar":
        bullets = [
            "• الأمان أولًا؛ حماية وقائية وتجنّب أدوات خطرة.",
            "• تحديثات دقيقة؛ ألعاب وتذكيرات دورية.",
            "• دعم سريع؛ إجابات موثوقة.",
        ]
        tip = "💡 استخدم القائمة السفلية للأقسام السريعة ⬇️"
    else:
        bullets = [
            "• Safety first; protective features.",
            "• Precise updates; games & periodic reminders.",
            "• Fast support; reliable answers.",
        ]
        tip = "💡 Use the bottom menu for quick sections ⬇️"

    L = _line(); P = _pad()

    # ------------------ ثيمات متعددة ------------------
    if THEME in {"neo","modern"}:
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
        if SHOW_BULLETS:
            parts += [L, *bullets]
        if SHOW_TIP:
            parts += ["", tip]
        parts += ["", cta]
        return "\n".join([p for p in parts if p is not None and str(p).strip()!=""])

    if THEME == "glass":
        chips = " · ".join([x.replace("<code>","").replace("</code>","") for x in (alerts_chip, lang_chip, vip_badge, role_chip) if x])
        extras = " · ".join([x.replace("<code>","").replace("</code>","") for x in (ver_chip, users_chip) if x])
        parts = [
            f"{_icon('title')} <b>{title}</b>  {L[:8]}",
            f"{_icon('hello')} <b>{first_name}</b>",
            chips,
            extras,
            "┈"* (24 if DENSITY=="compact" else 30),
            f"• {pitch}",
            f"• {safety}",
            "┈"* (24 if DENSITY=="compact" else 30),
        ]
        if SHOW_TIP: parts += [tip]
        parts += ["", cta]
        return "\n".join([p for p in parts if p and p.strip()])

    if THEME == "chip":
        chipline = "  ".join([f"[{x.replace('<code>','').replace('</code>','')}]" for x in (vip_badge, role_chip, lang_chip) if x])
        smalls  = "  ".join([x for x in (ver_chip, users_chip) if x])
        parts = [
            f"{_icon('title')} <b>{title}</b>",
            chipline,
            alerts_chip if alerts_chip else "",
            L,
            f"• {pitch}",
            f"• {safety}",
        ]
        if smalls: parts += [smalls]
        if SHOW_BULLETS: parts += [L, *bullets]
        if SHOW_TIP: parts += ["", tip]
        parts += ["", cta]
        return "\n".join([p for p in parts if p and p.strip()])

    if THEME == "plaque":
        bar = "▔" * (22 if DENSITY=="compact" else 30)
        chips = "  ".join([x for x in (vip_badge, role_chip, lang_chip) if x])
        parts = [
            f"{_icon('title')} <b>{title}</b>",
            bar,
            f"{_icon('hello')} <b>{first_name}</b>",
            alerts_chip if alerts_chip else "",
            "",
            f"• {pitch}",
            f"• {safety}",
            "",
            chips,
            ("  ".join([x for x in (ver_chip, users_chip) if x]) if (ver_chip or users_chip) else ""),
        ]
        if SHOW_TIP: parts += ["", tip]
        parts += ["", cta]
        return "\n".join([p for p in parts if p and p.strip()])

    if THEME == "banner":
        chips = "  ".join([x for x in (vip_badge, role_chip, lang_chip) if x])
        parts = [
            f"{_icon('title')} <b>{title}</b>",
            L,
            f"{_icon('hello')} <b>{first_name}</b>",
            alerts_chip if alerts_chip else "",
            "",
            f"• {pitch}",
            f"• {safety}",
            "",
            chips,
            ("  ".join([x for x in (ver_chip, users_chip) if x]) if (ver_chip or users_chip) else ""),
        ]
        if SHOW_TIP: parts += ["", tip]
        parts += ["", cta]
        return "\n".join([p for p in parts if p and p.strip()])

    # receipt (افتراضي احتياطي)
    line = "—" * (22 if DENSITY=="compact" else 30)
    rows = [
        f"{_icon('title')} {title}",
        line,
        f"{_icon('hello')} {first_name}",
    ]
    if SHOW_ALERTS and alerts_chip:
        rows.append(alerts_chip.replace("<code>","").replace("</code>",""))
    rows += [
        f"{_icon('lang')} Lang: {lang_label}",
        ("VIP: Yes" if is_vip else "VIP: No"),
        f"Role: {role_label}",
    ]
    if SHOW_VERSION and app_ver: rows.append(f"{_icon('ver')} Version: {app_ver}")
    if SHOW_USERS and isinstance(users_count,int): rows.append(f"{_icon('users')} Users: {users_count}")
    if SHOW_BULLETS:
        rows += [line, f"• {pitch}", f"• {safety}"]
    if SHOW_TIP:
        rows += [line, tip]
    rows += ["", cta]
    return "\n".join(rows)

    # ======== (البلوكات التالية بقيت كما هي – غير مُستخدمة، لم أحذفها) ========
    if style in ("neo", "glass"):
        line_top = "━━━━━━━"
        line_mid = "┈" * 24
        chips = " · ".join([alerts_chip.replace("<code>","").replace("</code>",""),
                            lang_chip.replace("<code>","").replace("</code>",""),
                            vip_badge.replace("<code>","").replace("</code>",""),
                            role_chip.replace("<code>","").replace("</code>","")])
        extras = " · ".join([x.replace("<code>","").replace("</code>","") for x in (ver_chip, users_chip) if x])
        parts = [
            f"🐍 <b>{title}</b>  {line_top}",
            f"👋 <b>{first_name}</b>",
            f"{chips}",
            (extras if extras else ""),
            line_mid,
            f"• {pitch}",
            f"• {safety}",
            line_mid,
            tip,
            "",
            cta,
        ]
        return "\n".join([p for p in parts if p.strip()])

    if style in ("banner", "headline"):
        bar   = "▬▬▬▬▬▬▬▬▬▬"
        chips = "  ".join([vip_badge, role_chip, lang_chip])
        parts = [
            f"🐍 <b>{title}</b>",
            bar,
            f"👋 <b>{first_name}</b>",
            alerts_chip,
            "",
            f"• {pitch}",
            f"• {safety}",
            "",
            chips,
            ("  ".join([x for x in (ver_chip, users_chip) if x]) if (ver_chip or users_chip) else ""),
            "",
            tip,
            "",
            cta,
        ]
        return "\n".join([p for p in parts if p.strip()])

    line = "—" * 24
    rows = [
        f"🐍 {title}",
        line,
        f"👤 {first_name}",
        alerts_chip.replace("<code>","").replace("</code>",""),
        f"🌐 Lang: {lang_label}",
        f"{'VIP: Yes' if is_vip else 'VIP: No'}",
        f"⭐ Role: {role_label}",
    ]
    if app_ver: rows.append(f"⚙️ Version: {app_ver}")
    if isinstance(users_count,int): rows.append(f"👥 Users: {users_count}")
    rows += [
        line,
        f"• {pitch}",
        f"• {safety}",
        line,
        tip,
        "",
        cta,
    ]
    return "\n".join(rows)

# --------- العرض ---------
async def render_home_card(message: Message, *, lang: str | None = None):
    """
    يرسل بطاقة ترحيب HTML مع أزرار 2×2 وتحوّل ديناميكي للأزرار (VIP/مروّج/مورّد).
    """
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

    # الدور قد يجمع أكثر من صفة: مورّد + مروّج
    roles = []
    roles.append("مورّد" if (_lang=="ar" and is_sup) else ("Supplier" if is_sup else ("مستخدم" if _lang=="ar" else "User")))
    if is_sup and not is_prom:
        pass
    elif is_prom:
        roles.append("مروّج" if _lang=="ar" else "Promoter")
    role_label = " · ".join(roles)

    first_name = message.from_user.first_name or ("ضيف" if _lang=="ar" else "Guest")

    # ⬅️ طبّق إعدادات /home_ui لحظياً (حتى تنعكس تغييرات الأدمن فورًا)
    _apply_runtime_cfg()

    # استخدم uid لاظهار تاريخ انتهاء VIP
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
    """
    في بعض الإصدارات السابقة كان الزر يستخدم callback_data='supplier_panel'
    ولعدم وجود هاندلر له عندك ظهر تحذير Unhandled callback.
    هذا alias يوجه المستخدم لنفس لوحة المورّد العامة (supplier_public) أو يشرح.
    """
    try:
        await cb.answer()
        await cb.message.edit_text(
            "🛍️ لوحة المورّد غير متاحة مباشرة من هنا.\n"
            "استخدم زر «لوحة المورّد» من القائمة الرئيسية أو اذهب إلى «المورّدون الموثوقون».",
        )
    except Exception:
        pass
