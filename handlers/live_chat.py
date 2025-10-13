from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/live_chat.py

import os, json, time, logging, inspect
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from lang import t, get_user_lang
from aiogram.filters import Command

__all__ = ["router", "LiveChat"]

router = Router(name="live_chat")
log = logging.getLogger(__name__)

# =============== ANTI-CONFLICT PATCH ===============
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")
# Ù„Ø§ ØªÙØ¹Ù‘Ù„ Ù‡Ø°Ø§ Ø§Ù„ÙÙ„ØªØ± Ø§Ù„Ø¹Ø§Ù… Ù‡Ù†Ø§ Ø­ØªÙ‰ Ù„Ø§ ÙŠØ¤Ø«Ø± Ø¹Ù„Ù‰ Ø±Ø§ÙˆØªØ±Ø§Øª Ø£Ø®Ø±Ù‰:
# router.message.filter(~F.text.startswith("/"), ~F.caption.startswith("/"))
router.callback_query.filter(F.data.startswith("live:") | (F.data == "bot:live"))
# ===================================================

# ----(optional) unified inbox binding ----
try:
    from utils import support_inbox as _inbox
except Exception:
    _inbox = None

def _inbox_call(fn: str, *a, **kw):
    """Call support_inbox.fn if available; ignore failures."""
    try:
        if _inbox and hasattr(_inbox, fn):
            getattr(_inbox, fn)(*a, **kw)
    except Exception:
        pass
# ----------------------------------------

ADMIN_ONLINE_TTL = int(os.getenv("ADMIN_ONLINE_TTL", "600"))  # 10 Ø¯Ù‚Ø§Ø¦Ù‚

ADMIN_IDS = get_admin_ids()
def _targets() -> list[int]:
    return [aid for aid in ADMIN_IDS]

# ---- Role-aware admin gate (works with or without roles.py) ----
try:
    from utils.roles import has_role_at_least as _has_role
    def _is_admin(uid: int) -> bool:
        # Ù†Ø³Ù…Ø­ Ù„Ù…Ù† Ø¯ÙˆØ±Ù‡ support Ø£Ùˆ Ø£Ø¹Ù„Ù‰ (support/moderator/admin/superadmin/owner)
        return bool(_has_role(uid, "support"))
except Exception:
    def _is_admin(uid: int) -> bool:
        return uid in ADMIN_IDS
# ----------------------------------------------------------------

DATA = Path("data")
SESSIONS_FILE = DATA/"live_sessions.json"
RELAYS_FILE   = DATA/"live_relays.json"
ADMIN_ACTIVE  = DATA/"live_admin_active.json"
HISTORY_FILE  = DATA/"live_history.json"
RATINGS_FILE  = DATA/"live_ratings.json"
BLOCKLIST_FILE= DATA/"live_blocklist.json"
ADMIN_SEEN    = DATA/"admin_last_seen.json"
SESSION_TTL = 60*30
LIVE_CONFIG = DATA/"live_config.json"

def _now() -> float: return time.time()

def _load(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(p: Path, obj):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        log.warning("save %s failed: %s", p, e)

def _support_enabled() -> bool:
    cfg = _load(LIVE_CONFIG)
    return bool(cfg.get("enabled", True))

def _blocked(uid: int) -> bool:
    row = _load(BLOCKLIST_FILE).get(str(uid))
    if not row:
        return False
    if isinstance(row, dict):
        until = float(row.get("until", 0) or 0)
        if until and _now() > until:
            bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
            return False
        return True
    return bool(row)

def _L(uid: int) -> str:
    try:
        return (get_user_lang(uid) or "ar").lower()
    except Exception:
        return "ar"

def _tt(lang: str, key: str, ar: str, en: str) -> str:
    try:
        val = t(lang, key)
        if val and val != key:
            return val
    except Exception:
        pass
    return ar if (lang or "ar").startswith("ar") else en

def _get_session(uid: int) -> dict:
    return _load(SESSIONS_FILE).get(str(uid), {})

def _put_session(uid: int, data: dict):
    s = _load(SESSIONS_FILE); s[str(uid)] = data; _save(SESSIONS_FILE, s)

def _del_session(uid: int):
    s = _load(SESSIONS_FILE); s.pop(str(uid), None); _save(SESSIONS_FILE, s)

def _touch(uid: int):
    s = _get_session(uid)
    if s:
        s["last_ts"] = _now()
        _put_session(uid, s)

def _expired(sess: dict) -> bool:
    return (_now() - float(sess.get("last_ts", 0))) > SESSION_TTL

def _set_admin_active(admin_id: int, uid: int):
    m = _load(ADMIN_ACTIVE); m[str(admin_id)] = int(uid); _save(ADMIN_ACTIVE, m)

def _clear_admin_active(admin_id: int):
    m = _load(ADMIN_ACTIVE); 
    if str(admin_id) in m:
        m.pop(str(admin_id), None); _save(ADMIN_ACTIVE, m)

def _get_admin_active(admin_id: int) -> int | None:
    m = _load(ADMIN_ACTIVE); v = m.get(str(admin_id))
    try:
        return int(v) if v else None
    except Exception:
        return None

def _ensure_history(sid: str, uid: int, admin_id: int | None, start_ts: float):
    h = _load(HISTORY_FILE)
    if sid not in h:
        h[sid] = {"uid": uid, "admin_id": admin_id, "start_ts": start_ts}
        _save(HISTORY_FILE, h)

def _update_history(sid: str, **fields):
    h = _load(HISTORY_FILE); rec = h.get(sid) or {}
    rec.update(fields); h[sid] = rec; _save(HISTORY_FILE, h)

def _finish_history(sid: str, tag: str | None = None) -> dict:
    h = _load(HISTORY_FILE); rec = h.get(sid) or {}
    if rec:
        rec["end_ts"] = _now()
        rec["duration"] = max(0, int(rec["end_ts"] - float(rec.get("start_ts", _now()))))
        if tag: rec["tag"] = tag
        h[sid] = rec; _save(HISTORY_FILE, h)
    return rec

def _set_admin_rating(sid: str, stars: int):
    r = _load(RATINGS_FILE); row = r.get(sid) or {}
    row["admin_rating"] = int(stars); r[sid] = row; _save(RATINGS_FILE, r)

def _format_period(seconds: int) -> str:
    # ØªÙ†Ø³ÙŠÙ‚ Ø¨Ø³ÙŠØ·: Ø£ÙŠØ§Ù…/Ø³Ø§Ø¹Ø§Øª/Ø¯Ù‚Ø§Ø¦Ù‚
    s = int(seconds)
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) or f"{s}s"

def _block_user(uid: int, seconds: int, reason: str | None = None):
    """ÙŠØ­Ø¸Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ù„Ù…Ø¯Ø© Ù…Ø¹ÙŠÙ‘Ù†Ø© Ø¨Ø§Ù„Ø«ÙˆØ§Ù†ÙŠ."""
    bl = _load(BLOCKLIST_FILE)
    bl[str(uid)] = {"until": _now() + max(1, int(seconds)), "reason": reason or ""}
    _save(BLOCKLIST_FILE, bl)

def _block_status(uid: int) -> tuple[bool, int, str | None]:
    """
    ÙŠØ±Ø¬Ø¹ (is_blocked, remaining_seconds, reason).
    ÙŠÙ†Ø¸Ù‘Ù Ø§Ù„Ø­Ø¸Ø± Ø§Ù„Ù…Ù†ØªÙ‡ÙŠ ØªÙ„Ù‚Ø§Ø¦ÙŠØ§Ù‹.
    """
    row = _load(BLOCKLIST_FILE).get(str(uid))
    if not row:
        return False, 0, None
    try:
        until = float(row.get("until", 0) or 0)
    except Exception:
        until = 0
    rem = max(0, int(until - _now()))
    if rem <= 0:
        bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
        return False, 0, None
    return True, rem, (row.get("reason") or None)

def _fmt_dur(sec: int, lang: str) -> str:
    """ØªÙ†Ø³ÙŠÙ‚ Ù…Ø®ØªØµØ± Ù„Ù„Ù…Ø¯Ø© Ø§Ù„Ù…ØªØ¨Ù‚Ù‘ÙŠØ© (Ø£ÙŠØ§Ù…/Ø³Ø§Ø¹Ø§Øª/Ø¯Ù‚Ø§Ø¦Ù‚/Ø«ÙˆØ§Ù†Ù)."""
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}" + (" ÙŠÙˆÙ…" if lang.startswith("ar") else "d"))
    if h: parts.append(f"{h}" + (" Ø³Ø§Ø¹Ø©" if lang.startswith("ar") else "h"))
    if m and not d: parts.append(f"{m}" + (" Ø¯Ù‚ÙŠÙ‚Ø©" if lang.startswith("ar") else "m"))
    if s and not d and not h: parts.append(f"{s}" + (" Ø«Ø§Ù†ÙŠØ©" if lang.startswith("ar") else "s"))
    return " ".join(parts) or ("Ø«ÙˆØ§Ù†Ù" if lang.startswith("ar") else "secs")

def _get_strikes(uid: int) -> int:
    bl = _load(BLOCKLIST_FILE)
    row = bl.get(str(uid)) or {}
    return int(row.get("strikes", 0))

def _put_block(uid: int, seconds: int, reason: str | None = None):
    bl = _load(BLOCKLIST_FILE)
    row = bl.get(str(uid)) or {}
    strikes = int(row.get("strikes", 0)) + 1
    until = _now() + max(0, int(seconds))
    bl[str(uid)] = {"until": until, "reason": reason or "", "strikes": strikes}
    _save(BLOCKLIST_FILE, bl)

def _clear_block(uid: int):
    bl = _load(BLOCKLIST_FILE)
    if str(uid) in bl:
        bl.pop(str(uid), None)
        _save(BLOCKLIST_FILE, bl)

# (Ø§Ø®ØªÙŠØ§Ø±ÙŠ) ØªØµØ¹ÙŠØ¯ ØªÙ„Ù‚Ø§Ø¦ÙŠ Ø¥Ù† Ø£Ø±Ø¯Øª â€” Ù…Ø«Ø§Ù„: Ã—2 Ù„ÙƒÙ„ Ø¶Ø±Ø¨Ø©
def _auto_penalty_seconds(base_seconds: int, strikes_after: int) -> int:
    # strike1=1x, strike2=2x, strike3=4x, ...
    factor = 2 ** max(0, strikes_after-1)
    return int(base_seconds * factor)

