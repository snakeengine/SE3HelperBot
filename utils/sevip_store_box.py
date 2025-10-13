from __future__ import annotations

# utils/sevip_store_box.py

import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from .json_box import load_json, save_json

# تخزين موحد على BASE/data
try:
    from utils.paths import BASE
    DATA_DIR = BASE
except Exception:
    DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

INV_FILE = DATA_DIR / "sevip_inventory.json"
PAY_FILE = DATA_DIR / "sevip_invoices.json"

def _init_inv() -> Dict[str, Any]:
    return {"boxes": {"3": [], "10": [], "30": []}}

def inv_load() -> Dict[str, Any]:
    d = load_json(INV_FILE, _init_inv()) or _init_inv()
    d.setdefault("boxes", {"3": [], "10": [], "30": []})
    return d

def inv_save(d: Dict[str, Any]) -> None:
    save_json(INV_FILE, d)

def inv_add_codes(days: int, codes: List[str], note: str = "") -> int:
    d = inv_load()
    box = d["boxes"].setdefault(str(int(days)), [])
    now = int(time.time())
    added = 0
    seen = {str(x.get("code", "")).upper() for x in box}
    for c in codes or []:
        c2 = str(c).strip().upper()
        if not c2 or c2 in seen:
            continue
        box.append({"code": c2, "status": "unused", "created_at": now, "note": note})
        seen.add(c2); added += 1
    inv_save(d)
    return added

def inv_pop_code(days: int) -> Optional[str]:
    d = inv_load()
    box = d["boxes"].get(str(int(days)), [])
    for item in box:
        if item.get("status") == "unused":
            item["status"] = "used"
            item["used_at"] = int(time.time())
            inv_save(d)
            return str(item["code"])
    return None

def inv_stats() -> Dict[int, int]:
    d = inv_load()
    out: Dict[int, int] = {}
    for k, arr in d["boxes"].items():
        unused = sum(1 for x in arr if (x or {}).get("status") == "unused")
        out[int(k)] = int(unused)
    return out

def pay_load() -> Dict[str, Any]:
    return load_json(PAY_FILE, {"pending": {}, "by_uid": {}}) or {"pending": {}, "by_uid": {}}

def pay_save(d: Dict[str, Any]) -> None:
    save_json(PAY_FILE, d)

def pay_add(payment_id: str, uid: int, days: int, amount: float, address: str, currency: str) -> None:
    d = pay_load()
    pid = str(payment_id)
    d["pending"][pid] = {
        "uid": int(uid), "days": int(days), "amount": float(amount),
        "address": str(address), "currency": str(currency), "status": "waiting",
        "created_at": int(time.time())
    }
    d["by_uid"].setdefault(str(int(uid)), []).append(pid)
    pay_save(d)

def pay_update_status(payment_id: str, status: str) -> Optional[Dict[str, Any]]:
    d = pay_load()
    it = d["pending"].get(str(payment_id))
    if not it:
        return None
    it["status"] = str(status)
    pay_save(d)
    return it

def pay_pop(payment_id: str) -> Optional[Dict[str, Any]]:
    d = pay_load()
    pid = str(payment_id)
    it = d["pending"].pop(pid, None)
    if it:
        arr = d["by_uid"].get(str(int(it["uid"])), [])
        if pid in arr:
            arr.remove(pid)
        pay_save(d)
    return it
