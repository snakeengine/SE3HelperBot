from aiogram import Router, types, F
import json
import os

router = Router()

USER_LANG_FILE = "user_langs.json"

def save_user_lang(user_id: int, lang_code: str):
    try:
        with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    data[str(user_id)] = lang_code
    with open(USER_LANG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_lang(user_id: int):
    try:
        with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(str(user_id), "en")
    except FileNotFoundError:
        return "en"

@router.callback_query(F.data == "change_lang")
async def language_menu(callback: types.CallbackQuery):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [types.InlineKeyboardButton(text="🇸🇦 العربية", callback_data="lang_ar")],
        [types.InlineKeyboardButton(text="🇮🇳 हिन्दी", callback_data="lang_hi")],
    ])
    await callback.message.edit_text("🌐 Please choose your language:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("lang_"))
async def set_language(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[1]
    save_user_lang(callback.from_user.id, lang_code)
    await callback.message.edit_text("✅ Language has been updated. Please type /start to reload.")
