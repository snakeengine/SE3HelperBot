# bot.py
import asyncio
import os
import logging
from dotenv import load_dotenv

# ⬅️ حمّل متغيرات البيئة أولاً
load_dotenv()

# --- FORCE LOCAL PROJECT ON SYS.PATH (fix for "handlers" name collision) ---
import sys, pathlib
ROOT = pathlib.Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# تشخيص اختياري: اطبع مصدر باكج handlers
try:
    import handlers as _handlers_pkg
    import logging as _hlog
    _hlog.info(f"[IMPORT] handlers package path -> {_handlers_pkg.__file__}")
except Exception:
    pass
# ---------------------------------------------------------------------------


# ✅ تطبيع (توافق) لدالة الترجمة t() لتقبل (lang,key) أو (lang,key,fallback)
import lang as _lang_mod
try:
    _orig_t = _lang_mod.t
except Exception:
    _orig_t = None

def _t_compat(*args, **kwargs):
    """
    يدعم:
      - t(lang, key)
      - t(lang, key, fallback)
    ويمنع الأخطاء ويرجع fallback/نصًا فارغًا عند عدم توفر الترجمة.
    """
    if _orig_t is None:
        if len(args) >= 3:
            return args[2]
        if len(args) >= 2:
            return args[1]
        return ""

    # ✅ صيغة بثلاثة وسائط: (lang, key, fallback)
    if len(args) >= 3:
        lang_code, key, fallback = args[0], args[1], args[2]
        try:
            val = _orig_t(lang_code, key)
        except Exception:
            val = None
        if isinstance(val, str) and val.strip() and val != key:
            return val
        return fallback or key or ""

    # ✅ صيغة بوسيطين: (lang, key)
    try:
        val = _orig_t(*args, **kwargs)
    except Exception:
        return ""
    key = args[1] if len(args) >= 2 else None
    if isinstance(val, str) and val.strip() and (key is None or val != key):
        return val
    return ""

_lang_mod.t = _t_compat
t = _lang_mod.t  # لاستخدامه محليًا

from utils.ensure_files import ensure_required_files
from importlib import import_module
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from handlers import start as h_start
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from handlers.sevip_store import router as sevip_store_router  # <<< أعلى الملف عند الاستيرادات موجود already
from admin.sevip_activation_admin import router as sevip_activation_admin_router
from admin.stars_revenue import router as stars_revenue_admin_router
from handlers.sevip_shop import router as sevip_shop_router            # NEW
from admin.sevip_inventory_admin import router as sevip_inventory_admin_router  # NEW

# ✅ راووترات إجبارية (forced include)
import handlers.supplier_payment as _supplier_payment
from handlers.human_check import router as human_router

# ✅ نظام الجوائز
import handlers.rewards_gate as _rewards_gate
import handlers.rewards_hub as _rewards_hub
import handlers.rewards_market as _rewards_market
import handlers.rewards_wallet as _rewards_wallet
import handlers.rewards_compat as _rewards_compat


# ✅ (اختياري) بروفايل الجوائز الاحترافي — استيراد مرن
try:
    from handlers import rewards_profile_pro as _rewards_profile_pro
except Exception:
    _rewards_profile_pro = None

# ✅ لوحات أدمن (اختياري) — استيراد ديناميكي مع لوج للأخطاء
import logging
from importlib import import_module

def _opt_import(mod_path: str):
    try:
        return import_module(mod_path)
    except Exception as e:
        logging.getLogger(__name__).info(
            f"[IMPORT] optional module skipped: {mod_path} ({e})"
        )
        return None


_rewards_market_admin = _opt_import("admin.rewards_market_admin")
_rewards_admin        = _opt_import("admin.rewards_admin")

# middlewares
from middlewares.force_start import ForceStartMiddleware
from middlewares.user_tracker import UserTrackerMiddleware
from middlewares.maintenance import MaintenanceMiddleware
from middlewares.vip_rate_limit import VipRateLimitMiddleware
from middlewares.unknown_gate import UnknownGateMiddleware
from middlewares.auto_subscribe import AutoSubscribeMiddleware
from handlers.home_hero import router as home_hero_router

