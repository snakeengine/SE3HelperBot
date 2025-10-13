from __future__ import annotations

# utils_user_resolver.py

import json
import re
from pathlib import Path
from typing import Optional, Tuple

# ---------- JSON helpers ----------
def _jload(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

# ---------- Username normalization ----------
def _norm_username(u: str) -> str:
    u = (u or "").strip()
    if u.startswith("@"):
        u = u[1:]
    return u.replace(" ", "").lower()

# ---------- Patterns ----------
_ID_RE    = re.compile(r"^-?\d+$")
_TG_UID1  = re.compile(r"^tg://user\?id=(-?\d+)$", re.IGNORECASE)
_TG_UID2  = re.compile(r"^tg://openmessage\?user_id=(-?\d+)$", re.IGNORECASE)
_TME_URL  = re.compile(
    r"^(?:https?://)?t\.me/(?P<uname>[A-Za-z0-9_]{3,})/?(?:\?.*)?$",
    re.IGNORECASE,
)

def _parse_query(q: str) -> Tuple[Optional[int], Optional[str]]:
    """
    يُعيد (uid, uname):
      - uid إذا كانت القيمة رقمًا أو tg://user?id=… أو tg://openmessage?user_id=…
      - uname إذا كانت @username أو t.me/username
    """
    q = (q or "").strip()
    if not q:
        return None, None

    m = _TG_UID1.match(q) or _TG_UID2.match(q)
    if m:
        try:
            return int(m.group(1)), None
        except Exception:
            return None, None

    if _ID_RE.match(q):
        try:
            return int(q), None
        except Exception:
            return None, None

    m = _TME_URL.match(q)
    if m:
        uname = _norm_username(m.group("uname"))
        return (None, uname) if uname else (None, None)

    uname = _norm_username(q)
    return (None, uname) if uname else (None, None)

# ---------- Local lookups ----------
def _search_users_json_by_username(uname: str) -> Optional[int]:
    """
    يبحث داخل data/users.json، ويدعم شكلين:
      - dict: { "<uid>": { "username": "...", "usernames":[...], ... }, ... }
      - list: [ { "id": 123, "username":"...", "usernames":[...] }, ... ]
    """
    p = Path("data") / "users.json"
    d = _jload(p)

    users = None
    if isinstance(d, dict):
        users = d.get("users", d)
    elif isinstance(d, list):
        users = d

    if isinstance(users, dict):
        for k, v in users.items():
            try:
                meta = v or {}
                u = meta.get("username") or meta.get("user_name") or ""
                if isinstance(u, str) and _norm_username(u) == uname:
                    return int(k)
                uh = meta.get("usernames") or meta.get("names") or []
                if isinstance(uh, list) and any(_norm_username(x) == uname for x in uh if isinstance(x, str)):
                    return int(k)
            except Exception:
                continue

    if isinstance(users, list):
        for row in users:
            try:
                uid = int((row or {}).get("id") or (row or {}).get("uid"))
                u   = (row or {}).get("username") or (row or {}).get("user_name") or ""
                if isinstance(u, str) and _norm_username(u) == uname:
                    return uid
                uh = (row or {}).get("usernames") or (row or {}).get("names") or []
                if isinstance(uh, list) and any(_norm_username(x) == uname for x in uh if isinstance(x, str)):
                    return uid
            except Exception:
                continue
    return None

def _search_rewards_store_by_username(uname: str) -> Optional[int]:
    """
    يبحث داخل data/rewards_store.json: {"users": { "<uid>": {"username": "..."} } }
    """
    p = Path("data") / "rewards_store.json"
    d = _jload(p)
    users = (d or {}).get("users") or {}
    if isinstance(users, dict):
        for k, v in users.items():
            try:
                u = (v or {}).get("username") or (v or {}).get("user_name") or ""
                if isinstance(u, str) and _norm_username(u) == uname:
                    return int(k)
            except Exception:
                continue
    return None

# ---------- Public resolver ----------
async def resolve_user_id(bot, query: str, *, allow_groups: bool = False) -> Optional[int]:
    """
    يحلّ الاستعلام إلى user_id:
      • يقبل: 12345 | tg://user?id=… | tg://openmessage?user_id=… | https://t.me/username | @username
      • يحاول أولًا عبر bot.get_chat، ثم يسقط على قواعد بيانات محليّة.
    allow_groups:
      • False (افتراضي): يرجّع فقط حسابات خاصّة (type == "private")
      • True: يقبل أي chat.id (قناة/مجموعة/خاص)
    """
    uid, uname = _parse_query(query)

    # حالة uid جاهز
    if uid is not None:
        if allow_groups:
            return uid
        try:
            chat = await bot.get_chat(uid)
            if getattr(chat, "type", "private") == "private":
                return int(chat.id)
            return None
        except Exception:
            # في وضع private-only، لا نثق في ID بلا تحقق
            return None

    # حالة username
    if uname:
        # 1) API
        try:
            # جرّب بدون @ ثم مع @
            for handle in (uname, f"@{uname}"):
                chat = await bot.get_chat(handle)
                ctype = getattr(chat, "type", "private")
                if allow_groups or ctype == "private":
                    return int(chat.id)
        except Exception:
            pass

        # 2) مخازن محليّة
        uid_local = _search_users_json_by_username(uname) or _search_rewards_store_by_username(uname)
        if uid_local:
            if allow_groups:
                return uid_local
            try:
                chat = await bot.get_chat(uid_local)
                if getattr(chat, "type", "private") == "private":
                    return uid_local
            except Exception:
                return None

    return None
