from utils.admins import get_admin_ids, is_admin, get_owner_ids
# bot.py
# =========================================
# S.E Support Bot (Aiogram v3) — Clean & Ready (Merged)
# =========================================
# bot.py (أول سطرين في الملف)
import os
from dotenv import load_dotenv, find_dotenv

# نكشف أننا على Railway من أي علامة بيئية
ON_RAILWAY = bool(
    os.getenv("RAILWAY_PROJECT_ID")
    or os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_STATIC_URL")
)

# محليًا فقط: حمّل .env (بدون override)
# على Railway: لا تلمس .env — استخدم Variables فقط
if not ON_RAILWAY:
    try:
        from utils.secrets import preload_env
        preload_env()  # لو عندك تهيئة سرّية محلية
    except Exception:
        pass
    load_dotenv(find_dotenv(filename=".env"), override=False)


from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(filename=".env"), override=True)

import os, sys, asyncio, logging, importlib, pathlib
from dotenv import load_dotenv
from aiogram import BaseMiddleware
from services import orders as ords
from services.payments import check_and_deliver_one
# ============ Maintenance switch ============
if os.getenv("MAINTENANCE") == "1":
    print("Maintenance mode: exiting.")
    sys.exit(0)


# ============ i18n safe t() shim ============
import lang as _lang_mod
try:
    _orig_t = _lang_mod.t
except Exception:
    _orig_t = None

def _t_compat(*args, **kwargs):
    if _orig_t is None:
        if len(args) >= 3:
            return args[2] or ""
        return ""
    if len(args) >= 3:
        lang_code, key, fallback = args[0], args[1], args[2]
        try:
            val = _orig_t(lang_code, key)
        except Exception:
            val = None
        if isinstance(val, str) and val.strip() and val != key:
            return val
        return fallback or ""
    try:
        val = _orig_t(*args, **kwargs)
    except Exception:
        return ""
    key = args[1] if len(args) >= 2 else None
    if isinstance(val, str) and val.strip() and (key is None or val != key):
        return val
    return ""

_lang_mod.t = _t_compat
t = _lang_mod.t

# ============ Logging ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
log = logging.getLogger(__name__)

# ============ Prefer local modules ============
import pathlib as _pl
ROOT = _pl.Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    import handlers as _handlers_pkg
    logging.info(f"[IMPORT] handlers package path -> {_handlers_pkg.__file__}")
except Exception:
    pass

# ============ Alerts (optional) ============
alerts_admin_router = None
alerts_user_router = None
init_alerts_scheduler = None
try:
    from admin.alerts_admin import router as alerts_admin_router
    from handlers.alerts_userف import router as alerts_user_router
    from utils.alerts_scheduler import init_alerts_scheduler
    logging.info("Alerts modules loaded (admin+user+scheduler).")
except Exception as e:
    logging.warning("FAILED to load alerts modules: %s", e)

if alerts_admin_router or alerts_user_router or init_alerts_scheduler:
    logging.info("Alerts modules available.")
else:
    logging.warning("Alerts modules not available (continuing without alerts).")

# ============ Storage backend ============
# ============ Storage backend ============
PRODUCT = os.getenv("PRODUCT_KEY", "8bp")

BACKEND = (os.getenv("INVENTORY_BACKEND", os.getenv("STORAGE_BACKEND", "")) or "").lower()
USE_DB  = bool(os.getenv("DATABASE_URL")) if not BACKEND.startswith("keys") else False

try:
    if BACKEND.startswith(("keys", "legacy")):
        import sys
        from services import inventory_keys_adapter as _inv_mod
        # نلبّس اسم الحزمة حتى أي import لاحق لـ services.inventory يقرأ المحوّل
        sys.modules['services.inventory'] = _inv_mod
        inv = _inv_mod
        logging.info("Storage backend: KEYS (adapter mounted as services.inventory)")
    elif USE_DB or BACKEND in ("db", "postgres", "postgresql"):
        from services import inventory_db as inv
        logging.info("Storage backend: DB (PostgreSQL)")
    else:
        from services import inventory as inv
        logging.info("Storage backend: FILES (txt)")
