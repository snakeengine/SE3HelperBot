from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/promo_free_sevip.py

import os, re, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import StateFilter
from aiogram.filters import Command
from utils.promo_sub_store import list_requests

from lang import get_user_lang
from utils.promo_sub_store import update_request, find_request, load_rules, PROMO_MIN_VIEWS
from handlers.promo_flow_extras import admin_menu_kb  # (Ù†ÙØ³ Ø§Ù„Ø£Ø²Ø±Ø§Ø±)

router = Router(name="promo_free_sevip")


ADMIN_IDS = get_admin_ids()
def _is_admin(i: int) -> bool: return i in set(ADMIN_IDS or [])

# ÙƒÙ… Ø¯Ù‚ÙŠÙ‚Ø© Ù†Ø³Ù…Ø Ø¨Ø¹Ø¯Ù‡Ø§ Ø¨Ø¥Ø¹Ø§Ø¯Ø© ØªÙ†Ø¨ÙŠÙ‡ Ø§Ù„Ø£Ø¯Ù…Ù† ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§ Ø¥Ø°Ø§ Ø¸Ù„Ù‘Øª Ø§Ù„ØØ§Ù„Ø© awaiting_admin
RENOTIFY_MIN = int(os.getenv("PROMO_RENOTIFY_MIN", "10"))

def _admin_ids_loaded() -> bool:
    return bool(ADMIN_IDS)

async def _notify_admins_once(bot, uid: int, note: str, force: bool = False):
    """ÙŠØ±Ø³Ù„ Ø¥Ø´Ø¹Ø§Ø±Ù‹Ø§ Ù„Ù„Ø£Ø¯Ù…Ù† ÙˆÙŠØ¶Ø¹ Ø®ØªÙ… admin_notified_at Ù„ØªÙØ§Ø¯ÙŠ Ø§Ù„ØªÙƒØ±Ø§Ø±."""
    rec = find_request(uid) or {}
    last = int(rec.get("admin_notified_at") or 0)
    if not force:
        # Ù„Ø§ ØªØ¹ÙŠØ¯ Ø§Ù„Ø¥Ø±Ø³Ø§Ù„ Ø¥Ø°Ø§ Ø£ÙØ±Ø³Ù„ Ø®Ù„Ø§Ù„ Ø§Ù„Ø¯Ù‚Ø§Ø¦Ù‚ Ø§Ù„Ù…Ø§Ø¶ÙŠØ©
        if _now() - last < RENOTIFY_MIN * 60:
            return
    # ÙØ¹Ù„ÙŠÙ‹Ø§ Ø£Ø±Ø³Ù„
    await _notify_admins(bot, uid, note=note)
    update_request(uid, admin_notified_at=_now())

# ØªÙ‚Ø¨Ù‘Ù„ uid Ø£Ùˆ ÙƒÙˆØ¯ Ù„ØºØ©
def _L(x, ar: str, en: str) -> str:
    lang = get_user_lang(x) if isinstance(x, int) else (x or "en")
    return ar if str(lang).startswith("ar") else en

PLATFORMS = (
    ("yt","YouTube"), ("tt","TikTok"), ("ig","Instagram"),
    ("fb","Facebook"), ("x","X"), ("rd","Reddit"), ("tg","Telegram")
)

class PromoState(StatesGroup):
    waiting_url  = State()
    waiting_shot = State()
    waiting_code = State()

_PAT = {
    "yt": r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/))",
    "tt": r"(?:tiktok\.com/(?:@[^/]+/video/\d+|t/|video/\d+))",
    "ig": r"(?:instagram\.com/(?:p|reel|tv)/)",
    "fb": r"(?:facebook\.com/(?:reel|watch|posts)/)",
    "x":  r"(?:(?:x|twitter)\.com/[^/]+/status/\d+)",
    "rd": r"(?:reddit\.com/r/[^/]+/comments/[^/]+/[^/]+/\w+)",
    "tg": r"(?:t\.me/[^/]+/\d+)",
}
def _valid(platform: str, url: str) -> bool:
    url = (url or "").strip()
    if not re.match(r"^https?://", url): return False
    pat = _PAT.get(platform)
    return bool(pat and re.search(pat, url, re.I))

