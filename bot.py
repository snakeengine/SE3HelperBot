# bot.py
import asyncio
import os
import logging
from dotenv import load_dotenv

# ✅ حمّل .env أولاً قبل أي استيراد يعتمد على الإعدادات
load_dotenv()
from middlewares.force_start import ForceStartMiddleware
from importlib import import_module
from middlewares.user_tracker import UserTrackerMiddleware
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from utils.vip_cron import run_vip_cron          # يقرأ إعدادات .env الآن بشكل صحيح
from lang import t
from middlewares.maintenance import MaintenanceMiddleware
from middlewares.vip_rate_limit import VipRateLimitMiddleware


# ====== إعدادات عامة ======
TOKEN = os.getenv("BOT_TOKEN")

# دعم ADMIN_IDS= id1,id2,id3 … مع توافق خلفي لـ ADMIN_ID
_admin_ids_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = []
for part in _admin_ids_env.split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.append(int(part))
# fallback لو ما تم الضبط
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

# ====== أوامر البوت (بدون /admin في المينيو) ======
def _public_cmds() -> list[BotCommand]:
    return [
        BotCommand(command="start",          description=t("en", "cmd_start")),
        BotCommand(command="help",           description=t("en", "cmd_help")),
        BotCommand(command="about",          description=t("en", "cmd_about")),
        BotCommand(command="report",         description=t("en", "cmd_report")),
        BotCommand(command="language",       description=t("en", "cmd_language")),
        # أوصاف مباشرة لتفادي نقص مفتاح الترجمة
        BotCommand(command="setlang",        description="Choose language"),
        BotCommand(command="apply_supplier", description="Apply as supplier"),
    ]

async def set_bot_commands(bot: Bot):
    # القائمة الافتراضية (EN) للجميع
    await bot.set_my_commands(
        _public_cmds(),
        scope=BotCommandScopeDefault(),
        language_code="en",
    )
    # نفس القائمة لدردشات الأدمن (بدون /admin)
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                _public_cmds(),
                scope=BotCommandScopeChat(chat_id=admin_id),
                language_code="en",
            )
        except Exception as e:
            logging.warning(f"Failed set commands for admin {admin_id}: {e}")

# ====== أدوات استيراد مرنة ======
def _try_import_router(mod_path: str):
    """يحاول استيراد module.router ويعيده أو None إن لم يوجد."""
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
        "admin.report_inbox",   # صندوق وارد البلاغات
        "admin.report_admin",   # إعدادات البلاغات (تشغيل/إيقاف/حظر/تبريد)
        "admin.vip_manager",
        "admin.promoter_admin",
        "admin.promoters_panel",
        "admin.promoter_actions",
    ):
        r = _try_import_router(path)
        if r:
            routers.append(r)
    if not routers:
        logging.warning("Admin modules not found. Skipping admin routers.")
    return routers

ADMIN_ROUTERS = _import_admin_routers()

# ====== قائمة الهاندلرز العامة ======
_HANDLER_MODULES = [
    "handlers.promoter_panel",
    "handlers.start",
    "handlers.help",
    "handlers.about",

    "handlers.promoter",


    # 👇 ضع هاندلرات المورد باكراً حتى تأخذ أولوية أعلى
    "handlers.supplier_vault",
    "handlers.supplier_directory",

    "handlers.download",
    "handlers.language_handlers",
    "handlers.language",
    "handlers.contact",
    "handlers.deviceinfo",
    "handlers.version",
    "handlers.reseller",
    "handlers.reseller_apply",
    "handlers.vip",
    "handlers.vip_features",
    "handlers.verified_resellers",
    "handlers.report",
    "handlers.supplier_payment",
    "handlers.admin_supplier_verify",
    "handlers.trusted_suppliers",
    "handlers.app_download",
    "handlers.security_status",
    "handlers.safe_usage",
    "handlers.deviceinfo_check",
    "handlers.server_status",

    # يظل الديبج في النهاية
    "handlers.debug_callbacks",
]
# --- تشخيص تحميل app_download ---
try:
    import handlers.app_download as _appdl_chk
    import logging as _lg
    _lg.info(f"[CHECK] imported handlers.app_download OK, has router={hasattr(_appdl_chk, 'router')}")
except Exception as _e:
    import logging as _lg
    _lg.exception("[CHECK] FAILED to import handlers.app_download")
# --- نهاية التشخيص ---

def _load_public_routers():
    routers = []
    for path in _HANDLER_MODULES:
        r = _try_import_router(path)
        if r:
            routers.append(r)
            logging.info(f"Loaded {path}")
    return routers

PUBLIC_ROUTERS = _load_public_routers()

# ====== تسجيل الـ Routers ======
def register_routers(dp: Dispatcher):
    # ترتيب الوسطاء: الصيانة ثم محدودية VIP ثم تتبع المستخدمين
    dp.message.middleware(ForceStartMiddleware())

    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())

    dp.message.middleware(VipRateLimitMiddleware())
    dp.callback_query.middleware(VipRateLimitMiddleware())

    dp.message.middleware(UserTrackerMiddleware())
    dp.callback_query.middleware(UserTrackerMiddleware())

    for r in ADMIN_ROUTERS:
        dp.include_router(r)

    if TOOLS_ROUTER:
        dp.include_router(TOOLS_ROUTER)

    for r in PUBLIC_ROUTERS:
        dp.include_router(r)

# ====== نقطة التشغيل ======
async def main():
    if not TOKEN:
        raise RuntimeError("❌ BOT_TOKEN غير موجود في ملف .env")

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    await bot.delete_webhook(drop_pending_updates=True)
    await set_bot_commands(bot)
    register_routers(dp)

    # 🔔 تشغيل مهمة تذكير/إنهاء VIP في الخلفية
    try:
        asyncio.create_task(run_vip_cron(bot))
        logging.info("⏰ VIP reminder task started.")
    except Exception as e:
        logging.warning(f"VIP reminder task failed to start: {e}")

    logging.info("🚀 Bot is starting polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot stopped.")
