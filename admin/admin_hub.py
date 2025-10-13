from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# admin/admin_hub.py


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

# Ø£Ø¯ÙˆØ§Ø± Ø§Ù„Ø£Ø¯Ù…Ù† (Ø§Ø³ØªØ®Ø¯Ù… Ø§Ù„Ù†Ø³Ø®Ø© Ø§Ù„Ù…ÙˆØÙ‘Ø¯Ø© Ù…Ù† utils.admin_roles ÙÙ‚Ø·)
from utils.admin_roles import (
    ROLES_FILE as ADMIN_ROLES_FILE,
    ROLES as _ADM_ROLES,
    load_roles as _admacc_load,
    save_roles as _admacc_save,
    role_label as _admacc_role_label,
    fmt_ids as _admacc_fmt_ids,
    parse_ids as _admacc_parse_ids,
)

# Ù…ØªØ¬Ø± Ø§Ù„Ù…ÙØ§ØªÙŠØ (Ø§Ø®ØªÙŠØ§Ø±ÙŠ)
try:
    from services import inventory as _shop_inv
except Exception:
    _shop_inv = None

try:
    from services import orders as _shop_ords
except Exception:
    _shop_ords = None

router = Router(name="admin_hub")

# ===================== Ø£Ø¯ÙˆØ§Øª Ø¹Ø§Ù…Ø© =====================
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

# ===================== Ù…Ø³Ø§Ø±Ø§Øª Ù…Ù„ÙØ§Øª Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©/Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ± =====================
DATA = BASE
LIVE_CONFIG       = DATA / "live_config.json"
SESSIONS_FILE     = DATA / "live_sessions.json"
BLOCKLIST_FILE    = DATA / "live_blocklist.json"
ADMIN_SEEN_FILE   = DATA / "admin_last_seen.json"
ADMIN_ONLINE_TTL  = int(os.getenv("ADMIN_ONLINE_TTL", "600"))

# â€œØ§Ù„ØªÙ‚Ø§Ø±ÙŠØ±â€
RIN_THREADS_FILE        = DATA / "support_threads.json"
REPORT_BLOCKLIST_FILE   = DATA / "report_blocklist.json"
REPORT_SETTINGS_FILE    = DATA / "report_settings.json"

# ===== Ù…ÙØ§ØªÙŠØ: ØªØ´ØºÙŠÙ„/Ø¥ÙŠÙ‚Ø§Ù Ù…ØªØ¬Ø± Ø§Ù„Ù…ÙØ§ØªÙŠØ =====
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

# ===== Ø¯Ø¹Ù… Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ØÙŠØ© =====
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

# ====== Ø¹Ø¯Ù‘Ø§Ø¯Ø§Øª Ø§Ù„ÙˆØ§Ø±Ø¯ Ù„Ù„ØªÙ‚Ø§Ø±ÙŠØ± ======
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
        blocked += len([x for x in banned if str(x).isdigit()])
    except Exception:
        pass

    return open_n, closed_n, blocked

# ===================== Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ (APK) =====================
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

APP_META = BASE / "app_latest.json"     # ÙŠÙ‚Ø±Ø¤Ù‡ handlers.app_download
VERSION_FILE = BASE / "VERSION"
APK_MIME = {"application/vnd.android.package-archive", "application/octet-stream"}

class AppUpload(StatesGroup):
    wait_apk = State()

# ðŸ‘‡ Ø§Ù†Ù‚Ù„ Ù‡Ø°Ø§ Ø§Ù„ØªØ¹Ø±ÙŠÙ Ø¥Ù„Ù‰ Ù‡Ù†Ø§ (ÙˆÙ‚Ù… Ø¨ØØ°Ù Ø§Ù„Ù†Ø³Ø®Ø© Ø§Ù„Ù…ÙˆØ¬ÙˆØ¯Ø© Ø£Ø³ÙÙ„ Ø§Ù„Ù…Ù„Ù)
class LiveQuickStates(StatesGroup):
    wait_unban_uid = State()
    wait_ban_uid   = State()

def _extract_ver(name: str) -> str | None:
    m = re.search(r"(\d+(?:\.\d+){1,3})", name or "")
    return m.group(1) if m else None

# ===================== Ø¹Ø¯Ø¯ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ† =====================
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

# ===================== Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø³Ù„Ø§Ø´ Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠØ© =====================
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

# ===================== Ø¬ÙˆØ§Ø¦Ø²: Ø¥ØØµØ§Ø¡Ø§Øª Ø³Ø±ÙŠØ¹Ø© =====================
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

# ===================== Ù„ÙˆØØ§Øª =====================
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

    suppliers_reqs    = "ðŸ“‚ " + tt(lang, "admin_hub_btn_resapps", "Ø·Ù„Ø¨Ø§Øª Ø§Ù„Ù…ÙˆØ±Ø¯ÙŠÙ†")
    suppliers_dir     = "ðŸ“– " + tt(lang, "admin_hub_btn_supdir", "Ø¯Ù„ÙŠÙ„ Ø§Ù„Ù…ÙˆØ±Ø¯ÙŠÙ†")
    app_txt           = "ðŸ“¦ " + tt(lang, "admin_hub_btn_app", "Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ (APK)") + ver
    security_txt      = "ðŸ›¡ï¸ " + tt(lang, "admin_hub_btn_security", "Ø§Ù„Ø£Ù…Ù† (Ø§Ù„Ø£Ù„Ø¹Ø§Ø¨) â€¢ Ø£Ø¯Ù…Ù†")
    reports_hub       = "ðŸ“® " + tt(lang, "admin_hub_btn_reports_hub", "Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ±") + inbox_badge
    servers_inbox     = "ðŸ“¡ " + tt(lang, "admin_hub_btn_server", "Ø§Ù„Ø³ÙŠØ±ÙØ±Ø§Øª â€” Ø§Ù„ÙˆØ§Ø±Ø¯")
    alerts_txt        = "ðŸ”” " + tt(lang, "admin_hub_btn_alerts", "Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª")
    users_count       = "ðŸ‘¥ " + tt(lang, "admin_hub_btn_users_count", "Ø¹Ø¯Ø¯ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ†")
    promoters_txt     = "ðŸ“£ " + tt(lang, "admin_hub_btn_promoters", "ØªØÙƒÙ… Ø§Ù„Ù…Ø±ÙˆÙ‘Ø¬ÙŠÙ†")
    maint_text        = "ðŸ› ï¸ " + tt(lang, "admin_hub_btn_maintenance", "ÙˆØ¶Ø¹ Ø§Ù„ØµÙŠØ§Ù†Ø©")
    live_text         = "ðŸ’¬ " + tt(lang, "admin.live.btn.panel", "Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ØÙŠÙ‘Ø©")
    bot_cmds_txt      = "ðŸ§¹ " + tt(lang, "admin_hub_btn_botcmds", "Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø¨ÙˆØª")
    vip_admin_txt     = "ðŸ‘‘ " + tt(lang, "admin_hub_btn_vip_admin", "إدارة VIP")
    rewards_admin_txt = "ðŸ† " + tt(lang, "admin_hub_btn_rewards_admin", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¬ÙˆØ§Ø¦Ø²")
    shop_admin_txt    = "ðŸ›ï¸ " + tt(lang, "admin_hub_btn_shop", "Ù…ØªØ¬Ø± Ø§Ù„Ù…ÙØ§ØªÙŠØ")
    admin_access_txt  = "ðŸ‘¥ " + tt(lang, "admin_hub_btn_admin_access", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø£Ø¯Ù…Ù†")
    features_txt      = "ðŸ§° " + tt(lang, "admin_hub_btn_features", "Ø§Ù„ØªØ¨ÙˆÙŠØ¨Ø§Øª/Ø§Ù„ØµÙŠØ§Ù†Ø©")
    promo_panel_txt   = "ðŸŽ›ï¸ " + tt(lang, "admin_hub_btn_promo_panel", "Ù„ÙˆØØ© SEVIP")  # â—€ï¸Ž Ø²Ø± Ø¬Ø¯ÙŠØ¯
    close_txt         = "âŒ " + tt(lang, "admin_hub_btn_close", "Ø¥ØºÙ„Ø§Ù‚")

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
    # Ø²Ø± Ù„ÙˆØØ© SEVIP (Ø¥Ø¯Ø§Ø±Ø© Ù†Ø¸Ø§Ù… Ø§Ù„Ù…Ø±ÙˆÙ‘Ø¬ÙŠÙ†/Ø§Ù„ØØ¸Ø±/Ø§Ù„ØªØ¬Ù…ÙŠØ¯ â€¦)
    kb.row(InlineKeyboardButton(text=promo_panel_txt, callback_data="ah:promo"))  # â—€ï¸Ž Ù‡Ù†Ø§

    # Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø£Ø¯Ù…Ù† + Ø§Ù„ØªØ¨ÙˆÙŠØ¨Ø§Øª
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

# === Ù‚Ø§Ø¦Ù…Ø© ÙØ±Ø¹ÙŠØ© Ù„Ù„ØªÙ‚Ø§Ø±ÙŠØ± ===
def _kb_reports(lang: str) -> InlineKeyboardMarkup:
    open_n, closed_n, blocked_n = _rin_counts()
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"ðŸ“¥ {tt(lang,'admin_hub_btn_reports_inbox','Ø§Ù„ÙˆØ§Ø±Ø¯')} ({open_n})", callback_data="rin:open"),
        InlineKeyboardButton(text=f"âš™ï¸ {tt(lang,'admin_hub_btn_reports_settings','Ø§Ù„Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª')}",       callback_data="ra:open"),
    )
    kb.row(
        InlineKeyboardButton(text=f"ðŸš« {tt(lang,'admin_hub_btn_reports_banned','Ø§Ù„Ù…ØØ¸ÙˆØ±ÙŠÙ†')} ({blocked_n})", callback_data="ra:banned"),
        InlineKeyboardButton(text=f"ðŸ“Š {tt(lang,'admin_hub_btn_reports_stats','Ø¥ØØµØ§Ø¡Ø§Øª')}",              callback_data="ah:rstats"),
    )
    kb.row(InlineKeyboardButton(text="ðŸ› ï¸ " + tt(lang,"admin_hub_btn_reports_shortcuts","اختصارات"), callback_data="ah:rshort"))
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang,"admin.back","Ø±Ø¬ÙˆØ¹"), callback_data="ah:menu"))
    return kb.as_markup()

# === Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª ===
def _kb_alerts(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=tt(lang, "alerts.menu.edit", "âœï¸ ØªØ¹Ø¯ÙŠÙ„ Ø§Ù„Ù†Øµ"),        callback_data="al:edit")
    kb.button(text=tt(lang, "alerts.menu.preview", "ðŸ‘€ Ù…Ø¹Ø§ÙŠÙ†Ø©"),          callback_data="al:prev")
    kb.button(text=tt(lang, "alerts.menu.send_now", "ðŸ“¢ Ø¥Ø±Ø³Ø§Ù„ Ø§Ù„Ø¢Ù†"),     callback_data="al:send")
    kb.button(text=tt(lang, "alerts.menu.schedule", "ðŸ•’ Ø¬Ø¯ÙˆÙ„Ø©"),          callback_data="al:sch")
    kb.button(text=tt(lang, "alerts.menu.quick", "â± Ø¬Ø¯ÙˆÙ„Ø© Ø³Ø±ÙŠØ¹Ø©"),       callback_data="al:schq")
    kb.button(text=tt(lang, "alerts.menu.jobs", "ðŸ—“ Ø§Ù„Ø¬ÙˆØ¨Ø² Ø§Ù„Ù…Ø¬Ø¯ÙˆÙ„Ø©"),    callback_data="al:jobs")
    kb.button(text=tt(lang, "alerts.menu.kind", "ðŸ—‚ Ø§Ù„Ù†ÙˆØ¹"),              callback_data="al:kind")
    kb.button(text=tt(lang, "alerts.menu.lang", "ðŸŒ ÙˆØ¶Ø¹ Ø§Ù„Ù„ØºØ©"),          callback_data="al:lang")
    kb.button(text=tt(lang, "alerts.menu.settings", "âš™ï¸ Ø§Ù„Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª"),      callback_data="al:cfg")
    kb.button(text=tt(lang, "alerts.menu.delete", "ðŸ—‘ï¸ ØØ°Ù Ø§Ù„Ù…Ø³ÙˆØ¯Ø©"),     callback_data="al:del")
    kb.button(text=tt(lang, "alerts.menu.stats", "ðŸ“Š Ø¥ØØµØ§Ø¦ÙŠØ§Øª"),          callback_data="al:stats")
    kb.button(text=tt(lang, "alerts.menu.list", "ðŸ—’ï¸ Ù‚Ø§Ø¦Ù…Ø©"), callback_data="al:list")

    kb.button(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"),               callback_data="ah:menu")
    kb.adjust(2,2,2,2,2,1)
    return kb.as_markup()

async def _safe_edit_text(message, text: str, **kwargs):
    """
    ÙŠØØ§ÙˆÙ„ edit_textØŒ ÙˆØ¥Ù† ØªØ¹Ø°Ù‘Ø± (Ø±Ø³Ø§Ù„Ø© Ù‚Ø¯ÙŠÙ…Ø©/ØªÙ… ØØ°ÙÙ‡Ø§/Ù„ÙŠØ³ Ù‡Ù†Ø§Ùƒ ØªØºÙŠÙŠØ±) ÙŠØ±Ø³Ù„ Ø±Ø³Ø§Ù„Ø© Ø¬Ø¯ÙŠØ¯Ø©.
    """
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        try:
            await message.answer(text, **kwargs)
        except Exception:
            pass

# ======== ØØ°Ù Ø°ÙƒÙŠ Ù„Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª (Ù‚Ø§Ø¦Ù…Ø© ÙˆØ§Ø®ØªÙŠØ§Ø±) ========
ALERTS_BLACKLIST_FILE = DATA / "alerts_blacklist.json"

def _alerts_bl_load() -> set[str]:
    try:
        if ALERTS_BLACKLIST_FILE.exists():
            return set(json.loads(ALERTS_BLACKLIST_FILE.read_text("utf-8")) or [])
    except Exception:
        pass
    return set()

def _alerts_bl_save(s: set[str]) -> None:
    try:
        ALERTS_BLACKLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ALERTS_BLACKLIST_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(list(s)), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ALERTS_BLACKLIST_FILE)
    except Exception:
        pass

