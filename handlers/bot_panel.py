# handlers/bot_panel.py
from __future__ import annotations
import os, time, json, logging, platform, shutil, sys
from pathlib import Path
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.types import CallbackQuery, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang

router = Router(name="bot_panel")
log = logging.getLogger(__name__)

# لا تلتقط أوامر /
router.message.filter(lambda m: not ((m.text or "").lstrip().startswith("/")))
# كولباكات هذا القسم تبدأ بـ "bot:"
router.callback_query.filter(lambda cq: (cq.data or "").startswith("bot:"))

# =========================================================
# Safe edit helper — يتفادى BadRequest: message is not modified
# =========================================================
async def _safe_edit(message, *, text: Optional[str] = None, reply_markup=None,
                    parse_mode: Optional[ParseMode] = None,
                    disable_web_page_preview: Optional[bool] = None):
    """
    يحاول تعديل الرسالة بأمان:
      1) إن تغيّر النص فعلاً → edit_text
      2) إن لم يتغيّر النص لكن تغيّر المارك-أب → edit_reply_markup فقط
      3) إن لم يتغيّر شيء → لا يرمي استثناء
    """
    try:
        cur_text = getattr(message, "text", None) or ""
        if text is not None and text != cur_text:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        if reply_markup is not None:
            return await message.edit_reply_markup(reply_markup=reply_markup)
        return None
    except TelegramBadRequest as e:
        # في حال لم يتغيّر شيء فعلاً
        if "message is not modified" in str(e):
            return None
        raise

# ===== إعدادات الإدمن =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ===== أدوات ترجمة =====
def _L(uid: int) -> str:
    return (get_user_lang(uid) or "ar").lower()

def _tt(lang: str, key: str, fallback: str) -> str:
    try:
        return t(lang, key) or fallback
    except Exception:
        return fallback

def _LBL(lang: str, ar: str, en: str) -> str:
    return ar if (lang or "ar").startswith("ar") else en

# ===== بيانات علنية قابلة للتخصيص من ملفات JSON =====
PUBLIC_META_PATH = Path("data/public_meta.json")   # معلومات يراها الجميع
FAQ_PATH        = Path("data/faq.json")            # أسئلة شائعة

def _load_json(path: Path) -> Optional[dict]:
    try:
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else None
    except Exception as e:
        log.debug("load_json failed for %s: %s", path, e)
    return None

def _public_meta() -> dict:
    # القيم الافتراضية (تقدر تغيّرها من الملف لاحقًا بدون تعديل كود)
    base = {
        "brand": "Snake Engine",
        "channel": "https://t.me/SnakeEngine",
        "forum": "https://t.me/SnakeEngine1",
        "website": None,
        "support_contact": "@SnakeEngine",
        "support_hours": "10:00–22:00 (GMT+3)",
        "commands_hint_ar": "/start /help /report /language",
        "commands_hint_en": "/start /help /report /language",

        "app_latest": {  # معلومات عامة للمستخدم (ليست نظامية)
            "android": None,
            "windows": None
        },
        "premium_benefits_ar": [
            "أولوية الرد من الدعم",
            "حدود استخدام أعلى",
            "مزايا إضافية عند توفرها"
        ],
        "premium_benefits_en": [
            "Priority support",
            "Higher usage limits",
            "Extra perks when available"
        ]
    }
    file = _load_json(PUBLIC_META_PATH) or {}
    base.update(file)
    return base

def _faq(lang: str) -> list[tuple[str, str]]:
    # صيغة الملف: {"items":[{"q_ar":"..","a_ar":"..","q_en":"..","a_en":".."}, ...]}
    items = []
    d = _load_json(FAQ_PATH) or {}
    for it in d.get("items", []):
        if not isinstance(it, dict):
            continue
        if (lang or "ar").startswith("ar"):
            q = it.get("q_ar") or it.get("q") or ""
            a = it.get("a_ar") or it.get("a") or ""
        else:
            q = it.get("q_en") or it.get("q") or ""
            a = it.get("a_en") or it.get("a") or ""
        if q and a:
            items.append((q, a))
    # افتراضيات لو الملف غير موجود
    if not items:
        if (lang or "ar").startswith("ar"):
            items = [
                ("كيف أبلّغ عن مشكلة؟",
                 "استخدم الأمر /report ووصف المشكلة، أو أرفق لقطة شاشة."),
                ("كيف أغيّر اللغة؟",
                 "اكتب /language ثم اختر العربية أو الإنجليزية."),
                ("كيف يمكنني الاتصال بكم؟",
                 "اضغط زر «💬 دردشة حية» بالأسفل للتواصل مباشرة مع فريق الدعم. "
                 "كما يمكنك استخدام /report عند الحاجة.")
            ]
        else:
            items = [
                ("How to report an issue?",
                 "Use /report and describe the issue, attach a screenshot if possible."),
                ("How to change language?",
                 "Send /language and choose Arabic or English."),
                ("How can I contact you?",
                 "Tap the “💬 Live chat” button below to talk to support directly. "
                 "You can also use /report if needed.")
            ]
    return items

