# utils/home_card_cfg.py
from __future__ import annotations
import json
from pathlib import Path

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE = DATA_DIR / "home_ui_cfg.json"

DEFAULT_CFG = {
    "theme": "neo",       # neo | glass | chip | plaque | banner | receipt
    "density": "comfy",   # comfy | compact
    "sep": "soft",        # soft | hard
    "icons": "modern",    # modern | classic
    "bullets": True,
    "tip": True,
    "version": True,
    "users": True,
    "alerts": True,
}

def get_cfg() -> dict:
    try:
        d = json.loads(CFG_FILE.read_text("utf-8"))
        if isinstance(d, dict):
            out = DEFAULT_CFG.copy()
            out.update(d)
            return out
    except Exception:
        pass
    return DEFAULT_CFG.copy()
