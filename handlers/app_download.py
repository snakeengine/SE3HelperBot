# handlers/app_download.py
from __future__ import annotations

import os, json, datetime, logging, re
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang
from utils.paths import BASE  # ✅ توحيد المسارات

logging.info("✅ handlers.app_download loaded")

router = Router()

# ===== إعدادات عامة / صلاحيات =====
def _locale(uid: int) -> str:
    return get_user_lang(uid) or "ar"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()] or [7360982123]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ===== ملف بيانات الإصدار (موحّد مع لوحة الأدمن) =====
APP_FILE: Path = BASE / "app_latest.json"  # ← نفس الملف الذي تعتمد عليه لوحة الأدمن

def _load_release() -> dict | None:
    try:
        if APP_FILE.exists():
            return json.loads(APP_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logging.warning(f"[app] read release failed: {e}")
    return None

def _save_release(data: dict) -> None:
    try:
        APP_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = APP_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, APP_FILE)
    except Exception as e:
        logging.error(f"[app] save release failed: {e}")
        raise

def _remove_release() -> bool:
    try:
        if APP_FILE.exists():
            APP_FILE.unlink()
            return True
    except Exception as e:
        logging.error(f"[app] remove release failed: {e}")
    return False

# ===== نصوص العرض (تُستخدم في لوحة الأدمن) =====
def _caption(lang: str, rel: dict) -> str:
    return f"{t(lang, 'app.caption.title')}\n{t(lang, 'app.caption.version')}: <b>{rel.get('version','-')}</b>"

def _info_text(lang: str, rel: dict) -> str:
    up_at = rel.get("uploaded_at", "-")
    up_by = rel.get("uploaded_by", "-")
    return (
        f"🛈 <b>{t(lang, 'app.info_title')}</b>\n"
        f"{t(lang, 'app.caption.version')}: <b>{rel.get('version','-')}</b>\n"
        f"ID: <code>{rel.get('file_name','-')}</code>\n"
        f"{t(lang, 'app.info_uploaded_by')}: <code>{up_by}</code>\n"
        f"{t(lang, 'app.info_uploaded_at')}: <code>{up_at}</code>"
    )

# ===== FSM لحالة الرفع (تستخدمها لوحة الأدمن عند الضغط على «رفع») =====
class AppUpload(StatesGroup):
    wait_apk = State()

def _is_apk(doc) -> bool:
    if not doc:
        return False
    name = (doc.file_name or "").lower()
    mt   = (doc.mime_type or "").lower()
    return name.endswith(".apk") or mt.endswith("android.package-archive")

_ver_re = re.compile(r"(?:^|[_\-\s])v?(\d+\.\d+(?:\.\d+)*)(?:[_\-\s]|\.apk$|$)", re.I)

def _guess_version(doc_name: str, caption: str | None) -> str:
    # 1) من الكابتشن لو فيه
    if caption:
        m = _ver_re.search(caption.strip())
        if m:
            return m.group(1)
    # 2) من اسم الملف
    m = _ver_re.search((doc_name or "").lower())
    if m:
        return m.group(1)
    return "-"

async def _save_and_ack(msg: Message, lang: str, doc) -> None:
    version = _guess_version(doc.file_name or "", msg.caption)
    rel = {
        "file_id": doc.file_id,
        "file_name": doc.file_name or "app.apk",
        "version": version,
        "uploaded_by": msg.from_user.id,
        "uploaded_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    _save_release(rel)
    logging.info(f"[app] release saved v={version} by {msg.from_user.id}")
    await msg.reply(t(lang, "app.updated_ok") or "✅ تم تحديث الإصدار.")

# ===== زر المستخدم (تحميل التطبيق من أي مكان) =====
@router.callback_query(F.data == "app:download")
async def on_download_app(cb: CallbackQuery):
    lang = _locale(cb.from_user.id)
    rel = _load_release()
    if not rel:
        await cb.answer(t(lang, "app.no_release_short") or "لا يوجد إصدار مرفوع بعد.", show_alert=True)
        return
    try:
        await cb.message.answer_document(document=rel["file_id"], caption=_caption(lang, rel))
        await cb.answer()
    except Exception as e:
        logging.error(f"[app] send file failed: {e}")
        await cb.answer(t(lang, "app.no_release_short") or "لا يوجد إصدار مرفوع بعد.", show_alert=True)

# ===== أوامر عامة =====
@router.message(Command("get_app"))
async def get_app_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short") or "لا يوجد إصدار مرفوع بعد.")
        return
    await msg.answer_document(document=rel["file_id"], caption=_caption(lang, rel))

@router.message(Command("app_info"))
async def app_info_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short") or "لا يوجد إصدار مرفوع بعد.")
        return
    await msg.reply(_info_text(lang, rel))

# ===== أمر بديل: /set_app (ردًّا على APK أو مع نفس الرسالة) =====
@router.message(Command("set_app"))
async def set_app_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    if not _is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin") or "للمشرفين فقط.")
        return
    doc = getattr(msg, "document", None) or (getattr(msg.reply_to_message, "document", None) if msg.reply_to_message else None)
    if not _is_apk(doc):
        await msg.reply(t(lang, "app.reply_with_apk") or "أرسل/ارفع ملف APK كـ Document.")
        return
    await _save_and_ack(msg, lang, doc)

# ===== الاستلام أثناء حالة الرفع (من لوحة الأدمن) =====
@router.message(AppUpload.wait_apk, F.document)
async def recv_apk_in_state(msg: Message, state: FSMContext):
    lang = _locale(msg.from_user.id)
    if not _is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin") or "للمشرفين فقط.")
        return
    if not _is_apk(msg.document):
        await msg.reply(t(lang, "app.not_apk") or "الملف ليس APK.")
        return
    await _save_and_ack(msg, lang, msg.document)
    try:
        await state.clear()
    except Exception:
        pass

# ===== fallback قوي: أي أدمن يرسل APK نحفظه (حتى بدون الحالة) =====
@router.message(F.document)
async def recv_apk_fallback(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    if not _is_apk(msg.document):
        return
    lang = _locale(msg.from_user.id)
    await _save_and_ack(msg, lang, msg.document)

# ===== حذف الإصدار الحالي (تُنفَّذ الأزرار من لوحة الأدمن) =====
def _rm_confirm_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "app.remove_confirm_yes") or "نعم", callback_data="app:rm_yes")
    kb.button(text=t(lang, "app.remove_confirm_no")  or "لا",  callback_data="app:rm_no")
    kb.adjust(2)
    return kb.as_markup()

@router.message(Command("remove_app"))
async def remove_app_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    if not _is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin") or "للمشرفين فقط.")
        return
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short") or "لا يوجد إصدار مرفوع بعد.")
        return
    await msg.reply(t(lang, "app.remove_confirm") or "تأكيد الحذف؟", reply_markup=_rm_confirm_kb(lang))
