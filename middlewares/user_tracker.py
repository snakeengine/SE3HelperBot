# middlewares/user_tracker.py
from __future__ import annotations
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"

# ---------- Helpers ----------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _ensure_files():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not USERS_FILE.exists():
        USERS_FILE.write_text(json.dumps({"users": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_raw():
    _ensure_files()
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[user_tracker] read error, recreating file: %s", e)
        USERS_FILE.write_text(json.dumps({"users": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"users": {}}

def _normalize(raw) -> dict:
    """
    يُرجع هيكل موحّد: {"users": { "<uid>": {...} }}
    ويحوّل تلقائيًا أي صيغة قديمة كانت List.
    """
    # الحالة 1: ملف عبارة عن List قديم (IDs أو Dicts)
    if isinstance(raw, list):
        users_dict = {}
        for item in raw:
            if isinstance(item, dict):
                uid = item.get("id") or item.get("uid")
                if uid is None:
                    continue
                users_dict[str(uid)] = item
                users_dict[str(uid)]["id"] = uid
            else:
                # عنصر عددي/نصي يمثل ID فقط
                uid = item
                users_dict[str(uid)] = {"id": uid}
        return {"users": users_dict}

    # الحالة 2: Dict حديث ولكن users = List
    if isinstance(raw, dict):
        users = raw.get("users", {})
        if isinstance(users, list):
            users_dict = {}
            for item in users:
                if isinstance(item, dict):
                    uid = item.get("id") or item.get("uid")
                    if uid is None:
                        continue
                    users_dict[str(uid)] = item
                    users_dict[str(uid)]["id"] = uid
                else:
                    uid = item
                    users_dict[str(uid)] = {"id": uid}
            raw["users"] = users_dict
            return raw
        if isinstance(users, dict):
            return {"users": users}
        # users موجود لكنه ليس dict ولا list
        return {"users": {}}

    # أي شكل غير معروف
    return {"users": {}}

def _load() -> dict:
    raw = _load_raw()
    norm = _normalize(raw)
    # لو تغيّر بالشكل أثناء التطبيع، نحفظه
    try:
        if norm != raw:
            _save(norm)
    except Exception:
        pass
    return norm

def _save(data: dict) -> None:
    _ensure_files()
    USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- Public API ----------

def get_users_count() -> int:
    data = _load()
    users = data.get("users", {})
    return len(users) if isinstance(users, dict) else 0

# ---------- Middleware ----------

class UserTrackerMiddleware(BaseMiddleware):
    """
    يلتقط كل رسالة/كولباك لإضافة المستخدم (مرة واحدة) وتحديث آخر نشاط.
    """

    async def __call__(self, handler, event, data):
        try:
            user = None
            if isinstance(event, Message):
                user = event.from_user
            elif isinstance(event, CallbackQuery):
                user = event.from_user

            if user is not None:
                uid = str(user.id)
                first_name = (user.first_name or "").strip()
                last_name  = (user.last_name or "").strip()
                username   = (user.username or "").strip().lower()

                db = _load()
                users = db.setdefault("users", {})
                rec = users.get(uid, {})

                # أول مرة؟
                if not rec:
                    rec = {
                        "id": user.id,
                        "first_seen": _utc_now_iso(),
                    }

                # تحديث معلومات أساسية + آخر نشاط
                rec.update({
                    "first_name": first_name,
                    "last_name": last_name,
                    "username": username,
                    "last_seen": _utc_now_iso(),
                })
                users[uid] = rec
                _save(db)

        except Exception as e:
            logger.warning("[user_tracker] track error: %s", e)

        # تابع السلسلة
        return await handler(event, data)
