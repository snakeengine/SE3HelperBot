# admin/report_inbox.py
from __future__ import annotations
import os, json, logging, time, datetime
from pathlib import Path
from datetime import datetime as dt, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from lang import t, get_user_lang

router = Router(name="report_inbox")

DATA_DIR       = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
THREADS_FILE   = DATA_DIR / "support_threads.json"    # موحّد مع report.py
BLOCKLIST_FILE = DATA_DIR / "report_blocklist.json"   # نفس بلوك ليست التقرير
SETTINGS_FILE  = DATA_DIR / "report_settings.json"    # لمعرفة cooldown_days
STATE_FILE     = DATA_DIR / "report_users.json"       # {"last": {uid: iso}}
LOG_FILE       = DATA_DIR / "reports_log.json"        # لاستخراج آخر بلاغ مختصر

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()] or [7360982123]

def is_admin(uid: int) -> bool: return uid in ADMIN_IDS
def L(uid: int) -> str: return get_user_lang(uid) or "ar"
def _now_iso(): return dt.now(tz=timezone.utc).replace(microsecond=0).isoformat()

# --------- I/O helpers ----------
def _load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logging.error(f"[rin] load {p} error: {e}")
    return json.loads(json.dumps(default))

def _save_json(p: Path, data):
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logging.error(f"[rin] save {p} error: {e}")

def _load() -> dict:
    d = _load_json(THREADS_FILE, {"threads": {}})
    d.setdefault("threads", {})
    return d

def _save(d: dict): _save_json(THREADS_FILE, d)

# public helper يُستدعى من report.py
def _touch_thread(user_id: int, user_name: str | None = None, last_text: str | None = None):
    d = _load()
    th = d["threads"].setdefault(str(user_id), {
        "user_id": user_id, "user_name": user_name or "", "status": "open",
        "last_text": "", "updated_at": _now_iso(),
    })
    if user_name: th["user_name"] = user_name
    if last_text: th["last_text"] = last_text
    th["updated_at"] = _now_iso(); _save(d)

# ===== Blocklist & cooldown helpers =====
def _bl_read() -> dict: return _load_json(BLOCKLIST_FILE, {})
def _bl_write(d: dict): _save_json(BLOCKLIST_FILE, d)
def _ban(uid: int, hours: int | None):
    bl = _bl_read()
    if hours is None: bl[str(uid)] = True
    else: bl[str(uid)] = {"until": time.time() + hours*3600}
    _bl_write(bl)
def _unban(uid: int):
    bl = _bl_read(); bl.pop(str(uid), None); _bl_write(bl)

def _settings() -> dict:
    d = _load_json(SETTINGS_FILE, {"enabled": True, "cooldown_days": 3, "banned": []})
    d.setdefault("cooldown_days", 3)
    return d

def _state_read() -> dict: return _load_json(STATE_FILE, {"last": {}})
def _state_write(d: dict): _save_json(STATE_FILE, d)
def _clear_cd(uid: int):
    st = _state_read(); st.setdefault("last", {}).pop(str(uid), None); _state_write(st)

def _human_left(seconds: int) -> str:
    seconds = max(0, int(seconds))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) if parts else f"{seconds}s"

def _human_hours_label(hours: int, lang: str) -> str:
    """تنسيق مدة على أساس ساعات لاستخدامها برسائل المستخدم."""
    try: hours = int(hours)
    except Exception: return "?"
    if hours < 24:
        return f"{hours}h" if not str(lang).startswith("ar") else f"{hours} ساعة"
    days = hours // 24
    if str(lang).startswith("ar"):
        return f"{days} يوم" if days == 1 else f"{days} أيام"
    return f"{days}d"

async def _safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

def _title(lang: str) -> str:
    return "📥 " + (t(lang, "rin.title") or "صندوق الوارد")