except Exception as e:
    logging.exception("Failed to init chosen storage, falling back to FILES: %s", e)
    from services import inventory as inv
    logging.info("Storage backend: FILES (fallback)")

# ============ Aiogram & utils ============
from utils.ensure_files import ensure_required_files
from importlib import import_module
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat,
    InlineKeyboardMarkup, InlineKeyboardButton, Message
)
from aiogram.fsm.context import FSMContext

# ===== Core handlers =====
from handlers import start as h_start
import handlers.supplier_payment as _supplier_payment
from handlers.human_check import router as human_router
from handlers.inventory_admin import router as inventory_admin_router
from handlers.help import help_handler_target as _help_target
from handlers import shop as _shop
from handlers.report import report_cmd, router as report_router
from handlers.home_hero import router as home_hero_router
from handlers.compat_shims import router as compat_router
from handlers.reseller_apply import router as reseller_apply_router
from handlers.supplier_directory import router as supplier_directory_router
from handlers.admin_manage import router as admin_manage
from admin.admin_access import router as admin_access
from aiogram import Router, F
# استدعِ دالة الهاندلر نفسها من ملفك
from handlers.promoter import router as promoter_router
from handlers.promoter_panel import router as promoter_panel_router
from handlers.anti_groups import router as anti_groups_router
from handlers.bot_panel import router as bot_panel_router
#from handlers.quick_sections import router as quick_sections_router
from handlers.home_menu import router as home_menu_router
from handlers.persistent_menu import router as persistent_menu_router
from handlers.menu_buttons import router as menu_buttons_router
from utils.vip_cron import run_vip_cron
from lang import t as _t_passthrough  # noqa
from handlers.live_chat import router as live_chat_router
from admin import shop_admin as _shop_admin

from middlewares.ephemeral_kb import EphemeralKBGuard
from handlers.support_inbox_admin import router as support_inbox_router
from admin.admin_features import router as features_router
from admin import admin_roles_panel as _admin_roles_panel
from middlewares.force_join import ForceJoinMiddleware
from handlers.force_join_check import router as fj_router
from handlers.rewards_profile_pro import router as rewards_profile_router
from handlers.debug_storage import router as debug_storage_router
from middlewares.seen_user import SeenUserMiddleware
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
# --- Promo system (Free SEVIP) ---
from handlers.promo_free_sevip import router as promo_free_router        # واجهة المستخدم للترويج (الشروط/المنصات/الرابط/اللقطة/الكود)
from handlers.promo_flow_extras import router as promo_flow_router       # أدوات الإدارة + فتح الدردشة + جمع Snake ID
from admin.promo_panel_ui import router as promo_panel_ui_router
         # (اختياري) لوحة مراجعة الطلبات
# لا تستورد promo_open/terms/choose_platform كدوال منفصلة — هذه مُسجّلة داخل الراوترات
from admin.promo_panel_ui import router as promo_panel_ui_router
from handlers import paydiag as _paydiag

# الصحيح:
from admin.admin_center import router as admin_center_router   # يملك Router
import admin.live_exclusive_only                            # 2) فعّل الـ patch (بدون include_router)


# ===== Rewards (optional) =====
import handlers.rewards_gate as _rewards_gate
import handlers.rewards_hub as _rewards_hub
import handlers.rewards_market as _rewards_market
import handlers.rewards_wallet as _rewards_wallet
import handlers.rewards_compat as _rewards_compat
try:
    from handlers import rewards_profile_pro as _rewards_profile_pro
except Exception:
    _rewards_profile_pro = None

def _opt_import(mod_path: str):
    try:
        return import_module(mod_path)
    except Exception as e:
        logging.getLogger(__name__).info(f"[IMPORT] optional module skipped: {mod_path} ({e})")
        return None

_rewards_market_admin = _opt_import("admin.rewards_market_admin")
_rewards_admin        = _opt_import("admin.rewards_admin")
from admin import admin_hub as _admin_hub

# ====== (NEW) Rewards mounting helpers to avoid callback conflicts ======
REWARDS_PREFIXES = ("rewards:", "rwd:", "wallet:", "rwm:", "store:", "rwh:", "rw:", "rwp:")

