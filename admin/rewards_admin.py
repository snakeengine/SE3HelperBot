from __future__ import annotations

# admin/rewards_admin.py


import json, os, math, re
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatType, ParseMode
from utils.user_resolver import resolve_user_id  # أعلى الملف

from lang import t, get_user_lang
from utils.rewards_store import (
    DATA_DIR,
    ensure_user, get_points, add_points, set_blocked, is_blocked, list_blocked_users
)
from utils.rewards_notify import (
    notify_user_points, notify_user_set_points,
    notify_user_ban, notify_user_unban
)

router = Router(name="rewards_admin")

# ----------------- مساعدة عامة -----------------
# نخلي التخزين متوافق مع utils.rewards_store (users.json)
STORE_FILE = DATA_DIR / "users.json"
DATA = Path("data")
USERNAMES_CACHE = DATA / "rwd_usernames.json"  # {uid: "@uname" or ""}

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
    """
    يقرأ نفس ملف التخزين المستخدم في utils.rewards_store: users.json
    الهيكل: { "12345": {...}, "67890": {...} }
    """
    try:
        if not STORE_FILE.exists():
            return []
        d = json.loads(STORE_FILE.read_text(encoding="utf-8")) or {}
        if isinstance(d, dict):
            out = []
            for k in d.keys():
                try:
                    out.append(int(k))
                except Exception:
                    continue
            return out
    except Exception:
        pass
    return []

async def _username_of(bot, uid: int) -> str:
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

# ================= قائمة المحظورين =================
BLOCKED_PAGE_SIZE = 10

def _blocked_page_kb(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"rwdadm:blocked:p:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}", callback_data=f"rwdadm:blocked:p:{page}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"rwdadm:blocked:p:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ رجوع", callback_data="ah:rewards"))
    return kb

async def _render_blocked_page(cb: CallbackQuery, page: int):
    lang = _L(cb.from_user.id)
    offset = page * BLOCKED_PAGE_SIZE
    items, total = list_blocked_users(offset=offset, limit=BLOCKED_PAGE_SIZE)

    # لا يوجد محظورون
    if total == 0:
        txt = t(lang, "rwdadm.blocked.empty", "لا يوجد مستخدمون محظورون حاليًا.")
        try:
            await cb.message.edit_text(txt, reply_markup=_blocked_page_kb(0, False, False).as_markup())
        except Exception:
            await cb.message.answer(txt, reply_markup=_blocked_page_kb(0, False, False).as_markup())
        await cb.answer()
        return

    # بناء النص والأزرار
    lines = [
        t(lang, "rwdadm.blocked.title", "🚫 قائمة المحظورين") +
        f"\n{t(lang,'rwdadm.total','الإجمالي')}: {total}"
    ]
    kb = InlineKeyboardBuilder()
    for uid, row in items:
        pts = int((row or {}).get("points", 0))
        warns = int((row or {}).get("warns", 0))
        lines.append(f"\n• <b>{uid}</b> — {t(lang,'rwdadm.points','النقاط')}: {pts} | {t(lang,'rwdadm.warns','تحذيرات')}: {warns}")
        kb.row(
            InlineKeyboardButton(text=t(lang, "rwdadm.open_panel", "فتح لوحة 🧩"), callback_data=f"rwdadm:panel:{uid}"),
            InlineKeyboardButton(text=t(lang, "rwdadm.unban_btn", "رفع الحظر ✅"), callback_data=f"rwdadm:unban:{uid}"),
        )

    has_prev = offset > 0
    has_next = (offset + BLOCKED_PAGE_SIZE) < total
    nav_kb = _blocked_page_kb(page, has_prev, has_next)
    for row in nav_kb.export():
        kb.row(*row)

    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)
    await cb.answer()

@router.callback_query(F.data == "ah:rwd:blocked")
async def ah_rwd_blocked(cb: CallbackQuery):
    """فتح الصفحة الأولى من قائمة المحظورين من لوحة الجوائز."""
    await _render_blocked_page(cb, 0)

