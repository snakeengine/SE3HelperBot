# utils_language.py
"""
Compatibility shim for legacy imports.

Primary: re-export from `lang.py` (single source of truth).
Fallback: loads from ./locales/en.json & ./locales/ar.json (flat dict), with a minimal built-in EN/AR set.

Improvements:
- Smarter resolution for user_langs.json (prefers BASE/data).
- Safe atomic writes (uses utils.json_box if available).
- Looks for locales under BASE/locales then ./locales.
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

    # --- discover BASE (shared data root) ---
    try:
        from utils.paths import BASE  # type: ignore
    except Exception:
        BASE = Path(os.getenv("DATA_DIR", "data")).resolve()

    # --- json helpers (atomic write if available) ---
    try:
        from utils.json_box import load_json as _jb_load, save_json as _jb_save  # type: ignore
    except Exception:
        _jb_load = _jb_save = None  # type: ignore

    def _atomic_write(path: Path, data: dict) -> None:
        if _jb_save:
            _jb_save(path, data)
            return
        tmp = Path(str(path) + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _atomic_read(path: Path, default):
        if _jb_load:
            return _jb_load(path, default)
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            return default

    # --- choose user_langs.json location (prefer data/ or BASE) ---
    CANDIDATE_LANG_FILES = [
        BASE / "user_langs.json",
        BASE / "data" / "user_langs.json",
        Path("data/user_langs.json"),
        Path("user_langs.json"),
    ]
    _chosen = None
    for cand in CANDIDATE_LANG_FILES:
        if cand.exists():
            _chosen = cand
            break
    USER_LANG_FILE = _chosen or (BASE / "user_langs.json")

    # --- locales location (prefer BASE/locales, then ./locales) ---
    LOCALES_DIRS = [
        BASE / "locales",
        Path(__file__).resolve().parent / "locales",
        Path("locales"),
    ]

    # Force default EN in fallback
    DEFAULT_LANG = "en"
    ALLOWED_LANGS = {"en", "ar"}

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

    def _load_lang_file_from(dir_path: Path, lang_code: str) -> Dict[str, str]:
        try:
            p = dir_path / f"{lang_code}.json"
            if p.exists():
                data = _atomic_read(p, {}) or {}
                return data.get("strings", data) if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _load_lang_file(lang_code: str) -> Dict[str, str]:
        for d in LOCALES_DIRS:
            res = _load_lang_file_from(d, lang_code)
            if res:
                return res
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
        data = _atomic_read(USER_LANG_FILE, {}) or {}
        return _normalize_lang(data.get(str(user_id), DEFAULT_LANG))

    def set_user_lang(user_id: int, lang_code: str) -> None:
        code = _normalize_lang(lang_code)
        data = _atomic_read(USER_LANG_FILE, {}) or {}
        data[str(user_id)] = code
        _atomic_write(USER_LANG_FILE, data)

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
