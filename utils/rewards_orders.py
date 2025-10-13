from __future__ import annotations
import json, time, os
from pathlib import Path
from typing import Dict, Any, Optional
from utils.paths import BASE  # ← المهم

ORDERS_FILE = (Path(os.getenv("DATA_DIR")) if os.getenv("DATA_DIR") else BASE) / "rewards_orders.json"

# ترحيل من القديم
_OLD = Path("data") / "rewards_orders.json"
try:
    if _OLD.exists() and not ORDERS_FILE.exists():
        ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ORDERS_FILE.write_text(_OLD.read_text(encoding="utf-8"), encoding="utf-8")
except Exception:
    pass


def _load() -> Dict[str, Any]:
    """Load file and migrate 'orders' list -> dict if needed."""
    try:
        if ORDERS_FILE.exists():
            d = json.loads(ORDERS_FILE.read_text(encoding="utf-8") or "{}")
        else:
            d = {}
    except Exception:
        d = {}

    orders = d.get("orders")
    if isinstance(orders, list):
        # 🔧 ترحيل قديم: كان list → نحوله إلى dict مع id مُثبت
        mapping: Dict[str, Any] = {}
        for i, row in enumerate(orders, start=1):
            oid = str(row.get("id") or i)
            row["id"] = int(oid)
            mapping[oid] = row
        d["orders"] = mapping
    elif orders is None:
        d["orders"] = {}

    # ثبّت last_id
    try:
        last_id = int(d.get("last_id", 0))
    except Exception:
        last_id = 0
    try:
        max_existing = max((int(k) for k in d["orders"].keys()), default=0)
    except Exception:
        max_existing = 0
    if last_id < max_existing:
        last_id = max_existing
    d["last_id"] = last_id
    return d

def _save(d: Dict[str, Any]) -> None:
    try:
        ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ORDERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ORDERS_FILE)
    except Exception:
        try:
            ORDERS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

def create_order(uid: int, kind: str, payload: Dict[str, Any]) -> int:
    """
    ينشئ طلب جديد بحالة pending ويعيد رقم الطلب.
    البنية:
    {
      "last_id": 3,
      "orders": { "1": {...}, "2": {...} }
    }
    """
    d = _load()
    oid = int(d.get("last_id", 0)) + 1
    row = {
        "id": oid,
        "uid": int(uid),
        "kind": str(kind),
        "status": "pending",
        "payload": payload or {},
        "ts": time.time(),
        "admin_id": None,
    }
    orders: Dict[str, Any] = d.get("orders") or {}
    if isinstance(orders, list):  # أمان إضافي
        orders = {str(i+1): r for i, r in enumerate(orders)}
    orders[str(oid)] = row
    d["orders"] = orders
    d["last_id"] = oid
    _save(d)
    return oid

def get_order(oid: int | str) -> Optional[Dict[str, Any]]:
    d = _load()
    return (d.get("orders") or {}).get(str(oid))

def set_status(oid: int | str, status: str, admin_id: Optional[int] = None) -> bool:
    d = _load()
    orders: Dict[str, Any] = d.get("orders") or {}
    key = str(oid)
    row = orders.get(key)
    if not row:
        return False
    row["status"] = status
    if admin_id is not None:
        row["admin_id"] = int(admin_id)
    row["ts_status"] = time.time()
    orders[key] = row
    d["orders"] = orders
    _save(d)
    return True

def list_orders(status: Optional[str] = None) -> Dict[str, Any]:
    d = _load()
    orders = d.get("orders") or {}
    if status:
        return {k: v for k, v in orders.items() if v.get("status") == status}
    return orders
