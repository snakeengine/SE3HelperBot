# utils/admin_access.py
from __future__ import annotations
import os

def get_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: set[int] = set()
    for part in str(raw).replace(";", ",").split(","):
        p = part.strip()
        if p.lstrip("-").isdigit():
            ids.add(int(p))
    if not ids:
        ids = {7360982123}
    return ids

def is_admin(uid: int) -> bool:
    return uid in get_admin_ids()

def get_admin_channel_id() -> int | None:
    ch = os.getenv("ADMIN_CHANNEL_ID") or os.getenv("ADMIN_CHANNEL")
    if not ch:
        return None
    ch = ch.strip()
    return int(ch) if ch.lstrip("-").isdigit() else None
