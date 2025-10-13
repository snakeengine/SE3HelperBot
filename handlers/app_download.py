from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/app_download.py


import os, json, datetime, logging, re
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang
from utils.paths import BASE  # âœ… ØªÙˆØÙŠØ¯ Ø§Ù„Ù…Ø³Ø§Ø±Ø§Øª

logging.info("âœ… handlers.app_download loaded")

router = Router()

# ===== Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø¹Ø§Ù…Ø© / ØµÙ„Ø§ØÙŠØ§Øª =====
def _locale(uid: int) -> str:
    return get_user_lang(uid) or "ar"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids() or [7360982123]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ===== Ù…Ù„Ù Ø¨ÙŠØ§Ù†Ø§Øª Ø§Ù„Ø¥ØµØ¯Ø§Ø± (Ù…ÙˆØÙ‘Ø¯ Ù…Ø¹ Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù†) =====
APP_FILE: Path = BASE / "app_latest.json"  # â† Ù†ÙØ³ Ø§Ù„Ù…Ù„Ù Ø§Ù„Ø°ÙŠ ØªØ¹ØªÙ…Ø¯ Ø¹Ù„ÙŠÙ‡ Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù†

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

# ===== Ù†ØµÙˆØµ Ø§Ù„Ø¹Ø±Ø¶ (ØªÙØ³ØªØ®Ø¯Ù… ÙÙŠ Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù†) =====
def _caption(lang: str, rel: dict) -> str:
    return f"{t(lang, 'app.caption.title')}\n{t(lang, 'app.caption.version')}: <b>{rel.get('version','-')}</b>"

def _info_text(lang: str, rel: dict) -> str:
    up_at = rel.get("uploaded_at", "-")
    up_by = rel.get("uploaded_by", "-")
    return (
        f"ðŸ›ˆ <b>{t(lang, 'app.info_title')}</b>\n"
        f"{t(lang, 'app.caption.version')}: <b>{rel.get('version','-')}</b>\n"
        f"ID: <code>{rel.get('file_name','-')}</code>\n"
        f"{t(lang, 'app.info_uploaded_by')}: <code>{up_by}</code>\n"
        f"{t(lang, 'app.info_uploaded_at')}: <code>{up_at}</code>"
    )

# ===== FSM Ù„ØØ§Ù„Ø© Ø§Ù„Ø±ÙØ¹ (ØªØ³ØªØ®Ø¯Ù…Ù‡Ø§ Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù† Ø¹Ù†Ø¯ Ø§Ù„Ø¶ØºØ· Ø¹Ù„Ù‰ Â«Ø±ÙØ¹Â») =====
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
    # 1) Ù…Ù† Ø§Ù„ÙƒØ§Ø¨ØªØ´Ù† Ù„Ùˆ ÙÙŠÙ‡
    if caption:
        m = _ver_re.search(caption.strip())
        if m:
            return m.group(1)
    # 2) Ù…Ù† Ø§Ø³Ù… Ø§Ù„Ù…Ù„Ù
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
    await msg.reply(t(lang, "app.updated_ok") or "âœ… ØªÙ… ØªØØ¯ÙŠØ« Ø§Ù„Ø¥ØµØ¯Ø§Ø±.")

# ===== Ø²Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… (ØªØÙ…ÙŠÙ„ Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ Ù…Ù† Ø£ÙŠ Ù…ÙƒØ§Ù†) =====
@router.callback_query(F.data == "app:download")
async def on_download_app(cb: CallbackQuery):
    lang = _locale(cb.from_user.id)
    rel = _load_release()
    if not rel:
        await cb.answer(t(lang, "app.no_release_short") or "Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø¥ØµØ¯Ø§Ø± Ù…Ø±ÙÙˆØ¹ Ø¨Ø¹Ø¯.", show_alert=True)
        return
    try:
        await cb.message.answer_document(document=rel["file_id"], caption=_caption(lang, rel))
        await cb.answer()
    except Exception as e:
        logging.error(f"[app] send file failed: {e}")
        await cb.answer(t(lang, "app.no_release_short") or "Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø¥ØµØ¯Ø§Ø± Ù…Ø±ÙÙˆØ¹ Ø¨Ø¹Ø¯.", show_alert=True)

