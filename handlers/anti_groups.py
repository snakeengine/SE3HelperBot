# handlers/anti_groups.py
from __future__ import annotations
import os
import logging
from aiogram import Router
from aiogram.types import ChatMemberUpdated
from aiogram.enums import ChatType, ChatMemberStatus

router = Router(name="anti_groups")

# قناة وحيدة مسموح بوجود البوت فيها (اختياري)
_ALLOWED_CHANNEL_ID = -1001947565627

# تفعيل/تعطيل تنبيهات الأدمن
_ADMIN_NOTIFY = os.getenv("ADMIN_NOTIFY", "1").strip().lower() not in {"0", "false", "no"}

def _load_admin_ids() -> list[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: list[int] = []
    for p in str(raw).split(","):
        p = p.strip()
        if p.isdigit():
            ids.append(int(p))
    if not ids:
        ids = [7360982123,8371697148]
    return ids

ADMIN_IDS = _load_admin_ids()

async def _notify_admins(bot, text: str):
    if not _ADMIN_NOTIFY:
        return
    for uid in ADMIN_IDS:
        try:
            await bot.send_message(uid, text, disable_web_page_preview=True)
        except Exception as e:
            logging.warning(f"[GUARD] notify admin {uid} failed: {e}")

def _chat_kind_label(chat_type: ChatType) -> str:
    m = {
        ChatType.GROUP: "group",
        ChatType.SUPERGROUP: "supergroup",
        ChatType.CHANNEL: "channel",
    }
    return m.get(chat_type, str(chat_type.value if hasattr(chat_type, "value") else chat_type))

def _chat_public_link(ev: ChatMemberUpdated) -> str | None:
    """
    يرجّع رابط يمكن النقر عليه إن توفر:
    - لو القروب/القناة لها اسم مستخدم عام -> https://t.me/username
    - لو الدخول تم عبر دعوة -> invite_link من التحديث نفسه
    وإلا يرجّع None (قروبات خاصة بدون رابط عام).
    """
    chat = ev.chat
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}"
    try:
        inv = ev.invite_link
        if inv and getattr(inv, "invite_link", None):
            return inv.invite_link
    except Exception:
        pass
    return None

@router.my_chat_member()
async def guard_my_chat_member(event: ChatMemberUpdated):
    """
    يمنع إضافة البوت للقروبات/القنوات، ويغادر فورًا ويرسل تنبيهًا.
    يستثني قناة واحدة محددة بـ ADMIN_CHANNEL_ID (اختياري).
    """
    chat = event.chat
    bot = event.bot

    # في الخاص: تجاهل
    if chat.type == ChatType.PRIVATE:
        return

    # سماح لقناة واحدة فقط (اختياري)
    if _ALLOWED_CHANNEL_ID and chat.id == _ALLOWED_CHANNEL_ID:
        return

    # الحالة الجديدة للبوت داخل الدردشة
    try:
        status = event.new_chat_member.status
    except Exception:
        status = None

    if status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        chat_kind = _chat_kind_label(chat.type)
        chat_title = (getattr(chat, "title", "") or "").strip()
        link = _chat_public_link(event)

        inviter = event.from_user
        inviter_line = ""
        if inviter:
            name = (inviter.full_name or "Unknown").strip()
            uname = f"@{inviter.username}" if inviter.username else ""
            # ذكر قابل للنقر حتى بدون username
            mention = f'<a href="tg://user?id={inviter.id}">{name}</a>'
            inviter_line = f"\n👤 بواسطة: {mention} {uname} | ID: <code>{inviter.id}</code>"

        link_line = f"\n🔗 الرابط: {link}" if link else ""

        try:
            await bot.leave_chat(chat.id)
            logging.info(f"[GUARD] Left {chat_kind} {chat.id} (title={chat_title!r})")
            await _notify_admins(
                bot,
                (
                    "🚫 تم منع إضافة البوت إلى مجموعة/قناة وغادر تلقائيًا.\n"
                    f"🏷️ النوع: <b>{chat_kind}</b>\n"
                    f"📛 العنوان: <b>{chat_title}</b>\n"
                    f"🆔 Chat ID: <code>{chat.id}</code>"
                    f"{link_line}"
                    f"{inviter_line}"
                )
            )
        except Exception as e:
            logging.warning(f"[GUARD] leave_chat failed for {chat.id}: {e}")
            await _notify_admins(
                bot,
                (
                    "⚠️ محاولة منع إضافة البوت لكن حدث خطأ أثناء الخروج.\n"
                    f"🏷️ النوع: <b>{chat_kind}</b>\n"
                    f"📛 العنوان: <b>{chat_title}</b>\n"
                    f"🆔 Chat ID: <code>{chat.id}</code>"
                    f"{link_line}\n"
                    f"🧯 الخطأ: <code>{e}</code>"
                    f"{inviter_line}"
                )
            )
