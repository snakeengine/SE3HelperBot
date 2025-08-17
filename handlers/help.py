# 📁 handlers/help.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from lang import t, get_user_lang
from utils.maintenance import load_maintenance_mode

router = Router()
ADMIN_ID = 7360982123  # معرّف المطوّر

# ✅ دالة موحّدة لعرض واجهة المساعدة
async def help_handler_target(user_id: int, send_func):
    lang = get_user_lang(user_id)

    # 🔒 احترام وضع الصيانة (السماح للمطوّر فقط)
    if load_maintenance_mode() and user_id != ADMIN_ID:
        await send_func(t(lang, "maintenance_active"), parse_mode="HTML", disable_web_page_preview=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "help_category_app"),    callback_data="help_app")],
        [InlineKeyboardButton(text=t(lang, "help_category_game"),   callback_data="help_game")],
        [InlineKeyboardButton(text=t(lang, "help_category_reseller"), callback_data="help_reseller")],
        [InlineKeyboardButton(text=t(lang, "help_category_errors"), callback_data="help_errors")],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"),         callback_data="back_to_menu")],
    ])

    await send_func(
        t(lang, "help_intro"),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# ✅ أمر /help
@router.message(Command("help"))
async def help_cmd(message: Message):
    await help_handler_target(message.from_user.id, message.answer)

# ✅ رجوع إلى صفحة المساعدة الرئيسية
@router.callback_query(F.data == "back_to_help")
async def back_to_help(callback: CallbackQuery):
    await help_handler_target(callback.from_user.id, callback.message.edit_text)
    await callback.answer()

# ===================== الأقسام =====================

# قسم: مشاكل التطبيق
@router.callback_query(F.data == "help_app")
async def app_issues(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "help_issue_app_not_open_btn"),       callback_data="help_app_not_open")],
        [InlineKeyboardButton(text=t(lang, "help_issue_app_slow_btn"),           callback_data="help_app_slow")],
        [InlineKeyboardButton(text=t(lang, "help_issue_menu_not_showing_btn"),   callback_data="help_menu_not_showing")],
        [InlineKeyboardButton(text=t(lang, "back_to_help"),                      callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        t(lang, "help_select_app_issue"),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# قسم: مشاكل اللعبة
@router.callback_query(F.data == "help_game")
async def game_issues(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "help_issue_game_not_working_btn"), callback_data="help_game_not_working")],
        [InlineKeyboardButton(text=t(lang, "help_issue_game_crash_btn"),       callback_data="help_game_crash")],
        [InlineKeyboardButton(text=t(lang, "back_to_help"),                    callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        t(lang, "help_select_game_issue"),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# قسم: مشاكل الموردين
@router.callback_query(F.data == "help_reseller")
async def reseller_issues(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "help_issue_reseller_not_responding_btn"), callback_data="help_reseller_not_responding")],
        [InlineKeyboardButton(text=t(lang, "help_issue_reseller_fake_btn"),           callback_data="help_reseller_fake")],
        [InlineKeyboardButton(text=t(lang, "back_to_help"),                           callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        t(lang, "help_select_reseller_issue"),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# قسم: أخطاء التطبيق
@router.callback_query(F.data == "help_errors")
async def errors_issues(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "help_issue_error_code_btn"),          callback_data="help_error_code")],
        [InlineKeyboardButton(text=t(lang, "help_issue_unexpected_behavior_btn"), callback_data="help_error_unexpected")],
        [InlineKeyboardButton(text=t(lang, "back_to_help"),                       callback_data="back_to_help")],
    ])
    await callback.message.edit_text(
        t(lang, "help_select_error_issue"),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# ===================== ردود المشاكل (التفاصيل) =====================

# التطبيق لا يفتح
@router.callback_query(F.data == "help_app_not_open")
async def app_not_open(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_app_not_open_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_app_issues"), callback_data="help_app")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# التطبيق بطيء
@router.callback_query(F.data == "help_app_slow")
async def app_slow(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_app_slow_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_app_issues"), callback_data="help_app")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# المينيو لا يظهر
@router.callback_query(F.data == "help_menu_not_showing")
async def menu_not_showing(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_menu_not_showing_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_app_issues"), callback_data="help_app")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# اللعبة لا تعمل
@router.callback_query(F.data == "help_game_not_working")
async def game_not_working(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_game_not_working_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_game_issues"), callback_data="help_game")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# اللعبة تتحطم/تنهار
@router.callback_query(F.data == "help_game_crash")
async def game_crash(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_game_crash_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_game_issues"), callback_data="help_game")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# المورد لا يرد
@router.callback_query(F.data == "help_reseller_not_responding")
async def reseller_not_responding(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_reseller_not_responding_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_reseller_issues"), callback_data="help_reseller")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# مورد مزيف/غير رسمي
@router.callback_query(F.data == "help_reseller_fake")
async def reseller_fake(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_reseller_fake_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_reseller_issues"), callback_data="help_reseller")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# رمز خطأ
@router.callback_query(F.data == "help_error_code")
async def error_code(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_error_code_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_error_issues"), callback_data="help_errors")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

# سلوك غير متوقع
@router.callback_query(F.data == "help_error_unexpected")
async def error_unexpected(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "help_issue_unexpected_behavior_text"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_error_issues"), callback_data="help_errors")],
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()
