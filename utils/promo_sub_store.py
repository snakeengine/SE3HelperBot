from __future__ import annotations

# utils/promo_sub_store.py

import os, json, time
from typing import Dict, Any, List
import os
BASE = os.getenv("STORAGE_DIR") or os.path.join("data")
os.makedirs(BASE, exist_ok=True)
PATH = os.path.join(BASE, "promo_store.json")

PROMO_MIN_VIEWS = int(os.getenv("PROMO_MIN_VIEWS", "10000"))

def _now() -> int: 
    return int(time.time())

def _load() -> Dict[str, Any]:
    if not os.path.exists(PATH):
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    with open(PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f) or {}
        except Exception:
            return {}

def _save(data: Dict[str, Any]) -> None:
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)

def find_request(uid: int) -> Dict[str, Any] | None:
    return _load().get(str(uid))

def update_request(uid: int, **fields) -> Dict[str, Any]:
    data = _load()
    rec = data.get(str(uid)) or {"uid": uid, "created_at": _now()}
    rec.update(fields)
    rec["updated_at"] = _now()
    data[str(uid)] = rec
    _save(data)
    return rec

def set_status(uid: int, status: str) -> Dict[str, Any]:
    return update_request(uid, status=status)

def list_pending(limit: int = 50) -> List[Dict[str, Any]]:
    data = _load()
    rows = [
        v for v in data.values() 
        if v.get("status") in {"awaiting_admin", "in_review", "approved"}
    ]
    rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
    return rows[:limit]

# مسارات اختيارية لملفين نصيين تُخزن فيهما القواعد لكل لغة
PROMO_RULES_AR_PATH = os.getenv("PROMO_RULES_AR_PATH", "data/promo_rules_ar.txt")
PROMO_RULES_EN_PATH = os.getenv("PROMO_RULES_EN_PATH", "data/promo_rules_en.txt")

def _read_file_or_none(path: str) -> str | None:
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read().strip()
                return txt if txt else None
    except Exception:
        pass
    return None

def load_rules(lang: str) -> str:
    """
    يرجع نص قواعد/تعليمات إضافية تُعرض للمستخدم.
    - إن وُجد ملف نصي للغة المناسبة يُقرأ منه، وإلا يُرجع نصًا افتراضيًا قصيرًا.
    """
    is_ar = (lang or "en").startswith("ar")
    path  = PROMO_RULES_AR_PATH if is_ar else PROMO_RULES_EN_PATH
    txt   = _read_file_or_none(path)

    if txt:
        return txt

    # نص افتراضي لو لم توفّر ملفات
    if is_ar:
        return (
            "• لا يُسمح بالمشاهدات الوهمية/المدفوعة.\n"
            "• يجب أن يكون المنشور عامًّا وغير محذوف حتى انتهاء المراجعة.\n"
            "• قد نطلب دليلًا إضافيًا عند الشك."
        )
    else:
        return (
            "• Fake/paid views are not allowed.\n"
            "• Post must remain public until review is completed.\n"
            "• We may request additional proof if needed."
        )

# === Admin listing helpers ===

def list_requests(status: str | None = None, limit: int = 100, order: str = "-updated_at"):
    """
    أرجع قائمة طلبات حسب الحالة (أو كلها).
    order: "-updated_at" أو "updated_at" أو "-requested_at" ..الخ
    """
    data = _load()
    rows = list(data.values())
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    key = order.lstrip("-")
    rows.sort(key=lambda r: r.get(key, 0), reverse=order.startswith("-"))
    return rows[:limit]


def reset_after_unban(uid: int):
    """تفريغ أي أثر للرفض/القفل حتى يتمكن من التقديم فورًا."""
    update_request(
        uid,
        status="none",
        unbanned_at=_now(),
        rejected_at=None,
        requested_at=None,
        locked=False,
        chat_on=False,
        chat_admin=None,
        step=None,
    )
