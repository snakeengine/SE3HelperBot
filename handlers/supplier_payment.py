# handlers/supplier_payment.py
from __future__ import annotations

import os
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from lang import t, get_user_lang
# نافذة السماح المؤقتة للإيصالات
try:
    from utils.receipt_gate import open_window as _open_receipt_window, close_window as _close_receipt_window
except Exception:
    def _open_receipt_window(*args, **kwargs): ...
    def _close_receipt_window(*args, **kwargs): ...

router = Router(name="supplier_payment")

# ===== إعدادات عامة =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

DEV_HANDLE   = os.getenv("DEV_HANDLE", "@DevSE2")
BINANCE_ID   = os.getenv("BINANCE_ID", "846769489")
SUPPLIER_FEE = int(os.getenv("SUPPLIER_FEE", "300"))

# ترقية/إلغاء المورد (اختياري – لو الملف غير موجود نكمل بدون خطأ)
try:
    from utils.suppliers import set_supplier as _set_supplier
except Exception:
    _set_supplier = None


def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def _tr(lang: str, key: str, en: str, ar: str) -> str:
    """
    ترجمة بمفتاح موجود مسبقًا مع قيمة احتياطية.
    لا نغيّر المفاتيح القديمة؛ فقط نوفّر نصًا افتراضيًا لو المفتاح ناقص.
    """
    try:
        v = t(lang, key)
        if isinstance(v, str) and v and v != key:
            return v
    except Exception:
        pass
    return ar if (lang or "ar").startswith("ar") else en


# ================= واجهة المستخدم: رسالة الدفع =================
async def prompt_user_payment(bot, user_id: int, lang: str | None = None):
    """
    يرسل رسالة الدفع للمستخدم مع زر 'تم الدفع ✅'.
    يعتمد على pay_title, pay_intro, pay_after_note, btn_i_paid
    ويستبدل {amount} و {binance}.
    """
    lang = lang or get_user_lang(user_id) or "en"

    title = _tr(
        lang, "pay_title",
        "Supplier payment",
        "دفع تفعيل المورد"
    )
    body_template = _tr(
        lang, "pay_intro",
        "To activate your supplier account, send <b>${amount}</b> in USDT to Binance ID <code>{binance}</code>, "
        "then tap the button below.",
        "لتفعيل حساب المورد، أرسل <b>{amount}$</b> USDT إلى معرف باينانس <code>{binance}</code> "
        "ثم اضغط الزر بالأسفل."
    )
    tail = _tr(
        lang, "pay_after_note",
        "After payment, verification is manual and may take some time.",
        "بعد التحويل، يتم التحقق يدويًا وقد يستغرق بعض الوقت."
    )
    body = body_template.format(amount=SUPPLIER_FEE, binance=BINANCE_ID)

    text = f"💳 <b>{title}</b>\n{body}\n\n{tail}"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=_tr(lang, "btn_i_paid", "I paid ✅", "تم الدفع ✅"),
            callback_data="supplier_paid"
        )
    ]])

    await bot.send_message(user_id, text, reply_markup=kb, disable_web_page_preview=True)


# ============= دالة عامة يمكن استدعاؤها من أي ملف =============
async def supplier_paid_done(
    bot,
    user_id: int,
    *,
    first_name: str = "",
    username: str = "",
    lang: str | None = None
):
    """
    عند ضغط المستخدم 'تم الدفع' أو استدعاؤها يدويًا:
      - تشكر المستخدم.
      - ترسل إشعارًا للأدمن مع أزرار التحقق.
    """
    lang = lang or get_user_lang(user_id) or "en"

    # إشعار المستخدم
    ack = _tr(
        lang,
        "supplier_paid_ack",
        "Thanks! We've notified the developer. You'll be upgraded after manual verification.",
        "شكرًا! تم إبلاغ المطوّر وسيتم ترقيتك بعد التحقق اليدوي."
    )
    try:
        await bot.send_message(user_id, ack)
    except Exception:
        pass

    # إشعار الأدمن
    uname = f"@{username}" if username else ""
    title = _tr(
        lang,
        "supplier_payment_notice_title",
        "🪙 Supplier Payment Notice",
        "🪙 إشعار دفع مورد"
    )
    body  = (
        f"<b>{title}</b>\n"
        f"{_tr(lang,'supplier_paid_user','User','المستخدم')} {first_name or ''} ({uname}) "
        f"{_tr(lang,'supplier_paid_confirms','confirms paying the $300 supplier fee.','يؤكد دفع رسوم المورد $300.')}\n\n"
        f"UserID: <code>{user_id}</code>\n"
        f"Binance ID: <code>{BINANCE_ID}</code>\n\n"
        f"{_tr(lang,'supplier_paid_footer','Please verify and upgrade.','يرجى التحقق والترقية.')}"
    )

    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_tr(lang,"adm_btn_confirm","Confirm ✅","تأكيد الدفع ✅"), callback_data=f"suppverify:confirm:{user_id}"),
            InlineKeyboardButton(text=_tr(lang,"adm_btn_reject","Not paid ⛔","لم يتم الدفع ⛔"),   callback_data=f"suppverify:reject:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=_tr(lang,"adm_btn_ask_receipt","Ask receipt 🧾","طلب إيصال 🧾"), callback_data=f"suppverify:askreceipt:{user_id}"),
            InlineKeyboardButton(text=_tr(lang,"adm_btn_contact","Contact user 🗣️","تواصل مع المستخدم 🗣️"), callback_data=f"suppverify:contact:{user_id}"),
        ],
    ])

    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, body, reply_markup=kb_admin, disable_web_page_preview=True)
        except Exception:
            pass


