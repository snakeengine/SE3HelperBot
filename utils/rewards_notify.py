from utils.admins import get_admin_ids, is_admin, get_owner_ids
# utils/rewards_notify.py
from __future__ import annotations

import os
import logging
from typing import Optional, Iterable, Any

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from lang import t, get_user_lang
from utils.rewards_store import get_points

log = logging.getLogger(__name__)

# ============ Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø¹Ø§Ù…Ø© ============
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids()

# Ù…ÙØ§ØªÙŠØ­ ØªØ¹Ø·ÙŠÙ„ Ø¥Ø´Ø¹Ø§Ø±Ø§Øª Ø§Ù„Ø£Ø¯Ù…Ù† Ù…Ù† .env
NOTIFY_ADMINS = (os.getenv("REWARDS_NOTIFY_ADMINS", "1").strip() not in {"0", "false", "no", "off", ""})
NOTIFY_VIP_ORDERS = (os.getenv("REWARDS_NOTIFY_VIP_ORDERS", "1").strip() not in {"0", "false", "no", "off", ""})

# ====== ØªØ¹Ø±ÙŠÙ Ø§Ù„Ø£Ù„Ø¹Ø§Ø¨ + ÙƒØ´Ù ØªÙ„Ù‚Ø§Ø¦ÙŠ Ù…Ù† Ø§Ù„Ù†Øµ ======
APP_8BP = "8bp"   # 8Ball Pool
APP_CAR = "car"   # Carrom Pool
APP_SET = {APP_8BP, APP_CAR}

APP_ALIASES = {
    APP_8BP: [
        "8bp", "8ball", "8 ball", "8-ball", "pool", "billiard",
        "Ø¨Ù„ÙŠØ§Ø±Ø¯", "Ø¨Ù„ÙŠØ§Ø±Ø¯Ùˆ", "Ø¨ÙˆÙ„", "Ø§ÙŠØªÙŠ Ø¨ÙˆÙ„", "8 Ø¨ÙˆÙ„",
    ],
    APP_CAR: [
        "carrom", "carom", "ÙƒØ§Ø±ÙˆÙ…", "ÙƒØ±ÙˆÙ…", "ÙƒØ§Ø±Ù…", "ÙƒØ§Ø±ÙˆÙ… Ø¨ÙˆÙ„",
    ],
}

def _detect_app_from_text(text: str | None) -> Optional[str]:
    """ÙŠØ­Ø§ÙˆÙ„ Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ø§Ù„Ù„Ø¹Ø¨Ø© Ù…Ù† Ù†Øµ Ø­Ø± Ø¨Ø§Ù„Ø¹Ø±Ø¨ÙŠ/Ø§Ù„Ø¥Ù†Ø¬Ù„ÙŠØ²ÙŠ."""
    if not text:
        return None
    s = str(text).lower()
    # Ù†Ø¹Ø·ÙŠ Ø£ÙˆÙ„ÙˆÙŠØ© Ù„Ù„ÙƒØ§Ø±ÙˆÙ… Ø¥Ø°Ø§ Ø°ÙƒØ±Øª ØµØ±Ø§Ø­Ø©ØŒ Ø«Ù… Ø§Ù„Ø¨Ù„ÙŠØ§Ø±Ø¯
    for key in APP_ALIASES[APP_CAR]:
        if key in s:
            return APP_CAR
    for key in APP_ALIASES[APP_8BP]:
        if key in s:
            return APP_8BP
    return None

def _app_human(app_id: str | None, lang: str) -> str:
    if not app_id:
        return "-"
    if app_id == APP_8BP:
        return "Ø¨Ù„ÙŠØ§Ø±Ø¯ (8Ball Pool)" if lang.startswith("ar") else "8Ball Pool"
    if app_id == APP_CAR:
        return "ÙƒØ§Ø±ÙˆÙ… (Carrom Pool)" if lang.startswith("ar") else "Carrom Pool"
    return app_id

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

