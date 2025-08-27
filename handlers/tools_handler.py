# 📁 handlers/tools_handler.py
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router()

# ==== Callback IDs ====
TOOLS_CB       = "tools"
TOOL_8BALL_CB  = "tool_8ball"
BACK_TO_MENU   = "back_to_menu"
BACK_TO_TOOLS  = "tools"

DEFAULT_APK_URL = "https://example.com/app-latest.apk"

def _get_download_url(lang: str) -> str:
    url = (t(lang, "download_url") or "").strip() or os.getenv("APK_URL", "").strip()
    return url or DEFAULT_APK_URL

# ==== helper: تعديل أو إرسال رسالة بأمان ====
async def _safe_edit_or_answer(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = ParseMode.HTML,
    disable_web_page_preview: bool | None = True,
    **_
):
    # منع تمرير نص فارغ إطلاقاً
    if not (text or "").strip():
        text = "…"

    try:
        if message.text is not None:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        if message.caption is not None:
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        # رسالة وسائط بدون نص/كابشن → أرسل جديدة
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        low = str(e).lower()
        if ("no text in the message to edit" in low
            or "message can't be edited" in low
            or "message is not modified" in low):
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        raise

# ==== نص + كيبورد قائمة الأدوات ====
def tools_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎱 {t(lang, 'tool_8ball')}", callback_data=TOOL_8BALL_CB)],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_TO_MENU)],
    ])

def tools_text(lang: str) -> str:
    return (
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

async def send_tools_menu(user_id: int, send_func):
    lang = get_user_lang(user_id) or "en"
    await send_func(
        tools_text(lang),
        reply_markup=tools_menu_keyboard(lang),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

# ==== Handlers ====
@router.callback_query(F.data == TOOLS_CB)
async def tools_handler(callback: CallbackQuery):
    # فقط أرسل/عدّل النص الحقيقي عبر الدالة الآمنة — بدون أي placeholder
    await send_tools_menu(
        callback.from_user.id,
        lambda *a, **kw: _safe_edit_or_answer(callback.message, *a, **kw)
    )
    await callback.answer()

@router.message(Command("tools"))
async def tools_command(message: Message):
    await send_tools_menu(message.from_user.id, message.answer)

# 🎱 8Ball Pool
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
    await _safe_edit_or_answer(
        callback.message,
        t(lang, "tool_8ball_description"),
        tool_8ball_keyboard(lang)
    )
    await callback.answer()
