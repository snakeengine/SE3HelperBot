from __future__ import annotations

# handlers/report.py


import os, json, logging, datetime, re, time
from pathlib import Path
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from lang import t, get_user_lang
from services import admin_roles  # ← فصل صلاحيات الأدمن عبر roles

router = Router(name="report_handler")
log = logging.getLogger(__name__)

# احصر الراوتر على الخاص لتفادي أي تضارب
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

# نحصر الكولباكات على نطاق الراوتر فقط لمنع التعارض
router.callback_query.filter(
    lambda cq: ((cq.data or "").startswith("rchat:")
                or (cq.data or "").startswith("rfb:")
                or (cq.data or "").startswith("rpadm:"))
)

# ===== ملفات التخزين =====
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE  = DATA_DIR / "report_settings.json"
STATE_FILE     = DATA_DIR / "report_users.json"
LOG_FILE       = DATA_DIR / "reports_log.json"
THREADS_FILE   = DATA_DIR / "support_threads.json"
FEEDBACK_FILE  = DATA_DIR / "report_feedback.json"
BLOCKLIST_FILE = DATA_DIR / "report_blocklist.json"

# ===== Alerts mute list (per-admin) =====
ALERTS_MUTE_FILE = DATA_DIR / "report_alerts_mute.json"

def _alerts_mute_read() -> set[int]:
    try:
        raw = _load_json(ALERTS_MUTE_FILE, [])
        return {int(x) for x in (raw or []) if str(x).isdigit()}
    except Exception:
        return set()

def _alerts_mute_write(s: set[int]) -> None:
    _save_json(ALERTS_MUTE_FILE, sorted(list(s)))

def _alerts_is_muted(uid: int) -> bool:
    return int(uid) in _alerts_mute_read()

def _alerts_mute(uid: int) -> None:
    s = _alerts_mute_read(); s.add(int(uid)); _alerts_mute_write(s)

def _alerts_unmute(uid: int) -> None:
    s = _alerts_mute_read(); s.discard(int(uid)); _alerts_mute_write(s)

# ===== إشعار إضافي اختياري (قناة/شات) =====
ADMIN_ALERT_CHAT_ID = int(os.getenv("ADMIN_ALERT_CHAT_ID", "0") or 0)

# --- تطبيع نص عربي للتمييز على أزرار الكيبورد السفلية ---
_AR_MAP = str.maketrans({"أ":"ا","إ":"ا","آ":"ا","ى":"ي","ئ":"ي","ؤ":"و","ة":"ه","ٔ":"", "ٰ":"", "ـ":""})

def _normalize_label(s: str) -> str:
    s = s or ""
    s = "".join(ch for ch in s if ch.isprintable())
    s = s.translate(_AR_MAP)
    s = re.sub(r"[^A-Za-z\u0600-\u06FF]+", " ", s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

_MENU_KEYWORDS = {
    "user","vip","bot","group","groups","channel","channels","forum","forums",
    "المستخدم","بريميوم","vip","البوت","المجموعات","القنوات","المنتديات","اخفاء اللوحه","اخفاء اللوحة","hide panel"
}

def _looks_like_menu_button(text: str) -> bool:
    n = _normalize_label(text)
    return any(k in n for k in _MENU_KEYWORDS)

# ===== تحقّق أدمن عبر دور reports/default =====
async def _is_admin(uid: int) -> bool:
    ids = set(await admin_roles.get_admins("reports")) | set(await admin_roles.get_admins("default"))
    return int(uid) in ids

# (اختياري) صندوق وارد الأدمن
try:
    from admin.report_inbox import _touch_thread as rin_touch_thread
except Exception:
    rin_touch_thread = None

def _rin_touch(uid: int, name: str, text: str | None = None):
    try:
        if rin_touch_thread:
            rin_touch_thread(uid, name or "", (text or "").strip())
    except Exception as e:
        log.warning(f"[report] rin_touch failed: {e}")

# ===== ترجمات قصيرة =====
def _tf(lang: str, key: str, fallback: str) -> str:
    try:
        s = t(lang, key)
    except Exception:
        s = None
    return fallback if not s or s == key else s

def _tx(lang: str, key: str, ar_fallback: str, en_fallback: str) -> str:
    """Fallback آمن عربي/إنجليزي."""
    try:
        s = t(lang, key)
        if s and s != key:
            return s
    except Exception:
        pass
    return ar_fallback if str(lang).lower().startswith("ar") else en_fallback

# ===== IO =====
def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"[report] load {path} error: {e}")
    return json.loads(json.dumps(default))

def _save_json(path: Path, data):
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:
        log.error(f"[report] save {path} error: {e}")

