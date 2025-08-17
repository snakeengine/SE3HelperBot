import json, os
from functools import lru_cache
from typing import Dict

_LOCALES_DIR = os.path.join(os.path.dirname(__file__), "..", "locales")
_FILES = {"en": "en.json", "ar": "ar.json"}

def _load(path: str) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@lru_cache(maxsize=2)
def _table(locale: str) -> Dict[str, str]:
    fname = _FILES.get(locale, _FILES["en"])
    return _load(os.path.join(_LOCALES_DIR, fname))

def t(key: str, locale: str = "en", **kwargs) -> str:
    table = _table(locale)
    s = table.get(key) or _table("en").get(key) or key
    return s.format(**kwargs) if kwargs else s

def reload_locales() -> None:
    """Call this if you edit JSON at runtime (clears cache)."""
    _table.cache_clear()
