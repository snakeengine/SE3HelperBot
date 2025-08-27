# handlers/home_hero.py
from __future__ import annotations

import json, os
from pathlib import Path

from aiogram import Router
from aiogram.types import Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang

router = Router(name="home_hero")  # للسلاسة مع الاستيراد

# مصادر اختيارية لمعرفة الدور/‏VIP
try:
    from utils.suppliers import is_supplier as _is_supplier
except Exception:
    _is_supplier = None

try:
    from utils.vip_store import is_vip as _is_vip
except Exception:
    _is_vip = None

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

def _count_known_users() -> int:
    try:
        data = json.loads(KNOWN_USERS_FILE.read_text("utf-8"))
        if isinstance(data, dict):
            return len([k for k in data.keys() if str(k).isdigit()])
        if isinstance(data, list):
            return len(data)
    except Exception:
        pass
    return 1

def _load_alert_counts(user_id: int, lang: str) -> tuple[int, int]:
    total = unseen = 0
    try:
        box = json.loads(USERBOX_FILE.read_text("utf-8")).get(str(user_id)) or {}
        seen = set(box.get("seen", []))
        ignored = set(box.get("ignored", []))
        deleted = set(box.get("deleted", []))
    except Exception:
        seen = ignored = deleted = set()

    try:
        from utils.alerts_broadcast import get_active_alerts
        items = get_active_alerts(lang)
    except Exception:
        items = []

    kept = [it["id"] for it in items if it["id"] not in ignored and it["id"] not in deleted]
    total = len(kept)
    unseen = len([i for i in kept if i not in seen])
    return total, unseen

# === مفاتيح الكولباك (مطابقة لبقيّة المشروع) ===
CB = {
    "SEP": "ui:sep",
    "TOOLS": "tools",
    "APP_DOWNLOAD": "app:download",
    "TRUSTED_SUPPLIERS": "trusted_suppliers",
    "CHECK_DEVICE": "check_device",
    "VIP_OPEN": "vip:open",
    "SECURITY_STATUS": "security_status",
    "SAFE_USAGE": "safe_usage:open",
    "SERVER_STATUS": "server_status",
    "LANG": "change_lang",
    "RESELLER_INFO": "reseller_info",
    "PROMO_INFO": "prom:info",
}

def _build_main_kb(lang: str):
    kb = InlineKeyboardBuilder()
    def row(*btns): kb.row(*btns)
    def header(text: str): return InlineKeyboardButton(text=text, callback_data=CB["SEP"])

    row(header("🧭 " + _k(lang, "sec_user_title", "القائمة العامة" if lang == "ar" else "General menu")))
    row(
        InlineKeyboardButton(text="📥 " + _k(lang, "btn_download", "تحميل تطبيق الثعبان" if lang == "ar" else "Download app"), callback_data=CB["APP_DOWNLOAD"]),
        InlineKeyboardButton(text="🎛️ " + _k(lang, "btn_game_tools", "أدوات وتعديلات الألعاب" if lang == "ar" else "Game tools & mods"), callback_data=CB["TOOLS"]),
    )
    row(
        InlineKeyboardButton(text="🏷️ " + _k(lang, "btn_trusted_suppliers", "المورّدون الموثوقون" if lang == "ar" else "Trusted suppliers"), callback_data=CB["TRUSTED_SUPPLIERS"]),
        InlineKeyboardButton(text="📱 " + _k(lang, "btn_check_device", "تحقق من جهازك" if lang == "ar" else "Check your device"), callback_data=CB["CHECK_DEVICE"]),
    )
    row(InlineKeyboardButton(text="👑 " + _k(lang, "btn_vip_subscribe", "الاشتراك VIP" if lang == "ar" else "VIP subscription"), callback_data=CB["VIP_OPEN"]))
    row(
        InlineKeyboardButton(text="🧠 " + _k(lang, "btn_safe_usage", "دليل الاستخدام الآمن" if lang == "ar" else "Safe-usage guide"), callback_data=CB["SAFE_USAGE"]),
        InlineKeyboardButton(text="🛡️ " + _k(lang, "btn_security", "حالة الأمان" if lang == "ar" else "Security status"), callback_data=CB["SECURITY_STATUS"]),
    )
    row(
        InlineKeyboardButton(text="📊 " + _k(lang, "btn_server_status", "حالة السيرفرات" if lang == "ar" else "Server status"), callback_data=CB["SERVER_STATUS"]),
        InlineKeyboardButton(text="🌐 " + _k(lang, "btn_lang", "تغيير اللغة" if lang == "ar" else "Change language"), callback_data=CB["LANG"]),
    )
    row(InlineKeyboardButton(text="❓ " + _k(lang, "btn_be_supplier_long", "كيف تصبح مورّدًا؟" if lang == "ar" else "How to become a supplier?"), callback_data=CB["RESELLER_INFO"]))
    row(InlineKeyboardButton(text="📣 " + _k(lang, "btn_be_promoter", "كيف تصبح مروّجًا؟" if lang == "ar" else "How to become a promoter?"), callback_data=CB["PROMO_INFO"]))
    return kb.as_markup()