# ===== إعدادات وجداول =====
def load_settings() -> dict:
    d = _load_json(SETTINGS_FILE, {"enabled": True, "cooldown_hours": 12, "banned": []})
    d.setdefault("enabled", True)
    if "cooldown_hours" not in d:
        days = int(d.get("cooldown_days", 0) or 0)
        d["cooldown_hours"] = (days * 24) if days > 0 else 12
    if not isinstance(d.get("banned"), list):
        d["banned"] = []
    return d

def load_state() -> dict:
    d = _load_json(STATE_FILE, {"last": {}})
    d.setdefault("last", {})
    return d

def save_state(d: dict): _save_json(STATE_FILE, d)

def append_log(item: dict):
    data = _load_json(LOG_FILE, []); data.append(item); _save_json(LOG_FILE, data)

def load_threads() -> dict:
    d = _load_json(THREADS_FILE, {"users": {}}); d.setdefault("users", {}); return d

def save_threads(d: dict): _save_json(THREADS_FILE, d)

def get_thread(user_id: int) -> dict | None:
    return (load_threads().get("users") or {}).get(str(user_id))

def set_thread(user_id: int, *, open: bool, admin_id: int | None):
    d = load_threads(); d.setdefault("users", {})
    d["users"][str(user_id)] = {"open": open, "admin_id": admin_id}
    save_threads(d)

def close_thread(user_id: int):
    d = load_threads(); d.setdefault("users", {})
    rec = d["users"].get(str(user_id))
    if rec: rec["open"] = False
    else:   d["users"][str(user_id)] = {"open": False, "admin_id": None}
    save_threads(d)

def delete_thread(user_id: int):
    d = load_threads(); d.setdefault("users", {})
    if str(user_id) in d["users"]:
        d["users"].pop(str(user_id), None)
        save_threads(d)

# ===== Blocklist =====
def _bl_read() -> dict:
    d = _load_json(BLOCKLIST_FILE, {})
    return d if isinstance(d, dict) else {}

def _bl_write(d: dict) -> None:
    _save_json(BLOCKLIST_FILE, d)

def _bl_is_blocked(uid: int) -> tuple[bool, str]:
    d = _bl_read()
    rec = d.get(str(uid))
    if not rec:
        return False, ""
    if rec is True:
        return True, "∞ (permanent)"
    if isinstance(rec, dict) and "until" in rec:
        now = datetime.datetime.utcnow().timestamp()
        if now < float(rec["until"]):
            remain = int(float(rec["until"]) - now)
            days, rem = divmod(remain, 86400); hours, rem = divmod(rem, 3600); mins, _ = divmod(rem, 60)
            parts = []
            if days: parts.append(f"{days}d")
            if hours: parts.append(f"{hours}h")
            if mins: parts.append(f"{mins}m")
            return True, " ".join(parts) or f"{remain}s"
        else:
            d.pop(str(uid), None); _bl_write(d)
    return False, ""

def _bl_ban(uid: int, duration_hours: int | None):
    d = _bl_read()
    if duration_hours is None:
        d[str(uid)] = True
    else:
        until = datetime.datetime.utcnow().timestamp() + int(duration_hours) * 3600
        d[str(uid)] = {"until": until}
    _bl_write(d)

def _bl_unban(uid: int):
    d = _bl_read(); d.pop(str(uid), None); _bl_write(d)

# ===== وقت =====
def utcnow_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def parse_iso_z(s: str) -> datetime.datetime | None:
    try:
        s = s.strip();  s = s[:-1] if s.endswith("Z") else s
        dt = datetime.datetime.fromisoformat(s)
        return dt.replace(tzinfo=datetime.timezone.utc) if dt.tzinfo is None else dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None

def human_remaining(td: datetime.timedelta) -> str:
    secs = int(td.total_seconds())
    if secs < 60: return f"{secs}s"
    mins, s = divmod(secs, 60)
    if mins < 60: return f"{mins}m {s}s"
    hrs, m = divmod(mins, 60)
    if hrs < 24: return f"{hrs}h {m}m"
    days, h = divmod(hrs, 24);  return f"{days}d {h}h"

# ===== FSM =====
class ReportState(StatesGroup):    waiting_text = State()
class ChatReplyState(StatesGroup): waiting_text = State()
class FeedbackState(StatesGroup):  waiting_reason = State()

# ===== أدوات ميديا =====
def _msg_media_info(m: Message):
    if m.photo: return "photo", m.photo[-1].file_id
    if getattr(m, "video", None): return "video", m.video.file_id
    if getattr(m, "document", None): return "document", m.document.file_id
    if getattr(m, "animation", None): return "animation", m.animation.file_id
    if getattr(m, "voice", None): return "voice", m.voice.file_id
    if getattr(m, "audio", None): return "audio", m.audio.file_id
    if getattr(m, "video_note", None): return "video_note", m.video_note.file_id
    return None, None