def _alerts_bl_add(alert_id: str) -> None:
    s = _alerts_bl_load(); s.add(str(alert_id)); _alerts_bl_save(s)

def _alerts_bl_remove(alert_id: str) -> None:
    s = _alerts_bl_load(); 
    if str(alert_id) in s:
        s.remove(str(alert_id))
        _alerts_bl_save(s)

def _kb_alerts_list(lang: str, items: list[dict], page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    start = page * per_page
    slice_ = items[start:start+per_page]

    if not slice_:
        kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back","Ø±Ø¬ÙˆØ¹"), callback_data="ah:alerts"))
        return kb.as_markup()

    for it in slice_:
        _id = str(it.get("id") or "")
        _k  = str(it.get("kind") or "alert")
        preview = (it.get("text") or "").replace("\n", " ")
        if len(preview) > 42:
            preview = preview[:42] + "â€¦"
        # Ø¹Ù…ÙˆØ¯Ø§Ù†: Ù†Øµ Ù‚ØµÙŠØ± + Ø²Ø± ØØ°Ù
        kb.row(
            InlineKeyboardButton(text=f"ðŸ”” {_k} Â· {_id[:6]} â€¢ {preview}", callback_data="ah:noop"),
            InlineKeyboardButton(text="ðŸ—‘ï¸ " + tt(lang,"alerts.btn.delete_one","حذف"), callback_data=f"al:blk:{_id}:{page}")
        )

    # ØªÙ†Ù‚Ù‘Ù„
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="â¬…ï¸", callback_data=f"al:list:{page-1}"))
    if start + per_page < len(items):
        nav.append(InlineKeyboardButton(text="âž¡ï¸", callback_data=f"al:list:{page+1}"))
    if nav:
        kb.row(*nav)

    # Ø³Ø·Ø± Ø£Ø¯ÙˆØ§Øª Ø¥Ø¶Ø§ÙÙŠØ©
    kb.row(
        InlineKeyboardButton(text="ðŸ—ƒ " + tt(lang,"alerts.btn.trash","Ø§Ù„Ù…ØØ°ÙˆÙØ§Øª"), callback_data="al:trash:0"),
        InlineKeyboardButton(text="â¬…ï¸ " + tt(lang,"admin.back","Ø±Ø¬ÙˆØ¹"), callback_data="ah:alerts")
    )
    return kb.as_markup()

def _kb_alerts_trash(lang: str, bl_ids: list[str], page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    start = page * per_page
    slice_ = bl_ids[start:start+per_page]
    if not slice_:
        kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang,"admin.back","Ø±Ø¬ÙˆØ¹"), callback_data="al:list:0"))
        return kb.as_markup()
    for aid in slice_:
        kb.row(
            InlineKeyboardButton(text=f"ðŸ—‘ï¸ {aid}", callback_data="ah:noop"),
            InlineKeyboardButton(text="â™»ï¸ " + tt(lang,"alerts.btn.restore","استرجاع"), callback_data=f"al:unblk:{aid}:{page}")
        )
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="â¬…ï¸", callback_data=f"al:trash:{page-1}"))
    if start + per_page < len(bl_ids):
        nav.append(InlineKeyboardButton(text="âž¡ï¸", callback_data=f"al:trash:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang,"admin.back","Ø±Ø¬ÙˆØ¹"), callback_data="al:list:0"))
    return kb.as_markup()

# Ù…Ø³Ø§Ø±Ø§Øª Ù…Ø³ØªØ®Ø¯Ù…Ø© Ù„ØµÙ†Ø§Ø¯ÙŠÙ‚ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ† (Ù†ÙØ³ Ø§Ù„Ù„ÙŠ ÙŠØ³ØªØ¹Ù…Ù„Ù‡Ø§ home_hero)
BASE = BASE  # Ù…ØªÙˆÙÙ‘Ø± Ù…Ø³Ø¨Ù‚Ø§Ù‹ ÙÙŠ Ø§Ù„Ù…Ù„Ù
DATA_DIR = BASE
USERBOX_FILE = DATA_DIR / "alerts_userbox.json"

# Ù†ØØ§ÙˆÙ„ Ø§Ø³ØªØ®Ø¯Ø§Ù… utils.alerts_broadcast Ø¥Ù† ÙˆØ¬Ø¯ØŒ ÙˆØ¥Ù„Ø§ Ù†Ø±Ø¬Ø¹ Ù„Ù…Ù„Ù Ù…ØÙ„ÙŠ
try:
    from utils.alerts_broadcast import list_all_alerts as _ab_list_all   # ÙŠØ¹ÙŠØ¯ [{id, lang, kind, text, ...}]
except Exception:
    _ab_list_all = None

try:
    from utils.alerts_broadcast import delete_alert as _ab_delete         # delete_alert(alert_id) -> bool
except Exception:
    _ab_delete = None

# ÙÙˆÙ„Ø¨Ø§Ùƒ Ù…ØÙ„ÙŠ Ø¨Ø³ÙŠØ·: Ù†Ø®Ø²Ù‘Ù† ÙÙŠ BASE/alerts_store.json Ø¨Ù†ÙØ³ Ø§Ù„Ø¨Ù†ÙŠØ© Ø§Ù„Ø¹Ø§Ù…Ø©
ALERTS_STORE = BASE / "alerts_store.json"

def _alerts__load_store() -> dict:
    try:
        if ALERTS_STORE.exists():
            return json.loads(ALERTS_STORE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    # Ø¨Ù†ÙŠØ© Ø§ÙØªØ±Ø§Ø¶ÙŠØ©
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
    """
    ÙŠØ±Ø¬Ø¹ Ø¬Ù…ÙŠØ¹ Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª Ø§Ù„ÙØ¹Ù‘Ø§Ù„Ø©.
    ÙŠÙØ¶Ù‘Ù„ Ø¯ÙˆØ§Ù„ utils.alerts_broadcast Ø¥Ù† ÙˆØ¬Ø¯ØªØ› ÙÙˆÙ„Ø¨Ø§Ùƒ Ù„Ù…Ù„Ù Ù…ØÙ„ÙŠ.
    """
    if _ab_list_all:
        try:
            lst = _ab_list_all() or []
            # Ø¶Ù…Ø§Ù† ØªØ±ØªÙŠØ¨ Ø£ØØ¯Ø« Ø£ÙˆÙ„Ø§Ù‹
            return sorted(lst, key=lambda x: x.get("created_ts", 0), reverse=True)
        except Exception:
            pass
    d = _alerts__load_store()
    lst = d.get("alerts") or []
    return sorted(lst, key=lambda x: x.get("created_ts", 0), reverse=True)

def _alerts_delete_one(alert_id: str) -> bool:
    """
    ÙŠØØ°Ù Ø§Ù„Ø¥Ø´Ø¹Ø§Ø± Ù…Ù† Ø§Ù„Ù…ØµØ¯Ø± ÙˆÙŠØ²ÙŠÙ„Ù‡ Ù…Ù† ØµÙ†Ø§Ø¯ÙŠÙ‚ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ†.
    """
    ok = False
    # 1) Ø§Ù„Ù…ØµØ¯Ø± Ø§Ù„Ø£Ø³Ø§Ø³ÙŠ
    if _ab_delete:
        try:
            ok = bool(_ab_delete(alert_id))
        except Exception:
            ok = False
    if not ok:
        # ÙÙˆÙ„Ø¨Ø§Ùƒ: ØØ°Ù Ù…Ù† Ø§Ù„Ù…Ù„Ù Ø§Ù„Ù…ØÙ„ÙŠ
        d = _alerts__load_store()
        before = len(d.get("alerts") or [])
        d["alerts"] = [a for a in (d.get("alerts") or []) if str(a.get("id")) != str(alert_id)]
        _alerts__save_store(d)
        ok = len(d.get("alerts") or []) < before

    # 2) ØªÙ†Ø¸ÙŠÙ ØµÙ†Ø§Ø¯ÙŠÙ‚ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ† ØØªÙ‰ ÙŠØ®ØªÙÙŠ ÙÙˆØ±Ø§Ù‹ Ù…Ù† Ø§Ù„Ø¬Ù…ÙŠØ¹
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
    # Ø¹Ù†ØµØ± Ù„ÙƒÙ„ Ø¥Ø´Ø¹Ø§Ø±: [ðŸ“ Ù…Ø¹Ø§ÙŠÙ†Ø©] [ðŸ—‘ ØØ°Ù]
    for a in chunk:
        a_id = str(a.get("id") or "")
        kind = (a.get("kind") or "alert").lower()
        alang = (a.get("lang") or "all").upper()
        title = (a.get("title") or "").strip()
        label = title if title else (a.get("text") or "").strip()[:28].replace("\n", " ")
        label = label if label else a_id
        left = f"{alang} â€¢ {kind} â€¢ {label}"

        kb.row(
            InlineKeyboardButton(text=f"ðŸ‘ {left}", callback_data=f"al:prev:{a_id}"),
            InlineKeyboardButton(text="ðŸ—‘ ØØ°Ù",     callback_data=f"al:del:{a_id}"),
        )

    # ØªÙ†Ù‚Ù‘Ù„
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="â¬…ï¸", callback_data=f"al:list:{page-1}"))
    if start + per < len(alerts):
        nav.append(InlineKeyboardButton(text="âž¡ï¸", callback_data=f"al:list:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:alerts"))
    return kb.as_markup()

@router.callback_query(F.data == "al:list")
async def al_list_open(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alerts = _alerts_list_all()
    total = len(alerts)
    head = "ðŸ—’ï¸ " + tt(lang, "alerts.list.title", "Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª") + f" â€” {total}"
    text = f"<b>{head}</b>\n" + tt(lang, "alerts.list.tip", "Ø§Ø®ØªØ± Ù…Ø¹Ø§ÙŠÙ†Ø© Ø£Ùˆ ØØ°Ù Ù„Ø¥Ø´Ø¹Ø§Ø± Ù…ØØ¯Ù‘Ø¯.")
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
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    page = int(cb.data.split(":")[-1])
    alerts = _alerts_list_all()
    total = len(alerts)
    head = "ðŸ—’ï¸ " + tt(lang, "alerts.list.title", "Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª") + f" â€” {total}"
    text = f"<b>{head}</b>\n" + tt(lang, "alerts.list.tip", "Ø§Ø®ØªØ± Ù…Ø¹Ø§ÙŠÙ†Ø© Ø£Ùˆ ØØ°Ù Ù„Ø¥Ø´Ø¹Ø§Ø± Ù…ØØ¯Ù‘Ø¯.")
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
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alert_id = cb.data.split(":")[-1]
    a = next((x for x in _alerts_list_all() if str(x.get("id")) == str(alert_id)), None)
    if not a:
        return await cb.answer(tt(lang, "alerts.not_found", "Ø§Ù„Ø¥Ø´Ø¹Ø§Ø± ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯"), show_alert=True)

    alang = (a.get("lang") or "all").upper()
    kind  = (a.get("kind") or "alert").lower()
    title = (a.get("title") or "").strip()
    body  = (a.get("text") or "").strip()
    meta  = f"{alang} â€¢ {kind} â€¢ id:{alert_id}"

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="ðŸ—‘ ØØ°Ù", callback_data=f"al:del:{alert_id}"))
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="al:list"))
    txt = f"ðŸ”” <b>{title or '(no title)'}</b>\n<code>{meta}</code>\n\n{body}"
    await cb.message.answer(txt, reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()

@router.callback_query(F.data.startswith("al:del:"))
async def al_delete_confirm(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alert_id = cb.data.split(":")[-1]
    # ØªØ£ÙƒÙŠØ¯
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="âœ… " + tt(lang,"confirm","ØªØ£ÙƒÙŠØ¯"), callback_data=f"al:delok:{alert_id}"),
        InlineKeyboardButton(text="âŽ " + tt(lang,"cancelled","Ø¥Ù„ØºØ§Ø¡"), callback_data="al:list"),
    )
    await cb.message.answer(
        tt(lang, "alerts.delete.ask", "Ù‡Ù„ ØªØ±ÙŠØ¯ ØØ°Ù Ù‡Ø°Ø§ Ø§Ù„Ø¥Ø´Ø¹Ø§Ø± Ø¨Ø§Ù„ØªØ£ÙƒÙŠØ¯ØŸ"),
        reply_markup=kb.as_markup()
    )
    await cb.answer()

