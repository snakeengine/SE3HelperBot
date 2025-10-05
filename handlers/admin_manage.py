# handlers/admin_manage.py
from __future__ import annotations
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode

from utils.admins import is_admin, OWNERS, ADMIN_IDS, add_admin, remove_admin, list_admins

router = Router(name="admin_manage")
router.message.filter(F.chat.type == "private")  # أو اسمح بالقنوات الخاصة بك فقط

async def _resolve_user_id(bot, raw: str) -> int | None:
    raw = (raw or "").strip()
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

def _fmt_mention(uid: int) -> str:
    return f'<a href="tg://user?id={uid}">{uid}</a>'

@router.message(Command("admins"))
async def cmd_admins(m: Message):
    if not is_admin(m.from_user.id):
        return
    owners = ", ".join(_fmt_mention(x) for x in sorted(OWNERS)) or "-"
    others = ", ".join(_fmt_mention(x) for x in sorted(ADMIN_IDS - OWNERS)) or "—"
    await m.answer(
        f"👑 <b>Owners</b>: {owners}\n"
        f"🛡️ <b>Admins</b>: {others}",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("admin_add"))
async def cmd_admin_add(m: Message):
    # مسموح للـ OWNERS فقط
    if m.from_user.id not in OWNERS:
        return await m.reply("Admins only (owners).")

    arg = (m.text or "").split(maxsplit=1)
    uid = None

    # 1) Reply على رسالة الشخص
    if m.reply_to_message and m.reply_to_message.from_user:
        uid = int(m.reply_to_message.from_user.id)
    # 2) أو تمرير رقم/يوزر
    elif len(arg) == 2:
        uid = await _resolve_user_id(m.bot, arg[1])

    if not uid:
        return await m.reply("استخدم:\n• رد على رسالة الشخص ثم /admin_add\n• أو /admin_add 123456 أو /admin_add @username")

    ok, code = add_admin(uid)
    if ok:
        return await m.answer(f"✅ تم ترقية {_fmt_mention(uid)} إلى أدمن.", parse_mode=ParseMode.HTML)
    if code == "already":
        return await m.answer("ℹ️ هو أدمن بالفعل.")
    await m.answer("❌ لم تنجح العملية.")

@router.message(Command("admin_del"))
async def cmd_admin_del(m: Message):
    if m.from_user.id not in OWNERS:
        return await m.reply("Admins only (owners).")

    arg = (m.text or "").split(maxsplit=1)
    uid = None

    if m.reply_to_message and m.reply_to_message.from_user:
        uid = int(m.reply_to_message.from_user.id)
    elif len(arg) == 2:
        uid = await _resolve_user_id(m.bot, arg[1])

    if not uid:
        return await m.reply("استخدم:\n• رد على رسالة الشخص ثم /admin_del\n• أو /admin_del 123456 أو /admin_del @username")

    ok, code = remove_admin(uid)
    if ok:
        return await m.answer(f"✅ تمت إزالة {_fmt_mention(uid)} من الأدمن.", parse_mode=ParseMode.HTML)
    if code == "owner_protected":
        return await m.answer("⚠️ لا يمكنك إزالة المالك (محمي).")
    if code == "not_found":
        return await m.answer("ℹ️ هذا المستخدم ليس أدمن.")
    await m.answer("❌ لم تنجح العملية.")
