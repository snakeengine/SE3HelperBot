# handlers/report_feedback.py
from __future__ import annotations
import os, json
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery
from lang import t, get_user_lang

router = Router(name="report_feedback")

DATA = Path("data"); DATA.mkdir(parents=True, exist_ok=True)
BOX_FILE = DATA / "reports_inbox.json"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def L(uid:int)->str: return get_user_lang(uid) or "ar"

def _load():
    try:
        if BOX_FILE.exists():
            return json.loads(BOX_FILE.read_text("utf-8"))
    except Exception:
        pass
    return {"tickets":[]}

def _save(d): BOX_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")

def _find(d, tid:int):
    for tk in d["tickets"]:
        if tk.get("id")==tid: return tk
    return None

async def _notify_admins(cb: CallbackQuery, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await cb.bot.send_message(admin_id, text)
        except Exception:
            pass

@router.callback_query(F.data.regexp(r"^rfb:(yes|no|skip):(\d+)$"))
async def rfb_handle(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    act, tid = cb.data.split(":")[1], int(cb.data.split(":")[2])
    d = _load(); tk = _find(d, tid)
    if not tk or tk.get("user_id") != cb.from_user.id:
        return await cb.answer("…", show_alert=False)

    tk["feedback"] = act
    _save(d)

    if act == "yes":
        await cb.message.edit_text(t(lang, "rfb.thanks_yes"))
        await _notify_admins(cb, f"✅ Feedback (ticket #{tid}): user {cb.from_user.id} confirmed resolved.")
    elif act == "no":
        await cb.message.edit_text(t(lang, "rfb.thanks_no"))
        await _notify_admins(cb, f"❌ Feedback (ticket #{tid}): user {cb.from_user.id} says NOT resolved.")
    else:
        await cb.message.edit_text(t(lang, "rfb.thanks_skip"))
        await _notify_admins(cb, f"ℹ️ Feedback (ticket #{tid}): user {cb.from_user.id} skipped.")
    await cb.answer("OK")
