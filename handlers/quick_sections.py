# handlers/quick_sections.py
from __future__ import annotations
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from lang import t, get_user_lang

try:
    from handlers.start import CB
except Exception:
    CB = {
        "APP_DOWNLOAD": "app:download", "TOOLS": "tools",
        "TRUSTED_SUPPLIERS": "trusted_suppliers", "CHECK_DEVICE": "check_device",
        "VIP_OPEN": "vip:open", "VIP_PANEL": "vip:open_tools",
        "SAFE_USAGE": "safe_usage:open", "SECURITY_STATUS": "security_status",
        "SERVER_STATUS": "server_status", "LANG": "change_lang",
        "RESELLER_INFO": "reseller_info", "PROMO_INFO": "prom:info", "PROMO_PANEL": "prom:panel",
    }

try:
    from utils.vip_store import is_vip as _is_vip
except Exception:
    def _is_vip(_): return False

try:
    from handlers.promoter import is_promoter as _is_promoter
except Exception:
    def _is_promoter(_): return False

router = Router(name="quick_sections")

def _tabs_kb(lang: str) -> ReplyKeyboardMarkup:
    u = t(lang, "qs.tab.user") or "User 👤"
    v = t(lang, "qs.tab.vip") or "👑 VIP"
    b = t(lang, "qs.tab.bot") or "🤖 Bot"
    g = t(lang, "qs.tab.groups") or "👥 Groups"
    c = t(lang, "qs.tab.channels") or "📣 Channels"
    f = t(lang, "qs.tab.forums") or "💬 Forums"
    hide = t(lang, "qs.hide") or "Hide panel ✖️"
    placeholder = t(lang, "qs.placeholder") or "Choose from the menu… 👉"

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=u), KeyboardButton(text=v), KeyboardButton(text=b)],
            [KeyboardButton(text=g), KeyboardButton(text=c), KeyboardButton(text=f)],
            [KeyboardButton(text=hide)],
        ],
        resize_keyboard=True,
        is_persistent=False,
        one_time_keyboard=False,
        input_field_placeholder=placeholder,
    )

def _section_inline_kb(section: str, lang: str, user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if section == "user":
        kb.row(
            InlineKeyboardButton(text=t(lang, "btn_download") or "📥 Download app", callback_data=CB["APP_DOWNLOAD"]),
            InlineKeyboardButton(text=t(lang, "btn_game_tools") or "🎛️ Game tools", callback_data=CB["TOOLS"]),
        )
        kb.row(
            InlineKeyboardButton(text=t(lang, "btn_trusted_suppliers") or "🏷️ Trusted suppliers", callback_data=CB["TRUSTED_SUPPLIERS"]),
            InlineKeyboardButton(text=t(lang, "btn_check_device") or "📱 Check device", callback_data=CB["CHECK_DEVICE"]),
        )

    elif section == "vip":
        if _is_vip(user_id):
            kb.row(InlineKeyboardButton(text=t(lang, "btn_vip_panel") or "👑 VIP panel", callback_data=CB["VIP_PANEL"]))
        else:
            kb.row(InlineKeyboardButton(text=t(lang, "btn_vip_subscribe") or "👑 Subscribe VIP", callback_data=CB["VIP_OPEN"]))

    elif section == "bot":
        kb.row(
            InlineKeyboardButton(text=t(lang, "btn_safe_usage") or "🧠 Safe usage", callback_data=CB["SAFE_USAGE"]),
            InlineKeyboardButton(text=t(lang, "btn_security") or "🛡️ Security status", callback_data=CB["SECURITY_STATUS"]),
        )
        kb.row(
            InlineKeyboardButton(text=t(lang, "btn_server_status") or "📊 Server status", callback_data=CB["SERVER_STATUS"]),
            InlineKeyboardButton(text=t(lang, "btn_lang") or "🌐 Language", callback_data=CB["LANG"]),
        )

    elif section == "groups":
        kb.row(
            InlineKeyboardButton(
                text=t(lang, "btn_promoter_panel") or "📣 Promoters panel", callback_data=CB.get("PROMO_PANEL", "prom:panel")
            ) if _is_promoter(user_id) else
            InlineKeyboardButton(text=t(lang, "btn_be_promoter") or "📣 How to be a promoter?", callback_data=CB.get("PROMO_INFO", "prom:info"))
        )
        kb.row(InlineKeyboardButton(text=t(lang, "btn_be_supplier_long") or "❓ How to be a supplier?", callback_data=CB["RESELLER_INFO"]))

    elif section == "channels":
        kb.row(InlineKeyboardButton(text=t(lang, "btn_be_supplier_long") or "❓ How to be a supplier?", callback_data=CB["RESELLER_INFO"]))
        kb.row(InlineKeyboardButton(text=t(lang, "btn_trusted_suppliers") or "🏷️ Trusted suppliers", callback_data=CB["TRUSTED_SUPPLIERS"]))

    elif section == "forums":
        kb.row(InlineKeyboardButton(text=t(lang, "btn_safe_usage") or "🧠 Safe usage", callback_data=CB["SAFE_USAGE"]))

    return kb.as_markup()

def _normalize_tab(text: str, lang: str) -> str | None:
    mapping = {
        "user": {"ar": ("المستخدم",), "en": ("User",)},
        "vip": {"ar": ("VIP", "في اي بي", "ڤي آي پي"), "en": ("VIP",)},
        "bot": {"ar": ("البوت",), "en": ("Bot",)},
        "groups": {"ar": ("المجموعات",), "en": ("Groups",)},
        "channels": {"ar": ("القنوات",), "en": ("Channels",)},
        "forums": {"ar": ("المنتديات",), "en": ("Forums", "Topics")},
    }
    txt = (text or "").strip()
    for k, langs in mapping.items():
        if any(w in txt for w in langs.get(lang, ())):
            return k
    return None

@router.message(Command("sections"))
async def cmd_sections(message: Message):
    lang = get_user_lang(message.from_user.id) or "en"
    await message.answer(
        t(lang, "qs.ready") or "Menu is ready below ⬇️",
        reply_markup=_tabs_kb(lang),
        parse_mode=ParseMode.HTML,
    )

@router.message(F.text)
async def on_tab_click(msg: Message):
    lang = get_user_lang(msg.from_user.id) or "en"
    txt = (msg.text or "").strip()

    if txt == (t(lang, "qs.hide") or "Hide panel ✖️"):
        await msg.answer(t(lang, "qs.hidden") or "Panel hidden.", reply_markup=ReplyKeyboardRemove())
        return

    sec = _normalize_tab(txt, lang)
    if not sec:
        return

    kb = _section_inline_kb(sec, lang, msg.from_user.id)
    title_map = {
        "user": t(lang, "qs.h_user") or "User 👤",
        "vip": t(lang, "qs.h_vip") or "👑 VIP",
        "bot": t(lang, "qs.h_bot") or "🤖 Bot",
        "groups": t(lang, "qs.h_groups") or "👥 Groups",
        "channels": t(lang, "qs.h_channels") or "📣 Channels",
        "forums": t(lang, "qs.h_forums") or "💬 Forums",
    }
    await msg.answer(f"<b>{title_map.get(sec, '')}</b>", reply_markup=kb, parse_mode=ParseMode.HTML)