def _set_user_rating(sid: str, stars: int):
    r = _load(RATINGS_FILE); row = r.get(sid) or {}
    row["user_rating"] = int(stars); r[sid] = row; _save(RATINGS_FILE, r)

def _touch_admin(admin_id: int):
    m = _load(ADMIN_SEEN)
    row = m.get(str(admin_id))
    if isinstance(row, dict):
        row["ts"] = _now()
    else:
        row = {"online": True, "ts": _now()}
    m[str(admin_id)] = row
    _save(ADMIN_SEEN, m)

def _set_admin_online(admin_id: int, online: bool):
    m = _load(ADMIN_SEEN)
    row = m.get(str(admin_id)) or {}
    row["online"] = bool(online)
    row["ts"] = _now()
    m[str(admin_id)] = row
    _save(ADMIN_SEEN, m)

def _any_admin_online() -> bool:
    m = _load(ADMIN_SEEN)
    now = _now()
    any_online = False
    dirty = False

    for k, v in m.items():
        if isinstance(v, dict):
            ts = float(v.get("ts", 0) or 0)
            online = bool(v.get("online", False))
            # Ø£ÙˆÙ†Ù„Ø§ÙŠÙ† ÙÙ‚Ø· Ø¥Ø°Ø§ Ø¶Ù…Ù† Ø§Ù„Ù†Ø§ÙØ°Ø© Ø§Ù„Ø²Ù…Ù†ÙŠØ©
            if online and ts and (now - ts) <= ADMIN_ONLINE_TTL:
                any_online = True
            elif online and ts and (now - ts) > ADMIN_ONLINE_TTL:
                m[k]["online"] = False
                dirty = True
        else:
            # Ø´ÙƒÙ„ Ù‚Ø¯ÙŠÙ…: Ù‚ÙŠÙ…Ø© = Ø¢Ø®Ø± Ø¸Ù‡ÙˆØ± (ts)
            try:
                if (now - float(v)) <= ADMIN_ONLINE_TTL:
                    any_online = True
                else:
                    dirty = True
            except Exception:
                pass

    if dirty:
        _save(ADMIN_SEEN, m)
    return any_online

def _live_available() -> bool:
    """Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù…ØªØ§Ø­Ø© ÙÙ‚Ø· Ø¥Ø°Ø§ ÙƒØ§Ù†Øª Ù…ÙØ¹Ù‘Ù„Ø© ÙˆÙŠÙˆØ¬Ø¯ Ø¥Ø¯Ù…Ù† Ø£ÙˆÙ†Ù„Ø§ÙŠÙ†."""
    try:
        return _support_enabled() and _any_admin_online()
    except Exception:
        return False


def _admin_is_online(aid: int) -> bool:
    m = _load(ADMIN_SEEN).get(str(aid))
    if isinstance(m, dict):
        ts = float(m.get("ts", 0) or 0)
        online = bool(m.get("online", False))
        return online and ts and (_now() - ts) <= ADMIN_ONLINE_TTL
    try:
        return (_now() - float(m)) <= ADMIN_ONLINE_TTL
    except Exception:
        return False

async def _notify_admins_t(bot, key: str, ar: str, en: str, build_kb=None, **fmt):
    for aid in _targets():
        # Ø£Ø±Ø³Ù„ Ø¥Ø´Ø¹Ø§Ø± ÙÙ‚Ø· Ù„Ù„Ø¥Ø¯Ù…Ù† Ø§Ù„Ø£ÙˆÙ†Ù„Ø§ÙŠÙ†
        if not _admin_is_online(aid):
            continue
        try:
            alang = _L(aid)
            text = _tt(alang, key, ar, en).format(**fmt)
            kb = None
            if build_kb:
                res = build_kb(alang)
                if inspect.isawaitable(res):
                    res = await res
                kb = res
            await bot.send_message(aid, text, reply_markup=kb)
        except Exception as e:
            log.warning("[live] notify %s failed: %s", aid, e)


def _sid_pack(s: str) -> str:
    return str(s).replace(":", "~")

def _sid_unpack(s: str) -> str:
    return str(s).replace("~", ":")

def _parse_uid_sid(data: str) -> tuple[int, str]:
    parts = data.split(":")
    uid = int(parts[2]); sid_packed = ":".join(parts[3:])
    return uid, _sid_unpack(sid_packed)

def _parse_uid_sid_tag(data: str) -> tuple[int, str, str]:
    parts = data.split(":")
    uid = int(parts[2]); tag = parts[-1]
    sid_packed = ":".join(parts[3:-1])
    return uid, _sid_unpack(sid_packed), tag

def _parse_uid_sid_stars(data: str) -> tuple[int, str, int]:
    parts = data.split(":")
    uid = int(parts[2]); stars = int(parts[-1])
    sid_packed = ":".join(parts[3:-1])
    return uid, _sid_unpack(sid_packed), stars

# ================== UI ==================
def _kb_user_actions(lang: str, sid: str) -> InlineKeyboardMarkup:
    psid = _sid_pack(sid)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang,"live.btn.end","âŒ Ø¥Ù†Ù‡Ø§Ø¡ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©","âŒ End chat"), callback_data="live:end_self"),
        InlineKeyboardButton(text=_tt(lang,"live.btn.rate","â­ ØªÙ‚ÙŠÙŠÙ…","â­ Rate"), callback_data=f"live:rateopen:{psid}")
    ]])

def _kb_user_rate_choices(psid: str, lang: str) -> InlineKeyboardMarkup:
    stars = [InlineKeyboardButton(text=f"{i}â­", callback_data=f"live:urate:{psid}:{i}") for i in range(1,6)]
    back  = InlineKeyboardButton(text=("â¬…ï¸ Ø±Ø¬ÙˆØ¹" if lang.startswith("ar") else "â¬…ï¸ Back"), callback_data=f"live:rateclose:{psid}")
    return InlineKeyboardMarkup(inline_keyboard=[stars,[back]])

def _kb_user_wait(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang, "live.btn.cancel", "âŒ Ø¥Ù„ØºØ§Ø¡ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©", "âŒ Cancel chat"), callback_data="live:cancel")
    ]])

def _kb_user_end(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang, "live.btn.end", "âŒ Ø¥Ù†Ù‡Ø§Ø¡ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©", "âŒ End chat"), callback_data="live:end_self")
    ]])

CATEGORIES = {
    "app": ("Ù…Ø´Ø§ÙƒÙ„ Ø§Ù„ØªØ·Ø¨ÙŠÙ‚", "App issues"),
    "pay": ("Ù…Ø´Ø§ÙƒÙ„ Ø§Ù„Ø¯ÙØ¹", "Payment issues"),
    "ask": ("Ø§Ø³ØªÙØ³Ø§Ø±Ø§Øª Ø¹Ø§Ù…Ø©", "General questions"),
    "prom": ("Ø£Ø±ÙŠØ¯ Ø£Ù† Ø£ØµØ¨Ø­ Ù…ÙØ±ÙˆÙ‘Ø¬Ù‹Ø§", "Become a promoter"),
    "sup": ("Ø£Ø±ÙŠØ¯ Ø£Ù† Ø£ØµØ¨Ø­ Ù…ÙˆØ±Ù‘Ø¯Ù‹Ø§", "Become a supplier"),
    "other": ("Ø£Ø®Ø±Ù‰", "Other"),
}
def _cat_label(lang: str, code: str) -> str:
    ar, en = CATEGORIES.get(code, CATEGORIES["other"])
    return ar if lang.startswith("ar") else en

def _kb_pre_live(lang: str) -> InlineKeyboardMarkup:
    rows = [[("app","ðŸ› ï¸"), ("pay","ðŸ’³")],
            [("ask","â“"), ("prom","ðŸ“£")],
            [("sup","ðŸ›ï¸"), ("other","ðŸ“")]]
    ik = []
    for pair in rows:
        row = []
        for code, icon in pair:
            row.append(InlineKeyboardButton(text=f"{icon} {_cat_label(lang, code)}", callback_data=f"live:cat:{code}"))
        ik.append(row)
    # â¬…ï¸ Ù…Ù‡Ù…: Namespace Ù…Ø­Ù„ÙŠ Ù„Ù„Ø¯Ø±Ø¯Ø´Ø© ÙÙ‚Ø· Ù„ØªØ¬Ù†Ø¨ Ø§Ù„ØªØ¹Ø§Ø±Ø¶ Ù…Ø¹ Ø£ÙŠ back Ø¹Ø§Ù…
    ik.append([InlineKeyboardButton(text=("â¬…ï¸ Ø±Ø¬ÙˆØ¹" if lang.startswith("ar") else "â¬…ï¸ Back"),
                                    callback_data="live:back")])
    return InlineKeyboardMarkup(inline_keyboard=ik)

def _pre_header(lang: str) -> str:
    if lang == "ar":
        return ("ðŸ’¬ <b>Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø©</b>\nØ§Ø®ØªØ± Ù†ÙˆØ¹ Ø·Ù„Ø¨Ùƒ Ø£ÙˆÙ„Ù‹Ø§ Ù„Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ù…Ø³Ø§Ø¹Ø¯Ø© Ø£Ø³Ø±Ø¹:")
    return ("ðŸ’¬ <b>Live chat</b>\nPlease pick a category first for faster help:")

