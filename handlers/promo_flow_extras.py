# handlers/promo_flow_extras.py
from __future__ import annotations

import os, re, time, json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InputFile
from aiogram.filters import StateFilter, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.promo_sub_store import find_request, update_request, PROMO_MIN_VIEWS
from lang import get_user_lang
import tempfile

REAPPLY_COOLDOWN_SECS = int(os.getenv("PROMO_REAPPLY_COOLDOWN", "43200"))  # 12h

class RegState(StatesGroup):
    enter_id = State()

router = Router(name="promo_flow_extras")

# ───────────────────────────── Admins ─────────────────────────────
ADMIN_IDS = [
    int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID",""))
    .replace(";",",").split(",") if x.strip().isdigit()
]
def _is_admin(i: int) -> bool: return i in set(ADMIN_IDS or [])


# تقبّل uid أو كود لغة
def _L(x, ar: str, en: str) -> str:
    lang = get_user_lang(x) if isinstance(x, int) else (x or "en")
    return ar if str(lang).startswith("ar") else en

# ───────────────────────────── Helpers ─────────────────────────────
GAMES = ["8BP", "Carrom", "Soccer"]

def _row_buttons(options: list[str], prefix: str, columns: int = 3):
    kb = InlineKeyboardBuilder()
    for o in options:
        kb.button(text=o, callback_data=f"{prefix}:{o}")
    kb.adjust(columns)
    return kb.as_markup()

def _chat_on(rec: dict) -> bool: return bool(rec.get("chat_on"))
def _now() -> int: return int(time.time())
def _is_locked(rec: dict) -> bool:
    return bool(rec.get("locked")) or str(rec.get("status")) in {"ready_for_activation","activated"}

# الخطط المتاحة للتفعيل
PLANS = {
    "3d":"3 أيام","10d":"10 أيام","30d":"30 يوم","90d":"90 يوم","180d":"180 يوم",
}

def activation_kb(uid: int, game: str):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ تفعيل 3 أيام",  callback_data=f"admin:activate:{uid}:{game}:3d"),
        InlineKeyboardButton(text="✅ تفعيل 10 أيام", callback_data=f"admin:activate:{uid}:{game}:10d"),
        InlineKeyboardButton(text="✅ تفعيل 30 يوم",  callback_data=f"admin:activate:{uid}:{game}:30d"),
    )
    kb.row(
        InlineKeyboardButton(text="✅ تفعيل 90 يوم",  callback_data=f"admin:activate:{uid}:{game}:90d"),
        InlineKeyboardButton(text="✅ تفعيل 180 يوم", callback_data=f"admin:activate:{uid}:{game}:180d"),
        InlineKeyboardButton(text="❌ رفض",           callback_data=f"admin:promo:reject:{uid}"),
    )
    return kb.as_markup()

def _user_chat_kb(uid: int):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_L(uid, "🔒 إنهاء المحادثة", "🔒 End chat"),
                             callback_data="user:chat:close"),
        InlineKeyboardButton(text=_L(uid, "✅ تمّ / شكراً", "✅ Done / Thanks"),
                             callback_data="user:chat:done"),
    )
    return kb.as_markup()

USER_ACK_COOLDOWN = 45  # ثواني بين كل رسالة تأكيد للمستخدم كي لا نُزعجه

async def _safe_edit_rm(cb: CallbackQuery):
    try: await cb.message.edit_reply_markup(None)
    except Exception: pass

async def _ask_once(msg_or_cb, uid: int, key: str, text: str, **kw):
    rec = find_request(uid) or {}
    if rec.get("last_prompt") == key and _now() - int(rec.get("last_prompt_ts") or 0) < 90:
        return
    update_request(uid, last_prompt=key, last_prompt_ts=_now())
    if isinstance(msg_or_cb, CallbackQuery):
        return await msg_or_cb.message.answer(text, **kw)
    return await msg_or_cb.answer(text, **kw)

