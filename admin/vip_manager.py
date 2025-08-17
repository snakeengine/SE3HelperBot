from __future__ import annotations

import os, re, time, math
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang

# مخزن VIP + الحظر
try:
    from utils.vip_store import (
        is_vip, add_vip, list_vips,
        get_pending, pop_pending,
        find_uid_by_app, remove_vip_by_app, search_vips_by_app_prefix,
        get_vip_meta, extend_vip_days,
        add_block, is_blocked, remove_block, list_blocked,
        remove_all_vips
    )
except Exception:
    # Fallbacks
    def is_vip(_): return False
    def add_vip(*args, **kwargs): return None
    def list_vips(): return {"users": {}}
    def get_pending(_): return None
    def pop_pending(_): return None
    def find_uid_by_app(_): return None
    def remove_vip_by_app(_): return False
    def search_vips_by_app_prefix(_): return {}
    def get_vip_meta(_): return {}
    def extend_vip_days(*args, **kwargs): return False
    def add_block(*args, **kwargs): return None
    def is_blocked(_): return False
    def remove_block(*args, **kwargs): return None
    def list_blocked(): return {"blocked": {}}
    def remove_all_vips(): return 0

router = Router(name="admin_vip_manager")

# ===== إعداد الأدمن =====
def _load_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    s = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            s.add(int(part))
    if not s:
        s = {7360982123}
    return s

ADMIN_IDS = _load_admin_ids()
def _is_admin(user_id: int) -> bool: return user_id in ADMIN_IDS

# إعدادات عامة
VIP_DEFAULT_DAYS = int(os.getenv("VIP_DEFAULT_DAYS", "30"))

# ===== تحقق App ID =====
_SNAKE_ONLY = os.getenv("SNAKE_ONLY", "0").strip() not in ("0", "false", "False", "")
_SNAKE_PATTERNS = [
    r"com\.snake\.[A-Za-z0-9._\-]{2,60}",
    r"snake\-[A-Za-z0-9._\-]{2,60}",
    r"\d{4,10}",
]
_SNAKE_RX = re.compile(r"^(?:%s)$" % "|".join(_SNAKE_PATTERNS))
_GENERIC_RX = re.compile(r"^[A-Za-z0-9._\-]{3,80}$")

def _is_valid_app_id(app_id: str) -> bool:
    app_id = (app_id or "").strip()
    if not app_id:
        return False
    if _SNAKE_ONLY:
        return bool(_SNAKE_RX.fullmatch(app_id))
    return bool(_SNAKE_RX.fullmatch(app_id) or _GENERIC_RX.fullmatch(app_id))

# ===== Helpers =====
_UID_RX = re.compile(r"^\d{5,15}$")

def _fmt_date(ts: int | None) -> str:
    try:
        if not ts: return "-"
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except Exception:
        return "-"

def _fmt_dt(ts: int | None) -> str:
    try:
        if not ts: return "-"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
    except Exception:
        return "-"

def _days_remaining_from_exp(expiry_ts: int | None) -> int:
    """تحويل expiry_ts إلى عدد أيام متبقية (≈)، إن لم يوجد نعطي المدة الافتراضية."""
    try:
        if not expiry_ts:
            return VIP_DEFAULT_DAYS
        now = int(time.time())
        delta = int(expiry_ts) - now
        if delta <= 0:
            return VIP_DEFAULT_DAYS
        return max(1, math.ceil(delta / 86400))
    except Exception:
        return VIP_DEFAULT_DAYS

def _find_duplicates(users: dict) -> dict[str, list[tuple[int, dict]]]:
    """
    يرجّع {app_id: [(uid, meta), ...]} لكل app_id له أكثر من UID.
    """
    by_app: dict[str, list[tuple[int, dict]]] = {}
    for uid, meta in (users or {}).items():
        app = str((meta or {}).get("app_id") or "").strip()
        if not app:
            continue
        by_app.setdefault(app, []).append((int(uid), meta or {}))
    return {app: lst for app, lst in by_app.items() if len(lst) > 1}

