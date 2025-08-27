# admin/admin_hub.py
from __future__ import annotations

import os, json, time
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router(name="admin_hub")

# ===================== أدوات عامة =====================
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
    except Exception:
        pass

def tt(lang: str, key: str, fallback: str) -> str:
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fallback

# ===================== مسارات ملفات الدردشة/التقارير =====================
DATA = Path("data")
LIVE_CONFIG       = DATA / "live_config.json"       # {"enabled": true/false}
SESSIONS_FILE     = DATA / "live_sessions.json"     # { uid: {...} }
BLOCKLIST_FILE    = DATA / "live_blocklist.json"    # { uid: true | {until: ts} }
ADMIN_SEEN_FILE   = DATA / "admin_last_seen.json"   # { admin_id: {...} } أو float قديم
ADMIN_ONLINE_TTL  = int(os.getenv("ADMIN_ONLINE_TTL", "600"))

# جديد: مصادر “التقارير”
RIN_THREADS_FILE        = DATA / "support_threads.json"     # موحّد مع report_inbox/report.py
REPORT_BLOCKLIST_FILE   = DATA / "report_blocklist.json"    # بلوك لِست نظام البلاغات
REPORT_SETTINGS_FILE    = DATA / "report_settings.json"     # (قديمة) تتضمن banned[]

def _support_enabled() -> bool:
    return bool(_load(LIVE_CONFIG).get("enabled", True))

def _set_support_enabled(v: bool):
    cfg = _load(LIVE_CONFIG); cfg["enabled"] = bool(v); _save(LIVE_CONFIG, cfg)

def _admin_is_online(admin_id: int) -> bool:
    d = _load(ADMIN_SEEN_FILE)
    v = d.get(str(admin_id))
    if isinstance(v, dict):
        return bool(v.get("online"))
    try:
        return (time.time() - float(v)) <= ADMIN_ONLINE_TTL
    except Exception:
        return False

def _set_admin_online(admin_id: int, online: bool):
    d = _load(ADMIN_SEEN_FILE)
    row = d.get(str(admin_id)) or {}
    row["online"] = bool(online)
    row["ts"] = time.time()
    d[str(admin_id)] = row
    _save(ADMIN_SEEN_FILE, d)

def _online_admins_count() -> int:
    d = _load(ADMIN_SEEN_FILE); now = time.time()
    n = 0
    for v in d.values():
        if isinstance(v, dict):
            if v.get("online"): n += 1
        else:
            try:
                if (now - float(v)) <= ADMIN_ONLINE_TTL: n += 1
            except Exception:
                pass
    return n

# ====== عدّادات “التقارير — الوارد” ======
def _rin_counts():
    """
    يُرجع (open_count, closed_count, blocked_count)
    - open/closed من support_threads.json
    - blocked من report_blocklist.json + banned[] القديمة للتوافق
    """
    open_n = closed_n = 0
    try:
        d = _load(RIN_THREADS_FILE) or {}
        threads = d.get("threads") or {}
        for th in threads.values():
            st = (th or {}).get("status", "open")
            if st == "open": open_n += 1
            else: closed_n += 1
    except Exception:
        pass

    blocked = 0
    try:
        bl = _load(REPORT_BLOCKLIST_FILE) or {}
        blocked += len(list(bl.keys()))
    except Exception:
        pass
    try:
        st = _load(REPORT_SETTINGS_FILE) or {}
        banned = st.get("banned") or []
        blocked += len([x for x in banned if str(x).isdigit()])
    except Exception:
        pass

    return open_n, closed_n, blocked

# ===================== (اختياري) لوحة التطبيق =====================
try:
    from handlers.app_download import (
        _load_release as app_load_release,
        _caption as app_caption,
        _info_text as app_info_text,
    )
except Exception:
    app_load_release = None
    app_caption = None
    app_info_text = None

# ===================== عدد المستخدمين =====================
try:
    from middlewares.user_tracker import get_users_count