_REWARDS_MOUNTED = False
def _mount_rewards_routers(dp: Dispatcher):
    """ثبت راوترات الجوائز مبكراً + فلترة على الخاص وبادئات معيّنة لمنع التضارب."""
    global _REWARDS_MOUNTED
    if _REWARDS_MOUNTED:
        logging.info("Rewards routers already mounted; skipping.")
        return

    def _pin(router_obj: Router):
        try:
            router_obj.message.filter(F.chat.type == "private")
        except Exception:
            pass
        try:
            router_obj.callback_query.filter(F.message.chat.type == "private")
            router_obj.callback_query.filter(F.data.startswith(REWARDS_PREFIXES))
        except Exception:
            pass

    for _r in (_rewards_gate.router, _rewards_hub.router, _rewards_market.router,
               _rewards_wallet.router, _rewards_compat.router):
        _pin(_r)

    if _rewards_profile_pro and hasattr(_rewards_profile_pro, "router"):
        _pin(_rewards_profile_pro.router)
        dp.include_router(_rewards_profile_pro.router)

    
    # الشِم يبقى بدون فلتر البادئات لأنه يستخدم قيم بسيطة مثل "rewards"/"wallet"/"store"
    dp.include_router(rewards_shim)

    _REWARDS_MOUNTED = True
    logging.info("Rewards routers mounted (priority + prefix filters applied).")

# ===== Middlewares =====
from middlewares.force_start import ForceStartMiddleware
from middlewares.user_tracker import UserTrackerMiddleware
from middlewares.maintenance import MaintenanceMiddleware
from middlewares.vip_rate_limit import VipRateLimitMiddleware
from middlewares.auto_subscribe import AutoSubscribeMiddleware
try:
    from middlewares.tracer import TracerMiddleware
except Exception:
    TracerMiddleware = None

# ============ Payments watcher ============
from services.payments import start_auto_watcher  # returns a ready Task

# ============ General env ============
TOKEN = os.getenv("BOT_TOKEN")
FORCE_START_ON_MSG = int(os.getenv("FORCE_START_ON_MSG", "0"))
UGATE_ON_MSG       = int(os.getenv("UGATE_ON_MSG", "0"))  # (موجود للتماشي فقط)
WATCHER_SEC        = int(os.getenv("WATCHER_SEC", "12"))
ONLY_REPORT        = os.getenv("ONLY_REPORT", "0") == "1"

# ============ Admin IDs ============
# ============ Admin IDs ============
import re
print("[BUILD] MARK = admin-fix-v1")

def _parse_admin_ids(s: str | None) -> list[int]:
    if not s:
        return []
    ids = set()
    for part in re.split(r"[,\s]+", s.strip()):
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return sorted(ids)

_admin_ids_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS: list[int] = _parse_admin_ids(_admin_ids_env)

# Fallback احتياطي لو ما وصل شيء من البيئة
if not ADMIN_IDS:
    ADMIN_IDS = get_admin_ids()

print(f"[ADMIN] Loaded ADMIN_IDS = {ADMIN_IDS}")

# ============ Commands ============
def _public_cmds(lang: str = "en") -> list[BotCommand]:
    return [
        BotCommand(command="start",    description=t(lang, "cmd_start")    or "Start"),
        BotCommand(command="shop",     description=t(lang, "cmd_shop")     or ("Buy keys" if lang=="en" else "شراء مفاتيح")),
        BotCommand(command="sections", description=t(lang, "cmd_sections") or ("Quick sections" if lang=="en" else "الأقسام السريعة")),
        BotCommand(command="rewards",  description=t(lang, "cmd_rewards")  or ("Rewards hub" if lang=="en" else "الجوائز")),
        BotCommand(command="help",     description=t(lang, "cmd_help")     or "Help"),
        BotCommand(command="about",    description=t(lang, "cmd_about")    or "About"),
        BotCommand(command="report",   description=t(lang, "cmd_report")   or "Report a problem"),
        BotCommand(command="language", description=t(lang, "cmd_language") or "Language"),
    ]

def _admin_cmds(lang: str = "en") -> list[BotCommand]:
    return _public_cmds(lang) + [
        BotCommand(command="admin", description=t(lang, "cmd_admin") or "Admin panel"),
    ]

