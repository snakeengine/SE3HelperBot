from __future__ import annotations

# handlers/persistent_menu.py


import logging, re, unicodedata
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from lang import t, get_user_lang
from handlers.home_menu import section_text
try:
    from handlers.home_menu import section_render as _section_render
except Exception:
    _section_render = None

# الحماية من التعارض مع الدردشة الحية
try:
    from handlers.live_chat import LiveChat
except Exception:
    class LiveChat:
        active = None

# لوحة مؤقتة تُغلق تلقائياً عبر الميدلوير EphemeralKBGuard
from utils.ephemeral_kb import open_panel, close_panel, is_active as _kb_active

logger = logging.getLogger(__name__)
router = Router(name="persistent_menu")

# نعمل بالخاص فقط وبلا FSM نشطة، ونتجنب اعتراض الأوامر
router.message.filter(F.chat.type == "private", StateFilter(None))
router.callback_query.filter(F.message.chat.type == "private", StateFilter(None))

# ======================= مساعدات لغة ونصوص =======================

def _ui_lang(user_id: int, fallback: str = "en") -> str:
    lang = (get_user_lang(user_id) or "").lower() or fallback
    return "ar" if lang.startswith("ar") else "en"

def _tt(lang: str, key: str, fallback: str) -> str:
    try:
        val = t(lang, key)
        if isinstance(val, str) and val and val != key:
            return val
    except Exception:
        pass
    return fallback

def _labels(lang: str) -> dict[str, str]:
    if lang == "ar":
        return {
            "user":    "المستخدم 👤",
            "premium": "🌟 VIP",
            "bot":     "🤖 البوت",
            "group":   "👥 المجموعات",
            "channel": "📣 القنوات",
            "forum":   "💬 المنتديات",
            "hide":    "إخفاء اللوحة ✖️",
        }
    else:
        return {
            "user":    "User 👤",
            "premium": "VIP 🌟",
            "bot":     "Bot 🤖",
            "group":   "Groups 👥",
            "channel": "Channels 📣",
            "forum":   "Forums 💬",
            "hide":    "Hide panel ✖️",
        }

def make_bottom_kb(lang: str) -> ReplyKeyboardMarkup:
    L = _labels(lang)
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder=_tt(lang, "menu.choose",
                                    "اختر القسم:" if lang == "ar" else "Choose a section:"),
        keyboard=[
            [KeyboardButton(text=L["user"]),  KeyboardButton(text=L["premium"]), KeyboardButton(text=L["bot"])],
            [KeyboardButton(text=L["group"]), KeyboardButton(text=L["channel"]), KeyboardButton(text=L["forum"])],
            [KeyboardButton(text=L["hide"])],
        ],
    )

# ======================= تطبيع نصوص للتعرّف =======================

_AR_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و",
    "ة": "ه", "ٔ": "", "ٰ": "", "ـ": "",
})

def _strip_controls(s: str) -> str:
    import unicodedata as _u
    return "".join(ch for ch in s if _u.category(ch) not in ("Cf", "Mn"))