# ===== واجهات عامة للمستخدم (لا إفشاء لأي معلومات نظام) =====
def _kb_main(lang: str, is_admin: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=_tt(lang, "bot.menu.info",     _LBL(lang, "ℹ️ معلومات", "ℹ️ Info")),     callback_data="bot:info")
    kb.button(text=_tt(lang, "bot.menu.faq",      _LBL(lang, "❓ الأسئلة الشائعة", "❓ FAQ")), callback_data="bot:faq")
    kb.button(text=_tt(lang, "bot.menu.support",  _LBL(lang, "🆘 الدعم", "🆘 Support")),     callback_data="bot:support")
    kb.button(text=_tt(lang, "bot.menu.live",     _LBL(lang, "💬 دردشة حية", "💬 Live chat")), callback_data="bot:live")
    kb.button(text=_tt(lang, "bot.menu.forum",    _LBL(lang, "💬 المنتدى", "💬 Forum")),      callback_data="bot:forum")
    kb.button(text=_tt(lang, "bot.menu.ping",     _LBL(lang, "🏓 بينغ", "🏓 Ping")),          callback_data="bot:ping")
    kb.button(text=_tt(lang, "bot.menu.close",    _LBL(lang, "❌ إغلاق", "❌ Close")),        callback_data="bot:close")
    kb.adjust(2, 2, 2, 2)
    return kb

@router.callback_query(F.data == "bot:forum")
async def bot_forum(cb: CallbackQuery):
    lang = (get_user_lang(cb.from_user.id) or "ar").lower()
    meta_forum = (json.loads(Path("data/public_meta.json").read_text(encoding="utf-8")).get("forum")
                  if Path("data/public_meta.json").exists() else "https://t.me/SnakeEngine1")
    txt = "رابط المنتدى:\n" + meta_forum if lang.startswith("ar") else "Forum link:\n" + meta_forum
    await _safe_edit(
        cb.message,
        text=txt,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=False
    )
    await cb.answer()

