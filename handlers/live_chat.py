# handlers/live_chat.py
from __future__ import annotations
import os, json, time, logging
from pathlib import Path
import inspect
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from lang import t, get_user_lang

router = Router(name="live_chat")
log = logging.getLogger(__name__)

# ================== إعدادات عامة ==================
ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID","")).split(",") if x.strip().isdigit()]
ADMIN_ONLINE_TTL = int(os.getenv("ADMIN_ONLINE_TTL", "600"))  # 10 دقائق

def _targets() -> list[int]:
    return [aid for aid in ADMIN_IDS]

# ملفات بيانات
DATA = Path("data")
SESSIONS_FILE = DATA/"live_sessions.json"       # { uid: {status,start_ts,last_ts,admin_id,queue,sid,tag?} }
RELAYS_FILE   = DATA/"live_relays.json"         # { "<admin_chat_id>:<message_id>": uid }
ADMIN_ACTIVE  = DATA/"live_admin_active.json"   # { admin_id: active_uid }
HISTORY_FILE  = DATA/"live_history.json"        # { sid: {...} }
RATINGS_FILE  = DATA/"live_ratings.json"        # { sid: {admin_rating?, user_rating?} }
BLOCKLIST_FILE= DATA/"live_blocklist.json"      # { uid: true | {until: ts} }
ADMIN_SEEN    = DATA/"admin_last_seen.json"     # { admin_id: {online: bool, ts: float} } أو float قديم
SESSION_TTL = 60*30  # 30 دقيقة
LIVE_CONFIG = DATA/"live_config.json"           # {"enabled": true}

# ================== أدوات ==================
def _now() -> float: return time.time()

def _load(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(p: Path, obj):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        log.warning("save %s failed: %s", p, e)

def _support_enabled() -> bool:
    cfg = _load(LIVE_CONFIG)
    return bool(cfg.get("enabled", True))

def _blocked(uid: int) -> bool:
    row = _load(BLOCKLIST_FILE).get(str(uid))
    if not row:
        return False
    if isinstance(row, dict):
        until = float(row.get("until", 0) or 0)
        if until and _now() > until:
            bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
            return False
        return True
    return bool(row)

def _L(uid: int) -> str:
    try:
        return (get_user_lang(uid) or "ar").lower()
    except Exception:
        return "ar"

def _tt(lang: str, key: str, ar: str, en: str) -> str:
    try:
        val = t(lang, key)
        if val and val != key:
            return val
    except Exception:
        pass
    return ar if (lang or "ar").startswith("ar") else en

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _get_session(uid: int) -> dict:
    return _load(SESSIONS_FILE).get(str(uid), {})

def _put_session(uid: int, data: dict):
    s = _load(SESSIONS_FILE); s[str(uid)] = data; _save(SESSIONS_FILE, s)

def _del_session(uid: int):
    s = _load(SESSIONS_FILE); s.pop(str(uid), None); _save(SESSIONS_FILE, s)

def _touch(uid: int):
    s = _get_session(uid)
    if s:
        s["last_ts"] = _now()
        _put_session(uid, s)

def _expired(sess: dict) -> bool:
    return (_now() - float(sess.get("last_ts", 0))) > SESSION_TTL

# active user per admin
def _set_admin_active(admin_id: int, uid: int):
    m = _load(ADMIN_ACTIVE); m[str(admin_id)] = int(uid); _save(ADMIN_ACTIVE, m)

def _get_admin_active(admin_id: int) -> int | None:
    m = _load(ADMIN_ACTIVE); v = m.get(str(admin_id))
    try:
        return int(v) if v else None
    except Exception:
        return None

# history / ratings
def _ensure_history(sid: str, uid: int, admin_id: int | None, start_ts: float):
    h = _load(HISTORY_FILE)
    if sid not in h:
        h[sid] = {"uid": uid, "admin_id": admin_id, "start_ts": start_ts}
        _save(HISTORY_FILE, h)

def _finish_history(sid: str, tag: str | None = None) -> dict:
    h = _load(HISTORY_FILE); rec = h.get(sid) or {}
    if rec:
        rec["end_ts"] = _now()
        rec["duration"] = max(0, int(rec["end_ts"] - float(rec.get("start_ts", _now()))))
        if tag: rec["tag"] = tag
        h[sid] = rec; _save(HISTORY_FILE, h)
    return rec

def _set_admin_rating(sid: str, stars: int):
    r = _load(RATINGS_FILE); row = r.get(sid) or {}
    row["admin_rating"] = int(stars); r[sid] = row; _save(RATINGS_FILE, r)

def _set_user_rating(sid: str, stars: int):
    r = _load(RATINGS_FILE); row = r.get(sid) or {}
    row["user_rating"] = int(stars); r[sid] = row; _save(RATINGS_FILE, r)

# ===== توفر الإدمن =====
def _touch_admin(admin_id: int):
    m = _load(ADMIN_SEEN)
    row = m.get(str(admin_id))
    if isinstance(row, dict):
        row["ts"] = _now()
    else:
        row = {"online": True, "ts": _now()}
    m[str(admin_id)] = row
    _save(ADMIN_SEEN, m)

def _set_admin_online(admin_id: int, online: bool):
    m = _load(ADMIN_SEEN)
    row = m.get(str(admin_id)) or {}
    row["online"] = bool(online)
    row["ts"] = _now()
    m[str(admin_id)] = row
    _save(ADMIN_SEEN, m)

def _any_admin_online() -> bool:
    m = _load(ADMIN_SEEN)
    now = _now()
    for v in m.values():
        if isinstance(v, dict):
            if v.get("online"):
                return True
        else:
            try:
                if (now - float(v)) <= ADMIN_ONLINE_TTL:
                    return True
            except Exception:
                pass
    return False

# ===== تنبيهات الإدمن =====
async def _notify_admins_t(bot, key: str, ar: str, en: str, build_kb=None, **fmt):
    for aid in _targets():
        try:
            alang = _L(aid)
            text = _tt(alang, key, ar, en).format(**fmt)
            kb = None
            if build_kb:
                res = build_kb(alang)
                if inspect.isawaitable(res):
                    res = await res
                kb = res
            await bot.send_message(aid, text, reply_markup=kb)
        except Exception as e:
            log.warning("[live] notify %s failed: %s", aid, e)

# ================== لوحات التحكم ==================
def _kb_user_wait(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=_tt(lang, "live.btn.cancel", "❌ إلغاء الدردشة", "❌ Cancel chat"),
            callback_data="live:cancel"
        )
    ]])

