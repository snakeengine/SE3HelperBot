from utils.admins import get_admin_ids, is_admin, get_owner_ids
# utils/admins.py
from __future__ import annotations
import os, re, json, logging
from pathlib import Path

log = logging.getLogger(__name__)

# -------- Ù…Ø³Ø§Ø± Ø§Ù„ØªØ®Ø²ÙŠÙ† --------
try:
    from utils.paths import BASE  # ÙŠÙØ¶Ù‘Ù„ Ø£Ù† ÙŠØ´ÙŠØ± Ø¥Ù„Ù‰ /data Ø¹Ù„Ù‰ Ø§Ù„Ø³ÙŠØ±ÙØ±
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "/data")).resolve()

ADMIN_STORE: Path = BASE / "admins.json"
ADMIN_STORE.parent.mkdir(parents=True, exist_ok=True)

# -------- Ø£Ø¯ÙˆØ§Øª Ù…Ø³Ø§Ø¹Ø¯Ø© --------
def _parse_ids(s: str | None) -> list[int]:
    """ÙŠÙØµÙ„ Ø¹Ù„Ù‰ ÙØ§ØµÙ„Ø©/Ù…Ø³Ø§ÙØ©/Ø³Ø·Ø± ÙˆÙŠØªØ¬Ø§Ù‡Ù„ Ø§Ù„Ø¶Ø¬ÙŠØ¬ØŒ ÙˆÙŠØ²ÙŠÙ„ Ø§Ù„ØªÙƒØ±Ø§Ø± Ù…Ø¹ Ø§Ù„Ø­ÙØ§Ø¸ Ø¹Ù„Ù‰ Ø§Ù„ØªØ±ØªÙŠØ¨."""
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
    """Ù‚Ø±Ø§Ø¡Ø© Ø£ÙˆÙ„ÙŠØ© Ù…Ù† Ù…ØªØºÙŠØ±Ø§Øª Ø§Ù„Ø¨ÙŠØ¦Ø©."""
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
    # Ø¯ÙˆÙ…Ø§Ù‹ Ø§ÙƒØªØ¨ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ Ø§Ù„Ù‚ÙŠØ§Ø³ÙŠØ© + Ù†Ø³Ø®Ø© Ø¸Ù„ Ù„Ù„ØªÙˆØ§ÙÙ‚
    payload = {
        "owners": list(dict.fromkeys(data.get("owners", []))),
        "admins": list(dict.fromkeys(data.get("admins", []))),
    }
    # alias Ù„Ù„ØªÙˆØ§ÙÙ‚ Ù…Ø¹ Ø£ÙŠ ÙƒÙˆØ¯ Ù‚Ø¯ÙŠÙ… ÙŠÙ‚Ø±Ø£ admin_ids
    payload["admin_ids"] = list(payload["admins"])
    ADMIN_STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_store() -> dict:
    if ADMIN_STORE.exists():
        try:
            data = json.loads(ADMIN_STORE.read_text(encoding="utf-8"))
            # Ø·Ø¨Ù‘Ø¹ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ Ø§Ù„Ù…Ø­ØªÙ…Ù„Ø©
            owners = data.get("owners") or []
            admins = data.get("admins") or data.get("admin_ids") or []
            return {"owners": owners, "admins": admins}
        except Exception:
            pass
    # Ø¥Ù† Ù„Ù… ÙŠÙˆØ¬Ø¯ Ù…Ù„ÙØ› Ù†Ø¨Ù†ÙŠÙ‡ Ù…Ù† Ø§Ù„Ø¨ÙŠØ¦Ø© ÙˆÙ†ÙƒØªØ¨Ù‡
    owners_env, admins_env = _env_admins()
    payload = {"owners": owners_env, "admins": admins_env}
    _save_store(payload)
    return payload

# -------- Ø§Ù„Ø­Ø§Ù„Ø© Ø§Ù„Ø­Ø§Ù„ÙŠØ© ÙÙŠ Ø§Ù„Ø°Ø§ÙƒØ±Ø© --------
_state = _load_store()

def reload_from_disk() -> None:
    """Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„ØªØ­Ù…ÙŠÙ„ Ù…Ù† Ø§Ù„Ù…Ù„Ù ÙŠØ¯ÙˆÙŠØ§Ù‹."""
    global _state, OWNERS, ADMIN_IDS
    _state = _load_store()
    OWNERS = list(_state.get("owners", []))
    # Ø§Ø¬Ø¹Ù„ ADMIN_IDS = Ø§ØªØ­Ø§Ø¯ (owners + admins) Ø­ØªÙ‰ Ù†Ø¶Ù…Ù† Ø§Ù„ØµÙ„Ø§Ø­ÙŠØ§Øª
    ADMIN_IDS = list(dict.fromkeys((_state.get("owners", []) or []) + (_state.get("admins", []) or [])))

