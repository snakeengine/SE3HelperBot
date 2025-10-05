# admin/live_support_admin.py
from __future__ import annotations
import os, json, time, logging
from pathlib import Path
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode

from lang import t, get_user_lang

# ✅ استخدم نظام الأدوار الجديد
try:
    from services import admin_roles
except Exception:  # Fallback بسيط
    admin_roles = None

router = Router(name="live_support_admin")
log = logging.getLogger(__name__)

DATA = Path("data")
SESSIONS_FILE = DATA/"live_sessions.json"
BLOCKLIST_FILE= DATA/"live_blocklist.json"
HISTORY_FILE  = DATA/"live_history.json"
CONFIG_FILE   = DATA/"live_config.json"       # {"enabled": true}
ADMIN_SEEN    = DATA/"admin_last_seen.json"   # { admin_id: {"online": bool, "ts": float} }

ADMIN_ONLINE_TTL = int(os.getenv("ADMIN_ONLINE_TTL", "600"))  # 10 دقائق

# ----------------- Helpers -----------------
def _now() -> float: return time.time()

def _load(p: Path):
    try:
        if p.exists(): return json.loads(p.read_text(encoding="utf-8"))
    except Exception: pass
    return {}

def _save(p: Path, obj):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        log.warning("save %s failed: %s", p, e)

def _L(uid: int) -> str:
    try: return (get_user_lang(uid) or "ar").lower()
    except Exception: return "ar"

def _tt(lang: str, key: str, ar: str, en: str) -> str:
    try:
        v = t(lang, key)
        if v and v != key: return v
    except Exception: pass
    return ar if (lang or "ar").startswith("ar") else en

async def _is_live_admin(uid: int) -> bool:
    """عضو في livechat أو default"""
    if admin_roles is None:
        return False
    ids = set(await admin_roles.get_admins("livechat")) | set(await admin_roles.get_admins("default"))
    return int(uid) in ids

def _support_enabled() -> bool:
    cfg = _load(CONFIG_FILE)
    return bool(cfg.get("enabled", True))

def _set_support_enabled(flag: bool):
    cfg = _load(CONFIG_FILE); cfg["enabled"] = bool(flag); _save(CONFIG_FILE, cfg)

def _format_ts(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return "-"

def _touch_admin(admin_id: int):
    m = _load(ADMIN_SEEN)
    row = m.get(str(admin_id))
    if isinstance(row, dict):
        row.setdefault("online", True)
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

def _admin_online_count(ttl: int = ADMIN_ONLINE_TTL) -> int:
    m = _load(ADMIN_SEEN); now = _now()
    n = 0
    for k, v in m.items():
        if isinstance(v, dict):
            if v.get("online") or (now - float(v.get("ts", 0))) <= ttl:
                n += 1
        else:
            try:
                if (now - float(v)) <= ttl:
                    n += 1
            except Exception:
                continue
    return n

# ====== الكيبورد ======
def _kb_main(lang: str) -> InlineKeyboardMarkup:
    toggle = _tt(lang, "liveadm.btn.disable", "🔕 إيقاف الدردشة", "🔕 Disable") if _support_enabled() \
             else _tt(lang, "liveadm.btn.enable", "🔔 تفعيل الدردشة", "🔔 Enable")
    online_btn = InlineKeyboardButton(
        text=_tt(lang, "liveadm.btn.i_am_online", "أنا متاح الآن ✅", "I'm online ✅"),
        callback_data="liveadm:online:on"
    )
    offline_btn = InlineKeyboardButton(
        text=_tt(lang, "liveadm.btn.i_am_offline", "غير متاح ⛔", "I'm offline ⛔"),
        callback_data="liveadm:online:off"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle, callback_data="liveadm:toggle"),
         InlineKeyboardButton(text=_tt(lang,"liveadm.btn.refresh","تحديث ♻️","Refresh ♻️"), callback_data="liveadm:refresh")],
        [online_btn, offline_btn],
        [InlineKeyboardButton(text=_tt(lang,"liveadm.btn.sessions","الجلسات النشطة","Active sessions"), callback_data="liveadm:sessions"),
         InlineKeyboardButton(text=_tt(lang,"liveadm.btn.blocklist","قائمة الحظر","Blocklist"), callback_data="liveadm:blocklist")],
        [InlineKeyboardButton(text=_tt(lang,"liveadm.btn.help","تعليمات","Help"), callback_data="liveadm:help")]
    ])

def _kb_session_item(uid: int, sid: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_tt(lang,"liveadm.btn.view","فتح","Open"), callback_data=f"liveadm:view:{uid}"),
        InlineKeyboardButton(text=_tt(lang,"liveadm.btn.end","إنهاء","End"), callback_data=f"live:end:{uid}:{sid}")
    ]])

