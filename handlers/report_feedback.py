# handlers/report_feedback.py
from __future__ import annotations

import os, json, time, tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router(name="report_feedback")

# ✅ قَيِّد هذا الراوتر على بادئة rfb: فقط لتجنّب أي تضارب
router.callback_query.filter(lambda cq: (cq.data or "").startswith("rfb:"))

# ========= المسارات والبيانات =========
DATA = Path("data"); DATA.mkdir(parents=True, exist_ok=True)
BOX_FILE = DATA / "reports_inbox.json"

# ========= إعدادات الأدمن =========
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def L(uid: int) -> str:
    # اللغة الافتراضية: ar إذا لم تتوفر
    return get_user_lang(uid) or "ar"

def _tf(lang: str, key: str, fallback: str) -> str:
    """ترجمة مع fallback آمن."""
    try:
        txt = t(lang, key)
        if isinstance(txt, str) and txt.strip():
            return txt
    except Exception:
        pass
    return fallback

def _default_data() -> Dict[str, Any]:
    return {"tickets": []}

def _load() -> Dict[str, Any]:
    try:
        if BOX_FILE.exists():
            return json.loads(BOX_FILE.read_text("utf-8")) or _default_data()
    except Exception:
        pass
    return _default_data()

def _save(d: Dict[str, Any]) -> None:
    """حفظ ذري (atomic) لتفادي تلف الملف."""
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(BOX_FILE.parent), encoding="utf-8") as tmp:
            json.dump(d, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp.name, BOX_FILE)
    except Exception:
        # في حال فشل الحفظ الذري، نحاول الحفظ المباشر كحل أخير
        BOX_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def _find(d: Dict[str, Any], tid: int) -> Optional[Dict[str, Any]]:
    for tk in d.get("tickets", []):
        if tk.get("id") == tid:
            return tk
    return None

async def _notify_admins(cb: CallbackQuery, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await cb.bot.send_message(admin_id, text)
        except Exception:
            pass

@router.callback_query(F.data.regexp(r"^rfb:(yes|no|skip):(\d+)$"))
async def rfb_handle(cb: CallbackQuery):
    lang = L(cb.from_user.id)

    # ===== تحليل الحمولة =====
    try:
        _, act, tid_s = (cb.data or "").split(":")
        tid = int(tid_s)
    except Exception:
        return await cb.answer(_tf(lang, "common.bad_payload", "Bad request."), show_alert=True)

    # ===== جلب التكت والتحقق من المالك =====
    d = _load()
    tk = _find(d, tid)
    if not tk:
        return await cb.answer(_tf(lang, "common.not_found", "Not found."), show_alert=True)
    if tk.get("user_id") != cb.from_user.id:
        return await cb.answer(_tf(lang, "rfb.err.not_yours", "This survey isn't for you."), show_alert=True)

    # ===== idempotency: لا تعيد التسجيل نفسه =====
    if tk.get("feedback") == act:
        return await cb.answer(_tf(lang, "rfb.already_done", "Already recorded ✅"))

    # ===== تحديث الحالة وحفظ =====
    tk["feedback"] = act
    tk["feedback_at"] = int(time.time())
    _save(d)

    # ===== نص الشكر للمستخدم =====
    if act == "yes":
        user_msg = _tf(lang, "rfb.thanks_yes", "Thanks! We'll mark your ticket as resolved ✅")
        admin_note = f"✅ Feedback (ticket #{tid}): user {cb.from_user.id} confirmed resolved."
    elif act == "no":
        user_msg = _tf(lang, "rfb.thanks_no", "Thanks! We'll take another look ❌")
        admin_note = f"❌ Feedback (ticket #{tid}): user {cb.from_user.id} says NOT resolved."
    else:
        user_msg = _tf(lang, "rfb.thanks_skip", "Got it — skipped for now.")
        admin_note = f"ℹ️ Feedback (ticket #{tid}): user {cb.from_user.id} skipped."

    # ===== تعديل الرسالة الأصلية/إزالة الأزرار بأمان =====
    try:
        if cb.message and (cb.message.text is not None):
            await cb.message.edit_text(user_msg)
        elif cb.message and (cb.message.caption is not None):
            await cb.message.edit_caption(user_msg)
    except TelegramBadRequest:
        # لو لا يمكن التعديل (قد تكون عُدّلت سابقًا)، أرسل رسالة جديدة
        try:
            await cb.message.answer(user_msg)
        except Exception:
            pass

    # إزالة الكيبورد إن وُجد
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # ===== إخطار الأدمن =====
    await _notify_admins(cb, admin_note)

    # ===== إشعار سريع للمستخدم =====
    await cb.answer(_tf(lang, "rfb.saved", "Saved ✅"))