# ===== دالة تحرير آمنة لتجنّب message is not modified =====
async def safe_edit_text(msg, text, reply_markup=None, parse_mode=None, disable_web_page_preview=True):
    try:
        return await msg.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            if reply_markup is not None:
                try:
                    return await msg.edit_reply_markup(reply_markup=reply_markup)
                except TelegramBadRequest:
                    pass
            return msg
        raise

# ===== FSM =====
class _AddFSM(StatesGroup):
    waiting_uid = State()
    waiting_app = State()
    waiting_confirm = State()  # تأكيد نقل App ID أثناء الإضافة اليدوية

class _RemoveByAppFSM(StatesGroup):
    waiting_app = State()

class _SearchFSM(StatesGroup):
    waiting_prefix = State()

class _CustomDaysFSM(StatesGroup):
    pending_uid = State()
    waiting_days = State()

class _ReassignPendFSM(StatesGroup):
    waiting_confirm = State()  # تأكيد نقل App ID أثناء قبول الطلبات

# ===== قوائم ولوحات =====
def _menu_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="➕ " + t(lang, "admin.vip.add_btn"), callback_data="vipadm:add"),
        InlineKeyboardButton(text="➖ " + t(lang, "admin.vip.remove_btn_by_app"), callback_data="vipadm:remove_by_app"),
    )
    kb.row(
        InlineKeyboardButton(text="📜 " + t(lang, "admin.vip.list_btn"), callback_data="vipadm:list"),
        InlineKeyboardButton(text="⏳ " + t(lang, "admin.vip.pending_btn"), callback_data="vipadm:pending"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "admin.back"), callback_data="ah:menu"))
    return kb.as_markup()

def _toolbar_list(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 " + t(lang, "admin.vip.search_btn"), callback_data="vipadm:search")
    kb.button(text="🔄 " + t(lang, "admin.refresh"), callback_data="vipadm:list")
    kb.button(text="🧹 " + t(lang, "admin.vip.clear_all_btn"), callback_data="vipadm:clear_all_confirm")
    kb.adjust(3)
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "admin.back"), callback_data="vipadm:menu"))
    return kb.as_markup()

def _user_row_line(uid: str, meta: dict) -> str:
    app = (meta or {}).get("app_id", "-")
    adder = (meta or {}).get("added_by")
    exp   = (meta or {}).get("expiry_ts")
    exp_s = _fmt_date(exp)
    adder_s = f"by:{adder}" if adder else "by:-"
    return f"• <code>{app}</code> — UID <a href=\"tg://user?id={uid}\">{uid}</a> ({adder_s}, exp:{exp_s})"

