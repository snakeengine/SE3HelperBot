from __future__ import annotations

import os, json, logging, datetime
from pathlib import Path
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from lang import t, get_user_lang

router = Router(name="report_handler")
log = logging.getLogger(__name__)

# ========= مسارات البيانات =========
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "report_settings.json"
STATE_FILE    = DATA_DIR / "report_users.json"
LOG_FILE      = DATA_DIR / "reports_log.json"

# جلسات محادثة المطوّر
THREADS_FILE  = DATA_DIR / "support_threads.json"

# نتائج التقييم بعد الإغلاق
FEEDBACK_FILE = DATA_DIR / "report_feedback.json"

# ========= إعدادات الأدمن =========
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()] or [7360982123]

# اختياري: إرسال تنبيه أيضًا إلى شات إداري عام (مجموعة/قناة/شخص)
ADMIN_ALERT_CHAT_ID = int(os.getenv("ADMIN_ALERT_CHAT_ID", "0") or 0)

log.info(f"[report] ADMIN_IDS={ADMIN_IDS}, ADMIN_ALERT_CHAT_ID={ADMIN_ALERT_CHAT_ID}")

# ========= الربط مع صندوق الوارد (اختياري) =========
# لو كان عندك الملف admin/report_inbox.py سنستخدمه لتحديث القائمة
try:
    from admin.report_inbox import _touch_thread as rin_touch_thread  # (user_id, user_name, last_text)
except Exception:
    rin_touch_thread = None

def _rin_touch(user_id: int, name: str, text: str | None = None):
    try:
        if rin_touch_thread:
            rin_touch_thread(user_id, name or "", (text or "").strip())
    except Exception as e:
        log.warning(f"[report] rin_touch failed: {e}")

# ========= ترجمة مع Fallback =========
def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = t(lang, key)
    except Exception:
        s = None
    if not s or s == key:
        return fallback
    return s

# ========= أدوات JSON عامة =========
def _load_json(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error(f"[report] load {path} error: {e}")
    return json.loads(json.dumps(default))

def _save_json(path: Path, data):
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[report] save {path} error: {e}")

# ========= إعدادات البلاغ =========
def load_settings() -> dict:
    d = _load_json(SETTINGS_FILE, {"enabled": True, "cooldown_days": 3, "banned": []})
    d.setdefault("enabled", True)
    d.setdefault("cooldown_days", 3)
    if not isinstance(d.get("banned"), list):
        d["banned"] = []
    return d

def load_state() -> dict:
    d = _load_json(STATE_FILE, {"last": {}})
    d.setdefault("last", {})
    return d

def save_state(d: dict):
    _save_json(STATE_FILE, d)

def append_log(item: dict):
    log_data = _load_json(LOG_FILE, [])
    log_data.append(item)
    _save_json(LOG_FILE, log_data)

# ========= جلسات المحادثة (تمرير رسائل المستخدم) =========
def load_threads() -> dict:
    d = _load_json(THREADS_FILE, {"users": {}})
    d.setdefault("users", {})
    return d

def save_threads(d: dict):
    _save_json(THREADS_FILE, d)

def get_thread(user_id: int) -> dict | None:
    return load_threads().get("users", {}).get(str(user_id))

def set_thread(user_id: int, *, open: bool, admin_id: int | None):
    data = load_threads()
    data.setdefault("users", {})
    data["users"][str(user_id)] = {"open": open, "admin_id": admin_id}
    save_threads(data)

def close_thread(user_id: int):
    data = load_threads()
    data.setdefault("users", {})
    rec = data["users"].get(str(user_id))
    if rec:
        rec["open"] = False
    else:
        data["users"][str(user_id)] = {"open": False, "admin_id": None}
    save_threads(data)

# ========= وقت UTC =========
def utcnow_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def parse_iso_z(s: str) -> datetime.datetime | None:
    try:
        s = s.strip()
        if s.endswith("Z"):
            s = s[:-1]
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt.astimezone(datetime.timezone.utc)
        return dt
    except Exception:
        return None

def human_remaining(td: datetime.timedelta) -> str:
    secs = int(td.total_seconds())
    if secs < 60:
        return f"{secs}s"
    mins, s = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m {s}s"
    hrs, m = divmod(mins, 60)
    if hrs < 24:
        return f"{hrs}h {m}m"
    days, h = divmod(hrs, 24)
    return f"{days}d {h}h"

# ========= FSM =========
class ReportState(StatesGroup):
    waiting_text = State()

class ChatReplyState(StatesGroup):
    waiting_text = State()

class FeedbackState(StatesGroup):
    waiting_reason = State()

# ========= كيبورد رد/إغلاق للأدمن =========
def _admin_reply_kb(user_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 " + _tf(lang, "rchat.btn_reply", "Reply"),
                              callback_data=f"rchat:reply:{user_id}")],
        [InlineKeyboardButton(text="🔒 " + _tf(lang, "rchat.btn_close", "Close chat"),
                              callback_data=f"rchat:close:{user_id}")]
    ])

