from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/security_status.py


import os, json, datetime, logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ParseMode
from lang import t, get_user_lang

# Ø¯Ø¹Ù… Ø§Ù„Ù…Ù†Ø·Ù‚Ø© Ø§Ù„Ø²Ù…Ù†ÙŠØ© (Python 3.9+). ÙÙŠ ØØ§Ù„ Ø¹Ø¯Ù… ØªÙˆÙØ±Ù‡Ø§ Ù†Ø³ØªØ®Ø¯Ù… ØªØ¹ÙˆÙŠØ¶ +3
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

router = Router()

# ========= Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø¹Ø§Ù…Ø© / Ø£Ø¯Ù…Ù† =========
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids()
if not ADMIN_IDS:
    ADMIN_IDS = get_admin_ids()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def L(user_id: int) -> str:
    return (get_user_lang(user_id) or "ar").lower()

# Ø¥Ø¸Ù‡Ø§Ø± Ø²Ø± "Ù„ÙˆØØ© ØªØÙƒÙ… Ø§Ù„Ø£Ù…Ø§Ù†" Ø¯Ø§Ø®Ù„ Ø´Ø§Ø´Ø© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ØŸ Ø§ÙØªØ±Ø§Ø¶ÙŠÙ‹Ø§: Ù…Ø®ÙÙŠ
SHOW_INLINE_ADMIN = False

# ========= Ù…Ù„Ù Ø§Ù„ØØ§Ù„Ø© =========
DATA_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "security_status.json"))

DEFAULT_GAMES = {
    "8bp":  {"name": {"ar": "8Ball Pool", "en": "8Ball Pool"}, "status": "safe", "note": ""},
    "car":  {"name": {"ar": "Carrom Pool", "en": "Carrom Pool"}, "status": "safe", "note": ""},
}
DEFAULT_DATA = {
    "global": {"status": "safe", "note": "", "updated_by": None, "updated_at": None},
    "games": DEFAULT_GAMES
}

def _ensure_file():
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        _save(DEFAULT_DATA)

def _load() -> dict:
    try:
        _ensure_file()
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "games" not in data:
            data["games"] = DEFAULT_GAMES
        if "global" not in data:
            data["global"] = DEFAULT_DATA["global"]
        return data
    except Exception as e:
        logging.error(f"[security_status] load error: {e}")
        return json.loads(json.dumps(DEFAULT_DATA))  # deep copy

def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _utcnow_iso_z() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def _set_global(status: str, note: str | None, by: int):
    data = _load()
    data["global"]["status"] = status
    if note is not None:
        data["global"]["note"] = note
    data["global"]["updated_by"] = by
    data["global"]["updated_at"] = _utcnow_iso_z()
    _save(data)
    return data

def _set_game(code: str, status: str, note: str | None, by: int):
    data = _load()
    if code not in data["games"]:
        data["games"][code] = {"name": {"ar": code, "en": code}, "status": "safe", "note": ""}
    data["games"][code]["status"] = status
    if note is not None:
        data["games"][code]["note"] = note
    data["global"]["updated_by"] = by
    data["global"]["updated_at"] = _utcnow_iso_z()
    _save(data)
    return data

# === Ø£Ø¯Ø§Ø© ØªÙ†Ø³ÙŠÙ‚ Ø§Ù„ÙˆÙ‚Øª ===
def _baghdad_tz():
    return ZoneInfo("Asia/Baghdad") if ZoneInfo else datetime.timezone(datetime.timedelta(hours=3))

def _format_updated_at(dt_iso: str | None) -> str:
    """
    ÙŠØ¹Ø±Ø¶ Ø¢Ø®Ø± ØªØØ¯ÙŠØ« Ø¨ØµÙŠØºØ©: 12-08-2025 14:05 UTC
    Ù†Ø¹ØªÙ…Ø¯ Ø¯Ø§Ø¦Ù…Ù‹Ø§ Ø¹Ù„Ù‰ UTC Ù„ØªØ¬Ù†Ø¨ Ù…Ø´Ø§ÙƒÙ„ Ø§Ù„Ù…Ù†Ø§Ø·Ù‚ Ø§Ù„Ø²Ù…Ù†ÙŠØ©.
    """
    if not dt_iso:
        return "-"
    try:
        s = dt_iso.strip()
        if s.endswith("Z"):
            s = s[:-1]
        dt_utc = datetime.datetime.fromisoformat(s)
        # ØªØ£ÙƒØ¯ Ø£Ù†Ù‡Ø§ UTC
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=datetime.timezone.utc)
        else:
            dt_utc = dt_utc.astimezone(datetime.timezone.utc)
        return dt_utc.strftime("%d-%m-%Y %H:%M") + " UTC"
    except Exception:
        return dt_iso or "-"