def _kb_user_end(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=_tt(lang, "live.btn.end", "❌ إنهاء الدردشة", "❌ End chat"),
            callback_data="live:end_self"
        )
    ]])

def _kb_admin_request(uid: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang, "live.admin.join", "✅ انضم للدردشة", "✅ Join chat"),
                             callback_data=f"live:accept:{uid}"),
        InlineKeyboardButton(text=_tt(lang, "live.admin.decline", "🚫 رفض", "🚫 Decline"),
                             callback_data=f"live:decline:{uid}")
    ]])

def _kb_admin_controls(uid: int, lang: str, sid: str) -> InlineKeyboardMarkup:
    stars = [InlineKeyboardButton(text=f"{i}⭐", callback_data=f"live:arate:{uid}:{sid}:{i}") for i in range(1, 6)]
    tags  = [
        InlineKeyboardButton(text=_tt(lang,"live.tag.solved","✅ محلولة","✅ Solved"),
                             callback_data=f"live:atag:{uid}:{sid}:solved"),
        InlineKeyboardButton(text=_tt(lang,"live.tag.follow","⏳ متابعة","⏳ Follow-up"),
                             callback_data=f"live:atag:{uid}:{sid}:follow"),
        InlineKeyboardButton(text=_tt(lang,"live.tag.bug","🐞 عيب","🐞 Bug"),
                             callback_data=f"live:atag:{uid}:{sid}:bug"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        stars,
        tags,
        [
            InlineKeyboardButton(text=_tt(lang,"live.btn.info","ℹ️ معلومات","ℹ️ Info"),
                                 callback_data=f"live:ainfo:{uid}:{sid}"),
            InlineKeyboardButton(text=_tt(lang,"live.btn.end.red","🔴 إنهاء الدردشة","🔴 End chat"),
                                 callback_data=f"live:end:{uid}:{sid}")
        ]
    ])

