# 📁 handlers/tools_handler.py
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

router = Router()

# ==== Callback IDs ====
TOOLS_CB        = "tools"
TOOL_8BALL_CB   = "tool_8ball"
TOOL_CARROM_CB  = "tool_carrom"
TOOL_SOCCER_CB  = "tool_soccer"        # ✅ جديد
BACK_TO_MENU    = "back_to_menu"
BACK_TO_TOOLS   = "tools"

DEFAULT_APK_URL = "https://www.mediafire.com/file/gjd3dx7ztdlbtdl/SE_2.0.6.apk/file"

# ---------- i18n fallback helpers ----------
def L(lang: str, ar: str, en: str) -> str:
    return ar if str(lang).startswith("ar") else en

def T(lang: str, key: str, ar_fallback: str, en_fallback: str) -> str:
    """t() مع فولباك آمن لنصّ عربي/إنجليزي."""
    try:
        val = (t(lang, key) or "").strip()
    except Exception:
        val = ""
    if val and val != key:
        return val
    return L(lang, ar_fallback, en_fallback)

# ---------- download URLs ----------
def _get_download_url_for(product_slug: str, lang: str) -> str:
    """
    يبحث بالترتيب:
      <SLUG>_APK_URL  →  APK_URL  → DEFAULT_APK_URL
    مثال: CARROM_APK_URL، 8BP_APK_URL، SOCCER_APK_URL
    """
    slug_key = f"{product_slug.upper()}_APK_URL".replace("-", "_")
    url = (os.getenv(slug_key, "") or os.getenv("APK_URL", "") or "").strip()
    return url or DEFAULT_APK_URL

# ==== helper: تعديل أو إرسال رسالة بأمان ====
async def _safe_edit_or_answer(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = ParseMode.HTML,
    disable_web_page_preview: bool | None = True,
    **_
):
    if not (text or "").strip():
        text = "…"
    try:
        if message.text is not None:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        if message.caption is not None:
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        return await message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        low = str(e).lower()
        if ("no text in the message to edit" in low
            or "message can't be edited" in low
            or "message is not modified" in low):
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        raise

# ==== نص + كيبورد قائمة الأدوات ====
def tools_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎱 {T(lang,'tool_8ball','8Ball Pool','8Ball Pool')}", callback_data=TOOL_8BALL_CB)],
        [InlineKeyboardButton(text=f"🟢 {T(lang,'tool_carrom','Carrom Pool','Carrom Pool')}", callback_data=TOOL_CARROM_CB)],
        [InlineKeyboardButton(text=f"⚽️ {T(lang,'tool_soccer','Soccer Stars: Football Kick','Soccer Stars: Football Kick')}", callback_data=TOOL_SOCCER_CB)],  # جديد
        [InlineKeyboardButton(text=T(lang,'back_to_menu','العودة للقائمة','Back to menu'), callback_data=BACK_TO_MENU)],
    ])

def tools_text(lang: str) -> str:
    return (
        f"🧰 <b>{T(lang,'tools_title','كتالوج أدوات الألعاب','Games Tools Catalog')}</b>\n\n"
        f"<b>✅ {T(lang,'tools_available','متوفرة الآن','Available now')}:</b>\n"
        f"• 🎱 <b>{T(lang,'tool_8ball','8Ball Pool','8Ball Pool')}</b> — {T(lang,'tools_ready','جاهزة للاستخدام','Ready')}\n"
        f"• 🟢 <b>{T(lang,'tool_carrom','Carrom Pool','Carrom Pool')}</b> — {T(lang,'tools_ready','جاهزة للاستخدام','Ready')}\n"
        f"• ⚽️ <b>{T(lang,'tool_soccer','Soccer Stars: Football Kick','Soccer Stars: Football Kick')}</b> — {T(lang,'tools_ready','جاهزة للاستخدام','Ready')}\n\n"
        f"<b>🕓 {T(lang,'tools_coming','قريبًا','Coming soon')}:</b>\n"
        f"• 🔥 {T(lang,'tool_freefire','Free Fire','Free Fire')}\n"
        f"• 🚗 {T(lang,'tool_carparking','Car Parking Multiplayer','Car Parking Multiplayer')}\n"
        f"• 🔫 {T(lang,'tool_cod','Call of Duty Mobile','Call of Duty Mobile')}\n"
        f"• 🧠 {T(lang,'tool_ml','Mobile Legends','Mobile Legends')}\n"
        f"• 🎮 {T(lang,'tool_others','ألعاب أخرى','Other games')}\n\n"
        f"📌 <i>{T(lang,'tools_tap_hint','اضغط على أداة لرؤية ميزاتها الكاملة.','Tap a tool to see its full features.')}</i>"
    )

