from __future__ import annotations

# utils/alerts_config.py


import os, json, threading, time
from pathlib import Path
from typing import Any, Dict

from utils.paths import BASE  # مجلد التخزين الدائم

ALERTS_DIR: Path = BASE / "alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE: Path = ALERTS_DIR / "alerts_config.json"

_LOCK = threading.Lock()

# القيم الافتراضية (كلها قابلة للتغيير من الأدمن)
_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "rate_limit": int(os.getenv("ALERTS_RATE_LIMIT", "20")),     # رسائل/ثانية
    "quiet_enabled": (os.getenv("ALERTS_QUIET_ENABLED", "1") not in {"0", "false", "False"}),
    "quiet_hours": os.getenv("ALERTS_QUIET_HOURS", "22:00-08:00"),  # يُتجاهل إذا quiet_enabled=False
    "max_per_week": int(os.getenv("ALERTS_MAX_PER_WEEK", "2")),
    "active_days": int(os.getenv("ALERTS_ACTIVE_DAYS", "120")),
    "tz": os.getenv("ALERTS_TZ", "Asia/Baghdad"),
}

def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.{int(time.time()*1000)}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload); f.flush()
        try: os.fsync(f.fileno())
        except Exception: pass
    os.replace(tmp, path)

def _load() -> Dict[str, Any]:
    if not CFG_FILE.exists():
        return {}
    try:
        raw = CFG_FILE.read_text("utf-8") or "{}"
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _save(d: Dict[str, Any]) -> None:
    _atomic_write(CFG_FILE, d)

def _coerce(cfg: Dict[str, Any]) -> Dict[str, Any]:
    d: Dict[str, Any] = {**_DEFAULTS, **(cfg or {})}

    d["enabled"] = bool(d.get("enabled"))
    d["quiet_enabled"] = bool(d.get("quiet_enabled"))

    try: d["rate_limit"] = max(1, min(100, int(d.get("rate_limit") or 10)))
    except Exception: d["rate_limit"] = 10

    try: d["max_per_week"] = max(0, int(d.get("max_per_week") or 2))
    except Exception: d["max_per_week"] = 2

    try: d["active_days"] = max(1, int(d.get("active_days") or 120))
    except Exception: d["active_days"] = 120

    d["quiet_hours"] = str(d.get("quiet_hours") or "22:00-08:00")
    d["tz"] = str(d.get("tz") or "Asia/Baghdad")
    return d

def get_config() -> Dict[str, Any]:
    with _LOCK:
        return _coerce(_load())

def set_config(patch: Dict[str, Any]) -> None:
    if not isinstance(patch, dict): return
    with _LOCK:
        cur = _load(); cur.update(patch or {})
        _save(_coerce(cur))