# ===== لوحة تحكم الأدمن على البلاغ =====
def _ban_btn_text(lang: str, hours: int) -> str:
    if hours < 24:
        return "🚫 " + _tx(lang, "rpadm.ban_hour", "حظر: {n} س", "Ban: {n} h").format(n=hours)
    days = hours // 24
    if lang.startswith("ar"):
        unit = "يوم" if days == 1 else "أيام"
        return f"🚫 حظر: {days} {unit}"
    return "🚫 " + _tx(lang, "rpadm.ban_days", "Ban: {n} d", "Ban: {n} d").format(n=days)

def _admin_controls_kb(user_id: int, lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💬 " + _tx(lang, "rchat.btn_reply", "ردّ", "Reply"),
                              callback_data=f"rchat:reply:{user_id}")],
        [InlineKeyboardButton(text="🔒 " + _tx(lang, "rchat.btn_close", "إنهاء المحادثة", "Close chat"),
                              callback_data=f"rchat:close:{user_id}")],
        [
            InlineKeyboardButton(text=_ban_btn_text(lang, 1),           callback_data=f"rpadm:ban:{user_id}:1"),
            InlineKeyboardButton(text=_ban_btn_text(lang, 24),          callback_data=f"rpadm:ban:{user_id}:24"),
        ],
        [
            InlineKeyboardButton(text=_ban_btn_text(lang, 24*7),        callback_data=f"rpadm:ban:{user_id}:{24*7}"),
            InlineKeyboardButton(text=_ban_btn_text(lang, 24*30),       callback_data=f"rpadm:ban:{user_id}:{24*30}"),
        ],
        [
            InlineKeyboardButton(text="🚫 " + _tx(lang, "rpadm.ban_perm", "حظر دائم ∞", "Permanent ban ∞"),
                                 callback_data=f"rpadm:ban:{user_id}:perm"),
            InlineKeyboardButton(text="✅ " + _tx(lang, "rpadm.unban", "رفع الحظر", "Unban"),
                                 callback_data=f"rpadm:unban:{user_id}"),
        ],
        [
            InlineKeyboardButton(text="ℹ️ " + _tx(lang, "rpadm.btn_info", "معلومات المستخدم", "User info"),
                                 callback_data=f"rpadm:info:{user_id}"),
            InlineKeyboardButton(text="🧹 " + _tx(lang, "rpadm.btn_clear_cd", "تصفير التبريد", "Clear cooldown"),
                                 callback_data=f"rpadm:clearcd:{user_id}"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== إشعار الأدمن ببلاغ جديد =====
async def _notify_admins_new_report(m: Message, user_id: int, text: str):
    admin_msg = (
        "⚠️ <b>New Report</b>\n"
        f"• ID: <code>{user_id}</code>\n"
        f"• Name: {m.from_user.full_name}\n"
        f"• Username: @{m.from_user.username if m.from_user.username else '-'}\n"
        f"• Date: <code>{utcnow_iso()}</code>\n"
        "— — —\n" + text
    )
    targets = set(await admin_roles.get_admins("reports"))
    if ADMIN_ALERT_CHAT_ID:
        targets.add(ADMIN_ALERT_CHAT_ID)
    muted = _alerts_mute_read()
    targets = {aid for aid in targets if int(aid) not in muted}
    for aid in targets:
        try:
            a_lang = get_user_lang(aid) or "en"
            await m.bot.send_message(aid, admin_msg, reply_markup=_admin_controls_kb(user_id, a_lang))
            try:
                await m.bot.copy_message(chat_id=aid, from_chat_id=m.chat.id, message_id=m.message_id)
            except Exception as e:
                log.warning(f"[report] copy_message -> {aid} failed: {e}")
        except Exception as e:
            log.warning(f"[report] notify -> {aid} failed: {e}")

# ===== /report =====
def _cooldown_hours() -> int:
    st = load_settings()
    try:
        return max(0, int(st.get("cooldown_hours", 12)))
    except Exception:
        return 12

def _next_allowed_dt(user_id: int) -> Optional[datetime.datetime]:
    last_iso = load_state().get("last", {}).get(str(user_id))
    if not last_iso:
        return None
    last_dt = parse_iso_z(last_iso)
    if not last_dt:
        return None
    return last_dt + datetime.timedelta(hours=_cooldown_hours())

def _has_active_cooldown(user_id: int) -> bool:
    nxt = _next_allowed_dt(user_id)
    if not nxt:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return now < nxt

@router.message(StateFilter(None), F.text.func(lambda s: isinstance(s, str) and s.lstrip().lower().startswith("/report")))
async def report_cmd_fallback(m: Message, state: FSMContext):
    return await report_cmd(m, state)

@router.message(Command("report"))
async def report_cmd(m: Message, state: FSMContext):
    user_id = m.from_user.id
    lang = (get_user_lang(user_id) or "en").lower()
    is_admin = await _is_admin(user_id)

    st = load_settings()
    if not st.get("enabled", True) and not is_admin:
        return await m.reply(_tx(
            lang, "report.disabled",
            "خدمة البلاغات متوقفة مؤقتاً.",
            "Reporting is temporarily disabled."
        ))

    # blocklist / banned / cooldown — الأدمن مُعفى
    if not is_admin:
        blocked, remain = _bl_is_blocked(user_id)
        if blocked:
            return await m.reply(_tx(
                lang, "report.blocked",
                f"⛔ تم تقييد ميزة البلاغات لديك ({remain}).",
                f"⛔ Reporting is restricted for you ({remain})."
            ))
        if user_id in st.get("banned", []):
            return await m.reply(_tx(
                lang, "report.banned",
                "عذراً، لا يمكنك إرسال بلاغ.",
                "Sorry, you cannot send a report."
            ))
        nxt = _next_allowed_dt(user_id)
        if nxt:
            now = datetime.datetime.now(datetime.timezone.utc)
            if now < nxt:
                remain = human_remaining(nxt - now)
                return await m.reply(_tx(
                    lang, "report.cooldown_wait",
                    "لديك بلاغ سابق. يرجى الانتظار {remaining} قبل إرسال بلاغ جديد."
                    .format(remaining=remain),
                    "You already have a report. Please wait {remaining} before sending another."
                    .format(remaining=remain)
                ))

    await state.set_state(ReportState.waiting_text)
    await m.reply(_tx(
        lang, "report.prompt",
        "✍️ أرسل وصف مشكلتك بالتفصيل. يمكنك أيضًا إرسال صورة/فيديو مع تعليق.",
        "✍️ Describe your issue in detail. You may also send a photo/video with a caption."
    ))

# ===== أثناء كتابة البلاغ: /cancel فقط =====
@router.message(StateFilter(ReportState.waiting_text), Command("cancel"))
async def report_cancel_cmd(m: Message, state: FSMContext):
    lang = (get_user_lang(m.from_user.id) or "ar").lower()
    await state.clear()
    await m.reply(_tx(lang, "report.cancelled",
                      "تم إلغاء البلاغ. يمكنك استخدام /report مجددًا عند الحاجة.",
                      "Report canceled. You can use /report again when needed."))

@router.message(StateFilter(ReportState.waiting_text),
                F.text.func(lambda s: isinstance(s, str) and s.startswith("/") and not s.lower().startswith("/cancel")))
async def report_block_commands(m: Message, state: FSMContext):
    lang = (get_user_lang(m.from_user.id) or "ar").lower()
    await m.reply(_tx(lang, "report.no_cmd_in_state",
                      "أنت الآن تكتب بلاغًا. أرسل التفاصيل أو استخدم /cancel.",
                      "You're currently writing a report. Send the details or use /cancel."))

# ===== استلام رسالة البلاغ =====
# ===== استلام رسالة البلاغ =====
@router.message(ReportState.waiting_text)
async def report_receive_any(m: Message, state: FSMContext):
    user_id = m.from_user.id
    lang = (get_user_lang(user_id) or "en").lower()

    # محظور؟
    blocked, remain = _bl_is_blocked(user_id)
    if blocked:
        await state.clear()
        return await m.reply(_tx(lang, "report.blocked",
                                 f"⛔ تم تقييد ميزة البلاغات لديك ({remain}).",
                                 f"⛔ Reporting is restricted for you ({remain})."))

    # نص/ميديا
    media_type, media_file_id = _msg_media_info(m)
    is_media = media_type is not None
    text = ((m.caption or "") if is_media else (m.text or "")).strip()

    if not is_media and len(text) < 10:
        return await m.reply(_tx(lang, "report.too_short",
                                 "الرسالة قصيرة جدًا. أرسل تفاصيل أكثر.",
                                 "The message is too short. Please provide more details."))

    # ✅ ثبّت التبريد أولًا (قبل أي إشعار) + انهي الحالة مباشرة لتفادي التكرار
    st = load_state(); st.setdefault("last", {})[str(user_id)] = utcnow_iso(); save_state(st)
    await state.clear()

    # سجّل البلاغ في اللوج
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

    # أنشئ جلسة معلّقة بانتظار رد الأدمن (الجسر يُفتح بعد أول رد)
    set_thread(user_id, open=False, admin_id=None)

    # صندوق وارد موحّد (اختياري)
    try:
        from utils.support_inbox import enqueue
        preview = (text if text else "(media)")[:200]
        enqueue("report", user_id, preview)
    except Exception:
        pass

    # لمس صندوق الوارد الإضافي
    display_text = text if text else "(media)"
    _rin_touch(user_id, m.from_user.full_name or m.from_user.username or str(user_id), display_text)

    # إشعار الأدمنين (سيصل مرّة واحدة فقط؛ أي محاولة ثانية سيوقفها التبريد)
    await _notify_admins_new_report(m, user_id, display_text)

    # رسالة تأكيد + مدة التبريد
    cd_hours = _cooldown_hours()
    ar_fallback = f"تم استلام بلاغك ✅ سنراجعه قريبًا.\nيمكنك إرسال بلاغ جديد بعد: {cd_hours} ساعة."
    en_fallback = f"Your report was received ✅ We'll review it soon.\nYou can send a new report after: {cd_hours}h."
    confirmation = _tx(lang, "report.saved_full", ar_fallback, en_fallback)

    await m.reply(confirmation, reply_markup=ReplyKeyboardRemove())

# ===== حارس: pending =====
# منع سبام التذكير
_last_pending_notice: dict[int, float] = {}
_PENDING_COOLDOWN_SEC = 600  # 10 دقائق

def _has_pending_report(m: Message) -> bool:
    if not m.from_user:
        return False

    # لا نتعامل إلا مع نص أو كابشن لميديا
    text_like = (m.text or m.caption or "")
    if not text_like.strip():
        return False

    # تجاهل الأوامر
    if m.text and m.text.startswith("/"):
        return False

    # تجاهل أزرار/كلمات القائمة
    if m.text and _looks_like_menu_button(m.text):
        return False

    th = get_thread(m.from_user.id)

    # 🔧 تنظيف تلقائي: إن كان لا يوجد تبريد فعّال، احذف أي سجل جلسة قديم
    if th and not th.get("open") and not _has_active_cooldown(m.from_user.id):
        delete_thread(m.from_user.id)
        return False

    # اعتبره "قيد المراجعة" فقط مع تبريد فعّال
    return bool(th and not th.get("open") and _has_active_cooldown(m.from_user.id))

@router.message(StateFilter(None), F.func(_has_pending_report))
async def pending_guard(m: Message):
    if await _is_admin(m.from_user.id):
        return

    now = time.time()
    last = _last_pending_notice.get(m.from_user.id, 0.0)
    if now - last < _PENDING_COOLDOWN_SEC:
        return  # لا نكرر التنبيه كثيرًا
    _last_pending_notice[m.from_user.id] = now

    lang = get_user_lang(m.from_user.id) or "en"
    nxt = _next_allowed_dt(m.from_user.id)
    if nxt:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        if now_dt < nxt:
            remain = human_remaining(nxt - now_dt)
            return await m.reply(_tx(
                lang, "report.wait_processing",
                "لديك بلاغ قيد المراجعة. يرجى الانتظار {remaining}.",
                "You already have a report under review. Please wait {remaining}."
            ).format(remaining=remain))

    await m.reply(_tx(
        lang, "report.wait_short",
        "تم استلام بلاغك، يرجى الانتظار إلى حين ردّ الدعم.",
        "We received your report; please wait for support to reply."
    ))

# ===== جسر رسائل المستخدم (بعد فتح الجسر) =====
def _should_bridge(m: Message) -> bool:
    """فلتر دقيق يمنع الإمساك العام لرسائل الخاص."""
    if not m or not m.from_user: return False
    if getattr(m, "chat", None) and getattr(m.chat, "type", "") != "private": return False
    if m.text and m.text.startswith("/"): return False
    if m.text and _looks_like_menu_button(m.text): return False
    blocked, _ = _bl_is_blocked(m.from_user.id)
    if blocked: return False
    th = get_thread(m.from_user.id)
    return bool(th and th.get("open"))

@router.message(StateFilter(None), F.func(_should_bridge))
async def user_chat_bridge(m: Message, state: FSMContext):
    if await _is_admin(m.from_user.id):
        return
    th = get_thread(m.from_user.id)
    if not (th and th.get("open")):
        return

    # اختيار الأدمن المسؤول
    role_admins = await admin_roles.get_admins("reports")
    admin_id = (th or {}).get("admin_id") or (role_admins[0] if role_admins else None)
    if not admin_id or admin_id == m.from_user.id:
        return

    # توصيل الرسالة
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
            _tx(a_lang, "rchat.user_reply_header", "ردّ على المستخدم:", "Reply to the user:"),
            reply_markup=_admin_controls_kb(m.from_user.id, a_lang)
        )
    except Exception:
        pass

    content = (m.caption if getattr(m, "caption", None) else m.text) or "(media)"
    _rin_touch(m.from_user.id, m.from_user.full_name or m.from_user.username or str(m.from_user.id), content)

# ===== ردّ/إغلاق من الأدمن =====
@router.callback_query(F.data.startswith("rchat:reply:"))
async def rchat_reply_start(cb: CallbackQuery, state: FSMContext):
    if not (await _is_admin(cb.from_user.id)):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l, "admins_only", "هذه الأداة للأدمن فقط.", "Admins only."), show_alert=True)
    try:
        target = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer()
    await state.set_state(ChatReplyState.waiting_text)
    await state.update_data(target_user_id=target)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer(_tx(lang, "rchat.reply_prompt",
                                "أرسل الرد الذي تريد إرساله للمستخدم (يمكنك إرسال نص/صورة/فيديو):",
                                "Send the reply to the user (you can send text/photo/video):"))
    await cb.answer()

