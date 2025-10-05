# utils/secrets.py
from __future__ import annotations
import os, json
from pathlib import Path

_ENV_CANDIDATES = [
    Path("/data/.env"),
    Path("/data/config.env"),
    Path("./.env"),
]

_JSON_CANDIDATES = [
    Path("/data/config.json"),
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
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def preload_env():
    """حمّل الأسرار من ملفاتك إلى os.environ قبل أي import آخر."""
    # 1) .env
    for p in _ENV_CANDIDATES:
        if p.exists():
            for k, v in _load_dotenv(p).items():
                os.environ.setdefault(k, str(v))
    # 2) config.json (لو تبغى)
    for p in _JSON_CANDIDATES:
        if p.exists():
            for k, v in _load_json(p).items():
                os.environ.setdefault(str(k), str(v))