# ========= كيبورد تقييم الإغلاق للمستخدم =========
def _feedback_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_tf(lang, "rfb.yes", "نعم ✅"), callback_data="rfb:yes"),
            InlineKeyboardButton(text=_tf(lang, "rfb.no",  "لا ❌"),  callback_data="rfb:no"),
        ],
        [InlineKeyboardButton(text=_tf(lang, "rfb.skip", "إغلاق بدون تقييم"), callback_data="rfb:skip")]
    ])

# ========= معلومات الميديا في الرسالة =========
def _msg_media_info(m: Message):
    """يرجع (نوع_الميديا, file_id) أو (None, None) إذا لا توجد ميديا"""
    if m.photo:
        return "photo", m.photo[-1].file_id
    if getattr(m, "video", None):
        return "video", m.video.file_id
    if getattr(m, "document", None):
        return "document", m.document.file_id
    if getattr(m, "animation", None):
        return "animation", m.animation.file_id
    if getattr(m, "voice", None):
        return "voice", m.voice.file_id
    if getattr(m, "audio", None):
        return "audio", m.audio.file_id
    if getattr(m, "video_note", None):
        return "video_note", m.video_note.file_id
    return None, None

# ========= Helper: إرسال تنبيه لأدمن واحد مع نسخ الرسالة =========
async def _try_notify_one(m: Message, aid: int, user_id: int, admin_msg: str) -> bool:
    a_lang = get_user_lang(aid) or "en"
    try:
        await m.bot.send_message(aid, admin_msg, reply_markup=_admin_reply_kb(user_id, a_lang))
        log.info(f"[report] notify text -> {aid} OK")
        try:
            await m.bot.copy_message(chat_id=aid, from_chat_id=m.chat.id, message_id=m.message_id)
            log.info(f"[report] copy_message -> {aid} OK")
        except Exception as e:
            log.warning(f"[report] copy_message -> {aid} failed: {e}")
        return True
    except Exception as e:
        log.warning(f"[report] notify text -> {aid} failed: {e}")
        return False

# ========= إرسال تنبيه لكل الأدمن =========
async def _notify_admins_new_report(m: Message, user_id: int, text: str):
    admin_msg = (
        f"⚠️ <b>New Report</b>\n"
        f"• ID: <code>{user_id}</code>\n"
        f"• Name: {m.from_user.full_name}\n"
        f"• Username: @{m.from_user.username if m.from_user.username else '-'}\n"
        f"• Date: <code>{utcnow_iso()}</code>\n"
        f"— — —\n{text}"
    )
    targets = list(set(ADMIN_IDS + ([ADMIN_ALERT_CHAT_ID] if ADMIN_ALERT_CHAT_ID else [])))
    success = False
    for aid in targets:
        ok = await _try_notify_one(m, aid, user_id, admin_msg)
        success = success or ok

    if not success and (m.from_user.id in ADMIN_IDS):
        lang = get_user_lang(m.from_user.id) or "en"
        try:
            await m.answer("🔔 <b>Admin Copy</b>\n" + admin_msg, reply_markup=_admin_reply_kb(user_id, lang))
            log.info("[report] local admin fallback shown")
        except Exception as e:
            log.error(f"[report] local admin fallback failed: {e}")

# ========= /report =========
@router.message(Command("report"))
async def report_cmd(m: Message, state: FSMContext):
    user_id = m.from_user.id
    lang = get_user_lang(user_id) or "en"

    st = load_settings()
    if not st.get("enabled", True):
        return await m.reply(_tf(lang, "report.disabled", "خدمة البلاغات متوقفة مؤقتاً."))
    if user_id in st.get("banned", []):
        return await m.reply(_tf(lang, "report.banned", "عذراً، لا يمكنك إرسال بلاغ."))

    cd_days = int(st.get("cooldown_days", 0) or 0)
    if cd_days > 0:
        last_iso = load_state().get("last", {}).get(str(user_id))
        if last_iso:
            last_dt = parse_iso_z(last_iso)
            if last_dt:
                now = datetime.datetime.now(datetime.timezone.utc)
                next_allowed = last_dt + datetime.timedelta(days=cd_days)
                if now < next_allowed:
                    remain = human_remaining(next_allowed - now)
                    return await m.reply(_tf(lang, "report.cooldown_wait", "يرجى الانتظار {remaining} قبل إرسال بلاغ آخر.").format(remaining=remain))

    await state.set_state(ReportState.waiting_text)
    await m.reply(_tf(lang, "report.prompt", "أرسل وصف مشكلتك بالتفصيل (صور/فيديو إن لزم)."))

