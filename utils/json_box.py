from __future__ import annotations

# utils/json_box.py


import json
import os
import shutil
import time
import threading
from pathlib import Path
from typing import Any, Callable, Tuple

# قفل خيطي + قفل ملفي (بين العمليات) لمنع تلف الكتابة المتزامنة
_THREAD_LOCK = threading.Lock()
_LOCKS_DIR = Path(os.getenv("DATA_DIR", "data")).resolve()
_LOCKS_DIR.mkdir(parents=True, exist_ok=True)

def _file_lock_path(path: Path) -> Path:
    base = _LOCKS_DIR / ".locks"
    base.mkdir(parents=True, exist_ok=True)
    # اسم مقفل مشتق من اسم الملف الهدف
    return base / (path.name + ".lock")

def _file_lock_acquire(lock_path: Path) -> Tuple[str | None, Any]:
    try:
        import msvcrt  # type: ignore
        fh = open(lock_path, "a+b")
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        return ("win", fh)
    except Exception:
        try:
            import fcntl  # type: ignore
            fh = open(lock_path, "a+b")
            fcntl.flock(fh, fcntl.LOCK_EX)
            return ("unix", fh)
        except Exception:
            return (None, None)

def _file_lock_release(tok: Tuple[str | None, Any]) -> None:
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

# نسخ احتياطي دوّار
BACKUPS_KEEP = int(os.getenv("JSON_BACKUPS_KEEP", "7") or "7")

def _snapshot(path: Path) -> None:
    try:
        if not path.exists():
            return
        backups_dir = path.parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        dst = backups_dir / f"{path.stem}.{ts}{path.suffix}"
        shutil.copy2(path, dst)
        fam = sorted(backups_dir.glob(f"{path.stem}.*{path.suffix}"))
        if len(fam) > BACKUPS_KEEP:
            for p in fam[:-BACKUPS_KEEP]:
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        # نتجاوز أخطاء النسخ الاحتياطي
        pass

def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _snapshot(path)

    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    # اكتب للمؤقت أولاً
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass

    # جرّب الاستبدال عدة مرات (لمشاكل قفل OneDrive)
    tries = 12       # إجمالي ~3 ثوانٍ
    delay = 0.25
    for _ in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(delay)

    # خطة احتياط لو بقي القفل: أنشئ نسخة bak ثم حرّك الملف المؤقت
    bak = path.with_suffix(path.suffix + ".bak")
    try:
        if bak.exists():
            try:
                bak.unlink()
            except Exception:
                pass
        if path.exists():
            try:
                shutil.copy2(path, bak)
            except Exception:
                pass
            try:
                path.unlink()
            except Exception:
                # لو لم يُحذف بسبب القفل، سنجرب التحريك فوقه
                pass
        shutil.move(str(tmp), str(path))
    finally:
        # تنظيف المؤقت إن بقي لأي سبب
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def load_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    lock = _file_lock_path(p)
    tok = _file_lock_acquire(lock)
    try:
        with _THREAD_LOCK:
            _atomic_write_json(p, data)
    finally:
        _file_lock_release(tok)

def update_json(path: str | Path, updater: Callable[[Any], Any], *, default: Any = None) -> Any:
    """
    يقرأ JSON، يمرّره إلى دالة updater لتعيد النسخة المحدّثة، ثم يكتبها ذَرّيًا.
    يُرجع الكائن بعد التحديث.
    """
    p = Path(path)
    cur = load_json(p, default)
    new_obj = updater(cur)
    save_json(p, new_obj)
    return new_obj