def _kb_list(lang: str) -> InlineKeyboardMarkup:
    d = _load()
    items = list(d["threads"].values())
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    kb = InlineKeyboardBuilder()
    if not items:
        kb.button(text=t(lang, "rin.empty") or "لا يوجد بلاغات", callback_data="rin:nop")
    else:
        for th in items[:25]:
            uid = th.get("user_id")
            name = th.get("user_name") or f"#{uid}"
            status = th.get("status", "open")
            mark = "🟢" if status == "open" else "⚪️"
            kb.button(text=f"{mark} {name}", callback_data=f"rin:chat:{uid}")
    kb.adjust(1)
    kb.button(text="🔄 " + (t(lang, "rin.refresh") or "تحديث"), callback_data="rin:open")
    kb.button(text="⬅️ " + (t(lang, "rin.back") or "رجوع"), callback_data="ah:menu")
    kb.adjust(1)
    return kb.as_markup()

def _chat_text(lang: str, th: dict) -> str:
    uid = th.get("user_id")
    name = th.get("user_name") or f"#{uid}"
    status = th.get("status", "open")
    st_txt = (t(lang, "rin.st_open") or "مفتوح") if status == "open" else (t(lang, "rin.st_closed") or "مغلق")
    last = th.get("last_text") or "-"
    upd = th.get("updated_at") or "-"
    return (
        f"👤 <b>{name}</b> (<code>{uid}</code>)\n"
        f"{t(lang, 'rin.status') or 'الحالة'}: <b>{st_txt}</b>\n"
        f"{t(lang, 'rin.last') or 'آخر رسالة'}: <i>{last}</i>\n"
        f"{t(lang, 'rin.updated') or 'آخر تحديث'}: <code>{upd}</code>"
    )

def _kb_chat(lang: str, th: dict) -> InlineKeyboardMarkup:
    uid = th.get("user_id")
    kb = InlineKeyboardBuilder()

    # ردّ / إغلاق / إعادة فتح
    kb.row(InlineKeyboardButton(text="💬 " + (t(lang, "rin.reply") or "ردّ"),
                                callback_data=f"rin:reply:{uid}"))
    if th.get("status", "open") == "open":
        kb.row(InlineKeyboardButton(text="🔒 " + (t(lang, "rin.close") or "إنهاء المحادثة"),
                                    callback_data=f"rin:close:{uid}"))
    else:
        kb.row(InlineKeyboardButton(text="♻️ " + (t(lang, "rin.reopen") or "إعادة فتح"),
                                    callback_data=f"rin:reopen:{uid}"))

    # أزرار الحظر النصّية الواضحة
    def ban_txt(h):
        if h < 24:
            return "🚫 " + (t(lang, "rpadm.ban_hour") or "حظر: {n} س").format(n=h)
        d = h // 24
        if str(lang).startswith("ar"):
            return f"🚫 حظر: {d} " + ("يوم" if d == 1 else "أيام")
        return "🚫 " + (t(lang, "rpadm.ban_days") or "Ban: {n} d").format(n=d)

    kb.row(
        InlineKeyboardButton(text=ban_txt(1),        callback_data=f"rin:ban:{uid}:1"),
        InlineKeyboardButton(text=ban_txt(24),       callback_data=f"rin:ban:{uid}:24"),
    )
    kb.row(
        InlineKeyboardButton(text=ban_txt(24*7),     callback_data=f"rin:ban:{uid}:{24*7}"),
        InlineKeyboardButton(text=ban_txt(24*30),    callback_data=f"rin:ban:{uid}:{24*30}"),
    )
    kb.row(
        InlineKeyboardButton(text="🚫 " + (t(lang, "rpadm.ban_perm") or "حظر دائم ∞"),
                             callback_data=f"rin:ban:{uid}:perm"),
        InlineKeyboardButton(text="✅ " + (t(lang, "rpadm.unban") or "رفع الحظر"),
                             callback_data=f"rin:unban:{uid}"),
    )

    # أدوات مساعدة (لاحظ توحيد الـ callbacks إلى rin: )
    kb.row(
        InlineKeyboardButton(text="ℹ️ " + (t(lang, "rpadm.btn_info") or "معلومات المستخدم"),
                             callback_data=f"rin:info:{uid}"),
        InlineKeyboardButton(text="🧹 " + (t(lang, "rpadm.btn_clear_cd") or "تصفير التبريد"),
                             callback_data=f"rin:clearcd:{uid}"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + (t(lang, "rin.back_list") or "عودة للقائمة"),
                                callback_data="rin:open"))

    return kb.as_markup()