def _sync_env_into_store() -> None:
    """Ø§Ø¯Ù…Ø¬ Ù…Ø§ ÙÙŠ Ø§Ù„Ø¨ÙŠØ¦Ø© (OWNERS/ADMIN_IDS) Ù…Ø¹ Ø§Ù„Ù…Ù„Ù Ø§Ù„Ø­Ø§Ù„ÙŠØŒ Ø«Ù… Ø§Ø­ÙØ¸ Ø¥Ø°Ø§ ØªØºÙŠÙ‘Ø±."""
    owners_env, admins_env = _env_admins()

    owners = list(dict.fromkeys((_state.get("owners", []) or []) + owners_env))
    admins = list(dict.fromkeys((_state.get("admins", []) or []) + admins_env))

    new_state = {"owners": owners, "admins": admins}
    if new_state != {"owners": _state.get("owners", []), "admins": _state.get("admins", [])}:
        _save_store(new_state)
        _state.update(new_state)

# Ù†ÙÙ‘Ø° Ø§Ù„Ù…Ø²Ø§Ù…Ù†Ø© ÙÙˆØ± Ø§Ù„ØªØ­Ù…ÙŠÙ„
_sync_env_into_store()

# Ù…ÙƒØ´ÙˆÙØ© Ù„Ù„ØªÙˆØ§ÙÙ‚ Ù…Ø¹ Ø§Ù„ÙƒÙˆØ¯ Ø§Ù„Ù‚Ø¯ÙŠÙ…
OWNERS: list[int] = list(_state.get("owners", []))
# IMPORTANT: Ù†Ø®Ù„ÙŠ ADMIN_IDS = Ø§ØªØ­Ø§Ø¯ (owners + admins) Ù„ØªØºØ·ÙŠØ© ÙƒÙ„ ØµÙ„Ø§Ø­ÙŠØ§Øª Ø§Ù„Ø£Ø¯Ù…Ù†
ADMIN_IDS: list[int] = list(dict.fromkeys((_state.get("owners", []) or []) + (_state.get("admins", []) or [])))

def list_admins() -> tuple[list[int], list[int]]:
    """(owners, admins) â€” admins Ù‡Ù†Ø§ Ù‡ÙŠ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…Ø®Ø²Ù†Ø© (ØºÙŠØ± Ù…ØªÙ‘Ø­Ø¯Ø© Ù…Ø¹ owners)."""
    return list(_state.get("owners", [])), list(_state.get("admins", []))

def is_admin(uid: int | str) -> bool:
    try:
        n = int(uid)
    except Exception:
        return False
    # Ù†Ø¹ØªØ¨Ø± Ø§Ù„Ù…Ø§Ù„Ùƒ Ø£Ø¯Ù…Ù† ØªÙ„Ù‚Ø§Ø¦ÙŠØ§Ù‹
    return n in ADMIN_IDS

def add_admin(uid: int | str, *, owner: bool = False) -> bool:
    """ÙŠØ¶ÙŠÙ Ø¢ÙŠ Ø¯ÙŠ ÙƒØ£Ø¯Ù…Ù† (Ø£Ùˆ Ù…Ø§Ù„Ùƒ Ø¥Ø°Ø§ owner=True). ÙŠØ±Ø¬Ù‘Ø¹ True Ù„Ùˆ Ø£Ø¶ÙŠÙ Ø¬Ø¯ÙŠØ¯."""
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
        # Ù„ÙŠØ³ Ø¶Ø±ÙˆØ±ÙŠØ§Ù‹ ÙˆØ¬ÙˆØ¯Ù‡ ÙƒØ£Ø¯Ù…Ù† Ø£ÙŠØ¶Ø§Ù‹ØŒ Ù„ÙƒÙ†Ù‡ Ø³ÙŠØ¸Ù‡Ø± Ø¶Ù…Ù† ADMIN_IDS Ø¹Ø¨Ø± Ø§Ù„Ø§ØªØ­Ø§Ø¯
        if n in admins:
            admins.remove(n)
    else:
        if n not in owners and n not in admins:
            admins.append(n)

    _state["owners"] = list(dict.fromkeys(owners))
    _state["admins"] = list(dict.fromkeys(admins))
    _save_store(_state)

    # Ø­Ø¯Ù‘Ø« Ø§Ù„Ù…ØµØ¯Ù‘Ø±Ø§Øª
    reload_from_disk()
    return not existed

def remove_admin(uid: int | str, *, allow_owner: bool = False) -> bool:
    """ÙŠØ­Ø°Ù Ù…Ù† Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø£Ø¯Ù…Ù†. Ù„Ùˆ allow_owner=True ÙŠØ­Ø°Ù Ù…Ù† Ø§Ù„Ù…Ø§Ù„ÙƒÙŠÙ† Ø£ÙŠØ¶Ø§Ù‹."""
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

    # ØªØ­Ø¯ÙŠØ« Ø§Ù„Ù…ØµØ¯Ù‘Ø±Ø§Øª
    reload_from_disk()
    return removed

# Ø·Ø¨Ø§Ø¹Ø© ØªØ´Ø®ÙŠØµÙŠØ© Ø¹Ù†Ø¯ Ø§Ù„ØªØ­Ù…ÙŠÙ„
print(f"[ADMIN] OWNERS={OWNERS} | ADMIN_IDS={ADMIN_IDS} | store={ADMIN_STORE}")
log.info("[ADMIN] EXPORT OWNERS=%s ADMIN_IDS=%s", OWNERS, ADMIN_IDS)

