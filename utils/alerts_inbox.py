# utils/alerts_inbox.py
from __future__ import annotations

import json, time, threading, os
from pathlib import Path
from typing import List, Dict, Any, Optional

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.paths import BASE  # يحدد مجلد التخزين الدائم (عادةً /data)

# ───────────────── مسارات التخزين الدائمة ─────────────────
ALERTS_DIR: Path = BASE / "alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)

BOX_FILE: Path   = ALERTS_DIR / "alerts_box.json"        # {"alerts":[{"id":..,"en":..,"ar":..,"kind":"..","exp":0}]}
INBOX_FILE: Path = ALERTS_DIR / "alerts_inbox_msg.json"  # {"<uid>": {"mid": 123}}

_LOCK = threading.Lock()

# ───────────────── أدوات I/O ذرّية ─────────────────
def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.{int(time.time()*1000)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        finally:
            raise

def _load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        raw = path.read_text("utf-8")
        return json.loads(raw or "null")
    except Exception:
        return None

def _save(path: Path, data: Any) -> None:
    _atomic_write(path, data)

# ───────────────── منطق الصندوق ─────────────────
def _now() -> int:
    return int(time.time())

def _read_box() -> Dict[str, Any]:
    with _LOCK:
        return _load(BOX_FILE) or {}

def _write_box(d: Dict[str, Any]) -> None:
    with _LOCK:
        _save(BOX_FILE, d)

def _read_inbox_idx() -> Dict[str, Any]:
    with _LOCK:
        return _load(INBOX_FILE) or {}

def _write_inbox_idx(d: Dict[str, Any]) -> None:
    with _LOCK:
        _save(INBOX_FILE, d)

def add_alert_to_box(alert_id: str, en: str, ar: str, kind: str, exp: int = 0) -> None:
    """
    يضيف إشعارًا إلى الصندوق المشترك مع تنظيف المنتهية.
    exp: طابع زمني لانتهاء صلاحية الإشعار (0 = بدون انتهاء).
    """
    d = _read_box()
    arr: List[Dict[str, Any]] = d.get("alerts") or []
    now = _now()
    # نظّف المنتهية
    arr = [a for a in arr if not a.get("exp") or int(a.get("exp", 0)) > now]
    # أضف الجديد
    arr.append({
        "id": str(alert_id),
        "en": str(en or ""),
        "ar": str(ar or ""),
        "kind": str(kind or "general"),
        "exp": int(exp or 0),
        "ts": now,
    })
    # حدّ علوي اختياري لتفادي التضخم
    if len(arr) > 500:
        arr = sorted(arr, key=lambda x: int(x.get("ts", 0)), reverse=True)[:500]
    d["alerts"] = arr
    _write_box(d)

def _active_alerts() -> List[Dict[str, Any]]:
    d = _read_box()
    arr: List[Dict[str, Any]] = d.get("alerts") or []
    now = _now()
    active = [a for a in arr if not a.get("exp") or int(a.get("exp", 0)) > now]
    # أعرض الأحدث أولًا
    active.sort(key=lambda x: int(x.get("ts", 0)), reverse=True)
    return active

def get_alert_by_id(alert_id: str) -> Optional[Dict[str, Any]]:
    for a in _active_alerts():
        if str(a.get("id")) == str(alert_id):
            return a
    return None

async def update_user_inbox_badge(bot: Bot, uid: int) -> None:
    """
    ينشئ/يحدّث رسالة 'صندوق الإشعارات' لكل مستخدم مع عدّاد نشِط.
    • يحاول تحرير الرسالة السابقة إن وُجدت، وإلا يرسل رسالة جديدة.
    """
    active = _active_alerts()
    count = len(active)

    # نص عربي/إنجليزي بسيط (يمكنك ربطه بـ utils.i18n لاحقًا)
    title = "🔔 صندوق الإشعارات"
    body  = f"لديك {count} إشعار نشِط." if count else "لا توجد إشعارات حالية."
    full_text = f"{title}\n\n{body}"

    kb = InlineKeyboardBuilder()
    kb.button(text="فتح الصندوق", callback_data="alerts:open")
    kb.adjust(1)
    markup = kb.as_markup()

    idx = _read_inbox_idx()
    rec = idx.get(str(uid)) or {}
    mid = rec.get("mid")

    if mid:
        try:
            await bot.edit_message_text(
                chat_id=uid,
                message_id=int(mid),
                text=full_text,
                reply_markup=markup
            )
            return
        except Exception:
            # فشل التحرير (قد تكون الرسالة حُذفت أو تغيّر محتواها بشكل غير متوافق)
            pass

    m = await bot.send_message(uid, full_text, reply_markup=markup)
    idx[str(uid)] = {"mid": m.message_id}
    _write_inbox_idx(idx)
