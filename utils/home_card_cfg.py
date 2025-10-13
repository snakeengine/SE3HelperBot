from __future__ import annotations

# utils/home_card_cfg.py


import json
import os
import shutil
import time
import threading
from pathlib import Path
from typing import Any, Dict, Tuple

# نحاول استخدام BASE الموحّد إن وُجد، وإلا fallback إلى data/
try:
    from utils.paths import BASE
    DATA_DIR = (BASE)
except Exception:
    DATA_DIR = Path("data").resolve()

DATA_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE = DATA_DIR / "home_ui_cfg.json"

# مجلد نسخ احتياطي
BACKUPS_DIR = (DATA_DIR / "backups")
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
MAX_BACKUPS = int(os.getenv("JSON_BACKUPS_KEEP", "7") or "7")

# قفل خيطي + قفل ملفي (بين العمليات)
_THREAD_LOCK = threading.Lock()
_FILELOCK_PATH = DATA_DIR / ".home_ui_cfg.lock"

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
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        pass

def _atomic_write_json(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _snapshot(path)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(d, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp, path)

def _safe_read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

# ---------------- Defaults & schema ----------------
DEFAULT_CFG: Dict[str, Any] = {
    "theme":   "neo",      # neo | glass | chip | plaque | banner | receipt
    "density": "comfy",    # comfy | compact
    "sep":     "soft",     # soft | hard
    "icons":   "modern",   # modern | classic
    "bullets": True,
    "tip":     True,
    "version": True,
    "users":   True,
    "alerts":  True,
}

_ALLOWED = {
    "theme":   {"neo", "glass", "chip", "plaque", "banner", "receipt"},
    "density": {"comfy", "compact"},
    "sep":     {"soft", "hard"},
    "icons":   {"modern", "classic"},
}

_BOOL_KEYS = {"bullets", "tip", "version", "users", "alerts"}

def _normalize(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = DEFAULT_CFG.copy()
    if not isinstance(cfg, dict):
        return out

    # خيارات نصية محددة
    for key, allowed in _ALLOWED.items():
        v = cfg.get(key, out[key])
        v = (str(v) if v is not None else out[key]).lower().strip()
        out[key] = v if v in allowed else out[key]

    # مفاتيح منطقية
    for key in _BOOL_KEYS:
        v = cfg.get(key, out[key])
        if isinstance(v, bool):
            out[key] = v
        elif isinstance(v, str):
            out[key] = v.strip().lower() not in {"0", "false", "off", "no"}
        else:
            out[key] = bool(v)

    return out

# ---------------- Public API ----------------
def get_cfg() -> dict:
    """
    إرجاع الإعدادات بعد الدمج مع الافتراضي + التطبيع.
    متوافق مع الإصدار السابق.
    """
    d = _safe_read_json(CFG_FILE, {})
    return _normalize(d if isinstance(d, dict) else {})

def set_cfg(new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    يستبدل الملف بإعدادات مطبّعة (مع افتراضيات).
    يُرجع النسخة النهائية المكتوبة.
    """
    final = _normalize(new_cfg or {})
    tok = _file_lock_acquire()
    try:
        with _THREAD_LOCK:
            _atomic_write_json(CFG_FILE, final)
    finally:
        _file_lock_release(tok)
    return final

def update_cfg(patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    يدمج patch فوق الموجود ثم يطبّع ويكتب.
    يُرجع النسخة النهائية المكتوبة.
    """
    cur = get_cfg()
    cur.update(patch or {})
    return set_cfg(cur)

def get_option(name: str, default: Any = None) -> Any:
    """
    قراءة خيار مفرد مع افتراضي.
    """
    cfg = get_cfg()
    return cfg.get(name, default)

def set_option(name: str, value: Any) -> Dict[str, Any]:
    """
    ضبط خيار مفرد (مع التطبيع والكتابة).
    """
    return update_cfg({name: value})

def toggle_option(name: str) -> Tuple[bool, Dict[str, Any]]:
    """
    قلب قيمة منطقية وإرجاع (القيمة_الجديدة, cfg_الكامل).
    """
    if name not in _BOOL_KEYS:
        # لو ليست منطقية، نعتبر أي قيمة غير "إيقاف" = True
        cur = bool(get_option(name))
        new_val = not cur
        return new_val, set_option(name, new_val)
    cur = bool(get_option(name))
    new_val = not cur
    cfg = set_option(name, new_val)
    return new_val, cfg

def reset_cfg() -> Dict[str, Any]:
    """
    إعادة الملف للوضع الافتراضي.
    """
    return set_cfg(DEFAULT_CFG.copy())

__all__ = [
    "get_cfg",
    "set_cfg",
    "update_cfg",
    "get_option",
    "set_option",
    "toggle_option",
    "reset_cfg",
]