# =============== المستخدم ضغط زر "تم الدفع ✅" ===============
@router.callback_query(F.data == "supplier_paid")
async def _fallback_supplier_paid(cb: CallbackQuery):
    await supplier_paid_done(
        cb.message.bot,
        cb.from_user.id,
        first_name=cb.from_user.first_name or "",
        username=cb.from_user.username or "",
        lang=get_user_lang(cb.from_user.id) or "ar",
    )
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("OK")


# =============== كولباكات الأدمن للتحقق ===============
@router.callback_query(F.data.regexp(r"^suppverify:(confirm|reject|askreceipt|contact):\d+$"))
async def admin_verify_actions(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tr("en", "admins_only", "Admins only.", "خاص بالأدمن."), show_alert=True)

    _, action, uid_s = cb.data.split(":")
    target_uid = int(uid_s)

    admin_lang = get_user_lang(cb.from_user.id) or "en"
    user_lang  = get_user_lang(target_uid) or "en"

    if action == "confirm":
        # أغلق نافذة السماح إن كانت مفتوحة
        _close_receipt_window(target_uid)

        if _set_supplier:
            try:
                _set_supplier(target_uid, True)
            except Exception as e:
                logging.warning(f"set_supplier failed for {target_uid}: {e}")

        msg_user = _tr(
            user_lang,
            "supplier_verify_ok_user",
            f"✅ Payment verified. You're now a supplier. The developer {DEV_HANDLE} will contact you to finalize access. Use /start to see supplier tools.",
            f"✅ تم التحقق من الدفع. تم ترقيتك كمورّد. سيتواصل معك المطوّر {DEV_HANDLE} لإتمام الوصول. استخدم /start لرؤية أدوات المورد."
        )
        try:
            await cb.message.bot.send_message(target_uid, msg_user, disable_web_page_preview=True)
        except Exception:
            pass

        done = _tr(admin_lang, "supplier_verify_ok_admin", "Confirmed ✅", "تم التأكيد ✅")
        try:
            await cb.message.edit_text(cb.message.text + f"\n\n{done}", disable_web_page_preview=True)
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        return await cb.answer("OK")

    if action == "reject":
        # أغلق نافذة السماح إن كانت مفتوحة
        _close_receipt_window(target_uid)

        # ⬇️ ألغي اعتماد المورد لو كان مفعَّلًا
        if _set_supplier:
            try:
                _set_supplier(target_uid, False)
            except Exception as e:
                logging.warning(f"set_supplier(False) failed for {target_uid}: {e}")

        msg_user = _tr(
            user_lang,
            "supplier_verify_reject_user",
            f"⛔ We couldn't verify your payment. If you already paid, please send the receipt or contact {DEV_HANDLE}.",
            f"⛔ تعذّر التحقق من الدفع. إن كنت دفعت بالفعل، الرجاء إرسال إيصال التحويل أو التواصل مع {DEV_HANDLE}."
        )

        try:
            await cb.message.bot.send_message(target_uid, msg_user, disable_web_page_preview=True)
        except Exception:
            pass

        note = _tr(admin_lang, "supplier_verify_reject_admin", "Marked as not paid.", "تم وضع الحالة: لم يتم الدفع.")
        try:
            await cb.message.edit_text(cb.message.text + f"\n\n{note}", disable_web_page_preview=True)
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        return await cb.answer("OK")

    if action == "askreceipt":
        # اسمح للمستخدم بإرسال صورة/مستند/نص لمدة 60 دقيقة (يمكن تعديلها)
        _open_receipt_window(target_uid, types=("photo", "document", "text"), ttl=3600)

        ask = _tr(
            user_lang,
            "supplier_verify_askreceipt_user",
            "Please send the payment receipt (screenshot or TxID).",
            "يرجى إرسال إيصال الدفع (لقطة شاشة أو TxID)."
        )
        try:
            await cb.message.bot.send_message(target_uid, ask)
        except Exception:
            pass

        done = _tr(admin_lang, "supplier_verify_askreceipt_admin", "Receipt requested from the user.", "تم طلب الإيصال من المستخدم.")
        return await cb.answer(done, show_alert=False)

    if action == "contact":
        open_chat_text = _tr(admin_lang, "supplier_verify_contact_open", "Open chat", "فتح المحادثة")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=open_chat_text, url=f"tg://user?id={target_uid}")
        ]])
        info = _tr(admin_lang, "supplier_verify_contact_info", "You can contact the user directly.", "يمكنك التواصل مع المستخدم مباشرة.")
        await cb.message.answer(info, reply_markup=kb, disable_web_page_preview=True)
        return await cb.answer("OK")


