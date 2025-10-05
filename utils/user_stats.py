# 📁 utils/user_stats.py
from __future__ import annotations
import json, os, csv, time, threading
from datetime import datetime, timezone, timedelta, date
from typing import Dict, Any, Optional, Set, List

# مسار مجلد data مطلق لتفادي أي غرابة في المسارات
DATA_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
USERS_LIST = os.path.join(DATA_DIR, "users.json")        # [123, ...] أو {"users":[...]} أو {"123": {...}}
USER_STATS = os.path.join(DATA_DIR, "user_stats.json")   # {"123": {"last_seen": "...", "visits": N, "username": "...", "first_seen":"..."}}

os.makedirs(DATA_DIR, exist_ok=True)

# ---------- قفل ملفات داخل العملية ----------
_LOCKS: dict[str, threading.Lock] = {}
def _get_lock(path: str) -> threading.Lock:
    lock = _LOCKS.get(path)
    if lock is None:
        lock = threading.Lock()
        _LOCKS[path] = lock
    return lock

# ---------- I/O آمن مع إعادة محاولات (ويندوز) ----------
def _atomic_replace(src: str, dst: str, retries: int = 20, delay: float = 0.12):
    last_exc = None
    for _ in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last_exc = e
            time.sleep(delay)
        except OSError as e:
            if getattr(e, "winerror", None) in (5, 32):
                last_exc = e
                time.sleep(delay)
            else:
                raise
    os.replace(src, dst)

