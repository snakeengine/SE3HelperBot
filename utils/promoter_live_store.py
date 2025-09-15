# utils/promoter_live_store.py
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = DATA_DIR / "promoter_live.json"

def _now() -> int:
    return int(time.time())

def _load() -> Dict[str, Any]:
    if STORE_FILE.exists():
        try:
            d = json.loads(STORE_FILE.read_text("utf-8"))
        except Exception:
            d = {}
    else:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("active", {})     # live_id -> record
    d.setdefault("user_map", {})   # uid(str) -> live_id
    d.setdefault("seq", 0)
    return d

def _save(d: Dict[str, Any]) -> None:
    try:
        STORE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _make_id(d: Dict[str, Any], uid: int) -> str:
    d["seq"] = int(d.get("seq", 0)) + 1
    return f"{int(time.time())}-{uid}-{d['seq']}"

def _purge_expired(d: Dict[str, Any]) -> None:
    """احذف كل البثوث التي انتهت."""
    now = _now()
    to_del = []
    for lid, rec in d["active"].items():
        if int(rec.get("expires_at", 0)) <= now:
            to_del.append(lid)
    for lid in to_del:
        uid = str(d["active"][lid].get("user_id"))
        d["active"].pop(lid, None)
        if d["user_map"].get(uid) == lid:
            d["user_map"].pop(uid, None)
    if to_del:
        _save(d)

def start_live(
    uid: int,
    *,
    platform: str,
    handle: str,
    title: str = "",
    display_name: str = "",
    ttl_hours: float = 1.0,
    platform_name: Optional[str] = None,   # ← جديد: اسم المنصّة عند اختيار "other"
    **_ignore,                              # ← لتجاهل أي مفاتيح إضافية بدون كراش
) -> Dict[str, Any]:
    """يسجّل بثًا جديدًا. المدة من 0.5h حتى 24h."""
    d = _load()
    _purge_expired(d)

    # بث واحد نشط لكل مروّج
    old_id = d["user_map"].get(str(uid))
    if old_id and old_id in d["active"]:
        d["active"].pop(old_id, None)

    # ✅ النطاق المسموح: 0.5h .. 24h
    try:
        hours = float(ttl_hours or 1.0)
    except Exception:
        hours = 1.0
    if hours < 0.5:
        hours = 0.5
    if hours > 24.0:
        hours = 24.0

    started = _now()
    live_id = _make_id(d, uid)
    plat = (platform or "").lower().strip()
    rec: Dict[str, Any] = {
        "id": live_id,
        "user_id": int(uid),
        "platform": plat,
        "handle": (handle or "").strip(),
        "title": (title or "").strip(),
        "display_name": (display_name or "").strip() or f"User {uid}",
        "ttl_h": hours,  # قد تكون عشرية
        "started_at": started,
        "expires_at": started + int(hours * 3600),
    }

    # في حالة "other" خزّن اسم المنصّة المخصّص
    if plat == "other" and platform_name:
        rec["platform_name"] = platform_name
        rec["display_platform"] = platform_name

    d["active"][live_id] = rec
    d["user_map"][str(uid)] = live_id
    _save(d)
    return rec

def end_live(live_id: str) -> Optional[Dict[str, Any]]:
    d = _load()
    _purge_expired(d)
    rec = d["active"].pop(live_id, None)
    if rec:
        uid = str(rec.get("user_id"))
        if d["user_map"].get(uid) == live_id:
            d["user_map"].pop(uid, None)
        _save(d)
        return rec  # ← نعيد بيانات البث لإشعار المروّج
    return None

def get_user_active(uid: int) -> Optional[Dict[str, Any]]:
    d = _load()
    _purge_expired(d)
    lid = d["user_map"].get(str(uid))
    if not lid:
        return None
    return d["active"].get(lid)

def _list_all() -> List[Dict[str, Any]]:
    d = _load()
    _purge_expired(d)
    items = list(d["active"].values())
    items.sort(key=lambda r: int(r.get("started_at", 0)), reverse=True)
    return items

def list_active(platform: Optional[str] = None, page: int = 1, per_page: int = 50) -> Tuple[List[Dict[str, Any]], int, int]:
    items = _list_all()
    if platform and platform != "all":
        p = platform.lower().strip()
        items = [r for r in items if (r.get("platform") or "").lower() == p]
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return items[start:start+per_page], pages, total

def count_active_lives(platform: Optional[str] = None) -> int:
    items = _list_all()
    if platform and platform != "all":
        p = platform.lower().strip()
        items = [r for r in items if (r.get("platform") or "").lower() == p]
    return len(items)