def _cat_hint(lang: str, code: str) -> str:
    if lang == "ar":
        mapping = {
            "app": "â€¢ Ø«Ø¨Ù‘Øª Ø¢Ø®Ø± Ù†Ø³Ø®Ø© Ù…Ù† Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ (Ø²Ø± <b>ØªØ«Ø¨ÙŠØª ØªØ·Ø¨ÙŠÙ‚ Ø«Ø¹Ø¨Ø§Ù†</b> ÙÙŠ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø©)\nâ€¢ Ø£Ø±ÙÙ‚ ØµÙˆØ±Ø©/ÙÙŠØ¯ÙŠÙˆ Ù„Ù„Ù…Ø´ÙƒÙ„Ø© + Ù†ÙˆØ¹ Ø¬Ù‡Ø§Ø²Ùƒ ÙˆØ£Ù†Ø¯Ø±ÙˆÙŠØ¯.",
            "pay": "â€¢ Ø£Ø±ÙÙ‚ Ù„Ù‚Ø·Ø© Ø´Ø§Ø´Ø© Ù„Ø¹Ù…Ù„ÙŠØ© Ø§Ù„Ø¯ÙØ¹ ÙˆØ±Ù‚Ù… Ø§Ù„Ø·Ù„Ø¨ (Ø¥Ù† ÙˆØ¬Ø¯) + Ø§Ø³Ù… Ø§Ù„Ø¨Ø§Ø¦Ø¹.\nâ€¢ ÙŠÙ…ÙƒÙ† ÙØªØ­ ØªØ°ÙƒØ±Ø© Ø£ÙŠØ¶Ù‹Ø§ Ø¨Ù€ /report.",
            "ask": "â€¢ Ø§ÙƒØªØ¨ Ø³Ø¤Ø§Ù„Ùƒ Ø¨Ø¥ÙŠØ¬Ø§Ø². Ø¥Ù† ÙƒØ§Ù† Ø¹Ù† Ø§Ù„Ø£Ù…Ø§Ù†ØŒ Ø±Ø§Ø¬Ø¹ Â«Ø¯Ù„ÙŠÙ„ Ø§Ù„Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø§Ù„Ø¢Ù…Ù†Â».",
            "prom": "â€¢ Ø§Ø·Ù„Ø¹ Ø£ÙˆÙ„Ù‹Ø§ Ø¹Ù„Ù‰ Ø´Ø±ÙˆØ· ÙˆÙ†ØµØ§Ø¦Ø­ Ø§Ù„Ù…Ø±ÙˆÙ‘Ø¬ÙŠÙ† Ù…Ù† Â«ÙƒÙŠÙ ØªØµØ¨Ø­ Ù…ÙØ±ÙˆÙ‘Ø¬Ù‹Ø§ØŸÂ».",
            "sup": "â€¢ Ù„Ù„ØªÙ‚Ø¯ÙŠÙ… ÙƒÙ…ÙˆØ±Ù‘Ø¯ Ø§Ø³ØªØ®Ø¯Ù… Â«ÙƒÙŠÙ ØªØµØ¨Ø­ Ù…ÙˆØ±Ù‘Ø¯Ù‹Ø§ØŸÂ» Ù…Ù† Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© ÙˆØ§Ù‚Ø±Ø£ Ø§Ù„Ø´Ø±ÙˆØ·.",
            "other": "â€¢ ØµÙ Ù…Ø´ÙƒÙ„ØªÙƒ Ø¨Ø¥ÙŠØ¬Ø§Ø² ÙˆØ§Ø°ÙƒØ± Ø£ÙŠ ØªÙØ§ØµÙŠÙ„ Ù…ÙÙŠØ¯Ø© (ØµÙˆØ±/Ø±ÙˆØ§Ø¨Ø·/Ø®Ø·ÙˆØ§Øª).",
        }
    else:
        mapping = {
            "app": "â€¢ Make sure you installed the latest app (see â€œDownload Appâ€).\nâ€¢ Attach a screenshot/video + your device model & Android.",
            "pay": "â€¢ Attach a payment screenshot and order ID (if any) + seller name.\nâ€¢ You can also open a ticket via /report.",
            "ask": "â€¢ Ask briefly. For safety questions, check â€œSafe Usage Guideâ€.",
            "prom": "â€¢ Read â€œBecome a promoter?â€ first for requirements.",
            "sup": "â€¢ Use â€œBecome a supplier?â€ in the menu and review the requirements.",
            "other": "â€¢ Describe your issue briefly and add useful details (images/links/steps).",
        }
    return mapping.get(code, mapping["other"])

def _terms_text(lang: str) -> str:
    if lang == "ar":
        return ("ðŸ“œ <b>Ø´Ø±ÙˆØ· Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©</b>\n"
                "1) ÙƒÙ† Ù…Ø­ØªØ±Ù…Ù‹Ø§ ÙˆØªØ­Ø¯Ù‘Ø« Ø¹Ù† Ù…ÙˆØ¶ÙˆØ¹ ÙˆØ§Ø­Ø¯ ÙÙ‚Ø·.\n"
                "2) Ù„Ø§ ØªØ´Ø§Ø±Ùƒ Ø¨ÙŠØ§Ù†Ø§Øª Ø­Ø³Ù‘Ø§Ø³Ø© Ø£Ùˆ Ø£ÙƒÙˆØ§Ø¯ Ø´Ø±Ø§Ø¡ Ø¹Ù„Ù†Ù‹Ø§.\n"
                "3) Ø£Ø±ÙÙ‚ Ù„Ù‚Ø·Ø§Øª/ØªÙØ§ØµÙŠÙ„ ÙˆØ§Ø¶Ø­Ø© Ù„ØªØ³Ø±ÙŠØ¹ Ø§Ù„Ø­Ù„.\n"
                "4) Ù‚Ø¯ ØªÙØ³ØªØ®Ø¯Ù… Ø§Ù„Ù…Ø­Ø§Ø¯Ø«Ø© Ù„ØªØ­Ø³ÙŠÙ† Ø¬ÙˆØ¯Ø© Ø§Ù„Ø®Ø¯Ù…Ø©.\n\n"
                "Ø¨Ø§Ù„Ø¶ØºØ· Ø¹Ù„Ù‰ Â«Ø£ÙˆØ§ÙÙ‚ ÙˆØ§Ø¨Ø¯Ø£Â»ØŒ Ø³ÙŠØªÙ… ÙØªØ­ Ø¯Ø±Ø¯Ø´Ø© Ù…Ø¹ Ø§Ù„Ø¯Ø¹Ù….")
    return ("ðŸ“œ <b>Chat terms</b>\n"
            "1) Be respectful and stick to one topic.\n"
            "2) Donâ€™t share sensitive data publicly.\n"
            "3) Provide clear screenshots/details for faster help.\n"
            "4) Chat may be used to improve service quality.\n\n"
            "By tapping â€œAgree & Startâ€, weâ€™ll open a chat with support.")

def _kb_terms(lang: str, code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("âœ… Ø£ÙˆØ§ÙÙ‚ ÙˆØ§Ø¨Ø¯Ø£" if lang=="ar" else "âœ… Agree & Start"),
                              callback_data=f"live:start:{code}")],
        [InlineKeyboardButton(text=("â¬…ï¸ Ø§Ø®ØªÙŠØ§Ø± Ù†ÙˆØ¹ Ø¢Ø®Ø±" if lang=="ar" else "â¬…ï¸ Pick another"),
                              callback_data="live:pre")]
    ])

@router.callback_query(F.data == "live:back")
async def cb_live_back(cb: CallbackQuery):
    # Ù†Ø­Ø°Ù Ø±Ø³Ø§Ù„Ø© Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© ÙÙ‚Ø· Ø¨Ø¯ÙˆÙ† Ù„Ù…Ø³ Ø£ÙŠ Ø±Ø§ÙˆØªØ± Ø¢Ø®Ø±
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()

def _kb_blocked(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=("âŸ³ ØªØ­Ø¯ÙŠØ« Ø§Ù„ÙˆÙ‚Øª" if lang.startswith("ar") else "âŸ³ Refresh"),
                             callback_data="live:brefresh")
    ]])

