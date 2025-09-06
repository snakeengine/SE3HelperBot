# utils/rewards_store.py
from __future__ import annotations

import json, time, os, threading
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

DATA_DIR = Path("data") / "rewards"
DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
ORDERS_FILE = DATA_DIR / "orders.json"
ITEMS_FILE = DATA_DIR / "items.json"  # optional catalog; we provide defaults if missing

_lock = threading.Lock()

def _atomic_write(path: Path, data: Any):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)

def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text() or "null") or default
    except Exception:
        return default

def _now() -> int:
    return int(time.time())

# ===== Users =====
def _load_users() -> Dict[str, Any]:
    return _load(USERS_FILE, {})

def _save_users(store: Dict[str, Any]):
    _atomic_write(USERS_FILE, store)

def ensure_user(uid: int) -> Dict[str, Any]:
    with _lock:
        store = _load_users()
        key = str(uid)
        if key not in store:
            store[key] = {
                "points": 0,
                "blocked": False,
                "created_at": _now(),
                "updated_at": _now(),
                "last_actions": {},    # {action: ts}
                "daily_date": "",      # "YYYY-MM-DD"
                "warns": 0
            }
            _save_users(store)
        return store[key]

def _get_user(uid: int) -> Dict[str, Any]:
    ensure_user(uid)
    store = _load_users()
    return store[str(uid)]

def _put_user(uid: int, data: Dict[str, Any]):
    with _lock:
        store = _load_users()
        store[str(uid)] = data
        store[str(uid)]["updated_at"] = _now()
        _save_users(store)

def get_points(uid: int) -> int:
    return int(_get_user(uid).get("points", 0))

def add_points(uid: int, delta: int, reason: str = "") -> int:
    u = _get_user(uid)
    u["points"] = max(0, int(u.get("points", 0)) + int(delta))
    # optionally append ledger (skip for brevity)
    _put_user(uid, u)
    return u["points"]

def set_blocked(uid: int, blocked: bool):
    u = _get_user(uid)
    u["blocked"] = bool(blocked)
    _put_user(uid, u)

def is_blocked(uid: int) -> bool:
    return bool(_get_user(uid).get("blocked", False))

def mark_warn(uid: int, reason: str = ""):
    u = _get_user(uid)
    u["warns"] = int(u.get("warns", 0)) + 1
    _put_user(uid, u)

# ===== Anti-abuse =====
def can_do(uid: int, action: str, cooldown_sec: int = 5) -> bool:
    u = _get_user(uid)
    last = int(u.get("last_actions", {}).get(action, 0))
    if _now() - last < cooldown_sec:
        return False
    u.setdefault("last_actions", {})[action] = _now()
    _put_user(uid, u)
    return True
# ===== Anti-abuse =====
def can_do(uid: int, action: str, cooldown_sec: int = 5) -> bool:
    u = _get_user(uid)
    last = int(u.get("last_actions", {}).get(action, 0))
    if _now() - last < cooldown_sec:
        return False
    u.setdefault("last_actions", {})[action] = _now()
    _put_user(uid, u)
    return True

# ✅ FIX: add this helper so rewards_hub import works
def mark_action(uid: int, action: str, when: int | None = None) -> bool:
    """
    يسجّل آخر وقت لتنفيذ action معيّن بدون فحص كولداون.
    مفيد للتتبّع اليدوي أو ختم حدث معيّن.
    """
    u = _get_user(uid)
    u.setdefault("last_actions", {})[action] = int(when or _now())
    _put_user(uid, u)
    return True

def daily_claim(uid: int, amount: int = 10) -> Tuple[bool, int]:
    # one claim per calendar day (UTC)
    import datetime as _dt
    u = _get_user(uid)
    today = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    if u.get("daily_date") == today:
        return False, 0
    u["daily_date"] = today
    _put_user(uid, u)
    add_points(uid, amount, reason="daily")
    return True, amount

# ===== Transfers =====
def transfer_points(src: int, dst: int, amount: int) -> Tuple[bool, str]:
    if src == dst:
        return False, "لا يمكنك التحويل لنفسك."
    if amount < 5:
        return False, "الحد الأدنى للتحويل 5 نقاط."
    su = _get_user(src)
    if su.get("points", 0) < amount:
        return False, "رصيدك لا يكفي."
    # very simple anti-abuse: 3 transfers/minute
    if not can_do(src, "tx_rate", cooldown_sec=20):
        return False, "التحويلات متقاربة جدًا."
    ensure_user(dst)
    add_points(src, -amount, reason=f"transfer_to:{dst}")
    add_points(dst, +amount, reason=f"transfer_from:{src}")
    return True, "OK"

# ===== Orders / Items =====
def _load_orders() -> Dict[str, Any]:
    return _load(ORDERS_FILE, {"seq": 1, "orders": []})

def _save_orders(store: Dict[str, Any]):
    _atomic_write(ORDERS_FILE, store)

def list_items() -> List[Dict[str, Any]]:
    # If external catalog exists, load it; else provide defaults
    if ITEMS_FILE.exists():
        try:
            data = json.loads(ITEMS_FILE.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return [
        {"id": "gift10", "title": "هديّة 10 نقاط", "cost": 10},
        {"id": "gift50", "title": "هديّة 50 نقطة", "cost": 50},
        {"id": "vip", "title": "ترقية VIP (رمزية)", "cost": 80},
    ]

def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    for it in list_items():
        if str(it["id"]) == str(item_id):
            return it
    return None

def create_order(uid: int, item_id: str, cost: int, payload: Dict[str, Any]) -> int:
    with _lock:
        store = _load_orders()
        order_id = int(store.get("seq", 1))
        store["seq"] = order_id + 1
        store["orders"].append({
            "id": order_id,
            "uid": uid,
            "item_id": item_id,
            "cost": cost,
            "payload": payload or {},
            "status": "new",
            "created_at": _now()
        })
        _save_orders(store)
        return order_id

def list_orders(uid: int) -> List[Dict[str, Any]]:
    store = _load_orders()
    return [o for o in store.get("orders", []) if int(o.get("uid")) == int(uid)]
