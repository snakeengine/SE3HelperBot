# admin/admin_hub.py
from __future__ import annotations

import os, json, time, re, io, csv, aiosqlite
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat, BufferedInputFile
)
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from utils.admins import ADMIN_IDS as DYN_ADMIN_IDS, is_admin as _is_admin
from admin.admin_roles_panel import _panel_text as adm_panel_text, _kb_main as adm_kb_main
from lang import t, get_user_lang
from utils.paths import BASE
from admin.promo_panel_ui import kb_panel_home as promo_kb_panel_home

from services.orders import DB_PATH, DB_IS_URI

# أدوار الأدمن (استخدم النسخة الموحّدة من utils.admin_roles فقط)
from utils.admin_roles import (
    ROLES_FILE as ADMIN_ROLES_FILE,
    ROLES as _ADM_ROLES,
    load_roles as _admacc_load,
    save_roles as _admacc_save,
    role_label as _admacc_role_label,
    fmt_ids as _admacc_fmt_ids,
    parse_ids as _admacc_parse_ids,
)

# متجر المفاتيح (اختياري)
try:
    from services import inventory as _shop_inv
except Exception:
    _shop_inv = None

try:
    from services import orders as _shop_ords
except Exception:
    _shop_ords = None

router = Router(name="admin_hub")

# ===================== أدوات عامة =====================
def _load(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(p: Path, obj):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass

def tt(lang: str, key: str, fallback: str) -> str:
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fallback

# ===================== مسارات ملفات الدردشة/التقارير =====================
DATA = BASE
LIVE_CONFIG       = DATA / "live_config.json"
SESSIONS_FILE     = DATA / "live_sessions.json"
BLOCKLIST_FILE    = DATA / "live_blocklist.json"
ADMIN_SEEN_FILE   = DATA / "admin_last_seen.json"
ADMIN_ONLINE_TTL  = int(os.getenv("ADMIN_ONLINE_TTL", "600"))

# “التقارير”
RIN_THREADS_FILE        = DATA / "support_threads.json"
REPORT_BLOCKLIST_FILE   = DATA / "report_blocklist.json"
REPORT_SETTINGS_FILE    = DATA / "report_settings.json"

# ===== مفاتيح: تشغيل/إيقاف متجر المفاتيح =====
FLAGS_PATH = DATA / "shop_flags.json"

try:
    from services.payments import (
        is_keys_service_enabled as _p_is_enabled,
        set_keys_service_enabled as _p_set_enabled,
        get_keys_stop_message as _p_get_stop_msg,
        set_keys_stop_message as _p_set_stop_msg,
    )
    def _keys_enabled() -> bool:      return bool(_p_is_enabled())
    def _set_keys_enabled(v: bool):   return _p_set_enabled(bool(v))
    def _get_stop_msg() -> str:       return _p_get_stop_msg() or ""
    def _set_stop_msg(msg: str):      return _p_set_stop_msg(msg or "")
except Exception:
    def _keys_enabled() -> bool:
        d = _load(FLAGS_PATH) or {}
        return not bool(d.get("keys_disabled", False))
    def _set_keys_enabled(v: bool):
        d = _load(FLAGS_PATH) or {}
        d["keys_disabled"] = (not bool(v))
        _save(FLAGS_PATH, d)
    def _get_stop_msg() -> str:
        d = _load(FLAGS_PATH) or {}
        return str(d.get("keys_stop_message", "") or "")
    def _set_stop_msg(msg: str):
        d = _load(FLAGS_PATH) or {}
        d["keys_stop_message"] = str(msg or "")
        _save(FLAGS_PATH, d)

# ===== دعم الدردشة الحية =====
def _support_enabled() -> bool:
    return bool(_load(LIVE_CONFIG).get("enabled", True))

def _set_support_enabled(v: bool):
    cfg = _load(LIVE_CONFIG); cfg["enabled"] = bool(v); _save(LIVE_CONFIG, cfg)

def _admin_is_online(admin_id: int) -> bool:
    d = _load(ADMIN_SEEN_FILE)
    v = d.get(str(admin_id))
    if isinstance(v, dict):
        return bool(v.get("online"))
    try:
        return (time.time() - float(v)) <= ADMIN_ONLINE_TTL
    except Exception:
        return False

def _set_admin_online(admin_id: int, online: bool):
    d = _load(ADMIN_SEEN_FILE)
    row = d.get(str(admin_id)) or {}
    row["online"] = bool(online)
    row["ts"] = time.time()
    d[str(admin_id)] = row
    _save(ADMIN_SEEN_FILE, d)

def _online_admins_count() -> int:
    d = _load(ADMIN_SEEN_FILE); now = time.time()
    n = 0
    for v in d.values():
        if isinstance(v, dict):
            if v.get("online"):
                n += 1
        else:
            try:
                if (now - float(v)) <= ADMIN_ONLINE_TTL: n += 1
            except Exception:
                pass
    return n

# ====== عدّادات الوارد للتقارير ======
def _rin_counts():
    open_n = closed_n = 0
    try:
        d = _load(RIN_THREADS_FILE) or {}
        threads = d.get("threads") or {}
        for th in threads.values():
            st = (th or {}).get("status", "open")
            if st == "open": open_n += 1
            else: closed_n += 1
    except Exception:
        pass

    blocked = 0
    try:
        bl = _load(REPORT_BLOCKLIST_FILE) or {}
        blocked += len(list(bl.keys()))
    except Exception:
        pass
    try:
        st = _load(REPORT_SETTINGS_FILE) or {}
        banned = st.get("banned") or []
        blocked += len([x for x in banned if str(x).isdigit() ])
    except Exception:
        pass

    return open_n, closed_n, blocked

# ===================== التطبيق (APK) =====================
try:
    from handlers.app_download import (
        _load_release as app_load_release,
        _caption as app_caption,
        _info_text as app_info_text,
    )
except Exception:
    app_load_release = None
    app_caption = None
    app_info_text = None

APP_META = BASE / "app_latest.json"     # يقرؤه handlers.app_download
VERSION_FILE = BASE / "VERSION"
APK_MIME = {"application/vnd.android.package-archive", "application/octet-stream"}

class AppUpload(StatesGroup):
    wait_apk = State()

# 👇 انقل هذا التعريف إلى هنا (وقم بحذف النسخة الموجودة أسفل الملف)
class LiveQuickStates(StatesGroup):
    wait_unban_uid = State()
    wait_ban_uid   = State()

def _extract_ver(name: str) -> str | None:
    m = re.search(r"(\d+(?:\.\d+){1,3})", name or "")
    return m.group(1) if m else None

# ===================== عدد المستخدمين =====================
try:
    from middlewares.user_tracker import get_users_count
except Exception:
    def get_users_count() -> int:
        try:
            p = BASE / "users.json"
            if not p.exists(): return 0
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                u = data.get("users")
                if isinstance(u, dict): return len(u)
                if isinstance(u, list): return len(u)
                return len(data)
            if isinstance(data, list): return len(data)
            return 0
        except Exception:
            return 0

ADMIN_IDS = DYN_ADMIN_IDS

# ===================== أوامر السلاش الافتراضية =====================
def _public_cmds_en() -> list[BotCommand]:
    return [
        BotCommand(command="start",          description=t("en", "cmd_start")),
        BotCommand(command="help",           description=t("en", "cmd_help")),
        BotCommand(command="about",          description=t("en", "cmd_about")),
        BotCommand(command="report",         description=t("en", "cmd_report")),
        BotCommand(command="language",       description=t("en", "cmd_language")),
        BotCommand(command="setlang",        description="Choose language"),
        BotCommand(command="apply_supplier", description="Apply as supplier"),
    ]

async def _clean_all_bot_commands(bot):
    await bot.set_my_commands([], scope=BotCommandScopeDefault(), language_code="en")
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=admin_id), language_code="en")
        except Exception:
            pass

async def _restore_default_bot_commands(bot):
    await bot.set_my_commands(_public_cmds_en(), scope=BotCommandScopeDefault(), language_code="en")
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(_public_cmds_en(), scope=BotCommandScopeChat(chat_id=admin_id), language_code="en")
        except Exception:
            pass

# ===================== جوائز: إحصاءات سريعة =====================
def _rwd_stats():
    try:
        p = BASE / "rewards_store.json"
        if not p.exists():
            return {"users": 0, "total_points": 0, "banned": 0}
        d = json.loads(p.read_text(encoding="utf-8")) or {}
        users = d.get("users") or {}
        total_users = 0
        total_points = 0
        banned = 0
        for uid, u in users.items():
            if not isinstance(u, dict):
                continue
            total_users += 1
            try:
                total_points += int(u.get("points", 0))
            except Exception:
                pass
            if u.get("banned"):
                banned += 1
        return {"users": total_users, "total_points": total_points, "banned": banned}
    except Exception:
        return {"users": 0, "total_points": 0, "banned": 0}