async def set_bot_commands(bot: Bot):
    await bot.set_my_commands(_public_cmds("en"), scope=BotCommandScopeDefault(), language_code="en")
    try:
        await bot.set_my_commands(_public_cmds("ar"), scope=BotCommandScopeDefault(), language_code="ar")
    except Exception as e:
        logging.warning(f"Failed set default AR commands: {e}")
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(_admin_cmds("en"), scope=BotCommandScopeChat(chat_id=admin_id), language_code="en")
        except Exception as e:
            logging.warning(f"Failed set commands (EN) for admin {admin_id}: {e}")
        try:
            await bot.set_my_commands(_admin_cmds("ar"), scope=BotCommandScopeChat(chat_id=admin_id), language_code="ar")
        except Exception as e:
            logging.warning(f"Failed set commands (AR) for admin {admin_id}: {e}")

# ============ Flexible imports groups ============
def _try_import_router(mod_path: str):
    try:
        mod = import_module(mod_path)
        r = getattr(mod, "router", None)
        if r is None:
            logging.warning(f"{mod_path} موجود لكن لا يحتوي router")
            return None
        return r
    except ModuleNotFoundError as e:
        logging.debug(f"Module not found: {mod_path} ({e})")
        return None
    except Exception as e:
        logging.warning(f"Failed to import {mod_path}: {e}")
        return None

def _import_tools_router():
    for path in ("handlers.tools_handler", "handlers.tools"):
        r = _try_import_router(path)
        if r:
            logging.info(f"Loaded {path}")
            return r
    logging.warning("No tools handler found. Skipping tools router.")
    return None
TOOLS_ROUTER = _import_tools_router()

def _import_admin_routers():
    paths = (
        "admin.report_admin",
        "admin.report_inbox",
        "admin.vip_manager",
        "admin.promoter_admin",
        "admin.promoters_panel",
        "admin.promoter_actions",
        "admin.live_support_admin",
        "admin.home_ui_admin",
    )
    routers = []
    for p in paths:
        r = _try_import_router(p)
        if r:
            routers.append(r)
    return routers

# ============ Public handlers list ============
_HANDLER_MODULES = [
    "handlers.help",
    "handlers.about",
    "handlers.supplier_vault",
    #"handlers.supplier_directory",
    "handlers.download",
    "handlers.language_handlers",
    "handlers.language",
    #"handlers.vip",
    #"handlers.vip_features",
    "handlers.app_download",
    "handlers.reseller",
    #"handlers.live_chat",
    "handlers.basic_cmds",
    "handlers.contact",
    "handlers.deviceinfo",
    "handlers.version",
    "handlers.verified_resellers",
    "handlers.trusted_suppliers",
    "handlers.security_status",
    "handlers.safe_usage",
    "handlers.deviceinfo_check",
    "handlers.server_status",
    "handlers.debug_callbacks",
]

try:
    import handlers.app_download as _appdl_chk
    logging.info(f"[CHECK] imported handlers.app_download OK, has router={hasattr(_appdl_chk, 'router')}")
except Exception:
    logging.exception("[CHECK] FAILED to import handlers.app_download")

def _load_public_routers():
    routers = []
    for path in _HANDLER_MODULES:
        r = _try_import_router(path)
        if r:
            routers.append(r)
            logging.info(f"Loaded {path}")
    return routers

PUBLIC_ROUTERS = _load_public_routers()

# ===== Shims (Rewards) =====
rewards_shim = Router(name="rewards_shim")

@rewards_shim.callback_query(F.data == "rewards")
async def _shim_rewards(cb):
    try:
        from handlers.rewards_profile_pro import open_profile
        await open_profile(cb, edit=True)
    except Exception:
        await _rewards_hub.open_hub(cb, edit=True)

@rewards_shim.callback_query(F.data == "wallet")
async def _shim_wallet(cb):
    await _rewards_wallet.open_wallet(cb)

@rewards_shim.callback_query(F.data == "store")
async def _shim_store(cb):
    await _rewards_market.open_market(cb)

