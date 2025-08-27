# handlers/vip.py
from __future__ import annotations

import os, re, time, json
from pathlib import Path
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang
from utils.vip_store import (
    is_vip, add_vip, add_vip_seconds,
    add_pending, pop_pending, get_pending,
    get_vip_meta, find_uid_by_app, normalize_app_id
)

router = Router(name="vip_router")

# ===== تخزين رسائل الإدمن المرتبطة بالطلبات =====
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ADMIN_MSGS_FILE = DATA_DIR / "vip_admin_msgs.json"

def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def _admin_msgs_add(uid: int, chat_id: int, message_id: int, ticket_id: str) -> None:
    store = _read_json(ADMIN_MSGS_FILE)
    key = str(uid)
    entry = store.get(key) or {"ticket_id": ticket_id, "items": []}
    entry["ticket_id"] = ticket_id
    entry["items"].append({"chat_id": int(chat_id), "message_id": int(message_id)})
    store[key] = entry
    _write_json(ADMIN_MSGS_FILE, store)

def _admin_msgs_pop(uid: int) -> dict | None:
    store = _read_json(ADMIN_MSGS_FILE)
    key = str(uid)
    val = store.pop(key, None)
    _write_json(ADMIN_MSGS_FILE, store)
    return val

def _admin_msgs_clear(uid: int) -> None:
    _admin_msgs_pop(uid)

# ---- إعدادات عامة ----
VIP_DEFAULT_DAYS = int(os.getenv("VIP_DEFAULT_DAYS", "30"))

def _load_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    if not ids:
        ids = {7360982123}
    return ids

ADMIN_IDS = _load_admin_ids()

def _admin_only(cb: CallbackQuery) -> bool:
    return bool(cb.from_user and (cb.from_user.id in ADMIN_IDS))

# ---- التحقق من SNAKE ID ----
_RX_NUMERIC = re.compile(r"^\d{4,10}$")
_RX_GENERIC = re.compile(r"^[A-Za-z0-9._\-]{3,80}$")
def _is_valid_app_id(text: str) -> bool:
    text = (text or "").strip()
    return bool(_RX_NUMERIC.fullmatch(text) or _RX_GENERIC.fullmatch(text))

def _fmt_ts(ts: int | float | None, date_only: bool = False) -> str:
    try:
        ts = int(ts) if ts is not None else None
        if not ts:
            return "-"
        fmt = "%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S"
        return time.strftime(fmt, time.localtime(ts))
    except Exception:
        return "-"

def _humanize_seconds(s: int) -> str:
    s = max(0, int(s))
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, r = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if r: parts.append(f"{r}s")
    return " ".join(parts) if parts else "0s"

# ---- فحص وجود نفس المعرف في الطلبات المعلّقة لأي مستخدم ----
def _is_app_in_pending(app_id: str) -> tuple[bool, int | None]:
    try:
        from utils.vip_store import _safe_read, PENDING_FILE  # type: ignore
        target = normalize_app_id(app_id)
        data = _safe_read(PENDING_FILE) or {"items": {}}
        items = data.get("items") or {}
        for uid, meta in items.items():
            mapp = normalize_app_id((meta or {}).get("app_id", ""))
            if mapp == target:
                return True, int(uid)
    except Exception:
        pass
    return False, None

# ===================== هيلبر ذكي للعرض =====================
async def _smart_show(cb: CallbackQuery, text: str, *, reply_markup=None,
                      parse_mode: ParseMode = ParseMode.HTML):
    """
    إن كانت الرسالة الأصلية وسائط -> أرسل رسالة نصية جديدة.
    إن كانت نصية -> حاول تعديلها، وإن فشل فلتكن رسالة جديدة.
    """
    m = cb.message
    is_media = bool(getattr(m, "photo", None) or getattr(m, "animation", None)
                    or getattr(m, "video", None) or getattr(m, "document", None))
    if is_media:
        return await m.answer(text, reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)
    try:
        return await m.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)
    except TelegramBadRequest:
        return await m.answer(text, reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)

