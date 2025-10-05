# handlers/compat_shims.py
from __future__ import annotations
import re, logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

# ترجمة/لغة
try:
    from lang import t, get_user_lang, set_user_lang
except Exception:
    # فولباك لو استعملت utils_language
    from utils_language import t, get_user_lang, set_user_lang  # type: ignore

router = Router(name="compat_shims")

# ====================== First-chance: Commands ======================

@router.message(Command("language", "lang"))
async def _compat_language_cmd(m: Message):
    # افتح شاشة اللغة الرسمية
    try:
        from handlers.language import language_command
        await language_command(m)
    except Exception as e:
        logging.getLogger(__name__).warning(f"[compat] language_command failed: {e}")
        lang = get_user_lang(m.from_user.id) or "en"
        await m.answer(t(lang, "choose_language") or ("اختر لغتك:" if lang.startswith("ar") else "Choose your language:"))

@router.message(Command("report"))
async def _compat_report_cmd(m: Message, state):
    try:
        from handlers.report import report_cmd
        await report_cmd(m, state)
    except Exception as e:
        logging.getLogger(__name__).warning(f"[compat] report_cmd failed: {e}")
        await m.answer("⚠️ Report module unavailable right now.")



@router.message(Command("rewards"))
async def _compat_rewards_cmd(m: Message):
    try:
        from handlers.rewards_profile_pro import open_profile
        await open_profile(m)
    except Exception:
        try:
            from handlers import rewards_hub as _hub
            await _hub.open_hub(m)
        except Exception as e2:
            logging.getLogger(__name__).warning(f"[compat] rewards open failed: {e2}")
            await m.answer("⚠️ Rewards module is unavailable.")

@router.message(Command("about"))
async def _compat_about_cmd(m: Message):
    try:
        lang = get_user_lang(m.from_user.id) or "en"
    except Exception:
        lang = "en"
    txt = (
        t(lang, "about_text")
        or "ℹ️ <b>S.E Support</b>\nAssistant for services & support.\nUse /help for FAQ."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "back_to_menu") or "⬅️ Back to menu", callback_data="back_to_menu")]]
    )
    await m.answer(txt, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ====================== Callback shims ======================

# فتح شاشة اللغة (مفاتيح قديمة/بديلة)
_OPEN_KEYS = {
    "lang", "language", "menu:lang", "menu:language",
    "settings:language", "profile:language", "change_lang", "change_language",
}
def _open_key(data: str) -> bool:
    d = (data or "").lower()
    return d in _OPEN_KEYS or (d.endswith(":open") and d.split(":")[0] in {"lang", "language"})

@router.callback_query(F.data.func(lambda s: _open_key(s or "")))
async def _compat_lang_open(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = get_user_lang(uid) or "en"
    try:
        from handlers.language import language_keyboard, smart_edit
        txt = t(lang, "choose_language") or ("اختر لغتك:" if lang.startswith("ar") else "Choose your language:")
        await smart_edit(cb.message, txt, language_keyboard(display_lang=lang, selected_lang=lang))
    except Exception:
        await cb.message.answer(t(lang, "choose_language") or ("اختر لغتك:" if lang.startswith("ar") else "Choose your language:"))
    await cb.answer()

# تغيير اللغة مباشرة: lang:ar | language:en | set-lang_ar | set_language:en ...
_LANG_SET_RE = re.compile(r"^(?:lang|language|set[_:-]?lang|set[_:-]?language)[:_-]?(ar|en)$", re.I)

@router.callback_query(F.data.func(lambda s: bool(_LANG_SET_RE.match(s or ""))))
async def _compat_lang_set(cb: CallbackQuery):
    m = _LANG_SET_RE.match(cb.data or "")
    new_lang = m.group(1).lower()  # ar/en
    uid = cb.from_user.id
    set_user_lang(uid, new_lang)

    # حدّث أوامر هذه الدردشة لو متاح
    try:
        from handlers.language import update_user_commands, SHOW_MENU_ON_LANG_CHANGE
        from handlers.persistent_menu import make_bottom_kb
    except Exception:
        update_user_commands = None
        SHOW_MENU_ON_LANG_CHANGE = False
        make_bottom_kb = None

    if update_user_commands:
        try:
            await update_user_commands(cb.message.bot, cb.message.chat.id, new_lang)
        except Exception:
            pass

    # أعرض شاشة التأكيد/الأزرار
    try:
        from handlers.language import language_keyboard, smart_edit
        ok = t(new_lang, "language_changed") or ("تم تغيير اللغة ✅" if new_lang == "ar" else "Language changed ✅")
        await smart_edit(cb.message, ok, language_keyboard(display_lang=new_lang, selected_lang=new_lang))
        if SHOW_MENU_ON_LANG_CHANGE and make_bottom_kb:
            await cb.message.answer(
                t(new_lang, "menu.keyboard_ready") or ("تم تجهيز القائمة بالأسفل ⬇️" if new_lang == "ar" else "Menu ready ⬇️"),
                reply_markup=make_bottom_kb(new_lang),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
    except Exception:
        await cb.message.answer("✅")

    await cb.answer("✅")

# جوائز (fallback) من الأزرار القديمة
@router.callback_query(F.data.in_({"rewards", "wallet", "store"}))
async def _compat_rewards_buttons(cb: CallbackQuery):
    try:
        if cb.data == "rewards":
            try:
                from handlers.rewards_profile_pro import open_profile
                await open_profile(cb, edit=True)
            except Exception:
                from handlers import rewards_hub as _hub
                await _hub.open_hub(cb, edit=True)
        elif cb.data == "wallet":
            from handlers import rewards_wallet as _w
            await _w.open_wallet(cb)
        elif cb.data == "store":
            from handlers import rewards_market as _m
            await _m.open_market(cb)
    except Exception as e:
        logging.getLogger(__name__).warning(f"[compat] rewards cb failed: {e}")
        await cb.answer("Temporarily unavailable.", show_alert=True)
