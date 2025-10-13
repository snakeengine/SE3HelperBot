# utils/admins_bootstrap.py
from __future__ import annotations
import os, json, pathlib, logging

log = logging.getLogger("admins.bootstrap")

def _parse_ids(s: str) -> list[int]:
    out = []
    for p in (s or "").split(","):
        p = p.strip()
        if p.isdigit():
            out.append(int(p))
    return out

def ensure_admin_store(path: str = "/data/admins.json") -> None:
    """يكتب owners/admins إلى /data/admins.json من متغيرات البيئة لو مفقود أو مختلف."""
    owners = _parse_ids(os.getenv("OWNERS", ""))
    admins = _parse_ids(os.getenv("ADMIN_IDS", "")) or owners[:]  # fallback

    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        current = {}
        if p.exists():
            try:
                current = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                current = {}

        desired = {"owners": owners, "admins": admins}
        if current != desired:
            p.write_text(json.dumps(desired, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("[ADMIN] bootstrap wrote %s -> %s", p, desired)
        else:
            log.info("[ADMIN] bootstrap OK (no change) %s", p)
    except Exception as e:
        log.warning("[ADMIN] bootstrap failed: %s", e)
