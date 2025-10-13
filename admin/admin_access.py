# admin/admin_access.py
from __future__ import annotations
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError

from lang import get_user_lang
from utils.admins import is_admin, get_owner_ids, add_admin, remove_admin, list_admins

router = Router(name="admin_access")

# فلتر ديناميكي بدل F.from_user.id.in_(ADMIN_IDS)
router.message.filter(F.chat.type == "private", F.from_user.func(lambda u: is_admin(u.id)))
router.callback_query.filter(F.message.chat.type == "private", F.from_user.func(lambda u: is_admin(u.id)))

ADMIN_ALERT_CHAT_ID = 0  # استخدم ENV من utils.rewards_notify لو عندك، أو اتركه 0

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
    rows = [[InlineKeyboardButton(text="📋 عرض القائمة", callback_data="admacc:list")]]
    if owner:
        rows.append([
            InlineKeyboardButton(text="➕ إضافة أدمن", callback_data="admacc:add"),
            InlineKeyboardButton(text="➖ إزالة أدمن", callback_data="admacc:del"),
        ])
    rows.append([InlineKeyboardButton(text="« رجوع", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _list_text() -> str:
    owners = set(get_owner_ids())
    owners_txt = ", ".join(_mention(x) for x in sorted(owners)) or "-"
    others = ", ".join(_mention(x) for x in sorted(set(list_admins()) - owners)) or "—"
    return f"👑 <b>Owners</b>: {owners_txt}\n🛡️ <b>Admins</b>: {others}"

class S(StatesGroup):
    add = State()
    rem = State()

@router.callback_query(F.data.in_({"admacc:open", "admacc:list"}))
async def open_panel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    owner = cb.from_user.id in set(get_owner_ids())
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
                     reply_markup=_kb_main(msg.from_user.id in set(get_owner_ids())))

@router.callback_query(F.data == "admacc:add")
async def start_add(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in set(get_owner_ids()):
        return await cb.answer("Owners only.", show_alert=True)
    await state.set_state(S.add)
    await cb.message.answer("أرسل @username أو الـ ID، أو ردّ على رسالة الشخص ثم اكتب أي شيء.")
    await cb.answer()

@router.message(S.add)
async def on_add(msg: Message, state: FSMContext):
    if msg.from_user.id not in set(get_owner_ids()):
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
    await msg.answer(_list_text(), parse_mode=ParseMode.HTML,
                     reply_markup=_kb_main(msg.from_user.id in set(get_owner_ids())))

@router.callback_query(F.data == "admacc:del")
async def start_del(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in set(get_owner_ids()):
        return await cb.answer("Owners only.", show_alert=True)
    await state.set_state(S.rem)
    await cb.message.answer("أرسل @username أو الـ ID، أو ردّ على رسالة الشخص لحذفه من الأدمن.")
    await cb.answer()

@router.message(S.rem)
async def on_del(msg: Message, state: FSMContext):
    if msg.from_user.id not in set(get_owner_ids()):
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
                     reply_markup=_kb_main(msg.from_user.id in set(get_owner_ids())))
