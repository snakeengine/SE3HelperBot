# handlers/app_download.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang

import os
import json
import datetime
import logging

logging.info("✅ handlers.app_download تم تحميله بنجاح")

router = Router()

# ===== لغة المستخدم =====
def get_locale(user_id: int) -> str:
    return get_user_lang(user_id) or "ar"

# ===== إعدادات الأدمن (مطابقة لطريقة bot.py) =====
_admin_ids_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS: list[int] = []
for part in _admin_ids_env.split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.append(int(part))
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ===== ملف بيانات آخر إصدار (داخل data/) =====
APP_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "app_release.json"))

def _load_release() -> dict | None:
    if not os.path.exists(APP_FILE):
        return None
    try:
        with open(APP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"[app_download] فشل قراءة {APP_FILE}: {e}")
        return None

def _save_release(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(APP_FILE), exist_ok=True)
        with open(APP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"[app_download] فشل حفظ {APP_FILE}: {e}")
        raise

def _remove_release() -> bool:
    try:
        if os.path.exists(APP_FILE):
            os.remove(APP_FILE)
            return True
    except Exception as e:
        logging.error(f"[app_download] فشل حذف {APP_FILE}: {e}")
    return False

# ===== كابشن وإظهار معلومات — بدون ملاحظات =====
def _caption(lang: str, rel: dict) -> str:
    return (
        f"{t(lang, 'app.caption.title')}\n"
        f"{t(lang, 'app.caption.version')}: <b>{rel.get('version', '-')}</b>"
    )

def _info_text(lang: str, rel: dict) -> str:
    up_at = rel.get("uploaded_at", "-")
    up_by = rel.get("uploaded_by", "-")
    return (
        f"🛈 <b>{t(lang, 'app.info_title')}</b>\n"
        f"{t(lang, 'app.caption.version')}: <b>{rel.get('version', '-')}</b>\n"
        f"ID: <code>{rel.get('file_name','-')}</code>\n"
        f"{t(lang, 'app.info_uploaded_by')}: <code>{up_by}</code>\n"
        f"{t(lang, 'app.info_uploaded_at')}: <code>{up_at}</code>"
    )

# ===== زر المستخدم: تحميل التطبيق =====
@router.callback_query(F.data == "app:download")
async def on_download_app(cb: CallbackQuery):
    lang = get_locale(cb.from_user.id)
    rel = _load_release()
    if not rel:
        await cb.answer(t(lang, "app.no_release_short"), show_alert=True)
        return
    try:
        await cb.message.answer_document(document=rel["file_id"], caption=_caption(lang, rel))
        await cb.answer()
    except Exception as e:
        logging.error(f"[app_download] إرسال الملف فشل: {e}")
        await cb.answer(t(lang, "app.no_release_short"), show_alert=True)

# ===== أمر الأدمن: رفع/تحديث الـAPK =====
# الاستخدام:
# 1) ردّ على رسالة فيها APK ثم: /set_app v1.2
# 2) أو أرسل APK ومعه الكابتشن: /set_app v1.2
@router.message(Command("set_app"))
async def set_app_cmd(msg: Message):
    lang = get_locale(msg.from_user.id)
    logging.info(f"[app_download] /set_app received, reply={bool(msg.reply_to_message)} doc_here={bool(getattr(msg, 'document', None))} user={msg.from_user.id}")

    if not is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin"))
        return

    # التقط الملف: إما من نفس الرسالة أو من الرسالة المردود عليها
    doc = getattr(msg, "document", None)
    if not doc and msg.reply_to_message and getattr(msg.reply_to_message, "document", None):
        doc = msg.reply_to_message.document

    if not doc:
        await msg.reply(t(lang, "app.reply_with_apk"))
        return

    fname = (doc.file_name or "").lower()
    if not (fname.endswith(".apk") or (doc.mime_type or "").endswith("android.package-archive")):
        await msg.reply(t(lang, "app.not_apk"))
        return

    # استخراج "الإصدار فقط" من النص/الكابتشن
    text = (msg.text or msg.caption or "")
    tokens = text.split()
    version = tokens[1] if len(tokens) >= 2 else "-"

    rel = {
        "file_id": doc.file_id,
        "file_name": doc.file_name,
        "version": version,
        # لم نعد نستخدم note
        "uploaded_by": msg.from_user.id,
        "uploaded_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    try:
        _save_release(rel)
        logging.info(f"✅ [app_download] تم تحديث الإصدار: {version} بواسطة {msg.from_user.id}")
        await msg.reply(t(lang, "app.updated_ok"))
    except Exception as e:
        logging.error(f"[app_download] فشل حفظ الإصدار: {e}")
        await msg.reply(t(lang, "app.no_release_short"))

# ===== أمر عام: إرسال آخر إصدار =====
@router.message(Command("get_app"))
async def get_app_cmd(msg: Message):
    lang = get_locale(msg.from_user.id)
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short"))
        return
    await msg.answer_document(document=rel["file_id"], caption=_caption(lang, rel))

# ===== أمر عام: معلومات الإصدار =====
@router.message(Command("app_info"))
async def app_info_cmd(msg: Message):
    lang = get_locale(msg.from_user.id)
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short"))
        return
    await msg.reply(_info_text(lang, rel))

# ===== أمر الأدمن: حذف الإصدار الحالي (مع تأكيد) =====
def _rm_confirm_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "app.remove_confirm_yes"), callback_data="app:rm_yes")
    kb.button(text=t(lang, "app.remove_confirm_no"),  callback_data="app:rm_no")
    kb.adjust(2)
    return kb.as_markup()

@router.message(Command("remove_app"))
async def remove_app_cmd(msg: Message):
    lang = get_locale(msg.from_user.id)
    if not is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin"))
        return
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short"))
        return
    await msg.reply(t(lang, "app.remove_confirm"), reply_markup=_rm_confirm_kb(lang))

@router.callback_query(F.data == "app:rm_yes")
async def do_remove_app(cb: CallbackQuery):
    lang = get_locale(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        await cb.answer(t(lang, "app.only_admin"), show_alert=True)
        return
    ok = _remove_release()
    try:
        await cb.message.edit_text(
            t(lang, "app.removed_ok") if ok else t(lang, "app.no_release_short")
        )
    except Exception:
        await cb.message.answer(t(lang, "app.removed_ok") if ok else t(lang, "app.no_release_short"))
    await cb.answer()

@router.callback_query(F.data == "app:rm_no")
async def cancel_remove_app(cb: CallbackQuery):
    lang = get_locale(cb.from_user.id)
    try:
        await cb.message.edit_text(t(lang, "app.remove_canceled"))
    except Exception:
        await cb.message.answer(t(lang, "app.remove_canceled"))
    await cb.answer()