# ===================== لوحات =====================
def _kb_main(lang: str) -> InlineKeyboardMarkup:
    ver = ""
    if app_load_release:
        try:
            rel = app_load_release()
            if rel and rel.get("version") and rel["version"] != "-":
                ver = f" ({rel['version']})"
        except Exception:
            ver = ""

    open_n, closed_n, blocked_n = _rin_counts()
    inbox_badge = f" {open_n}" if open_n else ""

    suppliers_reqs    = "📂 " + tt(lang, "admin_hub_btn_resapps", "طلبات الموردين")
    suppliers_dir     = "📖 " + tt(lang, "admin_hub_btn_supdir", "دليل الموردين")
    app_txt           = "📦 " + tt(lang, "admin_hub_btn_app", "التطبيق (APK)") + ver
    security_txt      = "🛡️ " + tt(lang, "admin_hub_btn_security", "الأمن (الألعاب) • أدمن")
    reports_hub       = "📮 " + tt(lang, "admin_hub_btn_reports_hub", "التقارير") + inbox_badge
    servers_inbox     = "📡 " + tt(lang, "admin_hub_btn_server", "السيرفرات — الوارد")
    alerts_txt        = "🔔 " + tt(lang, "admin_hub_btn_alerts", "الإشعارات")
    users_count       = "👥 " + tt(lang, "admin_hub_btn_users_count", "عدد المستخدمين")
    promoters_txt     = "📣 " + tt(lang, "admin_hub_btn_promoters", "تحكم المروّجين")
    maint_text        = "🛠️ " + tt(lang, "admin_hub_btn_maintenance", "وضع الصيانة")
    live_text         = "💬 " + tt(lang, "admin.live.btn.panel", "الدردشة الحيّة")
    bot_cmds_txt      = "🧹 " + tt(lang, "admin_hub_btn_botcmds", "أوامر البوت")
    vip_admin_txt     = "👑 " + tt(lang, "admin_hub_btn_vip_admin", "إدارة VIP")
    rewards_admin_txt = "🏆 " + tt(lang, "admin_hub_btn_rewards_admin", "إدارة الجوائز")
    shop_admin_txt    = "🛍️ " + tt(lang, "admin_hub_btn_shop", "متجر المفاتيح")
    admin_access_txt  = "👥 " + tt(lang, "admin_hub_btn_admin_access", "إدارة الأدمن")
    features_txt      = "🧰 " + tt(lang, "admin_hub_btn_features", "التبويبات/الصيانة")
    promo_panel_txt   = "🎛️ " + tt(lang, "admin_hub_btn_promo_panel", "لوحة SEVIP")
    close_txt         = "❌ " + tt(lang, "admin_hub_btn_close", "إغلاق")

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=suppliers_reqs, callback_data="ah:resapps"),
        InlineKeyboardButton(text=suppliers_dir,  callback_data="ah:supdir"),
    )
    kb.row(
        InlineKeyboardButton(text=app_txt,      callback_data="ah:app"),
        InlineKeyboardButton(text=security_txt, callback_data="sec:admin"),
    )
    kb.row(
        InlineKeyboardButton(text=reports_hub,   callback_data="ah:reports"),
        InlineKeyboardButton(text=servers_inbox, callback_data="server_status:admin"),
    )
    kb.row(InlineKeyboardButton(text=shop_admin_txt, callback_data="ah:shop"))
    kb.row(InlineKeyboardButton(text=alerts_txt,     callback_data="ah:alerts"))
    kb.row(
        InlineKeyboardButton(text=users_count,   callback_data="ah:users_count"),
        InlineKeyboardButton(text=promoters_txt, callback_data="promadm:open"),
    )
    kb.row(InlineKeyboardButton(text=promo_panel_txt, callback_data="ah:promo"))
    kb.row(
        InlineKeyboardButton(text=admin_access_txt, callback_data="ahc:send:/admins_panel"),
        InlineKeyboardButton(text=features_txt,     callback_data="ft:open"),
    )
    kb.row(InlineKeyboardButton(text=rewards_admin_txt, callback_data="ah:rewards"))
    kb.row(
        InlineKeyboardButton(text=maint_text, callback_data="maint:status"),
        InlineKeyboardButton(text=live_text,  callback_data="ah:live"),
    )
    kb.row(InlineKeyboardButton(text=bot_cmds_txt, callback_data="ah:bot_cmds"))
    kb.row(
        InlineKeyboardButton(text=vip_admin_txt, callback_data="vipadm:menu"),
        InlineKeyboardButton(text=close_txt,     callback_data="ah:close"),
    )
    return kb.as_markup()

# === لوحات متجر المفاتيح ===
def _kb_shop_main(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # تشغيل/إيقاف الخدمة
    kb.row(
        InlineKeyboardButton(
            text=("🟢 " + tt(lang, "admin.shop.btn.disable", "إيقاف الخدمة")) if _keys_enabled()
                 else ("🔴 " + tt(lang, "admin.shop.btn.enable", "تشغيل الخدمة")),
            callback_data="ah:shop:toggle"
        )
    )
    # المخزون / التقارير
    kb.row(
        InlineKeyboardButton(text="📦 " + tt(lang, "admin.shop.btn.inventory", "المخزون"), callback_data="ah:shop:inv"),
        InlineKeyboardButton(text="📊 " + tt(lang, "admin.shop.btn.reports", "التقارير"),  callback_data="ah:shop:rpt"),
    )
    # فحص سريع للمخزون
    kb.row(
        InlineKeyboardButton(text="🔎 " + tt(lang, "admin.shop.btn.scan", "فحص المخزون"), callback_data="shop:scan")
    )
    # رجوع
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()


def _kb_shop_inv(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # أزرار مساعدة للفحص/تحديث
    kb.row(
        InlineKeyboardButton(text="🔎 " + tt(lang, "admin.shop.inv.scan", "فحص المخزون"), callback_data="shop:scan"),
        InlineKeyboardButton(text="🔁 " + tt(lang, "admin.shop.inv.refresh", "تحديث"),    callback_data="shop:inv"),
    )
    # رجوع للمتجر
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:shop"))
    return kb.as_markup()

# === قائمة فرعية للتقارير ===
def _kb_reports(lang: str) -> InlineKeyboardMarkup:
    open_n, closed_n, blocked_n = _rin_counts()
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"📥 {tt(lang,'admin_hub_btn_reports_inbox','الوارد')} ({open_n})", callback_data="rin:open"),
        InlineKeyboardButton(text=f"⚙️ {tt(lang,'admin_hub_btn_reports_settings','الإعدادات')}",       callback_data="ra:open"),
    )
    kb.row(
        InlineKeyboardButton(text=f"🚫 {tt(lang,'admin_hub_btn_reports_banned','المحظورين')} ({blocked_n})", callback_data="ra:banned"),
        InlineKeyboardButton(text=f"📊 {tt(lang,'admin_hub_btn_reports_stats','إحصاءات')}",              callback_data="ah:rstats"),
    )
    kb.row(InlineKeyboardButton(text="🛠️ " + tt(lang,"admin_hub_btn_reports_shortcuts","اختصارات"), callback_data="ah:rshort"))
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang,"admin.back","رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

# === قائمة الإشعارات ===
def _kb_alerts(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=tt(lang, "alerts.menu.edit", "✍️ تعديل النص"),        callback_data="al:edit")
    kb.button(text=tt(lang, "alerts.menu.preview", "👀 معاينة"),          callback_data="al:prev")
    kb.button(text=tt(lang, "alerts.menu.send_now", "📢 إرسال الآن"),     callback_data="al:send")
    kb.button(text=tt(lang, "alerts.menu.schedule", "🕒 جدولة"),          callback_data="al:sch")
    kb.button(text=tt(lang, "alerts.menu.quick", "⏱ جدولة سريعة"),       callback_data="al:schq")
    kb.button(text=tt(lang, "alerts.menu.jobs", "🗓 الجوبز المجدولة"),    callback_data="al:jobs")
    kb.button(text=tt(lang, "alerts.menu.kind", "🗂 النوع"),              callback_data="al:kind")
    kb.button(text=tt(lang, "alerts.menu.lang", "🌐 وضع اللغة"),          callback_data="al:lang")
    kb.button(text=tt(lang, "alerts.menu.settings", "⚙️ الإعدادات"),      callback_data="al:cfg")
    kb.button(text=tt(lang, "alerts.menu.delete", "🗑️ حذف المسودة"),     callback_data="al:del")
    kb.button(text=tt(lang, "alerts.menu.stats", "📊 إحصائيات"),          callback_data="al:stats")
    kb.button(text=tt(lang, "alerts.menu.list", "🗒️ قائمة"),             callback_data="al:list")
    kb.button(text="⬅️ " + tt(lang, "admin.back", "رجوع"),               callback_data="ah:menu")
    kb.adjust(2,2,2,2,2,1)
    return kb.as_markup()

async def _safe_edit_text(message, text: str, **kwargs):
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        try:
            await message.answer(text, **kwargs)
        except Exception:
            pass

# ===================== إدارة قائمة الإشعارات (موحّدة) =====================

# مسارات مستخدمة لصناديق المستخدمين (نفس اللي يستعملها home_hero)
BASE = BASE
DATA_DIR = BASE
USERBOX_FILE = DATA_DIR / "alerts_userbox.json"

# نجرب utils.alerts_broadcast، وإلا نستخدم فولباك ملف محلي
try:
    from utils.alerts_broadcast import list_all_alerts as _ab_list_all   # [{id, lang, kind, text, ...}]
except Exception:
    _ab_list_all = None
try:
    from utils.alerts_broadcast import delete_alert as _ab_delete        # delete_alert(alert_id) -> bool
except Exception:
    _ab_delete = None

ALERTS_STORE = BASE / "alerts_store.json"

def _alerts__load_store() -> dict:
    try:
        if ALERTS_STORE.exists():
            return json.loads(ALERTS_STORE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {"alerts": []}

def _alerts__save_store(d: dict) -> None:
    try:
        ALERTS_STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ALERTS_STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ALERTS_STORE)
    except Exception:
        pass

