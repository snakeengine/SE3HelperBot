# admin/alerts_admin.py
from __future__ import annotations
import os, time, datetime
from pathlib import Path
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from lang import t, get_user_lang
from utils.alerts_broadcast import _load_json, _save_json, STATS_FILE, broadcast
from utils.alerts_scheduler import enqueue_job, list_jobs, cancel_job, cancel_all_jobs
from utils.alerts_config import get_config, set_config

router = Router(name="alerts_admin")

# =============== إعدادات عامة ===============
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
DRAFT_FILE = DATA_DIR / "alerts_draft.json"  # {"en": str, "ar": str, "lang_mode": "auto|en|ar", "kind": "app_update|maintenance", "await": "", "ttl": 0}

DEFAULT_KIND = "app_update"
DEFAULT_LANG_MODE = "auto"

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _load_draft() -> dict:
    d = _load_json(DRAFT_FILE) or {}
    d.setdefault("en", ""); d.setdefault("ar", "")
    d.setdefault("lang_mode", DEFAULT_LANG_MODE)
    d.setdefault("kind", DEFAULT_KIND)
    d.setdefault("await", "")
    d.setdefault("ttl", 0)
    return d

def _save_draft(d: dict):
    _save_json(DRAFT_FILE, d)

# ===== helper: edit_text بدون خطأ "message is not modified"
async def _safe_edit(target: CallbackQuery | Message, text: str, kb: InlineKeyboardBuilder | None = None):
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        await msg.edit_text(text, reply_markup=(kb.as_markup() if kb else None))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

def _menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.menu.edit") or "✍️ تعديل النص", callback_data="al:edit")
    kb.button(text=t(lang, "alerts.menu.preview") or "👀 معاينة", callback_data="al:prev")
    kb.button(text=t(lang, "alerts.menu.send_now") or "📣 إرسال الآن", callback_data="al:send")
    kb.button(text=t(lang, "alerts.menu.schedule") or "⏱️ جدولة", callback_data="al:sch")
    kb.button(text=t(lang, "alerts.menu.quick") or "⏳ جدولة سريعة", callback_data="al:schq")
    kb.button(text=t(lang, "alerts.menu.jobs") or "🗓️ الجوبز المجدولة", callback_data="al:jobs")
    kb.button(text=t(lang, "alerts.menu.kind") or "📂 النوع", callback_data="al:kind")
    kb.button(text=t(lang, "alerts.menu.lang") or "🌐 وضع اللغة", callback_data="al:lang")
    kb.button(text=t(lang, "alerts.menu.settings") or "⚙️ الإعدادات", callback_data="al:cfg")
    kb.button(text=t(lang, "alerts.menu.delete") or "🗑️ حذف المسودة", callback_data="al:del")
    kb.button(text=t(lang, "alerts.menu.stats") or "📊 إحصائيات", callback_data="al:stats")
    kb.adjust(2,2,2,2,2)
    return kb.as_markup()

# =============== FSM للحالات ===============
class AlStates(StatesGroup):
    # للإرسال الفوري (TTL)
    wait_ttl   = State()
    # ⬇️ حالات مخصّصة للإعدادات حتى لا تتعارض مع VIP
    wait_rate  = State()
    wait_quiet = State()
    wait_maxw  = State()
    wait_actd  = State()

