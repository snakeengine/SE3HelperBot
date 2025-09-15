# handlers/rewards_profile_pro.py
from __future__ import annotations

import time, re
from typing import Any, Dict, List, Tuple, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang
from .rewards_gate import require_membership
from utils.rewards_store import (
    ensure_user, get_points,
    get_user as _get_user_row,
    get_history,
    purge_user_history,          # ✅ نستعمله للحذف الحقيقي
)

try:
    from handlers.promoter import is_promoter as _is_promoter  # type: ignore
except Exception:
    _is_promoter = None  # type: ignore

try:
    from utils.vip import is_vip as _is_vip, get_expiry as _vip_expiry  # type: ignore
except Exception:
    _is_vip = None  # type: ignore
    _vip_expiry = None  # type: ignore

router = Router(name="rewards_profile_pro")

# ============== helpers ==============
def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tt(lang: str, key: str, fb: str) -> str:
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fb

def _fb(lang: str, ar: str, en: str) -> str:
    """Fallback ثنائي: يختار العربي/الإنجليزي حسب اللغة الحالية إذا كان المفتاح مفقودًا."""
    return en if str(lang).startswith("en") else ar

def _rank_for_points(pts: int) -> Tuple[str, str, int, int]:
    tiers = [
        ("Bronze",   "🥉", 0,    100),
        ("Silver",   "🥈", 100,  250),
        ("Gold",     "🥇", 250,  500),
        ("Platinum", "🏆", 500, 1000),
        ("Diamond",  "💎", 1000, 10_000_000),
    ]
    for name, badge, start, end in tiers:
        if start <= pts < end:
            return name, badge, start, end
    return "Bronze", "🥉", 0, 100

def _progress_bar(current: int, start: int, end: int, width: int = 10) -> str:
    rng = max(1, end - start)
    done = max(0, current - start)
    pct = min(1.0, done / rng)
    filled = int(round(pct * width))
    return "█" * filled + "░" * (width - filled)

async def _bot_username(obj: Message | CallbackQuery) -> str:
    try:
        me = await obj.bot.get_me()
        return me.username or ""
    except Exception:
        return ""

def _format_ts(ts: Optional[int], lang: str) -> str:
    if not ts:
        return "—"
    try:
        tm = time.gmtime(int(ts))
        return f"{tm.tm_year}-{tm.tm_mon:02d}-{tm.tm_mday:02d}"
    except Exception:
        return "—"

def _get_store_snapshot(uid: int) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    try:
        u = _get_user_row(uid) or {}
        if isinstance(u, dict):
            snap.update(u)
    except Exception:
        pass
    snap.setdefault("created_at", None)
    snap.setdefault("earned", None)
    snap.setdefault("spent", None)
    snap.setdefault("streak", None)
    snap.setdefault("last_claim", None)
    snap.setdefault("ref_count", None)
    return snap

def _kb_dump(markup: Optional[InlineKeyboardMarkup]) -> Any:
    try:
        return markup.model_dump(exclude_none=True) if markup else None
    except Exception:
        try:
            return markup.to_python() if markup else None
        except Exception:
            return str(markup) if markup else None

async def _safe_edit(cb: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup) -> bool:
    msg = cb.message
    if not msg:
        return False
    same_text = (getattr(msg, "text", None) == text)
    try:
        same_kb = (_kb_dump(reply_markup) == _kb_dump(msg.reply_markup))
    except Exception:
        same_kb = False
    if same_text and same_kb:
        try:
            await cb.message.edit_reply_markup(reply_markup=reply_markup)
        except Exception:
            try:
                await cb.answer(_tt(_L(cb.from_user.id), "common.no_changes", "لا يوجد جديد."), show_alert=False)
            except Exception:
                pass
        return False
    try:
        await msg.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        return True
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            try:
                await cb.message.edit_reply_markup(reply_markup=reply_markup)
            except Exception:
                pass
            return False
        raise

