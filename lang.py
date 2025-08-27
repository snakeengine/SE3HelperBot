# lang.py
from __future__ import annotations
import json, os, threading

# ===== إعدادات عامة =====
# اللغات المسموح بها فقط
ALLOWED_LANGS = {"en", "ar"}

# الافتراضي: من .env أو "en" إن كانت قيمة غير مسموحة
_ENV_DEFAULT = (os.getenv("DEFAULT_LANG") or "en").strip().lower()
_DEFAULT_LANG = _ENV_DEFAULT if _ENV_DEFAULT in ALLOWED_LANGS else "en"

# مسارات
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")
USER_LANG_FILE = os.path.join(BASE_DIR, "user_langs.json")

_LOCK = threading.RLock()
_translations: dict[str, dict] = {}
_known_langs: set[str] = set()  # اللغات المحمّلة فعليًا (محصورة EN/AR فقط)


def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _normalize_lang(code: str | None) -> str:
    """
    يختزل مثل 'en-US' → 'en' ويقصر على EN/AR فقط.
    أي قيمة غير معروفة تُعادَل الافتراضي (_DEFAULT_LANG).
    """
    if not code:
        return _DEFAULT_LANG
    code = str(code).strip().lower()
    if "-" in code:
        code = code.split("-", 1)[0]
    if code.startswith("ar"):
        code = "ar"
    elif code.startswith("en"):
        code = "en"
    return code if code in ALLOWED_LANGS else _DEFAULT_LANG


def load_translations() -> dict[str, dict]:
    """
    تحميل ملفات locales/<lang>.json للغات المسموح بها فقط (EN/AR).
    """
    translations: dict[str, dict] = {}
    if not os.path.isdir(LOCALES_DIR):
        return {_DEFAULT_LANG: {}}

    for filename in os.listdir(LOCALES_DIR):
        if not filename.endswith(".json"):
            continue
        lang_code = filename[:-5].strip().lower()
        if lang_code not in ALLOWED_LANGS:
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

    # تأكيد وجود خريطة للغة الافتراضية وفولباك إن لم توجد
    translations.setdefault(_DEFAULT_LANG, {})
    # تأكيد وجود خريطة للإنجليزية دومًا للفولباك
    translations.setdefault("en", {})
    return translations


def reload_locales() -> None:
    """إعادة تحميل ملفات الترجمة من القرص (EN/AR فقط)."""
    global _translations, _known_langs
    with _LOCK:
        _translations = load_translations()
        _known_langs = set(_translations.keys()).intersection(ALLOWED_LANGS)
        if "en" not in _known_langs:
            # ضمّن الإنجليزية كطبقة فولباك فارغة على الأقل
            _translations["en"] = _translations.get("en", {})
            _known_langs.add("en")


# تحميل أولي
reload_locales()


def available_languages() -> list[str]:
    """اللغات المتاحة فعليًا (محصورة في ALLOWED_LANGS)."""
    with _LOCK:
        langs = _known_langs or {_DEFAULT_LANG, "en"}
        return sorted(langs)


def t(lang_code: str, key: str) -> str:
    """
    ترجمة مفتاح مع فولباك: لغة المستخدم → الإنجليزية → إرجاع المفتاح نفسه.
    """
    if not key:
        return ""
    lang_code = _normalize_lang(lang_code)
    with _LOCK:
        # محاولة لغة المستخدم
        user_map = _translations.get(lang_code) or {}
        if key in user_map and isinstance(user_map[key], str):
            return user_map[key]
        # فولباك الإنجليزية
        en_map = _translations.get("en") or {}
        if key in en_map and isinstance(en_map[key], str):
            return en_map[key]
        # في النهاية المفتاح نفسه
        return key


def tf(lang_code: str, key: str, **kwargs) -> str:
    """t() + format(**kwargs) مع fallback آمن."""
    try:
        return t(lang_code, key).format(**kwargs)
    except Exception:
        return t(lang_code, key)


def set_user_lang(user_id: int, lang_code: str):
    """
    حفظ لغة المستخدم بشكل ذرّي. تُجبر القيم إلى EN/AR فقط،
    وإن كانت اللغة غير محمّلة فعليًا → نستخدم الافتراضي.
    """
    lang_code = _normalize_lang(lang_code)
    with _LOCK:
        try:
            with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}
        if lang_code not in _known_langs:
            lang_code = _DEFAULT_LANG
        data[str(user_id)] = lang_code
        _atomic_write(USER_LANG_FILE, data)


def get_user_lang(user_id: int) -> str:
    """
    جلب لغة المستخدم. يرجع الافتراضي لو غير معرّف أو غير محمّل.
    لا يقوم بأي تغيير تلقائي على ملف المستخدمين.
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


# ===== دوال اختيارية (مفيدة) — لا تكسر التوافق =====

def ensure_user_lang(user_id: int) -> str:
    """
    يعيد لغة المستخدم إن كانت موجودة، وإلا يُعيد الافتراضي (لا يكتب للملف).
    مفيد عند الاستدعاء الأول في /start بدون تعديل شيء.
    """
    return get_user_lang(user_id)

def switch_lang(user_id: int, lang_code: str) -> bool:
    """
    يبدّل لغة المستخدم ويُعيد True إذا تغيّرت فعلاً.
    استخدمها داخل handers/language فقط عند ضغط المستخدم على زر تغيير اللغة.
    """
    current = get_user_lang(user_id)
    new_val = _normalize_lang(lang_code)
    if new_val not in _known_langs:
        new_val = _DEFAULT_LANG
    if new_val != current:
        set_user_lang(user_id, new_val)
        return True
    return False
