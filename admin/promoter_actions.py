# admin/promoter_actions.py
from __future__ import annotations

import os, json, time
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.enums import ParseMode
from lang import t, get_user_lang

router = Router(name="promoter_actions")

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = DATA_DIR / "promoters.json"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def is_admin(uid: int) -> bool: 
    return uid in ADMIN_IDS

def L(uid: int) -> str: 
    return get_user_lang(uid) or "ar"

def _now() -> int: 
    return int(time.time())

def _load():
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"users": {}, "settings": {"daily_limit": 5}}

def _save(d): 
    STORE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def _tf(lang: str, key: str, fb: str) -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    return fb

async def _notify_user(cb: CallbackQuery, uid: int, text: str):
    try:
        await cb.bot.send_message(uid, text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

def _get_user(d, uid: str):
    u = d.setdefault("users", {}).setdefault(uid, {})
    u.setdefault("status", "pending")
    u.setdefault("submitted_at", _now())
    return u

# ====== أكشن عام ======
async def _finish(cb: CallbackQuery, note_key: str = "common.ok", fb: str = "OK ✅"):
    try:
        await cb.answer(_tf(L(cb.from_user.id), note_key, fb))
    except Exception:
        pass

# === موافقة / رفض / تعليق / معلومات إضافية ===
@router.callback_query(F.data.regexp(r"^prom:adm:(approve|reject|hold|more):\d+$"))
async def action_basic(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "Admins only."), show_alert=True)

    _, _, act, uid = cb.data.split(":")
    d = _load(); u = _get_user(d, uid)

    status_map = {
        "approve": ("approved", "prom.user.approved", "✅ تمت الموافقة على طلبك كمروّج."),
        "reject":  ("rejected", "prom.user.rejected", "❌ تم رفض طلبك."),
        "hold":    ("on_hold",  "prom.user.hold",     "⏸ تم تعليق طلبك مؤقتًا."),
        "more":    ("more_info","prom.user.more",     "✍️ نحتاج معلومات إضافية لطلبك."),
    }
    new_status, user_key, fb = status_map[act]
    u["status"] = new_status
    _save(d)

    await _notify_user(cb, int(uid), _tf(lang, user_key, fb))
    await _finish(cb, "common.done", "Done ✅")

# === منح/إلغاء لقب مروّج ===
@router.callback_query(F.data.regexp(r"^prom:adm:(promote|demote):\d+$"))
async def action_promote(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "Admins only."), show_alert=True)

    _, _, act, uid = cb.data.split(":")
    d = _load(); u = _get_user(d, uid)

    if act == "promote":
        u["is_promoter"] = True
        txt = _tf(lang, "prom.user.promoted", "👑 تم منحك لقب «مروّج» وتم تفعيل لوحة المروّجين.")
    else:
        u["is_promoter"] = False
        txt = _tf(lang, "prom.user.demoted", "🗑 تم إلغاء لقب «مروّج» لديك وتعطيل لوحتك.")
    _save(d)

    await _notify_user(cb, int(uid), txt)
    await _finish(cb, "common.done", "Done ✅")

# === الحظر 1/7/30 يوم ===
@router.callback_query(F.data.regexp(r"^prom:adm:ban(1|7|30):\d+$"))
async def action_ban(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "Admins only."), show_alert=True)

    _, _, ban_s, uid = cb.data.split(":")
    days = int(ban_s.replace("ban",""))
    d = _load(); u = _get_user(d, uid)

    u["banned_until"] = _now() + days*24*3600
    _save(d)

    await _notify_user(
        cb, int(uid),
        _tf(lang, "prom.user.banned_days", f"🚫 تم حظرك لمدة {days} يومًا.").replace("{days}", str(days))
    )
    await _finish(cb, "common.done", "Done ✅")

# === إزالة الحظر ===
@router.callback_query(F.data.regexp(r"^prom:adm:unban:\d+$"))
async def action_unban(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "Admins only."), show_alert=True)

    _, _, _, uid = cb.data.split(":")
    d = _load(); u = _get_user(d, uid)

    u["banned_until"] = 0
    _save(d)

    await _notify_user(cb, int(uid), _tf(lang, "prom.user.unbanned", "♻️ تم إزالة الحظر عن حسابك."))
    await _finish(cb, "common.done", "Done ✅")

# === حذف الطلب ===
@router.callback_query(F.data.regexp(r"^prom:adm:delete:\d+$"))
async def action_delete(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(_tf(lang, "common.admins_only", "Admins only."), show_alert=True)

    _, _, _, uid = cb.data.split(":")
    d = _load()
    d.get("users", {}).pop(uid, None)
    _save(d)

    await _notify_user(cb, int(uid), _tf(lang, "prom.user.deleted", "🗑 تم حذف طلبك."))
    await _finish(cb, "common.done", "Done ✅")