def _now() -> int: return int(time.time())
def _is_locked(rec: dict) -> bool:
    return bool(rec.get("locked")) or str(rec.get("status")) in {"ready_for_activation", "activated"}

async def _notify_admins(bot, uid: int, note: str):
    rec = find_request(uid) or {}
    for aid in ADMIN_IDS:
        try:
            txt = (
                f"ðŸ”Ž {note}\n"
                f"user_id={uid}\n"
                f"username=@{rec.get('username') or '-'}\n"
                f"status={rec.get('status')}\n"
                f"min_views={PROMO_MIN_VIEWS:,}\n"
            )
            await bot.send_message(aid, txt, reply_markup=admin_menu_kb(uid))
        except Exception:
            pass

def _menu_kb(lang: str):
    kb = InlineKeyboardBuilder()
    for pair in ((PLATFORMS[0],PLATFORMS[1]), (PLATFORMS[2],PLATFORMS[3]), (PLATFORMS[4],PLATFORMS[5])):
        kb.row(*(InlineKeyboardButton(text=lbl, callback_data=f"promo:plat:{code}") for code,lbl in pair))
    kb.row(InlineKeyboardButton(text="Telegram", callback_data="promo:plat:tg"))
    return kb.as_markup()

def _send_terms(lang: str):
    ar = (lang or "en").startswith("ar")
    title = "ðŸŽŸï¸ Ø§Ù„ØØµÙˆÙ„ Ø¹Ù„Ù‰ Ø§Ø´ØªØ±Ø§Ùƒ Ù…Ø¬Ø§Ù†Ù‹Ø§" if ar else "ðŸŽŸï¸ Get SEVIP for Free"
    terms_title = "ðŸ“œ Ø´Ø±ÙˆØ· Ø§Ù„Ù…Ø´Ø§Ø±ÙƒØ©" if ar else "ðŸ“œ Participation Terms"
    views_rule = (f"Minimum views: {PROMO_MIN_VIEWS:,} real views."
                  if not ar else f"ØØ¯ Ø£Ø¯Ù†Ù‰ Ù„Ù„Ù…Ø´Ø§Ù‡Ø¯Ø§Øª: {PROMO_MIN_VIEWS:,} Ù…Ø´Ø§Ù‡Ø¯Ø© ØÙ‚ÙŠÙ‚ÙŠØ©.")
    after_approve = ("After approval, choose a platform, post publicly, then send the URL and screenshot."
                     if not ar else "Ø¨Ø¹Ø¯ Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø© Ø§Ø®ØªØ± Ù…Ù†ØµØ© ÙˆØ§Ù†Ø´Ø± Ø¹Ù„Ù†Ù‹Ø§ Ø«Ù… Ø£Ø±Ø³Ù„ Ø§Ù„Ø±Ø§Ø¨Ø· ÙˆØ§Ù„Ù„Ù‚Ø·Ø©.")
    rules = load_rules(lang)

    body = f"{title}\n\n{terms_title}\nâ€¢ {views_rule}\nâ€¢ {after_approve}\n\n{rules}"
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=("âœ… Ø£ÙˆØ§ÙÙ‚" if ar else "âœ… I Agree"),   callback_data="promo:terms:accept"),
        InlineKeyboardButton(text=("âŒ Ù„Ø§ Ø£ÙˆØ§ÙÙ‚" if ar else "âŒ Decline"), callback_data="promo:terms:decline"),
    )
    kb.row(InlineKeyboardButton(text=("â¬…ï¸ Ø±Ø¬ÙˆØ¹" if ar else "â¬…ï¸ Back"), callback_data="back_to_menu"))
    return body, kb

# 12 Ø³Ø§Ø¹Ø© (ÙŠÙ…ÙƒÙ† ØªØºÙŠÙŠØ±Ù‡Ø§ Ù…Ù† Ù…ØªØºÙŠØ± Ø¨ÙŠØ¦ÙŠ)
REAPPLY_COOLDOWN_SECS = int(os.getenv("PROMO_REAPPLY_COOLDOWN", "43200"))

