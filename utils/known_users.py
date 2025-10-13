# utils/known_users.py
from __future__ import annotations

from pathlib import Path
from typing import List, Set

from utils.json_box import load_json, save_json, update_json

# نحاول استخدام BASE الموحّد لو متاح
try:
    from utils.paths import BASE
except Exception:
    BASE = Path("data").resolve()

USERS_PATH = (BASE / "users.json")

def _normalize(data) -> Set[int]:
    """
    يدعم صيغ قديمة ومتعددة:
      - قائمة أرقام: [123, 456]
      - قاموس مفاتيحه معرفات: {"123": {...}, "456": {...}}
      - قاموس يحتوي users: {"users":[...]}
    ويعيد مجموعة أرقام فريدة.
    """
    out: Set[int] = set()
    try:
        if isinstance(data, dict):
            if "users" in data and isinstance(data["users"], list):
                for v in data["users"]:
                    try:
                        out.add(int(v))
                    except Exception:
                        pass
            else:
                # مفاتيح القاموس تعتبر معرّفات
                for k in data.keys():
                    try:
                        out.add(int(k))
                    except Exception:
                        pass
        elif isinstance(data, list):
            for v in data:
                try:
                    out.add(int(v if not isinstance(v, dict) else v.get("id")))
                except Exception:
                    pass
    except Exception:
        pass
    return out

def _load_set() -> Set[int]:
    raw = load_json(USERS_PATH, default={"users": []})
    s = _normalize(raw)
    return s

def _save_set(s: Set[int]) -> None:
    # نخزّن بصيغة موحّدة حديثة: {"users":[...]} (والشيفرات القديمة التي تبحث عن list/keys مازالت تعمل)
    save_json(USERS_PATH, {"users": sorted(int(x) for x in s)})

def list_known_users() -> List[int]:
    return sorted(_load_set())

def count_known_users() -> int:
    return len(_load_set())

def is_known_user(uid: int) -> bool:
    try:
        uid = int(uid)
    except Exception:
        return False
    return uid in _load_set()

def add_known_user(uid: int) -> bool:
    """
    يضيف المعرف إن لم يكن موجوداً. يُرجع True عند الإضافة الفعلية.
    """
    try:
        uid = int(uid)
    except Exception:
        return False

    def _upd(cur):
        s = _normalize(cur)
        before = len(s)
        s.add(uid)
        return {"users": sorted(s)}, len(s) != before

    # نستخدم update_json ثم نُعيد العلم
    added_flag = {"v": False}
    def _fn(cur):
        s = _normalize(cur)
        before = len(s)
        s.add(uid)
        added_flag["v"] = (len(s) != before)
        return {"users": sorted(s)}
    update_json(USERS_PATH, _fn, default={"users": []})
    return added_flag["v"]

def remove_known_user(uid: int) -> bool:
    """
    يزيل المعرف إن كان موجوداً. يُرجع True عند الإزالة الفعلية.
    """
    try:
        uid = int(uid)
    except Exception:
        return False

    removed_flag = {"v": False}
    def _fn(cur):
        s = _normalize(cur)
        if uid in s:
            s.remove(uid)
            removed_flag["v"] = True
        return {"users": sorted(s)}
    update_json(USERS_PATH, _fn, default={"users": []})
    return removed_flag["v"]