@router.message(ReportState.waiting_text)
async def report_receive_any(m: Message, state: FSMContext):
    user_id = m.from_user.id
    lang = get_user_lang(user_id) or "en"

    # نحدد إن كانت الرسالة تحتوي ميديا ونأخذ الكابتشن إن وجد
    media_type, media_file_id = _msg_media_info(m)
    is_media = media_type is not None
    text = ((m.caption or "") if is_media else (m.text or "")).strip()

    # لو ما فيه ميديا: نطبّق شرط الحد الأدنى 10 أحرف
    if not is_media and len(text) < 10:
        return await m.reply(_tf(lang, "report.too_short", "الرسالة قصيرة جدًا. أرسل تفاصيل أكثر."))

    # نسجّل في اللوج
    append_log({
        "user_id": user_id,
        "username": m.from_user.username,
        "first_name": m.from_user.first_name,
        "date": utcnow_iso(),
        "text": text,
        "message_id": m.message_id,
        "chat_id": m.chat.id,
        "has_media": is_media,
        "media_type": media_type,
        "media_file_id": media_file_id,
    })

    # افتح الجلسة
    set_thread(user_id, open=True, admin_id=None)

    # حدّث صندوق الوارد فورًا
    display_text = text if text else "(media)"
    _rin_touch(user_id, m.from_user.full_name or m.from_user.username or str(user_id), display_text)

    # أبلغ الأدمنين (وتُنسخ الرسالة نفسها سواء نص/ميديا)
    await _notify_admins_new_report(m, user_id, display_text)

    # حدّث آخر وقت بلاغ
    st = load_state(); st.setdefault("last", {})[str(user_id)] = utcnow_iso(); save_state(st)

    await state.clear()
    await m.reply(_tf(lang, "report.saved", "تم استلام بلاغك ✅"))

# ========= الأدمن يضغط "رد" =========
@router.callback_query(F.data.startswith("rchat:reply:"))
async def rchat_reply_start(cb: CallbackQuery, state: FSMContext):
    admin_id = cb.from_user.id
    lang = get_user_lang(admin_id) or "en"
    if admin_id not in ADMIN_IDS:
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)

    try:
        user_id = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer()

    await state.set_state(ChatReplyState.waiting_text)
    await state.update_data(target_user_id=user_id)
    await cb.message.answer(_tf(lang, "rchat.reply_prompt", "أرسل الرد الذي تريد إرساله للمستخدم (يمكنك إرسال نص/صورة/فيديو):"))
    await cb.answer()

