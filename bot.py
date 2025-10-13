# bot.py
# =========================================
# S.E Support Bot (Aiogram v3) — Clean & Ready (Fixed Routers)
# =========================================

from utils.secrets import preload_env
preload_env()

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(filename=".env"), override=True)

import os, sys, asyncio, logging, importlib
from importlib import import_module

# ============ Maintenance switch ============
if os.getenv("MAINTENANCE") == "1":
    print("Maintenance mode: exiting.")
    sys.exit(0)

load_dotenv()

# ============ Logging ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
log = logging.getLogger(__name__)

# ============ Prefer local modules ============
try:
    import handlers as _handlers_pkg
    logging.info(f"[IMPORT] handlers package path -> {_handlers_pkg.__file__}")
except Exception:
    pass

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

# ============ Storage backend ============
PRODUCT = os.getenv("PRODUCT_KEY", "8bp")
BACKEND = (os.getenv("INVENTORY_BACKEND", os.getenv("STORAGE_BACKEND", "")) or "").lower()
USE_DB  = bool(os.getenv("DATABASE_URL")) if not BACKEND.startswith("keys") else False

try:
    if BACKEND.startswith(("keys", "legacy")):
        import sys as _sys
        from services import inventory_keys_adapter as _inv_mod
        _sys.modules['services.inventory'] = _inv_mod
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
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
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
# نحاول استيراد بأمان — أي خطأ لا يوقف البوت
def _opt_import(mod_path: str):
    try:
        return import_module(mod_path)
    except ModuleNotFoundError as e:
        logging.debug(f"Module not found: {mod_path} ({e})")
    except Exception as e:
        logging.info(f"[IMPORT] optional module skipped: {mod_path} ({e})")
    return None

# أساسيات
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
from handlers.promoter import router as promoter_router
from handlers.promoter_panel import router as promoter_panel_router
from handlers.anti_groups import router as anti_groups_router
from handlers.bot_panel import router as bot_panel_router
from handlers.home_menu import router as home_menu_router
from handlers.persistent_menu import router as persistent_menu_router
from handlers.menu_buttons import router as menu_buttons_router
from handlers.live_chat import router as live_chat_router
from admin import shop_admin as _shop_admin
from handlers.support_inbox_admin import router as support_inbox_router
from admin.admin_features import router as features_router
from admin import admin_roles_panel as _admin_roles_panel
from middlewares.force_join import ForceJoinMiddleware
from handlers.force_join_check import router as fj_router
from handlers.debug_storage import router as debug_storage_router
from middlewares.seen_user import SeenUserMiddleware
from handlers.promo_free_sevip import router as promo_free_router
from handlers.promo_flow_extras import router as promo_flow_router
from admin.promo_panel_ui import router as promo_panel_ui_router
from admin.admin_center import router as admin_center_router
import admin.live_exclusive_only  # patch فقط
from handlers import setup_handlers

# Rewards
import handlers.rewards_gate as _rewards_gate
import handlers.rewards_hub as _rewards_hub
import handlers.rewards_market as _rewards_market
import handlers.rewards_wallet as _rewards_wallet
import handlers.rewards_compat as _rewards_compat
try:
    from handlers import rewards_profile_pro as _rewards_profile_pro
except Exception:
    _rewards_profile_pro = None

_rewards_market_admin = _opt_import("admin.rewards_market_admin")
_rewards_admin        = _opt_import("admin.rewards_admin")
from admin import admin_hub as _admin_hub

# Alerts (optional) — إصلاح مسار alerts_user
alerts_admin_router = None
alerts_user_router  = None
init_alerts_scheduler = None
try:
    _adm = _opt_import("admin.alerts_admin")
    _usr = _opt_import("handlers.alerts_user")
    _sch = _opt_import("utils.alerts_scheduler")
    alerts_admin_router = getattr(_adm, "router", None) if _adm else None
    alerts_user_router  = getattr(_usr, "router", None) if _usr else None
    init_alerts_scheduler = getattr(_sch, "init_alerts_scheduler", None) if _sch else None
    if alerts_admin_router or alerts_user_router or init_alerts_scheduler:
        logging.info("Alerts modules available.")
except Exception as e:
    logging.warning("FAILED to load alerts modules: %s", e)

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

from middlewares.ephemeral_kb import EphemeralKBGuard

# Payments watcher & helpers
from services.payments import start_auto_watcher  # returns a ready Task
from services import orders as ords
from services.payments import check_and_deliver_one

# ============ General env ============
TOKEN = os.getenv("BOT_TOKEN")
FORCE_START_ON_MSG = int(os.getenv("FORCE_START_ON_MSG", "0"))
UGATE_ON_MSG       = int(os.getenv("UGATE_ON_MSG", "0"))  # compatibility only
WATCHER_SEC        = int(os.getenv("WATCHER_SEC", "12"))
ONLY_REPORT        = os.getenv("ONLY_REPORT", "0") == "1"

