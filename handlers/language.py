# 📁 handlers/language.py
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeChat
)
from aiogram.filters import Command
from lang import t, get_user_lang
from typing import List
import json, os

router = Router()

# ===== إعدادات اللغات =====
SUPPORTED_LOCALES = ("en", "ar")
DEFAULT_LOCALE = "en"

# ===== تحميل قائمة الأدمن من .env =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]  # عدّلها حسبك

# ===== تخزين لغة المستخدم (atomic write) =====
USER_LANG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "user_langs.json")
)
os.makedirs(os.path.dirname(USER_LANG_FILE), exist_ok=True)

def _safe_load_langs() -> dict:
    try:
        with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def set_user_lang(user_id: int, lang_code: str) -> None:
    if lang_code not in SUPPORTED_LOCALES:
        lang_code = DEFAULT_LOCALE
    data = _safe_load_langs()
    data[str(user_id)] = lang_code
    tmp = USER_LANG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USER_LANG_FILE)

# ===== أوامر البوت حسب اللغة =====
def _public_commands(lang: str) -> List[BotCommand]:
    """الأوامر العامة للمستخدمين (بدون /admin)."""
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    return [
        BotCommand(command="start",    description=t(lang, "cmd_start")),
        BotCommand(command="help",     description=t(lang, "cmd_help")),
        BotCommand(command="about",    description=t(lang, "cmd_about")),
        BotCommand(command="report",   description=t(lang, "cmd_report")),
        BotCommand(command="language", description=t(lang, "cmd_language")),
    ]

def _admin_extra_commands(lang: str) -> List[BotCommand]:
    """أوامر إضافية تظهر فقط للأدمن."""
    lang = lang if lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    return [
        BotCommand(command="admin", description=t(lang, "cmd_admin_center")),
    ]

async def update_user_commands(bot, chat_id: int, lang: str) -> None:
    """
    يضبط أوامر هذه الدردشة فقط:
      - مستخدم عادي: أوامر عامة
      - أدمن: أوامر عامة + /admin
    """
    is_admin = int(chat_id) in ADMIN_IDS
    cmds = _public_commands(lang)
    if is_admin:
        cmds += _admin_extra_commands(lang)

    # امسح أوامر هذه المحادثة ثم اضبطها
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:
        pass

    await bot.set_my_commands(
        commands=cmds,
        scope=BotCommandScopeChat(chat_id=chat_id)
    )

# ===== لوحات المفاتيح =====
def language_keyboard(display_lang: str, selected_lang: str) -> InlineKeyboardMarkup:
    display_lang = display_lang if display_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    selected_lang = selected_lang if selected_lang in SUPPORTED_LOCALES else DEFAULT_LOCALE

    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if selected_lang == "en" else "") + t(display_lang, "btn_lang_en"),
                callback_data="set_lang_en"
            ),
            InlineKeyboardButton(
                text=("✅ " if selected_lang == "ar" else "") + t(display_lang, "btn_lang_ar"),
                callback_data="set_lang_ar"
            ),
        ],
        [InlineKeyboardButton(text=t(display_lang, "back_to_menu"), callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== الأوامر/الكولباكات =====
@router.message(Command("language"))
async def language_command(message: Message):
    lang = get_user_lang(message.from_user.id) or DEFAULT_LOCALE
    await message.answer(
        t(lang, "choose_language"),
        reply_markup=language_keyboard(display_lang=lang, selected_lang=lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )

@router.callback_query(F.data == "change_lang")
async def change_lang(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id) or DEFAULT_LOCALE
    await callback.message.edit_text(
        t(lang, "choose_language"),
        reply_markup=language_keyboard(display_lang=lang, selected_lang=lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data.in_({"set_lang_en", "set_lang_ar"}))
async def set_language_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_lang = "en" if callback.data.endswith("_en") else "ar"

    set_user_lang(user_id, new_lang)
    await update_user_commands(callback.message.bot, callback.message.chat.id, new_lang)

    await callback.message.edit_text(
        t(new_lang, "language_changed"),
        reply_markup=language_keyboard(display_lang=new_lang, selected_lang=new_lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()