# (اختياري) Tracer
try:
    from middlewares.tracer import TracerMiddleware
except Exception:
    TracerMiddleware = None  # fallback

# utils
from utils.vip_cron import run_vip_cron

# ================= [ALERTS] Imports =================
try:
    from admin.alerts_admin import router as alerts_admin_router
    from handlers.alerts_user import router as alerts_user_router
    from utils.alerts_scheduler import init_alerts_scheduler
    _ALERTS_AVAILABLE = True
    logging.info("Alerts modules loaded (admin+user+scheduler).")
except Exception:
    _ALERTS_AVAILABLE = False
    alerts_admin_router = None
    alerts_user_router = None
    init_alerts_scheduler = None
    logging.exception("FAILED to load alerts modules")

# ================= إعدادات عامة =================
TOKEN = os.getenv("BOT_TOKEN")
FORCE_START_ON_MSG = int(os.getenv("FORCE_START_ON_MSG", "0"))
UGATE_ON_MSG = int(os.getenv("UGATE_ON_MSG", "0"))

_admin_ids_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS: list[int] = []
for part in _admin_ids_env.split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.append(int(part))
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

# === logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

if _ALERTS_AVAILABLE:
    logging.info("Alerts modules loaded (admin+user+scheduler).")
else:
    logging.warning("Alerts modules not available (continuing without alerts).")

