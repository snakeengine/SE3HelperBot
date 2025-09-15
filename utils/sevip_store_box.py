# utils/sevip_store_box.py
from __future__ import annotations
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from utils.json_box import load_json, save_json

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
INV_FILE = DATA_DIR / "sevip_inventory.json"
PAY_FILE = DATA_DIR / "sevip_invoices.json"

# شكل مخزن الأكواد:
# {
#   "boxes": {
#     "3": [{"code":"SE3-....", "status":"unused", "created_at":..., "note":""}, ...],
#     "10":[...],
#     "30":[...]
#   }
# }
def _init_inv() -> Dict[str, Any]:
    return {"boxes": {"3": [], "10": [], "30": []}}

def inv_load() -> Dict[str, Any]:
    return load_json(INV_FILE, _init_inv())

def inv_save(d: Dict[str, Any]) -> None:
    save_json(INV_FILE, d)

def inv_add_codes(days: int, codes: List[str], note: str = "") -> int:
    d = inv_load()
    box = d["boxes"].setdefault(str(days), [])
    now = int(time.time())
    added = 0
    seen = set((c["code"] for c in box))
    for c in codes:
        c2 = c.strip().upper()
        if not c2 or c2 in seen:
            continue
        box.append({"code": c2, "status": "unused", "created_at": now, "note": note})
        seen.add(c2); added += 1
    inv_save(d)
    return added

def inv_pop_code(days: int) -> Optional[str]:
    d = inv_load()
    box = d["boxes"].get(str(days), [])
    for item in box:
        if item.get("status") == "unused":
            item["status"] = "used"
            item["used_at"] = int(time.time())
            inv_save(d)
            return item["code"]
    return None

def inv_stats() -> Dict[str, int]:
    d = inv_load()
    out = {}
    for k, arr in d["boxes"].items():
        unused = sum(1 for x in arr if x.get("status") == "unused")
        out[int(k)] = unused
    return out

# فواتير/مدفوعات قيد المتابعة:
# {
#   "pending": { "payment_id": { "uid":..., "days":..., "amount":..., "currency":"USDT", "address":"...", "status":"waiting", "created_at":... } },
#   "by_uid":  { "123": ["payment_id1", "payment_id2"] }
# }
def pay_load() -> Dict[str, Any]:
    return load_json(PAY_FILE, {"pending": {}, "by_uid": {}})

def pay_save(d: Dict[str, Any]) -> None:
    save_json(PAY_FILE, d)

def pay_add(payment_id: str, uid: int, days: int, amount: float, address: str, currency: str) -> None:
    d = pay_load()
    d["pending"][payment_id] = {
        "uid": uid, "days": days, "amount": float(amount),
        "address": address, "currency": currency, "status": "waiting",
        "created_at": int(time.time())
    }
    d["by_uid"].setdefault(str(uid), []).append(payment_id)
    pay_save(d)

def pay_update_status(payment_id: str, status: str) -> Optional[Dict[str, Any]]:
    d = pay_load()
    item = d["pending"].get(payment_id)
    if not item:
        return None
    item["status"] = status
    pay_save(d)
    return item

def pay_pop(payment_id: str) -> Optional[Dict[str, Any]]:
    d = pay_load()
    item = d["pending"].pop(payment_id, None)
    if item:
        arr = d["by_uid"].get(str(item["uid"]), [])
        if payment_id in arr:
            arr.remove(payment_id)
        pay_save(d)
    return item