@router.message(ChatReplyState.waiting_text)
async def rchat_reply_send(m: Message, state: FSMContext):
    if not (await _is_admin(m.from_user.id)):
        l = get_user_lang(m.from_user.id) or "en"
        return await m.reply(_tx(l, "admins_only", "هذه الأداة للأدمن فقط.", "Admins only."))
    data = await state.get_data()
    uid = int(data.get("target_user_id"))
    await state.clear()
    try:
        await m.copy_to(chat_id=uid)
    except Exception:
        u_lang = get_user_lang(uid) or "en"
        await m.bot.send_message(uid, _tx(u_lang, "rchat.dev_reply",
                                          "تم استلام ردّ الدعم.", "Support reply received."))
    # فتح الجسر بعد أول رد من الأدمن
    set_thread(uid, open=True, admin_id=m.from_user.id)
    await m.reply(_tx(get_user_lang(m.from_user.id) or "en", "rchat.sent_ok", "تم الإرسال ✅", "Sent ✅"))

@router.callback_query(F.data.startswith("rchat:close:"))
async def rchat_close(cb: CallbackQuery):
    if not (await _is_admin(cb.from_user.id)):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l, "admins_only", "هذه الأداة للأدمن فقط.", "Admins only."), show_alert=True)
    try:
        uid = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer()
    close_thread(uid)  # إغلاق الجسر

    u_lang = get_user_lang(uid) or "ar"
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_tx(u_lang, "rfb.yes", "نعم ✅", "Yes ✅"), callback_data="rfb:yes"),
             InlineKeyboardButton(text=_tx(u_lang, "rfb.no", "لا ❌", "No ❌"), callback_data="rfb:no")],
            [InlineKeyboardButton(text=_tx(u_lang, "rfb.skip", "إغلاق بدون تقييم", "Close without rating"), callback_data="rfb:skip")]
        ])
        await cb.bot.send_message(uid, _tx(u_lang, "rfb.q", "هل تم حل مشكلتك؟", "Was your issue resolved?"), reply_markup=kb)
    except Exception as e:
        log.warning(f"[report] send feedback to {uid} failed: {e}")
    await cb.answer(_tx(get_user_lang(cb.from_user.id) or "en", "rchat.closed",
                        "تم إغلاق المحادثة.", "Conversation closed."), show_alert=True)

