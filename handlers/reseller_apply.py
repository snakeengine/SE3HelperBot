# handlers/reseller_apply.py
import os
import json
import time
import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from lang import t, get_user_lang
from handlers.supplier_payment import prompt_user_payment  # إرسال شاشة الدفع بعد الموافقة

# ⬇️ إلغاء/تفعيل المورد (اختياري: لو غير موجود يكمل بدون خطأ)
try:
    from utils.suppliers import set_supplier as _set_supplier
except Exception:
    _set_supplier = None

router = Router()

# ===== إعدادات عامة / تخزين =====
DATA_DIR = "data"
APPS_FILE = os.path.join(DATA_DIR, "reseller_apps.json")
os.makedirs(DATA_DIR, exist_ok=True)

# قراءة قائمة الأدمن من .env (ADMIN_IDS=id1,id2,...) أو fallback
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

# مدة الحظر بعد الرفض (أيام) — قابل للضبط من .env (مثلاً 7 أو 3)
COOLDOWN_DAYS = int(os.getenv("COOLDOWN_DAYS", "7"))

# عدد الطلبات المسموح بها وهي قيد المراجعة لنفس المستخدم
MAX_PENDING_PER_USER = 1


# ===== أدوات تخزين JSON =====
def _load() -> list[dict]:
    try:
        with open(APPS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def _save(data: list[dict]) -> None:
    tmp = APPS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, APPS_FILE)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _find_by_rec_id(rec_id: int):
    data = _load()
    for i, r in enumerate(data):
        if r.get("id") == rec_id:
            return i, r, data
    return None, None, data


def _update_status(rec_id: int, status: str, note: str | None = None):
    i, r, data = _find_by_rec_id(rec_id)
    if r is None:
        return None
    r["status"] = status
    if note:
        r["admin_note"] = note
    r["updated_at"] = _now_iso()
    data[i] = r
    _save(data)
    return r


# ===== أدوات منطق =====
def _blocked(user_id: int) -> tuple[bool, str | None]:
    """
    يَحظر المستخدم إذا كان أحدث سجل له 'rejected' خلال مهلة COOLDOWN_DAYS.
    إذا كان أحدث سجل 'rejected_unblocked' → غير محظور.
    """
    data = _load()
    last_rec = None
    last_ts = None

    for r in data:
        if r.get("user_id") != user_id:
            continue
        ts = r.get("updated_at") or r.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if last_ts is None or dt > last_ts:
            last_ts = dt
            last_rec = r

    if not last_rec:
        return False, None

    st = last_rec.get("status")
    if st == "rejected_unblocked":
        return False, None
    if st == "rejected" and last_ts:
        until_dt = last_ts + timedelta(days=COOLDOWN_DAYS)
        if datetime.utcnow() < until_dt:
            return True, until_dt.strftime("%Y-%m-%d")
    return False, None


def _pending_count(user_id: int) -> int:
    return sum(1 for x in _load() if x.get("user_id") == user_id and x.get("status") == "pending")


def _summary(lang: str, d: dict) -> str:
    lines = [
        f"• {t(lang,'rf_name')}: <b>{d['name']}</b>",
        f"• {t(lang,'rf_country')}: <b>{d['country']}</b>",
        f"• {t(lang,'rf_channel')}: <code>{d['channel']}</code>",
        f"• {t(lang,'rf_experience')}: {d['exp']}",
    ]
    if d.get("vol"):
        lines.append(f"• {t(lang,'rf_volume')}: {d['vol']}")
    lines.append(f"• {t(lang,'rf_lang_pref')}: {d['pref']}")
    return "\n".join(lines)


def _fee_note(lang: str) -> str:
    if lang == "ar":
        return "ملاحظة: توجد رسوم قدرها <b>500$</b> لتفعيل حساب المورد داخل التطبيق (تُضاف لمحفظتك لتفعيل المفاتيح/المعرّفات)."
    return "Note: There is a <b>$500</b> fee to activate your supplier account in-app (credited to your wallet for key/ID activations)."


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _norm_lang_pref(text: str, fallback: str = "en") -> str:
    """تطبيع إدخال اللغة من المستخدم إلى 'ar' أو 'en'."""
    if not text:
        return fallback
    s = text.strip().lower()
    ar_set = {"ar", "arabic", "عربي", "العربية"}
    en_set = {"en", "eng", "english", "انجليزي", "إنجليزي", "الانجليزية", "الإنجليزية"}
    if s in ar_set:
        return "ar"
    if s in en_set:
        return "en"
    return fallback


