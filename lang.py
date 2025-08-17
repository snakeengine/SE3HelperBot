# 📁 lang.py
import json
import os
import threading

# ===== إعدادات عامة =====
# اللغات المسموح بها فقط
ALLOWED_LANGS = {"en", "ar"}

# يمكن ضبط الافتراضي عبر .env، وإن كانت قيمة غير مسموحة → "en"
_ENV_DEFAULT = os.getenv("DEFAULT_LANG", "en").strip().lower()
_DEFAULT_LANG = _ENV_DEFAULT if _ENV_DEFAULT in ALLOWED_LANGS else "en"

# مسارات
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")
USER_LANG_FILE = os.path.join(BASE_DIR, "user_langs.json")

_LOCK = threading.RLock()
_translations: dict[str, dict] = {}
_known_langs: set[str] = set()  # اللغات المحمّلة فعليًا من ALLOWED_LANGS


def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _normalize_lang(code: str | None) -> str:
    """
    يختزل مثل 'en-US' → 'en' ويقصر على اللغات المسموح بها فقط.
    أي قيمة غير معروفة تُعادَل الافتراضي (_DEFAULT_LANG).
    """
    if not code:
        return _DEFAULT_LANG
    code = str(code).strip().lower()
    if "-" in code:
        code = code.split("-", 1)[0]
    # تطبيع سريع للمدخلات الشائعة
    if code.startswith("ar"):
        code = "ar"
    elif code.startswith("en"):
        code = "en"
    # حصر على المسموح
    return code if code in ALLOWED_LANGS else _DEFAULT_LANG


def load_translations() -> dict[str, dict]:
    """
    تحميل ملفات locales/<lang>.json للغات المسموح بها فقط.
    """
    translations: dict[str, dict] = {}
    if not os.path.isdir(LOCALES_DIR):
        return {_DEFAULT_LANG: {}}

    for filename in os.listdir(LOCALES_DIR):
        if not filename.endswith(".json"):
            continue
        lang_code = filename[:-5].strip().lower()
        if lang_code not in ALLOWED_LANGS:
            # نتجاهل أي ملفات غير en/ar حتى لو وجدت داخل المجلد
            continue
        path = os.path.join(LOCALES_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    translations[lang_code] = data
        except Exception:
            # تجاهل أي ملف تالف بدون كسر التحميل
            continue

    # تأكيد وجود خريطة للغة الافتراضية
    translations.setdefault(_DEFAULT_LANG, {})
    return translations


def reload_locales() -> None:
    """إعادة تحميل ملفات الترجمة من القرص (EN/AR فقط)."""
    global _translations, _known_langs
    with _LOCK:
        _translations = load_translations()
        # لا نُعلن إلا اللغات التي تم تحميلها فعليًا
        _known_langs = set(_translations.keys()).intersection(ALLOWED_LANGS)


# تحميل أولي
reload_locales()


def available_languages() -> list[str]:
    """اللغات المتاحة فعليًا (محصورة في ALLOWED_LANGS)."""
    with _LOCK:
        langs = _known_langs or { _DEFAULT_LANG }
        return sorted(langs)


def t(lang_code: str, key: str) -> str:
    """
    ترجمة مفتاح مع fallback للإنجليزية ثم المفتاح نفسه إن لم يوجد.
    """
    if not key:
        return ""
    lang_code = _normalize_lang(lang_code)
    with _LOCK:
        # محاولة لغة المستخدم
        lang_map = _translations.get(lang_code)
        if isinstance(lang_map, dict) and key in lang_map:
            val = lang_map.get(key)
            return val if isinstance(val, str) else key
        # فولباك الإنجليزية
        val = _translations.get("en", {}).get(key)
        return val if isinstance(val, str) else key


def tf(lang_code: str, key: str, **kwargs) -> str:
    """t() + format(**kwargs) مع fallback آمن."""
    try:
        return t(lang_code, key).format(**kwargs)
    except Exception:
        return t(lang_code, key)


def set_user_lang(user_id: int, lang_code: str):
    """
    حفظ لغة المستخدم بشكل ذرّي. تُجبر القيم إلى ALLOWED_LANGS فقط.
    """
    lang_code = _normalize_lang(lang_code)
    with _LOCK:
        # لو ملف المستخدمين تالف نبدأ من جديد
        try:
            with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}
        # لا نسجّل إلا اللغات التي تم تحميلها فعليًا، وإلا الافتراضي
        if lang_code not in _known_langs:
            lang_code = _DEFAULT_LANG
        data[str(user_id)] = lang_code
        _atomic_write(USER_LANG_FILE, data)


def get_user_lang(user_id: int) -> str:
    """
    جلب لغة المستخدم. يرجع الافتراضي لو غير معرّف أو غير محمّل.
    """
    try:
        with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                lang_code = data.get(str(user_id))
                if isinstance(lang_code, str):
                    lc = _normalize_lang(lang_code)
                    return lc if lc in _known_langs else _DEFAULT_LANG
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return _DEFAULT_LANG