# ===== التقييم =====
def _save_feedback(rec: dict):
    data = _load_json(FEEDBACK_FILE, []); data.append(rec); _save_json(FEEDBACK_FILE, data)

async def _notify_admins_feedback(bot, rec: dict):
    msg = ("🧾 <b>Report Feedback</b>\n"
           f"• User: <code>{rec['user_id']}</code>\n"
           f"• Result: <b>{rec['result']}</b>\n"
           f"• Time: <code>{rec['time']}</code>\n")
    if rec.get("reason"): msg += f"• Reason: {rec['reason']}\n"
    targets = set(await admin_roles.get_admins("reports"))
    if ADMIN_ALERT_CHAT_ID:
        targets.add(ADMIN_ALERT_CHAT_ID)
    muted = _alerts_mute_read()
    targets = {aid for aid in targets if int(aid) not in muted}
    for aid in targets:
        try: await bot.send_message(aid, msg)
        except Exception: pass

@router.message(Command("alerts_off"))
async def cmd_alerts_off(m: Message):
    # فقط الأدمن الذين لديهم دور reports/default
    if not (await _only_admin(m)): 
        return
    _alerts_mute(m.from_user.id)
    await m.reply("🔕 تم إيقاف تنبيهات البلاغات لهذا الحساب.")

