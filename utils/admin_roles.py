from __future__ import annotations

# utils/admin_roles.py


import json, os, threading, time
from pathlib import Path
from typing import Dict, List, Iterable, Optional
from utils.paths import BASE

# ───────────────── إعدادات عامة ─────────────────
# بإمكانك إضافة أدوار مخصّصة من البيئة (مفصولة بفواصل)
# ADMIN_EXTRA_ROLES="support,qa"
_EXTRA = [r.strip().lower() for r in (os.getenv("ADMIN_EXTRA_ROLES") or "").split(",") if r.strip()]

# الأدوار الافتراضية + المضافة من البيئة
ROLES: List[str] = ["default", "reports", "livechat", "sales", *_EXTRA]

# المسار الجديد المنظّم (داخل مجلد admin تحت التخزين الدائم BASE)
ROLES_DIR: Path = BASE / "admin"
ROLES_FILE: Path = ROLES_DIR / "roles.json"

# توافق قديم: لو كان الملف القديم موجودًا ننقله ونستمر على الجديد
LEGACY_FILE: Path = BASE / "admin_roles.json"

_LOCK = threading.Lock()


# ───────────────── أدوات I/O آمنة ─────────────────
def _atomic_write(path: Path, data: dict):
    """
    كتابة ذرّية متحملة لأقفال ويندوز/OneDrive:
    - ملف مؤقت فريد في نفس المجلد
    - flush + fsync
    - os.replace مع إعادة محاولات
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    tmp = path.with_name(f"{path.name}.{int(time.time()*1000)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            # fsync قد لا يتوفر على بعض الأنظمة — نتجاهل بهدوء
            pass

    last_err: Optional[Exception] = None
    for i in range(6):
        try:
            # أحيانًا الملف الهدف يكون للقراءة فقط
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
    # محاولة أخيرة ثم تنظيف المؤقت
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        finally:
            if last_err:
                raise last_err
            raise


def _load(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw or "{}") or default
    except Exception:
        return default


# ───────────────── ترحيل الملف القديم ─────────────────
def _migrate_legacy_if_needed() -> None:
    if LEGACY_FILE.exists() and not ROLES_FILE.exists():
        try:
            ROLES_DIR.mkdir(parents=True, exist_ok=True)
            # نقرأ القديم ونكتب الجديد بشكل ذرّي
            data = _load(LEGACY_FILE, {})
            _atomic_write(ROLES_FILE, data)
            # نُبقي القديم كنسخة احتياطية ولا نحذفه
        except Exception:
            pass


# ───────────────── منطق الأدوار ─────────────────
def _default_map() -> Dict[str, List[int]]:
    return {r: [] for r in ROLES}

def _clean_ids(ids: Iterable[int | str]) -> List[int]:
    out: List[int] = []
    for x in (ids or []):
        s = str(x).strip()
        if s.startswith("@"):   # نتجاهل usernames
            continue
        if s.lstrip("-").isdigit():
            try:
                out.append(int(s))
            except Exception:
                pass
    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set()
    dedup: List[int] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            dedup.append(v)
    return dedup

def load_roles() -> Dict[str, List[int]]:
    _migrate_legacy_if_needed()
    try:
        data = _load(ROLES_FILE, {})
        # تأكيد المفاتيح + تنظيف
        for r in ROLES:
            data.setdefault(r, [])
        cleaned: Dict[str, List[int]] = {}
        for role, ids in data.items():
            cleaned[role] = _clean_ids(ids or [])
        # لو لا يوجد أي مدير في أي دور، جرّب تعبئة من ADMIN_IDS/ADMIN_ID
        if not any(cleaned.values()):
            raw = (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")).strip()
            seed = _clean_ids(raw.replace(";", ",").split(",")) if raw else []
            if seed:
                cleaned["default"] = seed
        return cleaned
    except Exception:
        return _default_map()

def save_roles(m: Dict[str, List[int]]) -> None:
    with _LOCK:
        try:
            for r in ROLES:
                m.setdefault(r, [])
            data = {k: _clean_ids(v or []) for k, v in m.items()}
            _atomic_write(ROLES_FILE, data)
        except Exception:
            pass

def list_roles() -> Dict[str, List[int]]:
    return load_roles()

def get_role_members(role: str) -> List[int]:
    role = (role or "").lower()
    return load_roles().get(role, [])

def set_role_members(role: str, members: Iterable[int | str]) -> None:
    role = (role or "").lower()
    with _LOCK:
        m = load_roles()
        for r in ROLES:
            m.setdefault(r, [])
        m[role] = _clean_ids(members)
        save_roles(m)

def grant_role(role: str, uid: int) -> None:
    role = (role or "").lower()
    with _LOCK:
        m = load_roles()
        for r in ROLES:
            m.setdefault(r, [])
        ids = _clean_ids(m.get(role, []))
        if uid not in ids:
            ids.append(int(uid))
        m[role] = ids
        save_roles(m)

def revoke_role(role: str, uid: int) -> None:
    role = (role or "").lower()
    with _LOCK:
        m = load_roles()
        for r in ROLES:
            m.setdefault(r, [])
        ids = [x for x in _clean_ids(m.get(role, [])) if x != int(uid)]
        m[role] = ids
        save_roles(m)

def get_user_roles(uid: int) -> List[str]:
    uid = int(uid)
    roles = []
    m = load_roles()
    for r, ids in m.items():
        if uid in _clean_ids(ids):
            roles.append(r)
    return roles

def has_role(uid: int, role: str) -> bool:
    return int(uid) in get_role_members(role)

# ───────────────── تنسيقات مساعدة UI ─────────────────
def role_label(role: str, lang: str) -> str:
    role = (role or "").lower()
    if str(lang).startswith("ar"):
        return {
            "default": "الافتراضي",
            "reports": "التقارير",
            "livechat": "الدردشة",
            "sales": "المبيعات",
        }.get(role, role)
    return {
        "default": "default",
        "reports": "reports",
        "livechat": "livechat",
        "sales": "sales",
    }.get(role, role)

def fmt_ids(ids: List[int], lang: str) -> str:
    if ids:
        try:
            return ", ".join(str(int(x)) for x in ids)
        except Exception:
            return ", ".join(map(str, ids))
    return "(" + ("فارغ" if str(lang).startswith("ar") else "empty") + ")"

def parse_ids(text: str) -> List[int]:
    """
    يقبل: "123 456,789 @user" ← يعيد [123,456,789] (يتجاهل @user).
    """
    joined = (text or "").replace(",", " ")
    return _clean_ids(joined.split())