async def _render_list(cb_msg, lang: str):
    d = list_vips() or {"users": {}}
    users = d.get("users") or {}
    if not users:
        return await safe_edit_text(
            cb_msg,
            "📜 <b>" + t(lang, "admin.vip.list_title") + "</b>\n" + t(lang, "admin.vip.list_empty"),
            reply_markup=_toolbar_list(lang),
            parse_mode=ParseMode.HTML
        )

    # اكتشاف المكررات
    dups = _find_duplicates(users)
    dup_count = len(dups)

    # ترتيب حسب app_id
    items = [(str(uid), meta) for uid, meta in users.items()]
    items.sort(key=lambda x: str((x[1] or {}).get("app_id", "")).lower())

    lines = []
    if dup_count:
        lines.append("🚨 " + t(lang, "admin.vip.duplicates_found",).format(n=dup_count))
    lines.extend([_user_row_line(uid, meta) for uid, meta in items[:200]])
    text = "📜 <b>" + t(lang, "admin.vip.list_title") + "</b>\n" + "\n".join(lines)

    # كيبورد علوي + زر توحيد المكررات إن وُجدت
    kb = InlineKeyboardBuilder()
    top_row = [
        InlineKeyboardButton(text="🔎 " + t(lang, "admin.vip.search_btn"), callback_data="vipadm:search"),
        InlineKeyboardButton(text="🔄 " + t(lang, "admin.refresh"), callback_data="vipadm:list"),
        InlineKeyboardButton(text="🧹 " + t(lang, "admin.vip.clear_all_btn"), callback_data="vipadm:clear_all_confirm"),
    ]
    if dup_count:
        top_row.append(InlineKeyboardButton(text="🧼 " + t(lang, "admin.vip.dedupe_btn"), callback_data="vipadm:dedupe"))
    kb.row(*top_row)

    # أزرار لكل مشترك (تفاصيل/تمديد/إزالة/حظر)
    for uid, meta in items[:20]:
        kb.row(
            InlineKeyboardButton(text=f"ℹ️ {uid}", callback_data=f"vipadm:details:{uid}"),
            InlineKeyboardButton(text="➕ +30d", callback_data=f"vipadm:extend:{uid}:30"),
            InlineKeyboardButton(text="➕ +90d", callback_data=f"vipadm:extend:{uid}:90"),
        )
        kb.row(
            InlineKeyboardButton(text="🗑️ " + t(lang, "admin.vip.remove_one_btn"), callback_data=f"vipadm:remove_uid:{uid}"),
            InlineKeyboardButton(text="⛔ " + t(lang, "admin.vip.ban_btn"), callback_data=f"vipadm:ban:{uid}"),
        )
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "admin.back"), callback_data="vipadm:menu"))

    await safe_edit_text(
        cb_msg,
        text,
        reply_markup=kb.as_markup(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

def _details_kb(lang: str, uid: int, app_id: str):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="➕ +30d", callback_data=f"vipadm:extend:{uid}:30"),
        InlineKeyboardButton(text="➕ +90d", callback_data=f"vipadm:extend:{uid}:90"),
    )
    kb.row(
        InlineKeyboardButton(text="🗑️ " + t(lang, "admin.vip.remove_one_btn"), callback_data=f"vipadm:remove_uid:{uid}"),
        InlineKeyboardButton(text="⛔ " + t(lang, "admin.vip.ban_btn"), callback_data=f"vipadm:ban:{uid}"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "admin.back"), callback_data="vipadm:list"))
    return kb.as_markup()

# ===== فتح القائمة =====
@router.message(Command("vipadm"))
async def vipadm_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        l = get_user_lang(msg.from_user.id) or "en"
        return await msg.answer(t(l, "admins_only"))
    l = get_user_lang(msg.from_user.id) or "en"
    await msg.answer(
        f"👑 <b>{t(l, 'admin.vip.title')}</b>\n{t(l, 'admin.vip.desc.app_based')}",
        reply_markup=_menu_kb(l),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "vipadm:menu")
