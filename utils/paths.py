# utils/paths.py
from __future__ import annotations
import os
from pathlib import Path

def _default_base() -> Path:
    env = (os.getenv("DATA_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if Path("/data").exists():
        return Path("/data").resolve()
    return Path(__file__).resolve().parents[1] / "data"

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
BASE: Path = _default_base()
BASE.mkdir(parents=True, exist_ok=True)

INVENTORY_DIR = BASE / "inventory"
USED_DIR      = BASE / "used"
for d in (INVENTORY_DIR, USED_DIR):
    d.mkdir(parents=True, exist_ok=True)

FLAGS_PATH  = BASE / "shop_flags.json"
SHOP_CFG    = BASE / "shop_config.json"
INV_BL_PATH = BASE / "inv_blacklist.json"

def safe_join(base: Path | str, *parts: str | os.PathLike, must_exist: bool = False) -> Path:
    b = Path(base).resolve()
    p = b
    for part in parts:
        p = p / Path(part)
    p = p.resolve()
    try:
        p.relative_to(b)
    except ValueError:
        raise ValueError(f"Refusing to access outside base: {p} not under {b}")
    if must_exist and not p.exists():
        raise FileNotFoundError(str(p))
    return p

# Compatibility aliases
shop_base      = BASE / "shop"
cache_base     = BASE / "cache"
inventory_base = INVENTORY_DIR
for d in (shop_base, cache_base, inventory_base):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

# Optional debug prints (set PATHS_DEBUG=1)
if (os.getenv("PATHS_DEBUG") or "").strip() == "1":
    try:
        print(f"[STORAGE] BASE={BASE}")
        print(f"[STORAGE] INVENTORY_DIR={INVENTORY_DIR}")
        print(f"[STORAGE] USED_DIR={USED_DIR}")
        print(f"[STORAGE] FLAGS_PATH={FLAGS_PATH}")
        print(f"[STORAGE] SHOP_CFG={SHOP_CFG}")
        print(f"[STORAGE] INV_BL_PATH={INV_BL_PATH}")
    except Exception:
        pass

__all__ = [
    "PROJECT_ROOT", "BASE",
    "INVENTORY_DIR", "USED_DIR",
    "FLAGS_PATH", "SHOP_CFG", "INV_BL_PATH",
    "safe_join",
    "shop_base", "cache_base", "inventory_base",
]
