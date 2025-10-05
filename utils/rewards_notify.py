# utils/rewards_notify.py
from __future__ import annotations

import os
import logging
from typing import Optional, Iterable, Any

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from lang import t, get_user_lang
from utils.rewards_store import get_points

log = logging.getLogger(__name__)

# ============ إعدادات عامة ============
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in _admin_env.split(",") if x.strip().isdigit()]

# مفاتيح تعطيل إشعارات الأدمن من .env
NOTIFY_ADMINS = (os.getenv("REWARDS_NOTIFY_ADMINS", "1").strip() not in {"0", "false", "no", "off", ""})
NOTIFY_VIP_ORDERS = (os.getenv("REWARDS_NOTIFY_VIP_ORDERS", "1").strip() not in {"0", "false", "no", "off", ""})

# ====== تعريف الألعاب + كشف تلقائي من النص ======
APP_8BP = "8bp"   # 8Ball Pool
APP_CAR = "car"   # Carrom Pool
APP_SET = {APP_8BP, APP_CAR}

APP_ALIASES = {
    APP_8BP: [
        "8bp", "8ball", "8 ball", "8-ball", "pool", "billiard",
        "بليارد", "بلياردو", "بول", "ايتي بول", "8 بول",
    ],
    APP_CAR: [
        "carrom", "carom", "كاروم", "كروم", "كارم", "كاروم بول",
    ],
}

def _detect_app_from_text(text: str | None) -> Optional[str]:
    """يحاول استخراج اللعبة من نص حر بالعربي/الإنجليزي."""
    if not text:
        return None
    s = str(text).lower()
    # نعطي أولوية للكاروم إذا ذكرت صراحة، ثم البليارد
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
        return "بليارد (8Ball Pool)" if lang.startswith("ar") else "8Ball Pool"
    if app_id == APP_CAR:
        return "كاروم (Carrom Pool)" if lang.startswith("ar") else "Carrom Pool"
    return app_id

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

async def _safe_send(bot, chat_id: int, text: str, **kwargs) -> bool:
    """إرسال آمن (بدون كسر التدفق) مع تعطيل المعاينة افتراضيًا."""
    kwargs.setdefault("disable_web_page_preview", True)
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except Exception as e:
        log.debug(f"[notify] send failed chat_id={chat_id}: {e}")
        return False

# ------------------------------ Helpers ------------------------------
def _fb(lang: str, ar_text: str, en_text: str) -> str:
    """اختيار fallback بحسب اللغة."""
    return ar_text if str(lang).startswith("ar") else en_text

def _fmt_hours(hours: int, lang: str) -> str:
    """تنسيق مدة VIP باللغتين."""
    if hours < 24:
        return _fb(lang, f"{hours} ساعة", f"{hours} hour" + ("s" if hours != 1 else ""))
    days = hours // 24
    if str(lang).startswith("ar"):
        if days == 1:
            return "يوم"
        if days == 2:
            return "يومين"
        if 3 <= days <= 10:
            return f"{days} أيام"
        return f"{days} يومًا"
    else:
        return f"{days} day" + ("s" if days != 1 else "")

