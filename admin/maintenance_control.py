# admin/maintenance_control.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.maintenance_state import is_enabled, set_enabled, toggle
from utils.admins import is_admin as _is_admin  # ← أهم سطر

router = Router(name="admin_maintenance_control")

def _status_text() -> str:
    return (
        "🛠️ <b>Maintenance Mode</b>\n"
        f"الحالة: {'✅ <b>قيد الصيانة</b>' if is_enabled() else '🟢 <b>يعمل</b>'}"
    )

def _kb():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ تشغيل الصيانة", callback_data="maint:on"),
        InlineKeyboardButton(text="🟢 إيقاف الصيانة", callback_data="maint:off"),
    )
    b.row(
        InlineKeyboardButton(text="🔁 تبديل", callback_data="maint:toggle"),
        InlineKeyboardButton(text="📊 الحالة", callback_data="maint:status"),
    )
    return b.as_markup()

@router.message(Command("maintenance"))
async def maintenance_cmd(msg: Message):
    if not msg.from_user or not _is_admin(msg.from_user.id):
        return
    await msg.answer(_status_text(), reply_markup=_kb())

@router.message(Command("maint_on"))
async def maint_on(msg: Message):
    if not msg.from_user or not _is_admin(msg.from_user.id):
        return
    set_enabled(True)
    await msg.answer("✅ تم تفعيل وضع الصيانة.\n" + _status_text(), reply_markup=_kb())

@router.message(Command("maint_off"))
async def maint_off(msg: Message):
    if not msg.from_user or not _is_admin(msg.from_user.id):
        return
    set_enabled(False)
    await msg.answer("🟢 تم إلغاء وضع الصيانة.\n" + _status_text(), reply_markup=_kb())

@router.callback_query(F.data.startswith("maint:"))
async def maintenance_cb(cb: CallbackQuery):
    if not cb.from_user or not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True)
        return

    action = cb.data.split(":", 1)[1]
    if action == "on":
        set_enabled(True); await cb.answer("Maintenance ON")
    elif action == "off":
        set_enabled(False); await cb.answer("Maintenance OFF")
    elif action == "toggle":
        new_val = toggle(); await cb.answer("Maintenance ON" if new_val else "Maintenance OFF")
    elif action == "status":
        await cb.answer("OK")

    try:
        await cb.message.edit_text(_status_text(), reply_markup=_kb())
    except Exception:
        await cb.message.answer(_status_text(), reply_markup=_kb())