async def send_tools_menu(user_id: int, send_func):
    lang = get_user_lang(user_id) or "en"
    await send_func(
        tools_text(lang),
        reply_markup=tools_menu_keyboard(lang),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

# ==== Handlers ====
@router.callback_query(F.data == TOOLS_CB)
async def tools_handler(callback: CallbackQuery):
    await send_tools_menu(
        callback.from_user.id,
        lambda *a, **kw: _safe_edit_or_answer(callback.message, *a, **kw)
    )
    await callback.answer()

@router.message(Command("tools"))
async def tools_command(message: Message):
    await send_tools_menu(message.from_user.id, message.answer)

# ---------- 8Ball Pool ----------
def tool_8ball_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = []
    download_url = _get_download_url_for("8bp", lang)
    if download_url.lower().startswith(("http://", "https://")):
        buttons.append([InlineKeyboardButton(text=f"📥 {T(lang,'btn_download','تحميل التطبيق','Download App')}", url=download_url)])
    buttons.append([InlineKeyboardButton(text=T(lang,"back_to_tools","العودة للأدوات","Back to tools"), callback_data=BACK_TO_TOOLS)])
    buttons.append([InlineKeyboardButton(text=T(lang,"back_to_menu","العودة للقائمة","Back to menu"),  callback_data=BACK_TO_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def tool_8ball_text(lang: str) -> str:
    Lc = (lang or "ar").strip().lower()

    title = T(Lc, "tool_8ball_title",
              "8Ball Pool – محرك الثعبان v2",
              "8Ball Pool – Snake Engine v2")

    intro = T(Lc, "8bp_intro",
              "⚡ <i>تحكم بأكثر من 30 ميزة ذكية</i>",
              "⚡ <i>Control 30+ smart features</i>")

    # ——— الأقسام القديمة (المميّزات الأساسية) ———
    sec_core_title = "🎯 <b>" + T(Lc, "8bp.sec.core", "الميزات الأساسية", "Core Features") + "</b>"
    sec_core_lines = [
        T(Lc, "8bp.core.aim_lines", "• خطوط التصويب أثناء وبعد الضربة", "• Aim lines during & after shot"),
        T(Lc, "8bp.core.power_lock", "• قفل القوة وتعيين قوة افتراضية", "• Lock power + default power preset"),
        T(Lc, "8bp.core.pockets",    "• عرض مواضع الجيوب",             "• Show pocket positions"),
        T(Lc, "8bp.core.adblock",    "• مانع الإعلانات والعروض",        "• Ads & popup blocker"),
    ]

    sec_visual_title = "🎨 <b>" + T(Lc, "8bp.sec.visual", "تخصيص مرئي", "Visual Customization") + "</b>"
    sec_visual_lines = [
        T(Lc, "8bp.visual.line_style", "• عرض/شفافية/نمط الخط", "• Line visibility / opacity / style"),
        T(Lc, "8bp.visual.i18n",       "• واجهة متعددة اللغات",  "• Multi-language interface"),
    ]

    sec_auto_title = "⚙️ <b>" + T(Lc, "8bp.sec.automodes", "أوضاع اللعب التلقائي", "Auto Play Modes") + "</b>"
    sec_auto_lines = [
        T(Lc, "8bp.auto.modes", "• برو سريع | لاعب محترف | وضع سريع", "• Quick Pro | Pro Player | Fast Mode"),
        T(Lc, "8bp.auto.fix",   "• تصحيح الضربات غير القانونية",       "• Illegal-shot auto correction"),
    ]

    sec_queue_title = "🕹 <b>" + T(Lc, "8bp.sec.queue", "نظام الانتظار التلقائي", "Auto Matchmaking") + "</b>"
    sec_queue_lines = [
        T(Lc, "8bp.queue.auto",  "• مطابقة تلقائية",                                 "• Auto matchmaking"),
        T(Lc, "8bp.queue.info",  "• عرض معلومات الخصم (المستوى، العملات)",           "• Opponent info (level, coins)"),
    ]

    sec_smart_title = "🧠 <b>" + T(Lc, "8bp.sec.smart", "أدوات تصويب ذكية", "Smart Aiming Tools") + "</b>"
    sec_smart_lines = [
        T(Lc, "8bp.smart.prio9",   "• أولوية 9 كرات",     "• 9-ball priority"),
        T(Lc, "8bp.smart.block",   "• تعطيل الخصم",        "• Anti-opponent assists"),
        T(Lc, "8bp.smart.golden",  "• الضربة الذهبية",     "• Golden shot"),
    ]

    sec_filters_title = "💰 <b>" + T(Lc, "8bp.sec.filters", "فلاتر العملات والمباريات", "Coins & Table Filters") + "</b>"
    sec_filters_lines = [
        T(Lc, "8bp.filt.tables", "• فلاتر الطاولات (مثل 20M+ فقط)", "• Table filters (e.g., 20M+ only)"),
        T(Lc, "8bp.filt.mixed",  "• الانضمام المختلط أو المقفل",     "• Mixed/locked joining"),
        T(Lc, "8bp.filt.ratio",  "• التحكم بنسبة العملات",           "• Coins ratio control"),
    ]

    # ——— التحسينات الحديثة ———
    sec_new_title = "🆕 <b>" + T(Lc, "8bp.sec.new", "تحسينات أخيرة", "Latest Improvements") + "</b>"
    sec_new_lines = [
        T(Lc, "8bp_feat_speed",   "• أداء أسرع ولعب أكثر سلاسة",        "• Faster performance & smoother gameplay"),
        T(Lc, "8bp_feat_android", "• دعم كامل لأجهزة Android 16",       "• Full support for Android 16 devices"),
        T(Lc, "8bp_feat_auto",    "• تحسينات دقة اللعب الآلي",           "• Improved auto-play accuracy"),
        T(Lc, "8bp_feat_ads",     "• إزالة كاملة للإعلانات",            "• Ads removed completely"),
    ]

    tail_lines = [
        T(Lc, "8bp.tail.noroot",  "✅ بدون روت",                         "✅ No root"),
        T(Lc, "8bp.tail.nosys",   "✅ بدون تعديل ملفات النظام",          "✅ No system file edits"),
        T(Lc, "8bp.tail.safe",    "✅ آمن – يعمل مع اللعبة الرسمية",     "✅ Safe — works with the official game"),
    ]
    cta = T(Lc, "8bp.tail.cta",  "<b>قم بالتحميل الآن وسيطر!</b> 💥", "<b>Download now and dominate!</b> 💥")

    parts = [
        f"🎱 <b>{title}</b>",
        intro,
        "",
        sec_core_title,   *sec_core_lines,   "",
        sec_visual_title, *sec_visual_lines, "",
        sec_auto_title,   *sec_auto_lines,   "",
        sec_queue_title,  *sec_queue_lines,  "",
        sec_smart_title,  *sec_smart_lines,  "",
        sec_filters_title,*sec_filters_lines,"",
        sec_new_title,    *sec_new_lines,    "",
        *tail_lines,      "",
        cta,
    ]
    return "\n".join(parts)

@router.callback_query(F.data == TOOL_8BALL_CB)
async def tool_8ball_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    await _safe_edit_or_answer(
        callback.message,
        tool_8ball_text(lang),
        tool_8ball_keyboard(lang)
    )
    await callback.answer()

# ---------- Carrom Pool ----------
def tool_carrom_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = []
    download_url = _get_download_url_for("carrom", lang)
    if download_url.lower().startswith(("http://", "https://")):
        buttons.append([InlineKeyboardButton(text=f"📥 {T(lang,'btn_download','تحميل التطبيق','Download App')}", url=download_url)])
    buttons.append([InlineKeyboardButton(text=T(lang,"back_to_tools","العودة للأدوات","Back to tools"), callback_data=BACK_TO_TOOLS)])
    buttons.append([InlineKeyboardButton(text=T(lang,"back_to_menu","العودة للقائمة","Back to menu"),  callback_data=BACK_TO_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def tool_carrom_text(lang: str) -> str:
    return (
        f"🟢 <b>{T(lang,'tool_carrom','Carrom Pool','Carrom Pool')}</b>\n\n"
        f"• {L(lang,'أداء أسرع ولعب أكثر سلاسة','Faster performance & smoother gameplay')}\n"
        f"• {L(lang,'دعم كامل لأجهزة Android 16','Full support for Android 16 devices')}\n"
        f"• {L(lang,'إصلاح مشاكل التشغيل التلقائي وتحسين الدقة','Fixed auto-play issues & improved accuracy')}\n"
        f"• {L(lang,'إصلاح تعطل Lucky Shot','Fixed Lucky Shot crash')}\n"
        f"• {L(lang,'ميزة جديدة: تفعيل خروج/تعطل الخصم (Opponent Crash/Exit Trigger)','New feature: Opponent Crash/Exit Trigger')}\n"
        f"• {L(lang,'إضافة Pro Mode + Quick Play Mode للتحكم الكامل','Added Pro Mode + Quick Play Mode for full control')}\n"
        f"• {L(lang,'إضافة Fast Play Control للإجراءات الفورية','Added Fast Play Control for instant actions')}\n"
        f"• {L(lang,'إزالة الإعلانات بالكامل — تجربة نظيفة 100%','Ads completely removed – 100% clean experience')}\n"
    )

@router.callback_query(F.data == TOOL_CARROM_CB)
async def tool_carrom_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    await _safe_edit_or_answer(
        callback.message,
        tool_carrom_text(lang),
        tool_carrom_keyboard(lang)
    )
    await callback.answer()

# ---------- Soccer Stars: Football Kick (NEW) ----------
def tool_soccer_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = []
    download_url = _get_download_url_for("soccer", lang)   # يقرأ SOCCER_APK_URL من .env لو موجود
    if download_url.lower().startswith(("http://", "https://")):
        buttons.append([InlineKeyboardButton(text=f"📥 {T(lang,'btn_download','تحميل التطبيق','Download App')}", url=download_url)])
    buttons.append([InlineKeyboardButton(text=T(lang,"back_to_tools","العودة للأدوات","Back to tools"), callback_data=BACK_TO_TOOLS)])
    buttons.append([InlineKeyboardButton(text=T(lang,"back_to_menu","العودة للقائمة","Back to menu"),  callback_data=BACK_TO_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def tool_soccer_text(lang: str) -> str:
    title = T(lang, "tool_soccer", "Soccer Stars: Football Kick", "Soccer Stars: Football Kick")

    # استخدم L() لنص عربي/إنجليزي مباشر
    return "\n".join([
        f"⚽️ <b>{title}</b>",
        "",
        L(lang, "1) <b>تكامل رسمي مع محرك Snake Engine</b>", "1) <b>Official integration with Snake Engine</b>"),
        L(lang, "• دعم كامل ومُحسَّن داخل التطبيق.",           "• Full in-app support and optimizations."),
        L(lang, "• توافق مع إصدارات أندرويد حتى Android 16.",  "• Compatible with Android versions up to 16."),
        "",
        L(lang, "2) <b>أسلوب لعب أسرع وأكثر سلاسة</b>",         "2) <b>Faster & smoother gameplay</b>"),
        L(lang, "• تحسين سرعة الفيزيائيات واستجابة الكرة.",      "• Improved physics speed and ball response."),
        L(lang, "• دقة أفضل في التصويب والتمرير.",               "• Better accuracy for aiming and passing."),
        L(lang, "• استقرار أعلى في المباريات الفورية.",           "• Increased stability in instant matches."),
        "",
        L(lang, "3) <b>مساعد لعب ذكي</b>",                      "3) <b>Smart play assistant</b>"),
        L(lang, "• توازن أفضل للمساعدة على التصويب (Aim Assist).","• Better balance for Aim Assist."),
        L(lang, "• حماية من انقطاع الاتصال وإعادة الربط تلقائيًا.","• Connection-loss protection with auto-reconnect."),
        "",
        L(lang, "4) <b>واجهة وتجربة مستخدم مطوَّرة</b>",        "4) <b>Refined UI/UX</b>"),
        L(lang, "• قائمة حديثة متناسقة مع هوية Snake Engine.",   "• Modern menu aligned with Snake Engine brand."),
        L(lang, "• انتقالات أسرع ورسوميات أكثر سلاسة.",          "• Faster transitions and smoother visuals."),
        "",
        L(lang, "5) <b>ثبات وأداء محسَّن</b>",                   "5) <b>Stability & performance</b>"),
        L(lang, "• تقليل التهنيج ومعالجة أعطال عشوائية.",        "• Reduced stutter and random crashes."),
        L(lang, "• تحسين الأداء على الأجهزة المتوسطة والضعيفة.",  "• Optimized for mid/low-end devices."),
        "",
        L(lang, "6) <b>أوضاع وميزات إضافية</b>",                "6) <b>Extra modes & features</b>"),
        L(lang, "• وضع اللعب التلقائي المساعد (Auto Play Assist) لتحكم أسهل وأذكى.",
                    "• Auto Play Assist for easier, smarter control."),
        L(lang, "• وضع اللعب السريع (Quick/Fast Play) لمباريات فورية.",
                    "• Quick/Fast Play for instant matches."),
        L(lang, "• بدون إعلانات داخل Snake Engine لراحة أكبر.",
                    "• No ads inside Snake Engine for maximum comfort."),
    ])

@router.callback_query(F.data == TOOL_SOCCER_CB)
async def tool_soccer_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    await _safe_edit_or_answer(
        callback.message,
        tool_soccer_text(lang),
        tool_soccer_keyboard(lang)
    )
    await callback.answer()
