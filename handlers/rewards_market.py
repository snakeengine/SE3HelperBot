from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/rewards_market.py


import os
import re
import logging
from typing import Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from lang import t, get_user_lang
from utils.rewards_store import (
    get_points, add_points, is_blocked, can_do
)
from .rewards_gate import require_membership  # Ø§Ø­ØªØ±Ø§Ù… Ø§Ù„Ø§Ø´ØªØ±Ø§Ùƒ Ø§Ù„Ø¥Ù„Ø²Ø§Ù…ÙŠ

# Ø·Ù„Ø¨Ø§Øª ÙˆØ¥Ø´Ø¹Ø§Ø±Ø§Øª
from utils.rewards_orders import create_order, get_order, set_status
from utils.rewards_notify import (
    notify_admins_new_vip_order,
    notify_user_vip_submitted,
    notify_user_vip_approved,
    notify_user_vip_rejected,
)

# ÙˆØ¶Ø¹ Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø©
from handlers.live_chat import LiveChat

# ========= Ø§Ù„Ø±Ø§ÙˆØªØ± + ÙÙ„Ø§ØªØ± Ø¹Ø§Ù…Ø© =========
router = Router(name="rewards_market")
# Ø§Ù…Ù†Ø¹ Ø§Ù„ØªÙ†ÙÙŠØ° Ø£Ø«Ù†Ø§Ø¡ Ø¬Ù„Ø³Ø© Ø§Ù„Ø¯Ø±Ø¯Ø´Ø© Ø§Ù„Ø­ÙŠÙ‘Ø©ØŒ ÙˆØ§Ø´ØªØºÙ„ Ø¨Ø§Ù„Ø®Ø§Øµ ÙÙ‚Ø·
router.message.filter(F.chat.type == "private", ~StateFilter(LiveChat.active))
router.callback_query.filter(
    F.message.chat.type == "private",
    ~StateFilter(LiveChat.active),
    F.data.func(lambda s: isinstance(s, str) and (s.startswith("rwd:") or s.startswith("rwdadm:")))
)

log = logging.getLogger(__name__)

# ========= ÙƒØ§Ø¨ØªØ´Ø§ Ø¨Ø´Ø±ÙŠØ© (Ø§Ø®ØªÙŠØ§Ø±ÙŠ) =========
try:
    from .human_check import require_human, ensure_human_then  # type: ignore
except Exception:
    async def require_human(msg_or_cb, level: str = "normal") -> bool:
        return True
    async def ensure_human_then(msg_or_cb, level: str, resume):
        if await require_human(msg_or_cb, level=level):
            await resume(msg_or_cb)
            return True
        return False

# ========= Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø¹Ø§Ù…Ø© =========
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids()

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _fmt_hours_ar(hours: int) -> str:
    if hours < 24:
        return f"{hours} Ø³Ø§Ø¹Ø©"
    days = hours // 24
    if days == 1:
        return "ÙŠÙˆÙ…"
    if days == 2:
        return "ÙŠÙˆÙ…ÙŠÙ†"
    if 3 <= days <= 10:
        return f"{days} Ø£ÙŠØ§Ù…"
    return f"{days} ÙŠÙˆÙ…Ù‹Ø§"

# ========= Ø¹Ù†Ø§ØµØ± Ø§Ù„Ù…ØªØ¬Ø± =========
COST_1H  = int(os.getenv("SHOP_VIP1H_COST",  "100"))
COST_1D  = int(os.getenv("SHOP_VIP1D_COST",  "500"))
COST_3D  = int(os.getenv("SHOP_VIP3D_COST",  "1000"))
COST_30D = int(os.getenv("SHOP_VIP30D_COST", "8000"))  # 30 ÙŠÙˆÙ…
# NEW: ØªÙƒÙ„ÙØ© Ø§Ù„Ø§Ø³ØªØ¨Ø¯Ø§Ù„ (Ø¥Ù† Ø±ØºØ¨Øª Ø¨ØªÙƒÙ„ÙØ© Ø«Ø§Ø¨ØªØ©)
COST_REDEEM = int(os.getenv("SHOP_REDEEM_COST", "0"))
ENABLE_REDEEM = (os.getenv("SHOP_REDEEM_ENABLED", "0").strip().lower() in {"1","true","yes","on"})