def _fmt_eta(seconds: int, lang: str) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if (lang or "en").startswith("ar"):
        parts = []
        if h: parts.append(f"{h} ساعة")
        if m: parts.append(f"{m} Ø¯Ù‚ÙŠÙ‚Ø©")
        if not parts: parts = ["Ø£Ù‚Ù„ Ù…Ù† Ø¯Ù‚ÙŠÙ‚Ø©"]
        return " Ùˆ ".join(parts)
    else:
        parts = []
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        if not parts: parts = ["<1m"]
        return " ".join(parts)

def _cooldown_left(rec: dict) -> int:
    """Ø«ÙˆØ§Ù†Ù Ù…ØªØ¨Ù‚ÙŠØ© Ù‚Ø¨Ù„ Ø§Ù„Ø³Ù…Ø§Ø Ø¨Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„ØªÙ‚Ø¯ÙŠÙ… Ø¨Ø¹Ø¯ Ø§Ù„Ø±ÙØ¶."""
    if (rec.get("status") or "") != "rejected":
        return 0
    t0 = int(rec.get("rejected_at") or rec.get("updated_at") or 0)
    left = REAPPLY_COOLDOWN_SECS - max(0, _now() - t0)
    return max(0, left)

@router.message(Command("whoadmins"))
async def whoadmins(msg: Message):
    ids = ", ".join(map(str, ADMIN_IDS)) or "(empty)"
    await msg.reply(f"ADMIN_IDS = get_admin_ids()")

@router.message(Command("promo_list"))
async def promo_list(msg: Message):
    if msg.from_user.id not in set(ADMIN_IDS or []): return
    # Ø§Ù„Ø§Ø³ØªØ¹Ù…Ø§Ù„: /promo_list [status] [limit]
    parts = (msg.text or "").split()
    status = parts[1] if len(parts) > 1 and parts[1] not in {"all","*"} else None
    limit  = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30

    rows = list_requests(status=status, limit=limit, order="-updated_at")
    if not rows:
        return await msg.reply("Ù„Ø§ ØªÙˆØ¬Ø¯ Ù†ØªØ§Ø¦Ø¬.")

    # Ù†Ø·Ø¨Ø¹ Ù…Ø®ØªØµØ±Ø§Øª Ù…Ù†Ø¸Ù…Ø©
    lines = []
    for r in rows:
        lines.append(
            f"â€¢ uid={r.get('uid')} | st={r.get('status')} | plat={r.get('platform','-')} | "
            f"views_min={r.get('min_views','-')} | upd={r.get('updated_at')}"
        )
    text = "ðŸ“‹ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø·Ù„Ø¨Ø§Øª" + (f" (status={status})" if status else "") + f" â€” {len(rows)}\n\n" + "\n".join(lines)
    await msg.reply(text)


