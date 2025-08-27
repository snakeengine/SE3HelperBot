# utils/alerts_inbox.py
from __future__ import annotations
import time, json
from pathlib import Path
from typing import List, Dict, Any
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
BOX_FILE   = DATA_DIR / "alerts_box.json"     # {"alerts":[{"id":..,"en":..,"ar":..,"kind":"..","exp":0}]}
INBOX_FILE = DATA_DIR / "alerts_inbox_msg.json"  # {"<uid>": {"mid": 123}}

def _load(p: Path) -> Dict[str, Any] | None:
    try: return json.loads(p.read_text("utf-8"))
    except Exception: return None

def _save(p: Path, d: Dict[str, Any]):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def _now() -> int: return int(time.time())

def add_alert_to_box(alert_id: str, en: str, ar: str, kind: str, exp: int = 0):
    d = _load(BOX_FILE) or {}
    arr: List[Dict[str, Any]] = d.get("alerts") or []
    arr = [a for a in arr if not a.get("exp") or a.get("exp") > _now()]  # تنظيف المنتهية
    arr.append({"id": alert_id, "en": en, "ar": ar, "kind": kind, "exp": int(exp or 0)})
    d["alerts"] = arr
    _save(BOX_FILE, d)

def _active_alerts() -> List[Dict[str, Any]]:
    d = _load(BOX_FILE) or {}
    arr: List[Dict[str, Any]] = d.get("alerts") or []
    now = _now()
    return [a for a in arr if not a.get("exp") or a.get("exp") > now]

def get_alert_by_id(alert_id: str) -> Dict[str, Any] | None:
    for a in _active_alerts():
        if a.get("id") == alert_id:
            return a
    return None

async def update_user_inbox_badge(bot: Bot, uid: int):
    """ينشئ/يحدّث رسالة 'صندوق إشعارات' لكل مستخدم مع عدّاد نشِط."""
    active = _active_alerts()
    count = len(active)
    title = "🔔 صندوق الإشعارات"
    body  = f"لديك {count} إشعار نشِط." if count else "لا توجد إشعارات حالية."
    kb = InlineKeyboardBuilder()
    kb.button(text="فتح الصندوق", callback_data="alerts:open")
    kb.adjust(1)

    rec = (_load(INBOX_FILE) or {}).get(str(uid)) or {}
    mid = rec.get("mid")

    if mid:
        try:
            await bot.edit_message_text(body=f"{title}\n\n{body}", chat_id=uid, message_id=mid, reply_markup=kb.as_markup())
            return
        except Exception:
            pass  # سقط التحرير → أعد الإرسال

    m = await bot.send_message(uid, f"{title}\n\n{body}", reply_markup=kb.as_markup())
    store = _load(INBOX_FILE) or {}
    store[str(uid)] = {"mid": m.message_id}
    _save(INBOX_FILE, store)