def _now_ping_str() -> str:
    # ÙˆÙ‚Øª Ù„ØØ¸ÙŠ Ø¨ØµÙŠØºØ© UTC: 17:40:12 12-08-2025 UTC
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime("%H:%M:%S %d-%m-%Y") + " UTC"

# ========= Ø®Ø±Ø§Ø¦Ø· Ø§Ù„ØØ§Ù„Ø§Øª =========
STATUS_ORDER = ["safe", "warn", "down"]
STATUS_ICON = {
    "safe": "âœ…",
    "warn": "âš ï¸",
    "down": "âŒ",
}

def status_human(lang: str, st: str) -> str:
    key = {
        "safe": "sec.status.safe",
        "warn": "sec.status.warn",
        "down": "sec.status.down",
    }[st]
    return STATUS_ICON.get(st, "") + " " + t(lang, key)

# ========= Ù…Ø³Ø§Ø¹Ø¯: ØªØ¹Ø¯ÙŠÙ„ Ø°ÙƒÙŠ Ø£Ùˆ Ø¥Ø±Ø³Ø§Ù„ Ø¬Ø¯ÙŠØ¯ =========
async def _smart_edit_or_send(msg: Message, text: str, reply_markup=None):
    try:
        # Ø¬Ø±Ù‘Ø¨ ØªØ¹Ø¯ÙŠÙ„ Ù†Øµ
        if msg.text is not None:
            return await msg.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        # Ø¬Ø±Ù‘Ø¨ ØªØ¹Ø¯ÙŠÙ„ ÙˆØµÙ Ø§Ù„ÙˆØ³Ø§Ø¦Ø·
        if msg.caption is not None:
            return await msg.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        # Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ù†Øµ/ÙˆØµÙ â†’ Ø£Ø±Ø³Ù„ Ø±Ø³Ø§Ù„Ø© Ø¬Ø¯ÙŠØ¯Ø©
        return await msg.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        low = str(e).lower()
        if ("there is no text in the message to edit" in low or
            "message can't be edited" in low or
            "message is not modified" in low):
            return await msg.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        raise

# ========= ÙˆØ§Ø¬Ù‡Ø© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… =========
def _kb_main(lang: str, as_admin: bool, *, src: str) -> InlineKeyboardBuilder:
    """
    src âˆˆ {'main','vip'}
    - main â†’ Ø²Ø± Ø§Ù„Ø±Ø¬ÙˆØ¹ back_to_menu
    - vip  â†’ Ø²Ø± Ø§Ù„Ø±Ø¬ÙˆØ¹ vip:open_tools
    Ù†ØØ§ÙØ¸ Ø¹Ù„Ù‰ src ÙÙŠ Ø¬Ù…ÙŠØ¹ Ø§Ù„Ø£Ø²Ø±Ø§Ø±.
    """
    kb = InlineKeyboardBuilder()
    data = _load()
    games = data.get("games", {})

    # Ù†Ø¨Ù†ÙŠ Ø§Ù„Ø£Ø²Ø±Ø§Ø± Ø£ÙˆÙ„Ø§Ù‹
    game_buttons: list[InlineKeyboardButton] = []
    for code, g in games.items():
        name = g.get("name", {}).get(lang, g.get("name", {}).get("en", code))
        icon = STATUS_ICON.get(g.get("status", "safe"), "")
        game_buttons.append(
            InlineKeyboardButton(text=f"{icon} {name}", callback_data=f"sec:game:{code}:{src}")
        )

    # Ù†Ø±ØªÙ‘Ø¨ 2Ã—2
    i = 0
    while i < len(game_buttons):
        a = game_buttons[i]
        b = game_buttons[i+1] if i+1 < len(game_buttons) else None
        if b:
            kb.row(a, b, width=2)
            i += 2
        else:
            kb.row(a, width=1)
            i += 1

    # Ø²Ø± ØªØØ¯ÙŠØ«
    kb.row(InlineKeyboardButton(text="ðŸ”„ " + t(lang, "sec.btn_refresh"), callback_data=f"sec:refresh:{src}"), width=1)

    # Ø²Ø± Ù„ÙˆØØ© Ø§Ù„ØªØÙƒÙ… (Ù„Ù„Ø£Ø¯Ù…Ù† ÙÙ‚Ø· Ø¥Ø°Ø§ Ù…ÙÙØ¹Ù‘Ù„)
    if as_admin and SHOW_INLINE_ADMIN:
        kb.row(InlineKeyboardButton(text=t(lang, "sec.btn_admin_panel"), callback_data="sec:admin"), width=1)

    # Ø±Ø¬ÙˆØ¹ ØØ³Ø¨ Ø§Ù„Ù…ØµØ¯Ø±
    back_cb = "vip:open_tools" if src == "vip" else "back_to_menu"
    kb.row(InlineKeyboardButton(text=t(lang, "sec.btn_back"), callback_data=back_cb), width=1)
    return kb

