from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/bot_panel.py

import os, time, json, logging, platform, shutil, sys
from pathlib import Path
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.types import CallbackQuery, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang

router = Router(name="bot_panel")
log = logging.getLogger(__name__)

# Ù„Ø§ ØªÙ„ØªÙ‚Ø· Ø£ÙˆØ§Ù…Ø± /
router.message.filter(lambda m: not ((m.text or "").lstrip().startswith("/")))
# ÙƒÙˆÙ„Ø¨Ø§ÙƒØ§Øª Ù‡Ø°Ø§ Ø§Ù„Ù‚Ø³Ù… ØªØ¨Ø¯Ø£ Ø¨Ù€ "bot:"
router.callback_query.filter(lambda cq: (cq.data or "").startswith("bot:"))

# =========================================================
# Safe edit helper â€” ÙŠØªÙØ§Ø¯Ù‰ BadRequest: message is not modified
# =========================================================
async def _safe_edit(message, *, text: Optional[str] = None, reply_markup=None,
                    parse_mode: Optional[ParseMode] = None,
                    disable_web_page_preview: Optional[bool] = None):
    """
    ÙŠØØ§ÙˆÙ„ ØªØ¹Ø¯ÙŠÙ„ Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ø¨Ø£Ù…Ø§Ù†:
      1) Ø¥Ù† ØªØºÙŠÙ‘Ø± Ø§Ù„Ù†Øµ ÙØ¹Ù„Ø§Ù‹ â†’ edit_text
      2) Ø¥Ù† Ù„Ù… ÙŠØªØºÙŠÙ‘Ø± Ø§Ù„Ù†Øµ Ù„ÙƒÙ† ØªØºÙŠÙ‘Ø± Ø§Ù„Ù…Ø§Ø±Ùƒ-Ø£Ø¨ â†’ edit_reply_markup ÙÙ‚Ø·
      3) Ø¥Ù† Ù„Ù… ÙŠØªØºÙŠÙ‘Ø± Ø´ÙŠØ¡ â†’ Ù„Ø§ ÙŠØ±Ù…ÙŠ Ø§Ø³ØªØ«Ù†Ø§Ø¡
    """
    try:
        cur_text = getattr(message, "text", None) or ""
        if text is not None and text != cur_text:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        if reply_markup is not None:
            return await message.edit_reply_markup(reply_markup=reply_markup)
        return None
    except TelegramBadRequest as e:
        # ÙÙŠ ØØ§Ù„ Ù„Ù… ÙŠØªØºÙŠÙ‘Ø± Ø´ÙŠØ¡ ÙØ¹Ù„Ø§Ù‹
        if "message is not modified" in str(e):
            return None
        raise

# ===== Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø§Ù„Ø¥Ø¯Ù…Ù† =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids()
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ===== Ø£Ø¯ÙˆØ§Øª ØªØ±Ø¬Ù…Ø© =====
def _L(uid: int) -> str:
    return (get_user_lang(uid) or "ar").lower()

def _tt(lang: str, key: str, fallback: str) -> str:
    try:
        return t(lang, key) or fallback
    except Exception:
        return fallback

def _LBL(lang: str, ar: str, en: str) -> str:
    return ar if (lang or "ar").startswith("ar") else en

# ===== Ø¨ÙŠØ§Ù†Ø§Øª Ø¹Ù„Ù†ÙŠØ© Ù‚Ø§Ø¨Ù„Ø© Ù„Ù„ØªØ®ØµÙŠØµ Ù…Ù† Ù…Ù„ÙØ§Øª JSON =====
PUBLIC_META_PATH = Path("data/public_meta.json")   # Ù…Ø¹Ù„ÙˆÙ…Ø§Øª ÙŠØ±Ø§Ù‡Ø§ Ø§Ù„Ø¬Ù…ÙŠØ¹
FAQ_PATH        = Path("data/faq.json")            # Ø£Ø³Ø¦Ù„Ø© Ø´Ø§Ø¦Ø¹Ø©

