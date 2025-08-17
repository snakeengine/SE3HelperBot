# utils/maintenance_state.py
import json, os, tempfile

STATE_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "maintenance_state.json"))

def _safe_load() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _safe_save(obj: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="maint_", suffix=".json")
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

def set_enabled(value: bool):
    data = _safe_load()
    data["enabled"] = bool(value)
    _safe_save(data)

def toggle() -> bool:
    new_val = not is_enabled()
    set_enabled(new_val)
    return new_val
