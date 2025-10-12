# utils/admins.py
from __future__ import annotations
import os, re, json, logging
from pathlib import Path

log = logging.getLogger(__name__)

# -------- مسار التخزين --------
try:
    from utils.paths import BASE  # يفضّل أن يشير إلى /data على السيرفر
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "/data")).resolve()

ADMIN_STORE: Path = BASE / "admins.json"
ADMIN_STORE.parent.mkdir(parents=True, exist_ok=True)

# -------- أدوات مساعدة --------
def _parse_ids(s: str | None) -> list[int]:
    """يفصل على فاصلة/مسافة/سطر ويتجاهل الضجيج، ويزيل التكرار مع الحفاظ على الترتيب."""
    if not s:
        return []
    seen = set()
    out: list[int] = []
    for part in re.split(r"[,\s]+", s.strip()):
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            continue
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out

def _env_admins() -> tuple[list[int], list[int]]:
    """قراءة أولية من متغيرات البيئة."""
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

def _save_store(data: dict) -> None:
    ADMIN_STORE.parent.mkdir(parents=True, exist_ok=True)
    # دوماً اكتب المفاتيح القياسية + نسخة ظل للتوافق
    payload = {
        "owners": list(dict.fromkeys(data.get("owners", []))),
        "admins": list(dict.fromkeys(data.get("admins", []))),
    }
    # alias للتوافق مع أي كود قديم يقرأ admin_ids
    payload["admin_ids"] = list(payload["admins"])
    ADMIN_STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_store() -> dict:
    if ADMIN_STORE.exists():
        try:
            data = json.loads(ADMIN_STORE.read_text(encoding="utf-8"))
            # طبّع المفاتيح المحتملة
            owners = data.get("owners") or []
            admins = data.get("admins") or data.get("admin_ids") or []
            return {"owners": owners, "admins": admins}
        except Exception:
            pass
    # إن لم يوجد ملف؛ نبنيه من البيئة ونكتبه
    owners_env, admins_env = _env_admins()
    payload = {"owners": owners_env, "admins": admins_env}
    _save_store(payload)
    return payload

# -------- الحالة الحالية في الذاكرة --------
_state = _load_store()

def reload_from_disk() -> None:
    """إعادة التحميل من الملف يدوياً."""
    global _state, OWNERS, ADMIN_IDS
    _state = _load_store()
    OWNERS = list(_state.get("owners", []))
    # اجعل ADMIN_IDS = اتحاد (owners + admins) حتى نضمن الصلاحيات
    ADMIN_IDS = list(dict.fromkeys((_state.get("owners", []) or []) + (_state.get("admins", []) or [])))

def _sync_env_into_store() -> None:
    """ادمج ما في البيئة (OWNERS/ADMIN_IDS) مع الملف الحالي، ثم احفظ إذا تغيّر."""
    owners_env, admins_env = _env_admins()

    owners = list(dict.fromkeys((_state.get("owners", []) or []) + owners_env))
    admins = list(dict.fromkeys((_state.get("admins", []) or []) + admins_env))

    new_state = {"owners": owners, "admins": admins}
    if new_state != {"owners": _state.get("owners", []), "admins": _state.get("admins", [])}:
        _save_store(new_state)
        _state.update(new_state)

# نفّذ المزامنة فور التحميل
_sync_env_into_store()

# مكشوفة للتوافق مع الكود القديم
OWNERS: list[int] = list(_state.get("owners", []))
# IMPORTANT: نخلي ADMIN_IDS = اتحاد (owners + admins) لتغطية كل صلاحيات الأدمن
ADMIN_IDS: list[int] = list(dict.fromkeys((_state.get("owners", []) or []) + (_state.get("admins", []) or [])))

def list_admins() -> tuple[list[int], list[int]]:
    """(owners, admins) — admins هنا هي القائمة المخزنة (غير متّحدة مع owners)."""
    return list(_state.get("owners", [])), list(_state.get("admins", []))

def is_admin(uid: int | str) -> bool:
    try:
        n = int(uid)
    except Exception:
        return False
    # نعتبر المالك أدمن تلقائياً
    return n in ADMIN_IDS

def add_admin(uid: int | str, *, owner: bool = False) -> bool:
    """يضيف آي دي كأدمن (أو مالك إذا owner=True). يرجّع True لو أضيف جديد."""
    try:
        n = int(uid)
    except Exception:
        return False
    owners = list(_state.get("owners", []))
    admins = list(_state.get("admins", []))

    existed = (n in owners) or (n in admins)

    if owner:
        if n not in owners:
            owners.append(n)
        # ليس ضرورياً وجوده كأدمن أيضاً، لكنه سيظهر ضمن ADMIN_IDS عبر الاتحاد
        if n in admins:
            admins.remove(n)
    else:
        if n not in owners and n not in admins:
            admins.append(n)

    _state["owners"] = list(dict.fromkeys(owners))
    _state["admins"] = list(dict.fromkeys(admins))
    _save_store(_state)

    # حدّث المصدّرات
    reload_from_disk()
    return not existed

def remove_admin(uid: int | str, *, allow_owner: bool = False) -> bool:
    """يحذف من قائمة الأدمن. لو allow_owner=True يحذف من المالكين أيضاً."""
    try:
        n = int(uid)
    except Exception:
        return False
    owners = list(_state.get("owners", []))
    admins = list(_state.get("admins", []))
    removed = False
    if n in admins:
        admins.remove(n); removed = True
    if allow_owner and (n in owners):
        owners.remove(n); removed = True

    _state["owners"] = list(dict.fromkeys(owners))
    _state["admins"] = list(dict.fromkeys(admins))
    _save_store(_state)

    # تحديث المصدّرات
    reload_from_disk()
    return removed

# طباعة تشخيصية عند التحميل
print(f"[ADMIN] OWNERS={OWNERS} | ADMIN_IDS={ADMIN_IDS} | store={ADMIN_STORE}")
log.info("[ADMIN] EXPORT OWNERS=%s ADMIN_IDS=%s", OWNERS, ADMIN_IDS)
