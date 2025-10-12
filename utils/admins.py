# utils/admins.py
from __future__ import annotations
import os, re, json
from pathlib import Path

# ----- مسار تخزين دائم -----
try:
    from utils.paths import BASE  # يفضّل أن يشير إلى /data على السيرفر
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "/data")).resolve()

ADMIN_STORE: Path = BASE / "admins.json"
ADMIN_STORE.parent.mkdir(parents=True, exist_ok=True)

# ----- أدوات مساعدة -----
def _parse_ids(s: str | None) -> list[int]:
    """يفصل بسلاسة على فاصلة/مسافة/سطر جديد ويتجاهل أي ضجيج."""
    if not s:
        return []
    out = set()
    for part in re.split(r"[,\s]+", s.strip()):
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return sorted(out)

def _env_admins() -> tuple[list[int], list[int]]:
    """قراءة أولية من متغيرات البيئة."""
    # ادعم عدة أسماء محتملة للمالكين/المالكين الأساسيين
    owners_raw = (
        os.getenv("OWNERS")
        or os.getenv("OWNER_IDS")
        or os.getenv("ADMIN_OWNERS")
        or ""
    )
    admins_raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or ""
    owners = _parse_ids(owners_raw)
    admins = _parse_ids(admins_raw)
    return owners, admins

def _load_store() -> dict:
    if ADMIN_STORE.exists():
        try:
            return json.loads(ADMIN_STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # إن لم يوجد ملف؛ نبنيه من البيئة ونكتبه
    owners_env, admins_env = _env_admins()
    payload = {
        "owners": owners_env,
        "admins": admins_env,
    }
    _save_store(payload)
    return payload

def _save_store(data: dict) -> None:
    ADMIN_STORE.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ----- الحالة الحالية في الذاكرة -----
_state = _load_store()

def reload_from_disk() -> None:
    """اختياري: لإعادة تحميل القائمة من الملف يدوياً."""
    global _state
    _state = _load_store()

# مكشوفة للتوافق مع الكود القديم
OWNERS: list[int] = list(_state.get("owners", []))
ADMIN_IDS: list[int] = list(_state.get("admins", []))

def list_admins() -> tuple[list[int], list[int]]:
    """(owners, admins)"""
    return list(_state.get("owners", [])), list(_state.get("admins", []))

def is_admin(uid: int | str) -> bool:
    try:
        n = int(uid)
    except Exception:
        return False
    return n in _state.get("owners", []) or n in _state.get("admins", [])

def add_admin(uid: int | str, *, owner: bool = False) -> bool:
    """يضيف آي دي كأدمن (أو مالك إذا owner=True). يرجّع True لو أضيف جديد."""
    try:
        n = int(uid)
    except Exception:
        return False
    owners = set(_state.get("owners", []))
    admins = set(_state.get("admins", []))
    before = (n in owners) or (n in admins)
    if owner:
        owners.add(n)
        admins.discard(n)   # المالك ليس ضرورياً وجوده كأدمن أيضاً
    else:
        if n not in owners:
            admins.add(n)
    _state["owners"] = sorted(owners)
    _state["admins"] = sorted(admins)
    _save_store(_state)

    # حدّث المتغيّرات المصدّرة للتوافق
    global OWNERS, ADMIN_IDS
    OWNERS = list(_state["owners"])
    ADMIN_IDS = list(_state["admins"])
    return not before

def remove_admin(uid: int | str, *, allow_owner: bool = False) -> bool:
    """يحذف من قائمة الأدمن. لو allow_owner=True يحذف من المالكين أيضاً."""
    try:
        n = int(uid)
    except Exception:
        return False
    owners = set(_state.get("owners", []))
    admins = set(_state.get("admins", []))
    removed = False
    if n in admins:
        admins.remove(n); removed = True
    if allow_owner and (n in owners):
        owners.remove(n); removed = True
    _state["owners"] = sorted(owners)
    _state["admins"] = sorted(admins)
    _save_store(_state)
    # تحديث المصدّرات
    global OWNERS, ADMIN_IDS
    OWNERS = list(_state["owners"])
    ADMIN_IDS = list(_state["admins"])
    return removed

# طباعة تشخيصية عند التحميل
print(f"[ADMIN] OWNERS={OWNERS} | ADMIN_IDS={ADMIN_IDS} | store={ADMIN_STORE}")
