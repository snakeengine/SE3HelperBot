from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.i18n import t
from services.user_profile import UserProfile

def home_kb(p: UserProfile):
    kb = InlineKeyboardBuilder()
    # My Tools
    kb.button(text=t("btn_my_profile", p.locale), callback_data="my_profile")
    kb.button(text=t("btn_my_keys", p.locale), callback_data="my_keys")
    kb.button(text=t("btn_my_activations", p.locale), callback_data="my_acts")
    kb.adjust(3)
    # Explore
    kb.button(text=t("btn_tools", p.locale), callback_data="tools")
    kb.button(text=t("btn_download", p.locale), callback_data="app:download")
    kb.button(text=t("btn_device", p.locale), callback_data="device_check")
    kb.adjust(3)
    # Status/Info
    kb.button(text=t("btn_guide", p.locale), callback_data="guide")
    kb.button(text=t("btn_servers", p.locale), callback_data="servers_status")
    kb.button(text=t("btn_usage", p.locale), callback_data="usage_status")
    kb.adjust(3)
    # Language
    kb.button(text=t("btn_lang", p.locale), callback_data="change_lang")
    kb.adjust(1)
    return kb.as_markup()
