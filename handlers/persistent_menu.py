# handlers/persistent_menu.py
from __future__ import annotations

import re, json, time, logging, unicodedata
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode

from lang import t, get_user_lang
from handlers.home_menu import section_text
try:
    from handlers.home_menu import section_render as _section_render
except Exception:
    _section_render = None

logger = logging.getLogger(__name__)
router = Router(name="persistent_menu")

# ===== تذكّر آخر مرة أظهرنا فيها الكيبورد =====
SHOWN_PATH = Path("data/kb_shown.json")
SHOWN_TTL = 60 * 30  # 30 دقيقة

def _load_shown() -> dict[str, float]:
    try:
        if SHOWN_PATH.exists():
            return json.loads(SHOWN_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("kb_shown load failed: %s", e)
    return {}

def _save_shown(d: dict[str, float]) -> None:
    try:
        SHOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHOWN_PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("kb_shown save failed: %s", e)

_SHOWN = _load_shown()

# ===== نصوص الأزرار =====
def _L(uid: int) -> str:
    try:
        return get_user_lang(uid) or "ar"
    except Exception:
        return "ar"

def _labels(lang: str) -> dict[str, str]:
    # ✅ أزلنا مفاتيح: my_group / my_channel / my_forum
    if (lang or "ar").startswith("ar"):
        return {
            "user":    "👤 المستخدم",
            "premium": "🌟 VIP",
            "bot":     "🤖 البوت",
            "group":   "👥 المجموعات",
            "channel": "📣 القنوات",
            "forum":   "💬 المنتديات",
        }
    else:
        return {
            "user":    "User 👤",
            "premium": "VIP 🌟",
            "bot":     "Bot 🤖",
            "group":   "Groups 👥",
            "channel": "Channels 📣",
            "forum":   "Forums 💬",
        }

def _tt(lang: str, key: str, fallback: str) -> str:
    try:
        val = t(lang, key)
        return fallback if (not val or val == key) else val
    except Exception:
        return fallback

def make_bottom_kb(lang: str) -> ReplyKeyboardMarkup:
    L = _labels(lang)
    # ✅ صفّان فقط
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=L["user"]),  KeyboardButton(text=L["premium"]), KeyboardButton(text=L["bot"])],
            [KeyboardButton(text=L["group"]), KeyboardButton(text=L["channel"]), KeyboardButton(text=L["forum"])],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder=_tt(lang, "menu.choose", "اختر من القائمة…"),
        selective=False,
    )

# ===== تطبيع نص زر ReplyKeyboard =====
_AR_MAP = str.maketrans({
    "أ":"ا", "إ":"ا", "آ":"ا",
    "ى":"ي", "ئ":"ي", "ؤ":"و",
    "ة":"ه", "ٔ":"",  "ٰ":"", "ـ":"",  # همزات/مدّة/تطويل
})

def _strip_controls(s: str) -> str:
    return "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Mn"))

def _normalize_ar(s: str) -> str:
    s = _strip_controls(s)
    s = s.translate(_AR_MAP)
    s = re.sub(r"[^A-Za-z\u0600-\u06FF]+", " ", s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _pick_key(raw_text: str) -> str | None:
    s = _normalize_ar(raw_text)
    # ✅ لا يوجد أي مطابقة للأزرار الملغاة
    pairs = [
        ("user",    ("المستخدم", "user")),
        ("premium", ("بريميوم", "premium", "vip")),
        ("bot",     ("البوت", "bot")),
        ("group",   ("المجموعات", "المجاميع", "group", "groups")),
        ("channel", ("القنوات", "channel", "channels")),
        ("forum",   ("المنتديات", "forum", "forums")),
    ]
    for key, needles in pairs:
        for n in needles:
            if n in s:
                return key
    return None

# ===== اظهار الكيبورد ومعالجة الضغط =====
@router.message(F.chat.type == "private", F.text)
async def ensure_bottom_keyboard(m: Message):
    uid = int(m.from_user.id)
    lang = _L(uid)
    now = time.time()
    last = float(_SHOWN.get(str(uid), 0))

    if (now - last) > SHOWN_TTL or (m.text or "").strip() == "/start":
        try:
            await m.answer(
                _tt(lang, "menu.keyboard_ready", "تم تجهيز القائمة بالأسفل ⬇️"),
                reply_markup=make_bottom_kb(lang),
                parse_mode=ParseMode.HTML
            )
            _SHOWN[str(uid)] = now
            _save_shown(_SHOWN)
        except Exception as e:
            logger.debug("show kb failed: %s", e)

    await _maybe_handle_pressed_button(m, lang)

@router.message(F.chat.type == "private", F.text.casefold() == "/menu")
async def force_menu(m: Message):
    lang = _L(m.from_user.id)
    await m.answer(
        _tt(lang, "menu.keyboard_ready", "تم تجهيز القائمة بالأسفل ⬇️"),
        reply_markup=make_bottom_kb(lang),
        parse_mode=ParseMode.HTML
    )
    _SHOWN[str(m.from_user.id)] = time.time()
    _save_shown(_SHOWN)

async def _maybe_handle_pressed_button(m: Message, lang: str):
    text = (m.text or "").strip()
    if not text:
        return

    labels = _labels(lang)
    direct_map = {v: k for k, v in labels.items()}
    key = direct_map.get(text)

    if not key:
        key = _pick_key(text)

    logger.info("[MENU] raw=%r norm=%r -> key=%r lang=%s",
                text, _normalize_ar(text), key, lang)

    if not key:
        return

    body = ""
    kb = None
    try:
        if _section_render:
            body, kb = _section_render(key, m.from_user) or ("", None)
        else:
            body = section_text(key, m.from_user) or ""
    except Exception as e:
        logger.exception("section_text/section_render failed: %s", e)
        body = "❕ حدث خطأ مؤقت أثناء تجهيز المحتوى."

    try:
        await m.answer(body or "…", parse_mode=ParseMode.HTML,
                       disable_web_page_preview=False, reply_markup=kb)
    except Exception as e:
        logger.exception("send answer failed: %s", e)
        plain = re.sub(r"<[^>]+>", "", body)
        await m.answer(plain or "…", reply_markup=kb)
