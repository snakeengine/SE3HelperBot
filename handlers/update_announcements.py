# 📁 handlers/update_announcements.py
import os
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from lang import get_user_lang, t
from utils.updates import (
    is_active,
    get_update_text,
    was_user_notified,
    mark_user_notified,
)

DEFAULT_APK_URL = "https://www.mediafire.com/file/gjd3dx7ztdlbtdl/SE_2.0.6.apk/file"

def _valid_http(url: str | None) -> bool:
    return isinstance(url, str) and url.lower().startswith(("http://", "https://"))

def _download_url(lang: str) -> str | None:
    """download_url من الترجمات → من البيئة APK_URL → افتراضي."""
    url = (t(lang, "download_url") or "").strip()
    if not _valid_http(url):
        url = os.getenv("APK_URL", "").strip()
    if not _valid_http(url):
        url = DEFAULT_APK_URL
    return url

def _update_more_url(lang: str) -> str | None:
    """update_more_url من الترجمات → من البيئة UPDATE_MORE_URL."""
    url = (t(lang, "update_more_url") or "").strip()
    if not _valid_http(url):
        url = os.getenv("UPDATE_MORE_URL", "").strip()
    return url if _valid_http(url) else None

def _build_update_keyboard(lang: str) -> InlineKeyboardMarkup | None:
    """
    يبني لوحة أزرار التحديث حسب توفّر الروابط:
    - download_url + btn_download
    - update_more_url + btn_update_details
    """
    buttons: list[list[InlineKeyboardButton]] = []

    dl = _download_url(lang)
    if _valid_http(dl):
        buttons.append([InlineKeyboardButton(text=f"📥 {t(lang, 'btn_download')}", url=dl)])

    more = _update_more_url(lang)
    if _valid_http(more):
        buttons.append([InlineKeyboardButton(text=t(lang, "btn_update_details"), url=more)])

    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

async def send_update_if_needed(message: Message) -> None:
    """
    يرسل إعلان التحديث للمستخدم بلغته مرة واحدة فقط.
    يعتمد utils/updates.py (is_active / get_update_text / was_user_notified / mark_user_notified).
    """
    user_id = message.from_user.id

    # حواجز أمان بسيطة: أي فشل في utils → نتجاهل بدون كسر /start
    try:
        if not is_active():
            return
        if was_user_notified(user_id):
            return
    except Exception:
        return

    lang = get_user_lang(user_id) or "en"

    try:
        # get_update_text يُفترض أنه يملك fallback داخلي للإنجليزية
        text = get_update_text(lang)
    except Exception:
        return

    if not text:
        return

    kb = _build_update_keyboard(lang)

    try:
        await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        # إذا فشل الإرسال لا نعلِّم المستخدم كمُبلَّغ
        return

    # علّم المستخدم كمُبلَّغ فقط بعد نجاح الإرسال
    try:
        mark_user_notified(user_id)
    except Exception:
        # فشل التأشير لا يجب أن يكسر التدفق
        pass
