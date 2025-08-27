# bot.py
import asyncio
import os
import logging
from dotenv import load_dotenv

# ⬅️ حمّل متغيرات البيئة أولاً
load_dotenv()

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

# ✅ راووتر الدفع (forced include)
import handlers.supplier_payment as _supplier_payment

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
from lang import t

# ================= [ALERTS] Imports =================
try:
    from admin.alerts_admin import router as alerts_admin_router
    from handlers.alerts_user import router as alerts_user_router
    from utils.alerts_scheduler import init_alerts_scheduler
    _ALERTS_AVAILABLE = True
    logging.info("Alerts modules loaded (admin+user+scheduler).")
except Exception as e:
    _ALERTS_AVAILABLE = False
    alerts_admin_router = None
    alerts_user_router = None
    init_alerts_scheduler = None
    # ⬅️ اطبع الخطأ الحقيقي لمعرفة السبب إن تكرر
    logging.exception("FAILED to load alerts modules")


# ================= إعدادات عامة =================
TOKEN = os.getenv("BOT_TOKEN")

# [ForceStart] تحكم عبر .env (0 = عدم فرض /start على الرسائل)
FORCE_START_ON_MSG = int(os.getenv("FORCE_START_ON_MSG", "0"))
# [UnknownGate] تحكم عبر .env (0 = عدم تطبيق البوابة على الرسائل)
UGATE_ON_MSG = int(os.getenv("UGATE_ON_MSG", "0"))

_admin_ids_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS: list[int] = []
for part in _admin_ids_env.split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.append(int(part))
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

# === logging: إجبار التهيئة حتى لو تم إعداد اللوغ قبلها
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
    # أضفنا /menu و /sections لتسهيل الوصول للأقسام السفلية
    return [
        BotCommand(command="start",    description=t(lang, "cmd_start")    or "Start"),
        BotCommand(command="sections", description=t(lang, "cmd_sections") or ("Quick sections" if lang == "en" else "الأقسام السريعة")),
        BotCommand(command="help",     description=t(lang, "cmd_help")     or "Help"),
        BotCommand(command="about",    description=t(lang, "cmd_about")    or "About"),
        BotCommand(command="report",   description=t(lang, "cmd_report")   or "Report a problem"),
        BotCommand(command="language", description=t(lang, "cmd_language") or "Language"),
        # (اختياري) أظهر أوامر الاشتراك للمستخدمين:
        # BotCommand(command="alerts_on",  description="Enable alerts"),
        # BotCommand(command="alerts_off", description="Disable alerts"),
        # BotCommand(command="alerts_status", description="Alerts status"),
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

    "handlers.menu_buttons",

    "handlers.report",
    "handlers.vip",
    "handlers.vip_features",
    "handlers.quick_sections",

    "handlers.app_download",
    "handlers.reseller",
    "handlers.reseller_apply",
    "handlers.live_chat",
    "handlers.bot_panel",
    "handlers.basic_cmds",
    "handlers.contact",
    "handlers.deviceinfo",
    "handlers.version",
    "handlers.verified_resellers",
    "handlers.trusted_suppliers",

    "handlers.security_status",   # ⬅️ مهم
    "handlers.safe_usage",
    "handlers.deviceinfo_check",
    "handlers.server_status",
    "handlers.promoter",
    "handlers.promoter_panel",
    "handlers.debug_callbacks",

    "handlers.persistent_menu",
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
    # على الكولباكات دائمًا، وعلى الرسائل اختياري عبر .env (افتراضيًا معطّل)
    if FORCE_START_ON_MSG:
        dp.message.middleware(fs)
    dp.callback_query.middleware(fs)

    # 3) بوابة المنع
    ugm = UnknownGateMiddleware(
        block_unknown_messages=False,
        allow_commands=(
            # أوامر الوصول السريع
            "menu", "home", "sections",
            # أوامر أساسية
            "start","help","about","report","language","admin","support","livechat",
            # أوامر التطبيق
            "set_app","get_app","app_info","remove_app",
            # ===== [ALERTS] أوامر الإشعارات والإدارة =====
            "alerts_on","alerts_off","alerts_status",
            "push_update","push_preview","push_schedule","push_stats",
        ),
        allowed_content_types=("text","photo","video","document","voice","audio","video_note"),
        allow_free_text=True,
        enforce_known_users=False,
        admin_ids=ADMIN_IDS,
        fsm_bypass=True,
        fsm_whitelist=(
            # الحالات الموجودة سابقًا
            "ApplyStates:name","ApplyStates:country","ApplyStates:channel",
            "ApplyStates:exp","ApplyStates:vol","ApplyStates:pref","ApplyStates:confirm",
            "AdminAsk:waiting_question",
            "PubStates:name","PubStates:country","PubStates:languages",
            "PubStates:contact","PubStates:whatsapp","PubStates:channel","PubStates:bio",
            "report:collect","LiveChat:active","live_chat:active",
            # ⬇️ الأهم: حالة رفع الـAPK
            "AppUpload:wait_apk",
            "AlStates:wait_ttl",
            "AlStates:wait_rate",
            "AlStates:wait_quiet",
            "AlStates:wait_maxw",
            "AlStates:wait_actd",
        ),
    )
    # نُطبّق UnknownGate على الكولباكات دائمًا، وعلى الرسائل حسب .env (افتراضيًا = معطّل)
    if UGATE_ON_MSG:
        dp.message.middleware(ugm)
    dp.callback_query.middleware(ugm)

    # 4) قيود VIP
    dp.message.middleware(vrl); dp.callback_query.middleware(vrl)

    # ✅ /start الأساسي
    dp.include_router(h_start.router)
    logging.info("Loaded handlers.start (forced include)")

    # ✅ بطاقة Hero Pro (تعامل مع كولباكات hero:*)
    dp.include_router(home_hero_router)
    logging.info("Loaded handlers.home_hero")

    # ✅ راووتر الدفع
    dp.include_router(_supplier_payment.router)
    logging.info("Loaded handlers.supplier_payment (forced include)")

    # ===== [ALERTS] تضمين راووترات الإشعارات إن وُجدت =====
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

    # ===== [FALLBACK] راوتر أمان للرد على الأوامر الأساسية إن فشلت الراوترات الأصلية =====
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
        await msg.answer("🌐 تغيير اللغة: افتح القائمة السفليّة واختر Language (أو أرسل /setlang إن كانت متاحة).")

    @fallback.message(Command("sections"))
    async def _fb_sections(msg):
        await msg.answer("📂 الأقسام السريعة: استخدم زر Menu السفلي لعرض الأقسام.")

    @fallback.message(Command("admin"))
    async def _fb_admin(msg):
        if msg.from_user.id in ADMIN_IDS:
            await msg.answer("👑 لوحة الأدمن: إذا لم تظهر الواجهة، جرّب /vipadm أو /admin مرة أخرى.")
        else:
            await msg.answer("هذه الأوامر للمشرفين فقط.")

    dp.include_router(fallback)
    logging.info("Loaded fallback_public (safety commands).")

# ================= [ALERTS] Startup hook لجدولة الإشعارات =================
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

    # تشخيص: طباعة اسم البوت للتأكد من صحة التوكن والاتصال
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

    # [ALERTS] تسجيل الـ startup hook قبل بدء الـ polling
    dp.startup.register(_alerts_startup)

    try:
        asyncio.create_task(run_vip_cron(bot))
        logging.info("⏰ VIP reminder task started.")
    except Exception as e:
        logging.warning(f"VIP reminder task failed to start: {e}")

    logging.info("🚀 Bot is starting polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception:
        logging.exception("Polling crashed with an exception.")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot stopped.")
