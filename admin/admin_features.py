# admin/admin_features.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from utils.admins import is_admin as _is_admin
from lang import get_user_lang

# ← لاحظ: هذه الدوال تتوافق مع ملف utils/feature_flags.py الذي أرسلته
from utils.feature_flags import (
    list_tabs, get_tab, set_tab,
    maintenance, set_maintenance,
    DEFAULT_TABS, clear_message,
)

router = Router(name="admin_features")

# ======= Helpers =======
def _tab_title(lang: str, key: str) -> str:
    """يرجّع عنوان التبويب بلغته المناسبة من DEFAULT_TABS، وإلا يرجّع المفتاح نفسه."""
    for it in DEFAULT_TABS:
        if it["key"] == key:
            return it["label_ar"] if str(lang).startswith("ar") else it["label_en"]
    return key

def _kb_main(lang: str) -> InlineKeyboardMarkup:
    on, _ = maintenance(lang)
    mtxt = "🔴 الصيانة: فعّالة" if on else "🟢 الصيانة: متوقّفة"
    if not str(lang).startswith("ar"):
        mtxt = "🔴 Maintenance: ON" if on else "🟢 Maintenance: OFF"
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⚙️ " + mtxt, callback_data="ft:maint"))
    kb.row(InlineKeyboardButton(text=("📝 رسالة الصيانة" if str(lang).startswith("ar") else "📝 Maintenance message"),
                                callback_data="ft:maint_msg"))
    kb.row(InlineKeyboardButton(text=("🧰 إدارة التبويبات" if str(lang).startswith("ar") else "🧰 Tabs manager"),
                                callback_data="ft:tabs"))
    return kb.as_markup()

def _kb_maint(lang: str) -> InlineKeyboardMarkup:
    on, _ = maintenance(lang)
    kb = InlineKeyboardBuilder()
    if on:
        kb.row(InlineKeyboardButton(text=("🟢 إيقاف الصيانة" if str(lang).startswith("ar") else "🟢 Turn OFF"),
                                    callback_data="ft:maint_off"))
    else:
        kb.row(InlineKeyboardButton(text=("🔴 تفعيل الصيانة" if str(lang).startswith("ar") else "🔴 Turn ON"),
                                    callback_data="ft:maint_on"))
    kb.row(InlineKeyboardButton(text=("⬅️ رجوع" if str(lang).startswith("ar") else "⬅️ Back"),
                                callback_data="ft:open"))
    return kb.as_markup()

def _kb_tabs(lang: str) -> InlineKeyboardMarkup:
    tabs_list = list_tabs()  # ← قائمة قواميس
    tabs_map = {t["key"]: t for t in tabs_list}
    # ترتيب: الافتراضيات أولًا بنفس ترتيب DEFAULT_TABS ثم أي مفاتيح إضافية
    order = [it["key"] for it in DEFAULT_TABS] + [k for k in tabs_map.keys() if k not in [it["key"] for it in DEFAULT_TABS]]

    kb = InlineKeyboardBuilder()
    for key in order:
        t = tabs_map.get(key, {"enabled": True})
        mark = "🟢" if bool(t.get("enabled", True)) else "🔴"
        title = _tab_title(lang, key)
        kb.row(
            InlineKeyboardButton(text=f"{mark} {title}", callback_data=f"ft:toggle:{key}"),
            InlineKeyboardButton(text=("✍️ رسالة" if str(lang).startswith("ar") else "✍️ Message"), callback_data=f"ft:msg:{key}"),
            InlineKeyboardButton(text=("🧹 مسح الرسالة" if str(lang).startswith("ar") else "🧹 Clear message"), callback_data=f"ft:clr:{key}"),
        )
    kb.row(InlineKeyboardButton(text=("⬅️ رجوع" if str(lang).startswith("ar") else "⬅️ Back"), callback_data="ft:open"))
    return kb.as_markup()

# ======= فتح اللوحة =======
@router.message(Command("features"))
async def ft_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "ar"
    await msg.answer(("لوحة التحكّم بالتبويبات والصيانة:" if str(lang).startswith("ar") else "Tabs & Maintenance control:"),
                     reply_markup=_kb_main(lang))