# ---- حالات ----
class VipApplyFSM(StatesGroup):
    waiting_app_id = State()
    confirm_terms = State()

class AdminCustomSecsFSM(StatesGroup):
    waiting_secs = State()

# ---- لوحات ----
def _vip_menu_kb(lang: str, *, is_member: bool, has_pending: bool):
    kb = InlineKeyboardBuilder()
    if is_member:
        kb.button(text="⚡ " + t(lang, "vip.tools.title"), callback_data="vip:open_tools")
        kb.button(text=t(lang, "vip.btn.info"), callback_data="vip:info")
        kb.adjust(1)
    else:
        kb.button(text=t(lang, "vip.btn.apply"), callback_data="vip:apply")
        if has_pending:
            kb.button(text="📨 " + t(lang, "vip.btn.track"), callback_data="vip:track")
            kb.button(text="⛔ " + t(lang, "vip.btn.cancel"), callback_data="vip:cancel")
        kb.adjust(1)
    return kb.as_markup()

def _admin_review_kb(user_id: int, app_id: str, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "vip.admin.approve"), callback_data=f"vip:approve:{user_id}")
    kb.button(text=t(lang, "vip.admin.reject"), callback_data=f"vip:reject:{user_id}")
    kb.button(text="⏱ مخصّص", callback_data=f"vip:approve_secs:{user_id}")
    kb.adjust(3)
    kb.row(InlineKeyboardButton(text=f"👤 {t(lang, 'vip.admin.user')} {user_id}", callback_data="vip:noop"))
    kb.row(InlineKeyboardButton(text=f"🆔 {t(lang, 'vip.admin.app_id')}: {app_id}", callback_data="vip:noop"))
    return kb.as_markup()

# ===== نقاط الدخول =====
@router.message(Command("vip"))
async def vip_cmd(msg: Message, state: FSMContext):
    await state.clear()
    lang = get_user_lang(msg.from_user.id) or "en"
    member = is_vip(msg.from_user.id)
    pending = get_pending(msg.from_user.id)
    header = [t(lang, "vip.panel_title")]
    if member:
        meta = get_vip_meta(msg.from_user.id) or {}
        expiry_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
        if expiry_str != "-":
            header.append(f"🗓️ {t(lang, 'vip.expires_on')}: {expiry_str}")
    await msg.answer(
        "\n".join(header) + "\n" +
        (t(lang, "vip.menu.subscribed") if member else t(lang, "vip.menu.not_subscribed")),
        reply_markup=_vip_menu_kb(lang, is_member=member, has_pending=bool(pending)),
        parse_mode=ParseMode.HTML
    )

@router.message(Command("vip_status"))
async def vip_status_cmd(msg: Message):
    lang = get_user_lang(msg.from_user.id) or "en"
    if is_vip(msg.from_user.id):
        meta = get_vip_meta(msg.from_user.id) or {}
        expiry_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
        suffix = f"\n🗓️ {t(lang, 'vip.expires_on')}: {expiry_str}" if expiry_str != "-" else ""
        return await msg.answer(t(lang, "vip.status.ok") + suffix)
    pend = get_pending(msg.from_user.id)
    if pend:
        ticket = pend.get("ticket_id", "—")
        when = _fmt_ts(pend.get("ts"))
        appid = pend.get("app_id", "-")
        return await msg.answer(
            t(lang, "vip.track.status_line").format(ticket_id=ticket, submitted_at=when, app_id=appid),
            parse_mode=ParseMode.HTML
        )
    return await msg.answer(t(lang, "vip.status.none"))

@router.message(Command("vip_track"))
async def vip_track_cmd(msg: Message):
    lang = get_user_lang(msg.from_user.id) or "en"
    pend = get_pending(msg.from_user.id)
    if not pend:
        return await msg.answer(t(lang, "vip.track.none"))
    ticket = pend.get("ticket_id", "—")
    when = _fmt_ts(pend.get("ts"))
    appid = pend.get("app_id", "-")
    await msg.answer(
        t(lang, "vip.track.status_line").format(ticket_id=ticket, submitted_at=when, app_id=appid),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "vip:open")