async def vipadm_menu(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    await cb.answer()
    await safe_edit_text(
        cb.message,
        f"👑 <b>{t(l, 'admin.vip.title')}</b>\n{t(l, 'admin.vip.desc.app_based')}",
        reply_markup=_menu_kb(l),
        parse_mode=ParseMode.HTML
    )

# ===== إضافة VIP (UID + APP_ID) =====
@router.callback_query(F.data == "vipadm:add")
async def vipadm_add(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(_AddFSM.waiting_uid)
    await cb.message.answer(t(l, "admin.vip.ask_uid"))
    await cb.answer()

@router.message(_AddFSM.waiting_uid)
async def vipadm_add_uid(msg: Message, state: FSMContext):
    l = get_user_lang(msg.from_user.id) or "en"
    uid = (msg.text or "").strip()
    if not _UID_RX.fullmatch(uid):
        return await msg.answer(t(l, "admin.vip.bad_uid"))
    await state.update_data(uid=int(uid))
    await state.set_state(_AddFSM.waiting_app)
    await msg.answer(t(l, "admin.vip.ask_app"))

@router.message(_AddFSM.waiting_app)
async def vipadm_add_app(msg: Message, state: FSMContext):
    l = get_user_lang(msg.from_user.id) or "en"
    app = (msg.text or "").strip()
    if not _is_valid_app_id(app):
        return await msg.answer(t(l, "admin.vip.bad_app_snake"))

    data = await state.get_data()
    uid = int(data["uid"])

    owner = find_uid_by_app(app)
    if owner is not None and int(owner) != uid:
        await state.update_data(uid=uid, app=app, old_uid=int(owner))
        await state.set_state(_AddFSM.waiting_confirm)

        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="✅ نعم", callback_data="vipadm:reassign_yes"),
            InlineKeyboardButton(text="❌ " + t(l, "app.remove_confirm_no"), callback_data="vipadm:reassign_no"),
        )
        return await msg.answer(
            t(l, "admin.vip.app_in_use").format(old_uid=owner) + "\n" +
            t(l, "admin.vip.app_in_use_confirm").format(new_uid=uid),
            reply_markup=kb.as_markup()
        )

    await state.clear()
    add_vip(uid, app, added_by=msg.from_user.id, days=VIP_DEFAULT_DAYS)
    exp = (get_vip_meta(uid) or {}).get("expiry_ts")
    return await msg.answer(
        t(l, "admin.vip.added").format(user_id=uid, app_id=app) +
        (f"\n🗓️ {t(l,'vip.expires_on')}: {_fmt_date(exp)}" if exp else "")
    )