def _hero_text(lang: str, *, first_name: str, is_supplier: bool, is_vip: bool,
               alerts_total: int, alerts_unseen: int, known_users: int, app_ver: str, lang_label: str) -> str:
    title  = _k(lang, "home_title_plain", "مرحبًا بك في محرك الثعبان" if lang == "ar" else "Welcome to Snake Engine")
    pitch  = _k(lang, "pitch_plain", "منصة قوية لتعديل ألعاب أندرويد — بدون روت وبدون حظر." if lang == "ar" else "Powerful Android modding — no root, no bans.")
    safety = _k(lang, "safety_plain", "الأمان أولًا: خصائص وقائية، محاكي معزول، لا أدوات خطرة." if lang == "ar" else "Safety-first: protective features, sandboxed emulator, no risky tools.")
    cta    = _k(lang, "cta_plain", "ابدأ الآن — اختر أداتك:" if lang == "ar" else "Start now — choose your tool:")

    role = (_k(lang, "hero.role.supplier", "مورّد" if lang == "ar" else "Supplier") if is_supplier
            else _k(lang, "hero.role.user", "مستخدم" if lang == "ar" else "User"))

    vip_word = _k(lang, "hero.badge.vip", "VIP")
    vip_yes  = _k(lang, "hero.badge.vip_yes", "نعم" if lang == "ar" else "Yes")
    vip_no   = _k(lang, "hero.badge.vip_no", "لا" if lang == "ar" else "No")

    alerts_word = _k(lang, "hero.badge.alerts", "إشعارات" if lang == "ar" else "Alerts")
    role_word   = _k(lang, "hero.badge.role", "الدور" if lang == "ar" else "Role")
    lang_word   = _k(lang, "hero.badge.lang", "اللغة" if lang == "ar" else "Lang")
    users_word  = _k(lang, "hero.badge.users", "المستخدمون" if lang == "ar" else "Users")
    ver_word    = _k(lang, "hero.badge.version", "الإصدار" if lang == "ar" else "Version")

    if alerts_total == 0:
        alerts_str = f"🟢 {_k(lang, 'hero.status.ok', 'لا إشعارات' if lang=='ar' else 'All caught up')}"
    elif alerts_unseen == 0:
        alerts_str = f"🟢 {alerts_word}: {alerts_unseen}/{alerts_total}"
    else:
        alerts_str = f"🔔 {alerts_word}: {alerts_unseen}/{alerts_total}"

    lines = [
        f"🐍  {title}",
        f"┌──────────────────────────────────────────",
        f"│ 👋 {first_name}",
        f"│ {pitch}",
        f"│ {safety}",
        f"│",
        f"│ {alerts_str}",
        f"│ 👤 {role_word}: {role}    ⭐ {vip_word}: {vip_yes if is_vip else vip_no}",
        f"│ 🌐 {lang_word}: {lang_label}    👥 {users_word}: {known_users}    ⚙️ {ver_word}: {app_ver}",
        f"└──────────────────────────────────────────",
        f"• {_k(lang,'hero.point.safety','الأمان أولًا؛ حماية وقائية، تجنّب أدوات خطرة.' if lang=='ar' else 'Safety first; protective features.')}",
        f"• {_k(lang,'hero.point.updates','تحديثات دقيقة؛ ألعاب وتذكيرات دورية.' if lang=='ar' else 'Precise updates; games & periodic reminders.')}",
        f"• {_k(lang,'hero.point.support','دعم سريع؛ إجابات موثوقة.' if lang=='ar' else 'Fast support; reliable answers.')}",
        f"",
        f"💡 {_k(lang,'hero.tip','استخدم القائمة السفلية للأقسام السريعة ⬇️' if lang=='ar' else 'Use the bottom menu for quick sections ⬇️')}",
        f"",
        f"{cta}",
    ]
    return "<pre>" + "\n".join(lines) + "</pre>"

async def render_home_card(message: Message, *, lang: str | None = None):
    """
    يرسل بطاقة Hero Pro.
    ✅ المهم: يمكن تمرير lang صراحةً (ar/en). لو لم تُمرَّر → نقرأ لغة المستخدم مرة واحدة فقط.
    """
    _lang = (lang or get_user_lang(message.from_user.id) or "en").strip().lower()
    if _lang not in {"ar", "en"}:
        _lang = "en"

    is_sup = bool(_is_supplier and _is_supplier(message.from_user.id))
    is_vip = bool(_is_vip and _is_vip(message.from_user.id))
    total, unseen = _load_alert_counts(message.from_user.id, _lang)
    known = _count_known_users()
    app_ver = os.getenv("APP_VERSION", "v1")
    lang_label = "AR" if _lang == "ar" else "EN"

    text = _hero_text(
        _lang,
        first_name=message.from_user.first_name or ("ضيف" if _lang == "ar" else "Guest"),
        is_supplier=is_sup,
        is_vip=is_vip,
        alerts_total=total,
        alerts_unseen=unseen,
        known_users=known,
        app_ver=app_ver,
        lang_label=lang_label,
    )
    await message.answer(text, reply_markup=_build_main_kb(_lang), parse_mode="HTML", disable_web_page_preview=True)
