from __future__ import annotations

# utils/support_inbox.py

import json, time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

# تخزين موحّد على BASE
try:
    from utils.paths import BASE
    STORE = BASE / "support_inbox.json"
except Exception:
    STORE = Path("data/support_inbox.json")
STORE.parent.mkdir(parents=True, exist_ok=True)

def _load() -> dict:
    if STORE.exists():
        try:
            d = json.loads(STORE.read_text(encoding="utf-8")) or {}
            if isinstance(d, dict):
                d.setdefault("q", {"report": [], "chat": []})
                d.setdefault("assigned", {})
                return d
        except Exception:
            pass
    return {"q": {"report": [], "chat": []}, "assigned": {}}

def _save(d: dict) -> None:
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE)

def _now() -> int: return int(time.time())

def _find_idx(lst: List[dict], uid: int) -> int:
    for i, it in enumerate(lst):
        if int(it.get("uid", 0)) == int(uid):
            return i
    return -1

def enqueue(source: str, uid: int, preview: str = "", *, inc: int = 1) -> dict:
    """أضِف/حدّث تذكرة للمستخدم ضمن الصندوق."""
    src = "report" if source == "report" else "chat"
    d = _load()
    q = d["q"].setdefault(src, [])
    i = _find_idx(q, uid)
    now = _now()
    if i == -1:
        rec = {
            "uid": int(uid), "preview": (preview or "")[:200], "count": max(1, int(inc)),
            "last_ts": now, "assigned_to": None, "open": False
        }
        q.append(rec)
    else:
        rec = q[i]
        rec["count"] = int(rec.get("count", 0)) + max(1, int(inc))
        rec["preview"] = (preview or rec.get("preview", ""))[:200]
        rec["last_ts"] = now
        rec.setdefault("assigned_to", None)
        rec.setdefault("open", False)
        q[i] = rec
    _save(d)
    return rec

def claim_next(admin_id: int, source: str) -> Optional[dict]:
    """يسند أقدم تذكرة غير مأسندة إلى admin_id ويعيدها، أو None إذا لا يوجد."""
    src = "report" if source == "report" else "chat"
    d = _load()
    q = d["q"].setdefault(src, [])
    # غير المُسنَدة أولاً، الأقدم أولاً
    waiting = [r for r in q if r.get("assigned_to") is None]
    waiting.sort(key=lambda r: r.get("last_ts", 0))
    if not waiting:
        return None
    rec = waiting[0]
    rec["assigned_to"] = int(admin_id)
    rec["open"] = True
    _save(d)
    return rec

def list_waiting(source: str, limit: int = 10, offset: int = 0) -> Tuple[int, List[dict]]:
    src = "report" if source == "report" else "chat"
    d = _load()
    q = d["q"].setdefault(src, [])
    waiting = [r for r in q if r.get("assigned_to") is None]
    waiting.sort(key=lambda r: r.get("last_ts", 0))
    total = len(waiting)
    return total, waiting[offset: offset+limit]

def get_counts() -> dict:
    d = _load()
    res = {}
    for src in ("report", "chat"):
        q = d["q"].get(src, [])
        res[src] = {
            "waiting": sum(1 for r in q if r.get("assigned_to") is None),
            "assigned": sum(1 for r in q if r.get("assigned_to") is not None),
            "total": len(q)
        }
    return res

def mark_replied(uid: int, source: str) -> None:
    src = "report" if source == "report" else "chat"
    d = _load(); q = d["q"].setdefault(src, [])
    i = _find_idx(q, uid)
    if i != -1:
        q[i]["count"] = 0
        q[i]["last_ts"] = _now()
    _save(d)

def release(uid: int, source: str) -> None:
    """إرجاع التذكرة لقائمة الانتظار (تخطي)."""
    src = "report" if source == "report" else "chat"
    d = _load(); q = d["q"].setdefault(src, [])
    i = _find_idx(q, uid)
    if i != -1:
        q[i]["assigned_to"] = None
        q[i]["open"] = False
    _save(d)

def close(uid: int, source: str) -> None:
    """إغلاق التذكرة وإزالتها من الصندوق."""
    src = "report" if source == "report" else "chat"
    d = _load(); q = d["q"].setdefault(src, [])
    i = _find_idx(q, uid)
    if i != -1:
        q.pop(i)
    _save(d)