@router.message(Command("alerts_on"))
async def cmd_alerts_on(m: Message):
    if not (await _only_admin(m)): 
        return
    _alerts_unmute(m.from_user.id)
    await m.reply("🔔 تم تفعيل تنبيهات البلاغات لهذا الحساب.")

@router.message(Command("alerts_status"))
async def cmd_alerts_status(m: Message):
    if not (await _only_admin(m)): 
        return
    await m.reply("الحالة: " + ("🔕 متوقفة" if _alerts_is_muted(m.from_user.id) else "🔔 مفعّلة"))

@router.callback_query(F.data.in_(["rfb:yes", "rfb:no", "rfb:skip"]))
async def rfb_choice(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = get_user_lang(uid) or "ar"
    choice = cb.data.split(":")[1]
    if choice == "yes":
        rec = {"user_id": uid, "result": "solved", "reason": "", "time": utcnow_iso()}
        _save_feedback(rec); await _notify_admins_feedback(cb.bot, rec)
        await cb.message.edit_text(_tx(lang, "rfb.thx_yes", "سعدنا بحل مشكلتك ✅", "Glad it's solved ✅"));  return await cb.answer("✅")
    if choice == "skip":
        rec = {"user_id": uid, "result": "skipped", "reason": "", "time": utcnow_iso()}
        _save_feedback(rec); await _notify_admins_feedback(cb.bot, rec)
        await cb.message.edit_text(_tx(lang, "rfb.closed", "تم إغلاق البلاغ.", "Ticket closed."));  return await cb.answer("✅")
    await state.set_state(FeedbackState.waiting_reason)
    await cb.message.edit_text(_tx(lang, "rfb.ask_reason",
                                   "لم تُحل المشكلة؟ أخبرنا بالمشكلة بإيجاز:",
                                   "Not solved? Tell us briefly what went wrong:"))
    await cb.answer()

@router.message(FeedbackState.waiting_reason)
async def rfb_reason(m: Message, state: FSMContext):
    uid = m.from_user.id
    lang = get_user_lang(uid) or "ar"
    reason = (m.text or "").strip()[:500]
    await state.clear()
    rec = {"user_id": uid, "result": "not_solved", "reason": reason, "time": utcnow_iso()}
    _save_feedback(rec); await _notify_admins_feedback(m.bot, rec)
    await m.reply(_tx(lang, "rfb.thx_no", "شكرًا، تم تسجيل السبب وسنراجعه.", "Thanks, your reason was recorded and will be reviewed."))

# ===== كولباكات أدوات الأدمن: حظر/إلغاء/معلومات =====
@router.callback_query(F.data.startswith("rpadm:ban:"))
async def rpadm_ban(cb: CallbackQuery):
    if not (await _is_admin(cb.from_user.id)):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)

    _, _, uid_s, dur_s = cb.data.split(":")  # rpadm:ban:<uid>:<hours|perm>
    uid = int(uid_s)

    u_lang = get_user_lang(uid) or "ar"

    if dur_s == "perm":
        _bl_ban(uid, None)
        try:
            await cb.bot.send_message(uid, _tx(u_lang, "notify.banned_perm",
                                               "⛔ تم تقييد ميزة البلاغات لديك بشكل دائم. إن كان ذلك خطأً، تواصل مع الدعم.",
                                               "⛔ Reporting feature has been permanently restricted. If this is a mistake, contact support."))
        except Exception:
            pass
        txt = f"🚫 تم حظر {uid} دائمًا."
    else:
        hours = max(1, int(dur_s))
        _bl_ban(uid, hours)
        try:
            await cb.bot.send_message(
                uid,
                _tx(u_lang, "notify.banned_temp",
                    "⛔ تم تقييد ميزة البلاغات لديك لمدة {time}.",
                    "⛔ Reporting feature restricted for {time}.").format(
                    time=(f"{hours}h" if not u_lang.startswith("ar") else f"{hours} ساعة"))
            )
        except Exception:
            pass
        txt = f"🚫 تم حظر {uid} لمدة {hours} ساعة."

    await cb.answer(txt, show_alert=True)