def _kb_admin(lang: str) -> InlineKeyboardBuilder:
    data = _load()
    kb = InlineKeyboardBuilder()

    MARK_ON, MARK_OFF = "â—", "â—‹"

    # Ø²Ø± ØªØØ¯ÙŠØ« Ù„ÙˆØØ© Ø§Ù„ØªØÙƒÙ…
    kb.row(InlineKeyboardButton(text="ðŸ”„ " + t(lang, "sec.btn_refresh"), callback_data="sec:adm_refresh"), width=1)

    # === Ø§Ù„ØØ§Ù„Ø© Ø§Ù„Ø¹Ø§Ù…Ø© ===
    g_status = data.get("global", {}).get("status", "safe")
    kb.row(
        InlineKeyboardButton(
            text=f"{t(lang, 'sec.admin.global_now')}: {status_human(lang, g_status)}",
            callback_data="sec:nop"
        ),
        width=1
    )

    # ØµÙ Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„ØØ§Ù„Ø© Ø§Ù„Ø¹Ø§Ù…Ø© (3 Ø£Ø²Ø±Ø§Ø±)
    glob_row = [
        InlineKeyboardButton(text=f"{MARK_ON if g_status=='safe' else MARK_OFF} âœ…", callback_data="sec:adm:glob:safe"),
        InlineKeyboardButton(text=f"{MARK_ON if g_status=='warn' else MARK_OFF} âš ï¸", callback_data="sec:adm:glob:warn"),
        InlineKeyboardButton(text=f"{MARK_ON if g_status=='down' else MARK_OFF} âŒ", callback_data="sec:adm:glob:down"),
    ]
    kb.row(*glob_row, width=3)

    # ÙØ§ØµÙ„
    kb.row(InlineKeyboardButton(text="â€” " + t(lang, "sec.admin.games") + " â€”", callback_data="sec:nop"), width=1)

    # === Ø§Ù„Ø£Ù„Ø¹Ø§Ø¨ ===
    games = data.get("games", {})
    for code, g in games.items():
        name = g.get("name", {}).get(lang, g.get("name", {}).get("en", code))
        cur = g.get("status", "safe")
        kb.row(InlineKeyboardButton(text=f"ðŸŽ® {name} {STATUS_ICON.get(cur,'')}", callback_data="sec:nop"), width=1)

        row = [
            InlineKeyboardButton(text=f"{MARK_ON if cur=='safe' else MARK_OFF} âœ…", callback_data=f"sec:adm:{code}:safe"),
            InlineKeyboardButton(text=f"{MARK_ON if cur=='warn' else MARK_OFF} âš ï¸", callback_data=f"sec:adm:{code}:warn"),
            InlineKeyboardButton(text=f"{MARK_ON if cur=='down' else MARK_OFF} âŒ", callback_data=f"sec:adm:{code}:down"),
        ]
        kb.row(*row, width=3)

    # Ø±Ø¬ÙˆØ¹ Ø¥Ù„Ù‰ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© (Ø¹Ø§Ù…Ù‘Ø©)
    kb.row(InlineKeyboardButton(text=t(lang, "sec.btn_back_list"), callback_data="sec:back_list:main"), width=1)
    return kb