# ================== الحالة ==================
class LiveChat(StatesGroup):
    active = State()

# ================== تدفق الأحداث ==================
@router.callback_query(F.data == "bot:live")
async def cb_start_live(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    lang = _L(uid)

    if _blocked(uid):
        return await cb.answer(_tt(lang,"live.blocked","لا يمكنك بدء دردشة حالياً.","You can't start a chat now."), show_alert=True)

    # الدردشة مُفعّلة من لوحة الإدمن؟
    if not _support_enabled():
        await cb.message.edit_text(_tt(lang, "live.unavailable",
                                       "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                                       "❕ Live chat is currently unavailable. Please try later."))
        return await cb.answer()

    # هل يوجد إدمن متاح؟
    if not _any_admin_online():
        await cb.message.edit_text(_tt(lang, "live.unavailable",
                                       "❕ الدردشة الحيّة غير متاحة الآن. حاول لاحقًا.",
                                       "❕ Live chat is currently unavailable. Please try later."))
        return await cb.answer()

    # ✅ مهم: أنشئ جلسة انتظار وسجّلها ثم أبلغ الإدمنين
    sid  = f"{uid}:{int(_now())}"
    sess = {"status":"waiting","start_ts":_now(),"last_ts":_now(),"queue":[],"admin_id":None,"sid":sid}
    _put_session(uid, sess)
    _ensure_history(sid, uid, None, sess["start_ts"])

    await state.set_state(LiveChat.active)
    await cb.message.edit_text(
        _tt(lang, "live.opened", "💬 تم فتح طلب دردشة.\nالرجاء الانتظار حتى ينضم الدعم…",
                         "💬 Chat request opened.\nPlease wait for support to join…"),
        reply_markup=_kb_user_wait(lang)
    )
    await cb.answer()

    # إشعار الإدمنين مع كيبورد محلي لكل إدمن
    def _mk(alang: str):
        return _kb_admin_request(uid, alang)

    await _notify_admins_t(
        cb.bot,
        "live.admin.notify.request",
        "🆕 طلب دردشة حيّة\n• المستخدم: {name} @{username}\n• المعرّف: {uid}",
        "🆕 Live chat request\n• User: {name} @{username}\n• ID: {uid}",
        build_kb=_mk, name=cb.from_user.full_name, username=cb.from_user.username or "-", uid=uid
    )

@router.callback_query(F.data == "live:cancel")
async def cb_user_cancel(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id; lang = _L(uid)
    if _get_session(uid):
        _del_session(uid)
    await state.clear()
    await cb.message.edit_text(_tt(lang,"live.canceled","تم إلغاء طلب الدردشة.","Chat request canceled."))
    await _notify_admins_t(cb.bot,
        "live.admin.notify.user_canceled",
        "⚪️ ألغى المستخدم طلب الدردشة (UID:{uid})",
        "⚪️ Live chat canceled by user (UID:{uid})",
        uid=uid
    )
    await cb.answer()

@router.callback_query(F.data.startswith("live:accept:"))
async def cb_admin_accept(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid  = int(cb.data.split(":")[-1])
    user_lang = _L(uid)
    sess = _get_session(uid)
    if not sess or _expired(sess):
        _del_session(uid)
        return await cb.answer(_tt(user_lang,"live.expired","انتهت/غير موجودة.","Expired/Not found"), show_alert=True)

    sess["status"] = "active"; sess["admin_id"] = cb.from_user.id
    _put_session(uid, sess)
    _set_admin_active(cb.from_user.id, uid)
    _ensure_history(sess["sid"], uid, cb.from_user.id, sess["start_ts"])
    _touch_admin(cb.from_user.id)

    try:
        await cb.bot.send_message(uid, _tt(user_lang,"live.joined.user","✅ انضم الدعم إلى الدردشة. تفضل بالتحدث الآن.",
                                                         "✅ Support joined the chat. You can talk now."),
                                  reply_markup=_kb_user_end(user_lang))
    except Exception:
        pass

    # سلّم الرسائل المعلقة إلى الإدمنين
    relays = _load(RELAYS_FILE); delivered = False
    for mid in (sess.get("queue") or []):
        for tgt in _targets():
            try:
                cp = await cb.bot.copy_message(chat_id=tgt, from_chat_id=uid, message_id=mid)
                relays[f"{tgt}:{cp.message_id}"] = uid
                delivered = True
            except Exception as e:
                log.warning("deliver backlog to %s failed: %s", tgt, e)
    if delivered: _save(RELAYS_FILE, relays)

    # رسالة لوحة الإدارة بلغة الإدمن
    admin_lang = _L(cb.from_user.id)
    try:
        await cb.message.edit_text(
            _tt(admin_lang, "live.admin.joined.banner",
                "🟢 انضممت للدردشة مع المستخدم {uid}.",
                "🟢 Joined chat with user {uid}.").format(uid=uid),
            reply_markup=_kb_admin_controls(uid, admin_lang, sess["sid"])
        )
    except Exception:
        pass

    await _notify_admins_t(cb.bot,
        "live.admin.notify.joined",
        "🟢 انضم الإدمن {admin_id} للدردشة\nSID={sid}\nUID={uid}",
        "🟢 Admin {admin_id} joined chat\nSID={sid}\nUID={uid}",
        admin_id=cb.from_user.id, sid=sess["sid"], uid=uid
    )
    await cb.answer("Joined")

@router.callback_query(F.data.startswith("live:decline:"))
async def cb_admin_decline(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    uid  = int(cb.data.split(":")[-1]); lang = _L(uid)
    _touch_admin(cb.from_user.id)
    if _get_session(uid): _del_session(uid)
    try:
        await cb.bot.send_message(uid, _tt(lang,"live.declined","عذرًا، لا يتوفر دعم الآن. حاول لاحقًا.","Sorry, support is unavailable now. Please try later."))
    except Exception:
        pass
    await _notify_admins_t(cb.bot,
        "live.admin.notify.declined",
        "🚫 تم رفض الدردشة للمستخدم {uid} من الإدمن {admin_id}",
        "🚫 Chat declined for user {uid} by admin {admin_id}",
        uid=uid, admin_id=cb.from_user.id
    )
    await cb.answer("Declined")

@router.callback_query(F.data == "live:end_self")
async def cb_end_self(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id; lang = _L(uid)
    sess = _get_session(uid); sid = sess.get("sid") if sess else None
    if sess: _del_session(uid)
    await state.clear()
    try:
        await cb.message.edit_text(_tt(lang,"live.ended.user","تم إنهاء الدردشة. شكرًا لك.","Chat ended. Thank you."))
    except Exception:
        pass
    if sid:
        _finish_history(sid)
        await _notify_admins_t(cb.bot,
            "live.admin.notify.ended_by_user",
            "🔴 أنهى المستخدم الدردشة | SID={sid} | UID={uid}",
            "🔴 Chat ended by user | SID={sid} | UID={uid}",
            sid=sid, uid=uid
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"live:urate:{sid}:{i}") for i in range(1,6)]])
        try:
            await cb.bot.send_message(uid, _tt(lang,"live.rate.ask","قيّم تجربتك مع الدعم:","Rate your support experience:"), reply_markup=kb)
        except Exception:
            pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:end:"))
async def cb_admin_end(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    parts = cb.data.split(":")  # live:end:<uid>[:sid]
    uid   = int(parts[2]); user_lang = _L(uid)
    sess  = _get_session(uid)
    sid   = parts[3] if len(parts) > 3 else (sess.get("sid") if sess else None)
    if sess: _del_session(uid)
    try:
        await cb.bot.send_message(uid, _tt(user_lang,"live.ended.support","تم إنهاء الدردشة من جهة الدعم.","Chat has been ended by support."))
    except Exception:
        pass

    summary = {}
    if sid:
        summary = _finish_history(sid) or {}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"live:urate:{sid}:{i}") for i in range(1,6)]])
        try:
            await cb.bot.send_message(uid, _tt(user_lang,"live.rate.ask","قيّم تجربتك مع الدعم:","Rate your support experience:"), reply_markup=kb)
        except Exception:
            pass

    dur = int(summary.get("duration", 0)); tag = summary.get("tag", "-")
    await _notify_admins_t(cb.bot,
        "live.admin.notify.ended_by_admin",
        "🔴 أنهى الإدمن {admin_id} الدردشة\n• SID: {sid}\n• UID: {uid}\n• المدة: {dur}s\n• الوسم: {tag}",
        "🔴 Chat ended by admin {admin_id}\n• SID: {sid}\n• UID: {uid}\n• Duration: {dur}s\n• Tag: {tag}",
        admin_id=cb.from_user.id, sid=(sid or "-"), uid=uid, dur=dur, tag=tag
    )
    await cb.answer("Ended")

@router.callback_query(F.data.startswith("live:arate:"))
async def cb_admin_rate(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    _,_, uid, sid, stars = cb.data.split(":")
    _set_admin_rating(sid, int(stars))
    await cb.answer(f"Rated {stars}⭐")
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_admin_controls(int(uid), _L(cb.from_user.id), sid))
    except Exception:
        pass
    await _notify_admins_t(cb.bot,
        "live.admin.notify.admin_rating",
        "🛠️ قيّم الإدمن {admin_id} جلسة {sid}: {stars}⭐ (UID {uid})",
        "🛠️ Admin {admin_id} rated chat {sid}: {stars}⭐ (UID {uid})",
        admin_id=cb.from_user.id, sid=sid, stars=stars, uid=uid
    )

@router.callback_query(F.data.startswith("live:atag:"))
async def cb_admin_tag(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    _,_, uid, sid, tag = cb.data.split(":")
    uid = int(uid)
    h = _load(HISTORY_FILE); rec = h.get(sid) or {"uid": uid}
    rec["tag"] = tag; h[sid] = rec; _save(HISTORY_FILE, h)
    await cb.answer("Tagged")
    await _notify_admins_t(cb.bot,
        "live.admin.notify.tag",
        "🏷️ تم تعيين وسم: {tag} | SID={sid} | UID={uid}",
        "🏷️ Tag set: {tag} | SID={sid} | UID={uid}",
        tag=tag, sid=sid, uid=uid
    )

@router.callback_query(F.data.startswith("live:ainfo:"))
async def cb_admin_info(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _touch_admin(cb.from_user.id)
    _,_, uid, sid = cb.data.split(":")
    uid = int(uid)
    h  = _load(HISTORY_FILE).get(sid) or {}
    dur = int(max(0, (_now()-float(h.get("start_ts",_now()))) if not h.get("end_ts") else h.get("duration",0)))
    rr  = _load(RATINGS_FILE).get(sid) or {}
    tag = h.get("tag","-")
    alang = _L(cb.from_user.id)
    text = _tt(alang, "live.admin.info.text",
        "ℹ️ <b>معلومات</b>\n• UID: <code>{uid}</code>\n• SID: <code>{sid}</code>\n• المدة: <code>{dur}s</code>\n• الوسم: <code>{tag}</code>\n• التقييمات → إدمن: <code>{ar}</code> | مستخدم: <code>{ur}</code>",
        "ℹ️ <b>Info</b>\n• UID: <code>{uid}</code>\n• SID: <code>{sid}</code>\n• Duration: <code>{dur}s</code>\n• Tag: <code>{tag}</code>\n• Ratings → admin: <code>{ar}</code> | user: <code>{ur}</code>"
    ).format(uid=uid, sid=sid, dur=dur, tag=tag, ar=rr.get('admin_rating','-'), ur=rr.get('user_rating','-'))
    try: await cb.message.answer(text)
    except Exception: pass
    await cb.answer()

@router.callback_query(F.data.startswith("live:urate:"))
async def cb_user_rate(cb: CallbackQuery):
    sid, stars = cb.data.split(":")[2], int(cb.data.split(":")[3])
    _set_user_rating(sid, stars)
    await cb.answer("Thanks!")
    try:
        await cb.message.edit_text(_tt("ar","live.rate.done","⭐ تم.","⭐ Done."))
    except Exception:
        pass
    await _notify_admins_t(cb.bot,
        "live.admin.notify.user_rating",
        "⭐ تقييم المستخدم للجلسة {sid}: {stars}⭐",
        "⭐ User rating for chat {sid}: {stars}⭐",
        sid=sid, stars=stars
    )

# رسائل المستخدم أثناء الجلسة
@router.message(StateFilter(LiveChat.active))
async def user_live_message(m: Message, state: FSMContext):
    uid = m.from_user.id; lang = _L(uid)
    if _blocked(uid): return
    sess = _get_session(uid)
    if not sess: return
    if _expired(sess):
        _del_session(uid); await state.clear()
        return await m.answer(_tt(lang,"live.expired.msg","⏳ انتهت الجلسة. ابدأ واحدة جديدة من (الدعم).","⏳ Session expired. Start a new one from Support."))
    _touch(uid)

    if sess.get("status") == "waiting":
        q = list(sess.get("queue") or []); q.append(m.message_id); sess["queue"] = q; _put_session(uid, sess)
        return await m.answer(
            _tt(lang,"live.queue.received","✅ تم استلام رسالتك. سنرد بعد انضمام الدعم.\n(لا زلت في قائمة الانتظار)",
                             "✅ We got your message. We'll reply once support joins.\n(You are still in the queue)"),
            reply_markup=_kb_user_wait(lang)
        )

    # active → انسخ لخاص الإدمنين واحفظ مفتاح الربط <chat_id>:<message_id>
    relays = _load(RELAYS_FILE); delivered = False
    for tgt in _targets():
        try:
            cp = await m.bot.copy_message(chat_id=tgt, from_chat_id=m.chat.id, message_id=m.message_id)
            relays[f"{tgt}:{cp.message_id}"] = uid
            delivered = True
        except Exception as e:
            log.warning("copy user->%s failed: %s", tgt, e)
    if delivered:
        _save(RELAYS_FILE, relays)
        await m.answer(_tt(lang,"live.tip.end","للإنهاء اضغط الزر أدناه.","Tap below to end chat."), reply_markup=_kb_user_end(lang))

# ===== ردود ورسائل الإدمن =====
async def _relay_admin_reply(m: Message):
    _touch_admin(m.from_user.id)
    rel = _load(RELAYS_FILE)
    ref = m.reply_to_message.message_id if m.reply_to_message else None
    key = f"{m.chat.id}:{ref}" if ref is not None else None
    uid = rel.get(key) if key else None
    if not uid: return
    s = _get_session(int(uid))
    if not s or s.get("status") != "active":
        try: await m.reply("⚠️ Session not active.")
        except Exception: pass
        return
    try:
        await m.bot.copy_message(chat_id=int(uid), from_chat_id=m.chat.id, message_id=m.message_id)
        await m.bot.send_message(int(uid), _tt(_L(int(uid)),"live.tip.end","للإنهاء اضغط الزر أدناه.","Tap below to end chat."),
                                 reply_markup=_kb_user_end(_L(int(uid))))
    except Exception as e:
        log.warning("copy admin->user failed: %s", e)

# الإدمن يرد في الخاص بـ Reply
@router.message(F.reply_to_message, F.from_user.id.in_(ADMIN_IDS), F.chat.type == "private")
async def admin_reply_in_private(m: Message):
    await _relay_admin_reply(m)

# الإدمن يكتب رسالة عادية (بدون Reply) → ترسل للمستخدم النشط الذي انضم له
async def _send_to_active(m: Message):
    _touch_admin(m.from_user.id)
    aid = m.from_user.id
    uid = _get_admin_active(aid)
    if not uid: return
    s = _get_session(int(uid))
    if not s or s.get("status") != "active": return
    try:
        await m.bot.copy_message(chat_id=int(uid), from_chat_id=m.chat.id, message_id=m.message_id)
        await m.bot.send_message(int(uid), _tt(_L(int(uid)),"live.tip.end","للإنهاء اضغط الزر أدناه.","Tap below to end chat."),
                                 reply_markup=_kb_user_end(_L(int(uid))))
    except Exception as e:
        log.warning("copy admin(no-reply)->user failed: %s", e)

@router.message(F.chat.type == "private", F.from_user.id.in_(ADMIN_IDS))
async def admin_message_in_private(m: Message):
    if m.reply_to_message: return
    await _send_to_active(m)