# ============== UI ==============
def _profile_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tt(lang, "rewards.hub.wallet", "👛 محفظتي"), callback_data="rwd:hub:wallet"),
        InlineKeyboardButton(text=_tt(lang, "rewards.hub.market", "🎁 المتجر"),  callback_data="rwd:hub:market"),
    )
    kb.row(
        InlineKeyboardButton(
            text=_tt(lang, "rewards.hub.daily", _fb(lang, "🎯 نقاط يومية", "🎯 Daily points")),
            callback_data="rwd:hub:daily"
        ),
        InlineKeyboardButton(
            text=_tt(lang, "rwd.profile.history_btn", _fb(lang, "📜 السجل", "📜 History")),
            callback_data="rprof:history:p:1"
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text=_tt(lang, "rwd.profile.invite", _fb(lang, "👥 دعوة صديق", "👥 Invite a friend")),
            callback_data="rprof:invite"
        )
    )
    # ✅ زر تحديث فقط (إزالة زر الرجوع في الشاشة الرئيسية)
    kb.row(
        InlineKeyboardButton(
            text=_tt(lang, "common.refresh", _fb(lang, "🔄 تحديث", "🔄 Refresh")),
            callback_data="rprof:refresh"
        )
    )
    return kb.as_markup()


def _history_kb(lang: str, page: int, total: int, per_page: int) -> InlineKeyboardMarkup:
    max_page = max(1, (total + per_page - 1) // per_page)
    kb = InlineKeyboardBuilder()

    row = []
    prev_txt = _tt(lang, "rewards.history.prev", "«")
    next_txt = _tt(lang, "rewards.history.next", "»")
    page_txt = _tt(lang, "rewards.history.page", "{page}/{pages}").format(page=page, pages=max_page)
    if page > 1:
        row.append(InlineKeyboardButton(text=prev_txt, callback_data=f"rprof:history:p:{page-1}"))
    row.append(InlineKeyboardButton(text=page_txt, callback_data="noop"))
    if page < max_page:
        row.append(InlineKeyboardButton(text=next_txt, callback_data=f"rprof:history:p:{page+1}"))
    if row:
        kb.row(*row)

    # زر تنظيف السجل
    kb.row(
        InlineKeyboardButton(
            text=_tt(lang, "hist.clean.button", _fb(lang, "🧹 تنظيف السجل", "🧹 Clear history")),
            callback_data="rprof:history:clean"
        )
    )

    kb.row(InlineKeyboardButton(text=_tt(lang, "rwd.profile.back", _fb(lang, "⬅️ رجوع", "⬅️ Back")), callback_data="rprof:back"))
    return kb.as_markup()

def _icon_for_type(lang: str, typ: str) -> str:
    default = {
        "daily": "🎯", "buy": "🛒", "send": "📤", "recv": "📥",
        "admin": "⚙️", "adjust": "⚙️", "order": "🧾",
        "refund": "↩️", "penalty": "🚫", "gate": "🚪",
        "bonus": "🎁", "task": "✅", "invite": "👥"
    }
    return _tt(lang, f"rewards.history.icon.{typ}", default.get(typ, "•"))

def _label_for_type(lang: str, typ: str) -> str:
    return _tt(lang, f"rewards.history.type.{typ}", typ)

def _human_note(lang: str, typ: str, note: str) -> str:
    n = (note or "").strip()
    if not n:
        return ""
    if n in ("admin_set", "admin_set_cmd"):
        return _tt(lang, "rewards.note.admin_set", _fb(lang, "تعديل الرصيد بواسطة المشرف", "Balance edit by admin"))
    if n in ("admin_grant", "admin_grant_cmd"):
        return _tt(lang, "rewards.note.admin_grant", _fb(lang, "إضافة نقاط من المشرف", "Points granted by admin"))
    if n in ("admin_zero",):
        return _tt(lang, "rewards.note.admin_zero", _fb(lang, "تصفير الرصيد من المشرف", "Balance set to zero by admin"))

    if n.startswith("wallet_transfer_out") or n.startswith("to:") or n.startswith("to "):
        m = re.search(r"(to:|to )(\d+)", n)
        to_id = m.group(2) if m else "—"
        return _tt(lang, "rewards.note.transfer_out", _fb(lang, "تحويل صادر إلى {id}", "Outgoing transfer to {id}")).format(id=to_id)
    if n.startswith("wallet_transfer_in") or n.startswith("from:") or n.startswith("from "):
        m = re.search(r"(from:|from )(\d+)", n)
        from_id = m.group(2) if m else "—"
        return _tt(lang, "rewards.note.transfer_in", _fb(lang, "تحويل وارد من {id}", "Incoming transfer from {id}")).format(id=from_id)

    if n.startswith("market_buy_"):
        item_id = n.split("market_buy_", 1)[1]
        return _tt(lang, "rewards.note.market_buy", _fb(lang, "شراء من المتجر: {id}", "Market purchase: {id}")).format(id=item_id)
    if "market_refund" in n:
        return _tt(lang, "rewards.note.market_refund", _fb(lang, "استرجاع متجر", "Market refund"))
    if "vip_order_refund" in n:
        return _tt(lang, "rewards.note.vip_refund", _fb(lang, "استرجاع VIP", "VIP refund"))

    if n.startswith("create:"):
        try:
            meta = n.split("create:", 1)[1]
            item_id, order_id = meta.split("#", 1)
        except Exception:
            item_id, order_id = n, "?"
        return _tt(lang, "rewards.note.order_create", _fb(lang, "إنشاء طلب #{oid} ({item})", "Created order #{oid} ({item})")).format(oid=order_id, item=item_id)

    if "left_required_channel" in n:
        return _tt(lang, "rewards.note.left_required_channel", _fb(lang, "مغادرة قناة إلزامية", "Left a required channel"))
    if n == "daily":
        return _tt(lang, "rewards.note.daily", _fb(lang, "مكافأة يومية", "Daily reward"))
    if n.startswith("task:"):
        return _tt(lang, "rewards.note.task", _fb(lang, "مهمة: {name}", "Task: {name}")).format(name=n.split("task:",1)[1])
    return n

async def _build_profile_text(obj: Message | CallbackQuery) -> str:
    uid = obj.from_user.id
    lang = _L(uid)

    ensure_user(uid)
    pts = int(get_points(uid) or 0)

    name = (obj.from_user.full_name or "").strip()
    uname = ("@" + obj.from_user.username) if obj.from_user and obj.from_user.username else None

    rank_name, badge, start, end = _rank_for_points(pts)
    bar = _progress_bar(pts, start, end)
    to_next = max(0, end - pts)

    is_prom = False
    if _is_promoter:
        try:
            is_prom = bool(_is_promoter(uid))
        except Exception:
            pass

    vip_line = ""
    if _is_vip:
        try:
            if _is_vip(uid):
                exp = None
                try:
                    exp = _vip_expiry(uid)
                except Exception:
                    pass
                vip_line = "⭐ VIP"
                if exp:
                    vip_line += f" — {_tt(lang,'vip.expires',_fb(lang,'ينتهي','expires'))}: {_format_ts(exp, lang)}"
        except Exception:
            pass

    # لقطة من مخزن الجوائز
    snap = _get_store_snapshot(uid) or {}
    created = _format_ts(snap.get("created_at"), lang)
    earned  = snap.get("earned")
    spent   = snap.get("spent")
    streak  = snap.get("streak")
    ref_count = snap.get("ref_count")

    # بناء النص
    lines: list[str] = []
    header = f"👤 <b>{name}</b>"
    if uname:
        header += f" — <a href='https://t.me/{uname[1:]}'>{uname}</a>"
    lines.append(header)
    lines.append(f"🆔 <code>{uid}</code>")

    status_bits = []
    if is_prom:
        status_bits.append(_tt(lang, "rwd.profile.promoter", _fb(lang, "📣 مروّج", "📣 Promoter")))
    if vip_line:
        status_bits.append(vip_line)
    if status_bits:
        lines.append(" · ".join(status_bits))

    lines.append("")
    lines.append("💰 " + _tt(lang, "rwd.profile.balance", _fb(lang, "رصيدك: {points}", "Balance: {points}")).format(points=pts))
    lines.append("🏅 " + _tt(lang, "rwd.profile.rank", _fb(lang, "رتبتك: {rank}", "Rank: {rank}")).format(rank=f"{badge} {rank_name}"))
    lines.append(f"{bar} ({to_next} " + _tt(lang, "rwd.profile.to_next", _fb(lang, "للوصول للتالية", "to next tier")) + ")")

    extra: list[str] = []
    if earned is not None:
        extra.append("⬆️ " + _tt(lang, "rwd.profile.earned", _fb(lang, "مجمّع: {n}", "Earned: {n}")).format(n=earned))
    if spent is not None:
        extra.append("⬇️ " + _tt(lang, "rwd.profile.spent", _fb(lang, "منفق: {n}", "Spent: {n}")).format(n=spent))
    if streak:
        extra.append("🔥 " + _tt(lang, "rwd.profile.streak", _fb(lang, "سلسلة يومية: {n}", "Daily streak: {n}")).format(n=streak))
    if ref_count is not None:
        extra.append("👥 " + _tt(lang, "rwd.profile.referrals", _fb(lang, "دعوات: {n}", "Invites: {n}")).format(n=ref_count))
    if created != "—":
        extra.append("📅 " + _tt(lang, "rwd.profile.joined", _fb(lang, "تاريخ الانضمام: ", "Joined: ")) + created)

    if extra:
        lines.append("")
        lines.extend(extra)

    return "\n".join(lines)

def _render_history_lines(lang: str, rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return _tt(lang, "rewards.history.empty", _fb(lang, "لا توجد حركات بعد.", "No history yet."))
    coin = _tt(lang, "rewards.coin", "🪙")
    note_fmt = _tt(lang, "rewards.history.note", " — <i>{note}</i>")

    def pad_nbsp(s: str, width: int) -> str:
        s = str(s)
        return ("\u00A0" * max(0, width - len(s))) + s

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        d = _format_ts(r.get("t"), lang)
        grouped.setdefault(d, []).append(r)

    out: List[str] = []
    page_up, page_down = 0, 0

    for day, items in grouped.items():
        out.append(f"🗓 <b>{day}</b>")
        day_up, day_down = 0, 0

        for r in items:
            amt = int(r.get("amount", 0))
            typ_raw = str(r.get("type", "—"))
            raw_note = (r.get("note") or "")

            disp_type = "adjust" if (typ_raw == "admin" and raw_note.startswith("admin_")) else typ_raw
            icon = _icon_for_type(lang, disp_type)
            label = _label_for_type(lang, disp_type)

            pretty_note = _human_note(lang, disp_type, raw_note)
            final_note = pretty_note or raw_note
            note_sfx = note_fmt.format(note=final_note) if final_note else ""

            chip = "🟢" if amt > 0 else ("🔴" if amt < 0 else "⚪️")
            amt_str = f"{amt:+d}"
            amt_str = pad_nbsp(amt_str, 6)
            amount_html = f"<code>{amt_str}</code>"

            if amt > 0:
                day_up += amt;   page_up += amt
            elif amt < 0:
                day_down += -amt; page_down += -amt

            out.append(f"• {chip} {amount_html} {coin}  —  {icon} <b>{label}</b>{note_sfx}")

        net = day_up - day_down
        totals_line = _tt(
            lang,
            "rewards.history.section_total",
            _fb(lang, "<i>مجموع اليوم:</i> +{up} / -{down} — <b>الصافي {net}</b>",
                      "<i>Day total:</i> +{up} / -{down} — <b>net {net}</b>")
        ).format(up=day_up, down=day_down, net=net)
        out.append("┈" * 20)
        out.append(totals_line)
        out.append("")

    net_page = page_up - page_down
    page_totals = _tt(
        lang,
        "rewards.history.totals",
        _fb(lang, "<i>إجمالي الصفحة:</i> +{up} / -{down} — <b>الصافي {net}</b>",
                  "<i>Page total:</i> +{up} / -{down} — <b>net {net}</b>")
    ).format(up=page_up, down=page_down, net=net_page)
    out.append(page_totals)
    return "\n".join(out).strip()

# ============== open/update ==============
async def open_profile(msg_or_cb: Message | CallbackQuery, edit: bool = False):
    if await require_membership(msg_or_cb) is False:
        return
    lang = _L(msg_or_cb.from_user.id)
    text = await _build_profile_text(msg_or_cb)
    markup = _profile_kb(lang)
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text, reply_markup=markup, disable_web_page_preview=True)
    else:
        if edit and msg_or_cb.message:
            await _safe_edit(msg_or_cb, text, markup)
        else:
            await msg_or_cb.message.answer(text, reply_markup=markup, disable_web_page_preview=True)

@router.message(Command("profile", "my_rewards", "rprofile", "rewards_profile"))
async def _cmd_profile(m: Message):
    await open_profile(m)

# ============== history: pagination only ==============
@router.callback_query(F.data.startswith("rprof:history:p:"))
async def _cb_history(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return
    uid = cb.from_user.id
    lang = _L(uid)

    try:
        page = max(1, int(cb.data.split(":")[-1]))
    except Exception:
        page = 1

    per_page = 8
    offset = (page - 1) * per_page
    rows, total = get_history(uid, offset=offset, limit=per_page)

    head = _tt(lang, "rewards.history.title", _fb(lang, "📜 السجل", "📜 History"))
    body = _render_history_lines(lang, rows)
    text = f"<b>{head}</b>\n{body}"

    kb = _history_kb(lang, page=page, total=total, per_page=per_page)
    await _safe_edit(cb, text, kb)

# ============== history: cleaning (باستخدام التخزين) ==============
def _clean_menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_tt(lang, "hist.clean.opt.today",  _fb(lang, "🗓 اليوم فقط",  "🗓 Today only")),  callback_data="rprof:history:confirm:today"))
    kb.row(InlineKeyboardButton(text=_tt(lang, "hist.clean.opt.7d",     _fb(lang, "🗓 آخر 7 أيام", "🗓 Last 7 days")),  callback_data="rprof:history:confirm:7d"))
    kb.row(InlineKeyboardButton(text=_tt(lang, "hist.clean.opt.30d",    _fb(lang, "🗓 آخر 30 يومًا","🗓 Last 30 days")), callback_data="rprof:history:confirm:30d"))
    kb.row(InlineKeyboardButton(text=_tt(lang, "hist.clean.opt.all",    _fb(lang, "🗑 حذف الكل",   "🗑 Delete all")),    callback_data="rprof:history:confirm:all"))
    kb.row(InlineKeyboardButton(text=_tt(lang, "common.back", _fb(lang, "⬅️ رجوع", "⬅️ Back")), callback_data="rprof:history:p:1"))
    return kb.as_markup()

