from __future__ import annotations

# utils/admin_access.py


import os
from functools import lru_cache
from typing import Iterable, Set, Optional


# --------- Parsing helpers ---------
def _split_candidates(raw: str) -> Iterable[str]:
    # نقسم على فاصلة/فاصلة منقوطة/أسطر/مسافات
    raw = (raw or "").replace(";", ",")
    # نسمح بأسطر جديدة أيضاً
    parts = []
    for chunk in raw.split("\n"):
        parts.extend(p.strip() for p in chunk.split(","))
    return (p for p in parts if p)


def _parse_int_set(raw: str) -> Set[int]:
    out: Set[int] = set()
    for p in _split_candidates(raw):
        ps = p.strip()
        if ps.lstrip("-").isdigit():
            try:
                out.add(int(ps))
            except Exception:
                pass
    return out


# --------- Public API ---------
def _raw_admin_ids_env() -> str:
    # نجمع عدة مفاتيح محتملة للتوافق
    keys = [
        "ADMIN_IDS",
        "ADMIN_ID",
        "OWNERS",
        "TELEGRAM_OWNER_ID",
    ]
    vals = [os.getenv(k, "") for k in keys]
    return ",".join(v for v in vals if v)


@lru_cache(maxsize=1)
def get_admin_ids() -> Set[int]:
    """
    يرجّع مجموعة IDs للمدراء من متغيّرات البيئة.
    يستخدم كاش؛ استعمل reload_admin_ids() لتحديثها أثناء التشغيل.
    """
    ids = _parse_int_set(_raw_admin_ids_env())
    if not ids:
        # قيمة افتراضية آمنة (يمكنك تغييرها)
        ids = {7360982123}
    return ids


def reload_admin_ids() -> Set[int]:
    """
    امسح الكاش وأعد التحميل من البيئة (مفيد عند /reload أو أوامر الإدارة).
    """
    get_admin_ids.cache_clear()  # type: ignore[attr-defined]
    return get_admin_ids()


def is_admin(uid: int) -> bool:
    """تحقّق سريع إذا كان uid ضمن المدراء."""
    try:
        return int(uid) in get_admin_ids()
    except Exception:
        return False


def require_admin_id(uid: int) -> None:
    """
    ارفع استثناء لو المستخدم ليس مديرًا.
    استخدمها داخل المعالجات حيث تريد إنهاء التنفيذ فورًا.
    """
    if not is_admin(uid):
        raise PermissionError("Admin privileges required")


def get_admin_channel_id() -> Optional[int]:
    """
    يرجّع معرف قناة/مجموعة للإشعارات الإدارية إن محدّد بمتغير:
    ADMIN_CHANNEL_ID أو ADMIN_CHANNEL أو OWNERS_CHANNEL_ID.
    يقبل -100… للقنوات الفائقة.
    """
    for key in ("ADMIN_CHANNEL_ID", "ADMIN_CHANNEL", "OWNERS_CHANNEL_ID"):
        val = os.getenv(key)
        if not val:
            continue
        val = val.strip()
        if val.lstrip("-").isdigit():
            try:
                return int(val)
            except Exception:
                continue
    return None