def _load_json(path: Path) -> Optional[dict]:
    try:
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else None
    except Exception as e:
        log.debug("load_json failed for %s: %s", path, e)
    return None

def _public_meta() -> dict:
    # Ø§Ù„Ù‚ÙŠÙ… Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠØ© (ØªÙ‚Ø¯Ø± ØªØºÙŠÙ‘Ø±Ù‡Ø§ Ù…Ù† Ø§Ù„Ù…Ù„Ù Ù„Ø§ØÙ‚Ù‹Ø§ Ø¨Ø¯ÙˆÙ† ØªØ¹Ø¯ÙŠÙ„ ÙƒÙˆØ¯)
    base = {
        "brand": "Snake Engine",
        "channel": "https://t.me/SnakeEngine",
        "forum": "https://t.me/SnakeEngine1",
        "website": None,
        "support_contact": "@SnakeEngine",
        "support_hours": "10:00â€“22:00 (GMT+3)",
        "commands_hint_ar": "/start /help /report /language",
        "commands_hint_en": "/start /help /report /language",

        "app_latest": {  # Ù…Ø¹Ù„ÙˆÙ…Ø§Øª Ø¹Ø§Ù…Ø© Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… (Ù„ÙŠØ³Øª Ù†Ø¸Ø§Ù…ÙŠØ©)
            "android": None,
            "windows": None
        },
        "premium_benefits_ar": [
            "Ø£ÙˆÙ„ÙˆÙŠØ© Ø§Ù„Ø±Ø¯ Ù…Ù† Ø§Ù„Ø¯Ø¹Ù…",
            "ØØ¯ÙˆØ¯ Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø£Ø¹Ù„Ù‰",
            "Ù…Ø²Ø§ÙŠØ§ Ø¥Ø¶Ø§ÙÙŠØ© Ø¹Ù†Ø¯ ØªÙˆÙØ±Ù‡Ø§"
        ],
        "premium_benefits_en": [
            "Priority support",
            "Higher usage limits",
            "Extra perks when available"
        ]
    }
    file = _load_json(PUBLIC_META_PATH) or {}
    base.update(file)
    return base

def _faq(lang: str) -> list[tuple[str, str]]:
    # ØµÙŠØºØ© Ø§Ù„Ù…Ù„Ù: {"items":[{"q_ar":"..","a_ar":"..","q_en":"..","a_en":".."}, ...]}
    items = []
    d = _load_json(FAQ_PATH) or {}
    for it in d.get("items", []):
        if not isinstance(it, dict):
            continue
        if (lang or "ar").startswith("ar"):
            q = it.get("q_ar") or it.get("q") or ""
            a = it.get("a_ar") or it.get("a") or ""
        else:
            q = it.get("q_en") or it.get("q") or ""
            a = it.get("a_en") or it.get("a") or ""
        if q and a:
            items.append((q, a))
    # Ø§ÙØªØ±Ø§Ø¶ÙŠØ§Øª Ù„Ùˆ Ø§Ù„Ù…Ù„Ù ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯
    if not items:
        if (lang or "ar").startswith("ar"):
            items = [
                ("ÙƒÙŠÙ Ø£Ø¨Ù„Ù‘Øº Ø¹Ù† Ù…Ø´ÙƒÙ„Ø©ØŸ",
                 "Ø§Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø£Ù…Ø± /report ÙˆÙˆØµÙ Ø§Ù„Ù…Ø´ÙƒÙ„Ø©ØŒ Ø£Ùˆ Ø£Ø±ÙÙ‚ Ù„Ù‚Ø·Ø© Ø´Ø§Ø´Ø©."),
                ("ÙƒÙŠÙ Ø£ØºÙŠÙ‘Ø± Ø§Ù„Ù„ØºØ©ØŸ",
                 "Ø§ÙƒØªØ¨ /language Ø«Ù… Ø§Ø®ØªØ± Ø§Ù„Ø¹Ø±Ø¨ÙŠØ© Ø£Ùˆ Ø§Ù„Ø¥Ù†Ø¬Ù„ÙŠØ²ÙŠØ©."),
                ("ÙƒÙŠÙ ÙŠÙ…ÙƒÙ†Ù†ÙŠ Ø§Ù„Ø§ØªØµØ§Ù„ Ø¨ÙƒÙ…ØŸ",
                 "Ø§Ø¶ØºØ· Ø²Ø± Â«ðŸ’¬ Ø¯Ø±Ø¯Ø´Ø© ØÙŠØ©Â» Ø¨Ø§Ù„Ø£Ø³ÙÙ„ Ù„Ù„ØªÙˆØ§ØµÙ„ Ù…Ø¨Ø§Ø´Ø±Ø© Ù…Ø¹ ÙØ±ÙŠÙ‚ Ø§Ù„Ø¯Ø¹Ù…. "
                 "ÙƒÙ…Ø§ ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ø³ØªØ®Ø¯Ø§Ù… /report Ø¹Ù†Ø¯ Ø§Ù„ØØ§Ø¬Ø©.")
            ]
        else:
            items = [
                ("How to report an issue?",
                 "Use /report and describe the issue, attach a screenshot if possible."),
                ("How to change language?",
                 "Send /language and choose Arabic or English."),
                ("How can I contact you?",
                 "Tap the â€œðŸ’¬ Live chatâ€ button below to talk to support directly. "
                 "You can also use /report if needed.")
            ]
    return items