# ===== حالات FSM =====
class ApplyStates(StatesGroup):
    name = State()
    country = State()
    channel = State()
    exp = State()
    vol = State()
    pref = State()
    confirm = State()


class AdminAsk(StatesGroup):
    waiting_question = State()


# ===== كيبوردات =====
def _kb_cancel(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="app_cancel")]
    ])


def _kb_confirm(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "btn_submit"), callback_data="app_submit"),
            InlineKeyboardButton(text=t(lang, "btn_edit"), callback_data="app_restart"),
        ],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")],
    ])


def _kb_admin(rec_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "admin_btn_approve"), callback_data=f"resapp:approve:{rec_id}"),
            InlineKeyboardButton(text=t(lang, "admin_btn_reject"), callback_data=f"resapp:reject:{rec_id}"),
        ],
        [InlineKeyboardButton(text=t(lang, "admin_btn_ask"), callback_data=f"resapp:ask:{rec_id}")],
    ])


# ===== فتح النموذج =====
@router.callback_query(F.data == "apply_reseller")
async def open_apply(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"

    blocked, until = _blocked(cb.from_user.id)
    if blocked:
        await cb.message.edit_text(
            t(lang, "apply_blocked").format(days=COOLDOWN_DAYS, until=until)
        )
        return await cb.answer()

    if _pending_count(cb.from_user.id) >= MAX_PENDING_PER_USER:
        await cb.message.edit_text(t(lang, "apply_already_pending"))
        return await cb.answer()

    await state.clear()
    await state.set_state(ApplyStates.name)
    await cb.message.edit_text(
        f"{t(lang,'apply_intro')}\n\n{_fee_note(lang)}\n\n{t(lang,'ask_name')}",
        reply_markup=_kb_cancel(lang),
        disable_web_page_preview=True
    )
    await cb.answer()


@router.callback_query(F.data == "app_cancel")
async def app_cancel(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.clear()
    await cb.message.edit_text(t(lang, "apply_cancelled"))
    await cb.answer()


@router.callback_query(F.data == "app_restart")
async def app_restart(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    await state.set_state(ApplyStates.name)
    await cb.message.edit_text(t(lang, "ask_name"), reply_markup=_kb_cancel(lang))
    await cb.answer()


# ===== الأسئلة =====
@router.message(ApplyStates.name)
async def g_name(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    v = (msg.text or "").strip()
    if not v:
        return await msg.answer(t(lang, "retry_text"))
    await state.update_data(name=v)
    await state.set_state(ApplyStates.country)
    await msg.answer(t(lang, "ask_country"))


@router.message(ApplyStates.country)
async def g_country(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    v = (msg.text or "").strip()
    if not v:
        return await msg.answer(t(lang, "retry_text"))
    await state.update_data(country=v)
    await state.set_state(ApplyStates.channel)
    await msg.answer(t(lang, "ask_channel"))


@router.message(ApplyStates.channel)
async def g_channel(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    ch = (msg.text or "").strip()
    if not ch or not ("t.me/" in ch or ch.startswith("@")):
        return await msg.answer(t(lang, "retry_channel"))
    await state.update_data(channel=ch)
    await state.set_state(ApplyStates.exp)
    await msg.answer(t(lang, "ask_experience"))


@router.message(ApplyStates.exp)
async def g_exp(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    v = (msg.text or "").strip()
    if not v:
        return await msg.answer(t(lang, "retry_text"))
    await state.update_data(exp=v)
    await state.set_state(ApplyStates.vol)
    await msg.answer(t(lang, "ask_volume"))


@router.message(ApplyStates.vol)
async def g_vol(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    v = (msg.text or "").strip()
    await state.update_data(vol=v)
    await state.set_state(ApplyStates.pref)
    await msg.answer(t(lang, "ask_lang_pref"))


@router.message(ApplyStates.pref)
async def g_pref(msg: Message, state: FSMContext):
    current_lang = get_user_lang(msg.from_user.id) or "en"
    raw = (msg.text or "").strip()
    pref = _norm_lang_pref(raw, fallback=current_lang)

    await state.update_data(pref=pref)
    d = await state.get_data()

    await state.set_state(ApplyStates.confirm)
    await msg.answer(
        t(current_lang, "apply_review") + "\n\n" + _summary(current_lang, d),
        reply_markup=_kb_confirm(current_lang),
        disable_web_page_preview=True
    )


# ===== إرسال الطلب وإشعار الأدمن =====
@router.callback_query(F.data == "app_submit")
async def app_submit(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    d = await state.get_data()
    rec = {
        "id": int(time.time() * 1000),
        "user_id": cb.from_user.id,
        "username": cb.from_user.username or "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "status": "pending",
        **d
    }
    data = _load()
    data.append(rec)
    _save(data)

    await state.clear()
    await cb.message.edit_text(t(lang, "apply_submitted"))

    # إشعار الأدمنين
    txt = (
        "🆕 <b>New supplier application</b>\n"
        f"• RecID: <code>{rec['id']}</code>\n"
        f"• User: <code>{rec['user_id']}</code> @{rec['username']}\n"
        f"• Name: <b>{rec['name']}</b>\n"
        f"• Country: <b>{rec['country']}</b>\n"
        f"• Channel: <code>{rec['channel']}</code>\n"
        f"• Experience: {rec['exp']}"
    )
    kb = _kb_admin(rec["id"], lang)
    for aid in ADMIN_IDS:
        try:
            await cb.message.bot.send_message(aid, txt, reply_markup=kb)
        except Exception:
            pass

    await cb.answer("OK")


# ===== إجراءات الأدمن (اعتماد/رفض/طلب معلومات) =====
@router.callback_query(F.data.regexp(r"^resapp:(approve|reject|ask):\d+$"))
async def admin_actions(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await cb.answer(t("en", "admins_only"), show_alert=True)
        return

    try:
        _, action, rec_id_s = cb.data.split(":")
        rec_id = int(rec_id_s)
    except Exception:
        return await cb.answer("Bad data")

    i, rec, _ = _find_by_rec_id(rec_id)
    if rec is None:
        return await cb.answer(t("en", "not_found"), show_alert=True)

    user_lang = rec.get("pref") or get_user_lang(rec["user_id"]) or "en"

    if action == "approve":
        if _update_status(rec_id, "approved"):
            # 1) إخطار المستخدم بالقبول
            try:
                await cb.message.bot.send_message(rec["user_id"], t(user_lang, "approve_message"), parse_mode="HTML")
            except Exception:
                pass
            # 2) فتح شاشة الدفع للمستخدم
            try:
                await prompt_user_payment(cb.message.bot, rec["user_id"], user_lang)
            except Exception:
                pass
            # 3) تنظيف لوحة الأدمن وتأكيد
            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.message.answer(t(user_lang, "approve_message_admin"))
        return await cb.answer()

    if action == "reject":
        if _update_status(rec_id, "rejected"):
            # ⬇️ تأكد من إلغاء اعتماد المورد إن كان مفعّلاً
            if _set_supplier:
                try:
                    _set_supplier(rec["user_id"], False)
                except Exception as e:
                    logging.warning(f"set_supplier(False) failed for {rec['user_id']}: {e}")

            try:
                await cb.message.bot.send_message(rec["user_id"], t(user_lang, "reject_message"))
            except Exception:
                pass
            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.message.answer(t(user_lang, "reject_message_admin"))
        return await cb.answer()

    if action == "ask":
        await state.update_data(target_uid=rec["user_id"], target_lang=user_lang)
        await state.set_state(AdminAsk.waiting_question)
        await cb.message.answer(t(user_lang, "admin_ask_prompt"))
        await cb.answer()
        return


@router.message(AdminAsk.waiting_question)
async def admin_send_question(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return await msg.answer(t("en", "admins_only"))

    data = await state.get_data()
    uid = data.get("target_uid")
    lang = data.get("target_lang", "en")
    q = (msg.text or "").strip()

    if not uid or not q:
        await state.clear()
        return await msg.answer("Cancelled.")

    try:
        await msg.bot.send_message(uid, t(lang, "admin_ask_user").format(q=q))
    except Exception:
        pass

    await state.clear()
    await msg.answer(t(lang, "admin_done") if t(lang, "admin_done") != "admin_done" else "Done.")


# ====== لوحة إدارة الطلبات للأدمن ======
PER_PAGE = 5

def _items_by_status(status: str) -> list[dict]:
    data = _load()
    if status == "pending":
        items = [r for r in data if r.get("status") == "pending"]
    elif status == "approved":
        items = [r for r in data if r.get("status") == "approved"]
    elif status == "blocked":
        # أحدث سجل لكل مستخدم؛ إن كان "rejected" ضمن المهلة → محظور
        last = {}
        last_ts = {}
        for r in data:
            uid = r.get("user_id")
            if uid is None:
                continue
            ts = r.get("updated_at") or r.get("created_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if uid not in last_ts or dt > last_ts[uid]:
                last_ts[uid] = dt
                last[uid] = r

        items = []
        for uid, r in last.items():
            if r.get("status") == "rejected":
                dt = last_ts[uid]
                if datetime.utcnow() < dt + timedelta(days=COOLDOWN_DAYS):
                    items.append(r)
    elif status == "unbanned":
        items = [r for r in data if r.get("status") == "rejected_unblocked"]
    else:
        items = []
    items.sort(key=lambda x: (x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    return items


def _counts():
    data = _load()
    pending = sum(1 for r in data if r.get("status") == "pending")
    approved = sum(1 for r in data if r.get("status") == "approved")
    blocked = len(_items_by_status("blocked"))
    unbanned = sum(1 for r in data if r.get("status") == "rejected_unblocked")
    return pending, approved, blocked, unbanned


def _paginate(items: list[dict], page: int, per_page: int = PER_PAGE):
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start:start + per_page], page, total_pages


def _label_status(lang: str, status: str) -> str:
    if status == "pending":
        return t(lang, "admin_status_pending")
    if status == "approved":
        return t(lang, "admin_status_approved")
    if status == "blocked":
        return t(lang, "admin_status_blocked")
    if status == "unbanned":
        return t(lang, "admin_status_unbanned")
    return status


def _kb_list(status: str, page: int, total_pages: int, lang: str, page_items: list[dict]) -> InlineKeyboardMarkup:
    p, a, b, u = _counts()
    rows = [[
        InlineKeyboardButton(text=t(lang, "admin_btn_pending").format(n=p),  callback_data="resapp:list:pending:1"),
        InlineKeyboardButton(text=t(lang, "admin_btn_approved").format(n=a), callback_data="resapp:list:approved:1"),
        InlineKeyboardButton(text=t(lang, "admin_btn_blocked").format(n=b),  callback_data="resapp:list:blocked:1"),
        InlineKeyboardButton(text=t(lang, "admin_btn_unbanned").format(n=u), callback_data="resapp:list:unbanned:1"),
    ]]

    # عناصر الصفحة
    for r in page_items:
        rid = r.get("id")
        uname = r.get("username") or str(r.get("user_id"))
        rows.append([InlineKeyboardButton(text=f"#{rid} @{uname}", callback_data=f"resapp:view:{rid}")])

    # تنقل
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"resapp:list:{status}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"resapp:list:{status}:{page+1}"))
    rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_list_message(target, lang: str, status: str, page: int):
    all_items = _items_by_status(status)
    page_items, page, total_pages = _paginate(all_items, page)
    header = f"📂 <b>{t(lang, 'admin_resapps_title')}</b>\n{t(lang, 'admin_current_status')}: <b>{_label_status(lang, status)}</b>"
    if not all_items:
        header += f"\n\n{t(lang, 'admin_no_results')}"
    kb = _kb_list(status, page, total_pages, lang, page_items)

    # target يمكن أن يكون Message أو CallbackQuery.message
    if isinstance(target, Message):
        return await target.answer(header, reply_markup=kb, disable_web_page_preview=True)
    else:
        return await target.edit_text(header, reply_markup=kb, disable_web_page_preview=True)


@router.message(Command("resapps"))
async def admin_list_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    await _render_list_message(msg, lang, "pending", 1)


@router.callback_query(F.data.regexp(r"^resapp:list:(pending|approved|blocked|unbanned):\d+$"))
async def admin_list_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(t("en", "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    _, _, status, page_s = cb.data.split(":")
    await _render_list_message(cb.message, lang, status, int(page_s))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^resapp:view:\d+$"))
async def admin_view_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(t("en", "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    rec_id = int(cb.data.split(":")[2])
    _, rec, _ = _find_by_rec_id(rec_id)
    if rec is None:
        return await cb.answer(t("en", "not_found"), show_alert=True)

    user_lang = rec.get("pref") or get_user_lang(rec["user_id"]) or "en"
    text = (
        f"🧾 <b>RecID:</b> <code>{rec['id']}</code>\n"
        f"👤 <b>User:</b> <code>{rec['user_id']}</code> @{rec.get('username','')}\n"
        f"📌 <b>Status:</b> <code>{rec.get('status')}</code>\n\n"
        + _summary(user_lang, {
            'name': rec.get('name', ''),
            'country': rec.get('country', ''),
            'channel': rec.get('channel', ''),
            'exp': rec.get('exp', ''),
            'vol': rec.get('vol', ''),
            'pref': rec.get('pref', '')
        })
    )

    rows = [[
        InlineKeyboardButton(text=t(lang, "admin_btn_approve"), callback_data=f"resapp:approve:{rec_id}"),
        InlineKeyboardButton(text=t(lang, "admin_btn_reject"),  callback_data=f"resapp:reject:{rec_id}")
    ],
    [InlineKeyboardButton(text=t(lang, "admin_btn_ask"), callback_data=f"resapp:ask:{rec_id}")]]

    blocked, _ = _blocked(rec["user_id"])
    if rec.get("status") == "rejected" and blocked:
        rows.append([InlineKeyboardButton(text=t(lang, "admin_unban"), callback_data=f"resapp:unban:{rec_id}")])

    rows.append([InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="resapp:list:pending:1")])

    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^resapp:unban:\d+$"))
async def admin_unban_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer(t("en", "admins_only"), show_alert=True)

    admin_lang = get_user_lang(cb.from_user.id) or "en"
    rec_id = int(cb.data.split(":")[2])

    i, rec, data = _find_by_rec_id(rec_id)
    if rec is None:
        return await cb.answer(t("en", "not_found"), show_alert=True)

    target_uid = rec.get("user_id")
    user_lang = rec.get("pref") or get_user_lang(target_uid) or "en"

    # ابحث عن أحدث رفض لهذا المستخدم
    latest_reject_idx = None
    latest_reject_ts = None
    for idx, r in enumerate(data):
        if r.get("user_id") != target_uid or r.get("status") != "rejected":
            continue
        ts = r.get("updated_at") or r.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if latest_reject_ts is None or dt > latest_reject_ts:
            latest_reject_ts = dt
            latest_reject_idx = idx

    if latest_reject_idx is None:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(t(admin_lang, "admin_unbanned_admin"))
        return await cb.answer()

    data[latest_reject_idx]["status"] = "rejected_unblocked"
    data[latest_reject_idx]["updated_at"] = _now_iso()
    _save(data)

    try:
        await cb.message.bot.send_message(target_uid, t(user_lang, "admin_unbanned_user"))
    except Exception:
        pass

    try:
        await cb.message.edit_text(
            cb.message.text + "\n\n✅ " + t(admin_lang, "admin_status_unbanned"),
            disable_web_page_preview=True
        )
    except Exception:
        await cb.message.edit_reply_markup(reply_markup=None)

    await cb.message.answer(t(admin_lang, "admin_unbanned_admin"))
    await cb.answer()


# ===== Fallback خفيف — يمرّر زر "تم الدفع" للهاندلر الأصلي مع الأزرار =====
@router.callback_query(F.data == "supplier_paid")
async def _fallback_supplier_paid(cb: CallbackQuery):
    # استدعِ الدالة العامة بشكل صحيح
    try:
        from handlers.supplier_payment import supplier_paid_done
    except Exception:
        return await cb.answer("Payment handler not available.", show_alert=True)

    await supplier_paid_done(
        cb.message.bot,
        cb.from_user.id,
        first_name=cb.from_user.first_name or "",
        username=cb.from_user.username or "",
        lang=(get_user_lang(cb.from_user.id) or "en"),
    )

    # إزالة الأزرار من رسالة المستخدم (إن وُجدت)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await cb.answer("OK")


# زر ثابت للترقيم (لا يفعل شيئًا)
@router.callback_query(F.data == "noop")
async def _noop(cb: CallbackQuery):
    await cb.answer()
