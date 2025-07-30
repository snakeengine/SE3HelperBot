import json
import os

LOCALES_DIR = os.path.join(os.path.dirname(__file__), "locales")
USER_LANG_FILE = "user_langs.json"

def load_translations():
    translations = {}
    for filename in os.listdir(LOCALES_DIR):
        if filename.endswith(".json"):
            lang_code = filename[:-5]
            path = os.path.join(LOCALES_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                translations[lang_code] = json.load(f)
    return translations

translations = load_translations()

def t(lang_code, key):
    return translations.get(lang_code, translations.get("en", {})).get(key, key)

def get_user_lang(user_id: int):
    try:
        with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(str(user_id), "en")
    except FileNotFoundError:
        return "en"
