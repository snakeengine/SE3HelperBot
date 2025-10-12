from utils.admins import get_admin_ids, is_admin, get_owner_ids
# admin/promo_panel_ui.py
from __future__ import annotations
import os, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from lang import get_user_lang
from utils.promo_sub_store import find_request, update_request, list_requests, PROMO_MIN_VIEWS
from handlers.promo_flow_extras import admin_menu_kb  # نعيد استخدام بعض الأزرار الجاهزة

router = Router(name="admin.promo_panel_ui")

# ───────────── صلاحيات ─────────────
ADMIN_IDS = get_admin_ids()
def _is_admin(i: int) -> bool: return i in set(ADMIN_IDS or [])

def _reset_after_unban(uid: int):
    update_request(
        uid,
        status="none",          # يسمح بالتقديم فورًا
        unbanned_at=_now(),
        rejected_at=None,       # يلغي الكولداون
        requested_at=None,
        approved_at=None,
        submitted_at=None,
        banned_at=None,
        locked=False,
        frozen=False,
        chat_on=False,
        chat_admin=None,
        step=None,              # يلغي أي خطوة متوقفة
        last_prompt=None,
        last_prompt_ts=None,
        updated_at=_now(),
    )


def _now() -> int: return int(time.time())

def _L(x, ar: str, en: str) -> str:
    lang = get_user_lang(x) if isinstance(x, int) else (x or "en")
    return ar if str(lang).startswith("ar") else en

# ───────────── إعدادات ─────────────
PAGE_SIZE = 8
STATUSES = [
    ("awaiting_admin", "بانتظار"),
    ("approved", "موافَق"),
    ("in_review", "قيد المراجعة"),
    ("rejected", "مرفوض"),
    ("activated", "مُفعّل"),
    ("banned", "محظور"),
    ("frozen", "مُجمّد"),
]

# ───────────── لوحات الأزرار ─────────────
def kb_panel_home():
    kb = InlineKeyboardBuilder()
    # صف الفلاتر
    for code, label in STATUSES[:4]:
        kb.button(text=label, callback_data=f"ap:list:{code}:1")
    kb.adjust(4)
    for code, label in STATUSES[4:]:
        kb.button(text=label, callback_data=f"ap:list:{code}:1")
    kb.adjust(3)
    kb.row(InlineKeyboardButton(text="📋 الكل", callback_data="ap:list:*:1"))
    return kb.as_markup()

def kb_list(status: str, page: int, total: int, rows: list[dict]):
    kb = InlineKeyboardBuilder()
    for r in rows:
        uid = r.get("uid")
        st  = r.get("status")
        lbl = f"#{uid} | {st} | {r.get('platform','-')}"
        kb.row(InlineKeyboardButton(text=lbl, callback_data=f"ap:view:{uid}:{status}:{page}"))
    # تنقل
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    prev_p = max(1, page-1); next_p = min(pages, page+1)
    kb.row(
        InlineKeyboardButton(text="⬅️ السابق", callback_data=f"ap:list:{status}:{prev_p}"),
        InlineKeyboardButton(text=f"صفحة {page}/{pages}", callback_data="ap:none"),
        InlineKeyboardButton(text="التالي ➡️", callback_data=f"ap:list:{status}:{next_p}"),
    )
    kb.row(InlineKeyboardButton(text="🏠 الرئيسية", callback_data="ap:home"))
    return kb.as_markup()

