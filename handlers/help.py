# 📁 handlers/help.py
from __future__ import annotations

import os
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import get_user_lang

log = logging.getLogger(__name__)

# ===== Router =====
router = Router(name="help")

# لا نعترض back_to_menu حتى يبقى عند persistent_menu
router.callback_query.filter(lambda cq: (cq.data or "").startswith("help_") or (cq.data or "") in {"back_to_help"})

# ===== إدمن (اختياري) =====
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = {int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()} or {7360982123}

# ===== نص ثنائي اللغة محلي =====
def L(lang: str, ar: str, en: str) -> str:
    return ar if (lang or "ar").lower().startswith("ar") else en

# ===== شاشة الـFAQ الرئيسية =====
async def help_handler_target(user_id: int, send_func):
    lang = get_user_lang(user_id) or "en"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=L(lang, "📱 مشاكل التطبيق", "📱 App issues"),      callback_data="help_app")],
        [InlineKeyboardButton(text=L(lang, "🎮 مشاكل اللعبة", "🎮 Game issues"),       callback_data="help_game")],
        [InlineKeyboardButton(text=L(lang, "🛒 المورّدون/الشراء", "🛒 Resellers / Purchase"), callback_data="help_reseller")],
        [InlineKeyboardButton(text=L(lang, "🧩 أخطاء ورموز", "🧩 Errors & Codes"),     callback_data="help_errors")],
        [InlineKeyboardButton(text=L(lang, "⬅️ رجوع للقائمة", "⬅️ Back to menu"),     callback_data="back_to_menu")],
    ])

    await send_func(
        L(
            lang,
            "❓ <b>الأسئلة الشائعة (FAQ)</b>\n"
            "اختر فئة المشكلة للحصول على خطوات مفصلة. إن لم تُحل مشكلتك، افتح <code>/report</code> أو استخدم الدردشة الحيّة.",
            "❓ <b>Frequently Asked Questions (FAQ)</b>\n"
            "Pick a category to see detailed steps. If that doesn’t help, open <code>/report</code> or use Live Chat."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# ===== أوامر /help و /faq =====
@router.message(Command("help", "faq"))
async def help_cmd(message: Message):
    log.info("[HELP] handler fired")
    await help_handler_target(message.from_user.id, message.answer)

# ===== توافق مع أزرار قديمة للـFAQ =====
@router.callback_query(
    F.data.in_({"bot:faq", "menu:faq", "faq", "faq_open", "help", "help:open", "faq:open"})
)
async def open_faq_compat(callback: CallbackQuery):
    await help_handler_target(callback.from_user.id, callback.message.edit_text)
    await callback.answer()

# ===== رجوع لصفحة الـFAQ الرئيسية =====
@router.callback_query(F.data == "back_to_help")
async def back_to_help(callback: CallbackQuery):
    await help_handler_target(callback.from_user.id, callback.message.edit_text)
    await callback.answer()

# ===================== الأقسام =====================

@router.callback_query(F.data == "help_app")
async def help_app(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=L(lang, "التطبيق لا يفتح", "App won’t open"),       callback_data="help_app_not_open")],
        [InlineKeyboardButton(text=L(lang, "التطبيق بطيء/يعلّق", "App is slow/laggy"), callback_data="help_app_slow")],
        [InlineKeyboardButton(text=L(lang, "القوائم لا تظهر", "Menus not showing"),    callback_data="help_menu_not_showing")],
        [InlineKeyboardButton(text=L(lang, "⬅️ رجوع", "⬅️ Back"),                      callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        L(lang, "اختر مشكلة التطبيق:", "Choose an app issue:"),
        reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_app_not_open")
async def app_not_open(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "🔧 <b>حل مشكلة: التطبيق لا يفتح</b>\n"
        "1) حدّث لأحدث إصدار من داخل البوت (قسم التطبيق).\n"
        "2) عطّل مؤقتًا VPN/حاجب الإعلانات/DNS المخصص.\n"
        "3) إعدادات الهاتف ➜ التطبيقات ➜ التطبيق ➜ التخزين ➜ امسح الكاش ثم البيانات.\n"
        "4) تأكد من وجود >500MB مساحة ثم أعد تشغيل الجهاز.\n"
        "5) إن استمرت المشكلة: احذف التطبيق وثبته من جديد.\n"
        "6) ما زالت؟ افتح <code>/report</code> واذكر طراز جهازك وإصدار النظام.",
        "🔧 <b>Fix: App won’t open</b>\n"
        "1) Update to the latest build (App section in the bot).\n"
        "2) Temporarily disable VPN/ad-block/ custom DNS.\n"
        "3) Phone Settings ➜ Apps ➜ the app ➜ Storage ➜ clear cache then data.\n"
        "4) Ensure >500MB free storage and reboot the device.\n"
        "5) If persists: uninstall then reinstall the app.\n"
        "6) Still stuck? Open <code>/report</code> with device model & OS."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لمشاكل التطبيق", "⬅️ Back to app issues"), callback_data="help_app")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_app_slow")
async def app_slow(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "⚙️ <b>تحسين الأداء</b>\n"
        "• أغلق التطبيقات في الخلفية وفعّل وضع الأداء إن وُجد.\n"
        "• استخدم اتصالًا ثابتًا (جرّب Wi-Fi بدل البيانات).\n"
        "• حدّث التطبيق وامسح الكاش.\n"
        "• عطّل أوضاع توفير الطاقة الشديدة.\n"
        "• إن لم يتحسن: أعد التثبيت.\n"
        "• ما زالت المشكلة؟ أرسل <code>/report</code> مع تسجيل شاشة قصير.",
        "⚙️ <b>Performance tips</b>\n"
        "• Close background apps; enable performance mode.\n"
        "• Prefer stable internet (try Wi-Fi instead of mobile data).\n"
        "• Update the app and clear cache.\n"
        "• Disable aggressive battery savers.\n"
        "• If no change: reinstall the app.\n"
        "• Still slow? Use <code>/report</code> with a short screen recording."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لمشاكل التطبيق", "⬅️ Back to app issues"), callback_data="help_app")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_menu_not_showing")
async def menu_not_showing(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "📋 <b>القوائم/الأزرار لا تظهر</b>\n"
        "• حدّث التطبيق.\n"
        "• امسح الكاش والبيانات ثم افتحه مجددًا.\n"
        "• جرّب تغيير اللغة من /language ثم افتح القائمة.\n"
        "• تأكد من عدم تضخيم الخط (إمكانية الوصول).\n"
        "• إن استمرت: أرسل لقطة شاشة مع <code>/report</code>.",
        "📋 <b>Menus/buttons not visible</b>\n"
        "• Update the app.\n"
        "• Clear cache/data then reopen.\n"
        "• Switch language via /language and try again.\n"
        "• Ensure system font scaling isn’t too large.\n"
        "• Still happening? Send a screenshot with <code>/report</code>."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لمشاكل التطبيق", "⬅️ Back to app issues"), callback_data="help_app")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_game")
async def help_game(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=L(lang, "اللعبة لا تعمل", "Game not working"), callback_data="help_game_not_working")],
        [InlineKeyboardButton(text=L(lang, "اللعبة تتوقف/تخرج", "Game crashes/exits"), callback_data="help_game_crash")],
        [InlineKeyboardButton(text=L(lang, "⬅️ رجوع", "⬅️ Back"), callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        L(lang, "اختر مشكلة اللعبة:", "Choose a game issue:"),
        reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_game_not_working")
async def game_not_working(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "🎮 <b>حل مشكلة: اللعبة لا تعمل</b>\n"
        "1) حدّث اللعبة والتطبيق.\n"
        "2) عطّل VPN والأدوات التي تغيّر الشبكة.\n"
        "3) اسمح بأذونات التخزين/الوسائط.\n"
        "4) امسح كاش اللعبة ثم أعد التشغيل.\n"
        "5) أثناء صيانة الخادم قد تتعطل مؤقتًا — جرّب لاحقًا.\n"
        "6) ما زالت؟ أرسل <code>/report</code> مع اسم اللعبة وجهازك.",
        "🎮 <b>Fix: Game not working</b>\n"
        "1) Update both game and app.\n"
        "2) Disable VPN/network-altering tools.\n"
        "3) Grant storage/media permissions.\n"
        "4) Clear game cache then reboot.\n"
        "5) Server maintenance can cause temporary issues — try later.\n"
        "6) Still broken? <code>/report</code> with game name & device."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لمشاكل اللعبة", "⬅️ Back to game issues"), callback_data="help_game")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_game_crash")
async def game_crash(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "💥 <b>تعطّل/خروج مفاجئ</b>\n"
        "• أفرغ مساحة ورام كافية.\n"
        "• حدّث النظام/تعريفات الرسوم إن وُجدت.\n"
        "• أزل تطبيقات الطبقة فوق الشاشة.\n"
        "• امسح بيانات اللعبة وسجّل الدخول مجددًا.\n"
        "• إن استمر، أرفق فيديو/سجل أعطال مع <code>/report</code>.",
        "💥 <b>Crashes / force closes</b>\n"
        "• Free up storage/RAM.\n"
        "• Update OS/graphics drivers if applicable.\n"
        "• Remove screen-overlay apps.\n"
        "• Clear game data and sign in again.\n"
        "• If it persists, attach video/crash log via <code>/report</code>."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لمشاكل اللعبة", "⬅️ Back to game issues"), callback_data="help_game")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_reseller")
async def help_reseller(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=L(lang, "المورّد لا يرد", "Reseller not responding"), callback_data="help_reseller_not_responding")],
        [InlineKeyboardButton(text=L(lang, "التحقق/بلاغ عن مزيف", "Verify/Report fake"),  callback_data="help_reseller_fake")],
        [InlineKeyboardButton(text=L(lang, "⬅️ رجوع", "⬅️ Back"),                        callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        L(lang, "اختر موضوعًا:", "Choose a topic:"),
        reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_reseller_not_responding")
async def reseller_not_responding(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "📨 <b>المورّد لا يرد</b>\n"
        "• المهلة المعتادة للرد حتى 24 ساعة.\n"
        "• تواصل عبر القناة الظاهرة داخل البوت فقط.\n"
        "• إن تجاوز 24 ساعة دون تحديث: افتح <code>/report</code> مع رقم الطلب ووسيلة الدفع.\n"
        "• استخدم دائمًا قائمة <b>المورّدين الموثّقين</b> داخل البوت.",
        "📨 <b>Reseller not responding</b>\n"
        "• Typical response window is up to 24h.\n"
        "• Contact them only via the in-bot channel.\n"
        "• If >24h with no update: <code>/report</code> with order ID & payment method.\n"
        "• Always use the in-bot <b>Verified Resellers</b> list."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لقسم المورّدين", "⬅️ Back to resellers"), callback_data="help_reseller")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_reseller_fake")
async def reseller_fake(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "🛡️ <b>التحقق والإبلاغ</b>\n"
        "• لا تدفع خارج القنوات الرسمية داخل البوت.\n"
        "• اطلب إثبات الهوية داخل البوت (حساب موثّق/معرّف).\n"
        "• أبلغ فورًا عبر <code>/report</code> وأرفق المحادثات والفواتير.\n"
        "• سيتواصل فريقنا معك لاتخاذ اللازم.",
        "🛡️ <b>Verify & report</b>\n"
        "• Never pay outside the official in-bot channels.\n"
        "• Ask for in-bot identity proof (verified account/ID).\n"
        "• Report immediately via <code>/report</code> with chats/invoices attached.\n"
        "• Our team will follow up."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لقسم المورّدين", "⬅️ Back to resellers"), callback_data="help_reseller")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_errors")
async def help_errors(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=L(lang, "تفسير رموز الخطأ", "Error code meanings"), callback_data="help_error_code")],
        [InlineKeyboardButton(text=L(lang, "سلوك غير متوقع", "Unexpected behavior"),   callback_data="help_error_unexpected")],
        [InlineKeyboardButton(text=L(lang, "⬅️ رجوع", "⬅️ Back"),                       callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        L(lang, "اختر موضوعًا:", "Choose a topic:"),
        reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_error_code")
async def error_code(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "🧩 <b>أكثر رموز الخطأ شيوعًا</b>\n"
        "• 401/403: صلاحيات غير كافية — سجّل الدخول أو يلزم اشتراك.\n"
        "• 404: العنصر غير متاح أو تم حذفه.\n"
        "• 406/415: إصدار قديم أو صيغة غير مدعومة — حدّث التطبيق.\n"
        "• 429: محاولات كثيرة — انتظر دقائق ثم حاول.\n"
        "• 500/502/503: مشكلة خادم — جرّب لاحقًا.\n"
        "إن ظهر رمز آخر، أرفقه في <code>/report</code>.",
        "🧩 <b>Common error codes</b>\n"
        "• 401/403: Not authorized — sign in or subscription required.\n"
        "• 404: Item not available or removed.\n"
        "• 406/415: Old version or unsupported format — update the app.\n"
        "• 429: Too many attempts — wait a few minutes.\n"
        "• 500/502/503: Server issue — try again later.\n"
        "If you see a different code, include it in <code>/report</code>."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لقسم الأخطاء", "⬅️ Back to errors"), callback_data="help_errors")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data == "help_error_unexpected")
async def error_unexpected(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id) or "en"
    text = L(
        lang,
        "🛠️ <b>سلوك غير متوقع/أخطاء عامة</b>\n"
        "1) أعد تشغيل الجهاز.\n"
        "2) امسح كاش التطبيق وحدّثه.\n"
        "3) عطّل VPN/الأدوات التي تغيّر الشبكة.\n"
        "4) إن تكرّر: أعد التثبيت.\n"
        "5) أرسل <code>/report</code> مع وصف مختصر + صور/فيديو.",
        "🛠️ <b>Unexpected behavior / generic errors</b>\n"
        "1) Reboot the device.\n"
        "2) Clear app cache and update.\n"
        "3) Disable VPN/network-altering tools.\n"
        "4) If recurring: reinstall the app.\n"
        "5) Open <code>/report</code> with a short description + screenshots/video."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=L(lang, "⬅️ رجوع لقسم الأخطاء", "⬅️ Back to errors"), callback_data="help_errors")],
        ]),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await callback.answer()