@router.callback_query(F.data == "promo:open")
async def promo_open(cb: CallbackQuery):
    uid  = cb.from_user.id
    lang = get_user_lang(uid) or "en"

    rec = find_request(uid) or {}
    if not rec:
        update_request(uid, status="none", lang=lang, created_at=_now())
        rec = find_request(uid) or {}

        # Ù…Ù†Ø¹ Ø§Ù„Ù…ØØ¸ÙˆØ±/Ø§Ù„Ù…Ø¬Ù…Ù‘Ø¯
    if str(rec.get("status")) == "banned":
         return await cb.answer(_L(lang, "âŒ ØØ³Ø§Ø¨Ùƒ Ù…ØØ¸ÙˆØ± Ù…Ù† Ø§Ù„Ù…Ø´Ø§Ø±ÙƒØ©.", "âŒ You are banned from participating."), show_alert=True)
    if rec.get("frozen"):
         return await cb.answer(_L(lang, "ðŸ§Š ØØ³Ø§Ø¨Ùƒ Ù…Ø¬Ù…Ù‘Ø¯ Ù…Ø¤Ù‚ØªÙ‹Ø§.", "ðŸ§Š Your account is temporarily frozen."), show_alert=True)


    # Ø§Ù„Ø´Ø±ÙˆØ· Ø£ÙˆÙ„Ù‹Ø§
    if not rec.get("accepted_terms"):
        body, kb = _send_terms(lang)
        await cb.message.answer(body, reply_markup=kb.as_markup(), disable_web_page_preview=True)
        return await cb.answer()

    st = str(rec.get("status") or "none")

    # Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„ØªÙ‚Ø¯ÙŠÙ… (Ù…Ø¹ ÙƒÙˆÙ„Ø¯Ø§ÙˆÙ† 12 Ø³Ø§Ø¹Ø© Ø¨Ø¹Ø¯ Ø§Ù„Ø±ÙØ¶)
    if st in {"none", "declined", "rejected"}:
        if st == "rejected":
            left = _cooldown_left(rec)
            if left > 0:
                eta = _fmt_eta(left, lang)
                await cb.message.answer(_L(lang,
                    f"â³ Ù„Ø§ ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ù„ØªÙ‚Ø¯ÙŠÙ… Ø§Ù„Ø¢Ù†. Ø¬Ø±Ù‘Ø¨ Ø¨Ø¹Ø¯ {eta}.",
                    f"â³ You canâ€™t re-apply yet. Try again in {eta}."
                ))
                return await cb.answer()

        update_request(uid, status="awaiting_admin", lang=lang, requested_at=_now())
        await _notify_admins(cb.bot, uid, note="Promo approval request")
        await cb.message.answer(_L(lang,
                                   "â³ ØªÙ… Ø¥Ø±Ø³Ø§Ù„ Ø·Ù„Ø¨Ùƒ Ù„Ù„Ù…Ø±Ø§Ø¬Ø¹Ø©. Ø³Ù†Ø¨Ù„ØºÙƒ Ø¹Ù†Ø¯ Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø©.",
                                   "â³ Your request was sent for review. We'll notify you when approved."))
        return await cb.answer()

    if st == "awaiting_admin":
        await _notify_admins_once(cb.bot, uid, note="Promo approval request (auto-resend)")
        await cb.message.answer(_L(lang,
                                   "â³ ØªÙ… Ø¥Ø±Ø³Ø§Ù„ Ø·Ù„Ø¨Ùƒ Ù„Ù„Ù…Ø±Ø§Ø¬Ø¹Ø©. Ø³Ù†Ø¨Ù„ØºÙƒ Ø¹Ù†Ø¯ Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø©.",
                                   "â³ Your request was sent for review. We'll notify you when approved."))
        return await cb.answer()

    if st == "approved":
        body = (
            _L(lang, "âœ… ØªÙ…Øª Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø© Ù…Ù† Ø§Ù„Ø¥Ø¯Ø§Ø±Ø©. Ø§Ø®ØªØ± Ø§Ù„Ù…Ù†ØµØ© Ù„Ù†Ø´Ø± Ø§Ù„Ù…ØØªÙˆÙ‰.",
                     "âœ… Approved by admins. Choose a platform to post.")
            + "\n"
            + _L(lang, f"ØØ¯ Ø£Ø¯Ù†Ù‰ Ù„Ù„Ù…Ø´Ø§Ù‡Ø¯Ø§Øª: {PROMO_MIN_VIEWS:,} Ù…Ø´Ø§Ù‡Ø¯Ø© ØÙ‚ÙŠÙ‚ÙŠØ©.",
                       f"Minimum views: {PROMO_MIN_VIEWS:,} real views.")
            + "\n\n"
            + load_rules(lang)
            + "\n\n"
            + _L(lang, "Ø§Ø®ØªØ± Ø§Ù„Ù…Ù†ØµØ©:", "Choose a platform:")
        )
        await cb.message.answer(body, reply_markup=_menu_kb(lang), disable_web_page_preview=True)
        return await cb.answer()

    if st == "banned":
        return await cb.answer(_L(lang, "âŒ Ø¹Ø°Ø±Ù‹Ø§ØŒ ØªÙ… Ø±ÙØ¶ Ø·Ù„Ø¨Ùƒ.", "âŒ Sorry, your request was rejected."), show_alert=True)

    # fallback
    body, kb = _send_terms(lang)
    await cb.message.answer(body, reply_markup=kb.as_markup(), disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "promo:terms:decline")