@router.callback_query(F.data.startswith("rwdadm:blocked:p:"))
async def rwd_blocked_list(cb: CallbackQuery):
    """ترقيم صفحات قائمة المحظورين."""
    try:
        page = int(cb.data.split(":")[-1])
    except Exception:
        page = 0
    await _render_blocked_page(cb, page)

async def _refresh_blocked_current_page(cb: CallbackQuery):
    """يحاول استخراج الصفحة الحالية من كيبورد القائمة وإعادة عرضها."""
    try:
        for row in (cb.message.reply_markup.inline_keyboard or []):
            for btn in row:
                data = getattr(btn, "callback_data", "") or ""
                if data.startswith("rwdadm:blocked:p:"):
                    page = int(data.split(":")[-1])
                    await _render_blocked_page(cb, page)
                    return
    except Exception:
        pass

# ================= قائمة المستخدمين والبحث =================
PAGE_SIZE = 12

def _kb_users(lang: str, items: list[tuple[int, str]], page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 " + t(lang, "rwdadm.search", "بحث"), callback_data="rwdadm:search")
    for uid, label in items:
        kb.row(InlineKeyboardButton(text=label, callback_data=f"rwdadm:panel:{uid}"))
    kb.row(InlineKeyboardButton(text=f"page {page}/{pages}", callback_data="rwdadm:list:noop"))
    if page > 1:
        kb.button(text="⬅️", callback_data=f"rwdadm:list:p:{page-1}")
    if page < pages:
        kb.button(text="➡️", callback_data=f"rwdadm:list:p:{page+1}")
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "admin.back", "رجوع"), callback_data="ah:rewards"))
    return kb.as_markup()

async def _render_users_list(cb_or_msg: Message | CallbackQuery, page: int = 1):
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

# ---- بحث
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
    uid = await resolve_user_id(msg.bot, raw)
    if uid:
        ensure_user(uid)
        await user_panel_open(msg, int(uid))
        await state.clear()
        return
    await msg.reply(
        t(lang, "rwdadm.username_not_found",
          "لم أستطع العثور على مستخدم بهذا المعرف. تأكد أنه بدأ محادثة مع البوت.")
    )