def _kb_user_actions(uid: int, sid: Optional[str], lang: str) -> InlineKeyboardMarkup:
    rid = sid or "-"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_tt(lang,"liveadm.btn.forcejoin","الانضمام الآن","Join now"), callback_data=f"live:accept:{uid}")],
        [InlineKeyboardButton(text=_tt(lang,"liveadm.btn.end.red","🔴 إنهاء الدردشة","🔴 End chat"), callback_data=f"live:end:{uid}:{rid}")],
        [
            InlineKeyboardButton(text=_tt(lang,"liveadm.btn.block1h","حظر 1س","Block 1h"), callback_data=f"liveadm:block:{uid}:1h"),
            InlineKeyboardButton(text=_tt(lang,"liveadm.btn.block1d","حظر 1ي","Block 1d"), callback_data=f"liveadm:block:{uid}:1d"),
            InlineKeyboardButton(text=_tt(lang,"liveadm.btn.block7d","حظر 7ي","Block 7d"), callback_data=f"liveadm:block:{uid}:7d"),
            InlineKeyboardButton(text=_tt(lang,"liveadm.btn.blockperm","حظر دائم","Block perm"), callback_data=f"liveadm:block:{uid}:perm")
        ],
        [InlineKeyboardButton(text=_tt(lang,"liveadm.btn.unblock","رفع الحظر","Unblock"), callback_data=f"liveadm:unblock:{uid}")]
    ])

# ====== لوحة / أوامر ======
def _dashboard_stats(lang: str) -> str:
    s = _load(SESSIONS_FILE)
    active = sum(1 for v in s.values() if v.get("status") == "active")
    waiting= sum(1 for v in s.values() if v.get("status") == "waiting")
    online = _admin_online_count()
    en = _support_enabled()
    return _tt(lang, "liveadm.stats",
        "• الحالة: <b>{onoff}</b>\n• إدمن متصل (آخر 10د): <b>{online}</b>\n• نشطة: <b>{active}</b> | انتظار: <b>{waiting}</b>",
        "• Status: <b>{onoff}</b>\n• Admins online (10m): <b>{online}</b>\n• Active: <b>{active}</b> | Waiting: <b>{waiting}</b>"
    ).format(onoff=("مفعلة ✅" if en else "متوقفة ⛔"), online=online, active=active, waiting=waiting)

@router.message(Command("liveadmin"))
async def cmd_liveadmin(m: Message):
    if not await _is_live_admin(m.from_user.id):
        return
    lang = _L(m.from_user.id)
    txt = _tt(lang, "liveadm.title", "🛠️ لوحة تحكم الدردشة الحية", "🛠️ Live Chat Admin Panel")
    await m.answer(f"{txt}\n\n{_dashboard_stats(lang)}", reply_markup=_kb_main(lang), parse_mode=ParseMode.HTML)

# أوامر سريعة لتبديل الحالة
@router.message(Command("online"))
async def cmd_online(m: Message):
    if not await _is_live_admin(m.from_user.id):
        return
    _set_admin_online(m.from_user.id, True)
    lang = _L(m.from_user.id)
    await m.reply(_tt(lang, "liveadm.online.ok", "✔️ تم تعيين حالتك: متاح للدردشة.", "✔️ You are now online for live chat."))

@router.message(Command("offline"))
async def cmd_offline(m: Message):
    if not await _is_live_admin(m.from_user.id):
        return
    _set_admin_online(m.from_user.id, False)
    lang = _L(m.from_user.id)
    await m.reply(_tt(lang, "liveadm.offline.ok", "⛔ تم تعيين حالتك: غير متاح.", "⛔ You are now offline."))