@router.callback_query(F.data.startswith("al:delok:"))
async def al_delete_do(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    alert_id = cb.data.split(":")[-1]

    ok = _alerts_delete_one(alert_id)
    if not ok:
        return await cb.answer(tt(lang, "alerts.delete.fail", "ØªØ¹Ø°Ø± ØØ°Ù Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±."), show_alert=True)

    # Ø¨Ø¹Ø¯ Ø§Ù„ØØ°Ù: Ù†Ø¹ÙŠØ¯ ÙØªØ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ù…ØØ¯Ø«Ø©
    alerts = _alerts_list_all()
    total = len(alerts)
    head = "ðŸ—’ï¸ " + tt(lang, "alerts.list.title", "Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª") + f" â€” {total}"
    text = f"<b>{head}</b>\n" + tt(lang, "alerts.delete.done", "âœ… ØªÙ… Ø§Ù„ØØ°Ù. Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ù…ØØ¯Ø«Ø©.")
    try:
        await cb.message.edit_text(text, reply_markup=_kb_alerts_list(lang, 0), parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=_kb_alerts_list(lang, 0), parse_mode=ParseMode.HTML)
    await cb.answer("âœ…")

@router.callback_query(F.data == "al:list")
@router.callback_query(F.data.regexp(r"^al:list:(\d+)$"))
async def alerts_list(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    page = 0
    if ":" in cb.data:
        try: page = int(cb.data.split(":")[-1])
        except Exception: page = 0

    # Ù†Ø¬Ù„Ø¨ Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª Ø§Ù„ÙØ¹Ù‘Ø§Ù„Ø© (Ù…Ù† Ø§Ù„Ù…ÙˆØ¯ÙŠÙˆÙ„ Ø§Ù„ØØ§Ù„ÙŠ)
    try:
        from utils.alerts_broadcast import get_active_alerts
        items = get_active_alerts(lang) or []
    except Exception:
        items = []

    # Ø§Ø³ØªØ¨Ø¹Ø¯ Ø§Ù„Ù…ØØ°ÙˆÙØ© (blacklist) ÙƒÙŠ Ù…Ø§ ØªØ¸Ù‡Ø± Ù‡Ù†Ø§ØŸ 
    # Ù†Ø¹Ø±Ø¶Ù‡Ø§ Ù‡Ù†Ø§ Ù„Ø£Ù†Ùƒ ØªØ±ÙŠØ¯ ØØ°Ù Ù…Ù† "Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„ØØ§Ù„ÙŠØ©"
    # Ù„Ø°Ù„Ùƒ Ø³Ù†Ø¹Ø±Ø¶ ÙƒÙ„ Ø§Ù„Ù…ØªØ§Ø Ù…Ù† Ø§Ù„Ù…ØµØ¯Ø± Ø«Ù… Ù†ØØ°Ù Ø¹Ù†Ø¯ Ø§Ù„Ø¶ØºØ·.
    title = "ðŸ”” " + tt(lang,"alerts.list.title","Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª (Ø§Ø®ØªØ± Ù…Ø§ ØªØ±ÙŠØ¯ ØØ°ÙÙ‡)")

    try:
        await cb.message.edit_text(
            title,
            reply_markup=_kb_alerts_list(lang, items, page),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:blk:(.+):(\d+)$"))
async def alerts_delete_one(cb: CallbackQuery):
    """Ø¥Ø¶Ø§ÙØ© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø± Ø¥Ù„Ù‰ blacklist (Ø¥Ø®ÙØ§Ø¤Ù‡ Ø¹Ù† Ø§Ù„Ø¬Ù…ÙŠØ¹)."""
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    parts = cb.data.split(":")
    alert_id = parts[2]; page = int(parts[3])
    _alerts_bl_add(alert_id)
    await cb.answer(tt(lang,"alerts.deleted_ok","ØªÙ… ØØ°Ù Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±"), show_alert=False)
    # Ø£Ø¹Ø¯ ÙØªØ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø©
    await alerts_list(cb=cb.__class__(**cb.model_dump()))  # hack: recall handler with same cb
    # Ù…Ù„Ø§ØØ¸Ø©: Ø¨Ø¹Ø¶ Ø¥ØµØ¯Ø§Ø±Ø§Øª aiogram Ù„Ø§ ØªØ³Ù…Ø Ø¨Ø§Ø³ØªØ¯Ø¹Ø§Ø¡ handler Ù…Ø¨Ø§Ø´Ø±Ø©Ø›
    # Ø¥Ù† Ù„Ù… ØªØ¹Ù…Ù„ Ù„Ø¯ÙŠÙƒ Ø§Ø³ØªØ¨Ø¯Ù„ Ø§Ù„Ø³Ø·Ø± Ø§Ù„Ø³Ø§Ø¨Ù‚ Ø¨Ù€:
    # return await alerts_list.__wrapped__(cb)

@router.callback_query(F.data.regexp(r"^al:trash:(\d+)$"))
async def alerts_trash(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    page = int(cb.data.split(":")[-1])
    bl = sorted(list(_alerts_bl_load()))
    title = "ðŸ—ƒ " + tt(lang,"alerts.trash.title","Ø§Ù„Ù…ØØ°ÙˆÙØ§Øª (ÙŠÙ…ÙƒÙ† Ø§Ø³ØªØ±Ø¬Ø§Ø¹Ù‡Ø§)")
    try:
        await cb.message.edit_text(
            title,
            reply_markup=_kb_alerts_trash(lang, bl, page),
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:unblk:(.+):(\d+)$"))
async def alerts_unblock(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    parts = cb.data.split(":")
    aid = parts[2]; page = int(parts[3])
    _alerts_bl_remove(aid)
    await cb.answer(tt(lang,"alerts.restored_ok","ØªÙ… Ø§Ù„Ø§Ø³ØªØ±Ø¬Ø§Ø¹"), show_alert=False)
    # Ø£Ø¹ÙØ¯ ÙØªØ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…ØØ°ÙˆÙØ§Øª
    await alerts_trash(cb=cb.__class__(**cb.model_dump()))

# ============== Ø§Ù„Ù…ØªØ¬Ø±: Ø§Ù„Ù‚ÙˆØ§Ø¦Ù… =========================
def _kb_shop_main(lang: str) -> InlineKeyboardMarkup:
    on = _keys_enabled()
    toggle_txt = ("ðŸ”´ " + tt(lang, "admin.shop.btn.enable", "ØªØ´ØºÙŠÙ„ Ø§Ù„Ø®Ø¯Ù…Ø©")) if not on else ("ðŸ›‘ " + tt(lang, "admin.shop.btn.disable", "Ø¥ÙŠÙ‚Ø§Ù Ø§Ù„Ø®Ø¯Ù…Ø©"))
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="ðŸ§¾ " + tt(lang, "admin.shop.btn.orders",   "Ø§Ù„Ø·Ù„Ø¨Ø§Øª"),   callback_data="ah:shop:orders"),
        InlineKeyboardButton(text="ðŸ“¦ " + tt(lang, "admin.shop.btn.inventory","Ø§Ù„Ù…Ø®Ø²ÙˆÙ†"),   callback_data="ah:shop:inv"),
    )
    kb.row(InlineKeyboardButton(text="ðŸ“Š " + tt(lang, "admin.shop.btn.reports","Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ±"),  callback_data="ah:shop:rpt"))
    kb.row(InlineKeyboardButton(text="ðŸ§° " + tt(lang, "admin.shop.btn.advanced","Ù„ÙˆØØ© Ø§Ù„Ù…ØªØ¬Ø± Ø§Ù„Ù…ØªÙ‚Ø¯Ù‘Ù…Ø©"), callback_data="sad:inv"))
    kb.row(InlineKeyboardButton(text=toggle_txt, callback_data="ah:shop:toggle"))
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:menu"))
    return kb.as_markup()

def _kb_shop_inv(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="ðŸ“Š /inv_stats",   callback_data="ahc:send:/inv_stats"),
        InlineKeyboardButton(text="â¬‡ï¸ /inv_dump 3",  callback_data="ahc:send:/inv_dump 3"),
    )
    kb.row(
        InlineKeyboardButton(text="â¬‡ï¸ /inv_dump 10", callback_data="ahc:send:/inv_dump 10"),
        InlineKeyboardButton(text="â¬‡ï¸ /inv_dump 30", callback_data="ahc:send:/inv_dump 30"),
    )
    kb.row(
        InlineKeyboardButton(text="âž• /inv_add 3",   callback_data="ahc:send:/inv_add 3"),
        InlineKeyboardButton(text="âž• /inv_add 10",  callback_data="ahc:send:/inv_add 10"),
        InlineKeyboardButton(text="âž• /inv_add 30",  callback_data="ahc:send:/inv_add 30"),
    )
    kb.row(
        InlineKeyboardButton(text="ðŸ—‘ï¸ /inv_del 3",  callback_data="ahc:send:/inv_del 3"),
        InlineKeyboardButton(text="ðŸ—‘ï¸ /inv_del 10", callback_data="ahc:send:/inv_del 10"),
        InlineKeyboardButton(text="ðŸ—‘ï¸ /inv_del 30", callback_data="ahc:send:/inv_del 30"),
    )
    kb.row(
        InlineKeyboardButton(text="ðŸ§¨ /inv_clear 3",  callback_data="ahc:send:/inv_clear 3"),
        InlineKeyboardButton(text="ðŸ§¨ /inv_clear 10", callback_data="ahc:send:/inv_clear 10"),
        InlineKeyboardButton(text="ðŸ§¨ /inv_clear 30", callback_data="ahc:send:/inv_clear 30"),
    )
    kb.row(InlineKeyboardButton(text="ðŸ” " + tt(lang, "shopadm.btn.scan", "ÙØØµ Ù†Ù‚Øµ Ø§Ù„Ù…Ø®Ø²ÙˆÙ†"), callback_data="shop:scan"))
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:shop"))
    return kb.as_markup()

def _kb_shop_orders(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="ðŸ“‹ /orders_all",     callback_data="ahc:send:/orders_all"),
        InlineKeyboardButton(text="â„¹ï¸ /order_info 123", callback_data="ahc:send:/order_info 123"),
    )
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:shop"))
    return kb.as_markup()

# ---------- NEW (Ù…ÙˆØÙ‘Ø¯): Ø¬Ù…Ø¹ Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª Ø§Ù„Ù…Ø¹Ø±ÙˆÙØ© Ù„Ù„ÙØØµ/Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ± ----------
def _list_known_products() -> list[str]:
    """
    ÙŠØ¹ÙŠØ¯ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª Ø§Ù„Ù…Ø¹Ø±ÙˆÙØ© Ù…Ù†:
      - SHOP_PRODUCTS, PRODUCT_KEY (Ø¨ÙŠØ¦Ø©)
      - Ø£Ø³Ù…Ø§Ø¡ Ø§Ù„Ù…Ø¬Ù„Ø¯Ø§Øª Ø¯Ø§Ø®Ù„ BASE/inventory
    """
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

# ===================== ÙˆØ§Ø¬Ù‡Ø§Øª ÙˆØªØÙƒÙ… Ø¹Ø§Ù…Ø© =====================
@router.message(Command("admin"))
async def admin_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù† âš¡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    await msg.answer(f"<b>{title}</b>\n{desc}",
                     reply_markup=_kb_main(lang),
                     disable_web_page_preview=True,
                     parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "ah:menu")
async def ah_menu(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù† âš¡")
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
    """ÙŠÙØªØ Ù„ÙˆØØ© Ø¥Ø¯Ø§Ø±Ø© SEVIP (Promo Panel) Ø¹Ù†Ø¯ Ø§Ù„Ø¶ØºØ· Ø¹Ù„Ù‰ Ø²Ø± Ù„ÙˆØØ© SEVIP ÙÙŠ Ø§Ù„Ù‡ÙŽØ¨."""
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    text = "ðŸ› ï¸ " + tt(lang, "promo.panel.title", "Ù„ÙˆØØ© Ø¥Ø¯Ø§Ø±Ø© SEVIP") + " â€” " + tt(lang, "promo.panel.pick", "Ø§Ø®ØªØ± ÙÙ„ØªØ±Ù‹Ø§:")

    try:
        await cb.message.edit_text(
            text,
            reply_markup=promo_kb_panel_home(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except TelegramBadRequest:
        # Ø¥Ø°Ø§ ØªØ¹Ø°Ø± Ø§Ù„ØªØ¹Ø¯ÙŠÙ„ (Ø±Ø³Ø§Ù„Ø© Ù‚Ø¯ÙŠÙ…Ø©/ØªÙ… ØØ°ÙÙ‡Ø§)ØŒ Ø£Ø±Ø³Ù„ Ø±Ø³Ø§Ù„Ø© Ø¬Ø¯ÙŠØ¯Ø©
        await cb.message.answer(
            text,
            reply_markup=promo_kb_panel_home(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    await cb.answer()

# ---- Ø§Ù„Ù…ØªØ¬Ø±: Ø§Ù„Ø´Ø§Ø´Ø© Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ©
@router.callback_query(F.data == "ah:shop")
async def ah_shop(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

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

    status_txt = "ðŸŸ¢ " + tt(lang, "admin.shop.on", "Ø§Ù„Ø®Ø¯Ù…Ø© Ù…ÙØ¹Ù‘Ù„Ø©") if _keys_enabled() else "ðŸ”´ " + tt(lang, "admin.shop.off", "Ø§Ù„Ø®Ø¯Ù…Ø© Ù…ØªÙˆÙ‚ÙØ©")
    stop_msg = _get_stop_msg().strip()
    stop_line = tt(lang, "admin.shop.stopmsg", "â€¢ Ø±Ø³Ø§Ù„Ø© Ø§Ù„Ø¥ÙŠÙ‚Ø§Ù Ø§Ù„Ù…Ø®ØµÙ‘ØµØ©: {v}").format(v=("âœ…" if stop_msg else "â€”"))

    text = (
        "ðŸ›ï¸ <b>" + tt(lang, "admin.shop.title", "Ù…ØªØ¬Ø± Ø§Ù„Ù…ÙØ§ØªÙŠØ") + "</b>\n"
        + status_txt + "\n"
        + stop_line + "\n"
        + tt(lang, "admin.shop.desc", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø·Ù„Ø¨Ø§Øª ÙˆØ§Ù„Ù…Ø®Ø²ÙˆÙ†.") + "\n\n"
        + tt(lang, "admin.shop.stats", "ðŸ“Š Ø¥ØØµØ§Ø¡Ø§Øª Ø³Ø±ÙŠØ¹Ø©:") + "\n"
        + tt(lang, "admin.shop.stats.orders_open", "â€¢ Ø§Ù„Ø·Ù„Ø¨Ø§Øª Ø§Ù„Ù…ÙØªÙˆØØ©: {n}").format(n=open_orders) + "\n"
        + tt(lang, "admin.shop.stats.inv", "â€¢ Ø§Ù„Ù…Ø®Ø²ÙˆÙ† â€” 3d/10d/30d: {a}/{b}/{c}").format(a=inv_c3, b=inv_c10, c=inv_c30)
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
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    _set_keys_enabled(not _keys_enabled())
    await ah_shop(cb)

@router.callback_query(F.data == "ah:shop:inv")
async def shop_inv(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from services import inventory as _inv
        c = await _inv.counts()
        c3, c10, c30 = c.get(3,0), c.get(10,0), c.get(30,0)
    except Exception:
        c3 = c10 = c30 = 0

    hint_add  = tt(lang, "admin.shop.inv.hint_add",
                   "Ù„Ø±ÙØ¹ Ù…ÙØ§ØªÙŠØ: Ø£Ø±Ø³Ù„ Ø§Ù„Ù…ÙØ§ØªÙŠØ ÙƒØ³Ø·ÙˆØ± Ø«Ù… Ø±Ø¯Ù‘ Ø¨Ø§Ù„Ø£Ù…Ø±:\n"
                   "<code>/inv_add 3|10|30</code> (Ø¯ØŒ Ø§Ù„Ø£ÙŠØ§Ù…)")
    hint_dump = tt(lang, "admin.shop.inv.hint_dump",
                   "Ù„Ù„ØªØµØ¯ÙŠØ±: <code>/inv_dump 3|10|30</code>")
    hint_del  = tt(lang, "admin.shop.inv.hint_del",
                   "Ù„ØØ°Ù Ù…ÙØ±Ø¯: Ø±Ø¯ Ø¹Ù„Ù‰ Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ø§Ù„ØªÙŠ ØªØØªÙˆÙŠ Ø§Ù„Ù…ÙØ§ØªÙŠØ Ø¨Ù€ <code>/inv_del 3|10|30</code>\n"
                   "Ù„Ù„ØØ°Ù Ø§Ù„Ø¬Ù…Ø§Ø¹ÙŠ: <code>/inv_clear 3|10|30</code>")
    stats_hdr = "ðŸ“Š " + tt(lang, "admin.shop.inv.stats_title", "Ø¥ØØµØ§Ø¡Ø§Øª Ø§Ù„Ù…Ø®Ø²ÙˆÙ†:") \
                + f"\nâ€¢ 3d: <b>{c3}</b>\nâ€¢ 10d: <b>{c10}</b>\nâ€¢ 30d: <b>{c30}</b>"

    text = "ðŸ“¦ <b>" + tt(lang, "admin.shop.inv.title", "Ø§Ù„Ù…Ø®Ø²ÙˆÙ†") + "</b>\n" \
           + hint_add + "\n" + hint_dump + "\n" + hint_del + "\n\n" + stats_hdr

    await cb.message.edit_text(text, reply_markup=_kb_shop_inv(lang), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "shop:inv")
async def shop_inv_panel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    stats = ""
    if _shop_inv:
        try:
            c = await _shop_inv.counts()
            stats = f"\n\n<b>{tt(lang,'shopadm.inv.stats','Ø¥ØØµØ§Ø¡Ø§Øª Ø§Ù„Ù…Ø®Ø²ÙˆÙ†')}</b>\nâ€¢ 3d: <code>{c.get(3,0)}</code>\nâ€¢ 10d: <code>{c.get(10,0)}</code>\nâ€¢ 30d: <code>{c.get(30,0)}</code>"
        except Exception:
            stats = ""
    help_txt = tt(
        lang, "shopadm.inv.help",
        "Ù„Ø±ÙØ¹ Ù…ÙØ§ØªÙŠØ: Ø£Ø±Ø³Ù„ Ø§Ù„Ù…ÙØ§ØªÙŠØ ÙƒØ³Ø·ÙˆØ± Ø«Ù… (Ø±Ø¯Ù‘) Ø¨Ù€ /inv_add 3|10|30\n"
        "Ù„Ù„ØªØµØ¯ÙŠØ±: /inv_dump 3|10|30\n"
        "Ù„ØØ°Ù Ù…ÙØ±Ø¯: Ø±Ø¯Ù‘ Ø¨Ù€ /inv_del 3|10|30\n"
        "Ù„Ù„ØØ°Ù Ø§Ù„Ø¬Ù…Ø§Ø¹ÙŠ: /inv_clear 3|10|30"
    )
    await cb.message.edit_text(f"ðŸ“¦ <b>{tt(lang,'shopadm.inv.title','Ø§Ù„Ù…Ø®Ø²ÙˆÙ†')}</b>\n{help_txt}{stats}",
                               reply_markup=_kb_shop_inv(lang),
                               parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "shop:scan")
async def shop_scan(cb: CallbackQuery):
    """
    ÙŠÙØØµ Ù†Ù‚Øµ Ø§Ù„Ù…Ø®Ø²ÙˆÙ† Ù„Ø¬Ù…ÙŠØ¹ Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª Ø§Ù„Ù…Ø¹Ø±ÙˆÙØ© (ÙƒÙ„ Ø§Ù„Ø£Ù„Ø¹Ø§Ø¨)ØŒ ÙˆÙ„ÙƒÙ„ Ø§Ù„Ù…Ø¯Ø¯ 3/10/30.
    ÙŠØ¹ØªÙ…Ø¯ Ø¹Ù„Ù‰ inventory.maybe_alert_low_stock Ø§Ù„ØªÙŠ ØªØ±Ø³Ù„ ØªÙ†Ø¨ÙŠÙ‡Ù‹Ø§ Ø¹Ù†Ø¯ Ø§Ù†Ø®ÙØ§Ø¶ Ø§Ù„Ù…Ø®Ø²ÙˆÙ†.
    """
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    if not _shop_inv:
        return await cb.answer(tt(lang, "shopadm.not_available", "ÙˆØØ¯Ø© Ø§Ù„Ù…ØªØ¬Ø± ØºÙŠØ± Ù…ØªØ§ØØ©"), show_alert=True)

    products = _list_known_products()
    errs = 0
    for prod in products:
        for d in (3, 10, 30):
            try:
                await _shop_inv.maybe_alert_low_stock(cb.bot, d, product=prod)
            except Exception:
                errs += 1

    summary = tt(lang, "shopadm.scan.done", "ØªÙ… ÙØØµ Ø§Ù„Ù…Ø®Ø²ÙˆÙ† Ø§Ù„ØØ§Ù„ÙŠ.")
    prod_line = " â€¢ " + ", ".join(products)
    try:
        await cb.message.answer(f"{summary}\nØ§Ù„Ù…Ù†ØªØ¬Ø§Øª:{prod_line}")
    except Exception:
        pass
    await cb.answer(tt(lang, "shopadm.scan.ok", "ØªÙ…."), show_alert=False)


# ===================== ÙˆØ§Ø¬Ù‡Ø§Øª ÙˆØªØÙƒÙ… Ø¹Ø§Ù…Ø© =====================
@router.message(Command("admin"))
async def admin_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù† âš¡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    await msg.answer(f"<b>{title}</b>\n{desc}",
                     reply_markup=_kb_main(lang),
                     disable_web_page_preview=True,
                     parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "ah:menu")
async def ah_menu(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù† âš¡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    try:
        await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                                   reply_markup=_kb_main(lang),
                                   disable_web_page_preview=True,
                                   parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

# ---- Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ØÙŠÙ‘Ø©
@router.callback_query(F.data == "ah:live")
async def ah_live(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    status = "ðŸŸ¢ " + tt(lang, "admin.live.status_on", "Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù…ÙØ¹Ù‘Ù„Ø©") if _support_enabled() else "ðŸ”´ " + tt(lang, "admin.live.status_off", "Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù…ØªÙˆÙ‚ÙØ©")
    desc = tt(lang, "admin.live.desc", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ØÙŠÙ‘Ø©:")

    # --- ØªØ°ÙƒÙŠØ± Ø¨Ø§Ù„Ø£ÙˆØ§Ù…Ø± Ù„Ù„Ø¥Ø¯Ù…Ù† ---
    cmds_text = (
        "\n\nðŸ§° Ø£ÙˆØ§Ù…Ø± Ø³Ø±ÙŠØ¹Ø©:\n"
        "<code>/live_on</code> â€” ØªÙØ¹ÙŠÙ„ ÙˆØ¶Ø¹ Ø§Ù„Ø£ÙˆÙ†Ù„Ø§ÙŠÙ† Ù„Ø§Ø³ØªÙ‚Ø¨Ø§Ù„ Ø·Ù„Ø¨Ø§Øª Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©.\n"
        "<code>/live_off</code> â€” Ø¥ÙŠÙ‚Ø§Ù ÙˆØ¶Ø¹ Ø§Ù„Ø£ÙˆÙ†Ù„Ø§ÙŠÙ† Ù„Ø¹Ø¯Ù… Ø§Ø³ØªÙ‚Ø¨Ø§Ù„ Ø§Ù„Ø·Ù„Ø¨Ø§Øª."
    )

    await cb.message.edit_text(
        f"<b>{tt(lang, 'admin.live.title', 'Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ØÙŠÙ‘Ø©')}</b>\n{status}\n{desc}{cmds_text}",
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
        status = "ðŸŸ¢ " + tt(lang, "admin.live.status_on", "Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù…ÙØ¹Ù‘Ù„Ø©") if _support_enabled() \
                 else "ðŸ”´ " + tt(lang, "admin.live.status_off", "Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù…ØªÙˆÙ‚ÙØ©")
        desc = tt(lang, "admin.live.desc", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ØÙŠÙ‘Ø©:")

        # --- ØªØ°ÙƒÙŠØ± Ø¨Ø§Ù„Ø£ÙˆØ§Ù…Ø± Ù„Ù„Ø¥Ø¯Ù…Ù† ---
        cmds_text = (
            "\n\nðŸ§° Ø£ÙˆØ§Ù…Ø± Ø³Ø±ÙŠØ¹Ø©:\n"
            "<code>/live_on</code> â€” ØªÙØ¹ÙŠÙ„ ÙˆØ¶Ø¹ Ø§Ù„Ø£ÙˆÙ†Ù„Ø§ÙŠÙ† Ù„Ø§Ø³ØªÙ‚Ø¨Ø§Ù„ Ø·Ù„Ø¨Ø§Øª Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©.\n"
            "<code>/live_off</code> â€” Ø¥ÙŠÙ‚Ø§Ù ÙˆØ¶Ø¹ Ø§Ù„Ø£ÙˆÙ†Ù„Ø§ÙŠÙ† Ù„Ø¹Ø¯Ù… Ø§Ø³ØªÙ‚Ø¨Ø§Ù„ Ø§Ù„Ø·Ù„Ø¨Ø§Øª."
        )

        await cb.message.edit_text(
            f"<b>{tt(lang, 'admin.live.title', 'Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ØÙŠÙ‘Ø©')}</b>\n{status}\n{desc}{cmds_text}",
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
    await cb.answer(tt(lang, "admin.live.avail.on.done", "ØªÙ… ØªÙØ¹ÙŠÙ„ ØªÙˆÙØ±ÙÙƒ"), show_alert=True)

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
    await cb.answer(tt(lang, "admin.live.avail.off.done", "ØªÙ… Ø¥ÙŠÙ‚Ø§Ù ØªÙˆÙØ±ÙÙƒ"), show_alert=True)

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
    await cb.answer(tt(lang, "admin.live.touched", "ØªÙ… ØªØ³Ø¬ÙŠÙ„ ØªÙˆØ§Ø¬Ø¯Ùƒ"), show_alert=True)

def _kb_live_main(lang: str, admin_id: int) -> InlineKeyboardMarkup:
    on = _support_enabled()
    me_on = _admin_is_online(admin_id)
    online_n = _online_admins_count()

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=("ðŸŸ¢ " if on else "ðŸ”´ ") + (tt(lang, "admin.live.toggle_off", "Ø¥ÙŠÙ‚Ø§Ù") if on else tt(lang, "admin.live.toggle_on", "ØªØ´ØºÙŠÙ„")),
            callback_data="liveadm:toggle"
        ),
        InlineKeyboardButton(
            text=("ðŸ›‘ " + tt(lang, "admin.live.avail.off", "Ø¥ÙŠÙ‚Ø§Ù")) if me_on else ("âœ… " + tt(lang, "admin.live.avail.on", "Ø£Ù†Ø§ Ù…ØªØ§Ø Ø§Ù„Ø¢Ù†")),
            callback_data="liveadm:avail_off" if me_on else "liveadm:avail_on"
        )
    )
    kb.row(
        InlineKeyboardButton(text="ðŸ“‹ " + tt(lang, "admin.live.list", "Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¬Ù„Ø³Ø§Øª"), callback_data="liveadm:list"),
        InlineKeyboardButton(text=f"ðŸ‘¥ {tt(lang, 'admin.live.online_count', 'Ø§Ù„Ù…ØªØµÙ„ÙˆÙ†')}: {online_n}", callback_data="ah:noop")
    )
    # Ø£Ø²Ø±Ø§Ø± Ø³Ø±ÙŠØ¹Ø© Ø¨Ø§Ù„ØØ¸Ø±/Ø±ÙØ¹ Ø§Ù„ØØ¸Ø± Ø¹Ø¨Ø± UID
    kb.row(
        InlineKeyboardButton(text="ðŸš« " + tt(lang, "admin.live.btn.block_uid", "حظر (UID)"), callback_data="liveadm:ban_open"),
        InlineKeyboardButton(text="ðŸ”“ " + tt(lang, "admin.live.btn.unban_uid", "Ø±ÙØ¹ Ø§Ù„ØØ¸Ø± (UID)"), callback_data="liveadm:unban_open"),
    )
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:menu"))
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
    wt = ", ".join(map(str, waiting[:10])) or tt(lang, "admin.live.no_items", "Ù„Ø§ ÙŠÙˆØ¬Ø¯")
    ac = ", ".join(f"{u}(a:{a})" for u, a in active[:10]) or tt(lang, "admin.live.no_items", "Ù„Ø§ ÙŠÙˆØ¬Ø¯")
    text = (
        f"ðŸ—’ï¸ <b>{tt(lang,'admin.live.list.title','Ø§Ù„Ø¬Ù„Ø³Ø§Øª Ø§Ù„ØØ§Ù„ÙŠØ©')}</b>\n"
        f"â€¢ {tt(lang,'admin.live.waiting','Ù…Ù†ØªØ¸Ø±Ø©')}: {wt}\n"
        f"â€¢ {tt(lang,'admin.live.active','Ù†Ø´ÙØ·Ø©')}: {ac}\n"
        f"{tt(lang,'admin.live.hint','ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ù„Ø§Ù†Ø¶Ù…Ø§Ù…/Ø§Ù„Ø¥Ù†Ù‡Ø§Ø¡/Ø§Ù„ØØ¸Ø± Ù…Ù† Ø§Ù„Ø£Ø²Ø±Ø§Ø± Ø¨Ø§Ù„Ø£Ø³ÙÙ„.')}"
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
        InlineKeyboardButton(text="âˆž",    callback_data=f"liveadm:ban:{uid}:perm"),
    )
    kb.row(InlineKeyboardButton(text=tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="liveadm:list"))
    return kb.as_markup()

def _kb_live_list(lang: str, waiting: list[int], active: list[tuple[int,int]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    # Ø§Ù„Ø¬Ù„Ø³Ø§Øª Ø§Ù„Ù…Ù†ØªØ¸Ø±Ø©
    for uid in waiting[:5]:
        # Ø³Ø·Ø± 1: Ø§Ù„ØØ§Ù„Ø© + Ø§Ù†Ø¶Ù…Ø§Ù…/Ø¥Ù†Ù‡Ø§Ø¡
        kb.row(
            InlineKeyboardButton(text=f"ðŸŸ¡ {uid}", callback_data="ah:noop"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.join", "Ø§Ù†Ø¶Ù…Ø§Ù…"),  callback_data=f"live:accept:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.end", "Ø¥Ù†Ù‡Ø§Ø¡"),     callback_data=f"live:decline:{uid}"),
        )
        # Ø³Ø·Ø± 2: Ø§Ù„ØØ¸Ø± ÙÙ‚Ø·
        kb.row(
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.block", "حظر"), callback_data=f"liveadm:block:{uid}")
        )

    # Ø§Ù„Ø¬Ù„Ø³Ø§Øª Ø§Ù„Ù†Ø´Ø·Ø©
    for uid, aid in active[:5]:
        # Ø³Ø·Ø± 1: Ø§Ù„ØØ§Ù„Ø© + Ø¥Ù†Ù‡Ø§Ø¡
        kb.row(
            InlineKeyboardButton(text=f"ðŸŸ¢ {uid} Â· a:{aid}", callback_data="ah:noop"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.end", "Ø¥Ù†Ù‡Ø§Ø¡"), callback_data=f"live:end:{uid}"),
        )
        # Ø³Ø·Ø± 2: ØØ¸Ø±/Ø¥Ù„ØºØ§Ø¡ ØØ¸Ø±
        kb.row(
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.block", "حظر"),          callback_data=f"liveadm:block:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.unblock", "Ø¥Ù„ØºØ§Ø¡ ØØ¸Ø±"), callback_data=f"liveadm:unblock:{uid}")
        )

    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:live"))
    return kb.as_markup()

def ttf(lang: str, key: str, fb_en: str, fb_ar: str) -> str:
    # try translation; otherwise fall back based on lang
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
    await cb.message.answer(tt(lang, "live.unban.ask", "Ø£Ø±Ø³Ù„ UID Ø§Ù„Ù…Ø±Ø§Ø¯ Ø±ÙØ¹ Ø§Ù„ØØ¸Ø± Ø¹Ù†Ù‡.\nâ€¢ Ù„Ù„Ø¥Ù„ØºØ§Ø¡: /cancel"))
    await cb.answer()

@router.message(LiveQuickStates.wait_unban_uid)
async def liveadm_unban_do(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "Ø¥Ù„ØºØ§Ø¡", "Ø§Ù„ØºØ§Ø¡"}:
        await state.clear()
        return await msg.reply(tt(lang, "cancelled", "Cancelled"))  # ÙÙˆÙ„Ø¨Ø§Ùƒ EN Ù‡Ù†Ø§

    if not raw.isdigit():
        return await msg.reply(ttf(lang, "live.unban.bad",
                                   "Send a valid UID (digits only).",
                                   "Ø£Ø±Ø³Ù„ UID ØµØÙŠØ (Ø£Ø±Ù‚Ø§Ù… ÙÙ‚Ø·)."))

    uid = int(raw)
    bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
    await state.clear()

    # Ù„ØºØ© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø°ÙŠ Ø±ÙÙØ¹ Ø¹Ù†Ù‡ Ø§Ù„ØØ¸Ø±
    tlang = get_user_lang(uid) or "en"

    # Ø¥Ø´Ø¹Ø§Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…
    try:
        txt_user = ttf(tlang, "live.unban.user_ok",
                       "âœ… Unban complete. You can try now.",
                       "âœ… ØªÙ… Ø±ÙØ¹ Ø§Ù„ØØ¸Ø±. ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ù„Ù…ØØ§ÙˆÙ„Ø© Ø§Ù„Ø¢Ù†.")
        await msg.bot.send_message(uid, txt_user)
    except Exception:
        pass

    # Ø±Ø¯Ù‘ Ø§Ù„ØªØ£ÙƒÙŠØ¯ Ù„Ù„Ø£Ø¯Ù…Ù† Ø¨Ù„ØºØ© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…
    await msg.reply(
        ttf(tlang, "live.unban.ok",
            "Unban complete for {uid}.",
            "ØªÙ… Ø±ÙØ¹ Ø§Ù„ØØ¸Ø± Ø¹Ù† {uid}.").format(uid=uid)
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
        "Ø£Ø±Ø³Ù„ Ø§Ù„Ø¢Ù†:\n<code>UID</code> Ø£Ùˆ <code>UID Ù…Ø¯Ø©_Ø³Ø§Ø¹Ø§Øª</code> (Ù…Ø«Ø§Ù„: <code>123456 24</code>)\nÙ„Ù„ØØ¸Ø± Ø¯Ø§Ø¦Ù…Ù‹Ø§ Ø§Ø³ØªØ®Ø¯Ù…: <code>perm</code>\nâ€¢ Ù„Ù„Ø¥Ù„ØºØ§Ø¡: /cancel"
    )
    await cb.message.answer(txt, parse_mode=ParseMode.HTML)
    await cb.answer()

@router.message(LiveQuickStates.wait_ban_uid)
async def liveadm_ban_do(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "").strip().lower()
    if raw in {"/cancel", "cancel", "Ø¥Ù„ØºØ§Ø¡", "Ø§Ù„ØºØ§Ø¡"}:
        await state.clear()
        return await msg.reply(tt(lang, "cancelled", "Ø£ÙÙ„ØºÙŠØª"))

    parts = raw.split()
    if not parts or not parts[0].isdigit():
        return await msg.reply(tt(lang, "live.ban.bad", "Ø§Ù„Ø±Ø¬Ø§Ø¡ Ø¥Ø¯Ø®Ø§Ù„ UID ØµØÙŠØØŒ Ù…Ø«Ù„Ø§Ù‹: <code>123456</code> Ø£Ùˆ <code>123456 24</code>"), parse_mode=ParseMode.HTML)

    uid = int(parts[0])
    dur = (parts[1] if len(parts) >= 2 else "perm").lower()
    bl = _load(BLOCKLIST_FILE)
    if dur == "perm":
        bl[str(uid)] = {"until": 0, "reason": "by_admin", "by": msg.from_user.id}
    else:
        try:
            hours = int(dur)
        except Exception:
            return await msg.reply(tt(lang, "live.ban.bad_dur", "Ù…Ø¯Ø© ØºÙŠØ± ØµØ§Ù„ØØ©. Ø§Ø³ØªØ®Ø¯Ù… Ø¹Ø¯Ø¯ Ø§Ù„Ø³Ø§Ø¹Ø§Øª Ø£Ùˆ perm."))
        bl[str(uid)] = {"until": time.time() + hours * 3600, "reason": "by_admin", "by": msg.from_user.id}
    _save(BLOCKLIST_FILE, bl)
    await state.clear()
    await msg.reply(tt(lang, "live.ban.ok", "ØªÙ… ØØ¸Ø± {uid}.").format(uid=uid))

@router.callback_query(F.data.startswith("liveadm:block:"))
async def liveadm_block(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    uid = int(cb.data.split(":")[-1])

    await cb.message.answer(
        tt(lang, "admin.live.block.pick", "Ø§Ø®ØªØ± Ù…Ø¯Ø© Ø§Ù„ØØ¸Ø± Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù…: ") + f"<code>{uid:d}</code>",
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
    await cb.answer(tt(lang, "admin.live.block.done", "ØªÙ… Ø§Ù„ØØ¸Ø±"), show_alert=True)

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
    await cb.answer(tt(lang, "admin.live.unblock.done", "ØªÙ… Ø¥Ù„ØºØ§Ø¡ Ø§Ù„ØØ¸Ø±"), show_alert=True)

# ---- Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø¨ÙˆØª
@router.callback_query(F.data == "ah:bot_cmds")
async def ah_bot_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "ðŸ§¹ " + tt(lang, "admin.botcmds.title", "Ø§Ù„ØªØÙƒÙ… Ø¨Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø¨ÙˆØª")
    desc  = tt(lang, "admin.botcmds.desc", "اختر إجراء:")
    await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                               reply_markup=_kb_bot_cmds(lang),
                               disable_web_page_preview=True,
                               parse_mode=ParseMode.HTML)
    await cb.answer()

def _kb_bot_cmds(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="ðŸ§¹ " + tt(lang, "admin.botcmds.clean_now", "ØªÙ†Ø¸ÙŠÙ ÙÙˆØ±ÙŠ"), callback_data="ah:bot_cmds:clean"),
        InlineKeyboardButton(text="â†©ï¸ " + tt(lang, "admin.botcmds.restore", "Ø§Ø³ØªØ¹Ø§Ø¯Ø© Ø§Ù„Ø£ÙˆØ§Ù…Ø±"), callback_data="ah:bot_cmds:restore"),
    )
    kb.row(InlineKeyboardButton(text="â™»ï¸ /reload_cmds", callback_data="ahc:send:/reload_cmds"))
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:menu"))
    return kb.as_markup()

@router.callback_query(F.data == "ah:bot_cmds:clean")
async def ah_bot_cmds_clean(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    await _clean_all_bot_commands(cb.bot)
    await cb.answer("ðŸ§¹ ØªÙ… ØªÙ†Ø¸ÙŠÙ Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø¨ÙˆØª Ø¨Ø§Ù„ÙƒØ§Ù…Ù„.", show_alert=True)

@router.callback_query(F.data == "ah:bot_cmds:restore")
async def ah_bot_cmds_restore(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    await _restore_default_bot_commands(cb.bot)
    await cb.answer("â†©ï¸ ØªÙ… Ø§Ø³ØªØ¹Ø§Ø¯Ø© Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø¨ÙˆØª Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠØ©.", show_alert=True)

# ---- Ø´Ø§Ø´Ø© Ø£ÙˆØ§Ù…Ø± Ù…Ø®ØªØµØ±Ø©
@router.callback_query(F.data == "ah:cmds")
async def ah_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "ðŸ”§ " + tt(lang, "admin.cmds.vip_title", "Ø£ÙˆØ§Ù…Ø± VIP")
    desc  = tt(lang, "admin.cmds.desc", "Ø§Ø®ØªØµØ§Ø±Ø§Øª Ù„Ø¥Ø±Ø³Ø§Ù„ Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø³Ù„Ø§Ø´.")
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
        InlineKeyboardButton(text="ðŸ“£ " + tt(lang, "promadm.btn.open", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ù…Ø±ÙˆÙ‘Ø¬ÙŠÙ†"), callback_data="promadm:open"),
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
    kb.row(InlineKeyboardButton(text="ðŸ“¤ " + tt(lang, "admin.cmds.btn.send_all_slash", "Ø¥Ø±Ø³Ø§Ù„ ÙƒÙ„ Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø³Ù„Ø§Ø´"), callback_data="ahc:slash_all"))
    kb.row(InlineKeyboardButton(text=tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:menu"))
    return kb.as_markup()

@router.callback_query(F.data == "ahc:slash_all")
async def ahc_slash_all(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        "ðŸ§° <b>" + tt(lang, "admin.cmds.slash_title", "Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ø³Ù„Ø§Ø´") + "</b>\n"
        "<code>/rewards_admin</code> â€” " + tt(lang, "rwdadm.cmds.rewards_admin", "Ù„ÙˆØØ© Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¬ÙˆØ§Ø¦Ø²") + "\n"
        "<code>/r_grant &lt;uid&gt; &lt;points&gt;</code> â€” " + tt(lang, "rwdadm.cmds.r_grant", "Ù…Ù†Ø/Ø®ØµÙ… Ù†Ù‚Ø§Ø·") + "\n"
        "<code>/r_setpts &lt;uid&gt; &lt;points&gt;</code> â€” " + tt(lang, "rwdadm.cmds.setpts", "ØªØ¹ÙŠÙŠÙ† Ø§Ù„Ù†Ù‚Ø§Ø·") + "\n"
        "<code>/r_setstreak &lt;uid&gt; &lt;streak&gt;</code> â€” " + tt(lang, "rwdadm.cmds.setstreak", "ØªØ¹ÙŠÙŠÙ† Ø§Ù„Ø³Ù„Ø³Ù„Ø©") + "\n"
        "<code>/r_ban &lt;uid&gt;</code> â€” " + tt(lang, "rwdadm.cmds.ban", "ØØ¸Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…") + "\n"
        "<code>/r_unban &lt;uid&gt;</code> â€” " + tt(lang, "rwdadm.cmds.unban", "Ø¥Ù„ØºØ§Ø¡ Ø§Ù„ØØ¸Ø±") + "\n"
        "<code>/r_del &lt;uid&gt;</code> â€” " + tt(lang, "rwdadm.cmds.del", "ØØ°Ù Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…") + "\n"
        "<code>/r_notify &lt;uid&gt; &lt;text&gt;</code> â€” " + tt(lang, "rwdadm.cmds.notify", "Ø¥Ø´Ø¹Ø§Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…") + "\n"
        "\n"
        "<code>/vipadm</code> â€” " + tt(lang, "admin.cmds.tip.vipadm", "Ù„ÙˆØØ© Ø¥Ø¯Ø§Ø±Ø© VIP") + "\n"
        "<code>/vip</code> â€” " + tt(lang, "admin.cmds.tip.vip", "Ù„ÙˆØØ© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… VIP") + "\n"
        "<code>/vip_status</code> â€” " + tt(lang, "admin.cmds.tip.vip_status", "ØØ§Ù„Ø© Ø§Ø´ØªØ±Ø§Ùƒ VIP") + "\n"
        "<code>/vip_track</code> â€” " + tt(lang, "admin.cmds.tip.vip_track", "ØªØªØ¨Ù‘Ø¹ Ø·Ù„Ø¨ VIP") + "\n"
        "<code>/report</code> â€” " + tt(lang, "admin.cmds.tip.report", "ÙØªØ Ø¨Ù„Ø§Øº Ø¯Ø¹Ù…") + "\n"
        "<code>/language</code> â€” " + tt(lang, "admin.cmds.tip.language", "Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ù„ØºØ©") + "\n"
        "<code>/setlang</code> â€” " + tt(lang, "admin.cmds.tip.setlang", "ØªØºÙŠÙŠØ± Ø§Ù„Ù„ØºØ©") + "\n"
        "<code>/apply_supplier</code> â€” " + tt(lang, "admin.cmds.tip.apply_supplier", "Ø·Ù„Ø¨ Ø£Ù† ØªØµØ¨Ø Ù…ÙˆØ±Ù‘Ø¯Ù‹Ø§") + "\n"
    )
    try:
        await cb.message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass
    await cb.answer("âœ…")

@router.callback_query(F.data.startswith("ahc:send:/"))
async def ahc_send_one(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    cmd = cb.data.removeprefix("ahc:send:").strip()
    lang = get_user_lang(cb.from_user.id) or "en"

    # Ø§ÙØªØ Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù† Ø§Ù„Ø¬Ø¯ÙŠØ¯Ø© Ù…Ø¨Ø§Ø´Ø±Ø©
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
        return await cb.answer("âœ…")

    # Ø§Ù„Ø³Ù„ÙˆÙƒ Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠ: Ø£Ø±Ø³Ù„Ù‡Ø§ ÙƒÙ†Øµ (Ù„Ù„ØªÙØ¹ÙŠÙ„ Ø§Ù„Ø³Ø±ÙŠØ¹)
    try:
        await cb.message.answer(cmd)
    except Exception:
        pass
    await cb.answer("âœ…")

# ---- Ø±ÙˆØ§Ø¨Ø· Ø§Ù„Ø£Ù‚Ø³Ø§Ù… Ø§Ù„Ø£Ø®Ø±Ù‰
@router.callback_query(F.data == "ah:resapps")
async def ah_resapps(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from handlers.reseller_apply import _render_list_message
        await _render_list_message(cb.message, lang, "pending", 1)
    except Exception:
        await cb.answer(tt(lang, "admin_hub_module_missing", "Ø§Ù„ÙˆØØ¯Ø© ØºÙŠØ± Ù…ØªØ§ØØ©"), show_alert=True)
    else:
        await cb.answer()

@router.callback_query(F.data == "ah:supdir")
async def ah_supdir(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from handlers.supplier_directory import _render_admin_list
        await _render_admin_list(cb.message, lang, "pending", 1)
    except Exception:
        await cb.answer(tt(lang, "admin_hub_module_missing", "Ø§Ù„ÙˆØØ¯Ø© ØºÙŠØ± Ù…ØªØ§ØØ©"), show_alert=True)
    else:
        await cb.answer()

# ---- Ù„ÙˆØØ© Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ (Ø£Ø²Ø±Ø§Ø±)
@router.callback_query(F.data == "ah:app")
async def open_app_panel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
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
    kb.button(text="ðŸ“¤ " + tt(lang, "admin.app.btn_upload", "رفع"), callback_data="adm:app_upload")
    kb.button(text="ðŸ“¥ " + tt(lang, "admin.app.btn_send", "Ø¥Ø±Ø³Ø§Ù„") + ver_txt, callback_data="adm:app_send")
    kb.button(text="â„¹ï¸ " + tt(lang, "admin.app.btn_info", "Ù…Ø¹Ù„ÙˆÙ…Ø§Øª"),   callback_data="adm:app_info")
    kb.button(text="ðŸ—‘ï¸ " + tt(lang, "admin.app.btn_remove", "حذف"), callback_data="adm:app_remove")
    kb.adjust(2)

    title = tt(lang, "admin.app.title", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„ØªØ·Ø¨ÙŠÙ‚") + (f" â€” {ver_val}" if ver_val else "")
    await cb.message.edit_text(title, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "adm:app_upload")
async def app_upload(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    await state.set_state(AppUpload.wait_apk)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer(tt(lang, "admin.app.help", "Ø£Ø±Ø³Ù„ Ù…Ù„Ù APK ÙƒÙ€ Document ÙˆØ³ÙŠØªÙ… ØÙØ¸Ù‡."))
    await cb.answer()

@router.callback_query(F.data == "adm:app_help")
async def app_help(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    await state.set_state(AppUpload.wait_apk)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer(tt(lang, "admin.app.help", "Ø£Ø±Ø³Ù„ Ù…Ù„Ù APK ÙƒÙ€ Document ÙˆØ³ÙŠØªÙ… ØÙØ¸Ù‡."))
    await cb.answer()

@router.message(AppUpload.wait_apk, F.document)
async def app_on_apk(msg: Message, state: FSMContext):
    # Ø§Ø³ØªÙ‚Ø¨Ø§Ù„ Ù…Ù„Ù APK ÙÙŠ ÙˆØ¶Ø¹ Ø§Ù„Ø±ÙØ¹
    doc = msg.document
    name = (doc.file_name or "").lower()
    mime = (doc.mime_type or "").lower()

    if not name.endswith(".apk") and mime not in APK_MIME:
        await msg.answer("âŒ Ø£Ø±Ø³Ù„ Ù…Ù„Ù APK (Ø§Ù…ØªØ¯Ø§Ø¯Ù‡ .apk) ÙƒÙ€ Document.")
        return

    # Ø§Ù„Ø¥ØµØ¯Ø§Ø±
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
        "âœ… ØªÙ… ØªØØ¯ÙŠØ« Ù…Ù„Ù Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ Ø¨Ù†Ø¬Ø§Ø.\n"
        f"Ø§Ù„Ø§Ø³Ù…: <code>{meta['file_name']}</code>\n"
        f"Ø§Ù„Ø¥ØµØ¯Ø§Ø±: <b>{meta['version']}</b>\n"
        "ÙŠÙ…ÙƒÙ† Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ† Ø§Ù„ØªØÙ…ÙŠÙ„ Ø§Ù„Ø¢Ù†.",
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "adm:app_send")
async def app_send(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_caption:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "Ø§Ù„ÙˆØØ¯Ø© ØºÙŠØ± Ù…ØªØ§ØØ©"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø¥ØµØ¯Ø§Ø±"), show_alert=True)
        return
    await cb.message.answer_document(document=rel["file_id"], caption=app_caption(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "adm:app_info")
async def app_info(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_info_text:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "Ø§Ù„ÙˆØØ¯Ø© ØºÙŠØ± Ù…ØªØ§ØØ©"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø¥ØµØ¯Ø§Ø±"), show_alert=True)
        return
    await cb.message.answer(app_info_text(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "adm:app_remove")
async def app_remove(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    kb = InlineKeyboardBuilder()
    kb.button(text=tt(lang, "app.remove_confirm_yes", "Ù†Ø¹Ù…"), callback_data="app:rm_yes")
    kb.button(text=tt(lang, "app.remove_confirm_no", "Ù„Ø§"),  callback_data="app:rm_no")
    kb.adjust(2)
    await cb.message.answer(tt(lang, "app.remove_confirm", "ØªØ£ÙƒÙŠØ¯ Ø§Ù„ØØ°ÙØŸ"), reply_markup=kb.as_markup())
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
    await cb.answer("ðŸ—‘ï¸ ØªÙ… ØØ°Ù Ø§Ù„Ø¥ØµØ¯Ø§Ø±.", show_alert=True)

@router.callback_query(F.data == "app:rm_no")
async def app_rm_no(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    await cb.answer("âŽ ØªÙ… Ø§Ù„Ø¥Ù„ØºØ§Ø¡.")

# ---- Ø¹Ø¯Ø¯ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ†
@router.callback_query(F.data == "ah:users_count")
async def ah_users_count(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    n = get_users_count()
    try:
        txt = f"ðŸ‘¥ {t(lang, 'admin.users_count').format(n=n)}"
    except Exception:
        txt = f"ðŸ‘¥ Total users: {n}"
    await cb.message.answer(txt)
    await cb.answer("âœ…")

# ---- VIP Shortcut
@router.message(Command("vipadm", "admin_vip"))
async def cmd_vipadm(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ðŸ‘‘ " + tt(lang, "admin_hub_btn_vip_admin", "إدارة VIP"),
                              callback_data="vipadm:menu")],
        [InlineKeyboardButton(text=tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:menu")]
    ])
    await msg.reply(tt(lang, "admin.vipadm.open", "Ø§ÙØªØ Ù„ÙˆØØ© Ø¥Ø¯Ø§Ø±Ø© VIP:"), reply_markup=kb)

# ---- Ø§Ù„Ø¬ÙˆØ§Ø¦Ø² + Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª + Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ± (Ù…Ø®ØªØµØ±)
@router.callback_query(F.data == "ah:rewards")
async def ah_rewards(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    st = _rwd_stats() or {}
    text = (
        "ðŸ† <b>" + tt(lang, "admin_hub_rewards_title", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¬ÙˆØ§Ø¦Ø²") + "</b>\n" +
        tt(lang, "admin_hub_rewards_desc", "Ù„ÙˆØØ© ØªØÙƒÙ… ÙƒØ§Ù…Ù„Ø© Ù„Ù…Ù†Ø/Ø®ØµÙ…/ØØ¸Ø±/ØªØµÙÙŠØ± ÙˆÙ…Ø±Ø§Ø¬Ø¹Ø© Ø§Ù„Ø³Ø¬Ù„.") + "\n" +
        f"â€¢ {tt(lang,'rwdadm.stats.users','Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙˆÙ†')}: <b>{st.get('users',0)}</b>\n" +
        f"â€¢ {tt(lang,'rwdadm.stats.total','Ø¥Ø¬Ù…Ø§Ù„ÙŠ Ø§Ù„Ù†Ù‚Ø§Ø·')}: <b>{st.get('total_points',0)}</b>\n" +
        f"â€¢ {tt(lang,'rwdadm.stats.banned','Ù…ØØ¸ÙˆØ±ÙˆÙ†')}: <b>{st.get('banned',0)}</b>"
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
    kb.button(text="ðŸ† " + tt(lang, "rwdadm.open_my_panel", "ÙØªØ Ù„ÙˆØØªÙŠ"), callback_data=f"rwdadm:panel:{me_uid}")
    kb.button(text="ðŸ“‹ " + tt(lang, "rwdadm.users_list", "Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ†"), callback_data="rwdadm:list:p:0")
    kb.button(text="ðŸš« " + tt(lang, "rwdadm.blocked.title", "Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…ØØ¸ÙˆØ±ÙŠÙ†"), callback_data="ah:rwd:blocked")
    kb.button(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:menu")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

@router.callback_query(F.data == "ah:alerts")
async def ah_alerts(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "ðŸ”” " + tt(lang, "admin_hub_alerts_title", "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª")
    desc  = tt(lang, "admin_hub_alerts_desc", "ØªØÙƒÙ… ÙƒØ§Ù…Ù„: ØªØ¹Ø¯ÙŠÙ„/Ù…Ø¹Ø§ÙŠÙ†Ø©/Ø¥Ø±Ø³Ø§Ù„/Ø¬Ø¯ÙˆÙ„Ø©/Ø¥Ù„ØºØ§Ø¡/Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª.")
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
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    open_n, closed_n, blocked_n = _rin_counts()
    text = (
        f"ðŸ“® <b>{tt(lang,'admin_hub_reports_title','Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ±')}</b>\n"
        f"{tt(lang,'admin_hub_reports_desc','Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¨Ù„Ø§ØºØ§Øª ÙˆØ®ÙŠÙˆØ· Ø§Ù„Ø¯Ø¹Ù…:')}\n"
        f"â€¢ {tt(lang,'admin_hub_reports_open','Ù…ÙØªÙˆØØ©')}: <b>{open_n}</b>\n"
        f"â€¢ {tt(lang,'admin_hub_reports_closed','Ù…ØºÙ„Ù‚Ø©')}: <b>{closed_n}</b>\n"
        f"â€¢ {tt(lang,'admin_hub_reports_blocked','Ù…ØØ¸ÙˆØ±ÙˆÙ†')}: <b>{blocked_n}</b>"
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
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    open_n, closed_n, blocked_n = _rin_counts()
    txt = (
        f"ðŸ“Š <b>{tt(lang,'admin_hub_reports_stats','Ø¥ØØµØ§Ø¡Ø§Øª Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ±')}</b>\n"
        f"â€¢ {tt(lang,'admin_hub_reports_open','Ù…ÙØªÙˆØØ©')}: <code>{open_n}</code>\n"
        f"â€¢ {tt(lang,'admin_hub_reports_closed','Ù…ØºÙ„Ù‚Ø©')}: <code>{closed_n}</code>\n"
        f"â€¢ {tt(lang,'admin_hub_reports_blocked','Ù…ØØ¸ÙˆØ±ÙˆÙ†')}: <code>{blocked_n}</code>\n"
        f"{tt(lang,'admin_hub_reports_hint','Ø§Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø£Ø²Ø±Ø§Ø± Ù„Ù„ØªÙ†Ù‚Ù‘Ù„ Ø¨ÙŠÙ† Ø§Ù„ÙˆØ§Ø±Ø¯/Ø§Ù„Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª/Ø§Ù„Ù…ØØ¸ÙˆØ±ÙŠÙ†.')}"
    )
    await cb.message.answer(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer("âœ…")

@router.callback_query(F.data == "ah:rshort")
async def ah_reports_shortcuts(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        "ðŸ› ï¸ <b>" + tt(lang, "admin_hub_reports_shortcuts", "Ø§Ø®ØªØµØ§Ø±Ø§Øª Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ±") + "</b>\n"
        "<code>/report</code> â€” " + tt(lang, "admin.cmds.tip.report", "ÙØªØ Ø¨Ù„Ø§Øº Ø¯Ø¹Ù…") + "\n"
        "<code>/rinfo &lt;uid&gt;</code> â€” Ù…Ø¹Ù„ÙˆÙ…Ø§Øª Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…/Ø§Ù„ØØ¸Ø±/Ø§Ù„Ø¬Ù„Ø³Ø©\n"
        "<code>/rban &lt;uid&gt; &lt;hours|perm&gt;</code> â€” ØØ¸Ø± Ù…Ø¤Ù‚Ù‘Øª/Ø¯Ø§Ø¦Ù…\n"
        "<code>/runban &lt;uid&gt;</code> â€” Ø±ÙØ¹ Ø§Ù„ØØ¸Ø±\n"
        "â€” â€” â€”\n"
        "<b>ØªÙ†Ø¨ÙŠÙ‡Ø§Øª Ø§Ù„Ø¨Ù„Ø§ØºØ§Øª (Ù„Ù„Ù…Ø´Ø±Ù Ø§Ù„ØØ§Ù„ÙŠ ÙÙ‚Ø·):</b>\n"
        "<code>/alerts_off</code> â€” Ø¥ÙŠÙ‚Ø§Ù ÙˆØµÙˆÙ„ Ø¥Ø´Ø¹Ø§Ø±Ø§Øª Ø§Ù„Ø¨Ù„Ø§ØºØ§Øª Ø¥Ù„Ù‰ ØØ³Ø§Ø¨Ùƒ Ø§Ù„Ø¥Ø¯Ø§Ø±ÙŠ.\n"
        "<code>/alerts_on</code>  â€” ØªØ´ØºÙŠÙ„ ÙˆØ§Ø³ØªØ¹Ø§Ø¯Ø© ÙˆØµÙˆÙ„ Ø¥Ø´Ø¹Ø§Ø±Ø§Øª Ø§Ù„Ø¨Ù„Ø§ØºØ§Øª Ø¥Ù„Ù‰ ØØ³Ø§Ø¨Ùƒ."
    )
    await cb.message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer("âœ…")


@router.callback_query(F.data == "ah:close")
async def ah_close(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l, "admins_only", "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(tt(lang, "admin_closed", "ØªÙ… Ø§Ù„Ø¥ØºÙ„Ø§Ù‚"))
    await cb.answer()

@router.callback_query(F.data == "ah:noop")
async def ah_noop(cb: CallbackQuery):
    await cb.answer()

# ===================== ØªÙ‚Ø§Ø±ÙŠØ± Ø§Ù„Ù…ØªØ¬Ø± (Ù…Ù„Ø®Øµ/Ù…Ø³ØªØ®Ø¯Ù…/CSV) =====================


# ØØ§Ù„Ø§Øª FSM
class ShopRptStates(StatesGroup):
    wait_user = State()      # Ø¹Ø±Ø¶ ØªÙ‚Ø§Ø±ÙŠØ± Ù…Ø³ØªØ®Ø¯Ù…
    wait_user_del = State()  # ØØ°Ù ØªÙ‚Ø§Ø±ÙŠØ± Ù…Ø³ØªØ®Ø¯Ù…

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _period_range(code: str) -> tuple[datetime | None, datetime | None, str]:
    """
    ÙŠÙØ¹ÙŠØ¯ (start, end, label) ØØ³Ø¨ ÙƒÙˆØ¯ Ø§Ù„ÙØªØ±Ø©:
    today, yday, d7, d30, mtd, ytd, all
    """
    code = (code or "").lower()
    now = _now_utc()
    if code == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0); end = start + timedelta(days=1); return start, end, "Ø§Ù„ÙŠÙˆÙ…"
    if code == "yday":
        end = now.replace(hour=0, minute=0, second=0, microsecond=0); start = end - timedelta(days=1); return start, end, "Ø£Ù…Ø³"
    if code == "d7":
        return now - timedelta(days=7), now, "Ø¢Ø®Ø± 7 Ø£ÙŠØ§Ù…"
    if code == "d30":
        return now - timedelta(days=30), now, "Ø¢Ø®Ø± 30 ÙŠÙˆÙ…Ù‹Ø§"
    if code == "mtd":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0); return start, now, "Ù…Ù†Ø° Ø¨Ø¯Ø§ÙŠØ© Ø§Ù„Ø´Ù‡Ø±"
    if code == "ytd":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0); return start, now, "Ù…Ù†Ø° Ø¨Ø¯Ø§ÙŠØ© Ø§Ù„Ø³Ù†Ø©"
    return None, None, "ÙƒÙ„ Ø§Ù„ÙˆÙ‚Øª"

def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None

def _fmt_money(v) -> str:
    try: return f"{float(v):.2f}"
    except Exception: return "0.00"

async def _orders_fetch(*, start: datetime | None, end: datetime | None,
                        product: str | None = None,
                        user_key: str | None = None) -> list[dict]:
    """
    ÙŠØ¬Ù„Ø¨ Ø£ÙˆØ§Ù…Ø± Ø¶Ù…Ù† ÙØªØ±Ø© Ø§Ø®ØªÙŠØ§Ø±ÙŠØ©ØŒ Ù…Ø¹ ÙÙ„ØªØ±Ø© Ø§Ø®ØªÙŠØ§Ø±ÙŠØ© Ø¨Ø§Ù„Ù…Ù†ØªØ¬ Ø£Ùˆ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… (id Ø£Ùˆ @username).
    """
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
    """ÙŠØØ§ÙˆÙ„ Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ø§Ù„Ù…Ù†ØªØ¬ Ø§Ù„Ù…Ø®ØªØ§Ø± Ù…Ù† Ø§Ù„ÙƒÙŠØ¨ÙˆØ±Ø¯ (Ø²Ø± Ø¹Ù„ÙŠÙ‡ âœ…)."""
    try:
        for row in message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.text and btn.text.startswith("âœ…"):
                    return btn.text.replace("âœ…", "").strip()
    except Exception:
        pass
    return None

def _kb_shop_reports(lang: str, product: str | None = None) -> InlineKeyboardMarkup:
    prods = _list_known_products()
    product = product or "-"
    kb = InlineKeyboardBuilder()

    # ÙØªØ±Ø§Øª Ø³Ø±ÙŠØ¹Ø©
    kb.row(
        InlineKeyboardButton(text="ðŸ“… Ø§Ù„ÙŠÙˆÙ…",   callback_data="shopr:p:today"),
        InlineKeyboardButton(text="ðŸ“… Ø£Ù…Ø³",     callback_data="shopr:p:yday"),
        InlineKeyboardButton(text="â³ 7d",      callback_data="shopr:p:d7"),
        InlineKeyboardButton(text="â³ 30d",     callback_data="shopr:p:d30"),
    )
    kb.row(
        InlineKeyboardButton(text="ðŸ—“ MTD",     callback_data="shopr:p:mtd"),
        InlineKeyboardButton(text="ðŸ—“ YTD",     callback_data="shopr:p:ytd"),
        InlineKeyboardButton(text="âˆž Ø§Ù„ÙƒÙ„",    callback_data="shopr:p:all"),
    )

    # Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ù…Ù†ØªØ¬
    row = []
    for p in prods[:4]:
        mark = "âœ… " if p == product else ""
        row.append(InlineKeyboardButton(text=f"{mark}{p}", callback_data=f"shopr:prod:{p}"))
    if row: kb.row(*row)

    # Ø£Ø¯ÙˆØ§Øª Ø¥Ø¶Ø§ÙÙŠØ©
    kb.row(InlineKeyboardButton(text="ðŸ§ ØªÙ‚Ø§Ø±ÙŠØ± Ù…Ø³ØªØ®Ø¯Ù…", callback_data="shopr:byuser"))
    kb.row(
        InlineKeyboardButton(text="â¬‡ï¸ CSV 7d",  callback_data=f"shopr:csv:d7-{product or '-'}"),
        InlineKeyboardButton(text="â¬‡ï¸ CSV 30d", callback_data=f"shopr:csv:d30-{product or '-'}"),
    )
    # Ø£Ø²Ø±Ø§Ø± Ø§Ù„ØØ°Ù
    kb.row(
        InlineKeyboardButton(text="ðŸ—‘ ØØ°Ù ØªÙ‚Ø§Ø±ÙŠØ± Ù„Ù…Ø³ØªØ®Ø¯Ù…", callback_data="shopr:deluser"),
        InlineKeyboardButton(text="ðŸ§¨ Ù…Ø³Ø Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ± (ØØ³Ø¨ Ø§Ù„Ø§Ø®ØªÙŠØ§Ø±)", callback_data="shopr:delall"),
    )
    kb.row(InlineKeyboardButton(text="â¬…ï¸ " + tt(lang, "admin.back", "Ø±Ø¬ÙˆØ¹"), callback_data="ah:shop"))
    return kb.as_markup()

@router.callback_query(F.data == "ah:shop:rpt")
async def shop_reports_home(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    txt = "ðŸ“Š <b>" + tt(lang, "shop.reports.title", "ØªÙ‚Ø§Ø±ÙŠØ± Ø§Ù„Ù…ØªØ¬Ø±") + "</b>\n" + \
          tt(lang, "shop.reports.pick", "Ø§Ø®ØªØ± Ø§Ù„ÙØªØ±Ø© ÙˆØ§Ù„Ù…Ù†ØªØ¬ Ù„Ø¹Ø±Ø¶ Ø§Ù„Ù…Ù„Ø®ØµØŒ Ø£Ùˆ Ø§Ø³ØªØ®Ø¯Ù… (ØªÙ‚Ø§Ø±ÙŠØ± Ù…Ø³ØªØ®Ø¯Ù…).")
    await cb.message.edit_text(txt, reply_markup=_kb_shop_reports(lang), parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("shopr:prod:"))
async def shop_reports_set_product(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    prod = cb.data.split(":", 2)[-1]
    txt = tt(lang, "shop.reports.product_set", "ØªÙ… Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ù…Ù†ØªØ¬: ") + f"<b>{prod}</b>"
    await cb.message.edit_text(txt, reply_markup=_kb_shop_reports(lang, prod), parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("shopr:p:"))
async def shop_reports_period(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    prod = _selected_product_from_kb(cb.message) or "-"
    code = cb.data.split(":")[-1]
    start, end, label = _period_range(code)
    rows = await _orders_fetch(start=start, end=end, product=prod if prod != "-" else None)

    s = _summary_from_rows(rows)
    status_emo = {"pending":"ðŸŸ¡","paid":"ðŸŸ ","delivered":"ðŸŸ¢","cancelled":"âš«","expired":"âš«"}

    lines = []
    lines.append(f"ðŸ“Š <b>Ù…Ù„Ø®Øµ {label}</b> â€” Ø§Ù„Ù…Ù†ØªØ¬: <b>{'Ø§Ù„ÙƒÙ„' if prod=='-' else prod}</b>")
    lines.append(f"â€¢ Ø§Ù„Ø¹Ù…Ù„ÙŠØ§Øª: <b>{s['count']}</b>")
    lines.append(f"â€¢ Ø¥Ø¬Ù…Ø§Ù„ÙŠ USD: <b>{_fmt_money(s['usd'])}</b>")
    if s["by_asset"]:
        parts = [f"{k}: {_fmt_money(v)}" for k, v in s["by_asset"].items()]
        lines.append("â€¢ ØØ³Ø¨ Ø§Ù„Ø£ØµÙ„: " + " | ".join(parts))
    if s["by_status"]:
        parts = [f"{status_emo.get(k,'â€¢')} {k}: {v}" for k, v in s["by_status"].items()]
        lines.append("â€¢ ØØ³Ø¨ Ø§Ù„ØØ§Ù„Ø©: " + " | ".join(parts))

    lines.append("\n<b>Ø£ØØ¯Ø« 10 Ø¹Ù…Ù„ÙŠØ§Øª:</b>")
    for r in rows[:10]:
        uname = ("@" + r["username"]) if r.get("username") else "-"
        created = r.get("created_at") or "-"
        lines.append(
            f"#{r['id']} â€¢ {r.get('slug','-')}/{r.get('days','-')}d x{r.get('qty','-')} â€¢ "
            f"USD { _fmt_money(r.get('usd_amount')) } â€¢ {(r.get('asset') or '').upper()} { _fmt_money(r.get('ton_amount')) } â€¢ "
            f"{r.get('status','-')} â€¢ {created} â€¢ {uname} (id:{r.get('user_id','-')})"
        )

    txt = "\n".join(lines)
    await cb.message.edit_text(txt, reply_markup=_kb_shop_reports(lang, prod), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ---------- ØªÙ‚Ø§Ø±ÙŠØ± ØØ³Ø¨ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… ----------
@router.callback_query(F.data == "shopr:byuser")
async def shop_reports_byuser(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(ShopRptStates.wait_user)
    await cb.message.answer(tt(lang, "rpt.ask_user", "Ø£Ø±Ø³Ù„ Ø§Ù„Ø¢Ù† Ù…Ø¹Ø±Ù‘Ù Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… (ID) Ø£Ùˆ Ø§Ø³Ù… Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… @username."))
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
        return await msg.answer(tt(lang, "rpt.user_not_found","Ù„Ù… ÙŠØªÙ… Ø§Ù„Ø¹Ø«ÙˆØ± Ø¹Ù„Ù‰ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø£Ùˆ Ù„Ø§ ØªÙˆØ¬Ø¯ Ø¹Ù…Ù„ÙŠØ§Øª."))

    totals = _summary_from_rows(rows)
    status_emo = {"pending":"ðŸŸ¡","paid":"ðŸŸ ","delivered":"ðŸŸ¢","cancelled":"âš«","expired":"âš«"}

    lines = [f"ðŸ‘¤ <b>ID/âœ±</b>: <code>{key}</code>  |  {tt(lang,'rpt.count','Ø§Ù„Ø¹Ù…Ù„ÙŠØ§Øª')}: <b>{len(rows)}</b>"]
    lines.append(f"ðŸ’µ {tt(lang,'rpt.usd_total','Ø¥Ø¬Ù…Ø§Ù„ÙŠ USD')}: <b>{_fmt_money(totals.get('usd',0))}</b>")
    lines.append("â€” â€” â€”")
    for r in rows[:25]:
        emo = status_emo.get(str(r.get('status') or "").lower(), "â€¢")
        lines.append(
            f"{emo} #{r['id']} | {r.get('slug','-')}/{r.get('days','-')}dÃ—{r.get('qty','-')} | "
            f"USD { _fmt_money(r.get('usd_amount')) } | {(r.get('asset') or '').upper()} { _fmt_money(r.get('ton_amount')) } | "
            f"{r.get('status','-')} | {r.get('created_at','-')} | @{r.get('username') or '-'}"
        )
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ---------- ØØ°Ù ØªÙ‚Ø§Ø±ÙŠØ± Ù…Ø³ØªØ®Ø¯Ù… ----------
@router.callback_query(F.data == "shopr:deluser")
async def shop_reports_deluser(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(ShopRptStates.wait_user_del)
    await cb.message.answer(tt(lang, "rpt.deluser.ask", "Ø£Ø±Ø³Ù„ ID Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø£Ùˆ @username Ù„ØØ°Ù Ø¬Ù…ÙŠØ¹ ØªÙ‚Ø§Ø±ÙŠØ±Ù‡ (Ø³ÙŠÙØ·Ù„Ø¨ ØªØ£ÙƒÙŠØ¯)."))
    await cb.answer()

@router.message(ShopRptStates.wait_user_del)
async def shop_reports_deluser_confirm(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    key_raw = (msg.text or "").strip()
    await state.clear()

    if not key_raw:
        return await msg.answer(tt(lang, "rpt.input_empty", "Ø§Ù„Ù†Øµ ÙØ§Ø±Øº."))

    key = key_raw.lstrip("@").lower()
    kind = "uid" if key.isdigit() else "uname"

    # ÙƒÙ… Ø³Ø¬Ù„ØŸ
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
        InlineKeyboardButton(text="âœ… ØªØ£ÙƒÙŠØ¯ Ø§Ù„ØØ°Ù", callback_data=f"shopr:deluser:go:{kind}:{key}"),
        InlineKeyboardButton(text="âŽ Ø¥Ù„ØºØ§Ø¡",       callback_data="shopr:deluser:cancel"),
    )
    await msg.answer(
        tt(lang, "rpt.deluser.confirm", "Ø³ÙŠØªÙ… ØØ°Ù {n} Ø³Ø¬Ù„(Ø§Øª) Ù„Ù‡Ø°Ø§ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…. ØªØ£ÙƒÙŠØ¯ØŸ").format(n=n),
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "shopr:deluser:cancel")
async def shop_reports_deluser_cancel(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "cancelled", "Ø£ÙÙ„ØºÙŠØª"), show_alert=True)

@router.callback_query(F.data.startswith("shopr:deluser:go:"))
async def shop_reports_deluser_go(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    # shopr:deluser:go:<kind>:<val>
    parts = cb.data.split(":")
    kind, val = parts[-2], parts[-1]
    where = "user_id = ?" if kind == "uid" else "lower(username) = ?"
    param = int(val) if kind == "uid" else val

    if not DB_PATH:
        return await cb.answer(tt(lang, "rpt.no_db", "Ù‚Ø§Ø¹Ø¯Ø© Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª ØºÙŠØ± Ù…Ù‡ÙŠÙ‘Ø£Ø©."), show_alert=True)

    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        cur = await db.execute(f"DELETE FROM orders WHERE {where}", (param,))
        await db.commit()
        deleted = max(cur.rowcount or 0, 0)

    await cb.answer(tt(lang, "rpt.del_done", "ØªÙ… ØØ°Ù {n} Ø³Ø¬Ù„.").format(n=deleted), show_alert=True)

# ---------- Ù…Ø³Ø ÙƒÙ„ Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ± (Ø£Ùˆ ØªÙ‚Ø§Ø±ÙŠØ± Ù…Ù†ØªØ¬ Ù…Ø®ØªØ§Ø±) ----------
@router.callback_query(F.data == "shopr:delall")
async def shop_reports_delall(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    prod = _selected_product_from_kb(cb.message)  # None => Ù„Ø§ Ø´ÙŠØ¡ Ù…ØØ¯Ø¯
    scope_txt = "Ø§Ù„ÙƒÙ„" if not prod else f"Ø§Ù„Ù…Ù†ØªØ¬: {prod}"

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="ðŸ§¨ Ù†Ø¹Ù…ØŒ ØØ°Ù", callback_data=f"shopr:delall:go:{prod or '-'}"),
        InlineKeyboardButton(text="âŽ Ø¥Ù„ØºØ§Ø¡",     callback_data="shopr:delall:cancel"),
    )
    await cb.message.answer(
        tt(lang, "rpt.delall.ask", "ØªØ£ÙƒÙŠØ¯ Ù…Ø³Ø Ø§Ù„ØªÙ‚Ø§Ø±ÙŠØ± ({scope})ØŸ Ù„Ø§ ÙŠÙ…ÙƒÙ† Ø§Ù„ØªØ±Ø§Ø¬Ø¹.").format(scope=scope_txt),
        reply_markup=kb.as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "shopr:delall:cancel")
async def shop_reports_delall_cancel(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "cancelled", "Ø£ÙÙ„ØºÙŠØª"), show_alert=True)

@router.callback_query(F.data.startswith("shopr:delall:go:"))
async def shop_reports_delall_go(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    prod = cb.data.split(":")[-1]
    product = None if prod in ("-", "", "None") else prod

    if not DB_PATH:
        return await cb.answer(tt(lang, "rpt.no_db", "Ù‚Ø§Ø¹Ø¯Ø© Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª ØºÙŠØ± Ù…Ù‡ÙŠÙ‘Ø£Ø©."), show_alert=True)

    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        if product:
            cur = await db.execute("DELETE FROM orders WHERE slug = ?", (product,))
        else:
            cur = await db.execute("DELETE FROM orders")
        await db.commit()
        deleted = max(cur.rowcount or 0, 0)

    scope_txt = "Ø§Ù„ÙƒÙ„" if not product else f"Ø§Ù„Ù…Ù†ØªØ¬: {product}"
    await cb.answer(tt(lang, "rpt.delall.done", "ØÙØ°Ù {n} Ø³Ø¬Ù„ ({scope}).").format(n=deleted, scope=scope_txt), show_alert=True)

# ---------- ØªØµØ¯ÙŠØ± CSV ----------
@router.callback_query(F.data.startswith("shopr:csv:"))
async def shop_reports_csv(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"; return await cb.answer(tt(l,"admins_only","Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·"), show_alert=True)

    # shopr:csv:<period>-<product>
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
                                     caption=f"CSV â€” {label} â€¢ Ø§Ù„Ù…Ù†ØªØ¬: {product or 'Ø§Ù„ÙƒÙ„'} â€¢ Ø§Ù„Ø³Ø¬Ù„Ø§Øª: {len(rows)}")
    await cb.answer("âœ…")

