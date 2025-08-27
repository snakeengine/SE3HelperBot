# utils_language.py
"""
Compatibility shim for legacy imports.

Primary: re-export from `lang.py` (single source of truth).
Fallback: loads from ./locales/en.json & ./locales/ar.json (flat dict), with a minimal built-in EN/AR set.

Notes:
- Default language is *forced* to English in fallback to avoid accidental flips.
- Shares the same user_langs.json location/policy as lang.py (project root).
"""

from __future__ import annotations
import os, json
from pathlib import Path
from typing import Optional, Dict

# ====== Try primary module (preferred) ======
try:
    from lang import t, get_user_lang, set_user_lang, reload_locales  # type: ignore
    __all__ = ["t", "get_user_lang", "set_user_lang", "reload_locales"]
except Exception:
    # ====== Fallback implementation (EN/AR only) ======

    BASE_DIR = Path(__file__).resolve().parent  # project root (same dir as lang.py)
    USER_LANG_FILE = BASE_DIR / "user_langs.json"

    # Force default EN in fallback
    DEFAULT_LANG = "en"
    ALLOWED_LANGS = {"en", "ar"}

    # Look for ./locales (same as lang.py)
    LOCALES_DIR = BASE_DIR / "locales"

    # ---- helpers ----
    def _normalize_lang(code: Optional[str]) -> str:
        """Normalize to 'en' or 'ar' only; fallback: 'en'."""
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

    def _atomic_write(path: Path, data: dict) -> None:
        tmp = Path(str(path) + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ---- locales store ----
    _LOCALES: Dict[str, Dict[str, str]] = {"en": {}, "ar": {}}

    _EMBEDDED_MINIMAL = {
        "en": {
            # Commands
            "cmd_start": "Start",
            "cmd_help": "Help",
            "cmd_about": "About",
            "cmd_report": "Report a problem",
            "cmd_language": "Language",
            "cmd_sections": "Quick sections",
            "cmd_alerts": "Alerts",
            "cmd_admin_center": "Admin Center",

            # Language UI
            "btn_lang_en": "English",
            "btn_lang_ar": "Arabic",
            "choose_language": "Choose your language:",
            "language_changed": "Language updated ✅",
            "back_to_menu": "Back to menu",
            "menu.keyboard_ready": "Menu ready ⬇️",
        },
        "ar": {
            # Commands
            "cmd_start": "بدء البوت",
            "cmd_help": "مساعدة",
            "cmd_about": "حول البوت",
            "cmd_report": "بلاغ/شكوى",
            "cmd_language": "اللغة",
            "cmd_sections": "الأقسام السريعة",
            "cmd_alerts": "الإشعارات",
            "cmd_admin_center": "مركز الإدارة",

            # Language UI
            "btn_lang_en": "الإنجليزية",
            "btn_lang_ar": "العربية",
            "choose_language": "اختر لغتك:",
            "language_changed": "تم تحديث اللغة ✅",
            "back_to_menu": "العودة للقائمة",
            "menu.keyboard_ready": "تم تجهيز القائمة بالأسفل ⬇️",
        },
    }

    def _load_lang_file(lang_code: str) -> Dict[str, str]:
        """Load locales/<code>.json if exists (flat dict), else {}."""
        try:
            p = LOCALES_DIR / f"{lang_code}.json"
            if p.exists():
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                # accept flat dict or {"strings":{...}}
                return data.get("strings", data) if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _ensure_locales_loaded() -> None:
        """Load locales into _LOCALES once (or after reload)."""
        en = _load_lang_file("en")
        ar = _load_lang_file("ar")
        _LOCALES["en"] = {**_EMBEDDED_MINIMAL["en"], **(en or {})}
        _LOCALES["ar"] = {**_EMBEDDED_MINIMAL["ar"], **(ar or {})}

    _ensure_locales_loaded()

    # -------- API: get/set user lang --------
    def get_user_lang(user_id: int) -> str:
        try:
            with USER_LANG_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f) or {}
                return _normalize_lang(data.get(str(user_id), DEFAULT_LANG))
        except FileNotFoundError:
            return DEFAULT_LANG
        except Exception:
            return DEFAULT_LANG

    def set_user_lang(user_id: int, lang_code: str) -> None:
        code = _normalize_lang(lang_code)
        try:
            data = {}
            if USER_LANG_FILE.exists():
                with USER_LANG_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            data[str(user_id)] = code
            _atomic_write(USER_LANG_FILE, data)
        except Exception:
            pass  # never break

    # -------- API: translator --------
    def t(lang: str, key: str) -> str:
        """Translate key using loaded locales; fallback EN; final: key."""
        lc = _normalize_lang(lang)
        v = _LOCALES.get(lc, {}).get(key)
        if isinstance(v, str) and v:
            return v
        v = _LOCALES.get("en", {}).get(key)
        if isinstance(v, str) and v:
            return v
        return key

    def reload_locales() -> None:
        _ensure_locales_loaded()

    __all__ = ["t", "get_user_lang", "set_user_lang", "reload_locales"]
