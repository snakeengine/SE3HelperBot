# admin/rewards_admin.py
from __future__ import annotations

import json, os, math, re
from pathlib import Path
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatType, ParseMode

from lang import t, get_user_lang
from utils.rewards_store import (
    ensure_user, get_points, add_points, set_blocked, is_blocked
)
from utils.rewards_notify import (
    notify_user_points, notify_user_set_points, notify_user_ban
)

router = Router(name="rewards_admin")

DATA = Path("data")
STORE_FILE = DATA / "rewards_store.json"
USERNAMES_CACHE = DATA / "rwd_usernames.json"  # {uid: "@uname" or ""}

# ========= أدوات مساعدة أساسية =========

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _load_json(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_json(p: Path, obj: dict):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass

def _all_user_ids() -> list[int]:
    d = _load_json(STORE_FILE)
    users = (d or {}).get("users") or d  # دعم الشكلين
    out = []
    if isinstance(users, dict):
        for k in users.keys():
            try:
                out.append(int(k))
            except Exception:
                continue
    return out

async def _username_of(bot, uid: int) -> str:
    # كاش محلي
    cache = _load_json(USERNAMES_CACHE)
    if str(uid) in cache:
        return cache[str(uid)] or ""
    uname = ""
    try:
        chat = await bot.get_chat(uid)
        if chat.type == ChatType.PRIVATE and chat.username:
            uname = f"@{chat.username}"
    except Exception:
        uname = ""
    cache[str(uid)] = uname
    _save_json(USERNAMES_CACHE, cache)
    return uname

async def _display_line(bot, uid: int) -> str:
    pts = 0
    try:
        pts = int(get_points(uid))
    except Exception:
        pts = 0
    uname = await _username_of(bot, uid)
    return f"{uid} · {pts}p · {uname or '-'}"

# ========= لوحة: قائمة المستخدمين + بحث =========

PAGE_SIZE = 12

def _kb_users(lang: str, items: list[tuple[int, str]], page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # زر البحث
    kb.button(text="🔎 " + t(lang, "rwdadm.search", "بحث"), callback_data="rwdadm:search")
    # المستخدمون
    for uid, label in items:
        kb.row(InlineKeyboardButton(text=label, callback_data=f"rwdadm:panel:{uid}"))
    # صفحات
    kb.row(InlineKeyboardButton(text=f"page {page}/{pages}", callback_data="rwdadm:list:noop"))
    if page > 1:
        kb.button(text="⬅️", callback_data=f"rwdadm:list:p:{page-1}")
    if page < pages:
        kb.button(text="➡️", callback_data=f"rwdadm:list:p:{page+1}")
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "admin.back", "رجوع"), callback_data="ah:rewards"))
    return kb.as_markup()

async def _render_users_list(cb_or_msg, page: int = 1):
    lang = _L(cb_or_msg.from_user.id)
    uids = sorted(set(_all_user_ids()))
    total = len(uids)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, pages))
    slice_ids = uids[(page-1)*PAGE_SIZE : page*PAGE_SIZE]

    items: list[tuple[int,str]] = []
    for uid in slice_ids:
        ensure_user(uid)
        items.append((uid, await _display_line(cb_or_msg.bot, uid)))

    title = t(lang, "rwdadm.users_list_title", "📋 قائمة المستخدمين")
    desc  = t(lang, "rwdadm.users_list_desc", "اضغط على المستخدم لفتح لوحة التحكم.")
    text  = f"<b>{title}</b>\n{desc}"

    kb = _kb_users(lang, items, page, pages)
    if isinstance(cb_or_msg, CallbackQuery):
        try:
            await cb_or_msg.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        await cb_or_msg.answer()
    else:
        await cb_or_msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)

@router.callback_query(F.data == "rwdadm:list:noop")
async def _noop(cb: CallbackQuery):
    await cb.answer()

@router.callback_query(F.data.startswith("rwdadm:list:p:"))
async def list_page(cb: CallbackQuery):
    page = int(cb.data.split(":")[-1])
    await _render_users_list(cb, page)

# ========= بحث =========

class SearchStates(StatesGroup):
    wait_query = State()

