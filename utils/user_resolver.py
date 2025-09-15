from __future__ import annotations
import json, re
from pathlib import Path
from typing import Optional, Tuple

def _jload(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _norm_username(u: str) -> str:
    u = (u or "").strip()
    if u.startswith("@"):
        u = u[1:]
    return u.replace(" ", "").lower()

_ID_RE  = re.compile(r"^-?\d+$")
_TG_URL = re.compile(r"tg://user\?id=(\-?\d+)")

def _parse_query(q: str) -> Tuple[Optional[int], Optional[str]]:
    q = (q or "").strip()
    if not q: return None, None
    m = _TG_URL.match(q)
    if m:
        try: return int(m.group(1)), None
        except Exception: pass
    if _ID_RE.match(q):
        try: return int(q), None
        except Exception: pass
    uname = _norm_username(q)
    return (None, uname) if uname else (None, None)

def _search_users_json_by_username(uname: str) -> Optional[int]:
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
                u = (v or {}).get("username") or (v or {}).get("user_name") or ""
                if isinstance(u, str) and _norm_username(u) == uname:
                    return int(k)
                uh = (v or {}).get("usernames") or (v or {}).get("names") or []
                if isinstance(uh, list) and any(_norm_username(x) == uname for x in uh if isinstance(x, str)):
                    return int(k)
            except Exception:
                continue
    if isinstance(users, list):
        for row in users:
            try:
                uid = int((row or {}).get("id") or (row or {}).get("uid"))
                u   = (row or {}).get("username") or ""
                if isinstance(u, str) and _norm_username(u) == uname:
                    return uid
            except Exception:
                continue
    return None

def _search_rewards_store_by_username(uname: str) -> Optional[int]:
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

async def resolve_user_id(bot, query: str) -> Optional[int]:
    uid, uname = _parse_query(query)
    if uid:
        return uid
    if uname:
        try:
            chat = await bot.get_chat(f"@{uname}")
            if getattr(chat, "type", "private") == "private":
                return int(chat.id)
        except Exception:
            pass
        uid = _search_users_json_by_username(uname) or _search_rewards_store_by_username(uname)
        if uid:
            return uid
    return None
