# handlers/menu_buttons.py
from __future__ import annotations

import re, logging, unicodedata
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter

from lang import t, get_user_lang
from handlers.home_menu import section_text
try:
    from handlers.home_menu import section_render as _section_render
except Exception:
    _section_render = None

# منع التعارض مع الدردشة الحيّة
from handlers.live_chat import LiveChat

log = logging.getLogger(__name__)
router = Router(name="menu_buttons")

# عطّل هذا الروتر أثناء الدردشة الحيّة
router.message.filter(~StateFilter(LiveChat.active))

# ---------- تطبيع عربي/إنجليزي قوي ----------
_AR_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و",
    "ة": "ه", "ٔ": "", "ٰ": "", "ـ": "",  # همزات/مدّة/تطويل
})

def _strip_controls(s: str) -> str:
    # نحذف محارف الاتجاه/التشكيل (Cf/Mn) كي لا تكسر المطابقة
    return "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Mn"))

def _normalize(s: str) -> str:
    s = _strip_controls(s or "")
    s = s.translate(_AR_MAP)
    # نزيل الإيموجي والرموز ونبقي العربي/اللاتيني فقط
    s = re.sub(r"[^A-Za-z\u0600-\u06FF]+", " ", s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

# ---------- مفاتيح الأزرار المدعومة ----------
_PAIRS = [
    ("user",    ("المستخدم", "user")),
    ("premium", ("بريميوم", "premium", "vip")),
    ("bot",     ("البوت", "bot")),
    ("group",   ("المجموعات", "المجاميع", "group", "groups")),
    ("channel", ("القنوات", "channel", "channels")),
    ("forum",   ("المنتديات", "forum", "forums")),
]

def _detect_key(text: str) -> str | None:
    s = _normalize(text)
    for key, needles in _PAIRS:
        for n in needles:
            if n in s:
                return key
    return None

# ---------- كيبوردات إضافية لبعض الأقسام ----------
def _kb_for_section(key: str, lang: str) -> InlineKeyboardMarkup | None:
    if key == "bot":
        label = "فتح لوحة البوت" if lang.startswith("ar") else "Open bot panel"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data="bot:open")]
        ])
    if key == "premium":
        forum = "https://t.me/SnakeEngine2/1"
        btn_buy   = t(lang, "premium.btn.buy") or ("🛒 اشترِ الآن" if lang.startswith("ar") else "🛒 Buy now")
        btn_forum = t(lang, "ui.forum")        or ("💬 المنتدى" if lang.startswith("ar") else "💬 Forum")
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_buy,   callback_data="trusted_suppliers")],
            [InlineKeyboardButton(text=btn_forum, url=forum)]
        ])
    return None

# ---------- الهاندلر المباشر لأزرار الريـبلاي ----------
@router.message(F.chat.type == "private", F.text.func(lambda s: bool(_detect_key(s))))
async def on_menu_button(m: Message):
    lang = get_user_lang(m.from_user.id) or "ar"
    key  = _detect_key(m.text or "")
    log.info("[menu_buttons] matched key=%r for text=%r (norm=%r)", key, m.text, _normalize(m.text or ""))

    if not key:
        return

    # النص + كيبورد إنلاين (إن وجد)
    if _section_render:
        body, kb = _section_render(key, m.from_user)
    else:
        body, kb = section_text(key, m.from_user), None

    # كيبورد إضافي لبعض الأقسام (لا يطغى على الموجود من section_render)
    extra = _kb_for_section(key, lang)
    if extra and kb is None:
        kb = extra

    await m.answer(
        body or "…",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=False
    )
    return