# ================= أوامر البوت =================
def _public_cmds(lang: str = "en") -> list[BotCommand]:
    return [
        BotCommand(command="start",        description=t(lang, "cmd_start")    or "Start"),
        BotCommand(command="shop",         description=t(lang, "cmd_shop")     or ("SEVIP store" if lang == "en" else "متجر SEVIP")),

        BotCommand(command="sections",     description=t(lang, "cmd_sections") or ("Quick sections" if lang == "en" else "الأقسام السريعة")),
        BotCommand(command="help",         description=t(lang, "cmd_help")     or "Help"),
        BotCommand(command="about",        description=t(lang, "cmd_about")    or "About"),
        BotCommand(command="report",       description=t(lang, "cmd_report")   or "Report a problem"),
        BotCommand(command="language",     description=t(lang, "cmd_language") or "Language"),
        BotCommand(command="rewards",      description=t(lang, "cmd_rewards")  or ("Rewards hub" if lang == "en" else "الجوائز")),
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

# ================= أدوات استيراد مرنة =================
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
    routers = []
    for path in (
        "admin.server_admin",
        "admin.stats",
        "admin.update_editor",
        "admin.ratings_stats",
        "admin.maintenance_control",
        "admin.view_reports",
        "admin.admin_hub",
        "admin.report_inbox",
        "admin.report_admin",
        "admin.vip_manager",
        "admin.promoter_admin",
        "admin.promoters_panel",
        "admin.promoter_actions",
        "admin.live_support_admin",
        "admin.home_ui_admin",
        "admin.quest_admin",
    ):
        r = _try_import_router(path)
        if r:
            routers.append(r)
    if not routers:
        logging.warning("Admin modules not found. Skipping admin routers.")
    return routers

ADMIN_ROUTERS = _import_admin_routers()

# ================= قائمة الهاندلرز العامة =================
_HANDLER_MODULES = [
    "handlers.help",
    "handlers.about",
    "handlers.supplier_vault",
    "handlers.supplier_directory",
    "handlers.download",
    "handlers.language_handlers",
    "handlers.language",
    "handlers.home_menu",
    "handlers.reseller_apply",
    "handlers.promoter",
    "handlers.promoter_panel",
    "handlers.menu_buttons",
    "handlers.report",
    "handlers.vip",
    "handlers.vip_features",
    "handlers.quick_sections",
    "handlers.app_download",
    "handlers.reseller",
    "handlers.live_chat",
    "handlers.bot_panel",
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
    "handlers.persistent_menu",
    "handlers.admin_entry",
    "handlers.whoami",
]

# (اختياري) تشخيص
try:
    import handlers.app_download as _appdl_chk
    import logging as _lg
    _lg.info(f"[CHECK] imported handlers.app_download OK, has router={hasattr(_appdl_chk, 'router')}")
except Exception:
    import logging as _lg
    _lg.exception("[CHECK] FAILED to import handlers.app_download")

def _load_public_routers():
    routers = []
    for path in _HANDLER_MODULES:
        r = _try_import_router(path)
        if r:
            routers.append(r)
            logging.info(f"Loaded {path}")
    return routers

PUBLIC_ROUTERS = _load_public_routers()

# ======== Shims ========
rewards_shim = Router(name="rewards_shim")

@rewards_shim.callback_query(F.data == "rewards")
async def _shim_rewards(cb):
    """
    افتح البروفايل مباشرة إن توفر، وإلا افتح الهَب كفولباك.
    """
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

# ➕ Fallback لزرار rwdadm عند غياب لوحة الجوائز
rwdadm_shim = Router(name="rwdadm_shim")

@rwdadm_shim.callback_query(F.data.startswith("rwdadm:"))
async def _shim_rwdadm(cb):
    if cb.from_user.id in ADMIN_IDS:
        await cb.answer("❗ وحدة إدارة الجوائز غير محمّلة. تحقّق من لوج التشغيل (import admin.rewards_admin).", show_alert=True)
    else:
        await cb.answer("Admins only.", show_alert=True)

# ================= تسجيل الـ Routers & Middlewares =================
def register_routers(dp: Dispatcher):
    if TracerMiddleware:
        dp.update.middleware(TracerMiddleware())

    mmw = MaintenanceMiddleware()
    utm = UserTrackerMiddleware()
    fs  = ForceStartMiddleware()
    vrl = VipRateLimitMiddleware()

    # 1) الصيانة + تتبع المستخدمين
    dp.message.middleware(mmw); dp.callback_query.middleware(mmw)
    dp.message.middleware(utm); dp.callback_query.middleware(utm)

    # اجعل الاشتراك تلقائيًا لكل من يتفاعل
    autosub = AutoSubscribeMiddleware()
    dp.message.middleware(autosub); dp.callback_query.middleware(autosub)

    # العمل في الخاص فقط
    dp.message.filter(F.chat.type == "private")
    dp.callback_query.filter(F.message.chat.type == "private")

    # 2) فرض /start
    if FORCE_START_ON_MSG:
        dp.message.middleware(fs)
    dp.callback_query.middleware(fs)

    # 3) بوابة المنع
    ugm = UnknownGateMiddleware(
        block_unknown_messages=False,
        allow_commands=(
            "menu", "home", "sections",
            "start","help","about","report","language","admin","support","livechat",
            "set_app","get_app","app_info","remove_app",
            # ===== Alerts
            "alerts_on","alerts_off","alerts_status",
            "push_update","push_preview","push_schedule","push_stats",
            # ===== Store & Wallet & Rewards
            "rewards","wallet","store","send_points",
             "shop", 
            # أوامر أدمن المتجر
            "orders","sendcode","inv_add","inv_stats",   # ✅ NEW
            # اختصارات إضافية
            "profile","my_rewards","rprofile",
            "revenue",
        ),
        allowed_content_types=("text","photo","video","document","voice","audio","video_note"),
        allow_free_text=True,
        enforce_known_users=False,
        admin_ids=ADMIN_IDS,
        fsm_bypass=True,
        fsm_whitelist=(
            "ApplyStates:name","ApplyStates:country","ApplyStates:channel",
            "ApplyStates:exp","ApplyStates:vol","ApplyStates:pref","ApplyStates:confirm",
            "AdminAsk:waiting_question",
            "PubStates:name","PubStates:country","PubStates:languages",
            "PubStates:contact","PubStates:whatsapp","PubStates:channel","PubStates:bio",
            "report:collect","LiveChat:active","live_chat:active",
            "AppUpload:wait_apk",
            "AlStates:wait_ttl","AlStates:wait_rate","AlStates:wait_quiet",
            "AlStates:wait_maxw","AlStates:wait_actd",
            "VipCustom:wait_days",
        ),
    )
    if UGATE_ON_MSG:
        dp.message.middleware(ugm)
    dp.callback_query.middleware(ugm)

    # 4) قيود VIP
    dp.message.middleware(vrl); dp.callback_query.middleware(vrl)

    # ✅ /start الأساسي
    dp.include_router(h_start.router)
    logging.info("Loaded handlers.start (forced include)")

    # ✅ بطاقة Hero Pro
    dp.include_router(home_hero_router)
    logging.info("Loaded handlers.home_hero")

    # ✅ راووتر الدفع
    dp.include_router(_supplier_payment.router)
    logging.info("Loaded handlers.supplier_payment (forced include)")

    dp.include_router(human_router)
    logging.info("Loaded handlers.human_check")


    # ✅ متجر SEVIP (تضمين صريح)
    dp.include_router(sevip_store_router)
    logging.info("Loaded handlers.sevip_store (explicit include)")
        # ✅ متجر USDT (شاشة الشراء والفواتير)
    dp.include_router(sevip_shop_router)
    logging.info("Loaded handlers.sevip_shop (explicit include)")

    # ✅ أوامر مخزون الأكواد للأدمن (/inv_add /inv_stats)
    dp.include_router(sevip_inventory_admin_router)
    logging.info("Loaded admin.sevip_inventory_admin")


    dp.include_router(sevip_activation_admin_router)
    logging.info("Loaded admin.sevip_activation_admin")

    dp.include_router(stars_revenue_admin_router)
    logging.info("Loaded admin.stars_revenue")

    # ====== نظام الجوائز (الترتيب مهم)
    dp.include_router(_rewards_gate.router)     # بوابة الاشتراك + chat_member
    dp.include_router(_rewards_hub.router)      # الهَب (واجهة)
    dp.include_router(_rewards_market.router)   # المتجر
    dp.include_router(_rewards_wallet.router)   # المحفظة
    dp.include_router(_rewards_compat.router)   # توافق /rewards
    dp.include_router(rewards_shim)             # يمسك callbacks: rewards/wallet/store
    
    # ✅ NEW: بروفايل الجوائز الاحترافية (إن وُجد)
    if _rewards_profile_pro and hasattr(_rewards_profile_pro, "router"):
        dp.include_router(_rewards_profile_pro.router)
        logging.info("Loaded handlers.rewards_profile_pro")

    # ✅ لوحة أدمن الجوائز (إن وُجدت) وإلا فعّل الشِم
    if _rewards_admin and hasattr(_rewards_admin, "router"):
        dp.include_router(_rewards_admin.router)
        logging.info("Loaded admin.rewards_admin")
    else:
        dp.include_router(rwdadm_shim)
        logging.warning("admin.rewards_admin not available -> rwdadm_shim enabled")

    # ✅ لوحة أدمن المتجر (اختياري)
    if _rewards_market_admin and hasattr(_rewards_market_admin, "router"):
        dp.include_router(_rewards_market_admin.router)
        logging.info("Loaded admin.rewards_market_admin")

    # ===== [ALERTS]
    if alerts_user_router:
        dp.include_router(alerts_user_router)
        logging.info("Loaded handlers.alerts_user")
    if alerts_admin_router:
        dp.include_router(alerts_admin_router)
        logging.info("Loaded admin.alerts_admin")

    # بقية الراوترات
    for r in ADMIN_ROUTERS:
        dp.include_router(r)
    if TOOLS_ROUTER:
        dp.include_router(TOOLS_ROUTER)
    for r in PUBLIC_ROUTERS:
        dp.include_router(r)

    # ===== Fallback & Shortcuts
    fallback = Router(name="fallback_public")

    @fallback.message(Command("start"))
    async def _fb_start(msg):
        await msg.answer("👋 أهلاً بك! إذا لم تظهر القائمة، اضغط زر Menu بالأسفل، أو أرسل /sections.")

    @fallback.message(Command("help"))
    async def _fb_help(msg):
        await msg.answer("ℹ️ المساعدة: استخدم الأزرار بالأسفل للتنقل. إن لم تعمل الأوامر، أرسل /start مرة واحدة.")

    @fallback.message(Command("about"))
    async def _fb_about(msg):
        await msg.answer("ℹ️ حول البوت: S.E Support — مساعد الخدمات.\nللمزيد: /help")

    @fallback.message(Command("language"))
    async def _fb_lang(msg):
        await msg.answer("🌐 تغيير اللغة: افتح القائمة السفليّة واختر Language.")

    @fallback.message(Command("sections"))
    async def _fb_sections(msg):
        await msg.answer("📂 الأقسام السريعة: استخدم زر Menu السفلي لعرض الأقسام.")

    # ✅ أمر /rewards يفتح البروفايل مباشرة مع فولباك للهَب
    @fallback.message(Command("rewards"))
    async def _fb_rewards(msg):
        try:
            from handlers.rewards_profile_pro import open_profile
            await open_profile(msg)
        except Exception:
            await _rewards_hub.open_hub(msg)

    @fallback.message(Command("admin"))
    async def _fb_admin(msg):
        if msg.from_user.id in ADMIN_IDS:
            await msg.answer("👑 لوحة الأدمن: إذا لم تظهر الواجهة، جرّب /vipadm أو /admin مرة أخرى.")
        else:
            await msg.answer("هذه الأوامر للمشرفين فقط.")

    dp.include_router(fallback)
    logging.info("Loaded fallback_public (safety commands).")

# ================= [ALERTS] Startup hook =================
async def _alerts_startup(bot: Bot):
    if init_alerts_scheduler:
        try:
            await init_alerts_scheduler(bot)
            logging.info("🔔 Alerts scheduler started.")
        except Exception as e:
            logging.warning(f"Alerts scheduler failed to start: {e}")

# ================= تهيئة جلسة البوت =================
def _make_bot() -> Bot:
    total = float(os.getenv("BOT_HTTP_TOTAL_TIMEOUT", "15"))
    session = AiohttpSession(timeout=total)
    bot = Bot(
        token=TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    return bot

# ================= نقطة التشغيل =================
ensure_required_files()

async def main():
    if not TOKEN:
        raise RuntimeError("❌ BOT_TOKEN غير موجود في ملف .env")

    bot = _make_bot()
    dp = Dispatcher(storage=MemoryStorage())

    # تشخيص: اسم البوت
    try:
        me = await bot.get_me()
        logging.info(f"🤖 Logged in as @{me.username} (id={me.id})")
    except Exception:
        logging.exception("Failed to connect to Telegram (get_me). Check BOT_TOKEN / network.")
        raise

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook deleted (switching to polling).")
    except Exception as e:
        logging.warning(f"delete_webhook failed (continue polling): {e}")

    await set_bot_commands(bot)
    register_routers(dp)
    dp.startup.register(_alerts_startup)

    
    try:
        asyncio.create_task(run_vip_cron(bot))
        logging.info("⏰ VIP reminder task started.")
    except Exception as e:
        logging.warning(f"VIP reminder task failed to start: {e}")

    logging.info("🚀 Bot is starting polling...")
    try:
        # ✅ تأكد من تضمين chat_member ضمن allowed_updates
        updates = dp.resolve_used_update_types()
        if "chat_member" not in updates:
            updates.append("chat_member")
        await dp.start_polling(bot, allowed_updates=updates)
    except Exception:
        logging.exception("Polling crashed with an exception.")
        raise

    try:
        asyncio.create_task(_payments_cron(bot))
        logging.info("🔔 Payments monitor started.")
    except Exception as e:
        logging.warning(f"Payments monitor failed to start: {e}")


# يمرّ كل دقيقة ليتحقق من مدفوعات USDT ويسلّم الأكواد
async def _payments_cron(bot):
    from handlers.sevip_shop import check_payments_and_fulfill
    interval = int(os.getenv("PAYMENTS_POLL_INTERVAL", "60"))
    while True:
        try:
            await check_payments_and_fulfill(bot)
        except Exception:
            logging.exception("payments_cron crashed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot stopped.")  