except Exception:
    def get_users_count() -> int:
        try:
            p = Path("data") / "users.json"
            if not p.exists(): return 0
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                u = data.get("users")
                if isinstance(u, dict): return len(u)
                if isinstance(u, list): return len(u)
                return len(data)
            if isinstance(data, list): return len(data)
            return 0
        except Exception:
            return 0

# ===================== صلاحيات =====================
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ===================== أوامر السلاش الافتراضية =====================
def _public_cmds_en() -> list[BotCommand]:
    return [
        BotCommand(command="start",          description=t("en", "cmd_start")),
        BotCommand(command="help",           description=t("en", "cmd_help")),
        BotCommand(command="about",          description=t("en", "cmd_about")),
        BotCommand(command="report",         description=t("en", "cmd_report")),
        BotCommand(command="language",       description=t("en", "cmd_language")),
        BotCommand(command="setlang",        description="Choose language"),
        BotCommand(command="apply_supplier", description="Apply as supplier"),
    ]

async def _clean_all_bot_commands(bot):
    await bot.set_my_commands([], scope=BotCommandScopeDefault(), language_code="en")
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=admin_id), language_code="en")
        except Exception:
            pass

async def _restore_default_bot_commands(bot):
    await bot.set_my_commands(_public_cmds_en(), scope=BotCommandScopeDefault(), language_code="en")
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(_public_cmds_en(), scope=BotCommandScopeChat(chat_id=admin_id), language_code="en")
        except Exception:
            pass

# ===================== لوحات =====================
def _kb_main(lang: str) -> InlineKeyboardMarkup:
    ver = ""
    if app_load_release:
        try:
            rel = app_load_release()
            if rel and rel.get("version") and rel["version"] != "-":
                ver = f" ({rel['version']})"
        except Exception:
            ver = ""

    # عدّادات التقارير
    open_n, closed_n, blocked_n = _rin_counts()
    inbox_badge   = f" {open_n}" if open_n else ""

    suppliers_reqs   = "📂 " + tt(lang, "admin_hub_btn_resapps", "طلبات الموردين")
    suppliers_dir    = "📖 " + tt(lang, "admin_hub_btn_supdir", "دليل الموردين")
    app_txt          = "📦 " + tt(lang, "admin_hub_btn_app", "التطبيق (APK)") + ver
    security_txt     = "🛡️ " + tt(lang, "admin_hub_btn_security", "الأمن (الألعاب) • أدمن")

    # زر موحّد للتقارير (يفتح قائمة فرعية)
    reports_hub      = "📮 " + tt(lang, "admin_hub_btn_reports_hub", "التقارير") + inbox_badge
    servers_inbox    = "📡 " + tt(lang, "admin_hub_btn_server", "السيرفرات — الوارد")

    # === [NEW] زر الإشعارات
    alerts_txt       = "🔔 " + tt(lang, "admin_hub_btn_alerts", "الإشعارات")

    users_count      = "👥 " + tt(lang, "admin_hub_btn_users_count", "عدد المستخدمين")
    promoters_txt    = "📣 " + tt(lang, "admin_hub_btn_promoters", "تحكم المروّجين")
    maint_text       = "🛠️ " + tt(lang, "admin_hub_btn_maintenance", "وضع الصيانة")
    live_text        = "💬 " + tt(lang, "admin.live.btn.panel", "الدردشة الحيّة")
    bot_cmds_txt     = "🧹 " + tt(lang, "admin_hub_btn_botcmds", "أوامر البوت")
    vip_admin_txt    = "👑 " + tt(lang, "admin_hub_btn_vip_admin", "إدارة VIP")
    close_txt        = "❌ " + tt(lang, "admin_hub_btn_close", "إغلاق")

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=suppliers_reqs, callback_data="ah:resapps"),
        InlineKeyboardButton(text=suppliers_dir,  callback_data="ah:supdir"),
    )
    kb.row(
        InlineKeyboardButton(text=app_txt,      callback_data="ah:app"),
        InlineKeyboardButton(text=security_txt, callback_data="sec:admin"),
    )
    kb.row(
        InlineKeyboardButton(text=reports_hub,   callback_data="ah:reports"),
        InlineKeyboardButton(text=servers_inbox, callback_data="server_status:admin"),
    )
    # === [NEW] صف الإشعارات
    kb.row(InlineKeyboardButton(text=alerts_txt, callback_data="ah:alerts"))
    kb.row(
        InlineKeyboardButton(text=users_count,   callback_data="ah:users_count"),
        InlineKeyboardButton(text=promoters_txt, callback_data="promadm:open"),
    )
    kb.row(
        InlineKeyboardButton(text=maint_text, callback_data="maint:status"),
        InlineKeyboardButton(text=live_text,  callback_data="ah:live"),
    )
    kb.row(InlineKeyboardButton(text=bot_cmds_txt, callback_data="ah:bot_cmds"))
    kb.row(
        InlineKeyboardButton(text=vip_admin_txt, callback_data="vipadm:menu"),
        InlineKeyboardButton(text=close_txt,     callback_data="ah:close"),
    )
    return kb.as_markup()

