# 📁 utils/translation.py
"""
Thin wrapper around `lang.py` so old imports keep working.

Primary path: use `lang.t` / `lang.get_user_lang`.
Fallback path: lightweight loader from ./locales if `lang.py` is unavailable.
"""

from __future__ import annotations
import os, json, threading

try:
    # ✅ المصدر الموحّد
    from lang import t as _t_lang, get_user_lang as _get_user_lang, reload_locales as _reload_locales  # type: ignore

    def t(lang_code: str, key: str) -> str:
        return _t_lang(lang_code, key)

    def tf(lang_code: str, key: str, **kwargs) -> str:
        # ترجمة مع .format(**kwargs)
        try:
            return _t_lang(lang_code, key).format(**kwargs)
        except Exception:
            return _t_lang(lang_code, key)

    def get_user_lang(user_id: int) -> str:
        return _get_user_lang(user_id)

    def reload_translations() -> None:
        _reload_locales()

except Exception:
    # ⚠️ fallback: قارئ JSON بسيط مع كاش وقفل وخيار reload
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    LOCALES_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "locales"))
    DEFAULT_LANG = "en"

    _LOCK = threading.RLock()
    _CACHE: dict[str, dict] = {}

    def _normalize_lang(code: str | None) -> str:
        if not code:
            return DEFAULT_LANG
        code = str(code).strip().lower()
        if "-" in code:
            code = code.split("-", 1)[0]
        return code

    def _load_one(lang: str) -> dict:
        path = os.path.join(LOCALES_DIR, f"{lang}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _get(lang: str) -> dict:
        lang = _normalize_lang(lang)
        with _LOCK:
            if lang not in _CACHE:
                _CACHE[lang] = _load_one(lang)
            return _CACHE[lang]

    def reload_translations() -> None:
        with _LOCK:
            _CACHE.clear()

    def t(lang_code: str, key: str) -> str:
        lang_code = _normalize_lang(lang_code)
        val = _get(lang_code).get(key)
        if isinstance(val, str):
            return val
        if lang_code != DEFAULT_LANG:
            val = _get(DEFAULT_LANG).get(key)
            if isinstance(val, str):
                return val
        return key

    def tf(lang_code: str, key: str, **kwargs) -> str:
        try:
            return t(lang_code, key).format(**kwargs)
        except Exception:
            return t(lang_code, key)

    # اختياري: لو فيه استدعاءات قديمة تحتاجها
    def get_user_lang(user_id: int) -> str:
        # بدون ملف المستخدمين هنا؛ ارجع الإنجليزية كافتراضي
        return DEFAULT_LANG