async def terms_decline(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    update_request(cb.from_user.id, status="declined", accepted_terms=False, lang=lang, updated_at=_now())
    await cb.answer()
    await cb.message.answer(_L(lang, "âŒ ØªÙ… Ø¥Ù„ØºØ§Ø¡ Ø§Ù„Ø·Ù„Ø¨.", "âŒ Request cancelled."))

@router.message(Command("whoadmins"))
async def whoadmins(msg: Message):
    if not _is_admin(msg.from_user.id): return
    await msg.reply("ADMIN_IDS = get_admin_ids()")

@router.callback_query(F.data == "promo:terms:accept")
async def terms_accept(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    rec = find_request(cb.from_user.id) or {}

    # ÙƒÙˆÙ„Ø¯Ø§ÙˆÙ† Ø¨Ø¹Ø¯ Ø§Ù„Ø±ÙØ¶ (ÙƒÙ…Ø§ Ø¹Ù†Ø¯Ùƒ)
    if (rec.get("status") or "") == "rejected":
        left = _cooldown_left(rec)
        if left > 0:
            eta = _fmt_eta(left, lang)
            await cb.answer()
            return await cb.message.answer(_L(lang,
                f"â³ Ù„Ø§ ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ù„ØªÙ‚Ø¯ÙŠÙ… Ø§Ù„Ø¢Ù†. Ø¬Ø±Ù‘Ø¨ Ø¨Ø¹Ø¯ {eta}.",
                f"â³ You canâ€™t re-apply yet. Try again in {eta}."
            ))

    update_request(
        cb.from_user.id,
        accepted_terms=True,
        status="awaiting_admin",
        lang=lang,
        username=cb.from_user.username,
        first_name=cb.from_user.first_name,
        requested_at=_now(),
        min_views=PROMO_MIN_VIEWS,
    )

    # Ø£Ø±Ø³Ù„ Ù„Ù„Ø¥Ø¯Ø§Ø±Ø© ÙˆØ³Ø¬Ù‘Ù„ Ø§Ù„Ø®ØªÙ…
    await _notify_admins_once(cb.bot, cb.from_user.id, note="Promo approval request", force=True)

    await cb.answer()
    await cb.message.answer(_L(lang,
        "â³ ØªÙ… Ø¥Ø±Ø³Ø§Ù„ Ø·Ù„Ø¨Ùƒ Ù„Ù„Ù…Ø±Ø§Ø¬Ø¹Ø©. Ø³Ù†Ø¨Ù„ØºÙƒ Ø¹Ù†Ø¯ Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø©.",
        "â³ Your request was sent for review. We'll notify you when approved."
    ))


@router.callback_query(F.data.regexp(r"^admin:promo:(approve|reject):(\d+)$"))
async def admin_review(cb: CallbackQuery):
    if cb.from_user.id not in set(ADMIN_IDS or []):
        return await cb.answer("Admins only", show_alert=True)

    action, uid_s = cb.data.split(":")[2], cb.data.split(":")[3]
    try:
        uid = int(uid_s)
    except ValueError:
        return await cb.answer("bad uid", show_alert=True)

    lang = get_user_lang(uid) or "ar"
    rec  = find_request(uid) or {}
    status = str(rec.get("status") or "none")

    if action == "reject":
        update_request(uid, status="rejected", rejected_at=_now())
        try: await cb.bot.send_message(uid, _L(lang, "âŒ ØªÙ… Ø±ÙØ¶ Ø§Ù„Ø·Ù„Ø¨.", "âŒ Rejected."))
        except Exception: pass
        await cb.answer("rejected")
        try: await cb.message.edit_reply_markup(None)
        except Exception: pass
        return

    # approve
    if status in {"awaiting_admin", "declined", "none", "rejected"}:
        update_request(uid, status="approved", approved_at=_now())
        try:
            await cb.bot.send_message(uid, _L(lang, "âœ… ØªÙ…Øª Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø©. Ø§Ø®ØªØ± Ø§Ù„Ù…Ù†ØµØ©:", "âœ… Approved. Choose a platform:"),
                                      reply_markup=_menu_kb(lang))
        except Exception:
            pass
        await cb.answer("approved (stage 1)")
        try: await cb.message.edit_reply_markup(None)
        except Exception: pass
        return

    if status in {"in_review"}:
        update_request(uid, status="final_approved", final_approved_at=_now())
        try:
            msg1 = _L(lang,
                      "âœ… ØªÙ…Øª Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø© Ø§Ù„Ù†Ù‡Ø§Ø¦ÙŠØ© Ø¹Ù„Ù‰ Ø§Ù„ØªÙ‚Ø¯ÙŠÙ….\nØ³Ù†ÙØ¹Ù‘Ù„ Ø§Ø´ØªØ±Ø§ÙƒÙƒ Ø¨Ø¹Ø¯ Ø§Ø³ØªÙ„Ø§Ù… Ø§Ù„ØªÙØ§ØµÙŠÙ„.",
                      "âœ… Final approval granted.\nWeâ€™ll activate your subscription after we get your details.")
            await cb.bot.send_message(uid, msg1)
            # Ø³Ù†Ø¨Ø¯Ø£ Ø¬Ù…Ø¹ Ø§Ù„ØªÙØ§ØµÙŠÙ„ ÙÙŠ Ù…Ù„Ù promo_flow_extras Ø¹Ø¨Ø± start_user_details_flow Ø¹Ù†Ø¯ Ø£ÙˆÙ„ ØªÙØ¹ÙŠÙ„
            from handlers.promo_flow_extras import start_user_details_flow
            await start_user_details_flow(cb.bot, uid)
        except Exception:
            pass
        await cb.answer("approved (final)")
        try: await cb.message.edit_reply_markup(None)
        except Exception: pass
        return

    await cb.answer(f"no-op (status={status})")

@router.callback_query(F.data.regexp(r"^promo:plat:(yt|tt|ig|fb|x|rd|tg)$"))
async def choose_platform(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    rec = find_request(uid) or {}
    if _is_locked(rec):
        return await cb.answer(_L(uid, "Ø§Ù„Ø·Ù„Ø¨ Ù…ÙÙ‚ÙÙ„. Ø³Ù†Ø¨Ù„ØºÙƒ Ø¨Ø§Ù„ØªÙØ¹ÙŠÙ„.", "Request is locked. We'll notify you soon."), show_alert=True)

    if rec.get("status") != "approved":
        return await cb.answer(_L(uid, "âš ï¸ ÙŠØ¬Ø¨ Ù…ÙˆØ§ÙÙ‚Ø© Ø§Ù„Ø¥Ø¯Ø§Ø±Ø© Ø£ÙˆÙ„Ù‹Ø§.", "âš ï¸ Admin approval first."), show_alert=True)

    if rec.get("step") in {"shot","code"}:
        return await cb.answer(_L(uid, "Ù„Ù‚Ø¯ Ø§Ø³ØªÙ„Ù…Ù†Ø§ Ø§Ù„Ù…Ù†ØµÙ‘Ø© Ø¨Ø§Ù„ÙØ¹Ù„.", "We have already received your platform."))

    plat = cb.data.split(":")[-1]
    update_request(uid, platform=plat, step="url")
    await state.set_state(PromoState.waiting_url)

    try: await cb.message.edit_reply_markup(None)
    except Exception: pass

    await cb.message.answer(_L(uid, "ðŸ“Ž Ø£Ø±Ø³Ù„ Ø±Ø§Ø¨Ø· Ø§Ù„Ù…Ù†Ø´ÙˆØ±/Ø§Ù„ÙÙŠØ¯ÙŠÙˆ Ø§Ù„Ø¹Ø§Ù…:", "ðŸ“Ž Send the public URL:"))
    await cb.answer()

@router.message(StateFilter(PromoState.waiting_url))
async def got_url(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    rec = find_request(uid) or {}
    if _is_locked(rec) or rec.get("status") != "approved":
        await state.clear(); return

    if rec.get("step") not in {None, "url"}:
        return await msg.reply(_L(uid, "Ø§Ø³ØªÙ„Ù…Ù†Ø§ Ø§Ù„Ø±Ø§Ø¨Ø· Ø¨Ø§Ù„ÙØ¹Ù„.", "We already got the link."))

    url = (msg.text or "").strip()
    if not _valid(rec.get("platform",""), url):
        return await msg.reply(_L(uid, "Ø§Ù„Ø±Ø§Ø¨Ø· ØºÙŠØ± ØµØ§Ù„Ø Ù„Ù‡Ø°Ù‡ Ø§Ù„Ù…Ù†ØµØ©.", "Invalid link for this platform."))

    update_request(uid, post_url=url, step="shot")
    await state.set_state(PromoState.waiting_shot)
    await msg.reply(_L(uid, "ðŸ–¼ï¸ Ø£Ø±Ø³Ù„ Ù„Ù‚Ø·Ø© Ø´Ø§Ø´Ø© ØªÙØ¸Ù‡Ø± Ø¹Ø¯Ø¯ Ø§Ù„Ù…Ø´Ø§Ù‡Ø¯Ø§Øª ÙˆØ§Ù„ØªØ§Ø±ÙŠØ®.", "ðŸ–¼ï¸ Send a screenshot with views & date."))

@router.message(StateFilter(PromoState.waiting_shot), F.photo)
async def got_shot(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    rec = find_request(uid) or {}
    if _is_locked(rec) or rec.get("status") != "approved":
        await state.clear(); return

    if rec.get("step") != "shot":
        return await msg.reply(_L(uid, "Ù„Ø¯ÙŠÙ†Ø§ Ø§Ù„Ù„Ù‚Ø·Ø© Ø¨Ø§Ù„ÙØ¹Ù„.", "Screenshot already received."))

    file_id = msg.photo[-1].file_id
    update_request(uid, screenshot_id=file_id, step="code")
    await state.set_state(PromoState.waiting_code)
    await msg.reply(_L(uid, "ðŸ”‘ Ø£Ø¯Ø®Ù„ ÙƒÙˆØ¯ Ø§Ù„Ù…ØªØ§Ø¨Ø¹Ø© (Ø§Ø®ØªÙŠØ§Ø±ÙŠ) Ø£Ùˆ Ø£Ø±Ø³Ù„ - Ù„ØªØ®Ø·ÙŠ.", "ðŸ”‘ Enter tracking code (optional) or send - to skip."))

@router.message(StateFilter(PromoState.waiting_code))
async def got_code(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    rec = find_request(uid) or {}
    if _is_locked(rec) or rec.get("status") != "approved" or rec.get("step") != "code":
        await state.clear(); return

    code = (msg.text or "").strip()
    if code == "-": code = ""

    update_request(uid, tracking_code=code, status="in_review", submitted_at=_now(), step=None, locked=True)
    await state.clear()

    # ØªØ£ÙƒÙŠØ¯ Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø¨Ù„ØºØªÙ‡
    await msg.reply(_L(uid, "âœ… Ø§Ø³ØªÙ„Ù…Ù†Ø§ Ø¨ÙŠØ§Ù†Ø§ØªÙƒ. Ø³Ù†Ø±Ø§Ø¬Ø¹ Ø§Ù„Ù…Ø´Ø§Ù‡Ø¯Ø§Øª ÙˆÙ†Ø¨Ù„ØºÙƒ Ø¨Ø§Ù„Ù†ØªÙŠØ¬Ø©.",
                           "âœ… Received. We'll review views and update you."))

    # Ø¥Ø´Ø¹Ø§Ø± Ø§Ù„Ø¥Ø¯Ø§Ø±Ø© + Ø§Ù„ØµÙˆØ±Ø© Ø¥Ù† ÙˆÙØ¬Ø¯Øª
    try:
        await _notify_admins(msg.bot, uid, note="Promo submission received")
        rec = find_request(uid) or {}
        if rec.get("screenshot_id"):
            for aid in ADMIN_IDS:
                try:
                    await msg.bot.send_photo(aid, rec["screenshot_id"], caption="screenshot")
                except Exception:
                    pass
    except Exception:
        pass