@router.callback_query(F.data == "rwdadm:search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    lang = _L(cb.from_user.id)
    await state.set_state(SearchStates.wait_query)
    tip = t(lang, "rwdadm.search_tip", "أرسل @username أو ID المستخدم للبحث.")
    await cb.message.answer("🔎 " + t(lang, "rwdadm.search", "بحث"))
    await cb.message.answer(tip)
    await cb.answer()

_username_re = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")

@router.message(SearchStates.wait_query)
async def search_collect(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    raw = (msg.text or "").strip()

    # ID مباشر
    if raw.isdigit():
        uid = int(raw)
        ensure_user(uid)
        await user_panel_open(msg, uid)
        await state.clear()
        return

    # @username
    if _username_re.match(raw):
        uname = raw.lstrip("@")
        try:
            chat = await msg.bot.get_chat(f"@{uname}")
            if chat.type == ChatType.PRIVATE:
                ensure_user(int(chat.id))
                await user_panel_open(msg, int(chat.id))
                await state.clear()
                return
        except Exception:
            pass
        await msg.reply(t(lang, "rwdadm.username_not_found",
                          "لم أستطع العثور على مستخدم بهذا المعرف. تأكد أنه بدأ محادثة مع البوت."))
        return

    await msg.reply(t(lang, "rwdadm.search_invalid", "أرسل @username صحيحًا أو ID رقمي."))

# ========= لوحة مستخدم =========

def _kb_user_panel(lang: str, uid: int, pts: int, banned: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # زيادات/نواقص سريعة
    for delta in (10, 50, 100):
        kb.button(text=f"+{delta}", callback_data=f"rwdadm:grant:{uid}:{delta}")
    for delta in (10, 50, 100):
        kb.button(text=f"-{delta}", callback_data=f"rwdadm:grant:{uid}:-{delta}")
    kb.adjust(3, 3)

    # تعيين/تصفير/إشعار
    kb.row(
        InlineKeyboardButton(text=t(lang, "rwdadm.set_points", "تعيين رصيد"), callback_data=f"rwdadm:set:{uid}"),
        InlineKeyboardButton(text=t(lang, "rwdadm.zero_points", "تصفير"),      callback_data=f"rwdadm:zero:{uid}"),
    )
    kb.row(InlineKeyboardButton(text=t(lang, "rwdadm.notify", "إشعار المستخدم"), callback_data=f"rwdadm:notify:{uid}"))

    # حظر / إلغاء
    if banned:
        kb.row(InlineKeyboardButton(text="✅ " + t(lang, "rwdadm.unban", "إلغاء الحظر"), callback_data=f"rwdadm:unban:{uid}"))
    else:
        kb.row(InlineKeyboardButton(text="🚫 " + t(lang, "rwdadm.ban", "حظر المستخدم"), callback_data=f"rwdadm:ban:{uid}"))

    # حذف من قاعدة الجوائز
    kb.row(InlineKeyboardButton(text="🗑 " + t(lang, "rwdadm.delete_user", "حذف من قاعدة الجوائز"), callback_data=f"rwdadm:del:{uid}"))

    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "admin.back", "رجوع"), callback_data="rwdadm:list:p:1"))
    return kb.as_markup()

async def user_panel_open(ev: Message | CallbackQuery, uid: int):
    lang = _L(ev.from_user.id)
    ensure_user(uid)
    pts = int(get_points(uid))
    banned = bool(is_blocked(uid))

    uname = await _username_of(ev.bot, uid)
    head  = t(lang, "rwdadm.user_title", "لوحة مستخدم") + f" — {uname or uid}"
    line1 = t(lang, "rwdadm.user_points", "النقاط") + f": <b>{pts}</b>"
    line2 = t(lang, "rwdadm.user_status", "الحالة") + (": 🚫" if banned else ": ✅")
    text  = f"<b>{head}</b>\n{line1}\n{line2}"

    kb = _kb_user_panel(lang, uid, pts, banned)
    if isinstance(ev, CallbackQuery):
        try:
            await ev.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        await ev.answer()
    else:
        await ev.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

@router.callback_query(F.data.startswith("rwdadm:panel:"))
async def open_panel_cb(cb: CallbackQuery):
    uid = int(cb.data.split(":")[-1])
    await user_panel_open(cb, uid)

# ========= إجراءات النقاط =========

@router.callback_query(F.data.startswith("rwdadm:grant:"))
async def grant_points(cb: CallbackQuery):
    parts = cb.data.split(":")
    uid = int(parts[2])
    delta = int(parts[3])
    ensure_user(uid)
    # طبّق
    add_points(uid, delta, reason="admin_grant")
    new_bal = int(get_points(uid))
    # إشعارات
    await notify_user_points(cb.bot, uid, delta, new_bal, actor_id=cb.from_user.id)
    await user_panel_open(cb, uid)