def _main_text(lang: str, *, ping_now: bool = False) -> str:
    d = _load()
    g = d.get("global", {})
    st = g.get("status", "safe")

    # Ù…Ù„Ø§ØØ¸Ø© Ø§ÙØªØ±Ø§Ø¶ÙŠØ© Ø¥Ø°Ø§ ÙØ§Ø±ØºØ©
    note = g.get("note")
    if not note or str(note).strip() == "":
        note = t(lang, "sec.no_note")

    updated_at = _format_updated_at(g.get("updated_at"))
    ping_line = f"\nâ± {t(lang, 'sec.ping_now')}: <code>{_now_ping_str()}</code>" if ping_now else ""

    return (
        f"ðŸ›¡ <b>{t(lang, 'sec.title')}</b>\n"
        f"{t(lang, 'sec.global_status')}: {status_human(lang, st)}\n"
        f"{t(lang, 'sec.note')}: <i>{note}</i>\n"
        f"{t(lang, 'sec.updated')}: <code>{updated_at}</code>{ping_line}\n\n"
        f"{t(lang, 'sec.choose_game')}"
    )

def _game_text(lang: str, code: str) -> str:
    d = _load()
    g = d.get("games", {}).get(code)
    if not g:
        return t(lang, "sec.game_not_found")
    name = g.get("name", {}).get(lang, g.get("name", {}).get("en", code))
    st = g.get("status", "safe")

    # Ù…Ù„Ø§ØØ¸Ø© Ø§ÙØªØ±Ø§Ø¶ÙŠØ© Ø¥Ø°Ø§ ÙØ§Ø±ØºØ©
    note = g.get("note")
    if not note or str(note).strip() == "":
        note = t(lang, "sec.no_note")

    return (
        f"{STATUS_ICON.get(st,'')} <b>{name}</b>\n"
        f"{status_human(lang, st)}\n"
        f"{t(lang, 'sec.note')}: <i>{note}</i>"
    )

# ====== Ù†Ù‚Ø§Ø· Ø§Ù„Ø¯Ø®ÙˆÙ„ ======