@router.callback_query(F.data == "vipadm:reassign_yes")
async def vipadm_reassign_yes(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    data = await state.get_data()
    uid = int(data.get("uid", 0))
    old_uid = int(data.get("old_uid", 0))
    app = str(data.get("app", ""))

    await state.clear()
    if not (uid and old_uid and app):
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    try:
        remove_vip_by_app(app)
    except Exception:
        pass
    add_vip(uid, app, added_by=cb.from_user.id, days=VIP_DEFAULT_DAYS)

    await cb.answer("OK")
    await cb.message.answer(
        t(l, "admin.vip.app_reassigned").format(app_id=app, old_uid=old_uid, new_uid=uid)
    )
    await vipadm_list(cb)

@router.callback_query(F.data == "vipadm:reassign_no")
async def vipadm_reassign_no(cb: CallbackQuery, state: FSMContext):
    l = get_user_lang(cb.from_user.id) or "en"
    await state.clear()
    await cb.answer()
    await cb.message.answer(t(l, "admin.vip.cancelled"))

# ===== إزالة VIP — بالـ App ID =====
@router.callback_query(F.data == "vipadm:remove_by_app")
async def vipadm_remove_by_app(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(_RemoveByAppFSM.waiting_app)
    await cb.message.answer(t(l, "admin.vip.ask_app_remove"))
    await cb.answer()

@router.message(_RemoveByAppFSM.waiting_app)
async def vipadm_remove_by_app_recv(msg: Message, state: FSMContext):
    l = get_user_lang(msg.from_user.id) or "en"
    app = (msg.text or "").strip()
    if not _is_valid_app_id(app):
        return await msg.answer(t(l, "admin.vip.bad_app_snake"))
    await state.clear()

    uid = find_uid_by_app(app)
    if uid is None:
        suggestions = search_vips_by_app_prefix(app)
        if suggestions:
            lines = "\n".join([f"• <code>{a}</code> — UID <code>{u}</code>" for u, a in suggestions.items()])
            return await msg.answer(
                t(l, "admin.vip.not_found_app_with_suggestions").format(app_id=app) + "\n" + lines,
                parse_mode=ParseMode.HTML
            )
        return await msg.answer(t(l, "admin.vip.not_found_app").format(app_id=app))

    ok = remove_vip_by_app(app)
    if not ok:
        return await msg.answer(t(l, "admin.vip.not_found_app").format(app_id=app))
    await msg.answer(t(l, "admin.vip.removed_by_app").format(app_id=app, user_id=uid))

# ===== عرض القائمة الموسّعة =====
@router.callback_query(F.data == "vipadm:list")
async def vipadm_list(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    await cb.answer()
    await _render_list(cb.message, l)

# ===== تفاصيل مشترك =====
@router.callback_query(F.data.startswith("vipadm:details:"))
async def vipadm_details(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    try:
        uid = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    meta = get_vip_meta(uid) or {}
    app = meta.get("app_id", "-")
    exp = _fmt_dt(meta.get("expiry_ts"))
    ts  = _fmt_dt(meta.get("ts"))
    adder = meta.get("added_by", "-")
    bl = "✅" if is_blocked(uid) else "❌"

    text = (
        f"👑 <b>{t(l, 'admin.vip.sub_details')}</b>\n"
        f"👤 UID: <a href=\"tg://user?id={uid}\">{uid}</a>\n"
        f"🆔 SNAKE ID: <code>{app}</code>\n"
        f"🗓️ {t(l,'vip.expires_on')}: <code>{exp}</code>\n"
        f"🕒 {t(l,'admin.vip.added_at')}: <code>{ts}</code>\n"
        f"👮‍♂️ {t(l,'admin.vip.added_by')}: <code>{adder}</code>\n"
        f"⛔ {t(l,'admin.vip.blocked')}: {bl}\n"
    )
    await cb.answer()
    await safe_edit_text(
        cb.message,
        text,
        reply_markup=_details_kb(l, uid, app),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# ===== الطلبات المعلّقة =====
@router.callback_query(F.data == "vipadm:pending")
async def vipadm_pending(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    try:
        from utils.vip_store import _safe_read, PENDING_FILE  # type: ignore
        data = _safe_read(PENDING_FILE) or {"items": {}}
        items = data.get("items", {})
    except Exception:
        items = {}

    if not items:
        await cb.answer()
        return await safe_edit_text(cb.message, t(l, "admin.vip.pending_empty"))

    kb = InlineKeyboardBuilder()
    lines = []
    for uid, meta in list(items.items())[:20]:
        app = (meta or {}).get("app_id", "-")
        ts  = (meta or {}).get("ts")
        ticket = (meta or {}).get("ticket_id", "—")
        when = _fmt_dt(ts)
        lines.append(f"• <code>{app}</code> — UID <code>{uid}</code> — 🎫 <code>{ticket}</code> — {when}")
        kb.row(
            InlineKeyboardButton(text=f"✅ {app}", callback_data=f"vipadm:approve:{uid}"),
            InlineKeyboardButton(text=f"❌ {app}", callback_data=f"vipadm:reject:{uid}"),
            InlineKeyboardButton(text="➕ +30d", callback_data=f"vipadm:extend:{uid}:30"),
            InlineKeyboardButton(text="⏱", callback_data=f"vipadm:approvec:{uid}"),
        )
    kb.row(InlineKeyboardButton(text="🔄 " + t(l, "admin.refresh"), callback_data="vipadm:pending"))
    kb.row(InlineKeyboardButton(text="⬅️ " + t(l, "admin.back"), callback_data="vipadm:menu"))
    await cb.answer()
    await safe_edit_text(
        cb.message,
        "⏳ <b>" + t(l, "admin.vip.pending_title") + "</b>\n" + "\n".join(lines),
        reply_markup=kb.as_markup(),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("vipadm:approve:"))
async def vipadm_approve(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    try:
        uid = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    pend = get_pending(uid)
    if not pend:
        return await cb.answer(t(l, "vip.admin.no_pending"), show_alert=True)

    app_id = pend.get("app_id", "-")

    # تحقق التكرار قبل الإضافة
    owner = find_uid_by_app(app_id)
    if owner is not None and int(owner) != uid:
        await state.set_state(_ReassignPendFSM.waiting_confirm)
        await state.update_data(mode="default", uid=uid, old_uid=int(owner), app=app_id, days=VIP_DEFAULT_DAYS)
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="✅ نعم", callback_data="vipadm:reassign_pend_yes"),
            InlineKeyboardButton(text="❌ " + t(l, "app.remove_confirm_no"), callback_data="vipadm:reassign_pend_no"),
        )
        return await cb.message.answer(
            t(l, "admin.vip.app_in_use").format(old_uid=owner) + "\n" +
            t(l, "admin.vip.app_in_use_confirm").format(new_uid=uid),
            reply_markup=kb.as_markup()
        )

    # لا تضارب → نفّذ القبول
    pop_pending(uid)
    add_vip(uid, app_id, added_by=cb.from_user.id, days=VIP_DEFAULT_DAYS)

    try:
        exp = (get_vip_meta(uid) or {}).get("expiry_ts")
        exp_str = _fmt_date(exp)
        await cb.bot.send_message(uid, t(l, "vip.user.approved") + (f"\n🗓️ {t(l,'vip.expires_on')}: {exp_str}" if exp_str != "-" else ""))
    except Exception:
        pass

    await cb.answer("OK")
    await vipadm_pending(cb)

@router.callback_query(F.data.startswith("vipadm:reject:"))
async def vipadm_reject(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    try:
        uid = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    pend = pop_pending(uid)
    if not pend:
        return await cb.answer(t(l, "vip.admin.no_pending"), show_alert=True)

    try:
        await cb.bot.send_message(uid, t(l, "vip.user.rejected"))
    except Exception:
        pass

    await cb.answer("OK")
    await vipadm_pending(cb)

@router.callback_query(F.data.startswith("vipadm:approvec:"))
async def vipadm_approve_custom(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    try:
        uid = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    pend = get_pending(uid)
    if not pend:
        return await cb.answer(t(l, "vip.admin.no_pending"), show_alert=True)

    await state.set_state(_CustomDaysFSM.waiting_days)
    await state.update_data(pending_uid=uid)
    await cb.message.answer(t(l, "admin.vip.ask_days_custom"))
    await cb.answer()

@router.message(_CustomDaysFSM.waiting_days)
async def vipadm_approve_custom_recv(msg: Message, state: FSMContext):
    l = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "").strip()

    try:
        days = int(raw)
        if days <= 0 or days > 3650:
            raise ValueError()
    except Exception:
        return await msg.answer(t(l, "admin.vip.bad_days"))

    data = await state.get_data()
    uid = int(data.get("pending_uid", 0))
    await state.clear()

    if not uid:
        return await msg.answer(t(l, "vip.admin.bad_payload"))

    pend = get_pending(uid)
    if not pend:
        return await msg.answer(t(l, "vip.admin.no_pending"))

    app_id = pend.get("app_id", "-")

    # تحقق التكرار قبل الإضافة
    owner = find_uid_by_app(app_id)
    if owner is not None and int(owner) != uid:
        await state.set_state(_ReassignPendFSM.waiting_confirm)
        await state.update_data(mode="custom", uid=uid, old_uid=int(owner), app=app_id, days=days)
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="✅ نعم", callback_data="vipadm:reassign_pend_yes"),
            InlineKeyboardButton(text="❌ " + t(l, "app.remove_confirm_no"), callback_data="vipadm:reassign_pend_no"),
        )
        return await msg.answer(
            t(l, "admin.vip.app_in_use").format(old_uid=owner) + "\n" +
            t(l, "admin.vip.app_in_use_confirm").format(new_uid=uid),
            reply_markup=kb.as_markup()
        )

    # لا تضارب → نفّذ القبول
    pop_pending(uid)
    add_vip(uid, app_id, added_by=msg.from_user.id, days=days)

    exp = (get_vip_meta(uid) or {}).get("expiry_ts")
    exp_str = _fmt_date(exp)

    await msg.answer(
        t(l, "admin.vip.added_custom").format(user_id=uid, app_id=app_id, days=days) +
        (f"\n🗓️ {t(l,'vip.expires_on')}: {exp_str}" if exp_str != "-" else "")
    )
    try:
        await msg.bot.send_message(uid, t(l, "vip.user.approved") + f"\n🗓️ {t(l,'vip.expires_on')}: {exp_str}")
    except Exception:
        pass

# ===== إعادة تعيين ملكية App ID أثناء قبول الطلبات =====
@router.callback_query(F.data == "vipadm:reassign_pend_yes")
async def vipadm_reassign_pend_yes(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    data = await state.get_data()
    uid = int(data.get("uid", 0))
    old_uid = int(data.get("old_uid", 0))
    app = str(data.get("app", ""))
    days = int(data.get("days", VIP_DEFAULT_DAYS))
    await state.clear()

    if not (uid and old_uid and app):
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    try:
        remove_vip_by_app(app)
    except Exception:
        pass

    pend = get_pending(uid)
    if pend and pend.get("app_id") == app:
        pop_pending(uid)

    add_vip(uid, app, added_by=cb.from_user.id, days=days)

    exp = (get_vip_meta(uid) or {}).get("expiry_ts")
    exp_str = _fmt_date(exp)

    await cb.answer("OK")
    await cb.message.answer(
        t(l, "admin.vip.app_reassigned").format(app_id=app, old_uid=old_uid, new_uid=uid) +
        (f"\n🗓️ {t(l,'vip.expires_on')}: {exp_str}" if exp_str != "-" else "")
    )

    try:
        await cb.bot.send_message(uid, t(l, "vip.user.approved") + f"\n🗓️ {t(l,'vip.expires_on')}: {exp_str}")
    except Exception:
        pass

    await vipadm_pending(cb)

@router.callback_query(F.data == "vipadm:reassign_pend_no")
async def vipadm_reassign_pend_no(cb: CallbackQuery, state: FSMContext):
    l = get_user_lang(cb.from_user.id) or "en"
    await state.clear()
    await cb.answer()
    await cb.message.answer(t(l, "admin.vip.cancelled"))

# ===== توحيد المكررات (Deduplicate) =====
@router.callback_query(F.data == "vipadm:dedupe")
async def vipadm_dedupe(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    data = list_vips() or {"users": {}}
    users = data.get("users") or {}
    dups = _find_duplicates(users)
    if not dups:
        await cb.answer()
        await cb.message.answer(t(l, "admin.vip.no_duplicates"))
        return await vipadm_list(cb)

    kept, removed = 0, 0
    for app_id, entries in dups.items():
        # اختر صاحب أفضل سجل: expiry_ts الأكبر ثم ts الأحدث
        def _score(meta: dict) -> tuple[int, int]:
            return (int((meta or {}).get("expiry_ts") or 0), int((meta or {}).get("ts") or 0))
        entries.sort(key=lambda x: _score(x[1]), reverse=True)
        keep_uid, keep_meta = entries[0]
        keep_exp = int((keep_meta or {}).get("expiry_ts") or 0)
        keep_days = _days_remaining_from_exp(keep_exp)

        # احذف جميع السجلات لهذا الـ app_id (قد يزيل الكل)
        try:
            for _ in range(len(entries)):
                remove_vip_by_app(app_id)
        except Exception:
            pass

        # أعد التعيين للمالك المختار مع الحفاظ على المدة المتبقية قدر الإمكان
        add_vip(keep_uid, app_id, added_by=cb.from_user.id, days=keep_days)
        kept += 1
        removed += max(0, len(entries) - 1)

    await cb.answer("OK")
    await cb.message.answer(t(l, "admin.vip.dedupe_done").format(kept=kept, removed=removed))
    await vipadm_list(cb)

# ===== تمديد / إزالة / حظر =====
@router.callback_query(F.data.startswith("vipadm:extend:"))
async def vipadm_extend(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"

    try:
        _, _, uid_str, days_str = cb.data.split(":")
        uid = int(uid_str); days = int(days_str)
    except Exception:
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    ok = extend_vip_days(uid, days)
    if not ok:
        return await cb.answer("❌", show_alert=True)

    exp = (get_vip_meta(uid) or {}).get("expiry_ts")
    await cb.answer("✅")
    await cb.message.answer(f"✅ UID {uid} +{days}d → 🗓️ {_fmt_date(exp)}")

@router.callback_query(F.data.startswith("vipadm:remove_uid:"))
async def vipadm_remove_uid(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    try:
        uid = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    meta = get_vip_meta(uid) or {}
    app = meta.get("app_id")
    if not app:
        return await cb.answer("❌", show_alert=True)

    if not remove_vip_by_app(app):
        return await cb.answer("❌", show_alert=True)

    await cb.message.answer(f"🗑️ {t(l,'admin.vip.removed_by_app').format(app_id=app, user_id=uid)}")
    await vipadm_list(cb)

@router.callback_query(F.data.startswith("vipadm:ban:"))
async def vipadm_ban(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    try:
        uid = int(cb.data.split(":")[2])
    except Exception:
        return await cb.answer(t(l, "vip.admin.bad_payload"), show_alert=True)

    add_block(uid, reason="admin")
    await cb.message.answer(f"⛔ تم حظر UID {uid} وإزالته من VIP.")
    await vipadm_list(cb)

# ===== بحث =====
@router.callback_query(F.data == "vipadm:search")
async def vipadm_search(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(_SearchFSM.waiting_prefix)
    await cb.message.answer(t(l, "admin.vip.search_prompt"))
    await cb.answer()

@router.message(_SearchFSM.waiting_prefix)
async def vipadm_search_recv(msg: Message, state: FSMContext):
    l = get_user_lang(msg.from_user.id) or "en"
    pref = (msg.text or "").strip()
    await state.clear()
    if not pref:
        return await msg.answer("—")

    matches = search_vips_by_app_prefix(pref)
    if not matches:
        return await msg.answer(t(l, "admin.vip.search_no_results"))

    lines = [f"• <code>{app}</code> — UID <code>{uid}</code>" for uid, app in matches.items()]
    kb = InlineKeyboardBuilder()
    for uid in list(matches.keys())[:20]:
        kb.row(
            InlineKeyboardButton(text=f"ℹ️ {uid}", callback_data=f"vipadm:details:{uid}"),
            InlineKeyboardButton(text="➕ +30d", callback_data=f"vipadm:extend:{uid}:30"),
            InlineKeyboardButton(text="🗑️", callback_data=f"vipadm:remove_uid:{uid}"),
        )
    kb.row(InlineKeyboardButton(text=t(l, "admin.back"), callback_data="vipadm:list"))
    await msg.answer("نتائج البحث:\n" + "\n".join(lines), reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML)

# ===== حذف الكل =====
@router.callback_query(F.data == "vipadm:clear_all_confirm")
async def vipadm_clear_all_confirm(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🧹 " + t(l, "admin.vip.clear_all_yes"), callback_data="vipadm:clear_all"),
        InlineKeyboardButton(text=t(l, "app.remove_confirm_no"), callback_data="vipadm:list"),
    )
    await cb.message.answer(t(l, "admin.vip.clear_all_confirm"), reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "vipadm:clear_all")
async def vipadm_clear_all(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    l = get_user_lang(cb.from_user.id) or "en"
    n = remove_all_vips()
    await cb.message.answer(f"🧹 تم حذف {n} من مشتركي VIP.")
    await vipadm_list(cb)