SHOP_ITEMS: Dict[str, Dict[str, Any]] = {
    "vip1h":  {"title_ar": f"Ø§Ø´ØªØ±Ø§Ùƒ VIP â€¢ {_fmt_hours_ar(1)}",       "title_en": "VIP â€¢ 1 hour",   "cost": COST_1H,  "kind": "vip_hours", "hours": 1},
    "vip1d":  {"title_ar": f"Ø§Ø´ØªØ±Ø§Ùƒ VIP â€¢ {_fmt_hours_ar(24)}",      "title_en": "VIP â€¢ 1 day",    "cost": COST_1D,  "kind": "vip_hours", "hours": 24},
    "vip3d":  {"title_ar": f"Ø§Ø´ØªØ±Ø§Ùƒ VIP â€¢ {_fmt_hours_ar(72)}",      "title_en": "VIP â€¢ 3 days",   "cost": COST_3D,  "kind": "vip_hours", "hours": 72},
    "vip30d": {"title_ar": f"Ø§Ø´ØªØ±Ø§Ùƒ VIP â€¢ {_fmt_hours_ar(24 * 30)}", "title_en": "VIP â€¢ 30 days",  "cost": COST_30D, "kind": "vip_hours", "hours": 24 * 30},

    # NEW: Ø§Ø³ØªØ¨Ø¯Ø§Ù„ Ù†Ù‚Ø§Ø· Ø¨Ø¯Ù„ Ø§Ø´ØªØ±Ø§Ùƒ â€” ÙŠØ¬Ø¨Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ø¹Ù„Ù‰ ØªØ­Ø¯ÙŠØ¯ Ø§Ù„Ù„Ø¹Ø¨Ø© ÙˆÙŠÙØ¨Ù„Ù‘Øº Ø§Ù„Ø¥Ø¯Ø§Ø±Ø©
    "redeem": {"title_ar": "Ø§Ø³ØªØ¨Ø¯Ø§Ù„ Ù†Ù‚Ø§Ø· Ø¨Ø¯Ù„ Ø§Ø´ØªØ±Ø§Ùƒ", "title_en": "Redeem points (no subscription)",
               "cost": COST_REDEEM, "kind": "redeem"},
}

# ======== ÙˆØ§Ø¬Ù‡Ø© Ø§Ù„Ù…ØªØ¬Ø± ========
def _kb_market(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for item_id, it in SHOP_ITEMS.items():
        # âœ… Ø§Ø®ÙÙ Ø®ÙŠØ§Ø± Ø§Ù„Ø§Ø³ØªØ¨Ø¯Ø§Ù„ Ø¥Ø°Ø§ ØºÙŠØ± Ù…ÙØ¹Ù‘Ù„
        if item_id == "redeem" and not ENABLE_REDEEM:
            continue
        title = it["title_ar"] if lang.startswith("ar") else it["title_en"]
        cost = it["cost"]
        label = f"ðŸ’Ž {title} â€¢ {cost}"
        kb.row(InlineKeyboardButton(text=label, callback_data=f"rwd:mkt:buy:{item_id}"))
    kb.row(InlineKeyboardButton(text=t(lang, "market.back", "â¬…ï¸ Ø±Ø¬ÙˆØ¹"), callback_data="rwd:hub"))
    return kb


async def _show_market(msg_or_cb: Message | CallbackQuery):
    """ÙŠØ¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…ØªØ¬Ø± (Ù…ÙØµÙˆÙ„Ø© Ù„Ø§Ø³ØªØ®Ø¯Ø§Ù…Ù‡Ø§ Ù…Ø¹ ensure_human_then)."""
    uid = msg_or_cb.from_user.id
    lang = _L(uid)

    if await require_membership(msg_or_cb) is False:
        return
    if is_blocked(uid):
        txt = t(lang, "market.locked", "âš ï¸ Ù„Ø§ ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø§Ù„Ù…ØªØ¬Ø± Ø§Ù„Ø¢Ù†. Ø§Ø´ØªØ±Ùƒ Ø¨Ø§Ù„Ù‚Ù†ÙˆØ§Øª Ø§Ù„Ù…Ø·Ù„ÙˆØ¨Ø© Ø£ÙˆÙ„Ù‹Ø§.")
        if isinstance(msg_or_cb, CallbackQuery):
            return await msg_or_cb.answer(txt, show_alert=True)
        return await msg_or_cb.answer(txt)

    title = t(lang, "market.title", "ðŸ›ï¸ Ø§Ù„Ù…ØªØ¬Ø± â€” Ø§Ø®ØªØ± Ø¹Ù†ØµØ±Ù‹Ø§")
    kb = _kb_market(lang).as_markup()
    if isinstance(msg_or_cb, CallbackQuery):
        try:
            await msg_or_cb.message.edit_text(title, reply_markup=kb)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
    else:
        await msg_or_cb.answer(title, reply_markup=kb)

async def open_market(msg_or_cb: Message | CallbackQuery):
    """ÙŠØ¹Ø±Ø¶ Ø§Ù„Ù…ØªØ¬Ø± Ù…Ø¹ ÙƒØ§Ø¨ØªØ´Ø§ Ø®ÙÙŠÙØ© ÙˆØ§Ø³ØªØ¦Ù†Ø§Ù ØªÙ„Ù‚Ø§Ø¦ÙŠ Ø¹Ù†Ø¯ Ø§Ù„Ø­Ø§Ø¬Ø©."""
    await ensure_human_then(msg_or_cb, level="normal", resume=_show_market)

@router.callback_query(F.data == "rwd:hub:market")
async def cb_open_market(cb: CallbackQuery):
    await open_market(cb)

# ======== ØªØ£ÙƒÙŠØ¯ Ù‚Ø¨Ù„ Ø§Ù„Ø®ØµÙ… ========
def _kb_confirm(lang: str, item_id: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=t(lang, "market.confirm", "âœ… ØªØ£ÙƒÙŠØ¯"), callback_data=f"rwd:mkt:cfm:{item_id}"),
        InlineKeyboardButton(text=t(lang, "market.cancel", "âœ–ï¸ Ø¥Ù„ØºØ§Ø¡"), callback_data="rwd:hub:market"),
    )
    return kb