# ===== ÙˆØ§Ø¬Ù‡Ø§Øª Ø¹Ø§Ù…Ø© Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… (Ù„Ø§ Ø¥ÙØ´Ø§Ø¡ Ù„Ø£ÙŠ Ù…Ø¹Ù„ÙˆÙ…Ø§Øª Ù†Ø¸Ø§Ù…) =====
def _kb_main(lang: str, is_admin: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=_tt(lang, "bot.menu.info",     _LBL(lang, "â„¹ï¸ Ù…Ø¹Ù„ÙˆÙ…Ø§Øª", "â„¹ï¸ Info")),     callback_data="bot:info")
    kb.button(text=_tt(lang, "bot.menu.faq",      _LBL(lang, "â“ Ø§Ù„Ø£Ø³Ø¦Ù„Ø© Ø§Ù„Ø´Ø§Ø¦Ø¹Ø©", "â“ FAQ")), callback_data="bot:faq")
    kb.button(text=_tt(lang, "bot.menu.support",  _LBL(lang, "ðŸ†˜ Ø§Ù„Ø¯Ø¹Ù…", "ðŸ†˜ Support")),     callback_data="bot:support")
    kb.button(text=_tt(lang, "bot.menu.live",     _LBL(lang, "ðŸ’¬ Ø¯Ø±Ø¯Ø´Ø© ØÙŠØ©", "ðŸ’¬ Live chat")), callback_data="bot:live")
    kb.button(text=_tt(lang, "bot.menu.forum",    _LBL(lang, "ðŸ’¬ Ø§Ù„Ù…Ù†ØªØ¯Ù‰", "ðŸ’¬ Forum")),      callback_data="bot:forum")
    kb.button(text=_tt(lang, "bot.menu.ping",     _LBL(lang, "ðŸ“ Ø¨ÙŠÙ†Øº", "ðŸ“ Ping")),          callback_data="bot:ping")
    kb.button(text=_tt(lang, "bot.menu.close",    _LBL(lang, "âŒ Ø¥ØºÙ„Ø§Ù‚", "âŒ Close")),        callback_data="bot:close")
    kb.adjust(2, 2, 2, 2)
    return kb

@router.callback_query(F.data == "bot:forum")
async def bot_forum(cb: CallbackQuery):
    lang = (get_user_lang(cb.from_user.id) or "ar").lower()
    meta_forum = (json.loads(Path("data/public_meta.json").read_text(encoding="utf-8")).get("forum")
                  if Path("data/public_meta.json").exists() else "https://t.me/SnakeEngine1")
    txt = "Ø±Ø§Ø¨Ø· Ø§Ù„Ù…Ù†ØªØ¯Ù‰:\n" + meta_forum if lang.startswith("ar") else "Forum link:\n" + meta_forum
    await _safe_edit(
        cb.message,
        text=txt,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=False
    )
    await cb.answer()