@router.message(ChatReplyState.waiting_text)
async def rchat_reply_send(m: Message, state: FSMContext):
    admin_id = m.from_user.id
    lang = get_user_lang(admin_id) or "en"
    if admin_id not in ADMIN_IDS:
        return await m.reply(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."))

    data = await state.get_data()
    user_id = int(data.get("target_user_id"))
    await state.clear()

    # أرسل نفس رسالة الأدمن للمستخدم (copy للحفاظ على الوسائط)
    try:
        await m.copy_to(chat_id=user_id)
    except Exception:
        u_lang = get_user_lang(user_id) or "en"
        await m.bot.send_message(user_id, _tf(u_lang, "rchat.dev_reply", "تم استلام ردّ الدعم."))

    set_thread(user_id, open=True, admin_id=admin_id)

    media_type, _ = _msg_media_info(m)
    content = (m.caption if media_type else m.text) or "(media)"
    _rin_touch(user_id, str(user_id), f"Dev: {content}")

    await m.reply(_tf(lang, "rchat.sent_ok", "تم الإرسال ✅"))

# ========= إنهاء المحادثة (من الأدمن) + إرسال تقييم للمستخدم =========
@router.callback_query(F.data.startswith("rchat:close:"))
async def rchat_close(cb: CallbackQuery):
    admin_id = cb.from_user.id
    lang = get_user_lang(admin_id) or "en"
    if admin_id not in ADMIN_IDS:
        return await cb.answer(_tf(lang, "admins_only", "هذه الأداة للأدمن فقط."), show_alert=True)

    try:
        user_id = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer()

    close_thread(user_id)

    # أرسل للمستخدم استبيان الإغلاق
    u_lang = get_user_lang(user_id) or "ar"
    try:
        await cb.bot.send_message(
            chat_id=user_id,
            text=_tf(u_lang, "rfb.q", "هل تم حل مشكلتك؟"),
            reply_markup=_feedback_kb(u_lang)
        )
    except Exception as e:
        log.warning(f"[report] send feedback to {user_id} failed: {e}")

    await cb.answer(_tf(lang, "rchat.closed", "تم إغلاق المحادثة."), show_alert=True)

# ========= حفظ وإشعار التقييم =========
def _save_feedback(rec: dict):
    data = _load_json(FEEDBACK_FILE, [])
    data.append(rec)
    _save_json(FEEDBACK_FILE, data)

async def _notify_admins_feedback(bot, rec: dict):
    msg = (
        "🧾 <b>Report Feedback</b>\n"
        f"• User: <code>{rec['user_id']}</code>\n"
        f"• Result: <b>{rec['result']}</b>\n"
        f"• Time: <code>{rec['time']}</code>\n"
    )
    if rec.get("reason"):
        msg += f"• Reason: {rec['reason']}\n"

    # بدون تكرار أهداف
    targets = list(set(ADMIN_IDS + ([ADMIN_ALERT_CHAT_ID] if ADMIN_ALERT_CHAT_ID else [])))
    for aid in targets:
        try:
            await bot.send_message(aid, msg)
        except Exception:
            pass

@router.callback_query(F.data.in_(["rfb:yes", "rfb:no", "rfb:skip"]))
async def rfb_choice(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = get_user_lang(uid) or "ar"
    choice = cb.data.split(":")[1]

    if choice == "yes":
        rec = {"user_id": uid, "result": "solved", "reason": "", "time": utcnow_iso()}
        _save_feedback(rec)
        await _notify_admins_feedback(cb.bot, rec)
        await cb.message.edit_text(_tf(lang, "rfb.thx_yes", "سعدنا بحل مشكلتك ✅"))
        return await cb.answer("✅")

    if choice == "skip":
        rec = {"user_id": uid, "result": "skipped", "reason": "", "time": utcnow_iso()}
        _save_feedback(rec)
        await _notify_admins_feedback(cb.bot, rec)
        await cb.message.edit_text(_tf(lang, "rfb.closed", "تم إغلاق البلاغ."))
        return await cb.answer("✅")

    # choice == "no"
    await state.set_state(FeedbackState.waiting_reason)
    await cb.message.edit_text(_tf(lang, "rfb.ask_reason", "لم تُحل المشكلة؟ أخبرنا بالمشكلة بإيجاز:"))
    await cb.answer()

@router.message(FeedbackState.waiting_reason)
async def rfb_reason(m: Message, state: FSMContext):
    uid = m.from_user.id
    lang = get_user_lang(uid) or "ar"
    reason = (m.text or "").strip()[:500]
    await state.clear()

    rec = {"user_id": uid, "result": "not_solved", "reason": reason, "time": utcnow_iso()}
    _save_feedback(rec)
    await _notify_admins_feedback(m.bot, rec)

    await m.reply(_tf(lang, "rfb.thx_no", "شكرًا، تم تسجيل السبب وسنراجعه."))

# ========= جسر رسائل المستخدم أثناء الجلسة =========
@router.message(F.chat.type == "private")
async def user_chat_bridge(m: Message):
    # لا نتدخل بالأوامر
    if m.text and m.text.startswith("/"):
        return

    th = get_thread(m.from_user.id)
    if not th or not th.get("open"):
        return

    admin_id = th.get("admin_id") or (ADMIN_IDS[0] if ADMIN_IDS else None)
    if not admin_id:
        return

    # ننسخ رسالة المستخدم للأدمن
    try:
        await m.copy_to(chat_id=admin_id)
    except Exception as e:
        log.warning(f"[report] forward to admin failed: {e}")
        try:
            await m.bot.send_message(admin_id, f"👤 <b>User</b> <code>{m.from_user.id}</code>:\n{m.text or '-'}")
        except Exception as e2:
            log.error(f"[report] send text to admin failed: {e2}")

    a_lang = get_user_lang(admin_id) or "en"
    try:
        await m.bot.send_message(
            admin_id,
            _tf(a_lang, "rchat.user_reply_header", "Reply to the user:"),
            reply_markup=_admin_reply_kb(m.from_user.id, a_lang)
        )
    except Exception:
        pass

    # لمس الوارد
    media_type, _ = _msg_media_info(m)
    last_content = (m.caption if media_type else m.text) or "(media)"
    _rin_touch(
        m.from_user.id,
        m.from_user.full_name or m.from_user.username or str(m.from_user.id),
        last_content
    )