class SetStates(StatesGroup):
    wait_amount = State()
    wait_notify = State()

@router.callback_query(F.data.startswith("rwdadm:set:"))
async def set_points_start(cb: CallbackQuery, state: FSMContext):
    lang = _L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    await state.set_state(SetStates.wait_amount)
    await state.update_data(target_id=uid)
    await cb.message.answer(t(lang, "rwdadm.ask_amount", "أدخل الرصيد الجديد (عدد صحيح ≥ 0):"))
    await cb.answer()

@router.message(SetStates.wait_amount)
async def set_points_collect(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    raw = (msg.text or "").strip()
    if not raw.isdigit():
        await msg.reply(t(lang, "rwdadm.amount_invalid", "أدخل رقمًا صحيحًا (≥ 0)."))
        return
    new = int(raw)
    data = await state.get_data()
    uid = int(data["target_id"])
    ensure_user(uid)
    old = int(get_points(uid))
    delta = new - old
    if delta != 0:
        add_points(uid, delta, reason="admin_set")
    # إشعار
    await notify_user_set_points(msg.bot, uid, old, new, actor_id=msg.from_user.id)
    await state.clear()
    await user_panel_open(msg, uid)

@router.callback_query(F.data.startswith("rwdadm:zero:"))
async def zero_points(cb: CallbackQuery):
    uid = int(cb.data.split(":")[-1])
    ensure_user(uid)
    old = int(get_points(uid))
    if old != 0:
        add_points(uid, -old, reason="admin_zero")
    await notify_user_set_points(cb.bot, uid, old, 0, actor_id=cb.from_user.id)
    await user_panel_open(cb, uid)

# ========= حظر / إلغاء =========

@router.callback_query(F.data.startswith("rwdadm:ban:"))
async def ban_user(cb: CallbackQuery):
    uid = int(cb.data.split(":")[-1])
    set_blocked(uid, True)
    await notify_user_ban(cb.bot, uid, True, actor_id=cb.from_user.id)
    await user_panel_open(cb, uid)

@router.callback_query(F.data.startswith("rwdadm:unban:"))
async def unban_user(cb: CallbackQuery):
    uid = int(cb.data.split(":")[-1])
    set_blocked(uid, False)
    await notify_user_ban(cb.bot, uid, False, actor_id=cb.from_user.id)
    await user_panel_open(cb, uid)

# ========= إشعار يدوي =========

@router.callback_query(F.data.startswith("rwdadm:notify:"))
async def notify_start(cb: CallbackQuery, state: FSMContext):
    lang = _L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])
    await state.set_state(SetStates.wait_notify)
    await state.update_data(target_id=uid)
    await cb.message.answer(t(lang, "rwdadm.ask_notify", "أرسل نص الرسالة لإبلاغ المستخدم."))
    await cb.answer()

@router.message(SetStates.wait_notify)
async def notify_collect(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    data = await state.get_data()
    uid = int(data["target_id"])
    text = (msg.text or "").strip()
    if not text:
        await msg.reply(t(lang, "rwdadm.notify_empty", "النص فارغ."))
        return
    # إلى المستخدم
    try:
        await msg.bot.send_message(uid, text)
    except Exception:
        pass
    # للأدمن
    who = f"<a href='tg://user?id={uid}'>{uid}</a>"
    await msg.bot.send_message(msg.from_user.id, t(lang, "rwdadm.notify_sent", "✅ تم إرسال الإشعار."))
    from utils.rewards_notify import notify_admins
    await notify_admins(msg.bot, f"📣 <b>Manual notify</b>\n• User: {who}\n• By: <a href='tg://user?id={msg.from_user.id}'>{msg.from_user.id}</a>\n• Text: {text}")
    await state.clear()
    await user_panel_open(msg, uid)

# ========= حذف من قاعدة الجوائز =========

@router.callback_query(F.data.startswith("rwdadm:del:"))
async def delete_user(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])

    d = _load_json(STORE_FILE)
    users = d.get("users") or d
    if isinstance(users, dict):
        users.pop(str(uid), None)
        if "users" in d:
            d["users"] = users
        _save_json(STORE_FILE, d)

    # إعلام الأدمن
    from utils.rewards_notify import notify_admins
    who = f"<a href='tg://user?id={uid}'>{uid}</a>"
    await notify_admins(cb.bot, f"🗑 <b>User removed from rewards DB</b>\n• User: {who}\n• By: <a href='tg://user?id={cb.from_user.id}'>{cb.from_user.id}</a>")

    try:
        await cb.message.answer(t(lang, "rwdadm.deleted_done", "تم حذف المستخدم من قاعدة الجوائز."))
    except Exception:
        pass

    await _render_users_list(cb, 1)