def _alerts_list_all() -> list[dict]:
    try:
        if _ab_list_all:
            lst = _ab_list_all() or []
            return sorted(lst, key=lambda x: x.get("created_ts", 0), reverse=True)
    except Exception:
        pass
    d = _alerts__load_store()
    lst = d.get("alerts") or []
    return sorted(lst, key=lambda x: x.get("created_ts", 0), reverse=True)

def _alerts_delete_one(alert_id: str) -> bool:
    ok = False
    if _ab_delete:
        try:
            ok = bool(_ab_delete(alert_id))
        except Exception:
            ok = False
    if not ok:
        d = _alerts__load_store()
        before = len(d.get("alerts") or [])
        d["alerts"] = [a for a in (d.get("alerts") or []) if str(a.get("id")) != str(alert_id)]
        _alerts__save_store(d)
        ok = len(d.get("alerts") or []) < before
    if ok:
        _alerts_remove_from_userboxes(alert_id)
    return ok

def _alerts_remove_from_userboxes(alert_id: str) -> None:
    try:
        if not USERBOX_FILE.exists():
            return
        data = json.loads(USERBOX_FILE.read_text("utf-8")) or {}
        changed = False
        for uid, box in list(data.items()):
            if not isinstance(box, dict):
                continue
            for k in ("seen", "ignored", "deleted"):
                lst = list(box.get(k) or [])
                if not lst:
                    continue
                nlst = [x for x in lst if str(x) != str(alert_id)]
                if len(nlst) != len(lst):
                    box[k] = nlst
                    changed = True
        if changed:
            tmp = USERBOX_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, USERBOX_FILE)
    except Exception:
        pass

def _kb_alerts_list(lang: str, page: int = 0, per: int = 8) -> InlineKeyboardMarkup:
    alerts = _alerts_list_all()
    start = page * per
    chunk = alerts[start:start+per]

    kb = InlineKeyboardBuilder()
    for a in chunk:
        a_id = str(a.get("id") or "")
        kind = (a.get("kind") or "alert").lower()
        alang = (a.get("lang") or "all").upper()
        title = (a.get("title") or "").strip()
        label = title if title else (a.get("text") or "").strip()[:28].replace("\n", " ")
        label = label if label else a_id
        left = f"{alang} • {kind} • {label}"

        kb.row(
            InlineKeyboardButton(text=f"👁 {left}", callback_data=f"al:prev:{a_id}"),
            InlineKeyboardButton(text="🗑 حذف",     callback_data=f"al:del:{a_id}"),
        )

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"al:list:{page-1}"))
    if start + per < len(alerts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"al:list:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:alerts"))
    return kb.as_markup()