class RinStates(StatesGroup):
    waiting_reply = State()

# ===== فتح قائمة الوارد =====
@router.callback_query(F.data == "rin:open")
async def rin_open(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    await _safe_edit(cb.message, _title(lang), _kb_list(lang)); await cb.answer()

# ===== فتح محادثة =====
@router.callback_query(F.data.startswith("rin:chat:"))
async def rin_chat(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    uid = int(cb.data.split(":")[-1])
    d = _load(); th = d["threads"].get(str(uid))
    if not th: return await cb.answer(t(lang, "rin.thread_missing") or "المحادثة غير موجودة", show_alert=True)
    await _safe_edit(cb.message, _chat_text(lang, th), _kb_chat(lang, th)); await cb.answer()

# ===== بدء الرد =====
@router.callback_query(F.data.startswith("rin:reply:"))
async def rin_reply_start(cb: CallbackQuery, state: FSMContext):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.")
    uid = int(cb.data.split(":")[-1])
    await state.update_data(reply_to=uid); await state.set_state(RinStates.waiting_reply)
    await cb.message.answer(t(lang, "rin.ask_reply") or "أرسل الرد الآن (نص/ميديا):"); await cb.answer()

@router.message(RinStates.waiting_reply)
async def rin_reply_send(m: Message, state: FSMContext):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.")
    st = await state.get_data(); uid = st.get("reply_to")
    if not uid: return await m.reply(t(lang, "rin.thread_missing") or "لا توجد محادثة محددة.")
    try:
        await m.copy_to(chat_id=uid)
        d = _load(); th = d["threads"].setdefault(str(uid), {"user_id": uid, "user_name": "", "status": "open"})
        content = (m.caption if (getattr(m, "caption", None)) else (m.text or "(media)"))
        th["last_text"] = content; th["updated_at"] = _now_iso(); _save(d)
        await m.reply(t(lang, "rin.sent_ok") or "تم الإرسال ✅")
    except Exception as e:
        logging.error(f"[rin] send to {uid} failed: {e}")
        await m.reply(t(lang, "rin.send_fail") or "فشل الإرسال")
    finally:
        await state.clear()

# ===== إغلاق / إعادة فتح =====
@router.callback_query(F.data.startswith("rin:close:"))
async def rin_close(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    uid = int(cb.data.split(":")[-1])
    d = _load(); th = d["threads"].get(str(uid))
    if not th: return await cb.answer(t(lang, "rin.thread_missing") or "المحادثة غير موجودة", show_alert=True)
    th["status"] = "closed"; th["updated_at"] = _now_iso(); _save(d)

    # إشعار المستخدم
    u_lang = get_user_lang(uid) or "ar"
    try:
        await cb.bot.send_message(uid, t(u_lang, "notify.chat_closed") or
                                  "🔒 تم إغلاق محادثة الدعم الحالية. يمكنك فتح بلاغ جديد عبر /report عند الحاجة.")
    except Exception:
        pass

    await _safe_edit(cb.message, _chat_text(lang, th), _kb_chat(lang, th)); await cb.answer("✅")

@router.callback_query(F.data.startswith("rin:reopen:"))
async def rin_reopen(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    uid = int(cb.data.split(":")[-1])
    d = _load(); th = d["threads"].get(str(uid))
    if not th: return await cb.answer(t(lang, "rin.thread_missing") or "المحادثة غير موجودة", show_alert=True)
    th["status"] = "open"; th["updated_at"] = _now_iso(); _save(d)

    u_lang = get_user_lang(uid) or "ar"
    try:
        await cb.bot.send_message(uid, t(u_lang, "notify.chat_reopened") or
                                  "♻️ تم إعادة فتح محادثة الدعم. تفضل بإرسال رسالتك.")
    except Exception:
        pass

    await _safe_edit(cb.message, _chat_text(lang, th), _kb_chat(lang, th)); await cb.answer("✅")

# ===== حظر/رفع حظر من داخل المحادثة =====
@router.callback_query(F.data.startswith("rin:ban:"))
async def rin_ban(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    _, _, uid_s, dur_s = cb.data.split(":")   # rin:ban:<uid>:<hours|perm>
    uid = int(uid_s)

    u_lang = get_user_lang(uid) or "ar"

    if dur_s == "perm":
        _ban(uid, None); msg_a = f"🚫 تم حظر {uid} دائمًا."
        msg_u = t(u_lang, "notify.banned_perm") or "⛔ تم تقييد ميزة البلاغات لديك بشكل دائم. إن كان ذلك خطأً، تواصل مع الدعم."
    else:
        hours = max(1, int(dur_s)); _ban(uid, hours)
        msg_a = f"🚫 تم حظر {uid} لمدة {hours} ساعة."
        msg_u = (t(u_lang, "notify.banned_temp") or "⛔ تم تقييد ميزة البلاغات لديك لمدة {time}.") \
                 .format(time=_human_hours_label(hours, u_lang))

    try: await cb.bot.send_message(uid, msg_u)
    except Exception: pass

    await cb.answer(msg_a, show_alert=True)

@router.callback_query(F.data.startswith("rin:unban:"))
async def rin_unban(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    uid = int(cb.data.split(":")[-1]); _unban(uid)
    u_lang = get_user_lang(uid) or "ar"
    try:
        await cb.bot.send_message(uid, t(u_lang, "notify.unbanned") or
                                  "✅ تم رفع التقييد عن ميزة البلاغات لديك. يمكنك استخدام /report الآن.")
    except Exception:
        pass
    await cb.answer(f"✅ تم إلغاء الحظر عن {uid}.", show_alert=True)

# ===== معلومات + مسح التبريد =====
@router.callback_query(F.data.startswith("rin:info:"))
async def rin_info(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    uid = int(cb.data.split(":")[-1])

    # Block status
    bl = _bl_read()
    brec = bl.get(str(uid))
    if brec is True:
        bl_line = "Blocked — ∞"
    elif isinstance(brec, dict) and "until" in brec:
        rem = int(float(brec["until"]) - time.time())
        bl_line = "Blocked — " + (_human_left(rem) if rem > 0 else "expired")
    else:
        bl_line = "Not blocked"

    # Cooldown remaining
    st = _state_read(); last_iso = (st.get("last") or {}).get(str(uid))
    cd_days = int(_settings().get("cooldown_days", 0) or 0)
    if last_iso and cd_days > 0:
        s = last_iso[:-1] if last_iso.endswith("Z") else last_iso
        try:
            last_dt = datetime.datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        except Exception:
            last_dt = None
        if last_dt:
            next_allowed = last_dt + datetime.timedelta(days=cd_days)
            now = dt.now(timezone.utc)
            cd_line = "0" if now >= next_allowed else _human_left(int((next_allowed - now).total_seconds()))
        else:
            cd_line = "-"
    else:
        cd_line = "-"

    # Session
    th = (_load().get("threads") or {}).get(str(uid)) or {}
    sess_line = f"open={bool(th.get('status','open')=='open')}, admin_id={th.get('admin_id')}"

    # Last report (from log)
    logs = _load_json(LOG_FILE, [])
    last = next((it for it in reversed(logs) if int(it.get("user_id", 0)) == uid), None)
    last_line = "-" if not last else f"{last.get('date','-')} · {(last.get('text') or '(media)')[:180]}"

    txt = (f"👤 <b>User</b> <code>{uid}</code>\n"
           f"• Block: <b>{bl_line}</b>\n"
           f"• Cooldown left: <code>{cd_line}</code>\n"
           f"• Session: {sess_line}\n"
           f"• Last report: {last_line}")
    await cb.message.answer(txt, parse_mode="HTML", disable_web_page_preview=True)
    await cb.answer()

@router.callback_query(F.data.startswith("rin:clearcd:"))
async def rin_clearcd(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "admins_only") or "هذه الأداة للأدمن فقط.", show_alert=True)
    uid = int(cb.data.split(":")[-1]); _clear_cd(uid)
    await cb.answer("🧽 تم مسح التبريد لهذا المستخدم.", show_alert=True)

@router.callback_query(F.data == "rin:nop")
async def rin_nop(cb: CallbackQuery):
    await cb.answer()