@router.callback_query(F.data.in_({"bot:open", "menu:bot"}))
async def open_panel(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    is_admin = _is_admin(cb.from_user.id)
    title = _tt(lang, "bot.title", _LBL(lang, "ðŸ¤– Ø§Ù„Ø¨ÙˆØª", "ðŸ¤– Bot"))
    await _safe_edit(
        cb.message,
        text=f"<b>{title}</b>\n{_tt(lang,'bot.hint', _LBL(lang, 'Ø§Ø®ØªØ± Ø¥Ø¬Ø±Ø§Ø¡:', 'Choose an action:'))}",
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, is_admin).as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "bot:info")
async def bot_info(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    meta = _public_meta()

    # Ø§Ø³Ù… Ø§Ù„Ø¨Ø±Ø§Ù†Ø¯ Ù…Ù† public_meta Ø£Ùˆ Ø§Ø³Ù… Ø§Ù„Ø¨ÙˆØª Ù†ÙØ³Ù‡
    me = await cb.bot.get_me()
    brand = meta.get("brand") or me.first_name

    # Ù‡Ø°Ù‡ Ù…Ø¹Ù„ÙˆÙ…Ø§Øª Ø¹Ø§Ù…Ø© Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… ÙˆÙ„ÙŠØ³Øª ØªÙ‚Ù†ÙŠØ© Ø¹Ù† Ù†Ø¸Ø§Ù… Ø§Ù„Ø®Ø§Ø¯Ù…
    lines = [
        _LBL(lang, "â„¹ï¸ <b>Ù…Ø¹Ù„ÙˆÙ…Ø§Øª</b>", "â„¹ï¸ <b>Info</b>"),
        _LBL(lang, f"â€¢ Ù‡Ø°Ø§ Ø§Ù„Ø¨ÙˆØª ØªØ§Ø¨Ø¹ Ù„Ù€ <b>{brand}</b> ÙˆÙŠÙ‚Ø¯Ù‘Ù… Ø¯Ø¹Ù…Ù‹Ø§ ÙˆÙ…Ø³Ø§Ø¹Ø¯Ø©.",
                    f"â€¢ This bot belongs to <b>{brand}</b> and provides support/help."),
        _LBL(lang,
             f"â€¢ Ø£ÙˆØ§Ù…Ø± Ø³Ø±ÙŠØ¹Ø©: <code>{meta.get('commands_hint_ar') or '/start /help /report /language'}</code>",
             f"â€¢ Quick commands: <code>{meta.get('commands_hint_en') or '/start /help /report /language'}</code>"
        ),
    ]

    ch = meta.get("channel"); fm = meta.get("forum"); web = meta.get("website")
    if ch:
        lines.append(_LBL(lang, f"â€¢ Ø§Ù„Ù‚Ù†Ø§Ø©: <a href='{ch}'>{ch}</a>", f"â€¢ Channel: <a href='{ch}'>{ch}</a>"))
    if fm:
        lines.append(_LBL(lang, f"â€¢ Ø§Ù„Ù…Ù†ØªØ¯Ù‰: <a href='{fm}'>{fm}</a>", f"â€¢ Forum: <a href='{fm}'>{fm}</a>"))
    if web:
        lines.append(_LBL(lang, f"â€¢ Ø§Ù„Ù…ÙˆÙ‚Ø¹: <a href='{web}'>{web}</a>", f"â€¢ Website: <a href='{web}'>{web}</a>"))

    apps = meta.get("app_latest") or {}
    # Ø¹Ø±Ø¶ Ø¥ØµØ¯Ø§Ø±Ø§Øª Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ (Ù„Ùˆ Ù…ÙˆØ¬ÙˆØ¯Ø©) â€” Ù…Ø¹Ù„ÙˆÙ…Ø§Øª Ø¹Ù„Ù†ÙŠØ© Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù…
    app_lines = []
    if apps.get("android"):
        app_lines.append(_LBL(lang, f"Ø£Ù†Ø¯Ø±ÙˆÙŠØ¯: <code>{apps['android']}</code>", f"Android: <code>{apps['android']}</code>"))
    if apps.get("windows"):
        app_lines.append(_LBL(lang, f"ÙˆÙŠÙ†Ø¯ÙˆØ²: <code>{apps['windows']}</code>", f"Windows: <code>{apps['windows']}</code>"))

    if app_lines:
        lines.append(_LBL(lang, "â€¢ Ø¢Ø®Ø± Ø¥ØµØ¯Ø§Ø±Ø§Øª Ø§Ù„ØªØ·Ø¨ÙŠÙ‚:", "â€¢ Latest app versions:"))
        for al in app_lines:
            lines.append("  - " + al)

    await _safe_edit(
        cb.message,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=False
    )
    await cb.answer()

@router.callback_query(F.data == "bot:faq")
async def bot_faq(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    items = _faq(lang)
    title = _LBL(lang, "â“ <b>Ø§Ù„Ø£Ø³Ø¦Ù„Ø© Ø§Ù„Ø´Ø§Ø¦Ø¹Ø©</b>", "â“ <b>FAQ</b>")
    out = [title]
    for q, a in items[:10]:
        out.append(f"\n<b>â€¢ {q}</b>\n{a}")
    await _safe_edit(
        cb.message,
        text="\n".join(out),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=True
    )
    await cb.answer()

@router.callback_query(F.data == "bot:support")
async def bot_support(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    meta = _public_meta()
    contact = meta.get("support_contact") or "@SnakeEngine"
    hours   = meta.get("support_hours") or _LBL(lang, "10:00â€“22:00 (Ø¨ØªÙˆÙ‚ÙŠØª Ø§Ù„Ø±ÙŠØ§Ø¶)", "10:00â€“22:00 (GMT+3)")
    title = _LBL(lang, "ðŸ†˜ <b>Ø§Ù„Ø¯Ø¹Ù…</b>", "ðŸ†˜ <b>Support</b>")

    lines = [
        title,
        _LBL(lang,
             "â€¢ Ù„Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„ÙÙˆØ±ÙŠØ©: Ø§Ø¶ØºØ· Â«ðŸ’¬ Ø¯Ø±Ø¯Ø´Ø© ØÙŠØ©Â» Ø¨Ø§Ù„Ø£Ø³ÙÙ„.",
             "â€¢ For instant help: tap â€œðŸ’¬ Live chatâ€ below."),
        _LBL(lang,
             f"â€¢ ØªÙˆØ§ØµÙ„ Ù…Ø¹Ù†Ø§: <a href='https://t.me/{contact.lstrip('@')}'>{contact}</a>",
             f"â€¢ Contact: <a href='https://t.me/{contact.lstrip('@')}'>{contact}</a>"),
        _LBL(lang, f"â€¢ Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¹Ù…Ù„: <code>{hours}</code>", f"â€¢ Hours: <code>{hours}</code>"),
        _LBL(lang, "â€¢ Ù„Ù„Ø¥Ø¨Ù„Ø§Øº Ø¹Ù† Ù…Ø´ÙƒÙ„Ø©: Ø§Ø³ØªØ®Ø¯Ù… /report", "â€¢ To report an issue: use /report"),
    ]

    await _safe_edit(
        cb.message,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=True
    )
    await cb.answer()

def _kb_premium(lang: str, contact_user: str | None, forum_url: str | None):
    kb = InlineKeyboardBuilder()
    if contact_user:
        kb.button(
            text=_LBL(lang, "ðŸ›’ Ø§Ø´ØªØ±Ùƒ Ø§Ù„Ø¢Ù†", "ðŸ›’ Subscribe"),
            url=f"https://t.me/{contact_user.lstrip('@')}"
        )
    if forum_url:
        kb.button(
            text=_LBL(lang, "ðŸ’¬ Ø§Ù„Ù…Ù†ØªØ¯Ù‰", "ðŸ’¬ Forum"),
            url=forum_url
        )
    kb.button(text=_LBL(lang, "â¬…ï¸ Ø±Ø¬ÙˆØ¹", "â¬…ï¸ Back"), callback_data="bot:open")
    kb.adjust(1, 1, 1)
    return kb.as_markup()

def _fmt_period(lang: str, period: str | None) -> str:
    # period Ø£Ù…Ø«Ù„Ø©: "30d" Ø£Ùˆ "90d" Ø£Ùˆ "365d"
    if not period:
        return ""
    try:
        n = int(''.join(ch for ch in period if ch.isdigit()))
    except Exception:
        return period
    if (lang or "ar").startswith("ar"):
        if n % 365 == 0: return f"{n//365} Ø³Ù†Ø©"
        if n % 30 == 0:  return f"{n//30} Ø´Ù‡Ø±"
        return f"{n} ÙŠÙˆÙ…"
    else:
        if n % 365 == 0: return f"{n//365} year(s)"
        if n % 30 == 0:  return f"{n//30} month(s)"
        return f"{n} day(s)"

@router.callback_query(F.data == "bot:ping")
async def bot_ping(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    t0 = time.perf_counter()
    try:
        await cb.answer(_tt(lang, "bot.ping.wait", _LBL(lang, "Ø¬Ø§Ø±ÙŠ Ø§Ù„Ù‚ÙŠØ§Ø³â€¦", "Measuringâ€¦")), show_alert=False)
    except TelegramBadRequest:
        pass
    ms = int((time.perf_counter() - t0) * 1000)
    txt = _tt(lang, "bot.ping.ok", _LBL(lang, "ðŸ“ Ø¨ÙˆÙ†Øº", "ðŸ“ Pong")) + f" <b>{ms} ms</b>"
    await _safe_edit(
        cb.message,
        text=txt, parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup()
    )

# ===== Ù‚Ø§Ø¦Ù…Ø© Ø¥Ø¯Ø§Ø±ÙŠØ© Ù…Ø®ÙÙŠØ© (Ù„Ù„Ø£Ø¯Ù…Ù† ÙÙ‚Ø·) =====
def _kb_admin(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=_LBL(lang, "ðŸ“ˆ Ø¥ØØµØ§Ø¦ÙŠØ§Øª", "ðŸ“ˆ Stats"), callback_data="bot:admin:stats")
    kb.button(text=_LBL(lang, "ðŸ› ï¸ ØªØ¹ÙŠÙŠÙ† Ø§Ù„Ø£ÙˆØ§Ù…Ø±", "ðŸ› ï¸ Set Commands"), callback_data="bot:cmds")
    kb.button(text=_LBL(lang, "â¬…ï¸ Ø±Ø¬ÙˆØ¹", "â¬…ï¸ Back"), callback_data="bot:open")
    kb.adjust(2, 1)
    return kb

@router.callback_query(F.data == "bot:admin")
async def bot_admin(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True); return
    lang = _L(cb.from_user.id)
    await _safe_edit(
        cb.message,
        text=_LBL(lang, "ðŸ”§ <b>Ù„ÙˆØØ© Ø§Ù„Ø¥Ø¯Ø§Ø±Ø©</b>", "ðŸ”§ <b>Admin Panel</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_admin(lang).as_markup()
    )
    await cb.answer()

# Ø¥ØØµØ§Ø¡Ø§Øª Ø¯Ø§Ø®Ù„ÙŠØ© â€” Ù„Ø§ ØªØ¸Ù‡Ø± Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ†
def _users_count_fallback() -> int:
    try:
        from middlewares.user_tracker import get_users_count  # type: ignore
        return int(get_users_count())
    except Exception:
        pass
    dfile = Path("data/users.json")
    try:
        if dfile.exists():
            d = json.loads(dfile.read_text(encoding="utf-8"))
            return len(d.keys()) if isinstance(d, dict) else 0
    except Exception:
        pass
    return 0

@router.callback_query(F.data == "bot:admin:stats")
async def bot_admin_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True); return
    lang = _L(cb.from_user.id)

    users_total = _users_count_fallback()
    # Ù„Ø§ Ù†Ø¹Ø±Ø¶ ØªÙØ§ØµÙŠÙ„ Ø§Ù„Ù†Ø¸Ø§Ù… Ù‡Ù†Ø§ Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… â€” Ù‡Ø°ÙŠ Ø´Ø§Ø´Ø© Ù„Ù„Ø£Ø¯Ù…Ù† Ø£ØµÙ„Ø§Ù‹
    lines = [
        _LBL(lang, "ðŸ“ˆ <b>Ø¥ØØµØ§Ø¦ÙŠØ§Øª (Ø®Ø§Øµ Ø¨Ø§Ù„Ø¥Ø¯Ø§Ø±Ø©)</b>", "ðŸ“ˆ <b>Stats (Admin)</b>"),
        _LBL(lang, f"â€¢ Ø¥Ø¬Ù…Ø§Ù„ÙŠ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ†: <b>{users_total:,}</b>",
                    f"â€¢ Total users: <b>{users_total:,}</b>"),
    ]
    await _safe_edit(
        cb.message,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_admin(lang).as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "bot:cmds")
async def bot_set_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True); return
    lang = _L(cb.from_user.id)

    en_cmds = [
        BotCommand(command="start",    description="Show main menu"),
        BotCommand(command="help",     description="How to use the bot"),
        BotCommand(command="about",    description="About the bot"),
        BotCommand(command="report",   description="Report an issue"),
        BotCommand(command="language", description="Change language"),
    ]
    ar_cmds = [
        BotCommand(command="start",    description="Ø¹Ø±Ø¶ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ©"),
        BotCommand(command="help",     description="ÙƒÙŠÙÙŠØ© Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø§Ù„Ø¨ÙˆØª"),
        BotCommand(command="about",    description="Ø¹Ù† Ø§Ù„Ø¨ÙˆØª"),
        BotCommand(command="report",   description="Ø§Ù„Ø¥Ø¨Ù„Ø§Øº Ø¹Ù† Ù…Ø´ÙƒÙ„Ø©"),
        BotCommand(command="language", description="ØªØºÙŠÙŠØ± Ø§Ù„Ù„ØºØ©"),
    ]
    en_admin_cmds = en_cmds + [BotCommand(command="admin", description="Admin panel")]
    ar_admin_cmds = ar_cmds + [BotCommand(command="admin", description="Ù„ÙˆØØ© Ø§Ù„Ø¥Ø¯Ø§Ø±Ø©")]

    ok = True
    try:
        await cb.bot.delete_my_commands(scope=BotCommandScopeDefault())
        await cb.bot.delete_my_commands(scope=BotCommandScopeDefault(), language_code="ar")
        for admin_id in ADMIN_IDS:
            try: await cb.bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception: pass
            try: await cb.bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=admin_id), language_code="ar")
            except Exception: pass

        await cb.bot.set_my_commands(en_cmds, scope=BotCommandScopeDefault(), language_code="en")
        await cb.bot.set_my_commands(ar_cmds, scope=BotCommandScopeDefault(), language_code="ar")
        for admin_id in ADMIN_IDS:
            await cb.bot.set_my_commands(en_admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id), language_code="en")
            await cb.bot.set_my_commands(ar_admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id), language_code="ar")
    except Exception as e:
        log.exception("set_my_commands failed: %r", e); ok = False

    msg = _LBL(lang, "âœ… ØªÙ… ØªØØ¯ÙŠØ« Ø§Ù„Ø£ÙˆØ§Ù…Ø±.", "âœ… Commands updated.") if ok else _LBL(lang, "âŒ ÙØ´Ù„ ØªØØ¯ÙŠØ« Ø§Ù„Ø£ÙˆØ§Ù…Ø±.", "âŒ Failed to update commands.")
    await _safe_edit(
        cb.message,
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_admin(lang).as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "bot:close")
async def bot_close(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        await cb.answer()


