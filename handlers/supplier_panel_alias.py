# handlers/supplier_panel_alias.py
from __future__ import annotations
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="supplier_panel_alias")

# محاولة معرفة إن كان المستخدم مورّد (اختياري)
try:
    from utils.suppliers import is_supplier as _is_supplier
except Exception:
    _is_supplier = None

def _kb_fallback(lang_is_ar: bool):
    kb = InlineKeyboardBuilder()
    # أزرار آمنة موجودة مسبقًا عندك
    kb.row(InlineKeyboardButton(text=("🏷️ المورّدون الموثوقون" if lang_is_ar else "Trusted suppliers"),
                                callback_data="trusted_suppliers"))
    kb.row(InlineKeyboardButton(text=("🏠 العودة للقائمة" if lang_is_ar else "Main menu"),
                                callback_data="back_to_menu"))
    return kb.as_markup()

@router.callback_query(F.data == "supplier_panel")
async def supplier_panel_alias(cb: CallbackQuery):
    lang_is_ar = (getattr(cb.from_user, "language_code", "en") or "en").startswith("ar")

    # لو مش مورّد، أعط تنبيه خفيف
    try:
        if _is_supplier and not _is_supplier(cb.from_user.id):
            await cb.answer("هذه اللوحة للمورّدين فقط." if lang_is_ar else "Suppliers only.", show_alert=True)
            return
    except Exception:
        pass

    # جرّب استدعاء لوحة موجودة في handlers.reseller إن كان بها دالة جاهزة
    try:
        from handlers.reseller import open_reseller_panel  # type: ignore
        # كثير من لوحاتك تأخذ (CallbackQuery) مباشرة
        await open_reseller_panel(cb)  # إذا كانت التوقيع مختلف، تجاهل ويروح للفولباك
        return
    except Exception:
        pass

    # فولباك بسيط
    text = "🧰 لوحة المورد" if lang_is_ar else "🧰 Supplier Panel"
    await cb.message.edit_text(text, reply_markup=_kb_fallback(lang_is_ar))
    await cb.answer()
