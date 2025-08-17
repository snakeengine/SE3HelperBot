# utils/suppliers.py
from __future__ import annotations

import os, json
from typing import Set, List

DATA_DIR = "data"
FILE = os.path.join(DATA_DIR, "suppliers.json")
os.makedirs(DATA_DIR, exist_ok=True)

# كاش بسيط داخل العملية لتقليل فتح/قراءة الملف كل مرة
_cache: Set[int] | None = None
_dirty: bool = False

def _load_from_disk() -> Set[int]:
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return set()

    # نتأكد أنها أرقام صحيحة
    s: Set[int] = set()
    if isinstance(raw, list):
        for v in raw:
            try:
                s.add(int(v))
            except Exception:
                continue
    return s

def _ensure_cache() -> Set[int]:
    global _cache
    if _cache is None:
        _cache = _load_from_disk()
    return _cache

def _save_to_disk(s: Set[int]) -> None:
    # حفظ ذري لتفادي تلف الملف
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, FILE)

def is_supplier(user_id: int) -> bool:
    s = _ensure_cache()
    return int(user_id) in s

def set_supplier(user_id: int, value: bool = True) -> None:
    global _dirty
    s = _ensure_cache()
    uid = int(user_id)
    if value:
        if uid not in s:
            s.add(uid)
            _dirty = True
    else:
        if uid in s:
            s.discard(uid)
            _dirty = True
    if _dirty:
        _save_to_disk(s)
        _dirty = False

# دوال مساعدة اختيارية
def list_suppliers() -> List[int]:
    """قائمة مرتبة بكل المورّدين."""
    return sorted(_ensure_cache())

def count_suppliers() -> int:
    return len(_ensure_cache())
