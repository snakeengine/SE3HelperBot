# handlers/vip.py
from __future__ import annotations

import os, re, time
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from lang import t, get_user_lang
from utils.vip_store import (
    is_vip, add_vip, add_vip_seconds,            # ← إضافة add_vip_seconds
    add_pending, pop_pending, get_pending,
    get_vip_meta, find_uid_by_app, normalize_app_id
)

router = Router(name="vip_router")

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

# ---- فحص وجود نفس المعرف في الطلبات المعلّقة لأي مستخدم (مع تطبيع) ----
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

# ---- حالات ----
class VipApplyFSM(StatesGroup):
    waiting_app_id = State()

class AdminCustomSecsFSM(StatesGroup):
    waiting_secs = State()  # إدخال الثواني للمدة المخصصة (من الأدمن)

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
        kb.adjust(1)
    return kb.as_markup()

def _admin_review_kb(user_id: int, app_id: str, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "vip.admin.approve"), callback_data=f"vip:approve:{user_id}")
    kb.button(text=t(lang, "vip.admin.reject"), callback_data=f"vip:reject:{user_id}")
    kb.button(text="⏱ مخصّص", callback_data=f"vip:approve_secs:{user_id}")  # مدة بالثواني
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
    await cb.message.edit_text(
        "\n".join(header) + "\n" +
        (t(lang, "vip.menu.subscribed") if member else t(lang, "vip.menu.not_subscribed")),
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

@router.message(VipApplyFSM.waiting_app_id)
async def vip_receive_appid(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    app_id_raw = (msg.text or "").strip()
    app_id = normalize_app_id(app_id_raw)

    # 1) تحقق الصيغة
    if not _is_valid_app_id(app_id_raw):
        await msg.answer(t(lang, "vip.apply.invalid_appid"), parse_mode=ParseMode.HTML)
        return

    user_id = msg.from_user.id

    # 2) مستخدم VIP بالفعل؟
    if is_vip(user_id):
        meta = get_vip_meta(user_id) or {}
        expiry_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)
        return await msg.answer(
            t(lang, "vip.menu.subscribed") +
            (f"\n🗓️ {t(lang,'vip.expires_on')}: {expiry_str}" if expiry_str != "-" else "")
        )

    # 3) هل المعرف مستخدم بالفعل في VIP؟
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

    # 4) هل يوجد طلب معلّق بنفس المعرف؟
    in_pend, pend_uid = _is_app_in_pending(app_id)
    if in_pend:
        if pend_uid == user_id:
            return await msg.answer("ℹ️ لديك طلب قيد المراجعة بهذا المعرف بالفعل. يرجى الانتظار.")
        else:
            return await msg.answer(
                "⏳ هناك طلب آخر قيد المراجعة بنفس المعرف من مستخدم مختلف.\n"
                "يرجى الانتظار حتى يتم البت فيه أو التواصل مع الدعم."
            )

    # 5) لديه طلب معلّق لنفسه؟
    if get_pending(user_id):
        await state.clear()
        return await msg.answer(t(lang, "vip.track.already_pending"))

    # 6) إنشاء التذكرة + إضافة pending + إشعار الأدمن
    ticket_id = f"{user_id}-{int(time.time())%1000000:06d}"
    add_pending(user_id, app_id, ticket_id=ticket_id)

    submitted_at = _fmt_ts(time.time())

    for admin_id in ADMIN_IDS:
        try:
            await msg.bot.send_message(
                admin_id,
                f"{t(lang, 'vip.admin.new_request_title')}\n"
                f"🎫 <b>{t(lang, 'vip.ticket_id')}</b>: <code>{ticket_id}</code>\n"
                f"👤 {t(lang, 'vip.admin.user')}: <code>{user_id}</code>\n"
                f"🆔 {t(lang, 'vip.admin.app_id')}: <code>{app_id}</code>\n\n"
                f"{t(lang, 'vip.admin.instructions')}",
                reply_markup=_admin_review_kb(user_id, app_id, lang),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    await state.clear()
    await msg.answer(
        t(lang, "vip.apply.sent_with_ticket").format(
            ticket_id=ticket_id,
            submitted_at=submitted_at
        ),
        parse_mode=ParseMode.HTML
    )

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

# ===== إجراءات الأدمن (موافقة/رفض) افتراضية =====
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
    add_vip(user_id, app_id, added_by=cb.from_user.id, days=VIP_DEFAULT_DAYS)

    meta = get_vip_meta(user_id) or {}
    exp_str = _fmt_ts(meta.get("expiry_ts"), date_only=True)

    # ترحيب
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
    await cb.message.edit_text(note, parse_mode=ParseMode.HTML)
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
    await cb.message.edit_text(note, parse_mode=ParseMode.HTML)
    await cb.answer()

# ===== موافقة بمدة مخصّصة بالثواني =====
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
        if secs <= 0 or secs > 315360000:  # حتى 10 سنوات
            raise ValueError()
    except Exception:
        return await msg.answer("قيمة غير صحيحة. أدخل عدد الثواني فقط (1 .. 315360000).")

    data = await state.get_data()
    uid = int(data.get("pending_uid", 0))
    app_id = str(data.get("app_id", ""))
    await state.clear()

    if not uid or not app_id:
        return await msg.answer(t(lang, "vip.admin.bad_payload"))

    # تأكد أن المعرف لم يُستخدم أثناء انتظار الإدخال
    owner = find_uid_by_app(app_id)
    if owner is not None and int(owner) != uid:
        return await msg.answer("⚠️ هذا المعرف أصبح مستخدمًا لحساب آخر. العملية أُلغيت.")

    # نفّذ القبول بمدة حقيقية بالثواني
    pop_pending(uid)
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

    # رسالة ترحيبية للمستخدم
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