async def _safe_send(bot, chat_id: int, text: str, **kwargs) -> bool:
    """Ø¥Ø±Ø³Ø§Ù„ Ø¢Ù…Ù† (Ø¨Ø¯ÙˆÙ† ÙƒØ³Ø± Ø§Ù„ØªØ¯ÙÙ‚) Ù…Ø¹ ØªØ¹Ø·ÙŠÙ„ Ø§Ù„Ù…Ø¹Ø§ÙŠÙ†Ø© Ø§ÙØªØ±Ø§Ø¶ÙŠÙ‹Ø§."""
    kwargs.setdefault("disable_web_page_preview", True)
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except Exception as e:
        log.debug(f"[notify] send failed chat_id={chat_id}: {e}")
        return False

# ------------------------------ Helpers ------------------------------
def _fb(lang: str, ar_text: str, en_text: str) -> str:
    """Ø§Ø®ØªÙŠØ§Ø± fallback Ø¨Ø­Ø³Ø¨ Ø§Ù„Ù„ØºØ©."""
    return ar_text if str(lang).startswith("ar") else en_text

def _fmt_hours(hours: int, lang: str) -> str:
    """ØªÙ†Ø³ÙŠÙ‚ Ù…Ø¯Ø© VIP Ø¨Ø§Ù„Ù„ØºØªÙŠÙ†."""
    if hours < 24:
        return _fb(lang, f"{hours} Ø³Ø§Ø¹Ø©", f"{hours} hour" + ("s" if hours != 1 else ""))
    days = hours // 24
    if str(lang).startswith("ar"):
        if days == 1:
            return "ÙŠÙˆÙ…"
        if days == 2:
            return "ÙŠÙˆÙ…ÙŠÙ†"
        if 3 <= days <= 10:
            return f"{days} Ø£ÙŠØ§Ù…"
        return f"{days} ÙŠÙˆÙ…Ù‹Ø§"
    else:
        return f"{days} day" + ("s" if days != 1 else "")

def _from_order(obj: Any) -> dict:
    """
    ÙŠÙÙƒÙ‘ Ù…Ø­ØªÙˆÙ‰ Ø·Ù„Ø¨ VIP Ø³ÙˆØ§Ø¡ ÙƒØ§Ù† dict Ø£Ùˆ object Ø¨Ø³ÙŠØ·.
    ÙŠØ¯Ø¹Ù… Ù…ÙØ§ØªÙŠØ­ Ø´Ø§Ø¦Ø¹Ø©: id/oid/order_id, uid/user_id, hours, app/app_id, details, cost/price.
    ÙƒÙ…Ø§ Ù†Ø­Ø§ÙˆÙ„ Ø§ÙƒØªØ´Ø§Ù Ø§Ù„Ù„Ø¹Ø¨Ø© Ù…Ù† details Ø¥Ù† Ù„Ù… ØªÙƒÙ† app_id ÙˆØ§Ø¶Ø­Ø© (8bp/car).
    """
    if isinstance(obj, dict):
        get = obj.get
    else:
        get = lambda k, default=None: getattr(obj, k, default)

    oid = get("id") or get("oid") or get("order_id")
    uid = get("uid") or get("user_id")
    hours = get("hours") or 0
    details = get("details") or get("note") or ""
    cost = get("cost") or get("price") or 0

    # Ø£ÙˆÙ„ÙˆÙŠØ©: app_id â†’ app â†’ Ø§ÙƒØªØ´Ø§Ù Ù…Ù† Ø§Ù„ØªÙØ§ØµÙŠÙ„
    app_id_raw = get("app_id") or get("app") or ""
    app_id = str(app_id_raw or "").strip().lower()
    if app_id not in APP_SET:
        app_id = _detect_app_from_text(details) or ""

    return {
        "oid": oid,
        "uid": uid,
        "hours": int(hours or 0),
        "app_id": app_id,                # ÙŠÙƒÙˆÙ† 8bp/ car Ø£Ùˆ ÙØ§Ø±Øº Ø¥Ø°Ø§ Ù„Ù… Ù†Ø³ØªØ·Ø¹ ÙƒØ´ÙÙ‡
        "details": str(details or ""),
        "cost": int(cost or 0),
    }