rwdadm_shim = Router(name="rwdadm_shim")
@rwdadm_shim.callback_query(F.data.startswith("rwdadm:"))
async def _shim_rwdadm(cb):
    if cb.from_user.id in ADMIN_IDS:
        await cb.answer("❗ وحدة إدارة الجوائز غير محمّلة.", show_alert=True)
    else:
        await cb.answer("Admins only.", show_alert=True)

# ===== Diagnostics =====
diag_router = Router(name="diag")
from lang import get_user_lang, set_user_lang  # noqa

@diag_router.message(Command("language", "lang"))
async def _first_lang(m: Message):
    from handlers.language import language_command
    await language_command(m)

@diag_router.message(Command("report"))
async def _diag_report_entry(m: Message, state: FSMContext):
    return await report_cmd(m, state)

@diag_router.message(Command("help", "faq"))
async def _first_help(m: Message):
    await _help_target(m.from_user.id, m.answer)

@diag_router.message(Command("about"))
async def _about(m: Message):
    try:
        lang = get_user_lang(m.from_user.id) or "en"
    except Exception:
        lang = "en"
    text = t(lang, "about_text") or "ℹ️ <b>S.E Support</b>\nAssistant for services & support.\nUse /help for FAQ."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "back_to_menu") or "⬅️ Back to menu", callback_data="back_to_menu")]
    ])
    await m.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@diag_router.message(Command("whoami"))
async def whoami_cmd(m: Message):
    uid = m.from_user.id
    uname = f"@{m.from_user.username}" if m.from_user.username else "—"
    await m.answer(f"👤 Your ID: <code>{uid}</code>\n🔹 Username: {uname}")