# ========= الدخول: من زر لوحة الأدمن أو من أمر سلاش =========

@router.callback_query(F.data == "rwdadm:list")
@router.callback_query(F.data == "ah:rwd:list")
async def open_users_list(cb: CallbackQuery):
    await _render_users_list(cb, 1)

@router.message(Command("rewards_admin"))
async def cmd_rewards_admin(msg: Message):
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) == 2:
        arg = parts[1].strip()
        if arg.isdigit():
            await user_panel_open(msg, int(arg))
            return
    await _render_users_list(msg, 1)

# أوامر سريعة (سلاش)
@router.message(Command("r_grant"))
async def cmd_r_grant(msg: Message):
    # /r_grant <uid> <points>  (points قد تكون سالبة)
    try:
        _, uid_s, pts_s = msg.text.split(maxsplit=2)
        uid = int(uid_s); delta = int(pts_s)
    except Exception:
        return
    ensure_user(uid)
    add_points(uid, delta, reason="admin_grant_cmd")
    await notify_user_points(msg.bot, uid, delta, int(get_points(uid)), actor_id=msg.from_user.id)
    await msg.answer("✅")

@router.message(Command("r_setpts"))
async def cmd_r_setpts(msg: Message):
    try:
        _, uid_s, new_s = msg.text.split(maxsplit=2)
        uid = int(uid_s); new = int(new_s)
    except Exception:
        return
    ensure_user(uid)
    old = int(get_points(uid))
    add_points(uid, new - old, reason="admin_set_cmd")
    await notify_user_set_points(msg.bot, uid, old, new, actor_id=msg.from_user.id)
    await msg.answer("✅")

@router.message(Command("r_ban"))
async def cmd_r_ban(msg: Message):
    try:
        _, uid_s = msg.text.split(maxsplit=1)
        uid = int(uid_s)
    except Exception:
        return
    set_blocked(uid, True)
    await notify_user_ban(msg.bot, uid, True, actor_id=msg.from_user.id)
    await msg.answer("✅")

@router.message(Command("r_unban"))
async def cmd_r_unban(msg: Message):
    try:
        _, uid_s = msg.text.split(maxsplit=1)
        uid = int(uid_s)
    except Exception:
        return
    set_blocked(uid, False)
    await notify_user_ban(msg.bot, uid, False, actor_id=msg.from_user.id)
    await msg.answer("✅")

@router.message(Command("r_del"))
async def cmd_r_del(msg: Message):
    try:
        _, uid_s = msg.text.split(maxsplit=1)
        uid = int(uid_s)
    except Exception:
        return
    d = _load_json(STORE_FILE)
    users = d.get("users") or d
    if isinstance(users, dict):
        users.pop(str(uid), None)
        if "users" in d:
            d["users"] = users
        _save_json(STORE_FILE, d)
    from utils.rewards_notify import notify_admins
    who = f"<a href='tg://user?id={uid}'>{uid}</a>"
    await notify_admins(msg.bot, f"🗑 <b>User removed from rewards DB</b>\n• User: {who}\n• By: <a href='tg://user?id={msg.from_user.id}'>{msg.from_user.id}</a>")
    await msg.answer("✅")

@router.message(Command("r_notify"))
async def cmd_r_notify(msg: Message):
    # /r_notify <uid> <text...>
    try:
        _, uid_s, text = msg.text.split(maxsplit=2)
        uid = int(uid_s)
    except Exception:
        return
    try:
        await msg.bot.send_message(uid, text)
    except Exception:
        pass
    from utils.rewards_notify import notify_admins
    who = f"<a href='tg://user?id={uid}'>{uid}</a>"
    await notify_admins(msg.bot, f"📣 <b>Manual notify</b>\n• User: {who}\n• By: <a href='tg://user?id={msg.from_user.id}'>{msg.from_user.id}</a>\n• Text: {text}")
    await msg.answer("✅")
