# utils/secrets.py
from __future__ import annotations
import os, json
from pathlib import Path

# نقرأ من BASE إن توفر، وإلا مواقع شائعة
try:
    from utils.paths import BASE
    _DATA_BASE = BASE
except Exception:
    _DATA_BASE = Path("/data")

_ENV_CANDIDATES = [
    _DATA_BASE / ".env",
    _DATA_BASE / "config.env",
    Path("./.env"),
]
_JSON_CANDIDATES = [
    _DATA_BASE / "config.json",
    Path("./config.json"),
]

def _load_dotenv(path: Path) -> dict:
    data = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return data

def _load_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def preload_env() -> None:
    """حمّل الأسرار من ملفاتك إلى os.environ قبل أي import آخر (بدون الكتابة فوق الموجود)."""
    for p in _ENV_CANDIDATES:
        if p.exists():
            for k, v in _load_dotenv(p).items():
                os.environ.setdefault(k, str(v))
    for p in _JSON_CANDIDATES:
        if p.exists():
            for k, v in _load_json(p).items():
                os.environ.setdefault(str(k), str(v))