# ==============================================================
#                USER BALANCE / STATUS NOTIFICATIONS
# ==============================================================

async def notify_user_points(
    bot,
    uid: int,
    delta: int,
    new_balance: Optional[int] = None,
    *,
    actor_id: Optional[int] = None,
) -> None:
    if new_balance is None:
        try:
            new_balance = int(get_points(uid))
        except Exception:
            new_balance = None

    lang = _L(uid)
    if new_balance is None:
        text = t(lang, "rwdadm.user_notice.delta_short",
                 _fb(lang, "ØªÙ… ØªØ¹Ø¯ÙŠÙ„ Ø±ØµÙŠØ¯Ùƒ: {delta:+}", "Your balance changed: {delta:+}")) \
            .format(delta=delta)
    else:
        text = t(lang, "rwdadm.user_notice.delta",
                 _fb(lang, "ØªÙ… ØªØ¹Ø¯ÙŠÙ„ Ø±ØµÙŠØ¯Ùƒ: {delta:+} â€¢ Ø§Ù„Ø±ØµÙŠØ¯ Ø§Ù„Ø­Ø§Ù„ÙŠ: {balance}",
                             "Your balance changed: {delta:+} â€¢ New balance: {balance}")) \
            .format(delta=delta, balance=new_balance)

    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id,
                         f"âœ… delta={delta} balance={new_balance} | uid=<code>{uid}</code>")

async def notify_user_set_points(
    bot,
    uid: int,
    *args,
    actor_id: Optional[int] = None,
    **kwargs,
) -> None:
    # Ø§Ù„ØªÙ‚Ø· Ø¢Ø®Ø± Ù‚ÙŠÙ…Ø© Ø±Ù‚Ù…ÙŠØ© Ù…Ù† args ÙƒØ±ØµÙŠØ¯ Ø¬Ø¯ÙŠØ¯
    new_balance = None
    for v in args[::-1]:
        try:
            new_balance = int(v)
            break
        except Exception:
            continue
    if new_balance is None:
        try:
            new_balance = int(get_points(uid))
        except Exception:
            new_balance = 0

    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.set",
             _fb(lang, "ØªÙ… ØªØ¹ÙŠÙŠÙ† Ø±ØµÙŠØ¯Ùƒ Ø¥Ù„Ù‰: {balance}", "Your balance was set to: {balance}")) \
        .format(balance=new_balance)
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id,
                         f"âœ… set balance={new_balance} | uid=<code>{uid}</code>")

