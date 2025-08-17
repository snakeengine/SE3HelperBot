# admin/vipadm_panel.py
from __future__ import annotations

import os, json, time
from pathlib import Path
from typing import Optional, List, Dict

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from lang import t, get_user_lang

router = Router(name="vipadm_panel")

# ===== إعدادات عامة =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tt(lang: str, key: str, fallback: str) -> str:
    try:
        v = t(lang, key)
        if isinstance(v, str) and v.strip() and v != key:
            return v
    except Exception:
        pass
    return fallback

# مسار ملف الطلبات الذي تكتبه handlers/vip_features.py
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REQ_FILE = DATA_DIR / "vip_user_requests.json"

# ===== مساعدات قراءة/بحث =====
def _load_reqs() -> List[Dict]:
    try:
        if not REQ_FILE.exists():
            return []
        data = json.loads(REQ_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _find(ticket_id: str) -> Optional[Dict]:
    for it in _load_reqs():
        if it.get("ticket_id") == ticket_id:
            return it
    return None

def _count_by_status(status: str) -> int:
    return sum(1 for it in _load_reqs() if it.get("status") == status)

# ===== لوحات أزرار =====
def _kb_home(lang: str) -> InlineKeyboardMarkup:
    open_n = _count_by_status("open")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text=f"📬 " + _tt(lang, "vipadm.btn.open", "الطلبات المعلّقة") + f" ({open_n})",
        callback_data="vipadm:reqs:open:1"
    ))
    kb.row(InlineKeyboardButton(
        text="📁 " + _tt(lang, "vipadm.btn.all", "جميع الطلبات"),
        callback_data="vipadm:reqs:all:1"
    ))
    kb.row(InlineKeyboardButton(
        text="🛡️ " + _tt(lang, "vipadm.btn.security", "لوحة الأمان"),
        callback_data="sec:admin"
    ))
    kb.row(InlineKeyboardButton(text="⬅️ " + _tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

def _kb_reqs_nav(lang: str, scope: str, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    row = []
    if has_prev:
        row.append(InlineKeyboardButton(text="«", callback_data=f"vipadm:reqs:{scope}:{page-1}"))
    row.append(InlineKeyboardButton(text=f"{page}", callback_data="vipadm:nop"))
    if has_next:
        row.append(InlineKeyboardButton(text="»", callback_data=f"vipadm:reqs:{scope}:{page+1}"))
    kb.row(*row) if row else None
    kb.row(InlineKeyboardButton(text="⬅️ " + _tt(lang, "admin.back", "رجوع"), callback_data="vipadm:menu"))
    return kb.as_markup()

def _kb_ticket(lang: str, req: Dict) -> InlineKeyboardMarkup:
    uid = req.get("user")
    ticket = req.get("ticket_id")
    rtype = req.get("type")  # manage_id | transfer | renew
    kb = InlineKeyboardBuilder()
    # أزرار الإجراء (تعتمد على نفس الـcallbacks الموجودة في vip_features.py)
    if req.get("status") == "open":
        kb.row(
            InlineKeyboardButton(text="✅ " + _tt(lang, "approve", "موافقة"),
                                 callback_data=f"req:approve:{rtype}:{ticket}:{uid}"),
            InlineKeyboardButton(text="❌ " + _tt(lang, "reject", "رفض"),
                                 callback_data=f"req:reject:{rtype}:{ticket}:{uid}"),
        )
    # إثبات الدفع/العملية
    kb.row(InlineKeyboardButton(text="📎 " + _tt(lang, "vipadm.proof", "عرض الإثبات"),
                                callback_data=f"vipadm:req:proof:{ticket}"))
    # روابط سريعة
    kb.row(InlineKeyboardButton(text="👤 Chat", url=f"tg://user?id={uid}"))
    kb.row(InlineKeyboardButton(text="⬅️ " + _tt(lang, "admin.back", "رجوع"),
                                callback_data="vipadm:menu"))
    return kb.as_markup()

# ===== تنسيقات نصية =====
def _fmt_req(lang: str, r: Dict) -> str:
    head = "🎫 <b>{}</b>: <code>{}</code>\n".format(_tt(lang, "vipadm.ticket", "التذكرة"), r.get("ticket_id"))
    st   = "📌 {}: <b>{}</b>\n".format(_tt(lang, "vipadm.status", "الحالة"), r.get("status"))
    rtype = r.get("type")
    rtype_h = {"manage_id": _tt(lang, "vipadm.rt.manage", "إدارة/تعديل المعرّف"),
               "transfer":  _tt(lang, "vipadm.rt.transfer", "نقل الاشتراك"),
               "renew":     _tt(lang, "vipadm.rt.renew", "تجديد/ترقية")}.get(rtype, rtype or "-")
    typ  = "🧰 {}: <b>{}</b>\n".format(_tt(lang, "vipadm.type", "النوع"), rtype_h)
    user = "👤 {}: <code>{}</code>\n".format(_tt(lang, "vipadm.user", "المستخدم"), r.get("user"))
    when = "⏱ {}: <code>{}</code>\n".format(_tt(lang, "vipadm.when", "عند"), r.get("when"))

    # تفاصيل مشتركة/اختيارية
    lines = [head, st, typ, user, when, "—\n"]
    if r.get("seller"):
        lines.append(f"🏷️ {_tt(lang, 'vipadm.seller','البائع')}: {r.get('seller')}\n")
    if rtype == "transfer":
        if r.get("target"):
            lines.append(f"➡️ {_tt(lang,'vipadm.target','الهدف')}: <code>{r.get('target')}</code>\n")
    if r.get("old_app_id") or r.get("new_app_id"):
        lines.append(f"🆔 {_tt(lang,'vipadm.old_id','المعرف القديم')}: <code>{r.get('old_app_id') or '-'}</code>\n")
        lines.append(f"🆔 {_tt(lang,'vipadm.new_id','المعرف الجديد')}: <code>{r.get('new_app_id') or '-'}</code>\n")
    if r.get("amount"):
        lines.append(f"💵 {_tt(lang,'vipadm.amount','المبلغ')}: {r.get('amount')} {r.get('currency') or ''}\n")
    if r.get("purchase_date"):
        lines.append(f"📅 {_tt(lang,'vipadm.date','التاريخ')}: {r.get('purchase_date')}\n")
    if r.get("order_ref"):
        lines.append(f"🧾 {_tt(lang,'vipadm.order','المرجع')}: {r.get('order_ref')}\n")
    if r.get("device"):
        lines.append(f"📱 {_tt(lang,'vipadm.device','الجهاز')}: {r.get('device')}\n")
    if r.get("contact"):
        lines.append(f"☎️ {_tt(lang,'vipadm.contact','التواصل')}: {r.get('contact')}\n")
    if r.get("note"):
        lines.append(f"📝 {_tt(lang,'vipadm.note','ملاحظة')}: {r.get('note')}\n")
    return "".join(lines)

# ===== Handlers =====

@router.callback_query(F.data == "vipadm:menu")
async def vipadm_menu(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tt(_L(cb.from_user.id), "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = _L(cb.from_user.id)
    title = "👑 " + _tt(lang, "vipadm.title", "إدارة VIP")
    desc  = _tt(lang, "vipadm.choose", "اختر إجراء:")
    await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                               reply_markup=_kb_home(lang),
                               parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data.startswith("vipadm:reqs:"))
async def vipadm_reqs_list(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tt(_L(cb.from_user.id), "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = _L(cb.from_user.id)
    _, _, scope, page_s = cb.data.split(":", 3)
    page = max(1, int(page_s))
    per_page = 6

    reqs = _load_reqs()
    if scope == "open":
        reqs = [r for r in reqs if r.get("status") == "open"]
    # ترتيب من الأحدث
    reqs.sort(key=lambda r: r.get("when") or "", reverse=True)

    total = len(reqs)
    start = (page - 1) * per_page
    end   = start + per_page
    page_items = reqs[start:end]

    if not page_items:
        await cb.message.edit_text("📭 " + _tt(lang, "vipadm.empty", "لا توجد عناصر هنا."),
                                   reply_markup=_kb_reqs_nav(lang, scope, page, page>1, end<total))
        return await cb.answer()

    kb = InlineKeyboardBuilder()
    for it in page_items:
        ticket = it.get("ticket_id")
        rtype  = it.get("type")
        label  = f"🎫 {ticket} • {rtype}"
        kb.row(InlineKeyboardButton(text=label, callback_data=f"vipadm:req:show:{ticket}"))
    # تنقل
    has_prev = page > 1
    has_next = end < total
    if has_prev or has_next:
        nav = []
        if has_prev:
            nav.append(InlineKeyboardButton(text="«", callback_data=f"vipadm:reqs:{scope}:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page}", callback_data="vipadm:nop"))
        if has_next:
            nav.append(InlineKeyboardButton(text="»", callback_data=f"vipadm:reqs:{scope}:{page+1}"))
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ " + _tt(lang, "admin.back", "رجوع"), callback_data="vipadm:menu"))

    title = "🗂 " + (_tt(lang, "vipadm.list_open", "الطلبات المعلّقة") if scope == "open" else _tt(lang, "vipadm.list_all", "جميع الطلبات"))
    await cb.message.edit_text(title, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data.startswith("vipadm:req:show:"))
async def vipadm_req_show(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tt(_L(cb.from_user.id), "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = _L(cb.from_user.id)
    ticket = cb.data.split(":", 3)[-1]
    req = _find(ticket)
    if not req:
        return await cb.answer(_tt(lang, "common.not_found", "غير موجود"), show_alert=True)
    text = _fmt_req(lang, req)
    await cb.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_kb_ticket(lang, req))
    await cb.answer()

@router.callback_query(F.data.startswith("vipadm:req:proof:"))
async def vipadm_req_proof(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(_tt(_L(cb.from_user.id), "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = _L(cb.from_user.id)
    ticket = cb.data.split(":", 3)[-1]
    req = _find(ticket)
    if not req:
        return await cb.answer(_tt(lang, "common.not_found", "غير موجود"), show_alert=True)

    photo_id = req.get("proof_photo")
    doc_id   = req.get("proof_doc")
    sent = False
    try:
        if photo_id:
            await cb.message.answer_photo(photo_id, caption=f"🎫 {ticket}")
            sent = True
        if doc_id:
            await cb.message.answer_document(doc_id, caption=f"🎫 {ticket}")
            sent = True
    except Exception:
        pass

    if not sent:
        await cb.answer(_tt(lang, "vipadm.no_proof", "لا يوجد إثبات"), show_alert=True)
    else:
        await cb.answer("✅")

@router.callback_query(F.data == "vipadm:nop")
async def vipadm_nop(cb: CallbackQuery):
    await cb.answer("")

