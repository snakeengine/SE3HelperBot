# services/admin_roles.py
from __future__ import annotations
import os, json, time, asyncio, shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from services.admin_roles_sources import read_legacy_admins

try:
    from utils.paths import BASE, BACKUPS_DIR as _BACKUPS_DIR  # لو عندك BACKUPS_DIR معرّفة
except Exception:
    BASE = Path(__file__).resolve().parent.parent
    _BACKUPS_DIR = BASE / "backups"

DB_PATH = (BASE / "admin_roles.json")          # <— ثابت على Volume
BACKUPS_DIR = _BACKUPS_DIR if _BACKUPS_DIR else (BASE / "backups")
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
MAX_BACKUPS = int(os.getenv("JSON_BACKUPS_KEEP", "7") or "7")

# أقفال: قفل عمليات + قفل asyncio
_async_lock = asyncio.Lock()
_FILELOCK_PATH = (BASE / ".admin_roles.lock")

def _file_lock_acquire():
    _FILELOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        import msvcrt  # type: ignore
        fh = open(_FILELOCK_PATH, "a+b")
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        return ("win", fh)
    except Exception:
        try:
            import fcntl  # type: ignore
            fh = open(_FILELOCK_PATH, "a+b")
            fcntl.flock(fh, fcntl.LOCK_EX)
            return ("unix", fh)
        except Exception:
            return (None, None)

def _file_lock_release(tok):
    kind, fh = tok
    if not fh:
        return
    try:
        if kind == "win":
            import msvcrt  # type: ignore
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        elif kind == "unix":
            import fcntl  # type: ignore
            fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass

def _now() -> int:
    return int(time.time())

def _snapshot(path: Path) -> None:
    try:
        if not path.exists():
            return
        ts = time.strftime("%Y%m%d-%H%M%S")
        dst = BACKUPS_DIR / f"{path.stem}.{ts}{path.suffix}"
        shutil.copy2(path, dst)
        fam = sorted(BACKUPS_DIR.glob(f"{path.stem}.*{path.suffix}"))
        if len(fam) > MAX_BACKUPS:
            for p in fam[:-MAX_BACKUPS]:
                try: p.unlink()
                except Exception: pass
    except Exception:
        pass

def _parse_ids(s: str | None) -> List[int]:
    if not s:
        return []
    out: List[int] = []
    for tok in s.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            # تجاهل @username — لا يمكن تحويله إلى ID هنا
            pass
    return sorted(set(out))

def _default_seed() -> Dict[str, List[int]]:
    """
    الأولوية:
      1) ملفات الأدمن القديمة (admin/*)
      2) ENV (ADMIN_IDS*, …)
    """
    legacy = read_legacy_admins()  # default/livechat/reports

    def _env_ids(name: str) -> List[int]:
        raw = os.getenv(name, "") or ""
        ids = {int(x.strip()) for x in raw.replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()}
        return sorted(ids)

    merged = {
        "default": sorted(set(legacy.get("default", []))  | set(_env_ids("ADMIN_IDS"))),
        "reports": sorted(set(legacy.get("reports", []))  | set(_env_ids("ADMIN_IDS_REPORTS"))),
        "livechat": sorted(set(legacy.get("livechat", []))| set(_env_ids("ADMIN_IDS_LIVECHAT"))),
        "sales": _env_ids("ADMIN_IDS_SALES"),
    }
    return merged

# ترحيل من مسارات قديمة إلى BASE/admin_roles.json
def _maybe_migrate_legacy() -> None:
    candidates = [
        (Path(BASE) / "data" / "admin_roles.json"),               # إصدار قديم كنت تكتبه تحت BASE/data
        (Path(__file__).resolve().parents[1] / "data" / "admin_roles.json"),  # repo_root/data
    ]
    for src in candidates:
        try:
            if src.exists() and not DB_PATH.exists():
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, DB_PATH)
        except Exception:
            pass

def _read() -> Dict[str, object]:
    _maybe_migrate_legacy()
    if not DB_PATH.exists():
        return {"roles": _default_seed(), "updated_at": _now()}

    tok = _file_lock_acquire()
    try:
        with DB_PATH.open("r", encoding="utf-8") as f:
            obj = json.load(f)
            if "roles" not in obj or not isinstance(obj.get("roles"), dict):
                obj = {"roles": _default_seed(), "updated_at": _now()}
            return obj
    except Exception:
        return {"roles": _default_seed(), "updated_at": _now()}
    finally:
        _file_lock_release(tok)

def _write(obj: Dict[str, object]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tok = _file_lock_acquire()
    try:
        _snapshot(DB_PATH)
        tmp = DB_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        tmp.replace(DB_PATH)
    finally:
        _file_lock_release(tok)

# ========= Public API =========
async def get_roles() -> Dict[str, List[int]]:
    async with _async_lock:
        data = _read()
        return data["roles"]  # type: ignore

async def get_admins(role: str) -> List[int]:
    async with _async_lock:
        obj = _read()
        roles: Dict[str, List[int]] = obj["roles"]  # type: ignore
        ids = roles.get(role, [])
        if ids:
            return ids
        return roles.get("default", [])

async def set_admins(role: str, ids: List[int]) -> None:
    async with _async_lock:
        obj = _read()
        roles: Dict[str, List[int]] = obj["roles"]  # type: ignore
        roles[role] = sorted(set(int(x) for x in ids))
        obj["roles"] = roles
        obj["updated_at"] = _now()
        _write(obj)

async def add_admin(role: str, admin_id: int) -> None:
    async with _async_lock:
        obj = _read()
        roles: Dict[str, List[int]] = obj["roles"]  # type: ignore
        lst = set(roles.get(role, []))
        lst.add(int(admin_id))
        roles[role] = sorted(lst)
        obj["roles"] = roles
        obj["updated_at"] = _now()
        _write(obj)

async def remove_admin(role: str, admin_id: int) -> None:
    async with _async_lock:
        obj = _read()
        roles: Dict[str, List[int]] = obj["roles"]  # type: ignore
        lst = set(roles.get(role, []))
        lst.discard(int(admin_id))
        roles[role] = sorted(lst)
        obj["roles"] = roles
        obj["updated_at"] = _now()
        _write(obj)