# ===== Register routers =====
def register_routers(dp: Dispatcher):
    # ONLY_REPORT mode
    if ONLY_REPORT:
        dp.include_router(report_router)
        logging.warning("🚧 ONLY_REPORT=1 — Report router only (no middlewares).")
        return

    # Middlewares
    if TracerMiddleware:
        dp.update.middleware(TracerMiddleware())
    mmw = MaintenanceMiddleware()
    utm = UserTrackerMiddleware()
    fs  = ForceStartMiddleware()
    vrl = VipRateLimitMiddleware()
    dp.update.outer_middleware(EphemeralKBGuard())

    # Early routers
    dp.include_router(compat_router)
    dp.include_router(diag_router)
    logging.info("Loaded diag_router (debug_storage/migrate/inv_diag/inv_repair)")

    dp.message.middleware(mmw); dp.callback_query.middleware(mmw)
    dp.message.middleware(utm); dp.callback_query.middleware(utm)

    autosub = AutoSubscribeMiddleware()
    dp.message.middleware(autosub); dp.callback_query.middleware(autosub)

    # Private only
    dp.message.filter(F.chat.type == "private")
    dp.callback_query.filter(F.message.chat.type == "private")

    # --- (NEW) خطاف مبكر يضمن /sections دائماً ---
    sections_fast = Router(name="sections_fast")
    sections_fast.message.filter(F.chat.type == "private")
    dp.include_router(sections_fast)
    # ------------------------------------------------

    if FORCE_START_ON_MSG:
        dp.message.middleware(fs)
    dp.callback_query.middleware(fs)

    # ثبّت t داخل start (لو احتج)
    try:
        h_start.t = t
    except Exception:
        pass

    dp.include_router(_rewards_gate.router)
    dp.include_router(_rewards_hub.router)
    dp.include_router(_rewards_wallet.router)
    dp.include_router(_rewards_market.router)
    dp.include_router(_rewards_compat.router)
    # ===== (NEW) امنع الراوترات النصية من ابتلاع الأوامر =====
    home_menu_router.message.filter(~F.text.startswith("/"))
    bot_panel_router.message.filter(~F.text.startswith("/"))
    menu_buttons_router.message.filter(~F.text.startswith("/"))

    # Alerts (if available)
    if alerts_admin_router:
        dp.include_router(alerts_admin_router); logging.info("Loaded admin.alerts_admin")
    if alerts_user_router:
        dp.include_router(alerts_user_router);   logging.info("Loaded handlers.alerts_user")

    # === (NEW) ثبّت راوترات الجوائز مبكراً لتأخذ الأولوية ومنع التعارض ===
    #dp.include_router(admin_roles_panel.router)##########################
    dp.include_router(_admin_roles_panel.router)#########################

    # Shop
    dp.include_router(_shop.router);        logging.info("Loaded handlers.shop")
    dp.include_router(home_menu_router);        logging.info("Loaded handlers.home_menu")
    dp.include_router(supplier_directory_router);   logging.info("Loaded supplier_directory (PRIORITY)")

    # Start & hero
    dp.include_router(live_chat_router);        logging.info("Loaded handlers.live_chat (PRIORITY BEFORE MENUS)")
    dp.include_router(h_start.router);          logging.info("Loaded handlers.start (forced include)")
    dp.include_router(home_hero_router);        logging.info("Loaded handlers.home_hero")
    dp.include_router(_admin_hub.router)
    #dp.include_router(quick_sections_router);   logging.info("Loaded handlers.quick_sections")
    _mount_rewards_routers(dp)

    #persistent_menu_router.message.filter(~F.text.startswith("/"))
    dp.include_router(report_router);           logging.info("Loaded handlers.report (PRIORITY)")
   
    # Menus & panel
    dp.include_router(reseller_apply_router);   logging.info("Loaded handlers.reseller_apply (PRIORITY)")
    dp.include_router(promoter_router);         logging.info("Loaded handlers.promoter")
    dp.include_router(promoter_panel_router);   logging.info("Loaded handlers.promoter_panel")

    dp.include_router(bot_panel_router);        logging.info("Loaded handlers.bot_panel")
    dp.include_router(menu_buttons_router);     logging.info("Loaded handlers.menu_buttons")
    dp.include_router(persistent_menu_router);  logging.info("Loaded handlers.persistent_menu")
    dp.include_router(support_inbox_router);    logging.info("Loaded handlers.support_inbox_admin")
    dp.include_router(_shop_admin.router);      logging.info("Loaded handlers.shop_admin")

    # ===== (NEW) حصر live_chat في الخاص + لا يلتقط الأوامر أو نص أزرار الأقسام =====
    live_chat_router.message.filter(F.chat.type == "private")
    live_chat_router.callback_query.filter(F.message.chat.type == "private")
    live_chat_router.message.filter((~F.text.startswith("/")) | F.text.in_({"/live_on", "/live_off"}))

    # Anti-groups
    dp.include_router(anti_groups_router);      logging.info("Loaded handlers.anti_groups")

    # Core
    dp.include_router(_supplier_payment.router); logging.info("Loaded handlers.supplier_payment")
    dp.include_router(_paydiag.router)
    dp.include_router(human_router);             logging.info("Loaded handlers.human_check")
    dp.include_router(inventory_admin_router);   logging.info("Loaded handlers.inventory_admin")
    dp.message.outer_middleware(StarsPayMiddleware())
    dp.include_router(features_router)

    dp.message.outer_middleware(ForceJoinMiddleware())
    dp.callback_query.outer_middleware(ForceJoinMiddleware())
    dp.include_router(fj_router)   # ← هذا الذي يجعل fj_check يعمل
    dp.include_router(debug_storage_router)
    dp.update.middleware(SeenUserMiddleware())        # applies على كل التحديثات

    dp.include_router(promo_free_router)
    dp.include_router(promo_flow_router)

    dp.include_router(admin_center_router)
    dp.include_router(promo_panel_ui_router)


    # Rewards (fallback: لو لأي سبب ما رُكّبت مبكراً)
    if not _REWARDS_MOUNTED:
        _mount_rewards_routers(dp)

    # أولوية عالية
    
   
    dp.include_router(admin_manage)
    dp.include_router(admin_access)

    if _rewards_profile_pro and hasattr(_rewards_profile_pro, "router"):
        # سيكون مُضمَّن مسبقاً داخل _mount_rewards_routers؛ السطر التالي آمن لو لم يُضمَّن
        try:
            dp.include_router(_rewards_profile_pro.router); logging.info("Loaded handlers.rewards_profile_pro")
        except Exception:
            pass
    if _rewards_admin and hasattr(_rewards_admin, "router"):
        dp.include_router(_rewards_admin.router); logging.info("Loaded admin.rewards_admin")
    else:
        dp.include_router(rwdadm_shim); logging.warning("admin.rewards_admin not available -> rwdadm_shim enabled")

    # Additional admin routers
    for r in _import_admin_routers():
        dp.include_router(r)

    # Tools router (optional)
    if TOOLS_ROUTER:
        dp.include_router(TOOLS_ROUTER)

    # Public routers
    for r in _load_public_routers():
        dp.include_router(r)

    # Rate-Limit
    dp.message.middleware(vrl); dp.callback_query.middleware(vrl)

    # Fallbacks
    fallback = Router(name="fallback_public")

    @fallback.message(Command("whoami"))
    async def _fb_whoami(msg: Message):
        uid = msg.from_user.id
        un  = f"@{msg.from_user.username}" if msg.from_user.username else "—"
        await msg.answer(f"👤 Your ID: <code>{uid}</code>\n🔹 Username: {un}")

    @fallback.message(Command("debug_storage"))
    async def _fb_debug(msg: Message):
        mode = "DB" if USE_DB else "FILES"
        snap = await inv.snapshot_msg(PRODUCT)
        await msg.answer(f"[FB] Mode={mode}\nPRODUCT_KEY={PRODUCT}\nSnapshot={snap}", parse_mode=None)

    @fallback.message(Command("start"))
    async def _fb_start(msg: Message):
        await msg.answer("👋 أهلاً بك! إذا لم تظهر القائمة، اضغط زر Menu بالأسفل، أو أرسل /sections.")

    @fallback.message(Command("help"))
    async def _fb_help(msg: Message):
        await msg.answer("ℹ️ المساعدة: استخدم الأزرار بالأسفل للتنقل. إن لم تعمل الأوامر، أرسل /start مرة واحدة.")

    @fallback.message(Command("about"))
    async def _fb_about(msg: Message):
        await msg.answer("ℹ️ حول البوت: S.E Support — مساعد الخدمات.\nللمزيد: /help")

    @fallback.message(Command("language"))
    async def _fb_lang(msg: Message):
        await msg.answer("🌐 تغيير اللغة: افتح القائمة السفليّة واختر Language.")

    @fallback.message(Command("rewards"))
    async def _fb_rewards(msg: Message):
        try:
            from handlers.rewards_profile_pro import open_profile
            await open_profile(msg)
        except Exception:
            await _rewards_hub.open_hub(msg)

    @fallback.message(Command("shop"))
    async def _fb_shop(msg: Message):
        try:
            await _shop.open_shop(msg)
        except Exception as e:
            logging.exception("fallback /shop failed: %s", e)
            await msg.answer("⚠️ حدث خلل مؤقت أثناء فتح المتجر. حاول مرة أخرى.")

    @fallback.callback_query(F.data == "shop:sevip")
    async def _fb_shop_legacy(cb):
        try:
            await _shop.open_shop(cb.message)
            await cb.answer()
        except Exception as e:
            logging.exception("compat shop:sevip failed: %s", e)
            await cb.answer("⚠️ حدث خلل أثناء فتح المتجر.", show_alert=True)

    @fallback.message(Command("admin"))
    async def _fb_admin(msg: Message):
        if msg.from_user.id in ADMIN_IDS:
            await msg.answer("👑 لوحة الأدمن: إذا لم تظهر الواجهة، جرّب /vipadm أو /admin مرة أخرى.")
        else:
            await msg.answer("هذه الأوامر للمشرفين فقط.")

    dp.include_router(fallback)
    logging.info("Loaded fallback_public (safety commands).")