async def vip_open(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = get_user_lang(cb.from_user.id) or "en"
    member = is_vip(cb.from_user.id)
    pending = get_pending(cb.from_user.id)
    header = [t(lang, "vip.panel_title")]
    if member:
        meta = get_vip_meta(cb.from_user.id) or {}
        expiry_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
        if expiry_str != "-":
            header.append(f"🗓️ {t(lang, 'vip.expires_on')}: {expiry_str}")
    text = "\n".join(header) + "\n" + (t(lang, "vip.menu.subscribed") if member else t(lang, "vip.menu.not_subscribed"))
    await _smart_show(
        cb,
        text,
        reply_markup=_vip_menu_kb(lang, is_member=member, has_pending=bool(pending)),
        parse_mode=ParseMode.HTML
    )
    await cb.answer()

# ===== مسار التقديم =====
@router.callback_query(F.data == "vip:apply")
async def vip_apply(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    if is_vip(cb.from_user.id):
        await cb.answer(t(lang, "vip.menu.subscribed"))
        return
    if get_pending(cb.from_user.id):
        await cb.answer(t(lang, "vip.track.already_pending"), show_alert=True)
        return
    await state.set_state(VipApplyFSM.waiting_app_id)
    await cb.message.answer(t(lang, "vip.apply.prompt_appid"), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "vip:retry")
async def vip_retry(cb: CallbackQuery, state: FSMContext):
    return await vip_apply(cb, state)

@router.message(VipApplyFSM.waiting_app_id)
async def vip_receive_appid(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    app_id_raw = (msg.text or "").strip()
    app_id = normalize_app_id(app_id_raw)

    if not _is_valid_app_id(app_id_raw):
        await msg.answer(t(lang, "vip.apply.invalid_appid"), parse_mode=ParseMode.HTML)
        return

    user_id = msg.from_user.id

    if is_vip(user_id):
        meta = get_vip_meta(user_id) or {}
        expiry_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
        return await msg.answer(
            t(lang, "vip.menu.subscribed") +
            (f"\n🗓️ {t(lang,'vip.expires_on')}: {expiry_str}" if expiry_str != "-" else "")
        )

    owner = find_uid_by_app(app_id)
    if owner is not None:
        owner = int(owner)
        if owner == user_id:
            meta = get_vip_meta(user_id) or {}
            expiry_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
            return await msg.answer(
                "✅ هذا المعرف مستخدم لديك بالفعل واشتراكك فعّال."
                + (f"\n🗓️ {t(lang,'vip.expires_on')}: {expiry_str}" if expiry_str != "-" else "")
            )
        else:
            return await msg.answer(
                "⚠️ هذا SNAKE ID مستخدم لدى حساب آخر، لذلك لا يمكن تقديم طلب بهذا المعرف.\n"
                "إن كنت المالك الحقيقي، يرجى التواصل مع الدعم."
            )

    in_pend, pend_uid = _is_app_in_pending(app_id)
    if in_pend:
        if pend_uid == user_id:
            return await msg.answer("ℹ️ لديك طلب قيد المراجعة بهذا المعرف بالفعل. يرجى الانتظار.")
        else:
            return await msg.answer(
                "⏳ هناك طلب آخر قيد المراجعة بنفس المعرف من مستخدم مختلف.\n"
                "يرجى الانتظار حتى يتم البت فيه أو التواصل مع الدعم."
            )

    if get_pending(user_id):
        await state.clear()
        return await msg.answer(t(lang, "vip.track.already_pending"))

    await state.set_state(VipApplyFSM.confirm_terms)
    await state.update_data(pending_app_id=app_id, pending_ts=int(time.time()))

    warn_text = t(lang, "vip.apply.warning").format(app_id=app_id)
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "vip.apply.btn.confirm"), callback_data="vip:apply_confirm")
    kb.button(text=t(lang, "vip.apply.btn.abort"), callback_data="vip:apply_abort")
    kb.adjust(2)
    await msg.answer(warn_text, reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML)

# ===== تأكيد أو إلغاء التحذير =====
@router.callback_query(F.data == "vip:apply_abort")
async def vip_apply_abort(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup()
        except Exception:
            pass
    try:
        await cb.message.answer(t(lang, "vip.apply.cancelled_banner"), parse_mode=ParseMode.HTML)
        await _smart_show(
            cb,
            t(lang, "vip.panel_title"),
            reply_markup=_vip_menu_kb(lang, is_member=is_vip(cb.from_user.id), has_pending=bool(get_pending(cb.from_user.id))),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await cb.answer(t(lang, "vip.apply.cancelled"))

@router.callback_query(F.data == "vip:apply_confirm")
async def vip_apply_confirm(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    data = await state.get_data()
    app_id = normalize_app_id(str(data.get("pending_app_id", "")))
    if not app_id:
        await state.clear()
        await cb.answer(t(lang, "vip.apply.stale_or_invalid"), show_alert=True)
        return

    user_id = cb.from_user.id

    if is_vip(user_id):
        await state.clear(); await cb.answer(t(lang, "vip.menu.subscribed"), show_alert=True); return
    if get_pending(user_id):
        await state.clear(); await cb.answer(t(lang, "vip.track.already_pending"), show_alert=True); return
    owner = find_uid_by_app(app_id)
    if owner is not None and int(owner) != user_id:
        await state.clear(); await cb.answer("⚠️ هذا المعرف مستخدم لحساب آخر.", show_alert=True); return

    ticket_id = f"{user_id}-{int(time.time())%1000000:06d}"
    add_pending(user_id, app_id, ticket_id=ticket_id)
    submitted_at = _fmt_ts(time.time())

    for admin_id in ADMIN_IDS:
        try:
            m = await cb.bot.send_message(
                admin_id,
                f"{t(lang, 'vip.admin.new_request_title')}\n"
                f"🎫 <b>{t(lang, 'vip.ticket_id')}</b>: <code>{ticket_id}</code>\n"
                f"👤 {t(lang, 'vip.admin.user')}: <code>{user_id}</code>\n"
                f"🆔 {t(lang, 'vip.admin.app_id')}: <code>{app_id}</code>\n\n"
                f"{t(lang, 'vip.admin.instructions')}",
                reply_markup=_admin_review_kb(user_id, app_id, lang),
                parse_mode=ParseMode.HTML
            )
            _admin_msgs_add(user_id, admin_id, m.message_id, ticket_id)
        except Exception:
            pass

    await state.clear()
    try:
        await cb.message.edit_reply_markup()
    except Exception:
        pass
    await cb.message.answer(
        t(lang, "vip.apply.sent_with_ticket").format(ticket_id=ticket_id, submitted_at=submitted_at),
        parse_mode=ParseMode.HTML
    )
    await cb.answer()

# ===== زر تتبّع من القائمة =====
@router.callback_query(F.data == "vip:track")
async def vip_track_btn(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    pend = get_pending(cb.from_user.id)
    if not pend:
        await cb.answer(t(lang, "vip.track.none"), show_alert=True)
        return
    ticket = pend.get("ticket_id", "—")
    when = _fmt_ts(pend.get("ts"))
    appid = pend.get("app_id", "-")
    await cb.message.answer(
        t(lang, "vip.track.status_line").format(ticket_id=ticket, submitted_at=when, app_id=appid),
        parse_mode=ParseMode.HTML
    )
    await cb.answer()

# ===== إلغاء الطلب =====
@router.callback_query(F.data == "vip:cancel")
async def vip_cancel(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    pend = get_pending(cb.from_user.id)
    if not pend:
        await cb.answer(t(lang, "vip.cancel.no_pending"), show_alert=True)
        return

    ticket_id = pend.get("ticket_id", "—")
    user_id = cb.from_user.id

    pop_pending(user_id)

    record = _admin_msgs_pop(user_id) or {}
    items = (record.get("items") or []) if isinstance(record, dict) else []
    for it in items:
        try:
            await cb.bot.delete_message(chat_id=int(it["chat_id"]), message_id=int(it["message_id"]))
        except Exception:
            try:
                await cb.bot.edit_message_text(
                    chat_id=int(it["chat_id"]),
                    message_id=int(it["message_id"]),
                    text=t(lang, "vip.admin.cancelled_replace").format(user_id=user_id, ticket_id=ticket_id),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    for admin_id in ADMIN_IDS:
        try:
            await cb.bot.send_message(
                admin_id,
                t(lang, "vip.admin.user_cancelled_note").format(user_id=user_id, ticket_id=ticket_id),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    try:
        await cb.message.edit_reply_markup(
            reply_markup=_vip_menu_kb(lang, is_member=False, has_pending=False)
        )
    except Exception:
        pass

    await cb.answer(t(lang, "vip.cancel.done"))
    try:
        await cb.message.answer(t(lang, "vip.cancel.hint_retry"))
    except Exception:
        pass

# ===== إجراءات الأدمن =====
@router.callback_query(F.data.startswith("vip:approve:"))
async def vip_approve(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not _admin_only(cb):
        await cb.answer(t(lang, "vip.admin.only"), show_alert=True);  return
    try:
        user_id = int(cb.data.split(":")[2])
    except Exception:
        await cb.answer(t(lang, "vip.admin.bad_payload"), show_alert=True);  return

    pend = get_pending(user_id)
    if not pend:
        await cb.answer(t(lang, "vip.admin.no_pending"), show_alert=True);  return

    app_id = normalize_app_id(pend.get("app_id", ""))
    ticket_id = pend.get("ticket_id")

    owner = find_uid_by_app(app_id)
    if owner is not None and int(owner) != user_id:
        await cb.answer("⚠️ هذا المعرف أصبح مستخدمًا لحساب آخر. أوقفنا الإجراء.", show_alert=True)
        return

    pop_pending(user_id)
    _admin_msgs_clear(user_id)

    add_vip(user_id, app_id, added_by=cb.from_user.id, days=VIP_DEFAULT_DAYS)

    meta = get_vip_meta(user_id) or {}
    exp_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)

    try:
        msg_txt = t(lang, "vip.user.approved")
        if ticket_id:
            msg_txt = t(lang, "vip.user.approved_with_ticket").format(ticket_id=ticket_id)
        if exp_str != "-":
            msg_txt += f"\n🗓️ {t(lang,'vip.expires_on')}: {exp_str}"
        await cb.bot.send_message(user_id, msg_txt)
    except Exception:
        pass

    note = t(lang, "vip.admin.approved_note").format(user_id=user_id, app_id=app_id)
    if ticket_id:
        note += f"\n🎫 {t(lang, 'vip.ticket_id')}: <code>{ticket_id}</code>"
    if exp_str != "-":
        note += f"\n🗓️ {t(lang,'vip.expires_on')}: <b>{exp_str}</b>"

    await _smart_show(cb, note, parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data.startswith("vip:reject:"))
async def vip_reject(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not _admin_only(cb):
        await cb.answer(t(lang, "vip.admin.only"), show_alert=True);  return
    try:
        user_id = int(cb.data.split(":")[2])
    except Exception:
        await cb.answer(t(lang, "vip.admin.bad_payload"), show_alert=True);  return

    pend = get_pending(user_id)
    ticket_id = (pend or {}).get("ticket_id")
    pend = pop_pending(user_id)
    _admin_msgs_clear(user_id)
    if not pend:
        await cb.answer(t(lang, "vip.admin.no_pending"), show_alert=True);  return

    try:
        if ticket_id:
            await cb.bot.send_message(user_id, t(lang, "vip.user.rejected_with_ticket").format(ticket_id=ticket_id))
        else:
            await cb.bot.send_message(user_id, t(lang, "vip.user.rejected"))
    except Exception:
        pass

    note = t(lang, "vip.admin.rejected_note").format(user_id=user_id)
    if ticket_id:
        note += f"\n🎫 {t(lang, 'vip.ticket_id')}: <code>{ticket_id}</code>"

    await _smart_show(cb, note, parse_mode=ParseMode.HTML)
    await cb.answer()

# ===== موافقة بمدة مخصّصة =====
@router.callback_query(F.data.startswith("vip:approve_secs:"))
async def vip_approve_secs_start(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not _admin_only(cb):
        await cb.answer(t(lang, "vip.admin.only"), show_alert=True);  return
    try:
        user_id = int(cb.data.split(":")[2])
    except Exception:
        await cb.answer(t(lang, "vip.admin.bad_payload"), show_alert=True);  return

    pend = get_pending(user_id)
    if not pend:
        await cb.answer(t(lang, "vip.admin.no_pending"), show_alert=True);  return

    app_id = normalize_app_id(pend.get("app_id", ""))
    await state.set_state(AdminCustomSecsFSM.waiting_secs)
    await state.update_data(pending_uid=user_id, app_id=app_id)
    await cb.message.answer("أدخل مدة الاشتراك المطلوبة **بالثواني** (مثل: 2592000 لمدة 30 يوم).", parse_mode=ParseMode.MARKDOWN)
    await cb.answer()

@router.message(AdminCustomSecsFSM.waiting_secs)
async def vip_approve_secs_recv(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "").strip()
    try:
        secs = int(raw)
        if secs <= 0 or secs > 315360000:
            raise ValueError()
    except Exception:
        return await msg.answer("قيمة غير صحيحة. أدخل عدد الثواني فقط (1 .. 315360000).")

    data = await state.get_data()
    uid = int(data.get("pending_uid", 0))
    app_id = str(data.get("app_id", ""))
    await state.clear()

    if not uid or not app_id:
        return await msg.answer(t(lang, "vip.admin.bad_payload"))

    owner = find_uid_by_app(app_id)
    if owner is not None and int(owner) != uid:
        return await msg.answer("⚠️ هذا المعرف أصبح مستخدمًا لحساب آخر. العملية أُلغيت.")

    pop_pending(uid)
    _admin_msgs_clear(uid)

    add_vip_seconds(uid, app_id, seconds=secs, added_by=msg.from_user.id)

    meta = get_vip_meta(uid) or {}
    exp_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
    human = _humanize_seconds(secs)

    await msg.answer(
        f"✅ تم قبول UID <code>{uid}</code> على SNAKE ID <code>{app_id}</code>\n"
        f"⏱ المدة المضافة: <b>{human}</b>\n"
        + (f"🗓️ تاريخ الانتهاء: <b>{exp_str}</b>" if exp_str != "-" else ""),
        parse_mode=ParseMode.HTML
    )

    try:
        await msg.bot.send_message(
            uid,
            "✅ تم قبول طلبك وتفعيل اشتراكك.\n"
            f"⏱ المدة: {human}\n"
            + (f"🗓️ {t(lang,'vip.expires_on')}: {exp_str}" if exp_str != "-" else "")
        )
    except Exception:
        pass

# ===== معلومات/ميزات =====
@router.callback_query(F.data == "vip:info")
async def vip_info(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_vip(cb.from_user.id):
        await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)
        return
    meta = get_vip_meta(cb.from_user.id) or {}
    exp_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
    text = t(lang, "vip.info.text")
    if exp_str != "-":
        text += f"\n🗓️ {t(lang,'vip.expires_on')}: {exp_str}"
    await cb.message.answer(text)
    await cb.answer()

@router.callback_query(F.data == "vip:noop")
async def vip_noop(cb: CallbackQuery):
    await cb.answer()
