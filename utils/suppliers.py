# utils/suppliers.py
from __future__ import annotations

import os, json, time, threading, contextlib
from pathlib import Path
from typing import Set, List, Optional

# ========= مسار التخزين الموحّد =========
# نحاول استخدام BASE من utils.paths؛ وإن لم تتوفر لأي سبب نرجع إلى /data أو ./data.
try:
    from utils.paths import BASE  # مخزن البيانات الموحّد على السيرفر/الدبلويمنت
    DATA_DIR = BASE
except Exception:
    # أولاً جرّب /data إن كان موجود، وإلا أنشئ ./data محليًا
    DATA_DIR = Path("/data") if Path("/data").exists() else Path("data")

FILE     = DATA_DIR / "suppliers.json"
LOCKFILE = DATA_DIR / "suppliers.lock"

# أنشئ المجلد بصلاحيات مقيدة (إن أمكن)
DATA_DIR.mkdir(parents=True, exist_ok=True)
try:
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
    """
    Normalize and validate a user id.
    يتحقّق من أن المعرّف رقم صحيح وموجب وبنطاق معقول.
    """
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
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
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
            # قفل كامل الملف بمنطقة صغيرة (بايت واحد يكفي للإمساك بالقفل)
            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)  # حظر حتى يتوفر القفل
            try:
                yield
            finally:
                lf.seek(0)
                try:
                    msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
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
                s.add(_normalize_uid(v))
            except Exception:
                continue
    return s

def _rotate_corrupt_file():
    """تدوير الملف التالف (إن وُجد) كي نبدأ بملف نظيف بدون تعطيل النظام."""
    try:
        if FILE.exists():
            ts = time.strftime("%Y%m%d-%H%M%S")
            os.replace(FILE, FILE.with_suffix(FILE.suffix + f".corrupt-{ts}"))
    except Exception:
        pass

def _load_from_disk_nolock() -> Set[int]:
    """
    اقرأ الملف بدون أخذ قفل (المستوى الأعلى يتولى القفل).
    الكتابة تستخدم استبدالًا ذريًا، لذا القراءة بدون قفل آمنة.
    """
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
    """
    اكتب الملف بشكل ذري وآمن، بدون أخذ قفل (المستوى الأعلى يتولى القفل).
    - json مضغوط (separators) لتقليل الحجم.
    - fsync للملف ثم للمجلد لضمان ثبات البيانات على بعض الأنظمة.
    """
    tmp = FILE.with_suffix(FILE.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, FILE)
    # fsync للمجلد لضمان ثبات dirent
    try:
        dfd = os.open(str(DATA_DIR), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        pass

def _ensure_cache_up_to_date() -> Set[int]:
    """
    يحدّث الكاش داخل العملية إذا تغيّر mtime على القرص.
    يمنع القراءات المتكررة الثقيلة ويواكب التعديلات من عمليات أخرى.
    """
    global _cache, _cache_mtime_ns
    with _cache_lock:
        disk_mtime = _get_mtime_ns()
        if _cache is None or disk_mtime != _cache_mtime_ns:
            _cache = _load_from_disk_nolock()
            _cache_mtime_ns = disk_mtime
        return _cache

# ========= الواجهة العامة (API) =========
def is_supplier(user_id: int) -> bool:
    """
    تحقق هل المستخدم مورّد. / Check if user is a supplier.
    قراءة فقط من الكاش المحدّث — لا حاجة لقفل خيوط هنا.
    """
    uid = _normalize_uid(user_id)
    s = _ensure_cache_up_to_date()
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
    return sorted(_ensure_cache_up_to_date())

def count_suppliers() -> int:
    """عدد المورّدين. / Count suppliers."""
    return len(_ensure_cache_up_to_date())