# ===== Ø£ÙˆØ§Ù…Ø± Ø¹Ø§Ù…Ø© =====
@router.message(Command("get_app"))
async def get_app_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short") or "Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø¥ØµØ¯Ø§Ø± Ù…Ø±ÙÙˆØ¹ Ø¨Ø¹Ø¯.")
        return
    await msg.answer_document(document=rel["file_id"], caption=_caption(lang, rel))

@router.message(Command("app_info"))
async def app_info_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short") or "Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø¥ØµØ¯Ø§Ø± Ù…Ø±ÙÙˆØ¹ Ø¨Ø¹Ø¯.")
        return
    await msg.reply(_info_text(lang, rel))

# ===== Ø£Ù…Ø± Ø¨Ø¯ÙŠÙ„: /set_app (Ø±Ø¯Ù‘Ù‹Ø§ Ø¹Ù„Ù‰ APK Ø£Ùˆ Ù…Ø¹ Ù†ÙØ³ Ø§Ù„Ø±Ø³Ø§Ù„Ø©) =====
@router.message(Command("set_app"))
async def set_app_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    if not _is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin") or "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·.")
        return
    doc = getattr(msg, "document", None) or (getattr(msg.reply_to_message, "document", None) if msg.reply_to_message else None)
    if not _is_apk(doc):
        await msg.reply(t(lang, "app.reply_with_apk") or "Ø£Ø±Ø³Ù„/Ø§Ø±ÙØ¹ Ù…Ù„Ù APK ÙƒÙ€ Document.")
        return
    await _save_and_ack(msg, lang, doc)

# ===== Ø§Ù„Ø§Ø³ØªÙ„Ø§Ù… Ø£Ø«Ù†Ø§Ø¡ ØØ§Ù„Ø© Ø§Ù„Ø±ÙØ¹ (Ù…Ù† Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù†) =====
@router.message(AppUpload.wait_apk, F.document)
async def recv_apk_in_state(msg: Message, state: FSMContext):
    lang = _locale(msg.from_user.id)
    if not _is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin") or "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·.")
        return
    if not _is_apk(msg.document):
        await msg.reply(t(lang, "app.not_apk") or "Ø§Ù„Ù…Ù„Ù Ù„ÙŠØ³ APK.")
        return
    await _save_and_ack(msg, lang, msg.document)
    try:
        await state.clear()
    except Exception:
        pass

# ===== fallback Ù‚ÙˆÙŠ: Ø£ÙŠ Ø£Ø¯Ù…Ù† ÙŠØ±Ø³Ù„ APK Ù†ØÙØ¸Ù‡ (ØØªÙ‰ Ø¨Ø¯ÙˆÙ† Ø§Ù„ØØ§Ù„Ø©) =====
@router.message(F.document)
async def recv_apk_fallback(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    if not _is_apk(msg.document):
        return
    lang = _locale(msg.from_user.id)
    await _save_and_ack(msg, lang, msg.document)

# ===== ØØ°Ù Ø§Ù„Ø¥ØµØ¯Ø§Ø± Ø§Ù„ØØ§Ù„ÙŠ (ØªÙÙ†ÙÙ‘ÙŽØ° Ø§Ù„Ø£Ø²Ø±Ø§Ø± Ù…Ù† Ù„ÙˆØØ© Ø§Ù„Ø£Ø¯Ù…Ù†) =====
def _rm_confirm_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "app.remove_confirm_yes") or "Ù†Ø¹Ù…", callback_data="app:rm_yes")
    kb.button(text=t(lang, "app.remove_confirm_no")  or "Ù„Ø§",  callback_data="app:rm_no")
    kb.adjust(2)
    return kb.as_markup()

@router.message(Command("remove_app"))
async def remove_app_cmd(msg: Message):
    lang = _locale(msg.from_user.id)
    if not _is_admin(msg.from_user.id):
        await msg.reply(t(lang, "app.only_admin") or "Ù„Ù„Ù…Ø´Ø±ÙÙŠÙ† ÙÙ‚Ø·.")
        return
    rel = _load_release()
    if not rel:
        await msg.reply(t(lang, "app.no_release_short") or "Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø¥ØµØ¯Ø§Ø± Ù…Ø±ÙÙˆØ¹ Ø¨Ø¹Ø¯.")
        return
    await msg.reply(t(lang, "app.remove_confirm") or "ØªØ£ÙƒÙŠØ¯ Ø§Ù„ØØ°ÙØŸ", reply_markup=_rm_confirm_kb(lang))