@router.callback_query(F.data == "live:brefresh")
async def cb_block_refresh(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    blocked, remain, _ = _block_status(uid)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "â›” ØªÙ… Ø­Ø¸Ø±Ùƒ Ù…Ù† Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø©.\nØ§Ù„ÙˆÙ‚Øª Ø§Ù„Ù…ØªØ¨Ù‚Ù‘ÙŠ: {rem}",
                  "â›” You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            pass
        return await cb.answer()
    # Ù„Ù… ÙŠØ¹Ø¯ Ù…Ø­Ø¸ÙˆØ±Ø§Ù‹ â†’ Ù†Ø±Ø¬Ø¹ Ù„Ø´Ø§Ø´Ø© Ù…Ø§ Ù‚Ø¨Ù„ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©
    try:
        await cb.message.edit_text(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
    except Exception:
        try:
            await cb.message.answer(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
        except Exception:
            pass
    await cb.answer(_tt(lang, "live.unblocked", "ØªÙ… Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø±. ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ù„Ø¨Ø¯Ø¡ Ø§Ù„Ø¢Ù†.", "Ban lifted. You can start now."))

@router.callback_query(F.data.in_({"bot:live", "live:pre"}))
async def cb_open_pre(cb: CallbackQuery):
    lang = _L(cb.from_user.id)

    # ðŸ”’ Ø­Ø¸Ø±: Ø§Ø¹Ø±Ø¶ Ø±Ø³Ø§Ù„Ø© ØªÙØµÙŠÙ„ÙŠØ© Ù…Ø¹ Ø§Ù„ÙˆÙ‚Øª Ø§Ù„Ù…ØªØ¨Ù‚Ù‘ÙŠ
    blocked, remain, _ = _block_status(cb.from_user.id)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "â›” ØªÙ… Ø­Ø¸Ø±Ùƒ Ù…Ù† Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø©.\nØ§Ù„ÙˆÙ‚Øª Ø§Ù„Ù…ØªØ¨Ù‚Ù‘ÙŠ: {rem}",
                  "â›” You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            try:
                await cb.message.answer(txt, reply_markup=_kb_blocked(lang))
            except Exception:
                pass
        return await cb.answer()

    # â›” ØºÙŠØ± Ù…ØªØ§Ø­Ø© Ø§Ù„Ø¢Ù†
    if not _live_available():
        try:
            await cb.message.edit_text(
                _tt(lang, "live.unavailable",
                    "â• Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø© ØºÙŠØ± Ù…ØªØ§Ø­Ø© Ø§Ù„Ø¢Ù†. Ø­Ø§ÙˆÙ„ Ù„Ø§Ø­Ù‚Ù‹Ø§.",
                    "â• Live chat is currently unavailable. Please try later.")
            )
        except Exception:
            try:
                await cb.message.answer(
                    _tt(lang, "live.unavailable",
                        "â• Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø© ØºÙŠØ± Ù…ØªØ§Ø­Ø© Ø§Ù„Ø¢Ù†. Ø­Ø§ÙˆÙ„ Ù„Ø§Ø­Ù‚Ù‹Ø§.",
                        "â• Live chat is currently unavailable. Please try later.")
                )
            except Exception:
                pass
        return await cb.answer()

    # âœ… Ù…ØªØ§Ø­Ø© â†’ Ø§Ø¹Ø±Ø¶ Ø´Ø§Ø´Ø© Ø§Ù„ØªØµÙ†ÙŠÙØ§Øª
    try:
        await cb.message.edit_text(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
    except Exception:
        try:
            await cb.message.answer(_pre_header(lang), reply_markup=_kb_pre_live(lang), parse_mode="HTML")
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("live:cat:"))
async def cb_pick_category(cb: CallbackQuery):
    lang = _L(cb.from_user.id)

    # ðŸ”’ Ø­Ø¸Ø±
    blocked, remain, _ = _block_status(cb.from_user.id)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "â›” ØªÙ… Ø­Ø¸Ø±Ùƒ Ù…Ù† Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø©.\nØ§Ù„ÙˆÙ‚Øª Ø§Ù„Ù…ØªØ¨Ù‚Ù‘ÙŠ: {rem}",
                  "â›” You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            try:
                await cb.message.answer(txt, reply_markup=_kb_blocked(lang))
            except Exception:
                pass
        return await cb.answer()

    # â›” ØºÙŠØ± Ù…ØªØ§Ø­Ø©
    if not _live_available():
        try:
            await cb.message.edit_text(
                _tt(lang, "live.unavailable",
                    "â• Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø© ØºÙŠØ± Ù…ØªØ§Ø­Ø© Ø§Ù„Ø¢Ù†. Ø­Ø§ÙˆÙ„ Ù„Ø§Ø­Ù‚Ù‹Ø§.",
                    "â• Live chat is currently unavailable. Please try later.")
            )
        except Exception:
            try:
                await cb.message.answer(
                    _tt(lang, "live.unavailable",
                        "â• Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø© ØºÙŠØ± Ù…ØªØ§Ø­Ø© Ø§Ù„Ø¢Ù†. Ø­Ø§ÙˆÙ„ Ù„Ø§Ø­Ù‚Ù‹Ø§.",
                        "â• Live chat is currently unavailable. Please try later.")
                )
            except Exception:
                pass
        return await cb.answer()

    # âœ… Ø£Ø¹Ø±Ø¶ Ø§Ù„Ø´Ø±ÙˆØ· Ø­Ø³Ø¨ Ø§Ù„ØªØµÙ†ÙŠÙ
    code = cb.data.split(":")[2]
    title = _cat_label(lang, code)
    text = f"ðŸ—‚ï¸ <b>{title}</b>\n{_cat_hint(lang, code)}\n\n{_terms_text(lang)}"
    try:
        await cb.message.edit_text(text, reply_markup=_kb_terms(lang, code), parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        try:
            await cb.message.answer(text, reply_markup=_kb_terms(lang, code), parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
    await cb.answer()


class LiveChat(StatesGroup):
    active = State()   # Ø­Ø§Ù„Ø© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…
    admin  = State()   # ÙˆØ¶Ø¹ Ø§Ù„Ø¥Ø¯Ù…Ù† Ø§Ù„Ù…Ø¹Ø²ÙˆÙ„ Ù„Ù„Ø±Ø¯
    block_wait = State()  # Ø§Ù„Ø¥Ø¯Ù…Ù† ÙŠÙ†ØªØ¸Ø± Ø¥Ø¯Ø®Ø§Ù„ Ù…Ø¯Ø© Ø§Ù„Ø­Ø¸Ø± Ø§Ù„Ù…Ø®ØµØµØ©


@router.callback_query(F.data.startswith("live:start:"))
async def cb_start_live_after_terms(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = _L(uid)
    category = cb.data.split(":")[2]

    # ðŸ”’ Ù…Ø­Ø¸ÙˆØ± â†’ Ø±Ø³Ø§Ù„Ø© Ù…Ø¹ ÙˆÙ‚Øª Ù…ØªØ¨Ù‚Ù‘ÙŠ + Ø²Ø± ØªØ­Ø¯ÙŠØ«
    blocked, remain, _ = _block_status(uid)
    if blocked:
        txt = _tt(lang, "live.blocked.detail",
                  "â›” ØªÙ… Ø­Ø¸Ø±Ùƒ Ù…Ù† Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø©.\nØ§Ù„ÙˆÙ‚Øª Ø§Ù„Ù…ØªØ¨Ù‚Ù‘ÙŠ: {rem}",
                  "â›” You are blocked from live chat.\nTime remaining: {rem}").format(rem=_fmt_dur(remain, lang))
        try:
            await cb.message.edit_text(txt, reply_markup=_kb_blocked(lang))
        except Exception:
            try:
                await cb.message.answer(txt, reply_markup=_kb_blocked(lang))
            except Exception:
                pass
        return await cb.answer()

    # â›” Ù„Ø§ Ø¥Ø¯Ù…Ù† Ø£ÙˆÙ†Ù„Ø§ÙŠÙ† Ø£Ùˆ Ø§Ù„Ø¯Ø¹Ù… Ù…Ù‚ÙÙˆÙ„
    if not _live_available():
        await cb.message.edit_text(
            _tt(lang, "live.unavailable",
                "â• Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø© ØºÙŠØ± Ù…ØªØ§Ø­Ø© Ø§Ù„Ø¢Ù†. Ø­Ø§ÙˆÙ„ Ù„Ø§Ø­Ù‚Ù‹Ø§.",
                "â• Live chat is currently unavailable. Please try later.")
        )
        return await cb.answer()

    # âœ… Ø§ÙØªØ­ Ø§Ù„Ø·Ù„Ø¨ ÙˆØ§Ø¯Ø®Ù„ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø±
    sid  = f"{uid}:{int(_now())}"
    sess = {"status":"waiting","start_ts":_now(),"last_ts":_now(),"queue":[],"admin_id":None,"sid":sid,"category":category}
    _put_session(uid, sess)
    _ensure_history(sid, uid, None, sess["start_ts"])
    _update_history(sid, category=category)

    preview = f"[{_cat_label(lang, category)}] " + _tt(lang, "live.inbox.new", "Ø·Ù„Ø¨ Ø¯Ø±Ø¯Ø´Ø© Ø¬Ø¯ÙŠØ¯", "New live chat request")
    _inbox_call("enqueue", "live", uid, preview)

    await state.set_state(LiveChat.active)
    await cb.message.edit_text(
        _tt(lang, "live.opened",
            "ðŸ’¬ ØªÙ… ÙØªØ­ Ø·Ù„Ø¨ Ø¯Ø±Ø¯Ø´Ø©.\nØ§Ù„Ø±Ø¬Ø§Ø¡ Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø± Ø­ØªÙ‰ ÙŠÙ†Ø¶Ù… Ø§Ù„Ø¯Ø¹Ù…â€¦",
            "ðŸ’¬ Chat request opened.\nPlease wait for support to joinâ€¦"),
        reply_markup=_kb_user_wait(lang)
    )
    await cb.answer()

    def _mk(alang: str):
        return _kb_admin_request(uid, alang)

    await _notify_admins_t(
        cb.bot,
        "live.admin.notify.request",
        "ðŸ†• Ø·Ù„Ø¨ Ø¯Ø±Ø¯Ø´Ø© Ø­ÙŠÙ‘Ø©\nâ€¢ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…: {name} @{username}\nâ€¢ Ø§Ù„Ù…Ø¹Ø±Ù‘Ù: {uid}\nâ€¢ Ø§Ù„ÙØ¦Ø©: {cat}",
        "ðŸ†• Live chat request\nâ€¢ User: {name} @{username}\nâ€¢ ID: {uid}\nâ€¢ Category: {cat}",
        build_kb=_mk,
        name=cb.from_user.full_name,
        username=cb.from_user.username or "-",
        uid=uid,
        cat=_cat_label(_L(cb.from_user.id), category)
    )


def _kb_admin_request(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang, "live.admin.join", "âœ… Ø§Ù†Ø¶Ù… Ù„Ù„Ø¯Ø±Ø¯Ø´Ø©", "âœ… Join chat"), callback_data=f"live:accept:{uid}"),
        InlineKeyboardButton(text=_tt(lang, "live.admin.decline", "ðŸš« Ø±ÙØ¶", "ðŸš« Decline"), callback_data=f"live:decline:{uid}")
    ]])

def _kb_admin_controls(uid: int, lang: str, sid: str) -> InlineKeyboardMarkup:
    psid = _sid_pack(sid)
    stars = [InlineKeyboardButton(text=f"{i}â­", callback_data=f"live:arate:{uid}:{psid}:{i}") for i in range(1, 6)]
    tags  = [
        InlineKeyboardButton(text=_tt(lang,"live.tag.solved","âœ… Ù…Ø­Ù„ÙˆÙ„Ø©","âœ… Solved"), callback_data=f"live:atag:{uid}:{psid}:solved"),
        InlineKeyboardButton(text=_tt(lang,"live.tag.follow","â³ Ù…ØªØ§Ø¨Ø¹Ø©","â³ Follow-up"), callback_data=f"live:atag:{uid}:{psid}:follow"),
        InlineKeyboardButton(text=_tt(lang,"live.tag.bug","ðŸž Ø¹ÙŠØ¨","ðŸž Bug"), callback_data=f"live:atag:{uid}:{psid}:bug"),
    ]
    # Ø£Ø²Ø±Ø§Ø± Ø§Ù„Ø­Ø¸Ø± Ø§Ù„Ø³Ø±ÙŠØ¹Ø©
    blocks = [
        InlineKeyboardButton(text="ðŸš« 1h",  callback_data=f"live:ablock:{uid}:{psid}:3600"),
        InlineKeyboardButton(text="ðŸš« 24h", callback_data=f"live:ablock:{uid}:{psid}:86400"),
        InlineKeyboardButton(text="ðŸš« 7d",  callback_data=f"live:ablock:{uid}:{psid}:604800"),
        InlineKeyboardButton(text="â›” Ø¯Ø§Ø¦Ù…", callback_data=f"live:ablock:{uid}:{psid}:0"),
    ]
    custom = InlineKeyboardButton(
        text=("â±ï¸ Ø­Ø¸Ø± Ù…ÙØ®ØµØµ" if lang.startswith("ar") else "â±ï¸ Custom block"),
        callback_data=f"live:ablock_custom:{uid}:{psid}"
    )

    # Ø²Ø± Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø±
    unban_btn = InlineKeyboardButton(
        text=("ðŸ”“ Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø±" if lang.startswith("ar") else "ðŸ”“ Unban"),
        callback_data=f"live:aunblock:{uid}:{psid}"
    )

    return InlineKeyboardMarkup(inline_keyboard=[
        stars, tags,
        blocks,
        [custom],
        [unban_btn],  # â† Ù‡Ø°Ø§ Ø§Ù„ØµÙ Ø§Ù„Ø¬Ø¯ÙŠØ¯
        [InlineKeyboardButton(text=_tt(lang,"live.btn.info","â„¹ï¸ Ù…Ø¹Ù„ÙˆÙ…Ø§Øª","â„¹ï¸ Info"), callback_data=f"live:ainfo:{uid}:{psid}"),
         InlineKeyboardButton(text=_tt(lang,"live.btn.end.red","ðŸ”´ Ø¥Ù†Ù‡Ø§Ø¡ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©","ðŸ”´ End chat"), callback_data=f"live:end:{uid}:{psid}")]
    ])


@router.callback_query(F.data.startswith("live:ablock:"))
async def cb_admin_block_quick(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)

    uid, sid, seconds = _parse_uid_sid_stars(cb.data)  # Ø§Ø³ØªØ¹Ù…Ù„Ù†Ø§ Ù†ÙØ³ Ø§Ù„Ø¨Ø§Ø±Ø³Ø±: Ø¢Ø®Ø± Ø¬Ø²Ø¡ ÙƒØ£Ù†Ù‡ "Ù†Ø¬ÙˆÙ…" Ù„ÙƒÙ† Ù‡Ù†Ø§ Ø«ÙˆØ§Ù†ÙŠ
    # Ù…Ù„Ø§Ø­Ø¸Ø©: ÙÙˆÙ‚ Ø§Ø³ØªØ¹Ù…Ù„Ù†Ø§ live:ablock:{uid}:{psid}:{seconds} Ù„Ø°Ù„Ùƒ Ø§Ù„Ø¯Ø§Ù„Ø© ØªØ¹Ù…Ù„ ØªÙ…Ø§Ù…
    seconds = int(seconds)
    # ØªØµØ¹ÙŠØ¯ ØªÙ„Ù‚Ø§Ø¦ÙŠ (Ø§Ø®ØªÙŠØ§Ø±ÙŠ):
    strikes_after = _get_strikes(uid) + 1
    if seconds > 0:
        seconds = _auto_penalty_seconds(seconds, strikes_after)

    # Ø¯ÙˆÙ‘Ù† Ø§Ù„Ø­Ø¸Ø±
    _put_block(uid, seconds if seconds>0 else 10*365*24*3600, reason="quick")  # 0 = Ø¯Ø§Ø¦Ù… â†’ 10 Ø³Ù†ÙˆØ§Øª Ù…Ø«Ù„Ø§Ù‹

    # Ø£Ù†Ù‡Ù Ø§Ù„Ø¬Ù„Ø³Ø© Ù„Ùˆ Ù…ÙˆØ¬ÙˆØ¯Ø©
    sess = _get_session(uid)
    if sess:
        _del_session(uid)
    try:
        await state.clear()
    except Exception:
        pass

    # ÙˆØ³Ù… + Ø¥Ø´Ø¹Ø§Ø±Ø§Øª
    _update_history(sid, tag="blocked")
    lang_user = _L(uid)
    period = "permanent" if seconds==0 else _format_period(seconds)
    try:
        await cb.bot.send_message(uid,
            _tt(lang_user, "live.blocked.msg",
                f"â›” ØªÙ… Ø­Ø¸Ø±Ùƒ Ù…Ù† Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù„Ù…Ø¯Ø©: {period}.",
                f"â›” You have been blocked from live chat for: {period}."))
    except Exception:
        pass

    alang = _L(cb.from_user.id)
    try:
        await cb.message.edit_text(
            _tt(alang, "live.admin.blocked.ok",
                f"â›” ØªÙ… Ø­Ø¸Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid} ({period}) ÙˆØ¥Ù†Ù‡Ø§Ø¡ Ø§Ù„Ø¬Ù„Ø³Ø©.",
                f"â›” User {uid} blocked ({period}) and session ended."),
            reply_markup=None
        )
    except Exception:
        pass

    await _notify_admins_t(cb.bot,
        "live.admin.notify.block",
        "â›” Ø­Ø¸Ø± Ø§Ù„Ø¥Ø¯Ù…Ù† {admin_id} Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid} Ù„Ù…Ø¯Ø© {period}\nSID={sid}",
        "â›” Admin {admin_id} blocked user {uid} for {period}\nSID={sid}",
        admin_id=cb.from_user.id, uid=uid, sid=sid, period=period)

    await cb.answer("Blocked")

@router.callback_query(F.data.startswith("live:aunblock:"))
async def cb_admin_unblock(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)

    # Ù†ÙØ³ ØªÙ†Ø³ÙŠÙ‚ live:aunblock:{uid}:{psid} â†’ Ù†Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø¨Ø§Ø±Ø³Ø± Ø§Ù„Ø¹Ø§Ù…
    uid, sid = _parse_uid_sid(cb.data)

    # Ù„Ùˆ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… ØºÙŠØ± Ù…Ø­Ø¸ÙˆØ±ØŒ Ù†Ø®Ø¨Ø± Ø§Ù„Ø¥Ø¯Ù…Ù† Ø¨Ø´ÙƒÙ„ ÙˆØ¯Ù‘ÙŠ
    was_blocked, _, _ = _block_status(uid)
    _clear_block(uid)

    alang = _L(cb.from_user.id)
    msg_admin = ("ðŸ”“ ØªÙ… Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø± Ø¹Ù† Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid}."
                 if alang.startswith("ar") else
                 "ðŸ”“ Unban completed for user {uid}.")
    try:
        await cb.message.edit_text(msg_admin.format(uid=uid),
                                   reply_markup=_kb_admin_controls(uid, alang, sid))
    except Exception:
        pass

    # Ø£Ø®Ø¨Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø£Ù†Ù‡ ØªÙ… Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø±
    try:
        await cb.bot.send_message(
            uid,
            _tt(_L(uid),
                "live.unblocked",
                "âœ… ØªÙ… Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø±. ÙŠÙ…ÙƒÙ†Ùƒ ÙØªØ­ Ø¯Ø±Ø¯Ø´Ø© Ø¬Ø¯ÙŠØ¯Ø© Ù…Ù† Â«Ø§Ù„Ø¯Ø¹Ù…Â».",
                "âœ… Your ban was lifted. You can start a new chat from Support.")
        )
    except Exception:
        pass

    # Ø¥Ø´Ø¹Ø§Ø± Ù„Ø¨Ø§Ù‚ÙŠ Ø§Ù„Ø¥Ø¯Ù…Ù†Ø² Ø§Ù„Ø£ÙˆÙ†Ù„Ø§ÙŠÙ†
    await _notify_admins_t(
        cb.bot,
        "live.admin.notify.unblock",
        "ðŸ”“ Ø±ÙØ¹ Ø§Ù„Ø¥Ø¯Ù…Ù† {admin_id} Ø§Ù„Ø­Ø¸Ø± Ø¹Ù† Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid} | SID={sid}",
        "ðŸ”“ Admin {admin_id} unblocked user {uid} | SID={sid}",
        admin_id=cb.from_user.id, uid=uid, sid=sid
    )

    # Ø±Ø¯ Ù‚ØµÙŠØ± Ù„ÙˆØ§Ø¬Ù‡Ø© Ø§Ù„Ø²Ø±
    await cb.answer("Unblocked" if not alang.startswith("ar") else "ØªÙ… Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø±")

@router.message(Command("unban"))
async def cmd_unban(m: Message):
    if not _is_admin(m.from_user.id):
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        return await m.reply("Ø§Ø³ØªØ®Ø¯Ù…: /unban <uid>\nExample: /unban 123456789")
    uid = int(parts[1])
    was_blocked, _, _ = _block_status(uid)
    _clear_block(uid)
    await m.reply(("ðŸ”“ ØªÙ… Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø± Ø¹Ù† " if _L(m.from_user.id).startswith("ar") else "ðŸ”“ Unbanned ") + str(uid))
    try:
        await m.bot.send_message(uid,
            _tt(_L(uid),
                "live.unblocked",
                "âœ… ØªÙ… Ø±ÙØ¹ Ø§Ù„Ø­Ø¸Ø±. ÙŠÙ…ÙƒÙ†Ùƒ ÙØªØ­ Ø¯Ø±Ø¯Ø´Ø© Ø¬Ø¯ÙŠØ¯Ø© Ù…Ù† Â«Ø§Ù„Ø¯Ø¹Ù…Â».",
                "âœ… Your ban was lifted. You can start a new chat from Support."))
    except Exception:
        pass


@router.callback_query(F.data.startswith("live:ablock_custom:"))
async def cb_admin_block_custom_open(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    # Ø®Ø²Ù‘Ù† Ø§Ù„Ù‡Ø¯Ù ÙÙŠ FSM Ø«Ù… Ø§Ø·Ù„Ø¨ Ù…Ù† Ø§Ù„Ø¥Ø¯Ù…Ù† Ø¥Ø¯Ø®Ø§Ù„ Ø§Ù„Ø«ÙˆØ§Ù†ÙŠ|Ø³Ø¨Ø¨ (Ø§Ù„Ø³Ø¨Ø¨ Ø§Ø®ØªÙŠØ§Ø±ÙŠ)
    parts = cb.data.split(":")
    uid = int(parts[2]); sid = _sid_unpack(parts[3])
    await state.update_data(block_target_uid=uid, block_target_sid=sid)
    await state.set_state(LiveChat.block_wait)
    await cb.message.answer("â±ï¸ Ø£Ø±Ø³Ù„ Ù…Ø¯Ø© Ø§Ù„Ø­Ø¸Ø± Ø¨Ø§Ù„Ø«ÙˆØ§Ù†ÙŠØŒ ÙˆÙŠÙ…ÙƒÙ† Ø¥Ø¶Ø§ÙØ© Ø³Ø¨Ø¨ Ø¨Ø¹Ø¯ ÙØ§ØµÙ„Ø© Ø¹Ù…ÙˆØ¯ÙŠØ©:\nÙ…Ø«Ø§Ù„: `3600|Ø³Ø¨Ø§Ù…`\nExample: `86400|spam`", parse_mode="Markdown")
    await cb.answer()

@router.message(StateFilter(LiveChat.block_wait))
async def admin_block_custom_apply(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    text = (m.text or "").strip()
    if not text:
        return await m.reply("Ø£Ø±Ø³Ù„ Ø§Ù„Ø«ÙˆØ§Ù†ÙŠ Ø£Ùˆ `seconds|reason`.")
    try:
        if "|" in text:
            s, reason = text.split("|", 1)
            seconds = int(s.strip())
            reason = reason.strip()
        else:
            seconds = int(text)
            reason = ""
    except Exception:
        return await m.reply("ØªÙ†Ø³ÙŠÙ‚ ØºÙŠØ± ØµØ­ÙŠØ­. Ù…Ø«Ø§Ù„: `3600|Ø³Ø¨Ø§Ù…`", parse_mode="Markdown")

    data = await state.get_data()
    uid = int(data.get("block_target_uid"))
    sid = data.get("block_target_sid")

    # ØªØµØ¹ÙŠØ¯ ØªÙ„Ù‚Ø§Ø¦ÙŠ (Ø§Ø®ØªÙŠØ§Ø±ÙŠ)
    strikes_after = _get_strikes(uid) + 1
    if seconds > 0:
        seconds = _auto_penalty_seconds(seconds, strikes_after)

    _put_block(uid, seconds if seconds>0 else 10*365*24*3600, reason=reason or "custom")

    # Ø¥Ù†Ù‡Ù Ø£ÙŠ Ø¬Ù„Ø³Ø©
    if _get_session(uid):
        _del_session(uid)

    await state.clear()

    period = "permanent" if seconds==0 else _format_period(seconds)
    try:
        await m.bot.send_message(uid,
            _tt(_L(uid), "live.blocked.msg",
                f"â›” ØªÙ… Ø­Ø¸Ø±Ùƒ Ù…Ù† Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù„Ù…Ø¯Ø©: {period}.",
                f"â›” You have been blocked from live chat for: {period}."))
    except Exception:
        pass

    _update_history(sid, tag="blocked")
    await m.reply(f"ØªÙ… Ø§Ù„Ø­Ø¸Ø±: UID={uid} | {period} | reason={reason or '-'}")
    await _notify_admins_t(m.bot,
        "live.admin.notify.block",
        "â›” Ø­Ø¸Ø± Ø§Ù„Ø¥Ø¯Ù…Ù† {admin_id} Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid} Ù„Ù…Ø¯Ø© {period}\nSID={sid}\nØ³Ø¨Ø¨: {reason}",
        "â›” Admin {admin_id} blocked user {uid} for {period}\nSID={sid}\nReason: {reason}",
        admin_id=m.from_user.id, uid=uid, sid=sid, period=period, reason=(reason or "-"))

@router.callback_query(F.data == "live:cancel")
async def cb_user_cancel(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id; lang = _L(uid)
    if _get_session(uid): _del_session(uid)
    await state.clear()
    _inbox_call("resolve", "live", uid, status="canceled")
    await cb.message.edit_text(_tt(lang,"live.canceled","ØªÙ… Ø¥Ù„ØºØ§Ø¡ Ø·Ù„Ø¨ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©.","Chat request canceled."))
    await _notify_admins_t(cb.bot,"live.admin.notify.user_canceled","âšªï¸ Ø£Ù„ØºÙ‰ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø·Ù„Ø¨ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© (UID:{uid})","âšªï¸ Live chat canceled by user (UID:{uid})", uid=uid)
    await cb.answer()

@router.callback_query(F.data.startswith("live:accept:"))
async def cb_admin_accept(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid  = int(cb.data.split(":")[-1])
    user_lang = _L(uid)
    sess = _get_session(uid)
    if not sess or _expired(sess):
        _del_session(uid)
        return await cb.answer(_tt(user_lang,"live.expired","Ø§Ù†ØªÙ‡Øª/ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø©.","Expired/Not found"), show_alert=True)

    sess["status"] = "active"; sess["admin_id"] = cb.from_user.id
    _put_session(uid, sess)
    _set_admin_active(cb.from_user.id, uid)
    _ensure_history(sess["sid"], uid, cb.from_user.id, sess["start_ts"])
    _touch_admin(cb.from_user.id)

    # âœ… Ø£Ø¯Ø®Ù„ Ø§Ù„Ø¥Ø¯Ù…Ù† ÙÙŠ ÙˆØ¶Ø¹ Ø§Ù„Ø±Ø¯ Ø§Ù„Ù…Ø¹Ø²ÙˆÙ„
    await state.set_state(LiveChat.admin)

    # ØµÙ†Ø¯ÙˆÙ‚ Ø§Ù„ÙˆØ§Ø±Ø¯: ÙˆØ³Ù… ÙƒÙ€ "Ù‚ÙŠØ¯ Ø§Ù„Ù…Ø¹Ø§Ù„Ø¬Ø©"
    _inbox_call("assign", "live", uid, admin_id=cb.from_user.id)

    try:
        await cb.bot.send_message(
            uid,
            _tt(user_lang,"live.joined.user","âœ… Ø§Ù†Ø¶Ù…Ù‘ Ø£Ø­Ø¯ Ø£Ø¹Ø¶Ø§Ø¡ ÙØ±ÙŠÙ‚ Ø§Ù„Ø¯Ø¹Ù… Ø¥Ù„Ù‰ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©. ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ù„ØªØ­Ø¯Ù‘Ø« Ø§Ù„Ø¢Ù†.","âœ… A support team member has joined. You can talk now."),
            reply_markup=_kb_user_actions(user_lang, sess["sid"])
        )
    except Exception:
        pass

    relays = _load(RELAYS_FILE); delivered = False
    for mid in (sess.get("queue") or []):
        for tgt in _targets():
            try:
                cp = await cb.bot.copy_message(
                    chat_id=tgt, from_chat_id=uid, message_id=mid,
                    reply_markup=_kb_admin_controls(uid, _L(tgt), sess["sid"])
                )
                relays[f"{tgt}:{cp.message_id}"] = uid
                delivered = True
            except Exception as e1:
                try:
                    fwd = await cb.bot.forward_message(chat_id=tgt, from_chat_id=uid, message_id=mid)
                    relays[f"{tgt}:{fwd.message_id}"] = uid
                    delivered = True
                except Exception as e2:
                    log.warning("deliver backlog to %s failed: %s | %s", tgt, e1, e2)
    if delivered: _save(RELAYS_FILE, relays)

    admin_lang = _L(cb.from_user.id)
    cat = sess.get("category","-")
    try:
        await cb.message.edit_text(
            _tt(admin_lang, "live.admin.joined.banner","ðŸŸ¢ Ø§Ù†Ø¶Ù…Ù…Øª Ù„Ù„Ø¯Ø±Ø¯Ø´Ø© Ù…Ø¹ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid}. Ø§Ù„ÙØ¦Ø©: {cat}",
                "ðŸŸ¢ Joined chat with user {uid}. Category: {cat}").format(uid=uid, cat=_cat_label(admin_lang, cat)),
            reply_markup=_kb_admin_controls(uid, admin_lang, sess["sid"])
        )
    except Exception:
        pass

    await _notify_admins_t(cb.bot,
        "live.admin.notify.joined",
        "ðŸŸ¢ Ø§Ù†Ø¶Ù… Ø§Ù„Ø¥Ø¯Ù…Ù† {admin_id} Ù„Ù„Ø¯Ø±Ø¯Ø´Ø©\nSID={sid}\nUID={uid}\nØ§Ù„ÙØ¦Ø©: {cat}",
        "ðŸŸ¢ Admin {admin_id} joined chat\nSID={sid}\nUID={uid}\nCategory: {cat}",
        admin_id=cb.from_user.id, sid=sess["sid"], uid=uid, cat=_cat_label("ar" if admin_lang=="ar" else "en", cat)
    )
    await cb.answer("Joined")

@router.callback_query(F.data.startswith("live:decline:"))
async def cb_admin_decline(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid  = int(cb.data.split(":")[-1]); lang = _L(uid)
    _touch_admin(cb.from_user.id)
    if _get_session(uid): _del_session(uid)
    _inbox_call("resolve", "live", uid, status="declined")
    try:
        await cb.bot.send_message(uid, _tt(lang,"live.declined","Ø¹Ø°Ø±Ù‹Ø§ØŒ Ù„Ø§ ÙŠØªÙˆÙØ± Ø¯Ø¹Ù… Ø§Ù„Ø¢Ù†. Ø­Ø§ÙˆÙ„ Ù„Ø§Ø­Ù‚Ù‹Ø§.","Sorry, support is unavailable now. Please try later."))
    except Exception:
        pass
    # Ø®Ø±ÙˆØ¬ Ù…Ù† ÙˆØ¶Ø¹ Ø§Ù„Ø¥Ø¯Ù…Ù† Ù„Ùˆ ÙƒØ§Ù† Ø¨Ø¯Ø§Ø®Ù„Ù‡
    try: await state.clear()
    except Exception: pass
    await _notify_admins_t(cb.bot,"live.admin.notify.declined","ðŸš« ØªÙ… Ø±ÙØ¶ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid} Ù…Ù† Ø§Ù„Ø¥Ø¯Ù…Ù† {admin_id}","ðŸš« Chat declined for user {uid} by admin {admin_id}", uid=uid, admin_id=cb.from_user.id)
    await cb.answer("Declined")

@router.callback_query(F.data == "live:end_self")
async def cb_end_self(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id; lang = _L(uid)
    sess = _get_session(uid); sid = sess.get("sid") if sess else None
    admin_id = (sess or {}).get("admin_id")
    if sess: _del_session(uid)
    await state.clear()
    _inbox_call("resolve", "live", uid, status="ended_by_user")
    try:
        await cb.message.edit_text(_tt(lang,"live.ended.user","ØªÙ… Ø¥Ù†Ù‡Ø§Ø¡ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©. Ø´ÙƒØ±Ù‹Ø§ Ù„Ùƒ.","Chat ended. Thank you."))
    except Exception:
        pass
    if sid:
        _finish_history(sid)
        await _notify_admins_t(cb.bot,"live.admin.notify.ended_by_user","ðŸ”´ Ø£Ù†Ù‡Ù‰ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© | SID={sid} | UID={uid}","ðŸ”´ Chat ended by user | SID={sid} | UID={uid}", sid=sid, uid=uid)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}â­", callback_data=f"live:urate:{_sid_pack(sid)}:{i}") for i in range(1,6)]])
        try:
            await cb.bot.send_message(uid, _tt(lang,"live.rate.ask","Ù‚ÙŠÙ‘Ù… ØªØ¬Ø±Ø¨ØªÙƒ Ù…Ø¹ Ø§Ù„Ø¯Ø¹Ù…:","Rate your support experience:"), reply_markup=kb)
        except Exception:
            pass
    # Ù†Ø¸Ù‘Ù Ø±Ø¨Ø· Ø§Ù„Ø¥Ø¯Ù…Ù† Ø¨Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…
    if admin_id: _clear_admin_active(admin_id)
    await cb.answer()

@router.callback_query(F.data.startswith("live:end:"))
async def cb_admin_end(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid = _parse_uid_sid(cb.data)
    user_lang = _L(uid)
    sess  = _get_session(uid)
    if sess: _del_session(uid)
    _inbox_call("resolve", "live", uid, status="ended_by_admin")
    try:
        await cb.bot.send_message(uid, _tt(user_lang,"live.ended.support","ØªÙ… Ø¥Ù†Ù‡Ø§Ø¡ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ù…Ù† Ø¬Ù‡Ø© Ø§Ù„Ø¯Ø¹Ù….","Chat has been ended by support."))
    except Exception:
        pass
    summary = _finish_history(sid) or {}
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}â­", callback_data=f"live:urate:{_sid_pack(sid)}:{i}") for i in range(1,6)]])
    try:
        await cb.bot.send_message(uid, _tt(user_lang,"live.rate.ask","Ù‚ÙŠÙ‘Ù… ØªØ¬Ø±Ø¨ØªÙƒ Ù…Ø¹ Ø§Ù„Ø¯Ø¹Ù…:","Rate your support experience:"), reply_markup=kb)
    except Exception:
        pass
    dur = int(summary.get("duration", 0)); tag = summary.get("tag", "-")
    await _notify_admins_t(cb.bot,"live.admin.notify.ended_by_admin","ðŸ”´ Ø£Ù†Ù‡Ù‰ Ø§Ù„Ø¥Ø¯Ù…Ù† {admin_id} Ø§Ù„Ø¯Ø±Ø¯Ø´Ø©\nâ€¢ SID: {sid}\nâ€¢ UID: {uid}\nâ€¢ Ø§Ù„Ù…Ø¯Ø©: {dur}s\nâ€¢ Ø§Ù„ÙˆØ³Ù…: {tag}","ðŸ”´ Chat ended by admin {admin_id}\nâ€¢ SID: {sid}\nâ€¢ UID: {uid}\nâ€¢ Duration: {dur}s\nâ€¢ Tag: {tag}", admin_id=cb.from_user.id, sid=(sid or "-"), uid=uid, dur=dur, tag=tag)
    # Ø®Ø±ÙˆØ¬ Ù…Ù† ÙˆØ¶Ø¹ Ø§Ù„Ø¥Ø¯Ù…Ù† + ÙÙƒ Ø§Ù„Ø±Ø¨Ø·
    try: await state.clear()
    except Exception: pass
    _clear_admin_active(cb.from_user.id)
    await cb.answer("Ended")

@router.callback_query(F.data.startswith("live:arate:"))
async def cb_admin_rate(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid, stars = _parse_uid_sid_stars(cb.data)
    _set_admin_rating(sid, int(stars))
    await cb.answer(f"Rated {stars}â­")
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_admin_controls(int(uid), _L(cb.from_user.id), sid))
    except Exception:
        pass
    await _notify_admins_t(cb.bot,"live.admin.notify.admin_rating","ðŸ› ï¸ Ù‚ÙŠÙ‘Ù… Ø§Ù„Ø¥Ø¯Ù…Ù† {admin_id} Ø¬Ù„Ø³Ø© {sid}: {stars}â­ (UID {uid})","ðŸ› ï¸ Admin {admin_id} rated chat {sid}: {stars}â­ (UID {uid})", admin_id=cb.from_user.id, sid=sid, stars=stars, uid=uid)

@router.callback_query(F.data.startswith("live:atag:"))
async def cb_admin_tag(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid, tag = _parse_uid_sid_tag(cb.data)
    h  = _load(HISTORY_FILE).get(sid) or {"uid": uid}
    h["tag"] = tag; _update_history(sid, **h)
    await cb.answer("Tagged")
    await _notify_admins_t(cb.bot,"live.admin.notify.tag","ðŸ·ï¸ ØªÙ… ØªØ¹ÙŠÙŠÙ† ÙˆØ³Ù…: {tag} | SID={sid} | UID={uid}","ðŸ·ï¸ Tag set: {tag} | SID: {sid} | UID: {uid}", tag=tag, sid=sid, uid=uid)

@router.callback_query(F.data.startswith("live:ainfo:"))
async def cb_admin_info(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    uid, sid = _parse_uid_sid(cb.data)
    h  = _load(HISTORY_FILE).get(sid) or {}
    dur = int(max(0, (_now()-float(h.get("start_ts",_now()))) if not h.get("end_ts") else h.get("duration",0)))
    rr  = _load(RATINGS_FILE).get(sid) or {}
    tag = h.get("tag","-"); cat = h.get("category","-")
    alang = _L(cb.from_user.id)
    text = _tt(alang, "live.admin.info.text",
        "â„¹ï¸ <b>Ù…Ø¹Ù„ÙˆÙ…Ø§Øª</b>\nâ€¢ UID: <code>{uid}</code>\nâ€¢ SID: <code>{sid}</code>\nâ€¢ Ø§Ù„Ù…Ø¯Ø©: <code>{dur}s</code>\nâ€¢ Ø§Ù„ÙˆØ³Ù…: <code>{tag}</code>\nâ€¢ Ø§Ù„ÙØ¦Ø©: <code>{cat}</code>\nâ€¢ Ø§Ù„ØªÙ‚ÙŠÙŠÙ…Ø§Øª â†’ Ø¥Ø¯Ù…Ù†: <code>{ar}</code> | Ù…Ø³ØªØ®Ø¯Ù…: <code>{ur}</code>",
        "â„¹ï¸ <b>Info</b>\nâ€¢ UID: <code>{uid}</code>\nâ€¢ SID: <code>{sid}</code>\nâ€¢ Duration: <code>{dur}s</code>\nâ€¢ Tag: <code>{tag}</code>\nâ€¢ Category: <code>{cat}</code>\nâ€¢ Ratings â†’ admin: <code>{ar}</code> | user: <code>{ur}</code>"
    ).format(uid=uid, sid=sid, dur=dur, tag=tag, cat=cat, ar=rr.get('admin_rating','-'), ur=rr.get('user_rating','-'))
    try: await cb.message.answer(text, parse_mode="HTML")
    except Exception: pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:rateopen:"))
async def cb_rate_open(cb: CallbackQuery):
    psid = cb.data.split(":")[2]
    lang = _L(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_user_rate_choices(psid, lang))
    except Exception:
        pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:rateclose:"))
async def cb_rate_close(cb: CallbackQuery):
    sid = _sid_unpack(cb.data.split(":")[2])
    lang = _L(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_user_actions(lang, sid))
    except Exception:
        pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:urate:"))
async def cb_user_rate(cb: CallbackQuery):
    parts = cb.data.split(":")
    sid = _sid_unpack(":".join(parts[2:-1]))
    stars = int(parts[-1])
    _set_user_rating(sid, stars)
    lang = _L(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_user_actions(lang, sid))
    except Exception:
        pass
    await cb.answer("Thanks!")
    await _notify_admins_t(cb.bot,"live.admin.notify.user_rating","â­ ØªÙ‚ÙŠÙŠÙ… Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ù„Ù„Ø¬Ù„Ø³Ø© {sid}: {stars}â­","â­ User rating for chat {sid}: {stars}â­", sid=sid, stars=stars)

@router.message(StateFilter(LiveChat.active), ~F.text.startswith("/"), ~F.caption.startswith("/"))
async def user_live_message(m: Message, state: FSMContext):
    uid = m.from_user.id; lang = _L(uid)
    if _blocked(uid): return
    sess = _get_session(uid)
    if not sess: return
    if _expired(sess):
        _del_session(uid); await state.clear()
        _inbox_call("resolve", "live", uid, status="expired")
        return await m.answer(_tt(lang,"live.expired.msg","â³ Ø§Ù†ØªÙ‡Øª Ø§Ù„Ø¬Ù„Ø³Ø©. Ø§Ø¨Ø¯Ø£ ÙˆØ§Ø­Ø¯Ø© Ø¬Ø¯ÙŠØ¯Ø© Ù…Ù† (Ø§Ù„Ø¯Ø¹Ù…).","â³ Session expired. Start a new one from Support."))
    _touch(uid)

    if sess.get("status") == "waiting":
        q = list(sess.get("queue") or []); q.append(m.message_id); sess["queue"] = q; _put_session(uid, sess)
        # Ø­Ø¯Ù‘Ø« Ø§Ù„Ù…Ø¹Ø§ÙŠÙ†Ø© ÙÙŠ ØµÙ†Ø¯ÙˆÙ‚ Ø§Ù„ÙˆØ§Ø±Ø¯ (Ø¢Ø®Ø± Ø±Ø³Ø§Ù„Ø©)
        preview = (m.caption or m.text or f"({m.content_type})")[:200]
        _inbox_call("update", "live", uid, preview)
        return await m.answer(
            _tt(lang,"live.queue.received","âœ… ØªÙ… Ø§Ø³ØªÙ„Ø§Ù… Ø±Ø³Ø§Ù„ØªÙƒ. Ø³Ù†Ø±Ø¯ Ø¨Ø¹Ø¯ Ø§Ù†Ø¶Ù…Ø§Ù… Ø§Ù„Ø¯Ø¹Ù….\n(Ù„Ø§ Ø²Ù„Øª ÙÙŠ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø±)","âœ… We got your message. We'll reply once support joins.\n(You are still in the queue)"),
            reply_markup=_kb_user_wait(lang)
        )

    # active â†’ relay
    relays = _load(RELAYS_FILE); delivered = False
    for tgt in _targets():
        try:
            cp = await m.bot.copy_message(
                chat_id=tgt, from_chat_id=m.chat.id, message_id=m.message_id,
                reply_markup=_kb_admin_controls(uid, _L(tgt), sess["sid"])
            )
            relays[f"{tgt}:{cp.message_id}"] = uid
            delivered = True
        except Exception as e1:
            try:
                fwd = await m.bot.forward_message(
                    chat_id=tgt, from_chat_id=m.chat.id, message_id=m.message_id
                )
                relays[f"{tgt}:{fwd.message_id}"] = uid
                delivered = True
            except Exception as e2:
                if m.text:
                    msg = await m.bot.send_message(tgt, f"ðŸ‘¤ #{uid}:\n{m.text}")
                    relays[f"{tgt}:{msg.message_id}"] = uid
                    delivered = True
                else:
                    log.warning("copy/forward user->%s failed: %s | %s", tgt, e1, e2)
    if delivered:
        _save(RELAYS_FILE, relays)
        await m.answer(_tt(lang,"live.tip.end","Ù„Ù„Ø¥Ù†Ù‡Ø§Ø¡ Ø£Ùˆ Ø§Ù„ØªÙ‚ÙŠÙŠÙ… Ø§Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø£Ø²Ø±Ø§Ø± Ø£Ø¯Ù†Ø§Ù‡.","Use the buttons below to end or rate."),
                       reply_markup=_kb_user_actions(lang, sess["sid"]))

# ===== Admin messages â€” Reply always allowed; non-reply only in FSM state =====

# 1) Ø§Ù„Ø¥Ø¯Ù…Ù† ÙˆÙ‡Ùˆ ÙŠØ±Ø¯Ù‘ Reply Ø¹Ù„Ù‰ Ø±Ø³Ø§Ù„Ø© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… (ÙŠØ³Ù…Ø­ Ø¯Ø§Ø¦Ù…Ù‹Ø§)
@router.message(F.reply_to_message)
async def admin_reply_in_private(m: Message):
    if not _is_admin(m.from_user.id):
        return
    if m.text and m.text.startswith('/'):
        return
    delivered = await _relay_admin_reply(m)
    if delivered:
        return

# 2) Ø§Ù„Ø¥Ø¯Ù…Ù† ÙˆÙ‡Ùˆ ÙÙŠ ÙˆØ¶Ø¹ LiveChat.admin â†’ Ø£ÙŠ Ø±Ø³Ø§Ù„Ø© ØªØ±Ø³Ù„ Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø§Ù„Ù†Ø´Ø·
@router.message(StateFilter(LiveChat.admin))
async def admin_message_in_private(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    if m.text in {"/exit_admin", "/exit", "/leave"}:
        await state.clear()
        return await m.reply("ØªÙ… Ø§Ù„Ø®Ø±ÙˆØ¬ Ù…Ù† ÙˆØ¶Ø¹ Ø§Ù„Ø±Ø¯Ù‘ âœ…")
    if m.text == "/live_on":
        _set_admin_online(m.from_user.id, True); return await m.reply("Live chat: you are ONLINE âœ…")
    if m.text == "/live_off":
        _set_admin_online(m.from_user.id, False); return await m.reply("Live chat: you are OFFLINE â›”")
    if m.reply_to_message:  # Ù„Ùˆ Ø±Ø¯ØŒ Ø³ÙŠØ¹Ø§Ù„Ø¬Ù‡ Ø§Ù„Ù‡Ø§Ù†Ø¯Ù„Ø± Ø§Ù„Ø£ÙˆÙ„ ØºØ§Ù„Ø¨Ù‹Ø§
        return
    delivered = await _send_to_active(m)
    if not delivered:
        await m.reply("âš ï¸ Ù„Ø§ ØªÙˆØ¬Ø¯ Ø¬Ù„Ø³Ø© Ù†Ø´Ø·Ø© Ù…Ø±ØªØ¨Ø·Ø© Ø¨Ùƒ.\nØ§Ø³ØªØ®Ø¯Ù… Ø²Ø± âœ… Ø§Ù†Ø¶Ù… Ù„Ù„Ø¯Ø±Ø¯Ø´Ø©ØŒ Ø£Ùˆ Ø§Ø®Ø±Ø¬ Ø¨Ù€ /exit_admin.")

# --- Helpers to deliver admin messages ---
async def _relay_admin_reply(m: Message) -> bool:
    _touch_admin(m.from_user.id)
    rel = _load(RELAYS_FILE)
    ref = m.reply_to_message.message_id if m.reply_to_message else None
    key = f"{m.chat.id}:{ref}" if ref is not None else None
    uid = rel.get(key) if key else None
    if not uid:
        return False

    s = _get_session(int(uid))
    if not s or s.get("status") != "active":
        try:
            await m.reply("âš ï¸ Session not active.")
        except Exception:
            pass
        return False

    try:
        await m.bot.copy_message(
            chat_id=int(uid),
            from_chat_id=m.chat.id,
            message_id=m.message_id,
            reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
        )
        return True
    except Exception as e:
        log.warning("copy admin->user failed: %s", e)
        try:
            if m.text:
                await m.bot.send_message(
                    int(uid),
                    m.text,
                    reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
                )
                return True
        except Exception as e2:
            log.warning("send admin->user failed: %s", e2)
        return False

async def _send_to_active(m: Message) -> bool:
    _touch_admin(m.from_user.id)
    aid = m.from_user.id
    uid = _get_admin_active(aid)
    if not uid:
        try:
            await m.reply("âš ï¸ Ù„Ø§ ØªÙˆØ¬Ø¯ Ø¬Ù„Ø³Ø© Ù…ÙØ¹Ù‘Ù„Ø© Ù„Ùƒ Ø§Ù„Ø¢Ù†.\n"
                          "âžœ Ø¥Ù…Ù‘Ø§ Ø§Ø¶ØºØ· Â«âœ… Ø§Ù†Ø¶Ù… Ù„Ù„Ø¯Ø±Ø¯Ø´Ø©Â»ØŒ Ø£Ùˆ **Ø±Ø¯** (Reply) Ø¹Ù„Ù‰ Ø¥Ø­Ø¯Ù‰ Ø±Ø³Ø§Ø¦Ù„ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù….")
        except Exception:
            pass
        return False

    s = _get_session(int(uid))
    if not s or s.get("status") != "active":
        try:
            await m.reply("âš ï¸ Ø§Ù„Ø¬Ù„Ø³Ø© Ù„ÙŠØ³Øª Ù†Ø´Ø·Ø©.\n"
                          "Ø¥Ù†ØªÙ‡Øª/Ø£ÙØºÙ„Ù‚Øª. Ø§Ø·Ù„Ø¨ Ù…Ù† Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… ÙØªØ­ Ø·Ù„Ø¨ Ø¬Ø¯ÙŠØ¯ Ø£Ùˆ Ø§Ù†Ø¶Ù… Ø«Ø§Ù†ÙŠØ©.")
        except Exception:
            pass
        return False

    # Ø­Ø§ÙˆÙ„ Ø§Ù„Ù†Ø³Ø® Ø£ÙˆÙ„Ø§Ù‹ØŒ Ø«Ù… ÙÙˆÙ„Ø¨Ø§Ùƒ Ù„Ù†Øµ ÙÙ‚Ø·
    try:
        await m.bot.copy_message(
            chat_id=int(uid),
            from_chat_id=m.chat.id,
            message_id=m.message_id,
            reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
        )
        return True
    except Exception as e:
        log.warning("copy admin(no-reply)->user failed: %s", e)
        try:
            if m.text:
                await m.bot.send_message(
                    int(uid),
                    m.text,
                    reply_markup=_kb_user_actions(_L(int(uid)), s["sid"])
                )
                return True
            else:
                await m.reply("âš ï¸ Ù„Ù… Ø£Ø³ØªØ·Ø¹ Ø¥Ø¹Ø§Ø¯Ø© ØªÙˆØ¬ÙŠÙ‡ Ù‡Ø°Ø§ Ø§Ù„Ù†ÙˆØ¹ Ù…Ù† Ø§Ù„Ø±Ø³Ø§Ø¦Ù„.\n"
                              "Ø¬Ø±Ù‘Ø¨ Ø¥Ø±Ø³Ø§Ù„ Ù†ØµØŒ Ø£Ùˆ **Ø±Ø¯** Ø¹Ù„Ù‰ Ø±Ø³Ø§Ù„Ø© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ù„Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„ØªÙˆØ¬ÙŠÙ‡ Ø§Ù„ØªÙ„Ù‚Ø§Ø¦ÙŠ.")
        except Exception as e2:
            log.warning("send admin(no-reply)->user failed: %s", e2)
        return False

# ===== Ø£ÙˆØ§Ù…Ø± Ø­Ø§Ù„Ø© Ø£ÙˆÙ†Ù„Ø§ÙŠÙ† Ø§Ù„Ø¥Ø¯Ù…Ù† =====
@router.message(Command("live_on"))
async def cmd_live_on(m: Message):
    if not _is_admin(m.from_user.id):
        return
    _set_admin_online(m.from_user.id, True)
    await m.reply("Live chat: you are ONLINE âœ…")

@router.message(Command("live_off"))
async def cmd_live_off(m: Message):
    if not _is_admin(m.from_user.id):
        return
    _set_admin_online(m.from_user.id, False)
    await m.reply("Live chat: you are OFFLINE â›”")