def _mount_rewards_routers(dp: Dispatcher) -> None:
    # لا تضف الراوتر مرتين
    if getattr(rewards_profile_router, "parent_router", None) is None:
        dp.include_router(rewards_profile_router)
        logging.info("Loaded handlers.rewards_profile_pro (callbacks active).")

# ===== Alerts startup hook =====
def _alerts_startup_factory(init_alerts_scheduler):
    async def _alerts_startup(bot: Bot):
        if init_alerts_scheduler:
            try:
                await init_alerts_scheduler(bot)
                logging.info("🔔 Alerts scheduler started.")
            except Exception as e:
                logging.warning(f"Alerts scheduler failed to start: {e}")
    return _alerts_startup

# ===== Bot/session =====
def _make_bot() -> "Bot":
    total = float(os.getenv("BOT_HTTP_TOTAL_TIMEOUT", "15"))
    session = AiohttpSession(timeout=total)
    return Bot(token=TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

def _make_storage():
    REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
    if not REDIS_URL:
        logging.info("FSM storage: MemoryStorage (no REDIS_URL)")
        return MemoryStorage()
    try:
        RedisStorage = None
        try:
            from aiogram.fsm.storage.redis import RedisStorage as _RS
            RedisStorage = _RS
        except Exception:
            pass
        redis_async = importlib.import_module("redis.asyncio")
        redis_from_url = getattr(redis_async, "from_url")
        redis_cli = redis_from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        if not RedisStorage:
            logging.warning("aiogram RedisStorage not available; using MemoryStorage()")
            return MemoryStorage()
        logging.info(f"FSM storage: Redis ({REDIS_URL})")
        return RedisStorage(redis_cli)
    except Exception as e:
        logging.warning(f"Redis init failed ({e}); using MemoryStorage()")
        return MemoryStorage()

# ===== Entry point =====
ensure_required_files()

async def main():
    if not TOKEN:
        raise RuntimeError("❌ BOT_TOKEN غير موجود في متغيرات البيئة (.env)")

    bot = _make_bot()
    dp  = Dispatcher(storage=_make_storage())

    me = await bot.get_me()
    logging.info(f"🤖 Logged in as @{me.username} (id={me.id})")

    # CryptoPay watcher (ready task)
    try:
        start_auto_watcher(bot, interval_sec=WATCHER_SEC)
    except Exception as e:
        logging.warning(f"TON/USDT auto watcher failed to start: {e}")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook deleted (switching to polling).")
    except Exception as e:
        logging.warning(f"delete_webhook failed (continue polling): {e}")

    await set_bot_commands(bot)
    register_routers(dp)
    dp.startup.register(_alerts_startup_factory(init_alerts_scheduler))

    # VIP cron (best effort)
    try:
        asyncio.create_task(run_vip_cron(bot))
        logging.info("⏰ VIP reminder task started.")
    except Exception as e:
        logging.warning(f"VIP reminder task failed to start: {e}")

    logging.info("🚀 Bot is starting polling...")
    logging.info("Loaded handlers.promo_flow_extras")
    logging.info("Loaded handlers.promo_free_sevip")
    updates = set(dp.resolve_used_update_types() or [])
    updates.update({"message", "callback_query", "pre_checkout_query"})  # ⭐ مهم لنجوم تيليجرام
    updates.update({"chat_member", "my_chat_member"})
    logging.warning(f"[UPDATES] allowed_updates = {sorted(updates)}")
    await dp.start_polling(bot, allowed_updates=list(updates))

class StarsPayMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        """
        يمسك أي رسالة فيها successful_payment لعملة XTR (نجوم)،
        يوسِم الطلب كمدفوع ثم يسلّم المفاتيح فوراً.
        """
        try:
            msg = getattr(event, "message", None) or event
            sp = getattr(msg, "successful_payment", None)
            if sp:
                payload = (sp.invoice_payload or "")
                if payload.startswith("stars:"):
                    oid = int(payload.split(":", 1)[1])
                    logging.info("[PAY⭐][MW] caught successful_payment payload=%s", payload)

                    # علّم الطلب مدفوع
                    try:
                        await ords.mark_paid(oid)
                    except Exception as e:
                        logging.exception("mark_paid failed: %r", e)

                    # سلّم المفاتيح للمستخدم
                    try:
                        await check_and_deliver_one(data["bot"], oid, notify_user=True)
                    except Exception as e:
                        logging.exception("deliver failed: %r", e)

                    # لا تمرر لل_handlers الأخرى (يكفي)
                    return
        except Exception as e:
            logging.exception("StarsPayMiddleware error: %r", e)

        # مرر للمعالجة المعتادة
        return await handler(event, data)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot stopped.")

