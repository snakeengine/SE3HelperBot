# utils/alerts_config.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Any, Dict

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE  = DATA_DIR / "alerts_config.json"

_DEFAULTS = {
    "enabled": True,
    "rate_limit": int(os.getenv("ALERTS_RATE_LIMIT", "20")),
    "quiet_hours": os.getenv("ALERTS_QUIET_HOURS", "22:00-08:00"),
    "max_per_week": int(os.getenv("ALERTS_MAX_PER_WEEK", "2")),
    "active_days": int(os.getenv("ALERTS_ACTIVE_DAYS", "120")),
    "tz": os.getenv("ALERTS_TZ", "Asia/Baghdad"),
}

def _load() -> Dict[str, Any]:
    try:
        data = json.loads(CFG_FILE.read_text("utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}

def _save(d: Dict[str, Any]) -> None:
    CFG_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def get_config() -> Dict[str, Any]:
    d = {**_DEFAULTS, **_load()}
    # ensure types
    d["enabled"] = bool(d.get("enabled"))
    d["rate_limit"] = int(d.get("rate_limit") or 10)
    d["max_per_week"] = int(d.get("max_per_week") or 2)
    d["active_days"] = int(d.get("active_days") or 120)
    d["quiet_hours"] = str(d.get("quiet_hours") or "22:00-08:00")
    d["tz"] = str(d.get("tz") or "Asia/Baghdad")
    return d

def set_config(patch: Dict[str, Any]) -> None:
    d = get_config()
    d.update(patch or {})
    _save(d)