# === قائمة فرعية للتقارير ===
def _kb_reports(lang: str) -> InlineKeyboardMarkup:
    open_n, closed_n, blocked_n = _rin_counts()
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"📥 {tt(lang,'admin_hub_btn_reports_inbox','الوارد')} ({open_n})", callback_data="rin:open"),
        InlineKeyboardButton(text=f"⚙️ {tt(lang,'admin_hub_btn_reports_settings','الإعدادات')}",   callback_data="ra:open"),
    )
    kb.row(
        InlineKeyboardButton(text=f"🚫 {tt(lang,'admin_hub_btn_reports_banned','المحظورين')} ({blocked_n})", callback_data="ra:banned"),
        InlineKeyboardButton(text=f"📊 {tt(lang,'admin_hub_btn_reports_stats','إحصاءات')}",        callback_data="ah:rstats"),
    )
    kb.row(
        InlineKeyboardButton(text="🛠️ " + tt(lang,"admin_hub_btn_reports_shortcuts","اختصارات"), callback_data="ah:rshort"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang,"admin.back","رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

# === [NEW] قائمة الإشعارات: أزرار تستدعي callbacks من alerts_admin.py ===
def _kb_alerts(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=tt(lang, "alerts.menu.edit", "✍️ تعديل النص"),        callback_data="al:edit")
    kb.button(text=tt(lang, "alerts.menu.preview", "👀 معاينة"),          callback_data="al:prev")
    kb.button(text=tt(lang, "alerts.menu.send_now", "📢 إرسال الآن"),     callback_data="al:send")
    kb.button(text=tt(lang, "alerts.menu.schedule", "🕒 جدولة"),          callback_data="al:sch")
    kb.button(text=tt(lang, "alerts.menu.quick", "⏱ جدولة سريعة"),       callback_data="al:schq")
    kb.button(text=tt(lang, "alerts.menu.jobs", "🗓 الجوبز المجدولة"),    callback_data="al:jobs")
    kb.button(text=tt(lang, "alerts.menu.kind", "🗂 النوع"),              callback_data="al:kind")
    kb.button(text=tt(lang, "alerts.menu.lang", "🌐 وضع اللغة"),          callback_data="al:lang")
    kb.button(text=tt(lang, "alerts.menu.settings", "⚙️ الإعدادات"),      callback_data="al:cfg")
    kb.button(text=tt(lang, "alerts.menu.delete", "🗑️ حذف المسودة"),     callback_data="al:del")
    kb.button(text=tt(lang, "alerts.menu.stats", "📊 إحصائيات"),          callback_data="al:stats")
    kb.button(text="⬅️ " + tt(lang, "admin.back", "رجوع"),               callback_data="ah:menu")
    kb.adjust(2,2,2,2,2,1)
    return kb.as_markup()

@router.callback_query(F.data == "ah:alerts")
async def ah_alerts(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "🔔 " + tt(lang, "admin_hub_alerts_title", "إدارة الإشعارات")
    desc  = tt(lang, "admin_hub_alerts_desc", "تحكم كامل: تعديل/معاينة/إرسال/جدولة/إلغاء/إعدادات.")
    try:
        await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                                   reply_markup=_kb_alerts(lang),
                                   disable_web_page_preview=True,
                                   parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

@router.callback_query(F.data == "ah:reports")
async def ah_reports(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    open_n, closed_n, blocked_n = _rin_counts()
    text = (
        f"📮 <b>{tt(lang,'admin_hub_reports_title','التقارير')}</b>\n"
        f"{tt(lang,'admin_hub_reports_desc','إدارة البلاغات وخيوط الدعم:')}\n"
        f"• {tt(lang,'admin_hub_reports_open','مفتوحة')}: <b>{open_n}</b>\n"
        f"• {tt(lang,'admin_hub_reports_closed','مغلقة')}: <b>{closed_n}</b>\n"
        f"• {tt(lang,'admin_hub_reports_blocked','محظورون')}: <b>{blocked_n}</b>"
    )
    try:
        await cb.message.edit_text(text, reply_markup=_kb_reports(lang), parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

@router.callback_query(F.data == "ah:rstats")
async def ah_reports_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    open_n, closed_n, blocked_n = _rin_counts()
    txt = (
        f"📊 <b>{tt(lang,'admin_hub_reports_stats','إحصاءات التقارير')}</b>\n"
        f"• {tt(lang,'admin_hub_reports_open','مفتوحة')}: <code>{open_n}</code>\n"
        f"• {tt(lang,'admin_hub_reports_closed','مغلقة')}: <code>{closed_n}</code>\n"
        f"• {tt(lang,'admin_hub_reports_blocked','محظورون')}: <code>{blocked_n}</code>\n"
        f"{tt(lang,'admin_hub_reports_hint','استخدم الأزرار للتنقّل بين الوارد/الإعدادات/المحظورين.')}"
    )
    await cb.message.answer(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer("✅")

@router.callback_query(F.data == "ah:rshort")
async def ah_reports_shortcuts(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l,"admins_only","للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        "🛠️ <b>" + tt(lang,"admin_hub_reports_shortcuts","اختصارات التقارير") + "</b>\n"
        "<code>/report</code> — " + tt(lang,"admin.cmds.tip.report","فتح بلاغ دعم") + "\n"
        "<code>/rinfo &lt;uid&gt;</code> — معلومات المستخدم/الحظر/الجلسة\n"
        "<code>/rban &lt;uid&gt; &lt;hours|perm&gt;</code> — حظر مؤقّت/دائم\n"
        "<code>/runban &lt;uid&gt;</code> — رفع الحظر"
    )
    await cb.message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer("✅")

def _kb_cmds(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=tt(lang, "admin.cmds.vipadm", "/vipadm"), callback_data="ahc:send:/vipadm"),
        InlineKeyboardButton(text="/vip",        callback_data="ahc:send:/vip"),
        InlineKeyboardButton(text="/vip_status", callback_data="ahc:send:/vip_status"),
        InlineKeyboardButton(text="📣 " + tt(lang, "promadm.btn.open", "إدارة المروّجين"), callback_data="promadm:open"),
    )
    kb.row(
        InlineKeyboardButton(text="/vip_track",  callback_data="ahc:send:/vip_track"),
        InlineKeyboardButton(text="/report",     callback_data="ahc:send:/report"),
    )
    kb.row(
        InlineKeyboardButton(text="/language",   callback_data="ahc:send:/language"),
        InlineKeyboardButton(text="/setlang",    callback_data="ahc:send:/setlang"),
    )
    kb.row(InlineKeyboardButton(text="/apply_supplier", callback_data="ahc:send:/apply_supplier"))
    kb.row(InlineKeyboardButton(text="📤 " + tt(lang, "admin.cmds.btn.send_all_slash", "إرسال كل أوامر السلاش"), callback_data="ahc:slash_all"))
    kb.row(InlineKeyboardButton(text=tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

def _kb_bot_cmds(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🧹 " + tt(lang, "admin.botcmds.clean_now", "تنظيف فوري"), callback_data="ah:bot_cmds:clean"),
        InlineKeyboardButton(text="↩️ " + tt(lang, "admin.botcmds.restore", "استعادة الأوامر"), callback_data="ah:bot_cmds:restore"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

def _kb_live_main(lang: str, admin_id: int) -> InlineKeyboardMarkup:
    on = _support_enabled()
    me_on = _admin_is_online(admin_id)
    online_n = _online_admins_count()

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=("🟢 " if on else "🔴 ") + (tt(lang, "admin.live.toggle_off", "إيقاف") if on else tt(lang, "admin.live.toggle_on", "تشغيل")),
            callback_data="liveadm:toggle"
        ),
        InlineKeyboardButton(
            text=("🛑 " + tt(lang, "admin.live.avail.off", "إيقاف")) if me_on else ("✅ " + tt(lang, "admin.live.avail.on", "أنا متاح الآن")),
            callback_data="liveadm:avail_off" if me_on else "liveadm:avail_on"
        )
    )
    kb.row(
        InlineKeyboardButton(text="📋 " + tt(lang, "admin.live.list", "قائمة الجلسات"), callback_data="liveadm:list"),
        InlineKeyboardButton(text=f"👥 {tt(lang, 'admin.live.online_count', 'المتصلون')}: {online_n}", callback_data="ah:noop")
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:menu"))
    return kb.as_markup()

def _kb_live_block_durations(uid: int, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="1h",   callback_data=f"liveadm:ban:{uid}:1"),
        InlineKeyboardButton(text="24h",  callback_data=f"liveadm:ban:{uid}:24"),
        InlineKeyboardButton(text="7d",   callback_data=f"liveadm:ban:{uid}:{24*7}"),
        InlineKeyboardButton(text="30d",  callback_data=f"liveadm:ban:{uid}:{24*30}"),
        InlineKeyboardButton(text="∞",    callback_data=f"liveadm:ban:{uid}:perm"),
    )
    kb.row(InlineKeyboardButton(text=tt(lang, "admin.back", "رجوع"), callback_data="liveadm:list"))
    return kb.as_markup()

def _kb_live_list(lang: str, waiting: list[int], active: list[tuple[int,int]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for uid in waiting[:5]:
        kb.row(
            InlineKeyboardButton(text=f"🟡 {uid}", callback_data="ah:noop"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.join", "انضمام"),  callback_data=f"live:accept:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.end", "إنهاء"),     callback_data=f"live:decline:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.block", "حظر"),    callback_data=f"liveadm:block:{uid}")
        )
    for uid, aid in active[:5]:
        kb.row(
            InlineKeyboardButton(text=f"🟢 {uid} · a:{aid}", callback_data="ah:noop"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.end", "إنهاء"),          callback_data=f"live:end:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.block", "حظر"),          callback_data=f"liveadm:block:{uid}"),
            InlineKeyboardButton(text=tt(lang, "admin.live.btn.unblock", "إلغاء حظر"), callback_data=f"liveadm:unblock:{uid}")
        )
    kb.row(InlineKeyboardButton(text="⬅️ " + tt(lang, "admin.back", "رجوع"), callback_data="ah:live"))
    return kb.as_markup()

# ===================== واجهات وتحكم =====================
@router.message(Command("admin"))
async def admin_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "لوحة الأدمن ⚡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    await msg.answer(f"<b>{title}</b>\n{desc}",
                     reply_markup=_kb_main(lang),
                     disable_web_page_preview=True,
                     parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "ah:menu")
async def ah_menu(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "لوحة الأدمن ⚡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    try:
        await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                                   reply_markup=_kb_main(lang),
                                   disable_web_page_preview=True,
                                   parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

# ---- الدردشة الحيّة
@router.callback_query(F.data == "ah:live")
async def ah_live(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    status = "🟢 " + tt(lang, "admin.live.status_on", "الدردشة مفعّلة") if _support_enabled() else "🔴 " + tt(lang, "admin.live.status_off", "الدردشة متوقفة")
    desc = tt(lang, "admin.live.desc", "إدارة الدردشة الحيّة:")
    await cb.message.edit_text(f"<b>{tt(lang, 'admin.live.title', 'الدردشة الحيّة')}</b>\n{status}\n{desc}",
                               reply_markup=_kb_live_main(lang, cb.from_user.id),
                               parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "liveadm:toggle")
async def liveadm_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_support_enabled(not _support_enabled())
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        status = "🟢 " + tt(lang, "admin.live.status_on", "الدردشة مفعّلة") if _support_enabled() \
                 else "🔴 " + tt(lang, "admin.live.status_off", "الدردشة متوقفة")
        desc = tt(lang, "admin.live.desc", "إدارة الدردشة الحيّة:")
        await cb.message.edit_text(
            f"<b>{tt(lang, 'admin.live.title', 'الدردشة الحيّة')}</b>\n{status}\n{desc}",
            reply_markup=_kb_live_main(lang, cb.from_user.id),
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer()

@router.callback_query(F.data == "liveadm:avail_on")
async def liveadm_avail_on(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_admin_online(cb.from_user.id, True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_live_main(lang, cb.from_user.id))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer(tt(lang, "admin.live.avail.on.done", "تم تفعيل توفرُك"), show_alert=True)

@router.callback_query(F.data == "liveadm:avail_off")
async def liveadm_avail_off(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_admin_online(cb.from_user.id, False)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_live_main(lang, cb.from_user.id))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer(tt(lang, "admin.live.avail.off.done", "تم إيقاف توفرُك"), show_alert=True)

@router.callback_query(F.data == "liveadm:touch")
async def liveadm_touch(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    _set_admin_online(cb.from_user.id, True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        await cb.message.edit_reply_markup(reply_markup=_kb_live_main(lang, cb.from_user.id))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await cb.answer(tt(lang, "admin.live.touched", "تم تسجيل تواجدك"), show_alert=True)

@router.callback_query(F.data == "liveadm:list")
async def liveadm_list(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    sessions = _load(SESSIONS_FILE)
    waiting: list[int] = []
    active: list[tuple[int,int]] = []
    for k, s in (sessions or {}).items():
        try:
            uid = int(k)
        except Exception:
            continue
        st = s.get("status")
        if st == "waiting":
            waiting.append(uid)
        elif st == "active":
            aid = int(s.get("admin_id") or 0)
            active.append((uid, aid))
    wt = ", ".join(map(str, waiting[:10])) or tt(lang, "admin.live.no_items", "لا يوجد")
    ac = ", ".join(f"{u}(a:{a})" for u, a in active[:10]) or tt(lang, "admin.live.no_items", "لا يوجد")
    text = (
        f"🗒️ <b>{tt(lang,'admin.live.list.title','الجلسات الحالية')}</b>\n"
        f"• {tt(lang,'admin.live.waiting','منتظرة')}: {wt}\n"
        f"• {tt(lang,'admin.live.active','نشِطة')}: {ac}\n"
        f"{tt(lang,'admin.live.hint','يمكنك الانضمام/الإنهاء/الحظر من الأزرار بالأسفل.')}"
    )
    await cb.message.edit_text(text, reply_markup=_kb_live_list(lang, waiting, active), parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data.startswith("liveadm:block:"))
async def liveadm_block(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    uid = int(cb.data.split(":")[-1])
    await cb.message.answer(
        tt(lang, "admin.live.block.pick", "اختر مدة الحظر للمستخدم: ") + f"<code>{uid}</code>",
        reply_markup=_kb_live_block_durations(uid, lang),
        parse_mode=ParseMode.HTML
    )
    await cb.answer()

@router.callback_query(F.data.startswith("liveadm:ban:"))
async def liveadm_ban(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    parts = cb.data.split(":")  # liveadm:ban:<uid>:<hours|perm>
    uid = int(parts[2]); dur = parts[3]
    bl = _load(BLOCKLIST_FILE)
    if dur == "perm":
        bl[str(uid)] = True
    else:
        hours = int(dur)
        until = time.time() + hours * 3600
        bl[str(uid)] = {"until": until}
    _save(BLOCKLIST_FILE, bl)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "admin.live.block.done", "تم الحظر"), show_alert=True)

@router.callback_query(F.data.startswith("liveadm:unblock:"))
async def liveadm_unblock(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    uid = int(cb.data.split(":")[-1])
    bl = _load(BLOCKLIST_FILE)
    bl.pop(str(uid), None)
    _save(BLOCKLIST_FILE, bl)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.answer(tt(lang, "admin.live.unblock.done", "تم إلغاء الحظر"), show_alert=True)

# ---- لوحة أوامر البوت
@router.callback_query(F.data == "ah:bot_cmds")
async def ah_bot_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "🧹 " + tt(lang, "admin.botcmds.title", "التحكم بأوامر البوت")
    desc  = tt(lang, "admin.botcmds.desc", "اختر إجراء:")
    await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                               reply_markup=_kb_bot_cmds(lang),
                               disable_web_page_preview=True,
                               parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "ah:bot_cmds:clean")
async def ah_bot_cmds_clean(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    await _clean_all_bot_commands(cb.bot)
    await cb.answer("🧹 تم تنظيف أوامر البوت بالكامل.", show_alert=True)

@router.callback_query(F.data == "ah:bot_cmds:restore")
async def ah_bot_cmds_restore(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    await _restore_default_bot_commands(cb.bot)
    await cb.answer("↩️ تم استعادة أوامر البوت الافتراضية.", show_alert=True)

# ---- شاشة أوامر مختصرة
@router.callback_query(F.data == "ah:cmds")
async def ah_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(t(l, "admins_only"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = "🔧 " + tt(lang, "admin.cmds.vip_title", "أوامر VIP")
    desc  = tt(lang, "admin.cmds.desc", "اختصارات لإرسال أوامر السلاش.")
    await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                               reply_markup=_kb_cmds(lang),
                               disable_web_page_preview=True,
                               parse_mode=ParseMode.HTML)
    await cb.answer()

@router.callback_query(F.data == "ahc:slash_all")
async def ahc_slash_all(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    text = (
        "🧰 <b>" + tt(lang, "admin.cmds.slash_title", "أوامر السلاش") + "</b>\n"
        "<code>/vipadm</code> — " + tt(lang, "admin.cmds.tip.vipadm", "لوحة إدارة VIP") + "\n"
        "<code>/vip</code> — " + tt(lang, "admin.cmds.tip.vip", "لوحة المستخدم VIP") + "\n"
        "<code>/vip_status</code> — " + tt(lang, "admin.cmds.tip.vip_status", "حالةاشتراك VIP ") + "\n"
        "<code>/vip_track</code> — " + tt(lang, "admin.cmds.tip.vip_track", "تتبّع طلب VIP") + "\n"
        "<code>/report</code> — " + tt(lang, "admin.cmds.tip.report", "فتح بلاغ دعم") + "\n"
        "<code>/language</code> — " + tt(lang, "admin.cmds.tip.language", "اختيار اللغة") + "\n"
        "<code>/setlang</code> — " + tt(lang, "admin.cmds.tip.setlang", "تغيير اللغة") + "\n"
        "<code>/apply_supplier</code> — " + tt(lang, "admin.cmds.tip.apply_supplier", "طلب أن تصبح مورّدًا") + "\n"
    )
    await cb.message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer("✅")

@router.callback_query(F.data.startswith("ahc:send:/"))
async def ahc_send_one(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    cmd = cb.data.removeprefix("ahc:send:").strip()
    try:
        await cb.message.answer(f"<code>{cmd}</code>", parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await cb.answer("✅")

# ---- روابط الأقسام الأخرى
@router.callback_query(F.data == "ah:resapps")
async def ah_resapps(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from handlers.reseller_apply import _render_list_message
        await _render_list_message(cb.message, lang, "pending", 1)
    except Exception:
        await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    else:
        await cb.answer()

@router.callback_query(F.data == "ah:supdir")
async def ah_supdir(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        from handlers.supplier_directory import _render_admin_list
        await _render_admin_list(cb.message, lang, "pending", 1)
    except Exception:
        await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    else:
        await cb.answer()

# ---- لوحة التطبيق
@router.callback_query(F.data == "ah:app")
async def open_app_panel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    ver_val = None
    ver_txt = ""
    if app_load_release:
        try:
            rel = app_load_release()
            ver_val = (rel or {}).get("version")
            if ver_val and ver_val != "-":
                ver_txt = f" ({ver_val})"
        except Exception:
            ver_val = None
            ver_txt = ""

    kb = InlineKeyboardBuilder()
    kb.button(text="📤 " + tt(lang, "admin.app.btn_upload", "رفع"), callback_data="adm:app_help")
    kb.button(text="📥 " + tt(lang, "admin.app.btn_send", "إرسال") + ver_txt, callback_data="adm:app_send")
    kb.button(text="ℹ️ " + tt(lang, "admin.app.btn_info", "معلومات"),   callback_data="adm:app_info")
    kb.button(text="🗑️ " + tt(lang, "admin.app.btn_remove", "حذف"), callback_data="adm:app_remove")
    kb.adjust(2)

    title = tt(lang, "admin.app.title", "إدارة التطبيق") + (f" — {ver_val}" if ver_val else "")
    await cb.message.edit_text(title, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "adm:app_help")
async def app_help(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer(tt(lang, "admin.app.help", "أرسل ملف APK كـ Document وسيتم حفظه."))
    await cb.answer()

@router.callback_query(F.data == "adm:app_send")
async def app_send(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_caption:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "لا يوجد إصدار"), show_alert=True)
        return
    await cb.message.answer_document(document=rel["file_id"], caption=app_caption(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "adm:app_info")
async def app_info(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_info_text:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "لا يوجد إصدار"), show_alert=True)
        return
    await cb.message.answer(app_info_text(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "adm:app_remove")
async def app_remove(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    kb = InlineKeyboardBuilder()
    kb.button(text=tt(lang, "app.remove_confirm_yes", "نعم"), callback_data="app:rm_yes")
    kb.button(text=tt(lang, "app.remove_confirm_no", "لا"),  callback_data="app:rm_no")
    kb.adjust(2)
    await cb.message.answer(tt(lang, "app.remove_confirm", "تأكيد الحذف؟"), reply_markup=kb.as_markup())
    await cb.answer()

# ---- عدد المستخدمين
@router.callback_query(F.data == "ah:users_count")
async def ah_users_count(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    n = get_users_count()
    try:
        txt = f"👥 {t(lang, 'admin.users_count').format(n=n)}"
    except Exception:
        txt = f"👥 Total users: {n}"
    await cb.message.answer(txt)
    await cb.answer("✅")

# ---- VIP Shortcut
@router.message(Command("vipadm", "admin_vip"))
async def cmd_vipadm(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 " + tt(lang, "admin_hub_btn_vip_admin", "إدارة VIP"),
                              callback_data="vipadm:menu")],
        [InlineKeyboardButton(text=tt(lang, "admin.back", "رجوع"), callback_data="ah:menu")]
    ])
    await msg.reply(tt(lang, "admin.vipadm.open", "افتح لوحة إدارة VIP:"), reply_markup=kb)

@router.callback_query(F.data == "ah:close")
async def ah_close(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(tt(lang, "admin_closed", "تم الإغلاق"))
    await cb.answer()

@router.callback_query(F.data == "ah:noop")
async def ah_noop(cb: CallbackQuery):
    await cb.answer()