# ÙØªØ Ù…Ù† Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ© Ø£Ùˆ Ù…Ù† VIP
@router.callback_query(F.data.in_({"security_status", "security_status:vip"}))
async def security_menu(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    src = "vip" if cb.data == "security_status:vip" else "main"
    text = _main_text(lang)
    kb = _kb_main(lang, is_admin(cb.from_user.id), src=src).as_markup()
    await _smart_edit_or_send(cb.message, text, kb)
    await cb.answer()

# ØªØØ¯ÙŠØ« Ø§Ù„Ø´Ø§Ø´Ø© Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ© (ÙŠØØ§ÙØ¸ Ø¹Ù„Ù‰ Ù…ØµØ¯Ø± Ø§Ù„ÙØªØ)
@router.callback_query(F.data.regexp(r"^sec:refresh:(vip|main)$"))
async def security_refresh(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    _, _, src = cb.data.split(":")
    text = _main_text(lang, ping_now=True)
    kb = _kb_main(lang, is_admin(cb.from_user.id), src=src).as_markup()
    try:
        await _smart_edit_or_send(cb.message, text, kb)
        await cb.answer(t(lang, "sec.refreshed"))
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await cb.answer(t(lang, "sec.no_changes"))
        else:
            raise

# Ø¹Ø±Ø¶ Ù„Ø¹Ø¨Ø© Ù…Ø¹ÙŠÙ‘Ù†Ø© (Ù…Ø¹ Ø±Ø¬ÙˆØ¹ Ø¥Ù„Ù‰ Ù†ÙØ³ Ø§Ù„Ù…ØµØ¯Ø±)
@router.callback_query(F.data.regexp(r"^sec:game:([^:]+):(vip|main)$"))
async def security_game(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    _, _, code, src = cb.data.split(":")
    text = _game_text(lang, code)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=t(lang, "sec.btn_back_list"), callback_data=f"sec:back_list:{src}"), width=1)

    await _smart_edit_or_send(cb.message, text, kb.as_markup())
    await cb.answer()

# Ø±Ø¬ÙˆØ¹ Ø¥Ù„Ù‰ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© (ÙŠØØ§ÙØ¸ Ø¹Ù„Ù‰ Ø§Ù„Ù…ØµØ¯Ø±)
@router.callback_query(F.data.regexp(r"^sec:back_list:(vip|main)$"))
async def security_back_list(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    _, _, src = cb.data.split(":")
    text = _main_text(lang)
    kb = _kb_main(lang, is_admin(cb.from_user.id), src=src).as_markup()
    await _smart_edit_or_send(cb.message, text, kb)
    await cb.answer()

# ====== Ù„ÙˆØØ© ØªØÙƒÙ… Ø§Ù„Ø£Ø¯Ù…Ù† (Ø¥Ù†Ù„Ø§ÙŠÙ†) ======
@router.callback_query(F.data == "sec:admin")
async def security_admin(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "sec.admin.only_admin"), show_alert=True)
    text = "ðŸ›  " + t(lang, "sec.admin.title")
    kb = _kb_admin(lang).as_markup()
    await _smart_edit_or_send(cb.message, text, kb)
    await cb.answer()

# ØªØØ¯ÙŠØ« Ù„ÙˆØØ© Ø§Ù„ØªØÙƒÙ…
@router.callback_query(F.data == "sec:adm_refresh")
async def security_admin_refresh(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "sec.admin.only_admin"), show_alert=True)
    text = "ðŸ›  " + t(lang, "sec.admin.title")
    kb = _kb_admin(lang).as_markup()
    try:
        await _smart_edit_or_send(cb.message, text, kb)
        await cb.answer(t(lang, "sec.refreshed"))
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await cb.answer(t(lang, "sec.no_changes"))
        else:
            raise

@router.callback_query(F.data.startswith("sec:adm:"))
async def security_admin_action(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "sec.admin.only_admin"), show_alert=True)

    parts = cb.data.split(":")  # sec, adm, <scope or code>, <status>
    if len(parts) != 4:
        return await cb.answer()

    scope_or_code = parts[2]
    status = parts[3]
    if scope_or_code == "glob":
        _set_global(status, None, cb.from_user.id)
    else:
        _set_game(scope_or_code, status, None, cb.from_user.id)

    text = "ðŸ›  " + t(lang, "sec.admin.updated_ok")
    kb = _kb_admin(lang).as_markup()
    await _smart_edit_or_send(cb.message, text, kb)
    await cb.answer()

@router.callback_query(F.data == "sec:nop")
async def security_nop(cb: CallbackQuery):
    await cb.answer()

# ====== Ø£ÙˆØ§Ù…Ø± Ø£Ø¯Ù…Ù† (Ù†ØµÙŠØ©) ======
# /sec_set safe|warn|down [note...]
@router.message(Command("sec_set"))
async def cmd_sec_set(m: Message):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(t(lang, "sec.admin.only_admin"))
    toks = (m.text or "").split(maxsplit=2)
    if len(toks) < 2 or toks[1] not in STATUS_ORDER:
        return await m.reply(t(lang, "sec.admin.usage_set"))
    status = toks[1]
    note = toks[2] if len(toks) > 2 else None
    _set_global(status, note, m.from_user.id)
    await m.reply(t(lang, "sec.admin.updated_ok"))

# /sec_game <code> safe|warn|down [note...]
@router.message(Command("sec_game"))
async def cmd_sec_game(m: Message):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(t(lang, "sec.admin.only_admin"))
    toks = (m.text or "").split(maxsplit=3)
    if len(toks) < 3 or toks[2] not in STATUS_ORDER:
        return await m.reply(t(lang, "sec.admin.usage_game"))
    code = toks[1]
    status = toks[2]
    note = toks[3] if len(toks) > 3 else None
    _set_game(code, status, note, m.from_user.id)
    await m.reply(t(lang, "sec.admin.updated_ok"))