def _normalize_ar(s: str) -> str:
    s = _strip_controls(s or "")
    s = s.translate(_AR_MAP)
    s = re.sub(r"[^A-Za-z\u0600-\u06FF]+", " ", s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _pick_key(raw_text: str) -> Optional[str]:
    s = _normalize_ar(raw_text)
    pairs = [
        ("user",    ("المستخدم", "user")),
        ("premium", ("بريميوم", "vip", "premium")),
        ("bot",     ("البوت", "bot")),
        ("group",   ("المجموعات", "المجاميع", "group", "groups")),
        ("channel", ("القنوات", "channel", "channels")),
        ("forum",   ("المنتديات", "forum", "forums")),
        ("hide",    ("اخفاء", "اخفاء اللوحه", "اخفاء اللوحة", "اغلاق اللوحه", "اغلاق اللوحة",
                     "hide", "hide panel", "close panel", "close keyboard")),
    ]
    for key, needles in pairs:
        for n in needles:
            if n in s:
                return key
    return None

# ========= فلتر دقيق لتجنّب التعارض مع باقي الهاندلرات =========

def _is_menu_button_message(m: Message) -> bool:
    """
    يقيد الالتقاط عندما:
    1) لوحة /menu مفعّلة للمستخدم، و
    2) النص يطابق أحد أزرارنا أو مرادفاتها، و
    3) ليس أمراً يبدأ بـ '/'.
    """
    if not m or not m.from_user or not (m.text or "").strip():
        return False
    txt = (m.text or "").strip()
    if txt.startswith("/"):
        return False
    if not _kb_active(m.from_user.id, owner="menu"):
        return False
    lang = _ui_lang(m.from_user.id)
    if txt in _labels(lang).values():
        return True
    return _pick_key(txt) is not None

# ======================= منطق المعالجة =======================

async def _handle_pressed_button(m: Message, lang: str | None = None):
    _lang = (lang or _ui_lang(m.from_user.id)).lower()
    text = (m.text or "").strip()
    if not text:
        return

    labels = _labels(_lang)
    direct_map = {v: k for k, v in labels.items()}
    key = direct_map.get(text) or _pick_key(text)

    logger.info("[MENU] raw=%r norm=%r -> key=%r lang=%s",
                text, _normalize_ar(text), key, _lang)

    if not key:
        return

    # زر الإخفاء
    if key == "hide":
        msg = _tt(_lang, "menu.hidden",
                  "تم إخفاء اللوحة." if _lang == "ar" else "Panel hidden.")
        try:
            await m.answer(msg, reply_markup=ReplyKeyboardRemove())
        except Exception:
            try:
                await m.answer("\u2060", reply_markup=ReplyKeyboardRemove())
            except Exception:
                pass
        close_panel(m.from_user.id)
        return

    # بقية الأقسام
    body = ""
    kb = None
    try:
        if _section_render:
            body, kb = _section_render(key, m.from_user) or ("", None)
        else:
            body = section_text(key, m.from_user) or ""
    except Exception as e:
        logger.exception("section_text/section_render failed: %s", e)
        body = _tt(_lang, "menu.err",
                   "❕ حدث خطأ مؤقت أثناء تجهيز المحتوى."
                   if _lang == "ar" else
                   "❕ A temporary error occurred while preparing the content.")

    if not body:
        body = _tt(_lang, f"menu.section.{key}",
                   "هذا القسم غير متاح حاليًا."
                   if _lang == "ar" else
                   "This section is currently unavailable.")

    try:
        await m.answer(body, parse_mode=ParseMode.HTML,
                       disable_web_page_preview=False, reply_markup=kb)
    except Exception:
        plain = re.sub(r"<[^>]+>", "", body)
        await m.answer(plain or ("…" if _lang != "ar" else "…"), reply_markup=kb)

# ======================= الأوامر =======================

@router.message(Command("menu"))
@router.message(Command("sections"))
async def open_menu_cmd(message: Message, state: FSMContext):
    # لا تظهر أثناء الدردشة الحية
    if LiveChat.active and await state.get_state() == LiveChat.active.state:
        return

    lang = _ui_lang(message.from_user.id)
    # تفعيل لوحة مؤقتة تُغلق تلقائياً عند أي تفاعل آخر
    open_panel(message.from_user.id, owner="menu", ttl_sec=3600, allow_prefixes=())

    await message.answer(
        _tt(lang, "menu.keyboard_ready",
            "تم تجهيز القائمة بالأسفل ⬇️" if lang == "ar" else "Menu is ready below ⬇️"),
        reply_markup=make_bottom_kb(lang),
        parse_mode=ParseMode.HTML
    )

# هذا الهاندلر لن يُستدعى إلا إذا تحقق الفلتر الخاص بنا
@router.message(_is_menu_button_message, StateFilter(None))
async def on_reply_button(msg: Message, state: FSMContext):
    if LiveChat.active and await state.get_state() == LiveChat.active.state:
        return
    await _handle_pressed_button(msg, _ui_lang(msg.from_user.id))
