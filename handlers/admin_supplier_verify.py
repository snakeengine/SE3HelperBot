# 📁 handlers/admin_supplier_verify.py

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode

from lang import t, get_user_lang

router = Router(name="admin_supplier_verify")

# TODO: استبدل هذه الدوال بـ DB حقيقية
async def set_user_status(user_id: int, status: str): ...
async def set_user_role_supplier(user_id: int): ...
async def get_user_lang_safe(user_id: int) -> str:
    return get_user_lang(user_id) or "en"

def _parse_payload(data: str):
    # شكل الكولباك: suppverify:<action>:<user_id>
    try:
        _, action, uid = data.split(":")
        return action, int(uid)
    except Exception:
        return None, None

@router.callback_query(F.data.startswith("suppverify:"))
async def handle_verify(cb: CallbackQuery):
    action, target_uid = _parse_payload(cb.data)
    if not action or not target_uid:
        await cb.answer("Invalid payload", show_alert=True)
        return

    # لغة المستخدم المستهدف لرسالة الإشعار
    lang_user = await get_user_lang_safe(target_uid)

    if action == "approve":
        # اعتماد كمورد
        await set_user_role_supplier(target_uid)
        await set_user_status(target_uid, "supplier")

        # إخطار المستخدم
        text_user = "✅ You are now a verified supplier. Welcome aboard!" if lang_user == "en" \
                    else "✅ تم اعتمادك كمورد مُعتمد. أهلاً بك!"
        try:
            await cb.message.bot.send_message(target_uid, text_user)
        except Exception:
            pass

        # تحديث رسالة الأدمن
        await cb.message.edit_text(
            cb.message.text + "\n\n✅ Approved.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        await cb.answer("Approved ✅")
        return

    if action == "reject":
        await set_user_status(target_uid, "rejected")

        text_user = "⛔ Your payment was rejected. Please contact support." if lang_user == "en" \
                    else "⛔ تم رفض الدفع. يرجى التواصل مع الدعم."
        try:
            await cb.message.bot.send_message(target_uid, text_user)
        except Exception:
            pass

        await cb.message.edit_text(
            cb.message.text + "\n\n⛔ Rejected.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        await cb.answer("Rejected ⛔")
        return

    if action == "askreceipt":
        await set_user_status(target_uid, "awaiting_receipt")

        text_user = ("🧾 Please upload a payment receipt (as a photo or file) here, and we will review it."
                     if lang_user == "en"
                     else "🧾 يرجى إرسال إيصال الدفع (صورة أو ملف) هنا وسنقوم بمراجعته.")
        try:
            await cb.message.bot.send_message(target_uid, text_user)
        except Exception:
            pass

        await cb.message.edit_text(
            cb.message.text + "\n\n🧾 Asked for receipt.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        await cb.answer("Asked for receipt 🧾")
        return