@router.callback_query(F.data.startswith("rwd:mkt:buy:"))
async def cb_buy_item(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    item_id = cb.data.split(":")[-1]
    it = SHOP_ITEMS.get(item_id)
    if not it:
        return await cb.answer(t(lang, "market.unavailable", "Ù‡Ø°Ø§ Ø§Ù„Ø®ÙŠØ§Ø± ØºÙŠØ± Ù…ØªØ§Ø­ Ø­Ø§Ù„ÙŠÙ‹Ø§."), show_alert=True)


    # Ø¹Ø¶ÙˆÙŠØ© + ÙƒØ§Ø¨ØªØ´Ø§ Ø®ÙÙŠÙØ© + ØªØ¨Ø±ÙŠØ¯
    if await require_membership(cb) is False:
        return
    if not await require_human(cb, level="normal"):
        return
    if is_blocked(uid):
        return await cb.answer(t(lang, "market.locked", "âš ï¸ Ù„Ø§ ÙŠÙ…ÙƒÙ†Ùƒ Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø§Ù„Ù…ØªØ¬Ø± Ø§Ù„Ø¢Ù†."), show_alert=True)
    if not can_do(uid, f"mkt_buy_{item_id}", cooldown_sec=3):
        return await cb.answer(t(lang, "common.too_fast", "â³ Ø­Ø§ÙˆÙ„ Ø¨Ø¹Ø¯ Ù‚Ù„ÙŠÙ„."), show_alert=False)

    title = it["title_ar"] if lang.startswith("ar") else it["title_en"]
    cost = it["cost"]
    bal = get_points(uid)

    txt = (
        t(lang, "market.confirm_title", "ØªØ£ÙƒÙŠØ¯ Ø§Ù„Ø´Ø±Ø§Ø¡") + "\n" +
        t(lang, "market.you_will_get", "Ø³ØªØ­ØµÙ„ Ø¹Ù„Ù‰") + f": <b>{title}</b>\n" +
        t(lang, "market.price", "Ø§Ù„Ø³Ø¹Ø±") + f": <b>{cost}</b>\n" +
        t(lang, "market.balance", "Ø±ØµÙŠØ¯Ùƒ") + f": <b>{bal}</b>\n" +
        t(lang, "market.ask_confirm", "Ù‡Ù„ ØªØ±ÙŠØ¯ Ø§Ù„Ù…ØªØ§Ø¨Ø¹Ø©ØŸ")
    )
    try:
        await cb.message.edit_text(txt, reply_markup=_kb_confirm(lang, item_id).as_markup(), disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

# ======== FSM: Ø´Ø±Ø§Ø¡ VIP (Ø¨Ø¹Ø¯ Ø§Ù„Ø®ØµÙ…) ========
class BuyStates(StatesGroup):
    wait_app = State()       # Ù…Ø¹Ø±Ù‘Ù ØªØ·Ø¨ÙŠÙ‚ Ø§Ù„Ø«Ø¹Ø¨Ø§Ù†
    wait_details = State()   # ØªÙØ§ØµÙŠÙ„ Ø¥Ø¶Ø§ÙÙŠØ©

# ======== FSM: Ø§Ø³ØªØ¨Ø¯Ø§Ù„ Ø§Ù„Ù†Ù‚Ø§Ø· (ÙŠØ¬Ø¨Ø± Ù†ÙˆØ¹ Ø§Ù„Ù„Ø¹Ø¨Ø©) ========
class RedeemStates(StatesGroup):
    wait_game = State()      # Ù†ÙˆØ¹/Ø§Ø³Ù… Ø§Ù„Ù„Ø¹Ø¨Ø©
    wait_details = State()   # ØªÙØ§ØµÙŠÙ„ Ø¥Ø¶Ø§ÙÙŠØ©

# --- Ø§ÙƒØªØ´Ø§Ù Ø§Ù„Ø¥Ù„ØºØ§Ø¡ Ø¨Ø´ÙƒÙ„ Ù…Ø±Ù† (AR/EN) ---
_CANCEL_WORDS = {"Ø¥Ù„ØºØ§Ø¡", "Ø§Ù„ØºØ§Ø¡", "cancel", "Ø±Ø¬ÙˆØ¹"}  # Ø§Ù„Ø£Ø³Ø§Ø³ÙŠØ©

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _is_cancel(txt: str, lang: str) -> bool:
    n = _norm(txt)
    try:
        lbl_ar = _norm(t("ar", "market.cancel_refund", "Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªØ±Ø¬Ø§Ø¹"))
        lbl_en = _norm(t("en", "market.cancel_refund", "Cancel & refund"))
    except Exception:
        lbl_ar, lbl_en = _norm("Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªØ±Ø¬Ø§Ø¹"), _norm("Cancel & refund")

    if n in {_norm(w) for w in _CANCEL_WORDS}:
        return True
    if n == lbl_ar or n == lbl_en:
        return True
    if n.startswith("cancel"):  # ÙŠÙ‚Ø¨Ù„ "cancel & refund" ÙˆØºÙŠØ±Ù‡Ø§
        return True
    if "Ø¥Ù„ØºØ§Ø¡" in txt or "Ø§Ù„ØºØ§Ø¡" in txt:
        return True
    return False

def _cancel_rk(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "market.cancel_refund", "Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªØ±Ø¬Ø§Ø¹"))]],
        resize_keyboard=True, one_time_keyboard=True, selective=True
    )

