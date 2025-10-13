# utils/maintenance_state.py
from __future__ import annotations
import os, json, tempfile
from pathlib import Path

try:
    from utils.paths import BASE
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "data")).resolve()

STATE_FILE = BASE / "maintenance_state.json"

def _safe_load() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text("utf-8")) or {}
    except Exception:
        pass
    return {}

def _safe_save(obj: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="maint_", suffix=".json", dir=str(STATE_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def is_enabled() -> bool:
    return bool(_safe_load().get("enabled", False))

def set_enabled(value: bool) -> None:
    d = _safe_load()
    d["enabled"] = bool(value)
    _safe_save(d)

def toggle() -> bool:
    v = not is_enabled()
    set_enabled(v)
    return v