@router.callback_query(F.data.in_({"bot:open", "menu:bot"}))
async def open_panel(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    is_admin = _is_admin(cb.from_user.id)
    title = _tt(lang, "bot.title", _LBL(lang, "🤖 البوت", "🤖 Bot"))
    await _safe_edit(
        cb.message,
        text=f"<b>{title}</b>\n{_tt(lang,'bot.hint', _LBL(lang, 'اختر إجراء:', 'Choose an action:'))}",
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, is_admin).as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "bot:info")
async def bot_info(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    meta = _public_meta()

    # اسم البراند من public_meta أو اسم البوت نفسه
    me = await cb.bot.get_me()
    brand = meta.get("brand") or me.first_name

    # هذه معلومات عامة للمستخدم وليست تقنية عن نظام الخادم
    lines = [
        _LBL(lang, "ℹ️ <b>معلومات</b>", "ℹ️ <b>Info</b>"),
        _LBL(lang, f"• هذا البوت تابع لـ <b>{brand}</b> ويقدّم دعمًا ومساعدة.",
                    f"• This bot belongs to <b>{brand}</b> and provides support/help."),
        _LBL(lang,
             f"• أوامر سريعة: <code>{meta.get('commands_hint_ar') or '/start /help /report /language'}</code>",
             f"• Quick commands: <code>{meta.get('commands_hint_en') or '/start /help /report /language'}</code>"
        ),
    ]

    ch = meta.get("channel"); fm = meta.get("forum"); web = meta.get("website")
    if ch:
        lines.append(_LBL(lang, f"• القناة: <a href='{ch}'>{ch}</a>", f"• Channel: <a href='{ch}'>{ch}</a>"))
    if fm:
        lines.append(_LBL(lang, f"• المنتدى: <a href='{fm}'>{fm}</a>", f"• Forum: <a href='{fm}'>{fm}</a>"))
    if web:
        lines.append(_LBL(lang, f"• الموقع: <a href='{web}'>{web}</a>", f"• Website: <a href='{web}'>{web}</a>"))

    apps = meta.get("app_latest") or {}
    # عرض إصدارات التطبيق (لو موجودة) — معلومات علنية للمستخدم
    app_lines = []
    if apps.get("android"):
        app_lines.append(_LBL(lang, f"أندرويد: <code>{apps['android']}</code>", f"Android: <code>{apps['android']}</code>"))
    if apps.get("windows"):
        app_lines.append(_LBL(lang, f"ويندوز: <code>{apps['windows']}</code>", f"Windows: <code>{apps['windows']}</code>"))

    if app_lines:
        lines.append(_LBL(lang, "• آخر إصدارات التطبيق:", "• Latest app versions:"))
        for al in app_lines:
            lines.append("  - " + al)

    await _safe_edit(
        cb.message,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=False
    )
    await cb.answer()

@router.callback_query(F.data == "bot:faq")
async def bot_faq(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    items = _faq(lang)
    title = _LBL(lang, "❓ <b>الأسئلة الشائعة</b>", "❓ <b>FAQ</b>")
    out = [title]
    for q, a in items[:10]:
        out.append(f"\n<b>• {q}</b>\n{a}")
    await _safe_edit(
        cb.message,
        text="\n".join(out),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=True
    )
    await cb.answer()

@router.callback_query(F.data == "bot:support")
async def bot_support(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    meta = _public_meta()
    contact = meta.get("support_contact") or "@SnakeEngine"
    hours   = meta.get("support_hours") or _LBL(lang, "10:00–22:00 (بتوقيت الرياض)", "10:00–22:00 (GMT+3)")
    title = _LBL(lang, "🆘 <b>الدعم</b>", "🆘 <b>Support</b>")

    lines = [
        title,
        _LBL(lang,
             "• للدردشة الفورية: اضغط «💬 دردشة حية» بالأسفل.",
             "• For instant help: tap “💬 Live chat” below."),
        _LBL(lang,
             f"• تواصل معنا: <a href='https://t.me/{contact.lstrip('@')}'>{contact}</a>",
             f"• Contact: <a href='https://t.me/{contact.lstrip('@')}'>{contact}</a>"),
        _LBL(lang, f"• ساعات العمل: <code>{hours}</code>", f"• Hours: <code>{hours}</code>"),
        _LBL(lang, "• للإبلاغ عن مشكلة: استخدم /report", "• To report an issue: use /report"),
    ]

    await _safe_edit(
        cb.message,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup(),
        disable_web_page_preview=True
    )
    await cb.answer()

def _kb_premium(lang: str, contact_user: str | None, forum_url: str | None):
    kb = InlineKeyboardBuilder()
    if contact_user:
        kb.button(
            text=_LBL(lang, "🛒 اشترك الآن", "🛒 Subscribe"),
            url=f"https://t.me/{contact_user.lstrip('@')}"
        )
    if forum_url:
        kb.button(
            text=_LBL(lang, "💬 المنتدى", "💬 Forum"),
            url=forum_url
        )
    kb.button(text=_LBL(lang, "⬅️ رجوع", "⬅️ Back"), callback_data="bot:open")
    kb.adjust(1, 1, 1)
    return kb.as_markup()

def _fmt_period(lang: str, period: str | None) -> str:
    # period أمثلة: "30d" أو "90d" أو "365d"
    if not period:
        return ""
    try:
        n = int(''.join(ch for ch in period if ch.isdigit()))
    except Exception:
        return period
    if (lang or "ar").startswith("ar"):
        if n % 365 == 0: return f"{n//365} سنة"
        if n % 30 == 0:  return f"{n//30} شهر"
        return f"{n} يوم"
    else:
        if n % 365 == 0: return f"{n//365} year(s)"
        if n % 30 == 0:  return f"{n//30} month(s)"
        return f"{n} day(s)"

@router.callback_query(F.data == "bot:ping")
async def bot_ping(cb: CallbackQuery):
    lang = _L(cb.from_user.id)
    t0 = time.perf_counter()
    try:
        await cb.answer(_tt(lang, "bot.ping.wait", _LBL(lang, "جاري القياس…", "Measuring…")), show_alert=False)
    except TelegramBadRequest:
        pass
    ms = int((time.perf_counter() - t0) * 1000)
    txt = _tt(lang, "bot.ping.ok", _LBL(lang, "🏓 بونغ", "🏓 Pong")) + f" <b>{ms} ms</b>"
    await _safe_edit(
        cb.message,
        text=txt, parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(lang, _is_admin(cb.from_user.id)).as_markup()
    )

# ===== قائمة إدارية مخفية (للأدمن فقط) =====
def _kb_admin(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=_LBL(lang, "📈 إحصائيات", "📈 Stats"), callback_data="bot:admin:stats")
    kb.button(text=_LBL(lang, "🛠️ تعيين الأوامر", "🛠️ Set Commands"), callback_data="bot:cmds")
    kb.button(text=_LBL(lang, "⬅️ رجوع", "⬅️ Back"), callback_data="bot:open")
    kb.adjust(2, 1)
    return kb

@router.callback_query(F.data == "bot:admin")
async def bot_admin(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True); return
    lang = _L(cb.from_user.id)
    await _safe_edit(
        cb.message,
        text=_LBL(lang, "🔧 <b>لوحة الإدارة</b>", "🔧 <b>Admin Panel</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_admin(lang).as_markup()
    )
    await cb.answer()

# إحصاءات داخلية — لا تظهر للمستخدمين
def _users_count_fallback() -> int:
    try:
        from middlewares.user_tracker import get_users_count  # type: ignore
        return int(get_users_count())
    except Exception:
        pass
    dfile = Path("data/users.json")
    try:
        if dfile.exists():
            d = json.loads(dfile.read_text(encoding="utf-8"))
            return len(d.keys()) if isinstance(d, dict) else 0
    except Exception:
        pass
    return 0

@router.callback_query(F.data == "bot:admin:stats")
async def bot_admin_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True); return
    lang = _L(cb.from_user.id)

    users_total = _users_count_fallback()
    # لا نعرض تفاصيل النظام هنا للمستخدم — هذي شاشة للأدمن أصلاً
    lines = [
        _LBL(lang, "📈 <b>إحصائيات (خاص بالإدارة)</b>", "📈 <b>Stats (Admin)</b>"),
        _LBL(lang, f"• إجمالي المستخدمين: <b>{users_total:,}</b>",
                    f"• Total users: <b>{users_total:,}</b>"),
    ]
    await _safe_edit(
        cb.message,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_admin(lang).as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "bot:cmds")
async def bot_set_cmds(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True); return
    lang = _L(cb.from_user.id)

    en_cmds = [
        BotCommand(command="start",    description="Show main menu"),
        BotCommand(command="help",     description="How to use the bot"),
        BotCommand(command="about",    description="About the bot"),
        BotCommand(command="report",   description="Report an issue"),
        BotCommand(command="language", description="Change language"),
    ]
    ar_cmds = [
        BotCommand(command="start",    description="عرض القائمة الرئيسية"),
        BotCommand(command="help",     description="كيفية استخدام البوت"),
        BotCommand(command="about",    description="عن البوت"),
        BotCommand(command="report",   description="الإبلاغ عن مشكلة"),
        BotCommand(command="language", description="تغيير اللغة"),
    ]
    en_admin_cmds = en_cmds + [BotCommand(command="admin", description="Admin panel")]
    ar_admin_cmds = ar_cmds + [BotCommand(command="admin", description="لوحة الإدارة")]

    ok = True
    try:
        await cb.bot.delete_my_commands(scope=BotCommandScopeDefault())
        await cb.bot.delete_my_commands(scope=BotCommandScopeDefault(), language_code="ar")
        for admin_id in ADMIN_IDS:
            try: await cb.bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception: pass
            try: await cb.bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=admin_id), language_code="ar")
            except Exception: pass

        await cb.bot.set_my_commands(en_cmds, scope=BotCommandScopeDefault(), language_code="en")
        await cb.bot.set_my_commands(ar_cmds, scope=BotCommandScopeDefault(), language_code="ar")
        for admin_id in ADMIN_IDS:
            await cb.bot.set_my_commands(en_admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id), language_code="en")
            await cb.bot.set_my_commands(ar_admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id), language_code="ar")
    except Exception as e:
        log.exception("set_my_commands failed: %r", e); ok = False

    msg = _LBL(lang, "✅ تم تحديث الأوامر.", "✅ Commands updated.") if ok else _LBL(lang, "❌ فشل تحديث الأوامر.", "❌ Failed to update commands.")
    await _safe_edit(
        cb.message,
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_admin(lang).as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "bot:close")
async def bot_close(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        await cb.answer()