_APP_RE = re.compile(r"^@?[A-Za-z0-9_\.]{3,64}$")

def _normalize_app_id(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    if _APP_RE.match(s):
        return s.lstrip("@")
    return None

# ======== ØªØ£ÙƒÙŠØ¯ Ø§Ù„Ø´Ø±Ø§Ø¡ â†’ Ø®ØµÙ… â†’ Ù…Ø³Ø§Ø± VIP Ø£Ùˆ Redeem ========
@router.callback_query(F.data.startswith("rwd:mkt:cfm:"))
async def cb_confirm_buy(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = _L(uid)
    item_id = cb.data.split(":")[-1]
    it = SHOP_ITEMS.get(item_id)
    if not it:
        return await cb.answer(t(lang, "market.unavailable", "Ù‡Ø°Ø§ Ø§Ù„Ø®ÙŠØ§Ø± ØºÙŠØ± Ù…ØªØ§Ø­ Ø­Ø§Ù„ÙŠÙ‹Ø§."), show_alert=True)

    # Ø¹Ø¶ÙˆÙŠØ© + ÙƒØ§Ø¨ØªØ´Ø§ Ø£Ù‚ÙˆÙ‰ + Ù…Ù†Ø¹ Ø§Ù„Ù†Ù‚Ø± Ø§Ù„Ù…ÙƒØ±Ø±
    if await require_membership(cb) is False:
        return
    if not await require_human(cb, level="high"):
        return
    if not can_do(uid, f"mkt_cfm_{item_id}", cooldown_sec=3):
        return await cb.answer(t(lang, "common.too_fast", "â³ Ø­Ø§ÙˆÙ„ Ø¨Ø¹Ø¯ Ù‚Ù„ÙŠÙ„."), show_alert=False)

    cost = int(it["cost"])
    bal = get_points(uid)
    if bal < cost:
        return await cb.answer(t(lang, "market.no_balance", "Ø±ØµÙŠØ¯Ùƒ Ù„Ø§ ÙŠÙƒÙÙŠ Ù„Ø¥ØªÙ…Ø§Ù… Ø§Ù„Ø´Ø±Ø§Ø¡."), show_alert=True)

    # Ø®ØµÙ… ÙÙˆØ±ÙŠ Ù‚Ø¨Ù„ Ø¬Ù…Ø¹ Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª (ÙŠØ³Ø¬Ù‘Ù„ ÙÙŠ Ø§Ù„Ø³Ø¬Ù„ ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§)
    add_points(uid, -cost, reason=f"market_buy_{item_id}", typ="buy")

    # NEW: ÙØ±Ø¹ Ø§Ù„Ø§Ø³ØªØ¨Ø¯Ø§Ù„ â€” Ø§Ø¬Ù…Ø¹ Ù†ÙˆØ¹ Ø§Ù„Ù„Ø¹Ø¨Ø© Ø«Ù… Ø§Ù„ØªÙØ§ØµÙŠÙ„
    if it.get("kind") == "redeem":
        await state.clear()
        await state.set_state(RedeemStates.wait_game)
        await state.update_data(item_id=item_id, cost=cost)

        ask_game = t(lang, "market.redeem.ask_game",
                     "Ø§ÙƒØªØ¨ Ù†ÙˆØ¹/Ø§Ø³Ù… Ø§Ù„Ù„Ø¹Ø¨Ø© Ø§Ù„ØªÙŠ ØªØ±ÙŠØ¯ Ø§Ø³ØªØ¨Ø¯Ø§Ù„ Ù†Ù‚Ø§Ø·Ùƒ Ù„Ù‡Ø§ (Ù…Ø«Ø§Ù„: PUBGØŒ Free FireØŒ Fortnite...).")
        try:
            await cb.message.edit_text(ask_game, disable_web_page_preview=True)
        except TelegramBadRequest:
            await cb.message.answer(ask_game, disable_web_page_preview=True)
        await cb.message.answer(
            t(lang, "market.redeem.tip_game", "Ø£Ø±Ø³Ù„ Ø§Ø³Ù… Ø§Ù„Ù„Ø¹Ø¨Ø© Ø§Ù„Ø¢Ù† Ø£Ùˆ Ø§Ø®ØªØ± Â«Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªØ±Ø¬Ø§Ø¹Â»."),
            reply_markup=_cancel_rk(lang)
        )
        return

    # Ø§Ù„Ù…Ø³Ø§Ø± Ø§Ù„Ø­Ø§Ù„ÙŠ Ù„Ù„Ø§Ø´ØªØ±Ø§Ùƒ VIP ÙƒÙ…Ø§ Ù‡Ùˆ: Ø®Ø²Ù‘Ù† Ø³ÙŠØ§Ù‚ Ø§Ù„Ø·Ù„Ø¨ Ø«Ù… Ø§Ø·Ù„Ø¨ Ù…Ø¹Ø±Ù‘Ù Ø§Ù„ØªØ·Ø¨ÙŠÙ‚
    await state.clear()
    await state.set_state(BuyStates.wait_app)
    await state.update_data(item_id=item_id, cost=cost, hours=int(it.get("hours", 0)))

    tip = t(
        lang, "market.vip.ask_app",
        "Ø§Ø°Ù‡Ø¨ Ø¥Ù„Ù‰ ØªØ·Ø¨ÙŠÙ‚ Ù…Ø­Ø±Ùƒ Ø§Ù„Ø«Ø¹Ø¨Ø§Ù†ØŒ ÙÙŠ Ø£Ø¹Ù„Ù‰ Ø§Ù„ÙˆØ§Ø¬Ù‡Ø© (Ø§Ù„Ø²Ø§ÙˆÙŠØ© Ø§Ù„ÙŠØ³Ø±Ù‰) Ø³ØªØ¬Ø¯ <b>Ù…Ø¹Ø±Ù‘Ù Ø§Ù„ØªØ·Ø¨ÙŠÙ‚</b> Ø§Ù„Ø®Ø§Øµ Ø¨Ùƒ. Ø§Ù†Ø³Ø®Ù‡ ÙˆØ£Ø±Ø³Ù„Ù‡ Ù‡Ù†Ø§."
    )
    try:
        await cb.message.edit_text(tip, disable_web_page_preview=True)
    except TelegramBadRequest:
        await cb.message.answer(tip, disable_web_page_preview=True)
    await cb.message.answer(
        t(lang, "market.vip.ask_app_tip", "Ø£Ø±Ø³Ù„ Ø§Ù„Ù…Ø¹Ø±Ù‘Ù Ø§Ù„Ø¢Ù† Ø£Ùˆ Ø§Ø®ØªØ± Â«Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªØ±Ø¬Ø§Ø¹Â»."),
        reply_markup=_cancel_rk(lang)
    )
    await cb.answer()

# ======== Ø§Ø³ØªÙ„Ø§Ù… Ù…Ø¹Ø±Ù‘Ù Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ (VIP) â†’ Ø«Ù… Ø§Ù„ØªÙØ§ØµÙŠÙ„ ========
@router.message(BuyStates.wait_app)
async def buy_get_app(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="market_refund_cancel", typ="refund")
        await state.clear()
        return await msg.answer(t(lang, "market.vip.cancelled_refund", "ØªÙ… Ø§Ù„Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªÙØ±Ø¬Ø¹Øª Ù†Ù‚Ø§Ø·Ùƒ."),
                                reply_markup=ReplyKeyboardRemove())

    app_id = _normalize_app_id(txt)
    if not app_id:
        return await msg.reply(
            t(lang, "market.vip.invalid_app", "ØµÙŠØºØ© Ø§Ù„Ù…Ø¹Ø±Ù‘Ù ØºÙŠØ± ØµØ­ÙŠØ­Ø©. Ø§ÙƒØªØ¨ @username Ø£Ùˆ Ø§Ø³Ù…Ù‹Ø§ Ø¨Ø¯ÙˆÙ† @."),
            reply_markup=_cancel_rk(lang)
        )

    await state.update_data(app_id=app_id)
    await state.set_state(BuyStates.wait_details)

    ask = t(lang, "market.vip.ask_details",
            "Ø£Ø±Ø³Ù„ ØªÙØ§ØµÙŠÙ„ Ø§Ù„Ø§Ø´ØªØ±Ø§Ùƒ Ø§Ù„Ù…Ø·Ù„ÙˆØ¨Ø© (Ù…Ø«Ø§Ù„: Ø§Ù„Ù„Ø¹Ø¨Ø©/Ø§Ù„ÙˆØ¶Ø¹ØŒ Ù…Ù„Ø§Ø­Ø¸Ø§Øª Ø¥Ø¶Ø§ÙÙŠØ©).")
    tip = t(lang, "market.vip.details_tip", "ÙŠÙ…ÙƒÙ†Ùƒ ÙƒØªØ§Ø¨Ø© Ø£ÙŠ ØªÙØ§ØµÙŠÙ„ ØªØ³Ø§Ø¹Ø¯Ù†Ø§ Ø¹Ù„Ù‰ Ø§Ù„ØªÙØ¹ÙŠÙ„ Ø¨Ø´ÙƒÙ„ ØµØ­ÙŠØ­.")
    await msg.answer(ask)
    await msg.answer(tip, reply_markup=_cancel_rk(lang))

# ======== Ø§Ø³ØªÙ„Ø§Ù… ØªÙØ§ØµÙŠÙ„ (VIP) â†’ Ø¥Ù†Ø´Ø§Ø¡ Ø·Ù„Ø¨ Pending + Ø¥Ø´Ø¹Ø§Ø±Ø§Øª ========
@router.message(BuyStates.wait_details)
async def buy_get_details(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="market_refund_cancel", typ="refund")
        await state.clear()
        await msg.answer(t(lang, "market.vip.cancelled_refund", "ØªÙ… Ø§Ù„Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªÙØ±Ø¬Ø¹Øª Ù†Ù‚Ø§Ø·Ùƒ."),
                         reply_markup=ReplyKeyboardRemove())
        for aid in ADMIN_IDS:
            try:
                await msg.bot.send_message(aid, f"â†©ï¸ Ø§Ø³ØªØ±Ø¬Ø§Ø¹: Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… <code>{uid}</code> Ø£Ù„ØºÙ‰ Ø§Ù„Ø¹Ù…Ù„ÙŠØ© Ø£Ø«Ù†Ø§Ø¡ Ø¬Ù…Ø¹ Ø§Ù„ØªÙØ§ØµÙŠÙ„.")
            except Exception:
                pass
        return

    data = await state.get_data()
    await state.clear()

    item_id = data.get("item_id")
    cost = int(data.get("cost", 0))
    hours = int(data.get("hours", 0))
    app_id = data.get("app_id") or "-"
    tg_username = (msg.from_user.username or "").lstrip("@")

    # Ø¥Ù†Ø´Ø§Ø¡ Ø·Ù„Ø¨ Pending (VIP)
    oid = create_order(uid, kind="vip", payload={
        "hours": hours,
        "app": app_id,
        "details": txt,
        "tg_username": tg_username,
        "cost": cost,
    })

    # Ø¥Ø´Ø¹Ø§Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… + Ø§Ù„Ø£Ø¯Ù…Ù†
    await notify_user_vip_submitted(msg.bot, uid, oid, hours, cost)
    await notify_admins_new_vip_order(msg.bot, oid, uid, hours, app_id, txt, cost)

    # Ø±Ø³Ø§Ù„Ø© Ø¥Ø¶Ø§ÙÙŠØ© Ù„Ù„Ø£Ø¯Ù…Ù† ØªØªØ¶Ù…Ù† Username Ø¨Ø´ÙƒÙ„ ÙˆØ§Ø¶Ø­
    extra = f"â„¹ï¸ VIP order #{oid}\nâ€¢ User: <code>{uid}</code>{(' â€” @' + tg_username) if tg_username else ''}\nâ€¢ AppID: <code>{app_id}</code>"
    for aid in ADMIN_IDS:
        try:
            await msg.bot.send_message(aid, extra, disable_web_page_preview=True)
        except Exception:
            pass

# ======== (REDEEM) Ø§Ø³ØªÙ„Ø§Ù… Ù†ÙˆØ¹ Ø§Ù„Ù„Ø¹Ø¨Ø© â†’ Ø§Ù„ØªÙØ§ØµÙŠÙ„ â†’ Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„Ø·Ù„Ø¨ ÙˆØ¥Ø´Ø¹Ø§Ø± Ø§Ù„Ø£Ø¯Ù…Ù† ========
@router.message(RedeemStates.wait_game)
async def redeem_get_game(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="redeem_refund_cancel", typ="refund")
        await state.clear()
        return await msg.answer(t(lang, "market.redeem.cancelled_refund", "ØªÙ… Ø§Ù„Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªÙØ±Ø¬Ø¹Øª Ù†Ù‚Ø§Ø·Ùƒ."),
                                reply_markup=ReplyKeyboardRemove())

    # Ø¥Ù„Ø²Ø§Ù… ÙƒØªØ§Ø¨Ø© Ù„Ø¹Ø¨Ø© ÙˆØ§Ø¶Ø­Ø©
    game = txt
    if len(game) < 2:
        return await msg.reply(
            t(lang, "market.redeem.invalid_game", "Ù…Ù† ÙØ¶Ù„Ùƒ Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ù„Ø¹Ø¨Ø© Ø¨Ø´ÙƒÙ„ ÙˆØ§Ø¶Ø­."),
            reply_markup=_cancel_rk(lang)
        )

    await state.update_data(game=game)
    await state.set_state(RedeemStates.wait_details)

    ask = t(lang, "market.redeem.ask_details",
            "Ø£Ø±Ø³Ù„ ØªÙØ§ØµÙŠÙ„ Ø¥Ø¶Ø§ÙÙŠØ© (Ù…Ø«Ø§Ù„: Ø§Ù„Ù†Ø¸Ø§Ù…/Ø§Ù„Ø³ÙŠØ±ÙØ±/Ù…Ù„Ø§Ø­Ø¸Ø§Øª ØªÙ‡Ù… Ø§Ù„ØªÙ†ÙÙŠØ°).")
    tip = t(lang, "market.redeem.details_tip", "ØªÙØ§ØµÙŠÙ„ Ø£ÙƒØ«Ø± ØªØ³Ø§Ø¹Ø¯ Ø§Ù„Ø¥Ø¯Ø§Ø±Ø© Ø¹Ù„Ù‰ ØªÙ†ÙÙŠØ° Ø§Ù„Ø§Ø³ØªØ¨Ø¯Ø§Ù„.")
    await msg.answer(ask)
    await msg.answer(tip, reply_markup=_cancel_rk(lang))

@router.message(RedeemStates.wait_details)
async def redeem_get_details(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _L(uid)
    txt = (msg.text or "").strip()

    if _is_cancel(txt, lang):
        data = await state.get_data()
        add_points(uid, +int(data.get("cost", 0)), reason="redeem_refund_cancel", typ="refund")
        await state.clear()
        return await msg.answer(t(lang, "market.redeem.cancelled_refund", "ØªÙ… Ø§Ù„Ø¥Ù„ØºØ§Ø¡ ÙˆØ§Ø³ØªÙØ±Ø¬Ø¹Øª Ù†Ù‚Ø§Ø·Ùƒ."),
                                reply_markup=ReplyKeyboardRemove())

    data = await state.get_data()
    await state.clear()

    cost = int(data.get("cost", 0))
    game = data.get("game") or "-"
    tg_username = (msg.from_user.username or "").lstrip("@")

    # Ø¥Ù†Ø´Ø§Ø¡ Ø·Ù„Ø¨ Pending Ù„Ù†ÙˆØ¹ redeem
    oid = create_order(uid, kind="redeem", payload={
        "game": game,
        "details": txt,
        "tg_username": tg_username,
        "cost": cost,
    })

    # Ø¥Ø´Ø¹Ø§Ø± Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…
    await msg.answer(
        t(lang, "market.redeem.submitted",
          f"âœ… ØªÙ… Ø¥Ø±Ø³Ø§Ù„ Ø·Ù„Ø¨ Ø§Ù„Ø§Ø³ØªØ¨Ø¯Ø§Ù„ #{oid}.\nØ§Ù„Ù„Ø¹Ø¨Ø©: {game}\nØ³ÙŠØªÙ… Ø§Ù„Ù…Ø±Ø§Ø¬Ø¹Ø© ÙˆØ§Ù„ØªÙ†ÙÙŠØ° Ù‚Ø±ÙŠØ¨Ù‹Ø§."),
        reply_markup=ReplyKeyboardRemove()
    )

    # Ø¥Ø´Ø¹Ø§Ø± Ø§Ù„Ø£Ø¯Ù…Ù† â€” ÙŠØªØ¶Ù…Ù† Ù†ÙˆØ¹ Ø§Ù„Ù„Ø¹Ø¨Ø© ØµØ±Ø§Ø­Ø©Ù‹
    admin_text = (
        f"ðŸ†• Ø·Ù„Ø¨ Ø§Ø³ØªØ¨Ø¯Ø§Ù„ Ù†Ù‚Ø§Ø· #{oid}\n"
        f"â€¢ User: <code>{uid}</code>{(' â€” @' + tg_username) if tg_username else ''}\n"
        f"â€¢ Game: <b>{game}</b>\n"
        f"â€¢ Details: {txt or '-'}\n"
        f"â€¢ Cost: {cost}"
    )
    for aid in ADMIN_IDS:
        try:
            await msg.bot.send_message(aid, admin_text, disable_web_page_preview=True)
        except Exception:
            pass

# ======== (Ø£Ø¯Ù…Ù†) Ù‚Ø¨ÙˆÙ„/Ø±ÙØ¶ Ø·Ù„Ø¨ VIP ========
async def _grant_vip_hours_bridge(bot, uid: int, hours: int, reason: str = "rewards_approved") -> bool:
    """Ø¬Ø³Ø± Ø§Ø®ØªÙŠØ§Ø±ÙŠ Ù„ØªÙØ¹ÙŠÙ„ VIP Ø¥Ù† ØªÙˆÙØ±Øª ÙˆØ­Ø¯Ø© Ø§Ù„Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ù…Ù†Ø§Ø³Ø¨Ø©."""
    try:
        from admin.vip_manager import grant_vip_hours
        ok = await grant_vip_hours(bot, uid, hours, reason=reason)  # ÙŠØ¬Ø¨ Ø£Ù† ØªØ±Ø¬Ø¹ True/False
        return bool(ok)
    except Exception as e:
        log.warning(f"[VIP BRIDGE] not available / failed: {e}")
        return False

@router.callback_query(F.data.startswith("rwdadm:vip:approve:"))
async def approve_vip_order(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only", show_alert=True)

    oid = int(cb.data.split(":")[-1])
    row = get_order(oid)
    if not row:
        return await cb.answer("Order not found", show_alert=True)
    if row.get("status") != "pending":
        return await cb.answer("Already decided", show_alert=True)

    set_status(oid, "approved", admin_id=cb.from_user.id)
    p = row.get("payload", {}) or {}
    uid = int(row["uid"])
    hours = int(p.get("hours") or 0)
    app = str(p.get("app") or "-")
    details = str(p.get("details") or "-")

    ok = await _grant_vip_hours_bridge(cb.bot, uid, hours, reason="market_approved")
    if not ok:
        try:
            await cb.message.answer(
                f"â„¹ï¸ ØªÙ…Øª Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø© Ø¹Ù„Ù‰ #{oid} Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù… {uid} ({_fmt_hours_ar(hours)}). "
                f"Ù„Ù… ÙŠØªÙ… Ø§Ù„ØªÙØ¹ÙŠÙ„ Ø§Ù„Ø¢Ù„ÙŠ â€” ÙØ¹Ù‘ÙÙ„Ù‡ ÙŠØ¯ÙˆÙŠÙ‹Ø§ Ø¥Ù† Ù„Ø²Ù…."
            )
        except Exception:
            pass

    await notify_user_vip_approved(cb.bot, uid, oid, hours, app_id=app, details=details)
    try:
        await cb.message.edit_reply_markup()  # Ø¥Ø²Ø§Ù„Ø© Ø§Ù„Ø£Ø²Ø±Ø§Ø±
    except Exception:
        pass
    await cb.answer("âœ… Approved", show_alert=True)

@router.callback_query(F.data.startswith("rwdadm:vip:reject:"))
async def reject_vip_order(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only", show_alert=True)

    oid = int(cb.data.split(":")[-1])
    row = get_order(oid)
    if not row:
        return await cb.answer("Order not found", show_alert=True)
    if row.get("status") != "pending":
        return await cb.answer("Already decided", show_alert=True)

    p = row.get("payload", {}) or {}
    uid = int(row["uid"])
    cost = int(p.get("cost") or 0)

    # Ø±Ø¯Ù‘ Ø§Ù„Ù†Ù‚Ø§Ø· Ø«Ù… Ø¹Ù„Ù‘Ù… Ø§Ù„Ø·Ù„Ø¨ Ù…Ø±ÙÙˆØ¶
    if cost > 0:
        add_points(uid, +cost, reason="vip_order_refund", typ="refund")
    set_status(oid, "rejected", admin_id=cb.from_user.id)

    await notify_user_vip_rejected(cb.bot, uid, oid, refunded=cost)
    try:
        await cb.message.edit_reply_markup()
    except Exception:
        pass
    await cb.answer("âŒ Rejected & refunded", show_alert=True)

