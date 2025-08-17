# utils_language.py
"""
Compatibility shim for legacy imports.

Primary: re-export from `lang.py` (single source of truth).
Fallback: minimal local implementations (EN/AR only) if `lang.py` is unavailable.

Env vars (fallback only):
- DEFAULT_LANG=en|ar          → default language (default: en)
- ALLOWED_LANGS=en,ar         → whitelist (default: en,ar)
"""

from __future__ import annotations

import os
import json
from typing import Optional

# ====== محاولة الاستيراد من المصدر الموحّد ======
try:
    # ✅ المصدر الموحّد — إن وُجد نستعمله كما هو
    from lang import t, get_user_lang, set_user_lang, reload_locales  # type: ignore
    __all__ = ["t", "get_user_lang", "set_user_lang", "reload_locales"]
except Exception:
    # ====== خطة بديلة خفيفة (EN/AR فقط) ======
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    USER_LANG_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "user_langs.json"))

    # من البيئة (fallback فقط)
    _env_default = (os.getenv("DEFAULT_LANG") or "en").strip().lower()
    DEFAULT_LANG = "ar" if _env_default.startswith("ar") else "en"

    _env_allowed = (os.getenv("ALLOWED_LANGS") or "en,ar").strip().lower()
    ALLOWED_LANGS = {x.strip() for x in _env_allowed.split(",") if x.strip() in {"en", "ar"}}
    if not ALLOWED_LANGS:
        ALLOWED_LANGS = {"en", "ar"}

    def _normalize_lang(code: Optional[str]) -> str:
        """
        Normalize to 'en' or 'ar' only.
        - Accepts 'en', 'ar', and variants like 'en-US', 'ar-SA'.
        - Anything else falls back to DEFAULT_LANG.
        """
        if not code:
            return DEFAULT_LANG
        c = str(code).strip().lower()
        if "-" in c:
            c = c.split("-", 1)[0]
        if c in ALLOWED_LANGS:
            return c
        if c.startswith("ar"):
            return "ar"
        if c.startswith("en"):
            return "en"
        return DEFAULT_LANG

    def _atomic_write(path: str, data: dict) -> None:
        tmp = path + ".tmp"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # -------- API fallback --------
    def get_user_lang(user_id: int) -> str:
        try:
            with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                return _normalize_lang(data.get(str(user_id), DEFAULT_LANG))
        except FileNotFoundError:
            return DEFAULT_LANG
        except Exception:
            return DEFAULT_LANG

    def t(lang: str, key: str) -> str:
        """
        Minimal translator fallback:
        - Returns the key itself as a safe placeholder.
        - Real translations should come from `lang.py`.
        """
        # يمكن لاحقًا توسيعه لإرجاع نصوص أساسية لو أردت.
        return key

    def set_user_lang(user_id: int, lang_code: str) -> None:
        code = _normalize_lang(lang_code)
        try:
            data = {}
            if os.path.exists(USER_LANG_FILE):
                with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            data[str(user_id)] = code
            _atomic_write(USER_LANG_FILE, data)
        except Exception:
            # لا نرفع استثناءات — fallback يجب ألا يكسر المنطق
            pass

    def reload_locales() -> None:
        # لا شيء في وضع fallback — موجودة فقط لتوافق الواجهة
        return

    __all__ = ["t", "get_user_lang", "set_user_lang", "reload_locales"]