def _safe_load(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _safe_save(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        with _get_lock(path):
            _atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except Exception: pass

# ---------- وقت ----------
def _now_dt() -> datetime:
    return datetime.now(timezone.utc)

def _now_iso() -> str:
    return _now_dt().isoformat()

def _to_utc_date(iso_str: str) -> Optional[date]:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).date()
    except Exception:
        return None

# ---------- أدوات users.json ----------
def _read_users_structure():
    """يرجع (kind, obj) حيث kind ∈ {'list','dict-users','dict-map'}."""
    obj = _safe_load(USERS_LIST, [])
    if isinstance(obj, list):
        return "list", obj
    if isinstance(obj, dict):
        if isinstance(obj.get("users"), list):
            return "dict-users", obj
        return "dict-map", obj
    return "list", []

def _write_users_structure(kind: str, obj):
    _safe_save(USERS_LIST, obj if kind != "dict-users" else obj)

def _ensure_user_in_users_json(user_id: int, username: Optional[str] = None):
    kind, obj = _read_users_structure()
    if kind == "list":
        if user_id not in obj:
            obj.append(user_id)
            _safe_save(USERS_LIST, obj)
        return
    if kind == "dict-users":
        s = set(obj.get("users") or [])
        if user_id not in s:
            s.add(user_id)
            obj["users"] = list(s)
            _safe_save(USERS_LIST, obj)
        return
    # dict-map: {"123": {...}}
    if isinstance(obj, dict):
        key = str(user_id)
        rec = obj.get(key)
        if not isinstance(rec, dict):
            rec = {}
        # خزّن الاسم إن توفر
        if username is not None:
            rec.setdefault("username", str(username))
            # لا نكتب overwrite لو موجود — يمكن تحديثه خارجياً
            if not rec.get("username"):
                rec["username"] = str(username)
        obj[key] = rec
        _safe_save(USERS_LIST, obj)

# ========= تُستدعى من /start =========
def log_user(user_id: int, *, username: Optional[str] = None):
    """
    يسجّل المستخدم في users.json ويحدّث بصمته في user_stats.json.
    - يزيد visits +1
    - يحدّث last_seen
    - يملأ first_seen لأول مرة فقط
    """
    _ensure_user_in_users_json(user_id, username=username)

    stats: Dict[str, Dict[str, Any]] = _safe_load(USER_STATS, {})
    rec = stats.get(str(user_id), {})
    if not isinstance(rec, dict):
        rec = {}
    now_iso = _now_iso()
    rec.setdefault("first_seen", now_iso)
    rec["last_seen"] = now_iso
    rec["visits"] = int(rec.get("visits", 0)) + 1
    if username is not None:
        rec["username"] = str(username)
    stats[str(user_id)] = rec
    _safe_save(USER_STATS, stats)

def touch_user(user_id: int, *, username: Optional[str] = None):
    """
    يحدّث last_seen فقط (بدون زيادة visits). مفيد لـ ping/background touch.
    """
    _ensure_user_in_users_json(user_id, username=username)

    stats: Dict[str, Dict[str, Any]] = _safe_load(USER_STATS, {})
    rec = stats.get(str(user_id), {})
    if not isinstance(rec, dict):
        rec = {}
    now_iso = _now_iso()
    rec.setdefault("first_seen", now_iso)
    rec["last_seen"] = now_iso
    if username is not None:
        rec["username"] = str(username)
    stats[str(user_id)] = rec
    _safe_save(USER_STATS, stats)

# ========= أدوات إحصائية =========
def _all_user_ids() -> Set[int]:
    """يجمع الـ IDs من users.json و user_stats.json لضمان التوافق."""
    ids: Set[int] = set()

    users = _safe_load(USERS_LIST, [])
    if isinstance(users, list):
        for x in users:
            try: ids.add(int(x))
            except: pass
    elif isinstance(users, dict):
        if isinstance(users.get("users"), list):
            for x in users["users"]:
                try: ids.add(int(x))
                except: pass
        else:
            for k in users.keys():
                try: ids.add(int(k))
                except: pass

    stats = _safe_load(USER_STATS, {})
    if isinstance(stats, dict):
        for k in stats.keys():
            try: ids.add(int(k))
            except: pass

    return ids

def get_total_users() -> int:
    return len(_all_user_ids())

def get_active_users_today() -> int:
    return get_active_users(days=1)

def get_active_users(*, days: int = 1) -> int:
    """
    عدد المستخدمين الذين تفاعلوا خلال آخر N يوم (UTC).
    days=1 ≈ اليوم الحالي؛ days=7 ≈ آخر أسبوع، وهكذا.
    """
    stats = _safe_load(USER_STATS, {})
    if not isinstance(stats, dict) or days <= 0:
        return 0
    cutoff = (_now_dt() - timedelta(days=days)).date()
    active = 0
    for v in stats.values():
        last = v.get("last_seen")
        if not isinstance(last, str):
            continue
        d = _to_utc_date(last)
        if d is not None and d >= cutoff:
            active += 1
    return active

def get_new_users_today() -> int:
    return get_new_users(days=1)

def get_new_users(*, days: int = 1) -> int:
    """
    عدد المستخدمين الجدد الذين ظهروا لأول مرة خلال آخر N يوم (حسب first_seen).
    """
    stats = _safe_load(USER_STATS, {})
    if not isinstance(stats, dict) or days <= 0:
        return 0
    cutoff = (_now_dt() - timedelta(days=days)).date()
    newc = 0
    for v in stats.values():
        fs = v.get("first_seen")
        if isinstance(fs, str):
            d = _to_utc_date(fs)
            if d is not None and d >= cutoff:
                newc += 1
    return newc

def get_all_users_list() -> List[int]:
    return sorted(_all_user_ids())

def get_user_stats(user_id: int) -> Dict[str, Any]:
    stats = _safe_load(USER_STATS, {})
    rec = stats.get(str(user_id), {})
    return rec if isinstance(rec, dict) else {}

def get_usernames_map() -> Dict[int, str]:
    """
    خريطة ID→username من user_stats.json (أولوية) ثم users.json لو كان dict-map.
    """
    out: Dict[int, str] = {}
    stats = _safe_load(USER_STATS, {})
    if isinstance(stats, dict):
        for k, v in stats.items():
            try:
                uid = int(k)
                un = (v or {}).get("username")
                if isinstance(un, str) and un:
                    out[uid] = un
            except Exception:
                continue

    kind, obj = _read_users_structure()
    if kind == "dict-map" and isinstance(obj, dict):
        for k, v in obj.items():
            try:
                uid = int(k)
                if uid not in out:
                    un = (v or {}).get("username")
                    if isinstance(un, str) and un:
                        out[uid] = un
            except Exception:
                continue
    return out

# ========= تصدير وملخصات =========
def export_users_csv(path: Optional[str] = None) -> str:
    """
    يصدّر المستخدمين إلى CSV (UTF-8). يرجّع المسار النهائي.
    الأعمدة: user_id, username, visits, first_seen, last_seen
    """
    out_path = os.path.abspath(path or os.path.join(DATA_DIR, "users_export.csv"))
    stats = _safe_load(USER_STATS, {})
    ids = get_all_users_list()

    tmp = out_path + f".tmp.{os.getpid()}"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["user_id", "username", "visits", "first_seen", "last_seen"])
            for uid in ids:
                rec = stats.get(str(uid), {}) if isinstance(stats, dict) else {}
                w.writerow([
                    uid,
                    rec.get("username", "") if isinstance(rec, dict) else "",
                    int(rec.get("visits", 0)) if isinstance(rec, dict) else 0,
                    rec.get("first_seen", "") if isinstance(rec, dict) else "",
                    rec.get("last_seen", "") if isinstance(rec, dict) else "",
                ])
            f.flush()
            os.fsync(f.fileno())
        with _get_lock(out_path):
            _atomic_replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except Exception: pass
    return out_path

def build_admin_stats_text(lang: str = "en") -> str:
    """
    يُنشئ نص HTML بسيط لعرضه في لوحة الأدمن أو رد أمر /stats.
    """
    try:
        from lang import t as _t
    except Exception:
        def _t(_l, k): return k  # فولباك

    total = get_total_users()
    active_today = get_active_users(days=1)
    active_week  = get_active_users(days=7)
    new_today    = get_new_users(days=1)

    title   = _t(lang, "stats_title") or "📈 <b>Bot Stats</b>"
    k_total = _t(lang, "stats_total_users") or "Total users"
    k_active_today = _t(lang, "stats_active_today") or "Active today"
    k_active_week  = _t(lang, "stats_active_week") or "Active last 7d"
    k_new_today    = _t(lang, "stats_new_today") or "New today"

    return (
        f"{title}\n\n"
        f"• {k_total}: <code>{total}</code>\n"
        f"• {k_active_today}: <code>{active_today}</code>\n"
        f"• {k_active_week}: <code>{active_week}</code>\n"
        f"• {k_new_today}: <code>{new_today}</code>"
    )
