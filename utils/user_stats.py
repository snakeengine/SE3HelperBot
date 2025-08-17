# 📁 utils/user_stats.py
import json, os, csv
from datetime import datetime, timezone, date
from typing import Dict, Any, Optional, Set, List

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
USERS_LIST = os.path.join(DATA_DIR, "users.json")        # [123, 456, ...] أو {"users":[...]} أو {"123": {...}}
USER_STATS = os.path.join(DATA_DIR, "user_stats.json")   # {"123": {"last_seen": "...", "visits": N, "username": "..."}, ...}

os.makedirs(DATA_DIR, exist_ok=True)

# ---------- I/O آمن ----------
def _safe_load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _safe_save(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# ---------- أدوات وقت ----------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _to_utc_date(iso_str: str) -> Optional[date]:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).date()
    except Exception:
        return None

# ========= تُستدعى من /start لتجميع المستخدمين =========
def log_user(user_id: int, *, username: Optional[str] = None):
    """
    يسجّل المستخدم في users.json ويحدّث بصمته في user_stats.json.
    تُستدعى عادةً من /start.
    """
    # users.json
    users = _safe_load(USERS_LIST, [])
    if isinstance(users, dict) and "users" in users:
        current = set(users.get("users") or [])
        if user_id not in current:
            current.add(user_id)
            users["users"] = list(current)
            _safe_save(USERS_LIST, users)
    else:
        if not isinstance(users, list):
            users = []
        if user_id not in users:
            users.append(user_id)
            _safe_save(USERS_LIST, users)

    # user_stats.json
    stats: Dict[str, Dict[str, Any]] = _safe_load(USER_STATS, {})
    entry = stats.get(str(user_id), {})
    entry["last_seen"] = _now_iso()
    entry["visits"] = int(entry.get("visits", 0)) + 1
    if username is not None:
        # نخزن آخر يوزرنيم معروف بشكل اختياري
        entry["username"] = str(username)
    stats[str(user_id)] = entry
    _safe_save(USER_STATS, stats)

# ========= أدوات إحصائية أساسية =========
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
    """إجمالي المستخدمين الفريدين."""
    return len(_all_user_ids())

def get_active_users_today() -> int:
    """عدد المستخدمين الذين تفاعلوا اليوم (حسب last_seen بـ UTC)."""
    stats = _safe_load(USER_STATS, {})
    if not isinstance(stats, dict):
        return 0

    today_utc = datetime.now(timezone.utc).date()
    active = 0
    for v in stats.values():
        last = v.get("last_seen")
        if not isinstance(last, str):
            continue
        d = _to_utc_date(last)
        if d == today_utc:
            active += 1
    return active

def get_all_users_list() -> List[int]:
    """قائمة مرتّبة بكل الـ IDs المعروفة."""
    return sorted(_all_user_ids())

def get_user_stats(user_id: int) -> Dict[str, Any]:
    """
    يعيد سجل مستخدم واحد: {"last_seen": "...", "visits": N, "username": "..."} أو {} إن لم يوجد.
    """
    stats = _safe_load(USER_STATS, {})
    if not isinstance(stats, dict):
        return {}
    rec = stats.get(str(user_id), {})
    if not isinstance(rec, dict):
        return {}
    return rec

# ========= تصدير وملخصات =========
def export_users_csv(path: Optional[str] = None) -> str:
    """
    يصدّر المستخدمين إلى CSV (UTF-8). يرجّع المسار النهائي.
    الأعمدة: user_id, username, visits, last_seen
    """
    out_path = path or os.path.join(DATA_DIR, "users_export.csv")
    stats = _safe_load(USER_STATS, {})
    ids = get_all_users_list()

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "username", "visits", "last_seen"])
        for uid in ids:
            rec = stats.get(str(uid), {}) if isinstance(stats, dict) else {}
            w.writerow([
                uid,
                rec.get("username", "") if isinstance(rec, dict) else "",
                int(rec.get("visits", 0)) if isinstance(rec, dict) else 0,
                rec.get("last_seen", "") if isinstance(rec, dict) else "",
            ])
    os.replace(tmp, out_path)
    return out_path

def build_admin_stats_text(lang: str = "en") -> str:
    """
    يُنشئ نص HTML بسيط لعرضه في لوحة الأدمن أو رد أمر /stats.
    يعتمد مفاتيح ترجمة عامة؛ إن لم تتوفر سيظهر نص إنجليزي افتراضي.
    """
    try:
        from lang import t as _t
    except Exception:
        def _t(_l, k): return k  # فولباك

    total = get_total_users()
    active = get_active_users_today()

    title = _t(lang, "stats_title") or "📈 <b>Bot Stats</b>"
    k_total = _t(lang, "stats_total_users") or "Total users"
    k_active = _t(lang, "stats_active_today") or "Active today"

    return (
        f"{title}\n\n"
        f"• {k_total}: <code>{total}</code>\n"
        f"• {k_active}: <code>{active}</code>"
    )
