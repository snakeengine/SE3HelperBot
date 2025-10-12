# utils/admins.py
from __future__ import annotations
import os, re

def _parse_ids(s: str | None) -> list[int]:
    if not s:
        return []
    ids = set()
    for part in re.split(r"[,\s]+", s.strip()):
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return sorted(ids)

# اقرأ من ADMIN_IDS فقط (لا نخلطه مع ADMIN_ID حتى لا يطغى قيمة مفردة)
RAW_ADMIN_IDS = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = _parse_ids(RAW_ADMIN_IDS)

def is_admin(uid: int | str) -> bool:
    try:
        return int(uid) in ADMIN_IDS
    except Exception:
        return False