@router.callback_query(F.data.in_({"liveadm:refresh", "liveadm:toggle", "liveadm:sessions", "liveadm:blocklist", "liveadm:help", "liveadm:online:on", "liveadm:online:off"}))
async def cb_panel_actions(cb: CallbackQuery):
    if not await _is_live_admin(cb.from_user.id):
        return
    lang = _L(cb.from_user.id)

    # تبديل الحالة (أنا متاح/غير متاح)
    if cb.data == "liveadm:online:on":
        _set_admin_online(cb.from_user.id, True)
    elif cb.data == "liveadm:online:off":
        _set_admin_online(cb.from_user.id, False)

    if cb.data == "liveadm:toggle":
        _set_support_enabled(not _support_enabled())
    if cb.data in ("liveadm:refresh","liveadm:toggle","liveadm:online:on","liveadm:online:off"):
        await cb.message.edit_text(_dashboard_stats(lang), reply_markup=_kb_main(lang), parse_mode=ParseMode.HTML)
        return await cb.answer("OK")

    if cb.data == "liveadm:help":
        txt = _tt(lang, "liveadm.help",
            "• هذه لوحة للتحكم بالدردشة الحية.\n• استعمل الأزرار أو الأوامر: /online و /offline.\n• أوامر الحظر: /block UID مدة — /unblock UID",
            "• Manage live chat here.\n• Use /online and /offline to toggle presence.\n• Block cmds: /block UID duration — /unblock UID"
        )
        return await cb.message.edit_text(txt, reply_markup=_kb_main(lang))

    if cb.data == "liveadm:sessions":
        s = _load(SESSIONS_FILE)
        if not s:
            await cb.message.edit_text(_tt(lang,"liveadm.nosessions","لا توجد جلسات.","No sessions."), reply_markup=_kb_main(lang))
            return await cb.answer()
        lines = [_tt(lang,"liveadm.sessions.title","📋 الجلسات:","📋 Sessions:")]
        for i, (uid, v) in enumerate(list(s.items())[:10], start=1):
            lines.append(f"{i}) UID <code>{uid}</code> | {v.get('status','-')} | SID <code>{v.get('sid','-')}</code> | start <code>{_format_ts(v.get('start_ts',0))}</code>")
        await cb.message.edit_text("\n".join(lines), reply_markup=_kb_main(lang), parse_mode=ParseMode.HTML)
        for uid, v in list(s.items())[:10]:
            try:
                await cb.message.answer(f"UID <code>{uid}</code>", reply_markup=_kb_session_item(int(uid), v.get("sid","-"), lang), parse_mode=ParseMode.HTML)
            except Exception: pass
        return await cb.answer()

    if cb.data == "liveadm:blocklist":
        bl = _load(BLOCKLIST_FILE)
        if not bl:
            await cb.message.edit_text(_tt(lang,"liveadm.nobl","قائمة الحظر فارغة.","Blocklist is empty."), reply_markup=_kb_main(lang))
            return await cb.answer()
        lines = [_tt(lang,"liveadm.bl.title","🚫 قائمة الحظر:","🚫 Blocklist:")]
        for uid, row in bl.items():
            until = "-"
            reason = "-"
            if isinstance(row, dict):
                u = row.get("until", 0); until = _format_ts(u) if u else "دائم/Perm"
                reason = row.get("reason","-")
            lines.append(f"• UID <code>{uid}</code> | {until} | {reason}")
        await cb.message.edit_text("\n".join(lines), reply_markup=_kb_main(lang), parse_mode=ParseMode.HTML)
        return await cb.answer()

# عناصر الحظر ورفع الحظر
def _parse_dur(s: str) -> int:
    if s == "perm": return 0
    if s.endswith("h"): return int(s[:-1]) * 3600
    if s.endswith("d"): return int(s[:-1]) * 86400
    return int(s)  # ثوانٍ

@router.callback_query(F.data.startswith("liveadm:block:"))
async def cb_block(cb: CallbackQuery):
    if not await _is_live_admin(cb.from_user.id): return
    _,_, uid, dur = cb.data.split(":")
    uid = int(uid)
    seconds = _parse_dur(dur)
    now = _now()
    bl = _load(BLOCKLIST_FILE)
    bl[str(uid)] = {"until": (0 if seconds == 0 else now + seconds), "reason":"by_admin", "by": cb.from_user.id}
    _save(BLOCKLIST_FILE, bl)
    await cb.answer("Blocked")
    lang = _L(cb.from_user.id)
    await cb.message.answer(_tt(lang,"liveadm.blocked.ok","تم حظر المستخدم {uid}.","User {uid} blocked.").format(uid=uid))

@router.callback_query(F.data.startswith("liveadm:unblock:"))
async def cb_unblock(cb: CallbackQuery):
    if not await _is_live_admin(cb.from_user.id): return
    uid = int(cb.data.split(":")[-1])
    bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
    await cb.answer("Unblocked")
    lang = _L(cb.from_user.id)
    await cb.message.answer(_tt(lang,"liveadm.unblocked.ok","تم رفع الحظر عن {uid}.","User {uid} unblocked.").format(uid=uid))

# أوامر نصية /block /unblock (اختيارية)
@router.message(Command("block"))
async def cmd_block(m: Message):
    if not await _is_live_admin(m.from_user.id): return
    parts = (m.text or "").split()
    lang = _L(m.from_user.id)
    if len(parts) < 2:
        return await m.reply(_tt(lang,"liveadm.usage.block","الاستخدام: /block UID [مدة مثل 1d أو perm]","Usage: /block UID [duration like 1d or perm]"))
    try:
        uid = int(parts[1])
    except Exception:
        return await m.reply("UID?")
    dur = parts[2] if len(parts) >= 3 else "perm"
    seconds = _parse_dur(dur)
    bl = _load(BLOCKLIST_FILE)
    bl[str(uid)] = {"until": (0 if seconds==0 else _now()+seconds), "reason":"by_admin", "by": m.from_user.id}
    _save(BLOCKLIST_FILE, bl)
    await m.reply(_tt(lang,"liveadm.blocked.ok","تم حظر المستخدم {uid}.","User {uid} blocked.").format(uid=uid))

@router.message(Command("unblock"))
async def cmd_unblock(m: Message):
    if not await _is_live_admin(m.from_user.id): return
    parts = (m.text or "").split()
    lang = _L(m.from_user.id)
    if len(parts) < 2:
        return await m.reply(_tt(lang,"liveadm.usage.unblock","الاستخدام: /unblock UID","Usage: /unblock UID"))
    try:
        uid = int(parts[1])
    except Exception:
        return await m.reply("UID?")
    bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
    await m.reply(_tt(lang,"liveadm.unblocked.ok","تم رفع الحظر عن {uid}.","User {uid} unblocked.").format(uid=uid))