# =============== إلغاء المورد ===============
@router.message(Command("unsupplier"))
async def cmd_unsupplier(msg: Message):
    """أمر أدمن: /unsupplier <user_id>"""
    if not _is_admin(msg.from_user.id):
        return await msg.answer(_tr("en", "admins_only", "Admins only.", "خاص بالأدمن."))

    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
        return await msg.answer("Usage: /unsupplier <user_id>\nمثال: /unsupplier 123456789")

    target_uid = int(parts[1].strip())

    if _set_supplier:
        try:
            _set_supplier(target_uid, False)
        except Exception as e:
            logging.warning(f"set_supplier(False) failed for {target_uid}: {e}")

    admin_lang = get_user_lang(msg.from_user.id) or "en"
    user_lang  = get_user_lang(target_uid) or "en"

    # إشعار المستخدم
    try:
        await msg.bot.send_message(
            target_uid,
            _tr(
                user_lang,
                "supplier_demoted_user",
                "Your supplier status has been removed. You are now a regular user. Use /start to refresh your menu.",
                "تم إلغاء اعتمادك كمورّد. تم تحويلك إلى مستخدم عادي. استخدم /start لتحديث قائمتك."
            )
        )
    except Exception:
        pass

    # رد للأدمن
    await msg.answer(
        _tr(
            admin_lang,
            "supplier_demoted_admin",
            f"Removed supplier status for {target_uid} ✅",
            f"تم إلغاء اعتماد المورد للمعرّف {target_uid} ✅"
        )
    )


@router.callback_query(F.data.regexp(r"^suppverify:demote:\d+$"))
async def admin_demote_cb(cb: CallbackQuery):
    """زر كولباك اختياري لإلغاء المورد من بطاقة الأدمن."""
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tr("en", "admins_only", "Admins only.", "خاص بالأدمن."), show_alert=True)

    target_uid = int(cb.data.split(":")[2])

    if _set_supplier:
        try:
            _set_supplier(target_uid, False)
        except Exception as e:
            logging.warning(f"set_supplier(False) failed for {target_uid}: {e}")

    admin_lang = get_user_lang(cb.from_user.id) or "en"
    user_lang  = get_user_lang(target_uid) or "en"

    # إشعار المستخدم
    try:
        await cb.message.bot.send_message(
            target_uid,
            _tr(
                user_lang,
                "supplier_demoted_user",
                "Your supplier status has been removed. You are now a regular user. Use /start to refresh your menu.",
                "تم إلغاء اعتمادك كمورّد. تم تحويلك إلى مستخدم عادي. استخدم /start لتحديث قائمتك."
            )
        )
    except Exception:
        pass

    # تحديث رسالة الأدمن
    try:
        note = _tr(admin_lang, "supplier_demoted_admin_short", "✅ Supplier access removed.", "✅ تم إلغاء اعتماد المورد.")
        await cb.message.edit_text(cb.message.text + f"\n\n{note}", disable_web_page_preview=True)
    except Exception:
        pass
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await cb.answer("OK")