@router.callback_query(F.data == "ft:open")
async def ft_open(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "ar"
    await cb.message.edit_text(("لوحة التحكّم بالتبويبات والصيانة:" if str(lang).startswith("ar") else "Tabs & Maintenance control:"),
                               reply_markup=_kb_main(lang))
    await cb.answer()

# ======= الصيانة =======
@router.callback_query(F.data == "ft:maint")
async def ft_maint(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "ar"
    on, msg = maintenance(lang)
    txt = ("🛠️ الصيانة فعّالة" if on else "✅ الصيانة متوقّفة")
    if msg:
        txt += f"\n{('الرسالة' if str(lang).startswith('ar') else 'Message')}: {msg}"
    await cb.message.edit_text(txt, reply_markup=_kb_maint(lang))
    await cb.answer()

@router.callback_query(F.data == "ft:maint_on")
async def ft_maint_on(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    set_maintenance(True)
    await ft_maint(cb)

@router.callback_query(F.data == "ft:maint_off")
async def ft_maint_off(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    set_maintenance(False)
    await ft_maint(cb)

# ======= رسالة الصيانة =======
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

class FtStates(StatesGroup):
    wait_maint_msg = State()
    wait_tab_msg = State()
    wait_tab_key = State()

@router.callback_query(F.data == "ft:maint_msg")
async def ft_maint_msg(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "ar"
    await state.set_state(FtStates.wait_maint_msg)
    await cb.message.answer(("أرسل الآن رسالة الصيانة (أو أرسل - لمسحها)." if str(lang).startswith("ar")
                             else "Send maintenance message now (or send - to clear)."))
    await cb.answer("…")

@router.message(FtStates.wait_maint_msg)
async def ft_maint_msg_set(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "ar"
    text = (msg.text or "").strip()
    # نستخدم الـ API المتوافق:
    from utils.feature_flags import maint_set_message, maint_clear_message
    if text == "-":
        maint_clear_message(lang)
    else:
        maint_set_message(text, lang)
    await state.clear()
    await msg.answer(("✅ تم التحديث." if str(lang).startswith("ar") else "✅ Updated."))

# ======= التبويبات =======
@router.callback_query(F.data == "ft:tabs")
async def ft_tabs(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "ar"
    await cb.message.edit_text(("إدارة التبويبات:" if str(lang).startswith("ar") else "Tabs manager:"),
                               reply_markup=_kb_tabs(lang))
    await cb.answer()

@router.callback_query(F.data.startswith("ft:toggle:"))
async def ft_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    key = cb.data.split(":")[-1]
    cur = get_tab(key)
    set_tab(key, enabled=not bool(cur.get("enabled", True)))
    await ft_tabs(cb)

@router.callback_query(F.data.startswith("ft:msg:"))
async def ft_msg(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    key = cb.data.split(":")[-1]
    await state.update_data(tab_key=key)
    await state.set_state(FtStates.wait_tab_msg)
    lang = get_user_lang(cb.from_user.id) or "ar"
    title = _tab_title(lang, key)
    prompt = "✍️ أرسل رسالة (غير متاح) للتبويب «{t}». أرسل - لمسحها." if str(lang).startswith("ar") \
             else "✍️ Send an 'unavailable' message for «{t}». Send - to clear."
    await cb.message.answer(prompt.format(t=title))
    await cb.answer("…")

@router.message(FtStates.wait_tab_msg)
async def ft_msg_set(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    key = data.get("tab_key")
    lang = get_user_lang(msg.from_user.id) or "ar"
    text = (msg.text or "").strip()
    if str(lang).startswith("ar"):
        set_tab(key, msg_ar=("" if text == "-" else text))
    else:
        set_tab(key, msg_en=("" if text == "-" else text))
    await state.clear()
    await msg.answer(("✅ تم الحفظ." if str(lang).startswith("ar") else "✅ Saved."))

@router.callback_query(F.data.startswith("ft:clr:"))
async def ft_msg_clear(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    key = cb.data.split(":")[-1]
    clear_message(key, None)  # مسح العربي والإنجليزي
    await ft_tabs(cb)