def _from_order(obj: Any) -> dict:
    """
    يفكّ محتوى طلب VIP سواء كان dict أو object بسيط.
    يدعم مفاتيح شائعة: id/oid/order_id, uid/user_id, hours, app/app_id, details, cost/price.
    كما نحاول اكتشاف اللعبة من details إن لم تكن app_id واضحة (8bp/car).
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

    # أولوية: app_id → app → اكتشاف من التفاصيل
    app_id_raw = get("app_id") or get("app") or ""
    app_id = str(app_id_raw or "").strip().lower()
    if app_id not in APP_SET:
        app_id = _detect_app_from_text(details) or ""

    return {
        "oid": oid,
        "uid": uid,
        "hours": int(hours or 0),
        "app_id": app_id,                # يكون 8bp/ car أو فارغ إذا لم نستطع كشفه
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
                 _fb(lang, "تم تعديل رصيدك: {delta:+}", "Your balance changed: {delta:+}")) \
            .format(delta=delta)
    else:
        text = t(lang, "rwdadm.user_notice.delta",
                 _fb(lang, "تم تعديل رصيدك: {delta:+} • الرصيد الحالي: {balance}",
                             "Your balance changed: {delta:+} • New balance: {balance}")) \
            .format(delta=delta, balance=new_balance)

    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id,
                         f"✅ delta={delta} balance={new_balance} | uid=<code>{uid}</code>")

async def notify_user_set_points(
    bot,
    uid: int,
    *args,
    actor_id: Optional[int] = None,
    **kwargs,
) -> None:
    # التقط آخر قيمة رقمية من args كرصيد جديد
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
             _fb(lang, "تم تعيين رصيدك إلى: {balance}", "Your balance was set to: {balance}")) \
        .format(balance=new_balance)
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id,
                         f"✅ set balance={new_balance} | uid=<code>{uid}</code>")

async def notify_user_ban(bot, uid: int, *args, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.ban",
             _fb(lang, "🚫 تم حظرك من نظام الجوائز.", "🚫 You have been banned from rewards."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"✅ banned uid=<code>{uid}</code>")

async def notify_user_unban(bot, uid: int, *args, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.unban",
             _fb(lang, "✅ تم فك حظرك من نظام الجوائز.", "✅ Your rewards ban has been lifted."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"✅ unbanned uid=<code>{uid}</code>")

async def notify_user_warns_reset(bot, uid: int, *, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.warns_reset",
             _fb(lang, "تم تصفير التحذيرات على حسابك.", "Your warnings have been reset."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"✅ warns reset | uid=<code>{uid}</code>")

async def notify_user_reset_account(bot, uid: int, *, actor_id: Optional[int] = None) -> None:
    lang = _L(uid)
    text = t(lang, "rwdadm.user_notice.reset",
             _fb(lang, "تمت إعادة ضبط حساب الجوائز الخاص بك.", "Your rewards account has been reset."))
    await _safe_send(bot, uid, text)
    if actor_id:
        await _safe_send(bot, actor_id, f"✅ rewards reset | uid=<code>{uid}</code>")

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
    يدعم:
      - notify_user_vip_submitted(bot, uid, oid, hours, cost, app_id=?, details=?)
      - notify_user_vip_submitted(bot, order_dict)
    سيُكتشف نوع اللعبة تلقائيًا من details عند الحاجة.
    """
    if isinstance(order_or_uid, (dict,)):
        o = _from_order(order_or_uid)
        uid = o["uid"]
        oid = o["oid"]
        hours = o["hours"]
        # نعطي أولوية لما يأتينا صراحة ثم الذي اكتشفناه
        app_id = (app_id or o["app_id"] or "").lower()
        details = details or o["details"]
    else:
        uid = int(order_or_uid)
        # محاولة كشف من details الواردة (لو مررت هذه الدالة يدويًا)
        app_id = (app_id or _detect_app_from_text(details)).lower() if (app_id or details) else ""

    lang = _L(uid)
    txt = t(
        lang,
        "rwd.vip.submitted",
        _fb(
            lang,
            "✅ تم استلام طلب VIP الخاص بك.\nرقم الطلب: #{oid}\nالمدة: {hours}\nبانتظار موافقة الإدارة.",
            "✅ Your VIP request has been submitted.\nOrder: #{oid}\nDuration: {hours}\nAwaiting admin approval.",
        ),
    ).format(oid=oid, hours=_fmt_hours(int(hours or 0), lang))

    # سطر توضيحي باللعبة إن أمكن
    if app_id in APP_SET:
        txt += ("\nاللعبة: " if lang.startswith("ar") else "\nGame: ") + _app_human(app_id, lang)

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
    يدعم:
      - notify_admins_new_vip_order(bot, order_dict)
      - notify_admins_new_vip_order(bot, oid, uid, hours, app_id=?, details=?, cost=?)
    سيتم تصحيح app_id تلقائيًا من التفاصيل إن كان غير صالح.
    """
    if not (NOTIFY_ADMINS and NOTIFY_VIP_ORDERS):
        return

    if isinstance(order_or_oid, (dict,)):
        o = _from_order(order_or_oid)
        oid = o["oid"]
        uid = o["uid"]
        hours = o["hours"]
        # أولوية للقيمة الممرّرة ثم المكتشفة
        app_id = (app_id or o["app_id"] or "").lower()
        details = details or o["details"]
        cost = o["cost"] if cost is None else cost
    else:
        oid = order_or_oid
        # تصحيح app_id من details إن لم تكن صالحة
        if app_id not in APP_SET:
            app_id = _detect_app_from_text(details or "") or ""

    admins = list(admins) if admins else ADMIN_IDS
    if not admins:
        return

    app_h = _app_human(app_id, "ar")
    text = (
        "🧾 <b>طلب VIP جديد</b>\n"
        f"• رقم: <b>#{oid}</b>\n"
        f"• المستخدم: <a href='tg://user?id={uid}'>{uid}</a>\n"
        f"• المدة: {_fmt_hours(int(hours or 0), 'ar')}\n"
        f"• اللعبة: {app_h}\n"
        f"• تفاصيل: {details or '-'}\n"
        f"• التكلفة: {int(cost or 0)}"
    )

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="موافقة ✅", callback_data=f"rwdadm:vip:approve:{oid}"),
            InlineKeyboardButton(text="رفض ❌",    callback_data=f"rwdadm:vip:reject:{oid}"),
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
    يدعم:
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
        _fb(lang, "✅ تمت الموافقة على طلب VIP #{oid} لمدة: {hours}",
                    "✅ Your VIP order #{oid} was approved for: {hours}"),
    ).format(oid=oid, hours=_fmt_hours(int(hours or 0), lang))

    extra = []
    if app_id in APP_SET:
        extra.append(_fb(lang, "\nاللعبة: ", "\nGame: ") + _app_human(app_id, lang))
    if details:
        extra.append(_fb(lang, "\nالتفاصيل: ", "\nDetails: ") + details)

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
    يدعم:
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
        _fb(lang, "❌ تم رفض طلب VIP #{oid}", "❌ Your VIP order #{oid} was rejected"),
    ).format(oid=oid)
    if reason:
        base += _fb(lang, "\nالسبب: ", "\nReason: ") + reason
    if refunded > 0:
        base += "\n" + t(
            lang,
            "rwd.vip.refund",
            _fb(lang, "↩️ تم رد {amount} نقطة إلى رصيدك.", "↩️ {amount} points have been refunded."),
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
    يدعم:
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

    icon = "✅" if decision == "approved" else "❌"
    text = f"{icon} VIP order #{oid} for uid <code>{uid}</code> → {decision}"
    if reason:
        text += f" (reason: {reason})"
    for aid in ADMIN_IDS:
        if actor_id and aid == actor_id:
            continue
        await _safe_send(bot, aid, text)
