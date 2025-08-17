# 📁 handlers/tools_handler.py
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import t, get_user_lang

router = Router()

# ==== Callback IDs ====
TOOLS_CB       = "tools"
TOOL_8BALL_CB  = "tool_8ball"
BACK_TO_MENU   = "back_to_menu"
BACK_TO_TOOLS  = "tools"  # نعيد استخدام نفس كولباك الأدوات

DEFAULT_APK_URL = "https://example.com/app-latest.apk"

def _get_download_url(lang: str) -> str:
    """يحاول من الترجمة → من ENV → افتراضي."""
    url = (t(lang, "download_url") or "").strip()
    if not url:
        url = os.getenv("APK_URL", "").strip()
    if not url:
        url = DEFAULT_APK_URL
    return url

# ==== Keyboards/Text ====
def tools_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎱 {t(lang, 'tool_8ball')}", callback_data=TOOL_8BALL_CB)],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_TO_MENU)],
    ])

async def send_tools_menu(user_id: int, send_func):
    lang = get_user_lang(user_id) or "en"
    text = (
        f"🧰 <b>{t(lang, 'tools_title')}</b>\n\n"
        f"<b>✅ {t(lang, 'tools_available')}:</b>\n"
        f"• 🎱 <b>{t(lang, 'tool_8ball')}</b> — {t(lang, 'tools_ready')}\n\n"
        f"<b>🕓 {t(lang, 'tools_coming')}:</b>\n"
        f"• 🟤 {t(lang, 'tool_carrom')}\n"
        f"• 🔥 {t(lang, 'tool_freefire')}\n"
        f"• 🚗 {t(lang, 'tool_carparking')}\n"
        f"• 🔫 {t(lang, 'tool_cod')}\n"
        f"• 🧠 {t(lang, 'tool_ml')}\n"
        f"• 🎮 {t(lang, 'tool_others')}\n\n"
        f"📌 <i>{t(lang, 'tools_tap_hint')}</i>"
    )
    await send_func(text, reply_markup=tools_menu_keyboard(lang), parse_mode="HTML", disable_web_page_preview=True)

# ==== Handlers ====
# زر الأدوات من الواجهة
@router.callback_query(F.data == TOOLS_CB)
async def tools_handler(callback: CallbackQuery):
    await send_tools_menu(callback.from_user.id, callback.message.edit_text)
    await callback.answer()

# أمر /tools (اختياري)
@router.message(Command("tools"))
async def tools_command(message: Message):
    await send_tools_menu(message.from_user.id, message.answer)

# 🎱 أداة 8Ball Pool
def tool_8ball_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = []
    download_url = _get_download_url(lang)
    if download_url.lower().startswith(("http://", "https://")):
        buttons.append([InlineKeyboardButton(text=f"📥 {t(lang, 'btn_download')}", url=download_url)])
    buttons.append([InlineKeyboardButton(text=t(lang, "back_to_tools"), callback_data=BACK_TO_TOOLS)])
    buttons.append([InlineKeyboardButton(text=t(lang, "back_to_menu"),  callback_data=BACK_TO_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data == TOOL_8BALL_CB)
async def tool_8ball_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    await callback.message.edit_text(
        t(lang, "tool_8ball_description"),
        reply_markup=tool_8ball_keyboard(lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()