def _fmt_eta(seconds: int, lang: str) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if (lang or "en").startswith("ar"):
        parts = []
        if h: parts.append(f"{h} ساعة")
        if m: parts.append(f"{m} دقيقة")
        if not parts: parts = ["أقل من دقيقة"]
        return " و ".join(parts)
    else:
        parts = []
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        if not parts: parts = ["<1m"]
        return " ".join(parts)

def _cooldown_left(rec: dict) -> int:
    if (rec.get("status") or "") != "rejected":
        return 0
    t0 = int(rec.get("rejected_at") or rec.get("updated_at") or 0)
    left = REAPPLY_COOLDOWN_SECS - max(0, _now() - t0)
    return max(0, left)

# ───────────────────────────── لوحة أدمن للمراجعة ─────────────────────────────
def admin_menu_kb(uid: int):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Approve",     callback_data=f"admin:promo:approve:{uid}"),
        InlineKeyboardButton(text="✍️ Ask details", callback_data=f"admin:promo:ask:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text="💬 Open chat",   callback_data=f"admin:promo:chat:{uid}"),
        InlineKeyboardButton(text="🔒 Close chat",  callback_data=f"admin:promo:closechat:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text="⛔ Ban",          callback_data=f"admin:promo:ban:{uid}"),
        InlineKeyboardButton(text="✅ Unban",        callback_data=f"admin:promo:unban:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text="🧊 Freeze",       callback_data=f"admin:promo:freeze:{uid}"),
        InlineKeyboardButton(text="♻️ Unfreeze",     callback_data=f"admin:promo:unfreeze:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text="❌ Reject",      callback_data=f"admin:promo:reject:{uid}"),
    )
    return kb.as_markup()

# ───────────────────────────── SMART CHAT: قوالب + سجل + أزرار سريعة ─────────────────────────────
SMART_TEMPLATES = {
    "ask_url": {
        "ar":"📎 أرسل رابط المنشور/الفيديو (عام).",
        "en":"📎 Please send the public post/video URL.",
    },
    "ask_shot": {
        "ar":"🖼️ أرسل لقطة شاشة تُظهر عدد المشاهدات والتاريخ.",
        "en":"🖼️ Send a screenshot showing views & date.",
    },
    "ask_id": {
        "ar":"🔢 أرسل Snake ID (أرقام فقط).",
        "en":"🔢 Send your Snake ID (digits only).",
    },
    "busy": {
        "ar":"⌛ حاضر، سأتواصل معك قريبًا.",
        "en":"⌛ Got it — I’ll be with you shortly.",
    },
    "thanks": {
        "ar":"✅ استلمت رسالتك، شكرًا لك.",
        "en":"✅ Received, thank you.",
    },
    "close": {
        "ar":"🔒 تم إغلاق المحادثة. إن احتجت شيئًا افتح تذكرة جديدة.",
        "en":"🔒 Chat closed. If you need anything, open a new ticket.",
    },
}

def _block_reason_txt(uid: int, kind: str, reason: str | None):
    if kind == "ban":
        return _L(uid,
            f"❌ تم حظر حسابك عن المشاركة.{f' السبب: {reason}' if reason else ''}",
            f"❌ You are banned from participating.{f' Reason: {reason}' if reason else ''}")
    else:
        return _L(uid,
            f"🧊 تم تجميد حسابك مؤقتًا.{f' السبب: {reason}' if reason else ''}",
            f"🧊 Your account is temporarily frozen.{f' Reason: {reason}' if reason else ''}")

def _t(uid: int, key: str) -> str:
    lang = get_user_lang(uid) or "en"
    return SMART_TEMPLATES[key]["ar" if str(lang).startswith("ar") else "en"]

def _chat_kb(uid: int):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🔗 URL",      callback_data=f"admin:chat:quick:{uid}:ask_url"),
        InlineKeyboardButton(text="🖼️ Shot",     callback_data=f"admin:chat:quick:{uid}:ask_shot"),
        InlineKeyboardButton(text="🆔 ID",       callback_data=f"admin:chat:quick:{uid}:ask_id"),
    )
    kb.row(
        InlineKeyboardButton(text="✅ Thanks",    callback_data=f"admin:chat:quick:{uid}:thanks"),
        InlineKeyboardButton(text="⌛ Busy",      callback_data=f"admin:chat:quick:{uid}:busy"),
        InlineKeyboardButton(text="🔒 Close",     callback_data=f"admin:chat:close:{uid}"),
    )
    return kb.as_markup()

def _push_history(uid: int, role: str, content: str | None, kind: str = "text", file_id: str | None = None):
    rec = find_request(uid) or {}
    hist = rec.get("chat_history") or []
    hist.append({"t":_now(), "role":role, "kind":kind, "text":content or "", "file_id":file_id or ""})
    if len(hist) > 200:
        hist = hist[-200:]
    update_request(uid, chat_history=hist)

def _admin_chat_kb(uid: int):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✍️ Ask details", callback_data=f"admin:promo:ask:{uid}"),
        InlineKeyboardButton(text="🔒 Close chat",  callback_data=f"admin:promo:closechat:{uid}"),
    )
    return kb.as_markup()

def _reset_after_unban(uid: int):
    update_request(
        uid,
        status="none",
        unbanned_at=_now(),
        rejected_at=None,
        requested_at=None,
        locked=False,
        chat_on=False,
        chat_admin=None,
        updated_at=_now(),
    )

# ───────────────────── NEW: ملتقط روابط (يحفظ post_url ويشعر الأدمن) ─────────────────────
def _looks_like_url(s: str) -> bool:
    if not s:
        return False
    s = s.strip()
    if not s.lower().startswith(("http://", "https://")):
        return False
    # بسيط: وجود نقطة وعدم وجود مسافات
    return ("." in s) and (" " not in s)

@router.message(F.chat.type == "private", F.text.regexp(r"https?://"))
async def promo_capture_url(msg: Message):
    """
    يلتقط أي رسالة تحتوي رابط من المستخدم في الخاص أثناء مرحلة الطلب
    (قبل التفعيل)، ويحفظها كـ post_url ويغيّر الحالة إلى awaiting_admin،
    ثم يرسل إشعارًا للأدمنين مع كيبورد المراجعة.
    يتجاهل الرسالة إذا كانت محادثة الأدمن مفتوحة (chat_on).
    """
    uid = msg.from_user.id
    rec = find_request(uid) or {}

    # لو الشات مع الأدمن مفتوح، لا نتدخل (حتى تمر للـ relay)
    if _chat_on(rec):
        return

    status = str(rec.get("status") or "")
    # حالات مؤهلة لالتقاط الرابط
    if status in {"banned", "activated"}:
        return

    # لا نكرر إذا كان محفوظًا مسبقًا
    if rec.get("post_url"):
        return

    text = (msg.text or "").strip()
    if not _looks_like_url(text):
        return

    # احفظ الرابط وادفعه للمراجعة
    update_request(
        uid,
        post_url=text,
        status="awaiting_admin",
        requested_at=_now(),
        updated_at=_now(),
    )

    # تأكيد للمستخدم
    try:
        await msg.reply(
            _L(uid,
               "📨 تم استلام الرابط. سيتم مراجعته من الإدارة وسنخبرك بالنتيجة.",
               "📨 Got the URL. Admins will review it and we’ll notify you."),
            disable_web_page_preview=True
        )
    except Exception:
        pass

    # إشعار الأدمنين
    try:
        un = f"@{msg.from_user.username}" if msg.from_user.username else "-"
        platform = rec.get("platform", "-")
        notice = (
            "🔔 طلب جديد للمراجعة\n"
            f"user_id={uid}\n"
            f"username={un}\n"
            f"platform={platform}\n"
            f"post_url={text}\n"
            "status=awaiting_admin"
        )
        for aid in ADMIN_IDS:
            try:
                await msg.bot.send_message(aid, notice, reply_markup=admin_menu_kb(uid))
            except Exception:
                try:
                    await msg.bot.send_message(aid, notice)
                except Exception:
                    pass
    except Exception:
        pass

# ───────────────────────────── حظر/تجميد (أزرار الأدمن) ─────────────────────────────
@router.callback_query(F.data.regexp(r"^admin:promo:(ban|unban|freeze|unfreeze):(\d+)$"))
async def admin_block_ops(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)

    action, uid_s = cb.data.split(":")[2], cb.data.split(":")[3]
    uid = int(uid_s)

    if action == "ban":
        update_request(uid, status="banned", banned_at=_now(), frozen=False)
        try:
            await cb.bot.send_message(uid, _block_reason_txt(uid, "ban", None))
        except Exception:
            pass
        await cb.answer("User banned")

    elif action == "unban":
        update_request(
            uid,
            status="none",
            unbanned_at=_now(),
            rejected_at=None,
            requested_at=None,
            locked=False,
            chat_on=False,
            chat_admin=None,
            updated_at=_now(),
        )
        try:
            await cb.bot.send_message(
                uid,
                _L(uid, "✅ تم رفع الحظر. يمكنك التقديم من جديد.", "✅ Ban lifted. You can apply again.")
            )
        except Exception:
            pass
        await cb.answer("User unbanned & reset")

    elif action == "freeze":
        update_request(uid, frozen=True, frozen_at=_now())
        try:
            await cb.bot.send_message(uid, _block_reason_txt(uid, "freeze", None))
        except Exception:
            pass
        await cb.answer("User frozen")

    else:  # unfreeze
        update_request(uid, frozen=False, unfrozen_at=_now())
        try:
            await cb.bot.send_message(uid, _L(uid, "♻️ تم رفع التجميد. يمكنك المتابعة.", "♻️ Freeze removed. You can continue."))
        except Exception:
            pass
        await cb.answer("User unfrozen")

    try:
        await cb.message.edit_reply_markup(admin_menu_kb(uid))
    except Exception:
        pass

# ───────────────────────────── أوامر إدارية سريعة ─────────────────────────────
@router.message(Command("promo_view"))
async def promo_view(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.reply("usage: /promo_view <uid>")
    uid = int(parts[1])
    rec = find_request(uid) or {}
    await msg.reply(
        "📄 Record\n"
        + "\n".join(f"{k}={v}" for k,v in rec.items()),
        disable_web_page_preview=True
    )

@router.message(Command("promo_ban"))
async def promo_ban(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.reply("usage: /promo_ban <uid> [reason]")
    uid = int(parts[1]); reason = parts[2] if len(parts) > 2 else None
    update_request(uid, status="banned", banned_at=_now(), frozen=False, ban_reason=reason)
    try: await msg.bot.send_message(uid, _block_reason_txt(uid, "ban", reason))
    except Exception: pass
    await msg.reply("✅ banned.")

@router.message(Command("promo_unban"))
async def promo_unban(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.reply("usage: /promo_unban <uid>")
    uid = int(parts[1])
    update_request(
        uid,
        status="none",
        unbanned_at=_now(),
        rejected_at=None,
        requested_at=None,
        locked=False,
        chat_on=False,
        chat_admin=None,
        updated_at=_now(),
    )
    try:
        await msg.bot.send_message(
            uid,
            _L(uid, "✅ تم رفع الحظر. يمكنك التقديم من جديد.", "✅ Ban lifted. You can apply again.")
        )
    except Exception:
        pass
    await msg.reply("✅ unbanned & reset.")

@router.message(Command("promo_freeze"))
async def promo_freeze(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.reply("usage: /promo_freeze <uid> [reason]")
    uid = int(parts[1]); reason = parts[2] if len(parts) > 2 else None
    update_request(uid, frozen=True, frozen_at=_now(), freeze_reason=reason)
    try: await msg.bot.send_message(uid, _block_reason_txt(uid, "freeze", reason))
    except Exception: pass
    await msg.reply("✅ frozen.")

@router.message(Command("promo_unfreeze"))
async def promo_unfreeze(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.reply("usage: /promo_unfreeze <uid>")
    uid = int(parts[1])
    update_request(uid, frozen=False, unfrozen_at=_now())
    try: await msg.bot.send_message(uid, _L(uid, "♻️ تم رفع التجميد. يمكنك المتابعة.", "♻️ Freeze removed. You can continue."))
    except Exception: pass
    await msg.reply("✅ unfrozen.")

# ───────────────────────────── فتح/إغلاق الشات ─────────────────────────────
@router.callback_query(F.data.regexp(r"^admin:promo:chat:(\d+)$"))
async def open_chat(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    try:
        uid = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer("Bad payload", show_alert=True)
    update_request(uid, chat_on=True, chat_admin=cb.from_user.id, chat_opened=_now())
    try:
        await cb.bot.send_message(
            uid,
            _L(uid,"💬 تم فتح محادثة مباشرة مع المشرف. يمكنك الرد هنا.",
                    "💬 A direct chat with the admin was opened. You can reply here."),
            reply_markup=_user_chat_kb(uid)
        )
    except Exception:
        pass
    try:
        await cb.message.answer(
            f"Opened chat with #{uid}. Use /say {uid} <message>",
            parse_mode=None,
            reply_markup=_admin_chat_kb(uid)
        )
    except Exception:
        pass
    await cb.answer("Chat opened ✔")

@router.callback_query(F.data.startswith("admin:promo:closechat:"))
async def close_chat(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid = int(cb.data.split(":")[-1])
    update_request(uid, chat_on=False, chat_admin=None)
    try:
        await cb.bot.send_message(uid, _t(uid, "close"))
    except Exception:
        pass
    await cb.answer("Chat closed.")

# رد سريع جاهز من كيبورد الأدمن
@router.callback_query(F.data.regexp(r"^admin:chat:quick:(\d+):([a-z_]+)$"))
async def admin_quick_reply(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _, _, _, uid_s, key = cb.data.split(":")
    uid = int(uid_s)
    rec = find_request(uid) or {}
    if not (_chat_on(rec) and int(rec.get("chat_admin") or 0) == cb.from_user.id):
        return await cb.answer("Chat not open.", show_alert=True)
    text = _t(uid, key)
    try:
        await cb.bot.send_message(uid, text)
        _push_history(uid, "admin", text)
    except Exception:
        pass
    await cb.answer("Sent ✓")

@router.callback_query(F.data.regexp(r"^admin:chat:close:(\d+)$"))
async def admin_quick_close(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid = int(cb.data.split(":")[-1])
    update_request(uid, chat_on=False, chat_admin=None)
    try:
        await cb.bot.send_message(uid, _t(uid, "close"))
    except Exception:
        pass
    await cb.answer("Closed ✓")

# تدوين ملاحظة داخلية
@router.message(Command("note"))
async def admin_note(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return await msg.reply("usage: /note <uid> <text>")
    uid = int(parts[1]); note = parts[2]
    rec = find_request(uid) or {}
    notes = rec.get("admin_notes") or []
    notes.append({"t":_now(), "by":msg.from_user.id, "note":note})
    update_request(uid, admin_notes=notes)
    await msg.reply("📝 noted.")

# تصدير سجل الدردشة كملف JSON
@router.message(Command("exportchat"))
async def export_chat(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.reply("usage: /exportchat <uid>")
    uid = int(parts[1])
    rec = find_request(uid) or {}
    data = {"uid": uid, "history": rec.get("chat_history") or [], "notes": rec.get("admin_notes") or []}
    try:
        tmpdir = tempfile.gettempdir()
        path = os.path.join(tmpdir, f"chat_{uid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        await msg.reply_document(InputFile(path), caption=f"chat #{uid}")
    except Exception:
        await msg.reply("failed to export.")

# ───────────────────────────── Relay المستخدم → الأدمن (عند فتح الشات) ─────────────────────────────
@router.message(~StateFilter(RegState.enter_id), F.chat.type == "private")
async def user_to_admin_relay(msg: Message):
    uid = msg.from_user.id
    rec = find_request(uid) or {}
    if not (_chat_on(rec) and int(rec.get("chat_admin") or 0) > 0):
        return
    admin_id = int(rec.get("chat_admin"))
    try:
        un = f"@{msg.from_user.username}" if msg.from_user.username else "-"
        if msg.content_type == "text":
            text = f"👤 #{uid} ({un}):\n{msg.text}"
            await msg.bot.send_message(admin_id, text, reply_markup=_chat_kb(uid))
            _push_history(uid, "user", msg.text)
        elif msg.content_type == "photo":
            fid = msg.photo[-1].file_id
            await msg.bot.send_photo(admin_id, fid,
                                     caption=f"👤 #{uid} ({un}) sent a photo",
                                     reply_markup=_chat_kb(uid))
            _push_history(uid, "user", "[photo]", kind="photo", file_id=fid)
        else:
            await msg.bot.send_message(admin_id, f"👤 #{uid}: {msg.content_type}",
                                       reply_markup=_chat_kb(uid))
            _push_history(uid, "user", f"[{msg.content_type}]")
    except Exception:
        pass

    last_ack = int(rec.get("last_user_ack_ts") or 0)
    if _now() - last_ack >= USER_ACK_COOLDOWN:
        try:
            await msg.reply(
                _L(uid, "📨 تم إرسال رسالتك إلى المشرف. يرجى الانتظار.",
                         "📨 Your message was sent to the admin. Please wait."),
                reply_markup=_user_chat_kb(uid)
            )
            update_request(uid, last_user_ack_ts=_now())
        except Exception:
            pass

# إرسال رسالة يدوية من الأدمن
@router.message(Command("say"))
async def say_to_user(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return await msg.reply("usage: /say <uid> <message>")
    uid = int(parts[1]); txt = parts[2]
    rec = find_request(uid) or {}
    if not _chat_on(rec):
        return await msg.reply("chat is not open for this user.")
    try:
        await msg.bot.send_message(uid, txt, reply_markup=_user_chat_kb(uid))
        _push_history(uid, "admin", txt)
        await msg.reply("✅ sent.")
    except Exception:
        await msg.reply("⚠️ failed.")

# ───────────────────────────── Collect details after final approval ─────────────────────────────
async def start_user_details_flow(bot, uid: int):
    await bot.send_message(
        uid,
        _L(uid, "✅ تمت الموافقة النهائية. اختر اللعبة:", "✅ Final approval. Choose the game:"),
        reply_markup=_row_buttons(GAMES, "user:game")
    )

@router.callback_query(F.data == "user:chat:close")
async def user_close_chat(cb: CallbackQuery):
    uid = cb.from_user.id
    rec = find_request(uid) or {}
    admin_id = int(rec.get("chat_admin") or 0)
    update_request(uid, chat_on=False, chat_admin=None)
    try:
        await cb.message.answer(_L(uid, "🔒 تم إنهاء المحادثة. شكراً لك.",
                                         "🔒 Chat ended. Thank you."))
    except Exception:
        pass
    if admin_id:
        try:
            await cb.bot.send_message(admin_id, f"ℹ️ User #{uid} closed the chat.")
        except Exception:
            pass
    await cb.answer()

@router.callback_query(F.data == "user:chat:done")
async def user_done_chat(cb: CallbackQuery):
    uid = cb.from_user.id
    rec = find_request(uid) or {}
    admin_id = int(rec.get("chat_admin") or 0)
    try:
        await cb.message.answer(_L(uid, "✅ شكرًا لك! سنبقى متاحين لأي استفسار.",
                                         "✅ Thanks! We're here if you need anything."),
                                reply_markup=_user_chat_kb(uid))
    except Exception:
        pass
    if admin_id:
        try:
            await cb.bot.send_message(admin_id, f"ℹ️ User #{uid} marked conversation as done.")
        except Exception:
            pass
    await cb.answer()

@router.callback_query(F.data.startswith("user:game"))
async def pick_game(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    rec = find_request(uid) or {}
    if _is_locked(rec) and rec.get("status") not in {"final_approved","ready_for_activation"}:
        return await cb.answer("الطلب مُقفل.", show_alert=True)
    if rec.get("snake_id"):
        await _safe_edit_rm(cb); return await cb.answer("تم استلام التفاصيل سابقًا.")
    game = cb.data.split(":")[-1]
    await state.update_data(game=game, plan="none")
    await state.set_state(RegState.enter_id)
    await _safe_edit_rm(cb)
    await _ask_once(cb, uid, "ask:id", _L(uid,"أرسل Snake ID (أرقام فقط):","Send your Snake ID (digits only):"))
    await cb.answer()

@router.message(StateFilter(RegState.enter_id))
async def get_snake_id(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩","0123456789")
    raw = raw.translate(trans)
    sid = re.sub(r"\D+","", raw)
    if not (3 <= len(sid) <= 18):
        return await msg.reply("الرجاء إدخال ID رقمي صحيح (3–18 خانة). أرسل الأرقام فقط.")
    data = await state.get_data()
    game = data.get("game") or "-"
    update_request(
        msg.from_user.id,
        game=game, snake_id=sid,
        status="ready_for_activation",
        details_submitted_at=_now(), locked=True
    )
    await msg.answer(_L(msg.from_user.id,
        "✅ تم استلام معرفك.\n⏳ انتظر التفعيل من قِبل المشرف، وسنرسل لك إشعارًا فور اكتماله.",
        "✅ Got your ID.\n⏳ Please wait for activation; we’ll notify you when it’s done."
    ))
    try:
        for aid in ADMIN_IDS:
            await msg.bot.send_message(
                aid,
                "🔔 طلب تفعيل جاهز\n"
                f"user_id={msg.from_user.id}\n"
                f"username=@{msg.from_user.username or '-'}\n"
                f"game={game}\n"
                f"snake_id={sid}\n"
                "status=ready_for_activation",
                reply_markup=activation_kb(msg.from_user.id, game)
            )
    except Exception:
        pass
    await state.clear()

@router.callback_query(F.data.startswith("admin:activate:"))
async def admin_activate(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    try:
        _, _, uid_s, game, plan = cb.data.split(":"); uid = int(uid_s)
    except Exception:
        return await cb.answer("Bad payload", show_alert=True)
    if plan not in PLANS:
        return await cb.answer("Unknown plan", show_alert=True)
    update_request(uid, status="activated", plan=plan, activated_at=_now(), activated_by=cb.from_user.id)
    try:
        pretty = PLANS[plan]
        await cb.bot.send_message(uid, _L(uid,
            f"🎉 تم تفعيل لعبتك ({game}) لمدة {pretty} ✅\nنتمنى لك تجربة ممتعة! لو واجهت أي مشكلة تواصل معنا.",
            f"🎉 Your game ({game}) was activated for {pretty} ✅\nEnjoy! Contact us if you face any issue."
        ))
    except Exception:
        pass
    await cb.answer("Activated ✔")
    try:
        await cb.message.edit_text((cb.message.text or "")+f"\n\n✅ تم التفعيل ({game}, {PLANS[plan]}).", reply_markup=None)
    except Exception:
        pass