async def notify_user_ban(bot, uid: int, *args, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.ban",
             _fb(lang, "ðŸš« ØªÙ… Ø­Ø¸Ø±Ùƒ Ù…Ù† Ù†Ø¸Ø§Ù… Ø§Ù„Ø¬ÙˆØ§Ø¦Ø².", "ðŸš« You have been banned from rewards."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"âœ… banned uid=<code>{uid}</code>")

async def notify_user_unban(bot, uid: int, *args, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.unban",
             _fb(lang, "âœ… ØªÙ… ÙÙƒ Ø­Ø¸Ø±Ùƒ Ù…Ù† Ù†Ø¸Ø§Ù… Ø§Ù„Ø¬ÙˆØ§Ø¦Ø².", "âœ… Your rewards ban has been lifted."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"âœ… unbanned uid=<code>{uid}</code>")

async def notify_user_warns_reset(bot, uid: int, *, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.warns_reset",
             _fb(lang, "ØªÙ… ØªØµÙÙŠØ± Ø§Ù„ØªØ­Ø°ÙŠØ±Ø§Øª Ø¹Ù„Ù‰ Ø­Ø³Ø§Ø¨Ùƒ.", "Your warnings have been reset."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"âœ… warns reset | uid=<code>{uid}</code>")

async def notify_user_reset_account(bot, uid: int, *, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.reset",
             _fb(lang, "ØªÙ…Øª Ø¥Ø¹Ø§Ø¯Ø© Ø¶Ø¨Ø· Ø­Ø³Ø§Ø¨ Ø§Ù„Ø¬ÙˆØ§Ø¦Ø² Ø§Ù„Ø®Ø§Øµ Ø¨Ùƒ.", "Your rewards account has been reset."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"âœ… rewards reset | uid=<code>{uid}</code>")

# ==============================================================
#                        VIP ORDERS NOTIFY
# ==============================================================

async def notify_user_vip_submitted(
    bot,
    order_or_uid,
    oid: Optional[int] = None,
    hours: Optional[int] = None,
    cost: Optional[int] = None,
    app_id: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """
    ÙŠØ¯Ø¹Ù…:
      - notify_user_vip_submitted(bot, uid, oid, hours, cost, app_id=?, details=?)
      - notify_user_vip_submitted(bot, order_dict)
    Ø³ÙŠÙÙƒØªØ´Ù Ù†ÙˆØ¹ Ø§Ù„Ù„Ø¹Ø¨Ø© ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§ Ù…Ù† details Ø¹Ù†Ø¯ Ø§Ù„Ø­Ø§Ø¬Ø©.
    """
    if isinstance(order_or_uid, (dict,)):
        o = _from_order(order_or_uid)
        uid = o["uid"]
        oid = o["oid"]
        hours = o["hours"]
        # Ù†Ø¹Ø·ÙŠ Ø£ÙˆÙ„ÙˆÙŠØ© Ù„Ù…Ø§ ÙŠØ£ØªÙŠÙ†Ø§ ØµØ±Ø§Ø­Ø© Ø«Ù… Ø§Ù„Ø°ÙŠ Ø§ÙƒØªØ´ÙÙ†Ø§Ù‡
        app_id = (app_id or o["app_id"] or "").lower()
        details = details or o["details"]
    else:
        uid = int(order_or_uid)
        # Ù…Ø­Ø§ÙˆÙ„Ø© ÙƒØ´Ù Ù…Ù† details Ø§Ù„ÙˆØ§Ø±Ø¯Ø© (Ù„Ùˆ Ù…Ø±Ø±Øª Ù‡Ø°Ù‡ Ø§Ù„Ø¯Ø§Ù„Ø© ÙŠØ¯ÙˆÙŠÙ‹Ø§)
        app_id = (app_id or _detect_app_from_text(details)).lower() if (app_id or details) else ""

    lang = _L(uid)
    txt = t(
        lang,
        "rwd.vip.submitted",
        _fb(
            lang,
            "âœ… ØªÙ… Ø§Ø³ØªÙ„Ø§Ù… Ø·Ù„Ø¨ VIP Ø§Ù„Ø®Ø§Øµ Ø¨Ùƒ.\nØ±Ù‚Ù… Ø§Ù„Ø·Ù„Ø¨: #{oid}\nØ§Ù„Ù…Ø¯Ø©: {hours}\nØ¨Ø§Ù†ØªØ¸Ø§Ø± Ù…ÙˆØ§ÙÙ‚Ø© Ø§Ù„Ø¥Ø¯Ø§Ø±Ø©.",
            "âœ… Your VIP request has been submitted.\nOrder: #{oid}\nDuration: {hours}\nAwaiting admin approval.",
        ),
    ).format(oid=oid, hours=_fmt_hours(int(hours or 0), lang))

    # Ø³Ø·Ø± ØªÙˆØ¶ÙŠØ­ÙŠ Ø¨Ø§Ù„Ù„Ø¹Ø¨Ø© Ø¥Ù† Ø£Ù…ÙƒÙ†
    if app_id in APP_SET:
        txt += ("\nØ§Ù„Ù„Ø¹Ø¨Ø©: " if lang.startswith("ar") else "\nGame: ") + _app_human(app_id, lang)

    await _safe_send(bot, uid, txt)

async def notify_admins_new_vip_order(
    bot,
    order_or_oid,
    uid: Optional[int] = None,
    hours: Optional[int] = None,
    app_id: Optional[str] = None,
    details: Optional[str] = None,
    cost: Optional[int] = None,
    admins: Optional[Iterable[int]] = None,
) -> None:
    """
    ÙŠØ¯Ø¹Ù…:
      - notify_admins_new_vip_order(bot, order_dict)
      - notify_admins_new_vip_order(bot, oid, uid, hours, app_id=?, details=?, cost=?)
    Ø³ÙŠØªÙ… ØªØµØ­ÙŠØ­ app_id ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§ Ù…Ù† Ø§Ù„ØªÙØ§ØµÙŠÙ„ Ø¥Ù† ÙƒØ§Ù† ØºÙŠØ± ØµØ§Ù„Ø­.
    """
    if not (NOTIFY_ADMINS and NOTIFY_VIP_ORDERS):
        return

    if isinstance(order_or_oid, (dict,)):
        o = _from_order(order_or_oid)
        oid = o["oid"]
        uid = o["uid"]
        hours = o["hours"]
        # Ø£ÙˆÙ„ÙˆÙŠØ© Ù„Ù„Ù‚ÙŠÙ…Ø© Ø§Ù„Ù…Ù…Ø±Ù‘Ø±Ø© Ø«Ù… Ø§Ù„Ù…ÙƒØªØ´ÙØ©
        app_id = (app_id or o["app_id"] or "").lower()
        details = details or o["details"]
        cost = o["cost"] if cost is None else cost
    else:
        oid = order_or_oid
        # ØªØµØ­ÙŠØ­ app_id Ù…Ù† details Ø¥Ù† Ù„Ù… ØªÙƒÙ† ØµØ§Ù„Ø­Ø©
        if app_id not in APP_SET:
            app_id = _detect_app_from_text(details or "") or ""

    admins = list(admins) if admins else ADMIN_IDS
    if not admins:
        return

    app_h = _app_human(app_id, "ar")
    text = (
        "ðŸ§¾ <b>Ø·Ù„Ø¨ VIP Ø¬Ø¯ÙŠØ¯</b>\n"
        f"â€¢ Ø±Ù‚Ù…: <b>#{oid}</b>\n"
        f"â€¢ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…: <a href='tg://user?id={uid}'>{uid}</a>\n"
        f"â€¢ Ø§Ù„Ù…Ø¯Ø©: {_fmt_hours(int(hours or 0), 'ar')}\n"
        f"â€¢ Ø§Ù„Ù„Ø¹Ø¨Ø©: {app_h}\n"
        f"â€¢ ØªÙØ§ØµÙŠÙ„: {details or '-'}\n"
        f"â€¢ Ø§Ù„ØªÙƒÙ„ÙØ©: {int(cost or 0)}"
    )

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Ù…ÙˆØ§ÙÙ‚Ø© âœ…", callback_data=f"rwdadm:vip:approve:{oid}"),
            InlineKeyboardButton(text="Ø±ÙØ¶ âŒ",    callback_data=f"rwdadm:vip:reject:{oid}"),
        ]]
    )

    for aid in admins:
        await _safe_send(bot, aid, text, reply_markup=markup)

async def notify_user_vip_approved(
    bot,
    order_or_uid,
    oid: Optional[int] = None,
    hours: Optional[int] = None,
    *,
    app_id: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """
    ÙŠØ¯Ø¹Ù…:
      - notify_user_vip_approved(bot, uid, oid, hours, app_id=?, details=?)
      - notify_user_vip_approved(bot, order_dict)
    """
    if isinstance(order_or_uid, (dict,)):
        o = _from_order(order_or_uid)
        uid = o["uid"]
        oid = o["oid"]
        hours = o["hours"]
        if not app_id:
            app_id = o["app_id"]
        if not details:
            details = o["details"]
    else:
        uid = int(order_or_uid)

    lang = _L(uid)
    txt = t(
        lang,
        "rwd.vip.approved",
        _fb(lang, "âœ… ØªÙ…Øª Ø§Ù„Ù…ÙˆØ§ÙÙ‚Ø© Ø¹Ù„Ù‰ Ø·Ù„Ø¨ VIP #{oid} Ù„Ù…Ø¯Ø©: {hours}",
                    "âœ… Your VIP order #{oid} was approved for: {hours}"),
    ).format(oid=oid, hours=_fmt_hours(int(hours or 0), lang))

    extra = []
    if app_id in APP_SET:
        extra.append(_fb(lang, "\nØ§Ù„Ù„Ø¹Ø¨Ø©: ", "\nGame: ") + _app_human(app_id, lang))
    if details:
        extra.append(_fb(lang, "\nØ§Ù„ØªÙØ§ØµÙŠÙ„: ", "\nDetails: ") + details)

    await _safe_send(bot, uid, txt + "".join(extra))

async def notify_user_vip_rejected(
    bot,
    order_or_uid,
    oid: Optional[int] = None,
    *,
    reason: Optional[str] = None,
    refunded: int = 0,
) -> None:
    """
    ÙŠØ¯Ø¹Ù…:
      - notify_user_vip_rejected(bot, uid, oid, reason=?, refunded=?)
      - notify_user_vip_rejected(bot, order_dict, reason=?, refunded=?)
    """
    if isinstance(order_or_uid, (dict,)):
        o = _from_order(order_or_uid)
        uid = o["uid"]
        oid = o["oid"]
    else:
        uid = int(order_or_uid)

    lang = _L(uid)
    base = t(
        lang,
        "rwd.vip.rejected",
        _fb(lang, "âŒ ØªÙ… Ø±ÙØ¶ Ø·Ù„Ø¨ VIP #{oid}", "âŒ Your VIP order #{oid} was rejected"),
    ).format(oid=oid)
    if reason:
        base += _fb(lang, "\nØ§Ù„Ø³Ø¨Ø¨: ", "\nReason: ") + reason
    if refunded > 0:
        base += "\n" + t(
            lang,
            "rwd.vip.refund",
            _fb(lang, "â†©ï¸ ØªÙ… Ø±Ø¯ {amount} Ù†Ù‚Ø·Ø© Ø¥Ù„Ù‰ Ø±ØµÙŠØ¯Ùƒ.", "â†©ï¸ {amount} points have been refunded."),
        ).format(amount=refunded)
    await _safe_send(bot, uid, base)

async def notify_admins_vip_decision(
    bot,
    order_or_oid,
    uid: Optional[int] = None,
    decision: str = "approved",  # "approved" | "rejected"
    *,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> None:
    """
    ÙŠØ¯Ø¹Ù…:
      - notify_admins_vip_decision(bot, oid, uid, "approved"/"rejected", reason=?, actor_id=?)
      - notify_admins_vip_decision(bot, order_dict, ..., decision=?, ...)
    """
    if not NOTIFY_ADMINS:
        return

    if isinstance(order_or_oid, (dict,)):
        o = _from_order(order_or_oid)
        oid = o["oid"]
        uid = o["uid"]
    else:
        oid = order_or_oid

    icon = "âœ…" if decision == "approved" else "âŒ"
    text = f"{icon} VIP order #{oid} for uid <code>{uid}</code> â†’ {decision}"
    if reason:
        text += f" (reason: {reason})"
    for aid in ADMIN_IDS:
        if actor_id and aid == actor_id:
            continue
        await _safe_send(bot, aid, text)

