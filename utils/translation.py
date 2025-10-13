from __future__ import annotations

# 📁 utils/translation.py
"""
Thin wrapper around `lang.py` so old imports keep working.

Primary path: use `lang.t` / `lang.get_user_lang`.
Fallback path: lightweight loader from ../locales with safe caching & mtime watch.
"""

import os
import json
import threading
from pathlib import Path
from typing import Dict, Optional

# ========================= Primary (preferred) =========================
try:
    # ✅ Single source of truth
    from lang import (  # type: ignore
        t as _t_lang,
        get_user_lang as _get_user_lang,
        reload_locales as _reload_locales,
    )

    def t(lang_code: str, key: str) -> str:
        return _t_lang(lang_code, key)

    def tf(lang_code: str, key: str, **kwargs) -> str:
        try:
            return _t_lang(lang_code, key).format(**kwargs)
        except Exception:
            return _t_lang(lang_code, key)

    def get_user_lang(user_id: int) -> str:
        return _get_user_lang(user_id)

    def reload_translations() -> None:
        _reload_locales()

# ========================= Fallback (self-contained) =========================
except Exception:
    # Project root (…/repo) = parent of this utils/ folder
    PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

    # Allow overriding locales dir via env
    _ENV_LOCALES = (os.getenv("LOCALES_DIR") or os.getenv("APP_LOCALES_DIR") or "").strip()
    LOCALES_DIR: Path = (Path(_ENV_LOCALES) if _ENV_LOCALES else (PROJECT_ROOT / "locales")).resolve()

    USER_LANG_FILE: Path = (PROJECT_ROOT / "user_langs.json").resolve()

    DEFAULT_LANG = "en"
    ALLOWED = {"en", "ar"}

    _LOCK = threading.RLock()
    _CACHE: Dict[str, Dict[str, str]] = {}
    _MTIME: Dict[str, float] = {}

    def _normalize_lang(code: Optional[str]) -> str:
        """Normalize to 'en' or 'ar' only; fallback to 'en'."""
        if not code:
            return DEFAULT_LANG
        c = str(code).strip().lower()
        if "-" in c:
            c = c.split("-", 1)[0]
        if c.startswith("ar"):
            return "ar"
        if c.startswith("en"):
            return "en"
        return DEFAULT_LANG

    def _locale_path(lang: str) -> Path:
        return (LOCALES_DIR / f"{lang}.json").resolve()

    def _read_json(path: Path) -> Dict[str, str]:
        """
        Accepts flat dict or {"strings": {...}}. Non-string values are ignored.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if isinstance(raw, dict):
            # Prefer nested {"strings": {...}} if present
            src = raw.get("strings", raw)
            if isinstance(src, dict):
                # Keep only string->string
                return {str(k): str(v) for k, v in src.items() if isinstance(k, str) and isinstance(v, str)}
        return {}

    def _load_one(lang: str) -> Dict[str, str]:
        p = _locale_path(lang)
        if not p.exists():
            return {}
        data = _read_json(p)
        # Minimal built-ins (very small, avoids empty UI when locales missing)
        minimal_en = {
            "choose_language": "Choose your language:",
            "language_changed": "Language updated ✅",
        }
        minimal_ar = {
            "choose_language": "اختر لغتك:",
            "language_changed": "تم تحديث اللغة ✅",
        }
        if lang == "en":
            return {**minimal_en, **data}
        if lang == "ar":
            return {**minimal_ar, **data}
        return data

    def _get(lang: str) -> Dict[str, str]:
        """
        Load with mtime watch: if file changed on disk, refresh cache.
        """
        lang = _normalize_lang(lang)
        with _LOCK:
            p = _locale_path(lang)
            mtime = p.stat().st_mtime if p.exists() else -1.0
            if lang not in _CACHE or _MTIME.get(lang) != mtime:
                _CACHE[lang] = _load_one(lang)
                _MTIME[lang] = mtime
            return _CACHE[lang]

    def reload_translations() -> None:
        with _LOCK:
            _CACHE.clear()
            _MTIME.clear()

    def t(lang_code: str, key: str) -> str:
        lang_code = _normalize_lang(lang_code)
        val = _get(lang_code).get(key)
        if isinstance(val, str) and val:
            return val
        if lang_code != DEFAULT_LANG:
            val = _get(DEFAULT_LANG).get(key)
            if isinstance(val, str) and val:
                return val
        return key  # last-resort: show key for easier debugging

    def tf(lang_code: str, key: str, **kwargs) -> str:
        try:
            return t(lang_code, key).format(**kwargs)
        except Exception:
            return t(lang_code, key)

    def get_user_lang(user_id: int) -> str:
        """
        Fallback: read simple JSON map { "<uid>": "en|ar", ... } from project root.
        """
        try:
            data = json.loads(USER_LANG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _normalize_lang(data.get(str(int(user_id))))
        except Exception:
            pass
        return DEFAULT_LANG