@router.callback_query(F.data.startswith("rpadm:clearcd:"))
async def rpadm_clearcd(cb: CallbackQuery):
    if not (await _is_admin(cb.from_user.id)):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)

    uid = int(cb.data.split(":")[2])
    st = load_state()
    (st.setdefault("last", {})).pop(str(uid), None)
    save_state(st)

    u_lang = get_user_lang(uid) or "ar"
    try:
        await cb.bot.send_message(uid, _tx(u_lang, "notify.cooldown_cleared",
                                           "🧹 تم تصفير مدة التبريد لحسابك. يمكنك فتح بلاغ جديد الآن.",
                                           "🧹 Your cooldown has been cleared. You can open a new ticket now."))
    except Exception:
        pass

    a_lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(_tx(a_lang, "rpadm.cleared", "تم تصفير التبريد", "Cooldown cleared"), show_alert=True)

@router.callback_query(F.data.startswith("rpadm:unban:"))
async def rpadm_unban(cb: CallbackQuery):
    if not (await _is_admin(cb.from_user.id)):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l,"admins_only","هذه الأداة للأدمن فقط.","Admins only."), show_alert=True)

    uid = int(cb.data.split(":")[2])
    _bl_unban(uid)

    u_lang = get_user_lang(uid) or "ar"
    try:
        await cb.bot.send_message(uid, _tx(u_lang, "notify.unbanned",
                                           "✅ تم رفع التقييد عن ميزة البلاغات لديك. يمكنك استخدام /report الآن.",
                                           "✅ Reporting restriction lifted. You can use /report now."))
    except Exception:
        pass

    await cb.answer(f"✅ تم إلغاء الحظر عن {uid}.", show_alert=True)

