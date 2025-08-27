# admin/live_support_admin.py
from __future__ import annotations
import os, json, time, logging
from pathlib import Path
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from lang import t, get_user_lang

router = Router(name="live_support_admin")
log = logging.getLogger(__name__)

ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID","")).split(",") if x.strip().isdigit()]

DATA = Path("data")
SESSIONS_FILE = DATA/"live_sessions.json"
BLOCKLIST_FILE= DATA/"live_blocklist.json"
HISTORY_FILE  = DATA/"live_history.json"
CONFIG_FILE   = DATA/"live_config.json"       # {"enabled": true}
ADMIN_SEEN    = DATA/"admin_last_seen.json"   # { admin_id: ts }

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

def _admin_online_count(ttl: int = 600) -> int:
    m = _load(ADMIN_SEEN); now = _now()
    n = 0
    for k, ts in m.items():
        try:
            if (now - float(ts)) <= ttl:
                n += 1
        except Exception:
            continue
    return n

# ====== الكيبورد ======
def _kb_main(lang: str) -> InlineKeyboardMarkup:
    toggle = _tt(lang, "liveadm.btn.disable", "🔕 إيقاف الدردشة", "🔕 Disable") if _support_enabled() \
             else _tt(lang, "liveadm.btn.enable", "🔔 تفعيل الدردشة", "🔔 Enable")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle,              callback_data="liveadm:toggle"),
         InlineKeyboardButton(text=_tt(lang,"liveadm.btn.refresh","تحديث ♻️","Refresh ♻️"), callback_data="liveadm:refresh")],
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

# ====== أوامر الدخول ======
@router.message(Command("liveadmin"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_liveadmin(m: Message):
    lang = _L(m.from_user.id)
    txt = _tt(lang, "liveadm.title",
              "🛠️ لوحة تحكم الدردشة الحية",
              "🛠️ Live Chat Admin Panel")
    stats = _dashboard_stats(lang)
    await m.answer(f"{txt}\n\n{stats}", reply_markup=_kb_main(lang))

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

# ====== أزرار اللوحة الرئيسية ======
@router.callback_query(F.data.in_({"liveadm:refresh", "liveadm:toggle", "liveadm:sessions", "liveadm:blocklist", "liveadm:help"}),
                       F.from_user.id.in_(ADMIN_IDS))
async def cb_panel_actions(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    if cb.data == "liveadm:toggle":
        _set_support_enabled(not _support_enabled())
    if cb.data in ("liveadm:refresh","liveadm:toggle"):
        await cb.message.edit_text(_dashboard_stats(lang), reply_markup=_kb_main(lang))
        return await cb.answer("OK")
    if cb.data == "liveadm:help":
        txt = _tt(lang, "liveadm.help",
            "• هذه لوحة للتحكم بالدردشة الحية.\n• استخدم الأزرار لإدارة الجلسات والحظر.\n• يمكنك أيضًا الأمر: /block UID مدة  (مثال: /block 123 1d)\n• و /unblock UID",
            "• This panel lets you manage live chat.\n• Use buttons to manage sessions & blocklist.\n• You can also: /block UID duration  (e.g. /block 123 1d)\n• And /unblock UID")
        return await cb.message.edit_text(txt, reply_markup=_kb_main(lang))
    if cb.data == "liveadm:sessions":
        s = _load(SESSIONS_FILE)
        if not s:
            await cb.message.edit_text(_tt(lang,"liveadm.nosessions","لا توجد جلسات.","No sessions."),
                                       reply_markup=_kb_main(lang))
            return await cb.answer()
        # اعرض أول 10
        lines = [_tt(lang,"liveadm.sessions.title","📋 الجلسات:","📋 Sessions:")]
        for i, (uid, v) in enumerate(list(s.items())[:10], start=1):
            lines.append(f"{i}) UID <code>{uid}</code> | {v.get('status','-')} | SID <code>{v.get('sid','-')}</code> | start <code>{_format_ts(v.get('start_ts',0))}</code>")
        await cb.message.edit_text("\n".join(lines), reply_markup=_kb_main(lang))
        # أرسل أزرار لكل جلسة على حدة
        for uid, v in list(s.items())[:10]:
            try:
                await cb.message.answer(f"UID <code>{uid}</code>", reply_markup=_kb_session_item(int(uid), v.get("sid","-"), lang))
            except Exception: pass
        return await cb.answer()
    if cb.data == "liveadm:blocklist":
        bl = _load(BLOCKLIST_FILE)
        if not bl:
            await cb.message.edit_text(_tt(lang,"liveadm.nobl","قائمة الحظر فارغة.","Blocklist is empty."),
                                       reply_markup=_kb_main(lang))
            return await cb.answer()
        lines = [_tt(lang,"liveadm.bl.title","🚫 قائمة الحظر:","🚫 Blocklist:")]
        for uid, row in bl.items():
            until = "-"
            reason = "-"
            if isinstance(row, dict):
                u = row.get("until", 0); until = _format_ts(u) if u else "دائم/Perm"
                reason = row.get("reason","-")
            lines.append(f"• UID <code>{uid}</code> | {until} | {reason}")
        await cb.message.edit_text("\n".join(lines), reply_markup=_kb_main(lang))
        return await cb.answer()

# عرض بطاقة مستخدم/جلسة
@router.callback_query(F.data.startswith("liveadm:view:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_view_user(cb: CallbackQuery):
    uid = int(cb.data.split(":")[-1])
    lang = _L(cb.from_user.id)
    s = _load(SESSIONS_FILE).get(str(uid)) or {}
    sid = s.get("sid")
    text = _tt(lang, "liveadm.view",
        "👤 <b>مستخدم</b> <code>{uid}</code>\n• الحالة: <code>{st}</code>\n• SID: <code>{sid}</code>\n• بداية: <code>{stt}</code>",
        "👤 <b>User</b> <code>{uid}</code>\n• status: <code>{st}</code>\n• SID: <code>{sid}</code>\n• start: <code>{stt}</code>"
    ).format(uid=uid, st=s.get("status","-"), sid=(sid or "-"), stt=_format_ts(s.get("start_ts",0)))
    await cb.message.edit_text(text, reply_markup=_kb_user_actions(uid, sid, lang))
    await cb.answer()

# أزرار الحظر/فكه
def _parse_dur(s: str) -> int:
    if s == "perm": return 0
    if s.endswith("h"): return int(s[:-1]) * 3600
    if s.endswith("d"): return int(s[:-1]) * 86400
    return int(s)  # ثوانٍ

@router.callback_query(F.data.startswith("liveadm:block:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_block(cb: CallbackQuery):
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

@router.callback_query(F.data.startswith("liveadm:unblock:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_unblock(cb: CallbackQuery):
    uid = int(cb.data.split(":")[-1])
    bl = _load(BLOCKLIST_FILE); bl.pop(str(uid), None); _save(BLOCKLIST_FILE, bl)
    await cb.answer("Unblocked")
    lang = _L(cb.from_user.id)
    await cb.message.answer(_tt(lang,"liveadm.unblocked.ok","تم رفع الحظر عن {uid}.","User {uid} unblocked.").format(uid=uid))

# أوامر نصية سريعة /block /unblock (اختيارية)
@router.message(Command("block"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_block(m: Message):
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

@router.message(Command("unblock"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_unblock(m: Message):
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