# =============== فتح القائمة ===============
@router.message(Command("push_update", "push_preview", "push_schedule", "push_stats"))
async def open_menu(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _L(msg.from_user.id)
    await msg.reply(t(lang, "alerts.menu.title") or "إدارة الإشعارات 🔔\nتحكم كامل: تعديل/معاينة/إرسال/جدولة/إلغاء/إعدادات.", reply_markup=_menu_kb(lang))

# =============== تعديل النص ===============
@router.callback_query(F.data == "al:edit")
async def al_edit(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id)
    d = _load_draft(); d["await"] = "en"; _save_draft(d)
    await _safe_edit(
        cb,
        (t(lang, "alerts.enter_text") or "أرسل نص الإشعار (EN أولًا ثم AR).")
        + f"\n\n— kind: {d.get('kind')}\n— lang_mode: {d.get('lang_mode')}\n\nSend as: EN\nThen send as: AR"
    )
    await cb.answer()

@router.message(
    F.from_user.func(lambda u: u.id in ADMIN_IDS)
    & F.text.func(lambda v: (v or "").strip() and not (v or "").startswith("/") and (_load_draft().get("await") in ("en", "ar")))
)
async def capture_text(msg: Message):
    txt = (msg.text or "").strip()
    d = _load_draft()
    awaiting = d.get("await") or ""
    if awaiting == "en":
        d["en"] = txt; d["await"] = "ar"; _save_draft(d)
        return await msg.reply("تم الحفظ [EN]")
    elif awaiting == "ar":
        d["ar"] = txt; d["await"] = "";  _save_draft(d)
        return await msg.reply("تم الحفظ [AR]")

# =============== معاينة ===============
@router.callback_query(F.data == "al:prev")
async def al_prev(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await cb.answer(t(lang, "alerts.no_draft") or "لا توجد مسودة.", show_alert=True)
    txt = (t(lang, "alerts.preview.header") or "معاينة 👀") + \
          f"\n\n[EN]\n{d.get('en') or '-'}\n\n[AR]\n{d.get('ar') or '-'}\n\n(kind={d.get('kind')}, lang_mode={d.get('lang_mode')})"
    await _safe_edit(cb, txt); await cb.answer()

# =============== إرسال الآن (TTL) ===============
@router.callback_query(F.data == "al:send")
async def al_send(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await cb.answer(t(lang, "alerts.no_draft") or "لا توجد مسودة.", show_alert=True)

    # اطلب TTL بالثواني واستعمل FSM
    await state.set_state(AlStates.wait_ttl)
    d["await"] = ""  # نعتمد FSM الآن
    _save_draft(d)
    await _safe_edit(cb, t(lang, "alerts.ask_ttl") or "أدخل مدة بقاء الرسالة بالثواني (0 يعني لا حذف)، مثال: 60")
    await cb.answer()

@router.message(AlStates.wait_ttl, F.text.regexp(r"^\d{1,5}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def handle_ttl_send_now(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    ttl = int((msg.text or "0").strip())
    if ttl < 0 or ttl > 86400:
        return await msg.reply(t(lang, "alerts.invalid_seconds") or "قيمة غير صالحة. اختر بين 0 و 86400.")

    d = _load_draft()
    en = d.get("en") if d.get("lang_mode") in ("auto", "en") else None
    ar = d.get("ar") if d.get("lang_mode") in ("auto", "ar") else None

    sent, skipped, failed = await broadcast(
        msg.bot,
        text_en=en,
        text_ar=ar,
        kind=d.get("kind", "app_update"),
        delivery="inbox",   # إرسال تنبيه + وضع الإشعار في الصندوق
        ping_ttl=ttl,       # حذف رسالة التنبيه بعد N ثانية
        active_for=7*24*3600  # مدة بقاء الإشعار في الصندوق (أسبوع)
    )

    d["ttl"] = ttl; _save_draft(d)
    await state.clear()
    ok_txt = t(lang, "alerts.sent") or "تم الإرسال ✅"
    await msg.reply(f"{ok_txt}\nsent={sent}, skipped={skipped}, failed={failed}")

# =============== جدولة بوقت محدد ===============
@router.callback_query(F.data == "al:sch")
async def al_sch(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id)
    await _safe_edit(cb, (t(lang, "alerts.ask_when") or "أدخل وقت الجدولة (YYYY-MM-DD HH:MM)") + "\n例: 2025-08-26 21:30")
    await cb.answer()

@router.message(F.text.regexp(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def handle_schedule(msg: Message):
    lang = _L(msg.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await msg.reply(t(lang, "alerts.no_draft") or "لا توجد مسودة.")
    try:
        dt = datetime.datetime.strptime(msg.text.strip(), "%Y-%m-%d %H:%M")
        ts = int(dt.timestamp())
    except Exception:
        return await msg.reply(t(lang, "alerts.invalid_time") or "صيغة الوقت غير صحيحة.")
    en = d.get("en") if d.get("lang_mode") in ("auto", "en") else None
    ar = d.get("ar") if d.get("lang_mode") in ("auto", "ar") else None
    enqueue_job(ts, d.get("kind", "app_update"), en, ar)
    await msg.reply(t(lang, "alerts.scheduled") or "تمت الجدولة ✅")

# =============== جدولة سريعة ===============
@router.callback_query(F.data == "al:schq")
async def al_schq(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.quick.15m") or "بعد 15 دقيقة", callback_data="al:q:15m")
    kb.button(text=t(lang, "alerts.quick.1h")  or "بعد ساعة",     callback_data="al:q:1h")
    kb.button(text=t(lang, "alerts.quick.24h") or "بعد 24 ساعة",  callback_data="al:q:24h")
    kb.button(text=t(lang, "alerts.back") or "رجوع", callback_data="al:back")
    kb.adjust(3,1)
    await _safe_edit(cb, t(lang, "alerts.schedule.quick") or "اختر مدة الجدولة السريعة:", kb)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:q:(15m|1h|24h)$"))
async def al_quick(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await cb.answer(t(lang, "alerts.no_draft") or "لا توجد مسودة.", show_alert=True)
    delta = {"15m": 900, "1h": 3600, "24h": 86400}[cb.data.split(":")[-1]]
    ts = int(time.time()) + delta
    en = d.get("en") if d.get("lang_mode") in ("auto", "en") else None
    ar = d.get("ar") if d.get("lang_mode") in ("auto", "ar") else None
    enqueue_job(ts, d.get("kind", "app_update"), en, ar)
    await cb.answer(t(lang, "alerts.scheduled") or "تمت الجدولة ✅", show_alert=True)

# =============== إدارة الجوبز ===============
@router.callback_query(F.data == "al:jobs")
async def al_jobs(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id)
    jobs = list_jobs()
    if not jobs:
        return await _safe_edit(cb, t(lang, "alerts.jobs.empty") or "لا توجد مهام مجدولة.", InlineKeyboardBuilder())
    lines = [t(lang, "alerts.jobs.header") or "المهام المجدولة:"]
    kb = InlineKeyboardBuilder()
    for j in sorted(jobs, key=lambda x: int(x.get("ts", 0))):
        ts = int(j.get("ts", 0))
        when = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        jid = j.get("id")
        lines.append(f"• {when}  ({j.get('kind')})  id={jid}")
        kb.button(text=t(lang, "alerts.jobs.cancel_one") or "إلغاء", callback_data=f"al:cancel:{jid}")
    kb.button(text=t(lang, "alerts.jobs.cancel_all") or "إلغاء الكل", callback_data="al:cancel_all")
    kb.button(text=t(lang, "alerts.back") or "رجوع", callback_data="al:back")
    kb.adjust(1,1,1)
    await _safe_edit(cb, "\n".join(lines), kb); await cb.answer()

@router.callback_query(F.data.regexp(r"^al:cancel:.+"))
async def al_jobs_cancel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    jid = cb.data.split(":", 2)[-1]
    ok = cancel_job(jid)
    await cb.answer("تم الإلغاء" if ok else "غير موجود", show_alert=True)
    await al_jobs(cb)

@router.callback_query(F.data == "al:cancel_all")
async def al_jobs_cancel_all(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    n = cancel_all_jobs()
    await cb.answer(f"تم إلغاء {n}", show_alert=True)
    await al_jobs(cb)

# =============== النوع واللغة ===============
@router.callback_query(F.data == "al:kind")
async def al_kind(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id); d = _load_draft()
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.type.app_update") or "تحديث التطبيق", callback_data="al:k:app_update")
    kb.button(text=t(lang, "alerts.type.maintenance") or "صيانة", callback_data="al:k:maintenance")
    kb.button(text=t(lang, "alerts.back") or "رجوع", callback_data="al:back")
    kb.adjust(2,1)
    await _safe_edit(cb, f"{t(lang, 'alerts.set_type') or 'اختر النوع'} (cur={d.get('kind')})", kb)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:k:(app_update|maintenance)$"))
async def al_kind_set(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    d = _load_draft(); d["kind"] = cb.data.split(":")[-1]; _save_draft(d)
    await cb.answer("OK"); await al_kind(cb)

@router.callback_query(F.data == "al:lang")
async def al_lang(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id); d = _load_draft()
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.lang.auto") or "حسب لغة كل مستخدم", callback_data="al:l:auto")
    kb.button(text=t(lang, "alerts.lang.en")   or "إجبار إنجليزي",   callback_data="al:l:en")
    kb.button(text=t(lang, "alerts.lang.ar")   or "إجبار عربي",      callback_data="al:l:ar")
    kb.button(text=t(lang, "alerts.back") or "رجوع", callback_data="al:back")
    kb.adjust(3,1)
    await _safe_edit(cb, f"{t(lang, 'alerts.set_lang') or 'اختر اللغة'} (cur={d.get('lang_mode')})", kb)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:l:(auto|en|ar)$"))
async def al_lang_set(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    d = _load_draft()
    new_mode = cb.data.split(":")[-1]
    if new_mode == d.get("lang_mode"):
        return await cb.answer("نفس الإعداد ✅", show_alert=False)
    d["lang_mode"] = new_mode; _save_draft(d)
    await cb.answer("OK"); await al_lang(cb)

# =============== الإعدادات ===============
@router.callback_query(F.data == "al:cfg")
async def al_cfg(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id); cfg = get_config()
    body = [
        t(lang, "alerts.settings.header") or "إعدادات الإشعارات:",
        f"enabled = {cfg.get('enabled')}",
        f"rate_limit = {cfg.get('rate_limit')} msg/s",
        f"quiet_hours = {cfg.get('quiet_hours')}",
        f"max_per_week = {cfg.get('max_per_week')}",
        f"active_days = {cfg.get('active_days')}",
        f"tz = {cfg.get('tz')}",
    ]
    kb = InlineKeyboardBuilder()
    kb.button(text=("🔴 OFF" if cfg.get("enabled") else "🟢 ON"), callback_data="al:cfg:toggle")
    kb.button(text=t(lang, "alerts.settings.rate_limit") or "تحديد السرعة", callback_data="al:cfg:rate")
    kb.button(text=t(lang, "alerts.settings.quiet_hours") or "ساعات الهدوء", callback_data="al:cfg:quiet")
    kb.button(text=t(lang, "alerts.settings.max_per_week") or "الحد/أسبوع", callback_data="al:cfg:maxw")
    kb.button(text=t(lang, "alerts.settings.active_days") or "نشِط خلال X يوم", callback_data="al:cfg:actd")
    kb.button(text=t(lang, "alerts.back") or "رجوع", callback_data="al:back")
    kb.adjust(2,2,2,1)
    await _safe_edit(cb, "\n".join(body), kb); await cb.answer()

@router.callback_query(F.data == "al:cfg:toggle")
async def al_cfg_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    cfg = get_config(); set_config({"enabled": not bool(cfg.get("enabled"))})
    await cb.answer("OK"); await al_cfg(cb)

# ⬇️ الحالات الجديدة المقيّدة — تمنع تعارض الرسائل الرقمية مع VIP

@router.callback_query(F.data == "al:cfg:rate")
async def al_cfg_rate(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_rate)
    lang = _L(cb.from_user.id)
    await _safe_edit(cb, t(lang, "alerts.settings.ask_rate_limit") or "أرسل السرعة (رسائل/ثانية): 1..1000")
    await cb.answer()

@router.message(AlStates.wait_rate, F.text.regexp(r"^\d{1,4}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_rate_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"rate_limit": int(msg.text)})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "تم الحفظ ✅")

@router.callback_query(F.data == "al:cfg:quiet")
async def al_cfg_quiet(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_quiet)
    lang = _L(cb.from_user.id)
    await _safe_edit(cb, (t(lang, "alerts.settings.ask_quiet_hours") or "أدخل ساعات الهدوء hh:mm-hh:mm") + "\n例: 22:00-08:00")
    await cb.answer()

@router.message(AlStates.wait_quiet, F.text.regexp(r"^\d{2}:\d{2}-\d{2}:\d{2}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_quiet_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"quiet_hours": msg.text.strip()})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "تم الحفظ ✅")

@router.callback_query(F.data == "al:cfg:maxw")
async def al_cfg_maxw(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_maxw)
    lang = _L(cb.from_user.id)
    await _safe_edit(cb, t(lang, "alerts.settings.ask_max_per_week") or "أرسل الحد الأقصى في الأسبوع:")
    await cb.answer()

@router.message(AlStates.wait_maxw, F.text.regexp(r"^\d{1,3}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_maxw_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"max_per_week": int(msg.text)})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "تم الحفظ ✅")

@router.callback_query(F.data == "al:cfg:actd")
async def al_cfg_actd(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_actd)
    lang = _L(cb.from_user.id)
    await _safe_edit(cb, t(lang, "alerts.settings.ask_active_days") or "أرسل عدد الأيام النشطة (استهداف المستخدمين خلال X يوم):")
    await cb.answer()

@router.message(AlStates.wait_actd, F.text.regexp(r"^\d{1,4}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_actd_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"active_days": int(msg.text)})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "تم الحفظ ✅")

# =============== إحصائيات / حذف / رجوع ===============
@router.callback_query(F.data == "al:stats")
async def al_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id)
    stats = _load_json(STATS_FILE) or {}
    wk = max(stats.keys()) if stats else "-"
    body = stats.get(wk, {}) if wk != "-" else {}
    txt = [t(lang, "alerts.stats.header") or "إحصائيات هذا الأسبوع:"]
    if wk != "-":
        txt.append(f"Week {wk}: app_update={body.get('app_update',0)}, maintenance={body.get('maintenance',0)}")
    else:
        txt.append("No data yet")
    await _safe_edit(cb, "\n".join(txt)); await cb.answer()

@router.callback_query(F.data == "al:del")
async def al_del(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    _save_draft({"en": "", "ar": "", "lang_mode": DEFAULT_LANG_MODE, "kind": DEFAULT_KIND, "await": "", "ttl": 0})
    await cb.answer("OK", show_alert=True)

@router.callback_query(F.data == "al:back")
async def al_back(cb: CallbackQuery, state: FSMContext):
    lang = _L(cb.from_user.id)
    await state.clear()
    await _safe_edit(cb, t(lang, "alerts.menu.title") or "إدارة الإشعارات 🔔\nتحكم كامل: تعديل/معاينة/إرسال/جدولة/إلغاء/إعدادات.")
    await cb.message.edit_text(t(lang, "alerts.menu.title") or "إدارة الإشعارات 🔔", reply_markup=_menu_kb(lang))
    await cb.answer()