def kb_user(uid: int):
    kb = InlineKeyboardBuilder()
    # عمليات المراجعة السريعة
    kb.row(
        InlineKeyboardButton(text="✅ Approve", callback_data=f"ap:op:approve:{uid}"),
        InlineKeyboardButton(text="✍️ Ask details", callback_data=f"ap:op:ask:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text="💬 Open chat", callback_data=f"ap:op:chat_open:{uid}"),
        InlineKeyboardButton(text="🔒 Close chat", callback_data=f"ap:op:chat_close:{uid}"),
    )
    kb.row(InlineKeyboardButton(text="❌ Reject", callback_data=f"ap:op:reject:{uid}"))
    # إجراءات إدارية
    kb.row(
        InlineKeyboardButton(text="⛔️ Ban", callback_data=f"ap:op:ban:{uid}"),
        InlineKeyboardButton(text="✅ Unban", callback_data=f"ap:op:unban:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text="🧊 Freeze", callback_data=f"ap:op:freeze:{uid}"),
        InlineKeyboardButton(text="♻️ Unfreeze", callback_data=f"ap:op:unfreeze:{uid}"),
    )
    kb.row(
        InlineKeyboardButton(text="📝 Note", callback_data=f"ap:op:note:{uid}"),
        InlineKeyboardButton(text="📤 Export chat", callback_data=f"ap:op:export:{uid}"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ رجوع للقائمة", callback_data="ap:backlist"))
    kb.row(InlineKeyboardButton(text="🏠 الرئيسية", callback_data="ap:home"))
    return kb.as_markup()

# ───────────── عرض بطاقة المستخدم ─────────────
def _fmt_user_card(rec: dict) -> str:
    parts = [
        f"👤 uid={rec.get('uid')}",
        f"status={rec.get('status')}",
        f"frozen={rec.get('frozen', False)}",
        f"platform={rec.get('platform','-')}",
        f"post_url={rec.get('post_url','-')}",
        f"min_views={rec.get('min_views', PROMO_MIN_VIEWS)}",
        f"snake_id={rec.get('snake_id','-')}",
        f"chat_on={rec.get('chat_on', False)} admin={rec.get('chat_admin','-')}",
        f"updated_at={rec.get('updated_at') or rec.get('submitted_at') or rec.get('created_at')}",
    ]
    return "\n".join(parts)

# ───────────── حالات FSM لإدخال ملاحظة ─────────────
class NoteState(StatesGroup):
    waiting = State()

# ───────────── أوامر الدخول للوحة ─────────────
@router.message(Command("promo_panel", "promo_admin", "promo_help"))
async def open_panel(msg: Message):
    if not _is_admin(msg.from_user.id): 
        return
    await msg.reply("🛠️ لوحة إدارة SEVIP — اختر فلترًا:", reply_markup=kb_panel_home(), parse_mode=None)

# زر الرئيسية
@router.callback_query(F.data == "ap:home")
async def cb_home(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id): 
        return await cb.answer("Admins only.", show_alert=True)
    await cb.message.edit_text("🛠️ لوحة إدارة SEVIP — اختر فلترًا:", reply_markup=kb_panel_home(), parse_mode=None)
    await cb.answer()

# ───────────── القوائم مع صفحات ─────────────
@router.callback_query(F.data.regexp(r"^ap:list:(\*|[a-z_]+):(\d+)$"))
async def cb_list(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)

    _, _, status, page_s = cb.data.split(":")
    page = max(1, int(page_s))
    status_filter = None if status in {"*", "all"} else status

    # اجلب الكل وأحسب التوتال (list_requests يدعم limit/order، نجيب فوق ما نحتاجه للصفحة الحالية)
    all_rows = list_requests(status=status_filter, limit=200, order="-updated_at") or []
    total = len(all_rows)
    start = (page-1)*PAGE_SIZE
    rows = all_rows[start:start+PAGE_SIZE]

    header = "📋 قائمة الطلبات" + (f" (status={status_filter})" if status_filter else " (الكل)")
    if not rows:
        await cb.message.edit_text(header + "\n— لا نتائج —", reply_markup=kb_panel_home(), parse_mode=None)
        return await cb.answer()

    # نص مختصر
    lines = [f"• #{r.get('uid')} | {r.get('status')} | {r.get('platform','-')} | upd={r.get('updated_at')}" for r in rows]
    await cb.message.edit_text(header + f"\nالإجمالي: {total}\n\n" + "\n".join(lines),
                               reply_markup=kb_list(status, page, total, rows),
                               parse_mode=None)
    await cb.answer()

# حفظ آخر قائمة لزر “رجوع”
_last_list_ctx = {}  # {admin_id: (status, page, total)}

@router.callback_query(F.data.regexp(r"^ap:view:(\d+):(.+):(\d+)$"))
async def cb_view(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _, _, uid_s, status, page_s = cb.data.split(":")
    _last_list_ctx[cb.from_user.id] = (status, int(page_s), 0)
    uid = int(uid_s)

    rec = find_request(uid) or {}
    if not rec:
        await cb.answer("لا يوجد سجل.", show_alert=True)
        return

    await cb.message.edit_text("📄 المستخدم\n" + _fmt_user_card(rec),
                               reply_markup=kb_user(uid), parse_mode=None)
    await cb.answer()

@router.callback_query(F.data == "ap:backlist")
async def cb_backlist(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    status, page, _ = _last_list_ctx.get(cb.from_user.id, ("*", 1, 0))
    # إعادة استدعاء عرض القائمة
    cb.data = f"ap:list:{status}:{page}"
    return await cb_list(cb)

# ───────────── عمليات على المستخدم (زرار) ─────────────
@router.callback_query(F.data.regexp(r"^ap:op:(approve|ask|chat_open|chat_close|reject|ban|unban|freeze|unfreeze|export|note):(\d+)$"))
async def cb_ops(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)

    op, uid_s = cb.data.split(":")[2], cb.data.split(":")[3]
    uid = int(uid_s)

    # تنفيذ سريع اعتمادًا على الهاندلرات الموجودة لديك أصلاً
    if op == "approve":
        # نفس منطق الموافقة الأولية
        update_request(uid, status="approved", approved_at=_now())
        try:
            lang = get_user_lang(uid) or "ar"
            await cb.bot.send_message(uid, _L(lang, "✅ تمت الموافقة. اختر المنصة:", "✅ Approved. Choose platform:"))
        except Exception:
            pass
        await cb.answer("Approved ✓")

    elif op == "ask":
        # إعادة استخدام كولباك طلب التفاصيل
        from handlers.promo_flow_extras import admin_ask_details
        cb.data = f"admin:promo:ask:{uid}"
        return await admin_ask_details(cb, state)

    elif op == "chat_open":
        from handlers.promo_flow_extras import open_chat
        cb.data = f"admin:promo:chat:{uid}"
        return await open_chat(cb)

    elif op == "chat_close":
        from handlers.promo_flow_extras import close_chat
        cb.data = f"admin:promo:closechat:{uid}"
        return await close_chat(cb)

    elif op == "reject":
        update_request(uid, status="rejected", rejected_at=_now())
        try:
            await cb.bot.send_message(uid, _L(uid, "❌ تم رفض الطلب.", "❌ Rejected."))
        except Exception:
            pass
        await cb.answer("Rejected ✓")

    elif op in {"ban", "unban", "freeze", "unfreeze"}:
        if op == "ban":
            update_request(uid, status="banned", banned_at=_now(), frozen=False)
            try:
                await cb.bot.send_message(uid, _L(uid, "❌ تم حظرك من المشاركة.", "❌ You are banned from participating."))
            except Exception:
                pass
            await cb.answer("Banned ✓")

        elif op == "unban":
            # إعادة ضبط كاملة تسمح بالتقديم فورًا وتزيل أثر أي كولداون/قفل/تجميد
            update_request(
                uid,
                status="none",
                unbanned_at=_now(),
                updated_at=_now(),
                rejected_at=None,
                requested_at=None,
                approved_at=None,
                submitted_at=None,
                banned_at=None,
                locked=False,
                frozen=False,
                chat_on=False,
                chat_admin=None,
                step=None,
                last_prompt=None,
                last_prompt_ts=None,
                # اختياري تنظيف تفاصيل قديمة:
                # game=None, snake_id=None, platform=None, post_url=None,
            )
            try:
                await cb.bot.send_message(uid, _L(uid, "✅ تم رفع الحظر. يمكنك التقديم من جديد.", "✅ Ban lifted. You can apply again."))
            except Exception:
                pass
            await cb.answer("Unbanned & reset ✓")

        elif op == "freeze":
            update_request(uid, frozen=True, frozen_at=_now())
            try:
                await cb.bot.send_message(uid, _L(uid, "🧊 تم تجميد حسابك مؤقتًا.", "🧊 Your account is temporarily frozen."))
            except Exception:
                pass
            await cb.answer("Frozen ✓")

        else:  # unfreeze
            update_request(uid, frozen=False, unfrozen_at=_now())
            try:
                await cb.bot.send_message(uid, _L(uid, "♻️ تم رفع التجميد.", "♻️ Freeze removed."))
            except Exception:
                pass
            await cb.answer("Unfrozen ✓")

    elif op == "export":
        # نعيد استخدام أمر التصدير الموجود (يرسل لك أمر /exportchat لتنفّذه بسرعة)
        await cb.answer()
        await cb.message.answer(f"/exportchat {uid}")
        return

    elif op == "note":
        await state.set_state(NoteState.waiting)
        await state.update_data(target_uid=uid)
        await cb.message.answer("📝 أرسل نص الملاحظة (سيتم حفظها داخليًا).", parse_mode=None)
        return await cb.answer()

    # بعد أي عملية، نعيد رسم بطاقة المستخدم بالأحدث
    try:
        rec = find_request(uid) or {}
        await cb.message.edit_text("📄 المستخدم\n" + _fmt_user_card(rec), reply_markup=kb_user(uid), parse_mode=None)
    except Exception:
        pass

# استلام نص الملاحظة
@router.message(StateFilter(NoteState.waiting))
async def note_save(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    uid = int(data.get("target_uid"))
    rec = find_request(uid) or {}
    notes = rec.get("admin_notes") or []
    notes.append({"t":_now(), "by":msg.from_user.id, "note":msg.text})
    update_request(uid, admin_notes=notes)
    await msg.reply("✅ تم حفظ الملاحظة.", parse_mode=None)
    await state.clear()