# ============ Admin IDs ============
_admin_ids_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS: list[int] = []
for part in _admin_ids_env.split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.append(int(part))
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123, 8371697148]

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
    return _public_cmds(lang) + [BotCommand(command="admin", description=t(lang, "cmd_admin") or "Admin panel")]

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

# ============ Public handlers list ============
_HANDLER_MODULES = [
    "handlers.help",
    "handlers.about",
    "handlers.supplier_vault",
    "handlers.download",
    "handlers.language_handlers",
    "handlers.language",
    "handlers.app_download",
    "handlers.reseller",
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

def _load_public_routers():
    routers = []
    for path in _HANDLER_MODULES:
        r = _try_import_router(path)
        if r:
            routers.append(r)
            logging.info(f"Loaded {path}")
    return routers

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

# ===== include_once + register guard =====
_ROUTERS_REGISTERED = False
_INCLUDED_ROUTERS = set()

def include_once(dp: Dispatcher, router, label: str = ""):
    if router is None:
        return
    rid = id(router)
    if rid in _INCLUDED_ROUTERS:
        return
    try:
        dp.include_router(router)
        _INCLUDED_ROUTERS.add(rid)
        if label:
            logging.info(f"Included: {label}")
    except RuntimeError as e:
        if "already attached" in str(e):
            _INCLUDED_ROUTERS.add(rid)
            logging.warning(f"Skip already-attached router: {label or router!r}")
        else:
            raise

# ====== Rewards mounting (single source of truth) ======
REWARDS_PREFIXES = ("rewards:", "rwd:", "wallet:", "rwm:", "store:", "rwh:", "rw:", "rwp:")
_REWARDS_MOUNTED = False

def _mount_rewards_routers(dp: Dispatcher):
    """ثبت راوترات الجوائز مرة واحدة + فلترة على الخاص وبادئات معيّنة لمنع التضارب."""
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
        include_once(dp, _r, f"rewards:{getattr(_r, 'name', 'router')}")

    if _rewards_profile_pro and hasattr(_rewards_profile_pro, "router"):
        _pin(_rewards_profile_pro.router)
        include_once(dp, _rewards_profile_pro.router, "rewards_profile_pro")

    # الشِم يبقى بدون فلتر البادئات لأنه يستخدم قيم بسيطة مثل "rewards"/"wallet"/"store"
    include_once(dp, rewards_shim, "rewards_shim")

    _REWARDS_MOUNTED = True
    logging.info("Rewards routers mounted (priority + prefix filters applied).")

# ===== Middlewares =====
from aiogram.types import CallbackQuery  # used by some handlers

class StarsPayMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            msg = getattr(event, "message", None) or event
            sp = getattr(msg, "successful_payment", None)
            if sp:
                payload = (sp.invoice_payload or "")
                if payload.startswith("stars:"):
                    oid = int(payload.split(":", 1)[1])
                    logging.info("[PAY⭐][MW] caught successful_payment payload=%s", payload)
                    try:
                        await ords.mark_paid(oid)
                    except Exception as e:
                        logging.exception("mark_paid failed: %r", e)
                    try:
                        await check_and_deliver_one(data["bot"], oid, notify_user=True)
                    except Exception as e:
                        logging.exception("deliver failed: %r", e)
                    return
        except Exception as e:
            logging.exception("StarsPayMiddleware error: %r", e)

        return await handler(event, data)

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

def register_routers(dp: Dispatcher):
    global _ROUTERS_REGISTERED
    if _ROUTERS_REGISTERED:
        logging.warning("register_routers called again — skipping.")
        return

    # ONLY_REPORT mode
    if ONLY_REPORT:
        include_once(dp, report_router, "report_only")
        logging.warning("🚧 ONLY_REPORT=1 — Report router only (no middlewares).")
        _ROUTERS_REGISTERED = True
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
    include_once(dp, compat_router, "compat_router")
    include_once(dp, diag_router, "diag_router")
    logging.info("Loaded diag_router (debug_storage/migrate/inv_diag/inv_repair)")

    dp.message.middleware(mmw); dp.callback_query.middleware(mmw)
    dp.message.middleware(utm); dp.callback_query.middleware(utm)

    autosub = AutoSubscribeMiddleware()
    dp.message.middleware(autosub); dp.callback_query.middleware(autosub)

    # Private only
    dp.message.filter(F.chat.type == "private")
    dp.callback_query.filter(F.message.chat.type == "private")

    # Hook سريع للأقسام (إن وجِد)
    sections_fast = Router(name="sections_fast")
    sections_fast.message.filter(F.chat.type == "private")
    include_once(dp, sections_fast, "sections_fast")

    if FORCE_START_ON_MSG:
        dp.message.middleware(fs)
    dp.callback_query.middleware(fs)

    # ثبّت t داخل start (لو احتج)
    try:
        h_start.t = t
    except Exception:
        pass

    # Rewards — مصدر الحقيقة الواحد
    _mount_rewards_routers(dp)

    # امنع راوترات نصية من ابتلاع الأوامر
    try:
        home_menu_router.message.filter(~F.text.startswith("/"))
        bot_panel_router.message.filter(~F.text.startswith("/"))
        menu_buttons_router.message.filter(~F.text.startswith("/"))
    except Exception:
        pass

    # Alerts (اختياري)
    include_once(dp, alerts_admin_router, "alerts_admin")
    include_once(dp, alerts_user_router,  "alerts_user")

    # Admin roles panel
    include_once(dp, _admin_roles_panel.router, "admin_roles_panel")

    # Shop + أساسيات الواجهة
    include_once(dp, _shop.router, "shop")
    include_once(dp, home_menu_router, "home_menu")
    include_once(dp, supplier_directory_router, "supplier_directory")

    # Start & hero & hub
    include_once(dp, live_chat_router, "live_chat")
    include_once(dp, h_start.router, "start")
    include_once(dp, home_hero_router, "home_hero")
    include_once(dp, _admin_hub.router, "admin_hub")

    # Report أولويته عالية
    include_once(dp, report_router, "report")

    # Menus & panel
    include_once(dp, reseller_apply_router, "reseller_apply")
    include_once(dp, promoter_router, "promoter")
    include_once(dp, promoter_panel_router, "promoter_panel")
    include_once(dp, bot_panel_router, "bot_panel")
    include_once(dp, menu_buttons_router, "menu_buttons")
    include_once(dp, persistent_menu_router, "persistent_menu")
    include_once(dp, support_inbox_router, "support_inbox_admin")
    include_once(dp, _shop_admin.router, "shop_admin")

    # تقييد live_chat على الخاص وعدم التقاط الأوامر
    try:
        live_chat_router.message.filter(F.chat.type == "private")
        live_chat_router.callback_query.filter(F.message.chat.type == "private")
        live_chat_router.message.filter((~F.text.startswith("/")) | F.text.in_({"/live_on", "/live_off"}))
    except Exception:
        pass

    # Anti-groups
    include_once(dp, anti_groups_router, "anti_groups")

    # Core
    include_once(dp, _supplier_payment.router, "supplier_payment")
    from handlers import paydiag as _paydiag
    include_once(dp, _paydiag.router, "paydiag")
    include_once(dp, human_router, "human_check")
    include_once(dp, inventory_admin_router, "inventory_admin")
    dp.message.outer_middleware(StarsPayMiddleware())
    include_once(dp, features_router, "features_router")

    dp.message.outer_middleware(ForceJoinMiddleware())
    dp.callback_query.outer_middleware(ForceJoinMiddleware())
    include_once(dp, fj_router, "force_join_check")
    include_once(dp, debug_storage_router, "debug_storage")
    dp.update.middleware(SeenUserMiddleware())

    include_once(dp, promo_free_router, "promo_free")
    include_once(dp, promo_flow_router, "promo_flow")

    include_once(dp, admin_center_router, "admin_center")
    include_once(dp, promo_panel_ui_router, "promo_panel_ui")
    setup_handlers(dp)

    # Admin extras
    include_once(dp, admin_manage, "admin_manage")
    include_once(dp, admin_access, "admin_access")

    # rewards_admin (اختياري) أو الشِم
    if _rewards_admin and hasattr(_rewards_admin, "router"):
        include_once(dp, _rewards_admin.router, "rewards_admin")
    else:
        include_once(dp, rwdadm_shim, "rwdadm_shim")

    # Additional admin routers
    for r in _import_admin_routers():
        include_once(dp, r, f"extra_admin:{getattr(r, 'name', id(r))}")

    # Tools router (optional)
    if TOOLS_ROUTER:
        include_once(dp, TOOLS_ROUTER, "tools_router")

    # Public routers
    for r in _load_public_routers():
        include_once(dp, r, f"public:{getattr(r, 'name', id(r))}")

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

    include_once(dp, fallback, "fallback_public")
    logging.info("Loaded fallback_public (safety commands).")
    _ROUTERS_REGISTERED = True

async def main():
    if not TOKEN:
        raise RuntimeError("❌ BOT_TOKEN غير موجود في متغيرات البيئة (.env)")

    bot = _make_bot()
    dp  = Dispatcher(storage=_make_storage())

    me = await bot.get_me()
    logging.info(f"🤖 Logged in as @{me.username} (id={me.id})")

    # CryptoPay watcher (best effort)
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
    from utils.vip_cron import run_vip_cron
    try:
        asyncio.create_task(run_vip_cron(bot))
        logging.info("⏰ VIP reminder task started.")
    except Exception as e:
        logging.warning(f"VIP reminder task failed to start: {e}")

    logging.info("🚀 Bot is starting polling...")
    logging.info("Loaded handlers.promo_flow_extras")
    logging.info("Loaded handlers.promo_free_sevip")
    updates = set(dp.resolve_used_update_types() or [])
    updates.update({"message", "callback_query", "pre_checkout_query"})  # Telegram Stars
    updates.update({"chat_member", "my_chat_member"})
    logging.warning(f"[UPDATES] allowed_updates = {sorted(updates)}")
    await dp.start_polling(bot, allowed_updates=list(updates))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot stopped.")
