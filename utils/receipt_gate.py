# utils/receipt_gate.py
from __future__ import annotations
import json, time, os
from pathlib import Path
from typing import Iterable, Optional

_FILE = Path("data/receipt_windows.json")
_DEFAULT_TTL = int(os.getenv("RECEIPT_TTL_SECONDS", "3600"))  # مدة السماح الافتراضية بالثواني (افتراضي 60 دقيقة)

def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(d: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _FILE)

def _norm_types(types: Iterable[str]) -> list[str]:
    # وحّد الأنواع إلى lower-case وتخلّص من التكرار
    seen = set()
    out: list[str] = []
    for t in types or []:
        tt = str(t).lower().strip()
        if not tt or tt in seen:
            continue
        seen.add(tt)
        out.append(tt)
    return out

def open_window(user_id: int, types: Iterable[str] = ("photo", "document", "text"), ttl: Optional[int] = None) -> None:
    """
    اسمح للمستخدم بإرسال أنواع محتوى معيّنة لمدة ttl ثانية.
    إن لم تُحدّد ttl، تُستخدم القيمة من RECEIPT_TTL_SECONDS أو 3600 ثانية.
    """
    d = _load()
    d[str(user_id)] = {
        "types": _norm_types(types),
        "exp": time.time() + int(_DEFAULT_TTL if ttl is None else ttl),
    }
    _save(d)

def is_allowed(user_id: int, content_type: str) -> bool:
    """
    تحقّق إن كان هذا النوع مسموحًا حاليًا لهذا المستخدم.
    يقوم أيضًا بتنظيف السجلات المنتهية عند الحاجة.
    """
    d = _load()
    rec = d.get(str(user_id))
    if not rec:
        return False

    now = time.time()
    try:
        exp = float(rec.get("exp", 0))
    except Exception:
        exp = 0.0

    if now > exp:
        # انتهت النافذة — احذفها
        d.pop(str(user_id), None)
        _save(d)
        return False

    allowed = set(_norm_types(rec.get("types") or []))
    return str(content_type).lower() in allowed

def close_window(user_id: int) -> bool:
    """
    أغلق نافذة المستخدم إن كانت موجودة.
    يعيد True إذا كان هناك نافذة وأُغلقت.
    """
    d = _load()
    if str(user_id) in d:
        d.pop(str(user_id), None)
        _save(d)
        return True
    return False

# ---- دوال مساعدة اختيارية ----

def extend_window(user_id: int, extra_seconds: int) -> bool:
    """مدّد نافذة المستخدم بعدد ثوانٍ إضافية. يعيد True إن تم التمديد."""
    d = _load()
    rec = d.get(str(user_id))
    if not rec:
        return False
    try:
        rec["exp"] = float(rec.get("exp", 0)) + int(extra_seconds)
    except Exception:
        rec["exp"] = time.time() + int(extra_seconds)
    d[str(user_id)] = rec
    _save(d)
    return True

def remaining_seconds(user_id: int) -> int:
    """كم تبقّى من وقت النافذة بالثواني؟ 0 إن لم توجد أو انتهت."""
    d = _load()
    rec = d.get(str(user_id))
    if not rec:
        return 0
    try:
        rem = int(float(rec.get("exp", 0)) - time.time())
    except Exception:
        rem = 0
    return max(0, rem)

def purge_expired() -> int:
    """
    نظّف جميع النوافذ المنتهية. يعيد عدد السجلات التي تم حذفها.
    مفيد لو أحببت تشغّله دوريًا (كرون داخلي).
    """
    d = _load()
    now = time.time()
    deleted = 0
    for uid in list(d.keys()):
        try:
            if now > float(d[uid].get("exp", 0)):
                d.pop(uid, None)
                deleted += 1
        except Exception:
            d.pop(uid, None)
            deleted += 1
    if deleted:
        _save(d)
    return deleted