# ================= لوحة مستخدم =================
def _kb_user_panel(lang: str, uid: int, pts: int, banned: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for delta in (10, 50, 100):
        kb.button(text=f"+{delta}", callback_data=f"rwdadm:grant:{uid}:{delta}")
    for delta in (10, 50, 100):
        kb.button(text=f"-{delta}", callback_data=f"rwdadm:grant:{uid}:-{delta}")
    kb.adjust(3, 3)

    kb.row(
        InlineKeyboardButton(text=t(lang, "rwdadm.set_points", "تعيين رصيد"), callback_data=f"rwdadm:set:{uid}"),
        InlineKeyboardButton(text=t(lang, "rwdadm.zero_points", "تصفير"),      callback_data=f"rwdadm:zero:{uid}"),
    )
    kb.row(InlineKeyboardButton(text=t(lang, "rwdadm.notify", "إشعار المستخدم"), callback_data=f"rwdadm:notify:{uid}"))

    if banned:
        kb.row(InlineKeyboardButton(text="✅ " + t(lang, "rwdadm.unban", "إلغاء الحظر"), callback_data=f"rwdadm:unban:{uid}"))
    else:
        kb.row(InlineKeyboardButton(text="🚫 " + t(lang, "rwdadm.ban", "حظر المستخدم"), callback_data=f"rwdadm:ban:{uid}"))

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

# ================= إجراءات النقاط =================
@router.callback_query(F.data.startswith("rwdadm:grant:"))
async def grant_points(cb: CallbackQuery):
    parts = cb.data.split(":")
    uid = int(parts[2])
    delta = int(parts[3])
    ensure_user(uid)
    add_points(uid, delta, reason="admin_grant")
    new_bal = int(get_points(uid))
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

# ================= حظر / إلغاء الحظر =================
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
    await notify_user_unban(cb.bot, uid, actor_id=cb.from_user.id)
    # إن كانت العملية من قائمة المحظورين، حدّث نفس الصفحة
    if cb.message and cb.message.reply_markup:
        await _refresh_blocked_current_page(cb)
    else:
        await user_panel_open(cb, uid)

# ================= إشعار يدوي =================
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
    try:
        await msg.bot.send_message(uid, text)
    except Exception:
        pass
    await msg.bot.send_message(msg.from_user.id, t(lang, "rwdadm.notify_sent", "✅ تم إرسال الإشعار."))
    try:
        from utils.rewards_notify import notify_admins
        who = f"<a href='tg://user?id={uid}'>{uid}</a>"
        await notify_admins(msg.bot, f"📣 <b>Manual notify</b>\n• User: {who}\n• By: <a href='tg://user?id={msg.from_user.id}'>{msg.from_user.id}</a>\n• Text: {text}")
    except Exception:
        pass
    await state.clear()
    await user_panel_open(msg, uid)

# ================= حذف من قاعدة الجوائز =================
@router.callback_query(F.data.startswith("rwdadm:del:"))
async def delete_user(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    uid = int(cb.data.split(":")[-1])

    # احذف من users.json مباشرة
    try:
        if STORE_FILE.exists():
            d = json.loads(STORE_FILE.read_text(encoding="utf-8")) or {}
            if isinstance(d, dict):
                d.pop(str(uid), None)
                tmp = STORE_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, STORE_FILE)
    except Exception:
        pass

    try:
        from utils.rewards_notify import notify_admins
        who = f"<a href='tg://user?id={uid}'>{uid}</a>"
        await notify_admins(cb.bot, f"🗑 <b>User removed from rewards DB</b>\n• User: {who}\n• By: <a href='tg://user?id={cb.from_user.id}'>{cb.from_user.id}</a>")
    except Exception:
        pass

    try:
        await cb.message.answer(t(lang, "rwdadm.deleted_done", "تم حذف المستخدم من قاعدة الجوائز."))
    except Exception:
        pass

    await _render_users_list(cb, 1)

# ================= الدخول: أزرار + أوامر =================
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
    await notify_user_unban(msg.bot, uid, actor_id=msg.from_user.id)
    await msg.answer("✅")

@router.message(Command("r_del"))
async def cmd_r_del(msg: Message):
    try:
        _, uid_s = msg.text.split(maxsplit=1)
        uid = int(uid_s)
    except Exception:
        return
    try:
        if STORE_FILE.exists():
            d = json.loads(STORE_FILE.read_text(encoding="utf-8")) or {}
            if isinstance(d, dict):
                d.pop(str(uid), None)
                tmp = STORE_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, STORE_FILE)
        from utils.rewards_notify import notify_admins
        who = f"<a href='tg://user?id={uid}'>{uid}</a>"
        await notify_admins(msg.bot, f"🗑 <b>User removed from rewards DB</b>\n• User: {who}\n• By: <a href='tg://user?id={msg.from_user.id}'>{msg.from_user.id}</a>")
    except Exception:
        pass
    await msg.answer("✅")

@router.message(Command("r_notify"))
async def cmd_r_notify(msg: Message):
    try:
        _, uid_s, text = msg.text.split(maxsplit=2)
        uid = int(uid_s)
    except Exception:
        return
    try:
        await msg.bot.send_message(uid, text)
    except Exception:
        pass
    try:
        from utils.rewards_notify import notify_admins
        who = f"<a href='tg://user?id={uid}'>{uid}</a>"
        await notify_admins(msg.bot, f"📣 <b>Manual notify</b>\n• User: {who}\n• By: <a href='tg://user?id={msg.from_user.id}'>{msg.from_user.id}</a>\n• Text: {text}")
    except Exception:
        pass
    await msg.answer("✅")