@router.callback_query(F.data == "al:list")
async def al_list_open(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alerts = _alerts_list_all()
    total = len(alerts)
    head = "🗒️ " + tt(lang, "alerts.list.title", "قائمة الإشعارات") + f" — {total}"
    text = f"<b>{head}</b>\n" + tt(lang, "alerts.list.tip", "اختر معاينة أو حذف لإشعار محدّد.")
    await _safe_edit_text(
        cb.message,
        text,
        reply_markup=_kb_alerts_list(lang, 0),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await cb.answer()

@router.callback_query(F.data.startswith("al:list:"))
async def al_list_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    page = int(cb.data.split(":")[-1])
    alerts = _alerts_list_all()
    total = len(alerts)
    head = "🗒️ " + tt(lang, "alerts.list.title", "قائمة الإشعارات") + f" — {total}"
    text = f"<b>{head}</b>\n" + tt(lang, "alerts.list.tip", "اختر معاينة أو حذف لإشعار محدّد.")
    await _safe_edit_text(
        cb.message,
        text,
        reply_markup=_kb_alerts_list(lang, page),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await cb.answer()

@router.callback_query(F.data.startswith("al:prev:"))
async def al_prev_one(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alert_id = cb.data.split(":")[-1]
    a = next((x for x in _alerts_list_all() if str(x.get("id")) == str(alert_id)), None)
    if not a:
        return await cb.answer(tt(lang, "alerts.not_found", "الإشعار غير موجود"), show_alert=True)

    alang = (a.get("lang") or "all").upper()
    kind  = (a.get("kind") or "alert").lower()
    title = (a.get("title") or "").strip()
    body  = (a.get("text") or "").strip()
    meta  = f"{alang} • {kind} • id:{alert_id}"

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🗑 حذف", callback_data=f"al:del:{alert_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="al:list"))
    txt = f"🔔 <b>{title or '(no title)'}</b>\n<code>{meta}</code>\n\n{body}"
    await cb.message.answer(txt, reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()

@router.callback_query(F.data.startswith("al:del:"))
async def al_delete_confirm(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alert_id = cb.data.split(":")[-1]
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ " + tt(lang,"confirm","تأكيد"), callback_data=f"al:delok:{alert_id}"),
        InlineKeyboardButton(text="❎ " + tt(lang,"cancelled","إلغاء"), callback_data="al:list"),
    )
    await cb.message.answer(
        tt(lang, "alerts.delete.ask", "هل تريد حذف هذا الإشعار بالتأكيد؟"),
        reply_markup=kb.as_markup()
    )
    await cb.answer()

@router.callback_query(F.data.startswith("al:delok:"))
async def al_delete_do(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alert_id = cb.data.split(":")[-1]

    ok = _alerts_delete_one(alert_id)
    if not ok:
        return await cb.answer(tt(lang, "alerts.delete.fail", "تعذر حذف الإشعار."), show_alert=True)

    alerts = _alerts_list_all()
    total = len(alerts)
    head = "🗒️ " + tt(lang, "alerts.list.title", "قائمة الإشعارات") + f" — {total}"
    text = f"<b>{head}</b>\n" + tt(lang, "alerts.delete.done", "✅ تم الحذف. القائمة محدثة.")
    try:
        await cb.message.edit_text(text, reply_markup=_kb_alerts_list(lang, 0), parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=_kb_alerts_list(lang, 0), parse_mode=ParseMode.HTML)
    await cb.answer("✅")

# ===================== واجهات وتحكم عامة =====================
@router.message(Command("admin"))
async def admin_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "لوحة الأدمن ⚡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    await msg.answer(f"<b>{title}</b>\n{desc}",
                     reply_markup=_kb_main(lang),
                     disable_web_page_preview=True,
                     parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "ah:menu")
async def ah_menu(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "لوحة الأدمن ⚡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    try:
        await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                                   reply_markup=_kb_main(lang),
                                   disable_web_page_preview=True,
                                   parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

@router.callback_query(F.data == "ah:promo")
async def ah_open_promo(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    text = "🛠️ " + tt(lang, "promo.panel.title", "لوحة إدارة SEVIP") + " — " + tt(lang, "promo.panel.pick", "اختر فلترًا:")

    try:
        await cb.message.edit_text(
            text,
            reply_markup=promo_kb_panel_home(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except TelegramBadRequest:
        await cb.message.answer(
            text,
            reply_markup=promo_kb_panel_home(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    await cb.answer()

# ---- المتجر: الشاشة الرئيسية
@router.callback_query(F.data == "ah:shop")
async def ah_shop(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"

    open_orders = "-"
    if _shop_ords:
        try:
            if hasattr(_shop_ords, "count_open"):
                open_orders = await _shop_ords.count_open()
            elif hasattr(_shop_ords, "list_all_open"):
                rows = await _shop_ords.list_all_open()
                open_orders = len(rows or [])
            elif hasattr(_shop_ords, "list_pending"):
                rows = await _shop_ords.list_pending()
                open_orders = len(rows or [])
        except Exception:
            open_orders = "-"

    inv_c3 = inv_c10 = inv_c30 = "-"
    if _shop_inv:
        try:
            c = await _shop_inv.counts()
            inv_c3, inv_c10, inv_c30 = c.get(3, 0), c.get(10, 0), c.get(30, 0)
        except Exception:
            pass

    status_txt = "🟢 " + tt(lang, "admin.shop.on", "الخدمة مفعّلة") if _keys_enabled() else "🔴 " + tt(lang, "admin.shop.off", "الخدمة متوقفة")
    stop_msg = _get_stop_msg().strip()
    stop_line = tt(lang, "admin.shop.stopmsg", "• رسالة الإيقاف المخصّصة: {v}").format(v=("✅" if stop_msg else "—"))

    text = (
        "🛍️ <b>" + tt(lang, "admin.shop.title", "متجر المفاتيح") + "</b>\n"
        + status_txt + "\n"
        + stop_line + "\n"
        + tt(lang, "admin.shop.desc", "إدارة الطلبات والمخزون.") + "\n\n"
        + tt(lang, "admin.shop.stats", "📊 إحصاءات سريعة:") + "\n"
        + tt(lang, "admin.shop.stats.orders_open", "• الطلبات المفتوحة: {n}").format(n=open_orders) + "\n"
        + tt(lang, "admin.shop.stats.inv", "• المخزون — 3d/10d/30d: {a}/{b}/{c}").format(a=inv_c3, b=inv_c10, c=inv_c30)
    )
    try:
        await cb.message.edit_text(text, reply_markup=_kb_shop_main(lang), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

@router.callback_query(F.data == "ah:shop:toggle")
async def ah_shop_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    _set_keys_enabled(not _keys_enabled())
    await ah_shop(cb)

@router.callback_query(F.data == "ah:shop:inv")
async def shop_inv(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from services import inventory as _inv
        c = await _inv.counts()
        c3, c10, c30 = c.get(3,0), c.get(10,0), c.get(30,0)
    except Exception:
        c3 = c10 = c30 = 0

    hint_add  = tt(lang, "admin.shop.inv.hint_add",
                   "لرفع مفاتيح: أرسل المفاتيح كسطور ثم ردّ بالأمر:\n"
                   "<code>/inv_add 3|10|30</code> (د، الأيام)")
    hint_dump = tt(lang, "admin.shop.inv.hint_dump",
                   "للتصدير: <code>/inv_dump 3|10|30</code>")
    hint_del  = tt(lang, "admin.shop.inv.hint_del",
                   "لحذف مفرد: رد على الرسالة التي تحتوي المفاتيح بـ <code>/inv_del 3|10|30</code>\n"
                   "للحذف الجماعي: <code>/inv_clear 3|10|30</code>")
    stats_hdr = "📊 " + tt(lang, "admin.shop.inv.stats_title", "إحصاءات المخزون:") \
                + f"\n• 3d: <b>{c3}</b>\n• 10d: <b>{c10}</b>\n• 30d: <b>{c30}</b>"

    text = "📦 <b>" + tt(lang, "admin.shop.inv.title", "المخزون") + "</b>\n" \
           + hint_add + "\n" + hint_dump + "\n" + hint_del + "\n\n" + stats_hdr

    await cb.message.edit_text(text, reply_markup=_kb_shop_inv(lang), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "shop:inv")
async def shop_inv_panel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    stats = ""
    if _shop_inv:
        try:
            c = await _shop_inv.counts()
            stats = f"\n\n<b>{tt(lang,'shopadm.inv.stats','إحصاءات المخزون')}</b>\n• 3d: <code>{c.get(3,0)}</code>\n• 10d: <code>{c.get(10,0)}</code>\n• 30d: <code>{c.get(30,0)}</code>"
        except Exception:
            stats = ""
    help_txt = tt(
        lang, "shopadm.inv.help",
        "لرفع مفاتيح: أرسل المفاتيح كسطور ثم (ردّ) بـ /inv_add 3|10|30\n"
        "للتصدير: /inv_dump 3|10|30\n"
        "لحذف مفرد: ردّ بـ /inv_del 3|10|30\n"
        "للحذف الجماعي: /inv_clear 3|10|30"
    )
    await cb.message.edit_text(f"📦 <b>{tt(lang,'shopadm.inv.title','المخزون')}</b>\n{help_txt}{stats}",
                               reply_markup=_kb_shop_inv(lang),
                               parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "shop:scan")
async def shop_scan(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    if not _shop_inv:
        return await cb.answer(tt(lang, "shopadm.not_available", "وحدة المتجر غير متاحة"), show_alert=True)

    products = _list_known_products()
    errs = 0
    for prod in products:
        for d in (3, 10, 30):
            try:
                await _shop_inv.maybe_alert_low_stock(cb.bot, d, product=prod)
            except Exception:
                errs += 1

    summary = tt(lang, "shopadm.scan.done", "تم فحص المخزون الحالي.")
    prod_line = " • " + ", ".join(products)
    try:
        await cb.message.answer(f"{summary}\nالمنتجات:{prod_line}")
    except Exception:
        pass
    await cb.answer(tt(lang, "shopadm.scan.ok", "تم."), show_alert=False)

# ---------- NEW (موحّد): جمع المنتجات المعروفة للفحص/التقارير ----------
def _list_known_products() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    env_products = (os.getenv("SHOP_PRODUCTS") or os.getenv("SHOP_PRODUCT") or "")
    for p in env_products.split(","):
        p = p.strip().lower()
        if p and p not in seen:
            seen.add(p); out.append(p)

    default_prod = (os.getenv("PRODUCT_KEY") or "").strip().lower()
    if default_prod and default_prod not in seen:
        seen.add(default_prod); out.append(default_prod)

    try:
        inv_dir = BASE / "inventory"
        if inv_dir.exists():
            for sub in inv_dir.iterdir():
                if sub.is_dir():
                    name = sub.name.lower()
                    if name and name not in seen:
                        seen.add(name); out.append(name)
    except Exception:
        pass

    if not out:
        out = ["8bp", "carrom"]
    return out

# ---- الدردشة الحيّة
@router.callback_query(F.data == "ah:live")
async def ah_live(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    status = "🟢 " + tt(lang, "admin.live.status_on", "الدردشة مفعّلة") if _support_enabled() else "🔴 " + tt(lang, "admin.live.status_off", "الدردشة متوقفة")
    desc = tt(lang, "admin.live.desc", "إدارة الدردشة الحيّة:")

    cmds_text = (
        "\n\n🧰 أوامر سريعة:\n"
        "<code>/live_on</code> — تفعيل وضع الأونلاين لاستقبال طلبات الدردشة.\n"
        "<code>/live_off</code> — إيقاف وضع الأونلاين لعدم استقبال الطلبات."
    )

    await cb.message.edit_text(
        f"<b>{tt(lang, 'admin.live.title', 'الدردشة الحيّة')}</b>\n{status}\n{desc}{cmds_text}",
        reply_markup=_kb_live_main(lang, cb.from_user.id),
        parse_mode=ParseMode.HTML
    )
    await cb.answer()

@router.callback_query(F.data == "liveadm:toggle")
async def liveadm_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_support_enabled(not _support_enabled())
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        status = "🟢 " + tt(lang, "admin.live.status_on", "الدردشة مفعّلة") if _support_enabled() \
                 else "🔴 " + tt(lang, "admin.live.status_off", "الدردشة متوقفة")
        desc = tt(lang, "admin.live.desc", "إدارة الدردشة الحيّة:")

        cmds_text = (
            "\n\n🧰 أوامر سريعة:\n"
            "<code>/live_on</code> — تفعيل وضع الأونلاين لاستقبال طلبات الدردشة.\n"
            "<code>/live_off</code> — إيقاف وضع الأونلاين لعدم استقبال الطلبات."
        )

        await cb.message.edit_text(
            f"<b>{tt(lang, 'admin.live.title', 'الدردشة الحيّة')}</b>\n{status}\n{desc}{cmds_text}",
            reply_markup=_kb_live_main(lang, cb.from_user.id),
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

@router.callback_query(F.data == "liveadm:avail_on")
async def liveadm_avail_on(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_admin_online(cb.from_user.id, True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_live_main(lang, cb.from_user.id))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer(tt(lang, "admin.live.avail.on.done", "تم تفعيل توفرُك"), show_alert=True)

@router.callback_query(F.data == "liveadm:avail_off")
async def liveadm_avail_off(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_admin_online(cb.from_user.id, False)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_live_main(lang, cb.from_user.id))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer(tt(lang, "admin.live.avail.off.done", "تم إيقاف توفرُك"), show_alert=True)

@router.callback_query(F.data == "liveadm:touch")
async def liveadm_touch(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_admin_online(cb.from_user.id, True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_live_main(lang, cb.from_user.id))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer(tt(lang, "admin.live.touched", "تم تسجيل تواجدك"), show_alert=True)

def _kb_live_main(lang: str, admin_id: int) -> InlineKeyboardMarkup:
    on = _support_enabled()
    me_on = _admin_is_online(admin_id)
    online_n = _online_admins_count()

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=("🟢 " if on else "🔴 ") + (tt(lang, "admin.live.toggle_off", "إيقاف") if on else tt(lang, "admin.live.toggle_on", "تشغيل")),
            callback_data="liveadm:toggle"
        ),
        InlineKeyboardButton(
            text=("🛑 " + tt(lang, "admin.live.avail.off", "إيقاف")) if me_on else ("✅ " + tt(lang, "admin.live.avail.on", "أنا متاح الآن")),
            callback_data="liveadm:avail_off" if me_on else "liveadm:avail_on"
        )
    )
    kb.row(
        InlineKeyboardButton(text="📋 " + tt(lang, "admin.live.list", "قائمة الجلسات"), callback_data="liveadm:list"),
        InlineKeyboardButton(text=f"👥 {tt(lang, 'admin.live.online_count', 'المتصلون')}: {online_n}", callback_data="ah:noop")
    )
    kb.row(
        InlineKeyboardButton(text="🚫 " + tt(lang, "admin.live.btn.block_uid", "حظر (UID)"), callback_data="liveadm:ban_open"),
        InlineKeyboardButton(text="🔓 " + tt(lang, "admin.live.btn.unban_uid", "رفع الحظر (UID)"), callback_data="liveadm:unban_open"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

@router.callback_query(F.data == "liveadm:list")
async def liveadm_list(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    sessions = _load(SESSIONS_FILE)
    waiting: list[int] = []
    active: list[tuple[int,int]] = []
    for k, s in (sessions or {}).items():
        try:
            uid = int(k)
        except Exception:
            continue
        st = s.get("status")
        if st == "waiting":
            waiting.append(uid)
        elif st == "active":
            try:
                aid = int(s.get("admin_id") or 0)
            except Exception:
                aid = 0
            active.append((uid, aid))
    wt = ", ".join(map(str, waiting[:10])) or tt(lang, "admin.live.no_items", "لا يوجد")
    ac = ", ".join(f"{u}(a:{a})" for u, a in active[:10]) or tt(lang, "admin.live.no_items", "لا يوجد")
    text = (
        f"🗒️ <b>{tt(lang,'admin.live.list.title','الجلسات الحالية')}</b>\n"
        f"• {tt(lang,'admin.live.waiting','منتظرة')}: {wt}\n"
        f"• {tt(lang,'admin.live.active','نشِطة')}: {ac}\n"
        f"{tt(lang,'admin.live.hint','يمكنك الانضمام/الإنهاء/الحظر من الأزرار بالأسفل.')}"
    )
    await cb.message.edit_text(text, reply_markup=_kb_live_list(lang, waiting, active), parse_mode=ParseMode.HTML)
    await cb.answer()

def _kb_live_block_durations(uid: int, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="1h",   callback_data=f"liveadm:ban:{uid}:1"),
        InlineKeyboardButton(text="24h",  callback_data=f"liveadm:ban:{uid}:24"),
        InlineKeyboardButton(text="7d",   callback_data=f"liveadm:ban:{uid}:{24*7}"),
        InlineKeyboardButton(text="30d",  callback_data=f"liveadm:ban:{uid}:{24*30}"),
        InlineKeyboardButton(text="∞",    callback_data=f"liveadm:ban:{uid}:perm"),
    )
    kb.row(InlineKeyboardButton(text=tt(lang, "admin.back", "رجوع"), callback_data="liveadm:list"))
    return kb.as_markup()

def _kb_live_list(lang: str, waiting: list[int], active: list[tuple[int,int]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for uid in waiting[:5]:
        kb.row(
            InlineKeyboardButton(text=f"🟡 {uid}", callback_data="ah:noop"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.join", "انضمام"),  callback_data=f"live:accept:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.end", "إنهاء"),     callback_data=f"live:decline:{uid}"),
        )
        kb.row(
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.block", "حظر"), callback_data=f"liveadm:block:{uid}")
        )
    for uid, aid in active[:5]:
        kb.row(
            InlineKeyboardButton(text=f"🟢 {uid} · a:{aid}", callback_data="ah:noop"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.end", "إنهاء"), callback_data=f"live:end:{uid}"),
        )
        kb.row(
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.block", "حظر"),          callback_data=f"liveadm:block:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.unblock", "إلغاء حظر"), callback_data=f"liveadm:unblock:{uid}")
        )
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:live"))
    return kb.as_markup()

def ttf(lang: str, key: str, fb_en: str, fb_ar: str) -> str:
    try:
        val = t(lang or "en", key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fb_en if (lang or "en").lower().startswith("en") else fb_ar

@router.callback_query(F.data == "liveadm:unban_open")
async def liveadm_unban_open(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(LiveQuickStates.wait_unban_uid)
    await cb.message.answer(tt(lang, "live.unban.ask", "أرسل UID المراد رفع الحظر عنه.\n• للإلغاء: /cancel"))
    await cb.answer()

@router.message(LiveQuickStates.wait_unban_uid)
async def liveadm_unban_do(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "إلغاء", "الغاء"}:
        await state.clear()
        return await msg.reply(tt(lang, "cancelled", "Cancelled"))

    if not raw.isdigit():
        return await msg.reply(ttf(lang, "live.unban.bad",
                                   "Send a valid UID (digits only).",
                                   "أرسل UID صحيح (أرقام فقط)."))

    uid = int(raw)
    bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
    await state.clear()

    tlang = get_user_lang(uid) or "en"
    try:
        txt_user = ttf(tlang, "live.unban.user_ok",
                       "✅ Unban complete. You can try now.",
                       "✅ تم رفع الحظر. يمكنك المحاولة الآن.")
        await msg.bot.send_message(uid, txt_user)
    except Exception:
        pass

    await msg.reply(
        ttf(tlang, "live.unban.ok",
            "Unban complete for {uid}.",
            "تم رفع الحظر عن {uid}.").format(uid=uid)
    )

@router.callback_query(F.data == "liveadm:ban_open")
async def liveadm_ban_open(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(LiveQuickStates.wait_ban_uid)
    txt = tt(
        lang, "live.ban.ask",
        "أرسل الآن:\n<code>UID</code> أو <code>UID مدة_ساعات</code> (مثال: <code>123456 24</code>)\nللحظر دائمًا استخدم: <code>perm</code>\n• للإلغاء: /cancel"
    )
    await cb.message.answer(txt, parse_mode=ParseMode.HTML)
    await cb.answer()

@router.message(LiveQuickStates.wait_ban_uid)
async def liveadm_ban_do(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "").strip().lower()
    if raw in {"/cancel", "cancel", "إلغاء", "الغاء"}:
        await state.clear()
        return await msg.reply(tt(lang, "cancelled", "أُلغيت"))

    parts = raw.split()
    if not parts or not parts[0].isdigit():
        return await msg.reply(tt(lang, "live.ban.bad", "الرجاء إدخال UID صحيح، مثلاً: <code>123456</code> أو <code>123456 24</code>"), parse_mode=ParseMode.HTML)

    uid = int(parts[0])
    dur = (parts[1] if len(parts) >= 2 else "perm").lower()
    bl = _load(BLOCKLIST_FILE)
    if dur == "perm":
        bl[str(uid)] = {"until": 0, "reason": "by_admin", "by": msg.from_user.id}
    else:
        try:
            hours = int(dur)
        except Exception:
            return await msg.reply(tt(lang, "live.ban.bad_dur", "مدة غير صالحة. استخدم عدد الساعات أو perm."))
        bl[str(uid)] = {"until": time.time() + hours * 3600, "reason": "by_admin", "by": msg.from_user.id}
    _save(BLOCKLIST_FILE, bl)
    await state.clear()
    await msg.reply(tt(lang, "live.ban.ok", "تم حظر {uid}.").format(uid=uid))

@router.callback_query(F.data.startswith("liveadm:block:"))
async def liveadm_block(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    uid = int(cb.data.split(":")[-1])

    await cb.message.answer(
        tt(lang, "admin.live.block.pick", "اختر مدة الحظر للمستخدم: ") + f"<code>{uid:d}</code>",
        reply_markup=_kb_live_block_durations(uid, lang),
        parse_mode=ParseMode.HTML
    )
    await cb.answer()

@router.callback_query(F.data.startswith("liveadm:ban:"))
async def liveadm_ban(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    parts = cb.data.split(":")  # liveadm:ban:<uid>:<hours|perm>
    uid = int(parts[2]); dur = parts[3]
    bl = _load(BLOCKLIST_FILE)
    if dur == "perm":
        bl[str(uid)] = True
    else:
        hours = int(dur)
        until = time.time() + hours * 3600
        bl[str(uid)] = {"until": until}
    _save(BLOCKLIST_FILE, bl)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "admin.live.block.done", "تم الحظر"), show_alert=True)

@router.callback_query(F.data.startswith("liveadm:unblock:"))
async def liveadm_unblock(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    bl = _load(BLOCKLIST_FILE)
    bl.pop(str(uid), None)
    _save(BLOCKLIST_FILE, bl)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "admin.live.unblock.done", "تم إلغاء الحظر"), show_alert=True)

# ---- أوامر البوت
@router.callback_query(F.data == "ah:bot_cmds")
async def ah_bot_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "🧹 " + tt(lang, "admin.botcmds.title", "التحكم بأوامر البوت")
    desc  = tt(lang, "admin.botcmds.desc", "اختر إجراء:")
    await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                               reply_markup=_kb_bot_cmds(lang),
                               disable_web_page_preview=True,
                               parse_mode=ParseMode.HTML)
    await cb.answer()

def _kb_bot_cmds(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🧹 " + tt(lang, "admin.botcmds.clean_now", "تنظيف فوري"), callback_data="ah:bot_cmds:clean"),
        InlineKeyboardButton(text="↩️ " + tt(lang, "admin.botcmds.restore", "استعادة الأوامر"), callback_data="ah:bot_cmds:restore"),
    )
    kb.row(InlineKeyboardButton(text="♻️ /reload_cmds", callback_data="ahc:send:/reload_cmds"))
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

@router.callback_query(F.data == "ah:bot_cmds:clean")
async def ah_bot_cmds_clean(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    await _clean_all_bot_commands(cb.bot)
    await cb.answer("🧹 تم تنظيف أوامر البوت بالكامل.", show_alert=True)

@router.callback_query(F.data == "ah:bot_cmds:restore")
async def ah_bot_cmds_restore(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    await _restore_default_bot_commands(cb.bot)
    await cb.answer("↩️ تم استعادة أوامر البوت الافتراضية.", show_alert=True)

# ---- شاشة أوامر مختصرة
@router.callback_query(F.data == "ah:cmds")
async def ah_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "🔧 " + tt(lang, "admin.cmds.vip_title", "أوامر VIP")
    desc  = tt(lang, "admin.cmds.desc", "اختصارات لإرسال أوامر السلاش.")
    await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                               reply_markup=_kb_cmds(lang),
                               disable_web_page_preview=True,
                               parse_mode=ParseMode.HTML)
    await cb.answer()

def _kb_cmds(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=tt(lang, "admin.cmds.vipadm", "/vipadm"), callback_data="ahc:send:/vipadm"),
        InlineKeyboardButton(text="/vip",        callback_data="ahc:send:/vip"),
        InlineKeyboardButton(text="/vip_status", callback_data="ahc:send:/vip_status"),
        InlineKeyboardButton(text="📣 " + tt(lang, "promadm.btn.open", "إدارة المروّجين"), callback_data="promadm:open"),
    )
    kb.row(
        InlineKeyboardButton(text="/vip_track",  callback_data="ahc:send:/vip_track"),
        InlineKeyboardButton(text="/report",     callback_data="ahc:send:/report"),
    )
    kb.row(
        InlineKeyboardButton(text="/language",   callback_data="ahc:send:/language"),
        InlineKeyboardButton(text="/setlang",    callback_data="ahc:send:/setlang"),
    )
    kb.row(InlineKeyboardButton(text="/apply_supplier", callback_data="ahc:send:/apply_supplier"))
    kb.row(InlineKeyboardButton(text="📤 " + tt(lang, "admin.cmds.btn.send_all_slash", "إرسال كل أوامر السلاش"), callback_data="ahc:slash_all"))
    kb.row(InlineKeyboardButton(text=tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

@router.callback_query(F.data == "ahc:slash_all")
async def ahc_slash_all(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        "🧰 <b>" + tt(lang, "admin.cmds.slash_title", "أوامر السلاش") + "</b>\n"
        "<code>/rewards_admin</code> — " + tt(lang, "rwdadm.cmds.rewards_admin", "لوحة إدارة الجوائز") + "\n"
        "<code>/r_grant &lt;uid&gt; &lt;points&gt;</code> — " + tt(lang, "rwdadm.cmds.r_grant", "منح/خصم نقاط") + "\n"
        "<code>/r_setpts &lt;uid&gt; &lt;points&gt;</code> — " + tt(lang, "rwdadm.cmds.setpts", "تعيين النقاط") + "\n"
        "<code>/r_setstreak &lt;uid&gt; &lt;streak&gt;</code> — " + tt(lang, "rwdadm.cmds.setstreak", "تعيين السلسلة") + "\n"
        "<code>/r_ban &lt;uid&gt;</code> — " + tt(lang, "rwdadm.cmds.ban", "حظر المستخدم") + "\n"
        "<code>/r_unban &lt;uid&gt;</code> — " + tt(lang, "rwdadm.cmds.unban", "إلغاء الحظر") + "\n"
        "<code>/r_del &lt;uid&gt;</code> — " + tt(lang, "rwdadm.cmds.del", "حذف المستخدم") + "\n"
        "<code>/r_notify &lt;uid&gt; &lt;text&gt;</code> — " + tt(lang, "rwdadm.cmds.notify", "إشعار المستخدم") + "\n"
        "\n"
        "<code>/vipadm</code> — " + tt(lang, "admin.cmds.tip.vipadm", "لوحة إدارة VIP") + "\n"
        "<code>/vip</code> — " + tt(lang, "admin.cmds.tip.vip", "لوحة المستخدم VIP") + "\n"
        "<code>/vip_status</code> — " + tt(lang, "admin.cmds.tip.vip_status", "حالة اشتراك VIP") + "\n"
        "<code>/vip_track</code> — " + tt(lang, "admin.cmds.tip.vip_track", "تتبّع طلب VIP") + "\n"
        "<code>/report</code> — " + tt(lang, "admin.cmds.tip.report", "فتح بلاغ دعم") + "\n"
        "<code>/language</code> — " + tt(lang, "admin.cmds.tip.language", "اختيار اللغة") + "\n"
        "<code>/setlang</code> — " + tt(lang, "admin.cmds.tip.setlang", "تغيير اللغة") + "\n"
        "<code>/apply_supplier</code> — " + tt(lang, "admin.cmds.tip.apply_supplier", "طلب أن تصبح مورّدًا") + "\n"
    )
    try:
        await cb.message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass
    await cb.answer("✅")

@router.callback_query(F.data.startswith("ahc:send:/"))
async def ahc_send_one(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    cmd = cb.data.removeprefix("ahc:send:").strip()
    lang = get_user_lang(cb.from_user.id) or "en"

    if cmd.startswith("/admins_panel"):
        try:
            await cb.message.answer(
                adm_panel_text(lang),
                reply_markup=adm_kb_main(lang),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass
        return await cb.answer("✅")

    try:
        await cb.message.answer(cmd)
    except Exception:
        pass
    await cb.answer("✅")

# ---- روابط الأقسام الأخرى
@router.callback_query(F.data == "ah:resapps")
async def ah_resapps(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from handlers.reseller_apply import _render_list_message
        await _render_list_message(cb.message, lang, "pending", 1)
    except Exception:
        await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    else:
        await cb.answer()

@router.callback_query(F.data == "ah:supdir")
async def ah_supdir(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from handlers.supplier_directory import _render_admin_list
        await _render_admin_list(cb.message, lang, "pending", 1)
    except Exception:
        await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    else:
        await cb.answer()

# ---- لوحة التطبيق (أزرار)
@router.callback_query(F.data == "ah:app")
async def open_app_panel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    ver_val = None
    ver_txt = ""
    if app_load_release:
        try:
            rel = app_load_release()
            ver_val = (rel or {}).get("version")
            if ver_val and ver_val != "-":
                ver_txt = f" ({ver_val})"
        except Exception:
            ver_val = None
            ver_txt = ""

    kb = InlineKeyboardBuilder()
    kb.button(text="📤 " + tt(lang, "admin.app.btn_upload", "رفع"), callback_data="adm:app_upload")
    kb.button(text="📥 " + tt(lang, "admin.app.btn_send", "إرسال") + ver_txt, callback_data="adm:app_send")
    kb.button(text="ℹ️ " + tt(lang, "admin.app.btn_info", "معلومات"),   callback_data="adm:app_info")
    kb.button(text="🗑️ " + tt(lang, "admin.app.btn_remove", "حذف"), callback_data="adm:app_remove")
    kb.adjust(2)

    title = tt(lang, "admin.app.title", "إدارة التطبيق") + (f" — {ver_val}" if ver_val else "")
    await cb.message.edit_text(title, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "adm:app_upload")
async def app_upload(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    await state.set_state(AppUpload.wait_apk)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer(tt(lang, "admin.app.help", "أرسل ملف APK كـ Document وسيتم حفظه."))
    await cb.answer()

@router.callback_query(F.data == "adm:app_help")
async def app_help(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    await state.set_state(AppUpload.wait_apk)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer(tt(lang, "admin.app.help", "أرسل ملف APK كـ Document وسيتم حفظه."))
    await cb.answer()

@router.message(AppUpload.wait_apk, F.document)
async def app_on_apk(msg: Message, state: FSMContext):
    doc = msg.document
    name = (doc.file_name or "").lower()
    mime = (doc.mime_type or "").lower()

    if not name.endswith(".apk") and mime not in APK_MIME:
        await msg.answer("❌ أرسل ملف APK (امتداده .apk) كـ Document.")
        return

    try:
        prev = app_load_release() or {}
    except Exception:
        prev = {}
    version = _extract_ver(doc.file_name or "") or (prev.get("version") or "")

    meta = {
        "file_id": doc.file_id,
        "file_unique_id": doc.file_unique_id,
        "file_name": doc.file_name or "app.apk",
        "size": doc.file_size or 0,
        "version": version or "-",
        "updated_ts": int(time.time()),
    }

    _save(APP_META, meta)
    try:
        if meta["version"] and meta["version"] != "-":
            VERSION_FILE.write_text(meta["version"], encoding="utf-8")
    except Exception:
        pass

    await state.clear()
    await msg.answer(
        "✅ تم تحديث ملف التطبيق بنجاح.\n"
        f"الاسم: <code>{meta['file_name']}</code>\n"
        f"الإصدار: <b>{meta['version']}</b>\n"
        "يمكن للمستخدمين التحميل الآن.",
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "adm:app_send")
async def app_send(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_caption:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "لا يوجد إصدار"), show_alert=True)
        return
    await cb.message.answer_document(document=rel["file_id"], caption=app_caption(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "adm:app_info")
async def app_info(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_info_text:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "لا يوجد إصدار"), show_alert=True)
        return
    await cb.message.answer(app_info_text(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "adm:app_remove")
async def app_remove(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    kb = InlineKeyboardBuilder()
    kb.button(text=tt(lang, "app.remove_confirm_yes", "نعم"), callback_data="app:rm_yes")
    kb.button(text=tt(lang, "app.remove_confirm_no", "لا"),  callback_data="app:rm_no")
    kb.adjust(2)
    await cb.message.answer(tt(lang, "app.remove_confirm", "تأكيد الحذف؟"), reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "app:rm_yes")
async def app_rm_yes(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    try:
        if APP_META.exists(): APP_META.unlink()
    except Exception:
        pass
    try:
        if VERSION_FILE.exists(): VERSION_FILE.unlink()
    except Exception:
        pass
    await cb.answer("🗑️ تم حذف الإصدار.", show_alert=True)

@router.callback_query(F.data == "app:rm_no")
async def app_rm_no(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    await cb.answer("❎ تم الإلغاء.")

# ---- عدد المستخدمين
@router.callback_query(F.data == "ah:users_count")
async def ah_users_count(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    n = get_users_count()
    try:
        txt = f"👥 {t(lang, 'admin.users_count').format(n=n)}"
    except Exception:
        txt = f"👥 Total users: {n}"
    await cb.message.answer(txt)
    await cb.answer("✅")

# ---- VIP Shortcut
@router.message(Command("vipadm", "admin_vip"))
async def cmd_vipadm(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 " + tt(lang, "admin_hub_btn_vip_admin", "إدارة VIP"),
                              callback_data="vipadm:menu")],
        [InlineKeyboardButton(text=tt(lang, "admin.back", "رجوع"), callback_data="ah:menu")]
    ])
    await msg.reply(tt(lang, "admin.vipadm.open", "افتح لوحة إدارة VIP:"), reply_markup=kb)

# ---- الجوائز + الإشعارات + التقارير (مختصر)
@router.callback_query(F.data == "ah:rewards")
async def ah_rewards(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    st = _rwd_stats() or {}
    text = (
        "🏆 <b>" + tt(lang, "admin_hub_rewards_title", "إدارة الجوائز") + "</b>\n" +
        tt(lang, "admin_hub_rewards_desc", "لوحة تحكم كاملة لمنح/خصم/حظر/تصفير ومراجعة السجل.") + "\n" +
        f"• {tt(lang,'rwdadm.stats.users','المستخدمون')}: <b>{st.get('users',0)}</b>\n" +
        f"• {tt(lang,'rwdadm.stats.total','إجمالي النقاط')}: <b>{st.get('total_points',0)}</b>\n" +
        f"• {tt(lang,'rwdadm.stats.banned','محظورون')}: <b>{st.get('banned',0)}</b>"
    )
    try:
        await cb.message.edit_text(
            text,
            reply_markup=_kb_rewards_admin(lang, cb.from_user.id),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

def _kb_rewards_admin(lang: str, me_uid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 " + tt(lang, "rwdadm.open_my_panel", "فتح لوحتي"), callback_data=f"rwdadm:panel:{me_uid}")
    kb.button(text="📋 " + tt(lang, "rwdadm.users_list", "قائمة المستخدمين"), callback_data="rwdadm:list:p:0")
    kb.button(text="🚫 " + tt(lang, "rwdadm.blocked.title", "قائمة المحظورين"), callback_data="ah:rwd:blocked")
    kb.button(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:menu")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

@router.callback_query(F.data == "ah:alerts")
async def ah_alerts(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "🔔 " + tt(lang, "admin_hub_alerts_title", "إدارة الإشعارات")
    desc  = tt(lang, "admin_hub_alerts_desc", "تحكم كامل: تعديل/معاينة/إرسال/جدولة/إلغاء/إعدادات.")
    try:
        await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                                   reply_markup=_kb_alerts(lang),
                                   disable_web_page_preview=True,
                                   parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

@router.callback_query(F.data == "ah:reports")
async def ah_reports(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    open_n, closed_n, blocked_n = _rin_counts()
    text = (
        f"📮 <b>{tt(lang,'admin_hub_reports_title','التقارير')}</b>\n"
        f"{tt(lang,'admin_hub_reports_desc','إدارة البلاغات وخيوط الدعم:')}\n"
        f"• {tt(lang,'admin_hub_reports_open','مفتوحة')}: <b>{open_n}</b>\n"
        f"• {tt(lang,'admin_hub_reports_closed','مغلقة')}: <b>{closed_n}</b>\n"
        f"• {tt(lang,'admin_hub_reports_blocked','محظورون')}: <b>{blocked_n}</b>"
    )
    try:
        await cb.message.edit_text(text, reply_markup=_kb_reports(lang), parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

@router.callback_query(F.data == "ah:rstats")
async def ah_reports_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    open_n, closed_n, blocked_n = _rin_counts()
    txt = (
        f"📊 <b>{tt(lang,'admin_hub_reports_stats','إحصاءات التقارير')}</b>\n"
        f"• {tt(lang,'admin_hub_reports_open','مفتوحة')}: <code>{open_n}</code>\n"
        f"• {tt(lang,'admin_hub_reports_closed','مغلقة')}: <code>{closed_n}</code>\n"
        f"• {tt(lang,'admin_hub_reports_blocked','محظورون')}: <code>{blocked_n}</code>\n"
        f"{tt(lang,'admin_hub_reports_hint','استخدم الأزرار للتنقّل بين الوارد/الإعدادات/المحظورين.')}"
    )
    await cb.message.answer(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer("✅")

@router.callback_query(F.data == "ah:rshort")
async def ah_reports_shortcuts(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        "🛠️ <b>" + tt(lang, "admin_hub_reports_shortcuts", "اختصارات التقارير") + "</b>\n"
        "<code>/report</code> — " + tt(lang, "admin.cmds.tip.report", "فتح بلاغ دعم") + "\n"
        "<code>/rinfo &lt;uid&gt;</code> — معلومات المستخدم/الحظر/الجلسة\n"
        "<code>/rban &lt;uid&gt; &lt;hours|perm&gt;</code> — حظر مؤقّت/دائم\n"
        "<code>/runban &lt;uid&gt;</code> — رفع الحظر\n"
        "— — —\n"
        "<b>تنبيهات البلاغات (للمشرف الحالي فقط):</b>\n"
        "<code>/alerts_off</code> — إيقاف وصول إشعارات البلاغات إلى حسابك الإداري.\n"
        "<code>/alerts_on</code>  — تشغيل واستعادة وصول إشعارات البلاغات إلى حسابك."
    )
    await cb.message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer("✅")

@router.callback_query(F.data == "ah:close")
async def ah_close(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(tt(lang, "admin_closed", "تم الإغلاق"))
    await cb.answer()

@router.callback_query(F.data == "ah:noop")
async def ah_noop(cb: CallbackQuery):
    await cb.answer()

# ===================== تقارير المتجر (ملخص/مستخدم/CSV) =====================

class ShopRptStates(StatesGroup):
    wait_user = State()
    wait_user_del = State()

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _period_range(code: str) -> tuple[datetime | None, datetime | None, str]:
    code = (code or "").lower()
    now = _now_utc()
    if code == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0); end = start + timedelta(days=1); return start, end, "اليوم"
    if code == "yday":
        end = now.replace(hour=0, minute=0, second=0, microsecond=0); start = end - timedelta(days=1); return start, end, "أمس"
    if code == "d7":
        return now - timedelta(days=7), now, "آخر 7 أيام"
    if code == "d30":
        return now - timedelta(days=30), now, "آخر 30 يومًا"
    if code == "mtd":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0); return start, now, "منذ بداية الشهر"
    if code == "ytd":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0); return start, now, "منذ بداية السنة"
    return None, None, "كل الوقت"

def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None

def _fmt_money(v) -> str:
    try: return f"{float(v):.2f}"
    except Exception: return "0.00"

async def _orders_fetch(*, start: datetime | None, end: datetime | None,
                        product: str | None = None,
                        user_key: str | None = None) -> list[dict]:
    if not DB_PATH:
        return []

    sql = "SELECT * FROM orders WHERE 1=1"
    params: list = []
    if start:
        sql += " AND datetime(created_at) >= datetime(?)"; params.append(_iso(start))
    if end:
        sql += " AND datetime(created_at) <  datetime(?)"; params.append(_iso(end))
    if product and product != "-":
        sql += " AND slug = ?"; params.append(product)
    if user_key:
        key = user_key.strip().lower().lstrip("@")
        if key.isdigit():
            sql += " AND user_id = ?"; params.append(int(key))
        else:
            sql += " AND lower(username) = ?"; params.append(key)
    sql += " ORDER BY id DESC"

    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        cur  = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]

def _summary_from_rows(rows: list[dict]) -> dict:
    s = {"count": len(rows), "usd": 0.0, "by_asset": {}, "by_status": {}, "by_product": {}}
    for r in rows:
        s["usd"] += float(r.get("usd_amount") or 0)
        asset = (r.get("asset") or "").upper()
        s["by_asset"][asset] = s["by_asset"].get(asset, 0.0) + float(r.get("ton_amount") or 0)
        st = (r.get("status") or "").lower()
        s["by_status"][st] = s["by_status"].get(st, 0) + 1
        pr = (r.get("slug") or r.get("product") or "").lower()
        s["by_product"][pr] = s["by_product"].get(pr, 0) + 1
    return s

def _selected_product_from_kb(message) -> str | None:
    try:
        for row in message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.text and btn.text.startswith("✅"):
                    return btn.text.replace("✅", "").strip()
    except Exception:
        pass
    return None

def _kb_shop_reports(lang: str, product: str | None = None) -> InlineKeyboardMarkup:
    prods = _list_known_products()
    product = product or "-"
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(text="📅 اليوم",   callback_data="shopr:p:today"),
        InlineKeyboardButton(text="📅 أمس",     callback_data="shopr:p:yday"),
        InlineKeyboardButton(text="⏳ 7d",      callback_data="shopr:p:d7"),
        InlineKeyboardButton(text="⏳ 30d",     callback_data="shopr:p:d30"),
    )
    kb.row(
        InlineKeyboardButton(text="🗓 MTD",     callback_data="shopr:p:mtd"),
        InlineKeyboardButton(text="🗓 YTD",     callback_data="shopr:p:ytd"),
        InlineKeyboardButton(text="∞ الكل",    callback_data="shopr:p:all"),
    )

    row = []
    for p in prods[:4]:
        mark = "✅ " if p == product else ""
        row.append(InlineKeyboardButton(text=f"{mark}{p}", callback_data=f"shopr:prod:{p}"))
    if row: kb.row(*row)

    kb.row(InlineKeyboardButton(text="🧍 تقارير مستخدم", callback_data="shopr:byuser"))
    kb.row(
        InlineKeyboardButton(text="⬇️ CSV 7d",  callback_data=f"shopr:csv:d7-{product or '-'}"),
        InlineKeyboardButton(text="⬇️ CSV 30d", callback_data=f"shopr:csv:d30-{product or '-'}"),
    )
    kb.row(
        InlineKeyboardButton(text="🗑 حذف تقارير لمستخدم", callback_data="shopr:deluser"),
        InlineKeyboardButton(text="🧨 مسح التقارير (حسب الاختيار)", callback_data="shopr:delall"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:shop"))
    return kb.as_markup()

@router.callback_query(F.data == "ah:shop:rpt")
async def shop_reports_home(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    txt = "📊 <b>" + tt(lang, "shop.reports.title", "تقارير المتجر") + "</b>\n" + \
          tt(lang, "shop.reports.pick", "اختر الفترة والمنتج لعرض الملخص، أو استخدم (تقارير مستخدم).")
    await cb.message.edit_text(txt, reply_markup=_kb_shop_reports(lang), parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("shopr:prod:"))
async def shop_reports_set_product(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    prod = cb.data.split(":", 2)[-1]
    txt = tt(lang, "shop.reports.product_set", "تم اختيار المنتج: ") + f"<b>{prod}</b>"
    await cb.message.edit_text(txt, reply_markup=_kb_shop_reports(lang, prod), parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("shopr:p:"))
async def shop_reports_period(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    prod = _selected_product_from_kb(cb.message) or "-"
    code = cb.data.split(":")[-1]
    start, end, label = _period_range(code)
    rows = await _orders_fetch(start=start, end=end, product=prod if prod != "-" else None)

    s = _summary_from_rows(rows)
    status_emo = {"pending":"🟡","paid":"🟠","delivered":"🟢","cancelled":"⚫","expired":"⚫"}

    lines = []
    lines.append(f"📊 <b>ملخص {label}</b> — المنتج: <b>{'الكل' if prod=='-' else prod}</b>")
    lines.append(f"• العمليات: <b>{s['count']}</b>")
    lines.append(f"• إجمالي USD: <b>{_fmt_money(s['usd'])}</b>")
    if s["by_asset"]:
        parts = [f"{k}: {_fmt_money(v)}" for k, v in s["by_asset"].items()]
        lines.append("• حسب الأصل: " + " | ".join(parts))
    if s["by_status"]:
        parts = [f"{status_emo.get(k,'•')} {k}: {v}" for k, v in s["by_status"].items()]
        lines.append("• حسب الحالة: " + " | ".join(parts))

    lines.append("\n<b>أحدث 10 عمليات:</b>")
    for r in rows[:10]:
        uname = ("@" + r["username"]) if r.get("username") else "-"
        created = r.get("created_at") or "-"
        lines.append(
            f"#{r['id']} • {r.get('slug','-')}/{r.get('days','-')}d x{r.get('qty','-')} • "
            f"USD { _fmt_money(r.get('usd_amount')) } • {(r.get('asset') or '').upper()} { _fmt_money(r.get('ton_amount')) } • "
            f"{r.get('status','-')} • {created} • {uname} (id:{r.get('user_id','-')})"
        )

    txt = "\n".join(lines)
    await cb.message.edit_text(txt, reply_markup=_kb_shop_reports(lang, prod), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ---------- تقارير حسب المستخدم ----------
@router.callback_query(F.data == "shopr:byuser")
async def shop_reports_byuser(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(ShopRptStates.wait_user)
    await cb.message.answer(tt(lang, "rpt.ask_user", "أرسل الآن معرّف المستخدم (ID) أو اسم المستخدم @username."))
    await cb.answer()

@router.message(ShopRptStates.wait_user)
async def shop_reports_user_query(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    key = (msg.text or "").strip()
    await state.clear()
    rows = await _orders_fetch(start=None, end=None, user_key=key)

    if not rows:
        return await msg.answer(tt(lang, "rpt.user_not_found","لم يتم العثور على المستخدم أو لا توجد عمليات."))

    totals = _summary_from_rows(rows)
    status_emo = {"pending":"🟡","paid":"🟠","delivered":"🟢","cancelled":"⚫","expired":"⚫"}

    lines = [f"👤 <b>ID/✱</b>: <code>{key}</code>  |  {tt(lang,'rpt.count','العمليات')}: <b>{len(rows)}</b>"]
    lines.append(f"💵 {tt(lang,'rpt.usd_total','إجمالي USD')}: <b>{_fmt_money(totals.get('usd',0))}</b>")
    lines.append("— — —")
    for r in rows[:25]:
        emo = status_emo.get(str(r.get('status') or "").lower(), "•")
        lines.append(
            f"{emo} #{r['id']} | {r.get('slug','-')}/{r.get('days','-')}d×{r.get('qty','-')} | "
            f"USD { _fmt_money(r.get('usd_amount')) } | {(r.get('asset') or '').upper()} { _fmt_money(r.get('ton_amount')) } | "
            f"{r.get('status','-')} | {r.get('created_at','-')} | @{r.get('username') or '-'}"
        )
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ---------- حذف تقارير مستخدم ----------
@router.callback_query(F.data == "shopr:deluser")
async def shop_reports_deluser(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(ShopRptStates.wait_user_del)
    await cb.message.answer(tt(lang, "rpt.deluser.ask", "أرسل ID المستخدم أو @username لحذف جميع تقاريره (سيُطلب تأكيد)."))
    await cb.answer()

@router.message(ShopRptStates.wait_user_del)
async def shop_reports_deluser_confirm(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    key_raw = (msg.text or "").strip()
    await state.clear()

    if not key_raw:
        return await msg.answer(tt(lang, "rpt.input_empty", "النص فارغ."))

    key = key_raw.lstrip("@").lower()
    kind = "uid" if key.isdigit() else "uname"

    where = "user_id = ?" if kind == "uid" else "lower(username) = ?"
    param = int(key) if kind == "uid" else key
    n = 0
    if DB_PATH:
        async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
            cur = await db.execute(f"SELECT COUNT(*) FROM orders WHERE {where}", (param,))
            row = await cur.fetchone()
            n = int(row[0] if row else 0)

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ تأكيد الحذف", callback_data=f"shopr:deluser:go:{kind}:{key}"),
        InlineKeyboardButton(text="❎ إلغاء",       callback_data="shopr:deluser:cancel"),
    )
    await msg.answer(
        tt(lang, "rpt.deluser.confirm", "سيتم حذف {n} سجل(ات) لهذا المستخدم. تأكيد؟").format(n=n),
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "shopr:deluser:cancel")
async def shop_reports_deluser_cancel(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "cancelled", "أُلغيت"), show_alert=True)

@router.callback_query(F.data.startswith("shopr:deluser:go:"))
async def shop_reports_deluser_go(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    parts = cb.data.split(":")
    kind, val = parts[-2], parts[-1]
    where = "user_id = ?" if kind == "uid" else "lower(username) = ?"
    param = int(val) if kind == "uid" else val

    if not DB_PATH:
        return await cb.answer(tt(lang, "rpt.no_db", "قاعدة البيانات غير مهيّأة."), show_alert=True)

    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        cur = await db.execute(f"DELETE FROM orders WHERE {where}", (param,))
        await db.commit()
        deleted = max(cur.rowcount or 0, 0)

    await cb.answer(tt(lang, "rpt.del_done", "تم حذف {n} سجل.").format(n=deleted), show_alert=True)

# ---------- مسح كل التقارير ----------
@router.callback_query(F.data == "shopr:delall")
async def shop_reports_delall(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    prod = _selected_product_from_kb(cb.message)
    scope_txt = "الكل" if not prod else f"المنتج: {prod}"

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🧨 نعم، حذف", callback_data=f"shopr:delall:go:{prod or '-'}"),
        InlineKeyboardButton(text="❎ إلغاء",     callback_data="shopr:delall:cancel"),
    )
    await cb.message.answer(
        tt(lang, "rpt.delall.ask", "تأكيد مسح التقارير ({scope})؟ لا يمكن التراجع.").format(scope=scope_txt),
        reply_markup=kb.as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "shopr:delall:cancel")
async def shop_reports_delall_cancel(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "cancelled", "أُلغيت"), show_alert=True)

@router.callback_query(F.data.startswith("shopr:delall:go:"))
async def shop_reports_delall_go(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    prod = cb.data.split(":")[-1]
    product = None if prod in ("-", "", "None") else prod

    if not DB_PATH:
        return await cb.answer(tt(lang, "rpt.no_db", "قاعدة البيانات غير مهيّأة."), show_alert=True)

    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        if product:
            cur = await db.execute("DELETE FROM orders WHERE slug = ?", (product,))
        else:
            cur = await db.execute("DELETE FROM orders")
        await db.commit()
        deleted = max(cur.rowcount or 0, 0)

    scope_txt = "الكل" if not product else f"المنتج: {product}"
    await cb.answer(tt(lang, "rpt.delall.done", "حُذف {n} سجل ({scope}).").format(n=deleted, scope=scope_txt), show_alert=True)

# ---------- تصدير CSV ----------
@router.callback_query(F.data.startswith("shopr:csv:"))
async def shop_reports_csv(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)

    _, _, payload = cb.data.partition("shopr:csv:")
    period, _, prod = payload.partition("-")
    product = None if prod in ("", "-") else prod

    start, end, label = _period_range(period)
    rows = await _orders_fetch(start=start, end=end, product=product)

    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(["id","user_id","username","slug","days","qty","usd_amount","ton_amount","asset","to_address","status","lang","created_at","expires_at","invoice_hash","delivered_text"])
    for r in rows:
        w.writerow([
            r.get("id"), r.get("user_id"), r.get("username"), r.get("slug"), r.get("days"),
            r.get("qty"), r.get("usd_amount"), r.get("ton_amount"), r.get("asset"), r.get("to_address"),
            r.get("status"), r.get("lang"), r.get("created_at"), r.get("expires_at"), r.get("invoice_hash"),
            (r.get("delivered_text") or "").replace("\n"," ").replace("\r"," "),
        ])
    data = sio.getvalue().encode("utf-8-sig")
    fname = f"orders_{period}_{product or 'all'}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    await cb.message.answer_document(BufferedInputFile(data, filename=fname),
                                     caption=f"CSV — {label} • المنتج: {product or 'الكل'} • السجلات: {len(rows)}")
    await cb.answer("✅")
