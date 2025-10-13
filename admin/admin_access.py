from __future__ import annotations

# admin/admin_access.py

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
import os
from aiogram.exceptions import TelegramForbiddenError
from lang import get_user_lang
from utils.admins import ADMIN_IDS, OWNERS, is_admin, add_admin, remove_admin, list_admins

router = Router(name="admin_access")
router.message.filter(F.chat.type == "private", F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.message.chat.type == "private", F.from_user.id.in_(ADMIN_IDS))




ADMIN_ALERT_CHAT_ID = int(os.getenv("ADMIN_ALERT_CHAT_ID", "0") or 0)

async def _notify_admin_change(bot, target_uid: int, added: bool, actor_id: int):
    """يرسل إشعار للمستخدم الذي تغيّرت حالته + ينشر إشعار اختياري في قناة/قروب المشرفين."""
    # نص المستخدم
    lang = (get_user_lang(target_uid) or "en").lower()
    if added:
        text_ar = (
            "🎉 تم ترقيتك إلى <b>مشرف</b> في البوت.\n"
            "يمكنك فتح لوحة الأدمن عبر الأمر: <code>/admin</code>"
        )
        text_en = (
            "🎉 You’ve been promoted to <b>admin</b>.\n"
            "Open the admin panel with: <code>/admin</code>"
        )
    else:
        text_ar = "⚠️ تم إزالة صلاحيات الأدمن الخاصة بك."
        text_en = "⚠️ Your admin permissions were removed."

    text_user = text_ar if lang.startswith("ar") else text_en

    # حاول مراسلة المستخدم (قد يفشل إذا لم يبدأ البوت/قام بالحظر)
    try:
        await bot.send_message(target_uid, text_user, parse_mode="HTML")
    except TelegramForbiddenError:
        # لا يمكن بدء المحادثة — نخبر المنفّذ
        try:
            await bot.send_message(
                actor_id,
                "⚠️ لا أستطيع مراسلة المستخدم (لم يبدأ البوت أو قام بحظره).",
            )
        except Exception:
            pass
    except Exception:
        # تجاهل أي خطأ آخر
        pass

    # إشعار اختياري لغرفة تنبيهات الأدمن
    if ADMIN_ALERT_CHAT_ID:
        sign = "✅ ترقية" if added else "⛔ إزالة"
        try:
            await bot.send_message(
                ADMIN_ALERT_CHAT_ID,
                f"{sign} صلاحيات: <code>{target_uid}</code> بواسطة <code>{actor_id}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass

# ================= helpers =================
def _mention(uid: int) -> str:
    return f'<a href="tg://user?id={uid}">{uid}</a>'

async def _resolve_user_id(bot, raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    if raw.startswith("@"):
        try:
            chat = await bot.get_chat(raw)
            if chat.type.name == "PRIVATE":
                return int(chat.id)
        except Exception:
            return None
    return None

def _kb_main(owner: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📋 عرض القائمة", callback_data="admacc:list")],
    ]
    if owner:
        rows.append([
            InlineKeyboardButton(text="➕ إضافة أدمن", callback_data="admacc:add"),
            InlineKeyboardButton(text="➖ إزالة أدمن", callback_data="admacc:del"),
        ])
    rows.append([InlineKeyboardButton(text="« رجوع", callback_data="admin:home")])  # إن لم توجد admin:home تجاهلها
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _list_text() -> str:
    owners = ", ".join(_mention(x) for x in sorted(OWNERS)) or "-"
    others = ", ".join(_mention(x) for x in sorted(set(list_admins()) - OWNERS)) or "—"
    return f"👑 <b>Owners</b>: {owners}\n🛡️ <b>Admins</b>: {others}"

# ================= states =================
class S(StatesGroup):
    add = State()
    rem = State()

# ================ open panel ================
@router.callback_query(F.data.in_({"admacc:open", "admacc:list"}))
async def open_panel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    owner = cb.from_user.id in OWNERS
    text = "👥 <b>إدارة الأدمن</b>\n\n" + _list_text()
    try:
        await cb.message.edit_text(text, reply_markup=_kb_main(owner), parse_mode=ParseMode.HTML)
    except Exception:
        await cb.message.answer(text, reply_markup=_kb_main(owner), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.message(Command("admins"))
async def cmd_admins(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    await msg.answer(_list_text(), parse_mode=ParseMode.HTML,
                     reply_markup=_kb_main(msg.from_user.id in OWNERS))

# ================ add ================
@router.callback_query(F.data == "admacc:add")
async def start_add(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in OWNERS:
        return await cb.answer("Owners only.", show_alert=True)
    await state.set_state(S.add)
    await cb.message.answer("أرسل @username أو الـ ID، أو ردّ على رسالة الشخص ثم اكتب أي شيء.")
    await cb.answer()

@router.message(S.add)
async def on_add(msg: Message, state: FSMContext):
    if msg.from_user.id not in OWNERS:
        return
    uid = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        uid = int(msg.reply_to_message.from_user.id)
    else:
        uid = await _resolve_user_id(msg.bot, msg.text or "")
    if not uid:
        return await msg.reply("صيغة غير صحيحة. أرسل @username أو رقم ID أو استخدم Reply.")
    ok, code = add_admin(uid)
    await state.clear()
    if ok:
        await msg.answer(f"✅ تمت الترقية: {_mention(uid)}", parse_mode=ParseMode.HTML)
    elif code == "already":
        await msg.answer("ℹ️ هو أدمن بالفعل.")
    else:
        await msg.answer("❌ فشل الإضافة.")
    # تحديث اللوحة
    await msg.answer(_list_text(), parse_mode=ParseMode.HTML,
                     reply_markup=_kb_main(msg.from_user.id in OWNERS))

# ================ remove ================
@router.callback_query(F.data == "admacc:del")
async def start_del(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in OWNERS:
        return await cb.answer("Owners only.", show_alert=True)
    await state.set_state(S.rem)
    await cb.message.answer("أرسل @username أو الـ ID، أو ردّ على رسالة الشخص لحذفه من الأدمن.")
    await cb.answer()

@router.message(S.rem)
async def on_del(msg: Message, state: FSMContext):
    if msg.from_user.id not in OWNERS:
        return
    uid = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        uid = int(msg.reply_to_message.from_user.id)
    else:
        uid = await _resolve_user_id(msg.bot, msg.text or "")
    if not uid:
        return await msg.reply("صيغة غير صحيحة.")
    ok, code = remove_admin(uid)
    await state.clear()
    if ok:
        await msg.answer(f"✅ تمت الإزالة: {_mention(uid)}", parse_mode=ParseMode.HTML)
    elif code == "owner_protected":
        await msg.answer("⚠️ لا يمكن إزالة المالك.")
    elif code == "not_found":
        await msg.answer("ℹ️ هذا المستخدم ليس أدمن.")
    else:
        await msg.answer("❌ فشل الإزالة.")
    await msg.answer(_list_text(), parse_mode=ParseMode.HTML,
                     reply_markup=_kb_main(msg.from_user.id in OWNERS))
