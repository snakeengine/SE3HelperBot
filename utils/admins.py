# utils/admins.py
from __future__ import annotations

import os, json
from pathlib import Path
from typing import Iterable

# مسار ملف تخزين الأدمنز (للقابلية للتعديل أثناء التشغيل)
DATA_DIR = Path(os.getenv("DATA_DIR") or os.getenv("BASE") or "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
ADMINS_FILE = DATA_DIR / "admins.json"

# ---------- أدوات داخلية ----------
def _parse_ids(val: str | Iterable[int] | None) -> list[int]:
    out: list[int] = []
    if val is None:
        return out
    if isinstance(val, str):
        for p in val.replace(";", ",").split(","):
            p = p.strip()
            if p.isdigit():
                out.append(int(p))
        return sorted(set(out))
    try:
        for v in val:  # type: ignore
            if isinstance(v, int):
                out.append(v)
            elif isinstance(v, str) and v.isdigit():
                out.append(int(v))
    except Exception:
        pass
    return sorted(set(out))

def _load_json(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}

def _save_json(p: Path, obj: dict) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass

# ---------- تحميل من البيئة + الملف ----------
_env_admins = _parse_ids(os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID"))
_env_owners = _parse_ids(os.getenv("OWNER_IDS") or os.getenv("OWNER_ID"))

_store = _load_json(ADMINS_FILE)
_file_admins = _parse_ids((_store.get("admins") if isinstance(_store.get("admins"), list) else []))
_file_owners = _parse_ids((_store.get("owners") if isinstance(_store.get("owners"), list) else []))

# اجمع الاثنين (البيئة + الملف)
_all_admins = sorted(set(_env_admins + _file_admins))
_all_owners = sorted(set(_env_owners + _file_owners))

# ---------- واجهة توافقية (متغيّرات) ----------
# ملاحظة: نخليهم "قوائم" لتكون قابلة للتقطيع/العرض بدون أخطاء
ADMIN_IDS: list[int] = _all_admins[:]   # كان set ببعض المشاريع؛ هنا نخليها list لراحة الاستخدام
OWNERS:    list[int] = _all_owners[:]

# لأغراض أداء العضوية (اختياري)
_ADMIN_SET = set(ADMIN_IDS) | set(OWNERS)

# ---------- دوال مطلوبة/قديمة ----------
def get_admin_ids() -> list[int]:
    """قائمة كل الأدمن (تشمل المالكين)."""
    return sorted(set(ADMIN_IDS) | set(OWNERS))

def get_owner_ids() -> list[int]:
    """قائمة المالكين (Owners)."""
    return OWNERS[:]

def is_admin(user_id: int) -> bool:
    """تحقق هل المستخدم أدمن (أو مالك)."""
    try:
        return int(user_id) in _ADMIN_SET
    except Exception:
        return False

def list_admins() -> list[int]:
    """قائمة الأدمن فقط (بدون المالكين)."""
    return ADMIN_IDS[:]

def add_admin(user_id: int) -> bool:
    """أضف أدمن واحفظه في الملف (لا يضيف مالك)."""
    try:
        uid = int(user_id)
    except Exception:
        return False
    if uid in ADMIN_IDS:
        return True
    ADMIN_IDS.append(uid)
    _ADMIN_SET.add(uid)
    _persist()
    return True

def remove_admin(user_id: int) -> bool:
    """احذف أدمن واحفظ التغيير."""
    try:
        uid = int(user_id)
    except Exception:
        return False
    if uid in ADMIN_IDS:
        ADMIN_IDS.remove(uid)
        # لا نحذف من OWNERS هنا
        if uid in _ADMIN_SET and uid not in set(OWNERS):
            _ADMIN_SET.remove(uid)
        _persist()
        return True
    return False

# ---------- حفظ إلى الملف ----------
def _persist() -> None:
    data = {
        "admins": sorted(set(ADMIN_IDS)),
        "owners": sorted(set(OWNERS)),
    }
    _save_json(ADMINS_FILE, data)

# ---------- توافق أسماء قديمة ----------
# بعض الملفات قد تعتمد على أسماء برمجية قديمة:
# - OWNER_IDS: قمنا بتوفيرها كتوافق (تعيد نفس OWNERS)
OWNER_IDS: list[int] = OWNERS[:]

__all__ = [
    "ADMIN_IDS", "OWNERS", "OWNER_IDS",
    "get_admin_ids", "get_owner_ids",
    "is_admin", "add_admin", "remove_admin", "list_admins",
    "ADMINS_FILE",
]