def _clean_confirm_kb(lang: str, scope: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tt(lang, "hist.clean.yes", _fb(lang, "✅ نعم، احذف", "✅ Yes, delete")), callback_data=f"rprof:history:purge:{scope}"),
        InlineKeyboardButton(text=_tt(lang, "hist.clean.no",  _fb(lang, "↩️ رجوع", "↩️ Back")),             callback_data="rprof:history:clean"),
    )
    return kb.as_markup()

@router.callback_query(F.data == "rprof:history:clean")
async def _cb_history_clean_menu(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return
    lang = _L(cb.from_user.id)
    title = _tt(lang, "hist.clean.title",  _fb(lang, "🧹 تنظيف السجل", "🧹 Clear history"))
    hint  = _tt(lang, "hist.clean.choice", _fb(lang, "اختر ما تريد حذفه:", "Choose what to delete:"))
    await _safe_edit(cb, f"<b>{title}</b>\n{hint}", _clean_menu_kb(lang))

@router.callback_query(F.data.startswith("rprof:history:confirm:"))
async def _cb_history_clean_confirm(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return
    lang = _L(cb.from_user.id)
    scope = cb.data.split(":")[-1]  # today/7d/30d/all
    title = _tt(lang, "hist.clean.title",  _fb(lang, "🧹 تنظيف السجل", "🧹 Clear history"))
    warn  = _tt(lang, "hist.clean.confirm", _fb(lang, "هل أنت متأكد؟ هذا الإجراء لا يمكن التراجع عنه.", "Are you sure? This action cannot be undone."))
    await _safe_edit(cb, f"<b>{title}</b>\n{warn}", _clean_confirm_kb(lang, scope))

@router.callback_query(F.data.startswith("rprof:history:purge:"))
async def _cb_history_clean_purge(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return
    uid = cb.from_user.id
    lang = _L(uid)
    scope = cb.data.split(":")[-1]  # today/7d/30d/all

    removed = purge_user_history(uid, scope=scope)  # ✅ يحفظ في users.json

    per_page = 8
    rows, total = get_history(uid, offset=0, limit=per_page)
    head = _tt(lang, "rewards.history.title", _fb(lang, "📜 السجل", "📜 History"))
    body = _render_history_lines(lang, rows)

    if removed > 0:
        msg = _tt(lang, "hist.clean.done", _fb(lang, "تم حذف {n} حركة من السجل.", "{n} entries were deleted.")).format(n=removed)
    else:
        msg = _tt(lang, "hist.clean.nothing", _fb(lang, "لا توجد عناصر مطابقة للحذف.", "No matching entries to delete."))

    text = f"<b>{head}</b>\n{body}\n\n<i>{msg}</i>"
    await _safe_edit(cb, text, _history_kb(lang, page=1, total=total, per_page=per_page))

# ============== misc ==============
@router.callback_query(F.data == "rprof:back")
async def _cb_back(cb: CallbackQuery):
    await open_profile(cb, edit=True)

@router.callback_query(F.data == "rprof:refresh")
async def _cb_refresh(cb: CallbackQuery):
    # ردّ سريع لإنهاء دوران الزر
    try:
        lang = _L(cb.from_user.id)
        await cb.answer(_tt(lang, "common.refreshed", _fb(lang, "تم التحديث ✅", "Refreshed ✅")), show_alert=False)
    except Exception:
        pass
    # ثم حدّث محتوى الرسالة
    await open_profile(cb, edit=True)

@router.callback_query(F.data == "rprof:invite")
async def _cb_invite(cb: CallbackQuery):
    if await require_membership(cb) is False:
        return
    uid = cb.from_user.id
    lang = _L(uid)
    try:
        me = await cb.bot.get_me()
        bot_un = me.username or ""
    except Exception:
        bot_un = ""
    if not bot_un:
        return await cb.answer(_tt(lang, "common.error", _fb(lang, "حدث خطأ غير متوقع.", "Unexpected error.")), show_alert=True)
    link = f"https://t.me/{bot_un}?start=ref_{uid}"
    txt = _tt(lang, "rwd.profile.invite_text", _fb(lang, "شارك الرابط التالي لدعوة الأصدقاء وكسب مكافآت:\n{link}", "Share this link to invite friends and earn rewards:\n{link}")).format(link=link)
    await _safe_edit(cb, txt, _profile_kb(lang))

@router.callback_query(F.data == "noop")
async def _noop(cb: CallbackQuery):
    try:
        await cb.answer("•")
    except Exception:
        pass

@router.callback_query(F.data == "rwd:profile:open")
async def _cb_profile(cb: CallbackQuery):
    await open_profile(cb, edit=True)