@router.callback_query(F.data.startswith("rpadm:info:"))
async def rpadm_info(cb: CallbackQuery):
    if not (await _is_admin(cb.from_user.id)):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(_tx(l, "admins_only", "هذه الأداة للأدمن فقط.", "Admins only."), show_alert=True)
    uid = int(cb.data.split(":")[2])
    blocked, remain = _bl_is_blocked(uid)
    bl_line = f"{'Blocked' if blocked else 'Not blocked'}" + (f" — {remain}" if blocked and remain else "")
    logs = _load_json(LOG_FILE, [])
    last_log = next((it for it in reversed(logs) if int(it.get("user_id", 0)) == uid), None)
    last_line = "-" if not last_log else f"{last_log.get('date','-')} · {(last_log.get('text') or '(media)')[:120]}"
    th = get_thread(uid) or {}
    sess_line = f"open={bool(th.get('open'))}, admin_id={th.get('admin_id')}"
    txt = (f"👤 <b>User</b> <code>{uid}</code>\n"
           f"• Block: <b>{bl_line}</b>\n"
           f"• Session: {sess_line}\n"
           f"• Last report: {last_line}")
    try:
        await cb.message.answer(txt, disable_web_page_preview=True)
    except Exception:
        pass
    await cb.answer()

# ===== أوامر سلاش مختصرة للأدمن =====
async def _only_admin(m: Message) -> bool:
    return bool(m.from_user and (await _is_admin(m.from_user.id)))

@router.message(Command("rinfo"))
async def cmd_rinfo(m: Message):
    if not (await _only_admin(m)): return
    parts = (m.text or "").split()
    if len(parts) < 2: return await m.reply("Usage: /rinfo <uid>")
    uid = int(parts[1])
    blocked, remain = _bl_is_blocked(uid)
    bl_line = f"{'Blocked' if blocked else 'Not blocked'}" + (f" — {remain}" if blocked and remain else "")
    th = get_thread(uid) or {}
    sess_line = f"open={bool(th.get('open'))}, admin_id={th.get('admin_id')}"
    logs = _load_json(LOG_FILE, [])
    last = next((it for it in reversed(logs) if int(it.get('user_id',0))==uid), None)
    last_line = "-" if not last else f"{last.get('date','-')} · {(last.get('text') or '(media)')[:200]}"
    await m.reply(f"👤 <b>User</b> <code>{uid}</code>\n• Block: <b>{bl_line}</b>\n• Session: {sess_line}\n• Last: {last_line}")

@router.message(Command("rban"))
async def cmd_rban(m: Message):
    if not (await _only_admin(m)): return
    parts = (m.text or "").split()
    if len(parts) < 3: return await m.reply("Usage: /rban <uid> <hours|perm>")
    uid = int(parts[1]); dur = parts[2].lower()
    if dur == "perm":
        _bl_ban(uid, None);  return await m.reply(f"🚫 تم حظر {uid} دائمًا.")
    try:
        hours = max(1, int(dur))
    except Exception:
        return await m.reply("Bad value. Use number of hours or 'perm'.")
    _bl_ban(uid, hours); await m.reply(f"🚫 تم حظر {uid} لمدة {hours} ساعة.")

@router.message(Command("runban"))
async def cmd_runban(m: Message):
    if not (await _only_admin(m)): return
    parts = (m.text or "").split()
    if len(parts) < 2: return await m.reply("Usage: /runban <uid>")
    uid = int(parts[1]); _bl_unban(uid); await m.reply(f"✅ تم إلغاء الحظر عن {uid}.")
