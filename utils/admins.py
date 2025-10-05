# utils/admins.py
from __future__ import annotations

import json, os, threading, time
from pathlib import Path
from typing import Iterable, List, Set
from utils.paths import BASE
from utils.admin_roles import load_roles

# ───────────── مواقع التخزين ─────────────
ADMIN_DIR: Path = BASE / "admin"
ADMIN_DIR.mkdir(parents=True, exist_ok=True)
STORE: Path = ADMIN_DIR / "admin_ids.json"

# توافق قديم: data/admin_ids.json
LEGACY_STORE: Path = (BASE / ".." / "data" / "admin_ids.json").resolve()

_LOCK = threading.Lock()

# ───────────── أدوات مساعدة ─────────────
def _parse_ids_env(val: str | None) -> List[int]:
    if not val:
        return []
    raw = val.replace(";", ",")
    out: List[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok and tok.lstrip("-").isdigit():
            try:
                out.append(int(tok))
            except Exception:
                pass
    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set(); dedup: List[int] = []
    for v in out:
        if v not in seen:
            seen.add(v); dedup.append(v)
    return dedup

def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.{int(time.time()*1000)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload); f.flush()
        try: os.fsync(f.fileno())
        except Exception: pass
    last_err = None
    for i in range(6):
        try:
            try:
                if path.exists():
                    path.chmod(0o666)
            except Exception:
                pass
            os.replace(tmp, path)
            return
        except Exception as e:
            last_err = e
            time.sleep(0.1 * (i + 1))
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists(): tmp.unlink()
        finally:
            if last_err: raise last_err
            raise

def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw or "null") or default
    except Exception:
        return default

def _migrate_legacy_if_needed():
    try:
        if LEGACY_STORE.exists() and not STORE.exists():
            data = _load_json(LEGACY_STORE, [])
            _atomic_write(STORE, data)
    except Exception:
        pass

# ───────────── الحالة (state) ─────────────
# المالكين من البيئة (محميون من الحذف)
_OWNERS_ENV = (
    os.getenv("OWNER_IDS")
    or os.getenv("ADMIN_IDS")
    or os.getenv("ADMIN_ID")
    or ""
)
OWNERS: Set[int] = set(_parse_ids_env(_OWNERS_ENV))

def _load_file_ids() -> Set[int]:
    arr = _load_json(STORE, [])
    out: Set[int] = set()
    for x in arr or []:
        s = str(x).strip()
        if s.lstrip("-").isdigit():
            try: out.add(int(s))
            except Exception: pass
    return out

def _save_file_ids(ids: Iterable[int]) -> None:
    # لا نخزن المالكين في الملف (يبقون من البيئة)
    data = sorted({int(x) for x in ids if int(x) not in OWNERS})
    _atomic_write(STORE, data)

def _union_with_roles(admins: Set[int]) -> Set[int]:
    try:
        roles = load_roles()
        default_role = set(int(x) for x in (roles.get("default") or []))
        return set(admins) | set(OWNERS) | default_role
    except Exception:
        return set(admins) | set(OWNERS)

def _current_admins() -> Set[int]:
    _migrate_legacy_if_needed()
    file_ids = _load_file_ids()
    return _union_with_roles(file_ids)

# ───────────── واجهة عامة ─────────────
def is_admin(uid: int) -> bool:
    try:
        return int(uid) in _current_admins()
    except Exception:
        return False

def list_admins() -> list[int]:
    return sorted(_current_admins())

def add_admin(uid: int) -> tuple[bool, str]:
    """يضيف مديرًا إلى ملف التخزين (حتى لو لم يكن Owner)."""
    uid = int(uid)
    with _LOCK:
        admins = _load_file_ids() | set(OWNERS)  # مجموعة العمل شامل المالِكين مؤقتًا
        if uid in admins:
            return False, "already"
        # أضِف للملف فقط إن لم يكن Owner من البيئة
        file_ids = _load_file_ids()
        file_ids.add(uid)
        _save_file_ids(file_ids)
        return True, "added"

def remove_admin(uid: int) -> tuple[bool, str]:
    """يزيل مديرًا من ملف التخزين (لن يزيل Owner القادم من البيئة)."""
    uid = int(uid)
    with _LOCK:
        if uid in OWNERS:
            return False, "owner_protected"
        file_ids = _load_file_ids()
        if uid not in file_ids:
            # قد يكون قادمًا من roles أو owners، لكن ليس في الملف
            return False, "not_found"
        file_ids.discard(uid)
        _save_file_ids(file_ids)
        return True, "removed"

# ───────────── توافق قديم + واجهة موحّدة ─────────────
def get_admin_ids() -> set[int]:
    """إرجاع مجموعة المدراء الحالية (Owners + ملف + roles.default)."""
    try:
        return set(_current_admins())
    except Exception:
        return set()

# ثابت للتوافق مع الاستيرادات القديمة:
try:
    ADMIN_IDS: set[int] = set(_current_admins())
except Exception:
    ADMIN_IDS = set()
