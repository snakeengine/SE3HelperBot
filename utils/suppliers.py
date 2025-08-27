# utils/suppliers.py
from __future__ import annotations

import os, json, time, threading
from pathlib import Path
from typing import Set, List, Optional
import contextlib

# ========= إعدادات المسار والملفات (Secure Paths & Permissions) =========
DATA_DIR = Path("data")
FILE = DATA_DIR / "suppliers.json"
LOCKFILE = DATA_DIR / "suppliers.lock"

# أنشئ المجلد بصلاحيات مقيدة (إن أمكن)
DATA_DIR.mkdir(parents=True, exist_ok=True)
try:
    # على ويندوز قد لا تُحترم الصلاحيات بنفس الدقة، لكن لا ضرر من المحاولة
    os.chmod(DATA_DIR, 0o700)
except Exception:
    pass

# ========= كاش داخل العملية + قفل على مستوى الخيوط =========
_cache: Optional[Set[int]] = None
_cache_mtime_ns: int = 0
_cache_lock = threading.RLock()

# حدود لضبط صحة المعرّف (حماية بسيطة)
_MIN_UID = 1
_MAX_UID = 2**63 - 1  # حد منطقي لمنع قيم شاذة جداً

def _normalize_uid(user_id: int) -> int:
    """Normalize and validate a user id. يتحقّق من أن المعرف رقم صحيح وموجب وبنطاق معقول"""
    try:
        uid = int(user_id)
    except Exception as e:
        raise ValueError(f"Invalid user_id: {user_id!r}") from e
    if uid < _MIN_UID or uid > _MAX_UID:
        raise ValueError(f"user_id out of allowed range: {uid}")
    return uid

# ========= قفل بين العمليات (Interprocess Lock) =========
if os.name == "posix":
    import fcntl  # type: ignore

    @contextlib.contextmanager
    def _interprocess_lock(exclusive: bool = True):
        LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCKFILE, "a+b") as lf:
            flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lf.fileno(), flags)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
else:
    # Windows: استخدم msvcrt.locking على lockfile
    import msvcrt  # type: ignore

    @contextlib.contextmanager
    def _interprocess_lock(exclusive: bool = True):
        LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
        lf = open(LOCKFILE, "a+b")
        try:
            # استخدم قفل كامل الملف بمنطقة صغيرة (بايت واحد يكفي للإمساك بالقفل)
            mode_block = msvcrt.LK_LOCK   # حظر حتى توفر القفل
            size = 1
            lf.seek(0)
            msvcrt.locking(lf.fileno(), mode_block, size)
            try:
                yield
            finally:
                lf.seek(0)
                try:
                    msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, size)
                except Exception:
                    pass
        finally:
            lf.close()

# ========= أدوات مساعدة للقراءة/الكتابة بأمان =========
def _get_mtime_ns() -> int:
    try:
        return FILE.stat().st_mtime_ns
    except FileNotFoundError:
        return 0

def _decode_set(raw) -> Set[int]:
    s: Set[int] = set()
    if isinstance(raw, list):
        for v in raw:
            try:
                uid = _normalize_uid(v)
            except Exception:
                continue
            s.add(uid)
    return s

def _rotate_corrupt_file():
    try:
        if FILE.exists():
            ts = time.strftime("%Y%m%d-%H%M%S")
            corrupt = FILE.with_suffix(FILE.suffix + f".corrupt-{ts}")
            os.replace(FILE, corrupt)
    except Exception:
        # لا نريد تعطيل النظام إن فشل التدوير
        pass

def _load_from_disk_nolock() -> Set[int]:
    """اقرأ الملف بدون أخذ قفل (المستوى الأعلى يتولى القفل)."""
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return set()
    except Exception:
        # JSON تالف أو وصول متزامن غير مكتمل → دوّر الملف وابدأ نظيفاً
        _rotate_corrupt_file()
        return set()
    return _decode_set(raw)

def _save_to_disk_nolock(s: Set[int]) -> None:
    """اكتب الملف بشكل ذري وآمن، بدون أخذ قفل (المستوى الأعلى يتولى القفل)."""
    tmp = FILE.with_suffix(FILE.suffix + ".tmp")
    # اكتب البيانات
    with open(tmp, "w", encoding="utf-8") as f:
        # لا نحتاج indent في الإنتاج، يقلل الحجم ويسرّع القراءة
        json.dump(sorted(s), f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    # شدّد الصلاحيات إن أمكن
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    # استبدال ذري
    os.replace(tmp, FILE)
    # fsync للمجلد لضمان ثبات الدخول (dirent) على أقراص وأنظمة ملفات معينة
    try:
        dfd = os.open(str(DATA_DIR), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        pass

def _ensure_cache_up_to_date() -> Set[int]:
    """يحدّث الكاش داخل العملية إذا تغيّر mtime على القرص."""
    global _cache, _cache_mtime_ns
    with _cache_lock:
        disk_mtime = _get_mtime_ns()
        if _cache is None or disk_mtime != _cache_mtime_ns:
            # قراءة بدون قفل هنا آمنة لأن الكتابة تستخدم استبدال ذري
            _cache = _load_from_disk_nolock()
            _cache_mtime_ns = disk_mtime
        return _cache

# ========= الواجهة العامة (API) =========
def is_supplier(user_id: int) -> bool:
    """تحقق هل المستخدم مورّد. / Check if user is a supplier."""
    uid = _normalize_uid(user_id)
    s = _ensure_cache_up_to_date()
    # لا حاجة لقفل خيوط هنا لأننا لا نعدّل الكاش
    return uid in s

def set_supplier(user_id: int, value: bool = True) -> None:
    """
    أضف/أزل مورداً بشكل آمن عبر قفل بين العمليات (منع فقدان التحديثات).
    Safely add/remove a supplier with read-modify-write under an exclusive lock.
    """
    global _cache, _cache_mtime_ns
    uid = _normalize_uid(user_id)

    with _interprocess_lock(exclusive=True):
        # حمّل من القرص مباشرة كي ندمج أي تغييرات من عمليات أخرى
        current = _load_from_disk_nolock()
        changed = False
        if value:
            if uid not in current:
                current.add(uid)
                changed = True
        else:
            if uid in current:
                current.discard(uid)
                changed = True

        if changed:
            _save_to_disk_nolock(current)
            # حدّث الكاش المحلي فوراً ليعكس الحالة الجديدة
            with _cache_lock:
                _cache = set(current)
                _cache_mtime_ns = _get_mtime_ns()

def list_suppliers() -> List[int]:
    """قائمة مرتبة بكل المورّدين. / Sorted list of supplier IDs."""
    s = _ensure_cache_up_to_date()
    return sorted(s)

def count_suppliers() -> int:
    """عدد المورّدين. / Count suppliers."""
    s = _ensure_cache_up_to_date()
    return len(s)
