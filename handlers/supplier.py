# handlers_supplier.py
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.utils.callback_data import CallbackData

from states import SupplierApply, AdminAsk
from db import upsert_application, get_application, set_status
from config import ADMIN_IDS, AUDIT_CHAT_ID
from i18n import t, DEFAULT_LANG

apply_cb = CallbackData("apply", "action", "user_id")  # action: approve/reject/ask

def lang_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("العربية"), KeyboardButton("English"), KeyboardButton("हिंदी"))
    return kb

def confirm_kb(lang):
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton(t(lang, "apply.btn.submit"), callback_data="confirm_submit"),
        InlineKeyboardButton(t(lang, "apply.btn.cancel"), callback_data="confirm_cancel"),
    )

def admin_kb(user_id: int, lang: str):
    return InlineKeyboardMarkup().row(
        InlineKeyboardButton(t(lang, "admin.btn.approve"), callback_data=apply_cb.new(action="approve", user_id=user_id)),
        InlineKeyboardButton(t(lang, "admin.btn.reject"), callback_data=apply_cb.new(action="reject", user_id=user_id)),
    ).add(
        InlineKeyboardButton(t(lang, "admin.btn.ask"), callback_data=apply_cb.new(action="ask", user_id=user_id))
    )

async def get_user_lang(message_or_call) -> str:
    # خزّن اللغة في user_data بالذاكرة، أو استنتج من النص
    data = getattr(message_or_call, "bot", None)
    # لأجل البساطة هنا، سنحتفظ في memory FSM فقط
    return DEFAULT_LANG

# ====== Public flow ======
def register_public(dp):
    @dp.message_handler(Command("setlang"))
    async def setlang(message: types.Message):
        await message.answer(t(DEFAULT_LANG, "ask.lang"), reply_markup=lang_kb())

    @dp.message_handler(lambda m: m.text in ["العربية", "English", "हिंदी"])
    async def choose_lang(message: types.Message, state: FSMContext):
        lang = "ar" if message.text == "العربية" else "en" if message.text == "English" else "hi"
        await state.update_data(lang=lang)
        await message.answer(t(lang, "lang.set"), reply_markup=types.ReplyKeyboardRemove())

    @dp.message_handler(Command("apply_supplier"))
    async def cmd_apply(message: types.Message, state: FSMContext):
        data = await state.get_data()
        lang = data.get("lang", DEFAULT_LANG)
        await message.answer(
            f"🧾 {t(lang, 'apply.welcome')}\n\n{t(lang, 'apply.note')}"
        )
        await message.answer(t(lang, "apply.q1"))
        await SupplierApply.FULL_NAME.set()

    @dp.message_handler(state=SupplierApply.FULL_NAME, content_types=types.ContentTypes.TEXT)
    async def q1(message: types.Message, state: FSMContext):
        await state.update_data(full_name=message.text.strip())
        data = await state.get_data()
        lang = data.get("lang", DEFAULT_LANG)
        await message.answer(t(lang, "apply.q2"))
        await SupplierApply.COUNTRY_CITY.set()

    @dp.message_handler(state=SupplierApply.COUNTRY_CITY, content_types=types.ContentTypes.TEXT)
    async def q2(message: types.Message, state: FSMContext):
        await state.update_data(country_city=message.text.strip())
        data = await state.get_data()
        lang = data.get("lang", DEFAULT_LANG)
        await message.answer(t(lang, "apply.q3"))
        await SupplierApply.CONTACT.set()

    @dp.message_handler(state=SupplierApply.CONTACT, content_types=types.ContentTypes.TEXT)
    async def q3(message: types.Message, state: FSMContext):
        await state.update_data(contact=message.text.strip())
        data = await state.get_data()
        lang = data.get("lang", DEFAULT_LANG)
        await message.answer(t(lang, "apply.q4"))
        await SupplierApply.ANDROID_EXP.set()

    @dp.message_handler(state=SupplierApply.ANDROID_EXP, content_types=types.ContentTypes.TEXT)
    async def q4(message: types.Message, state: FSMContext):
        await state.update_data(android_exp=message.text.strip())
        data = await state.get_data()
        lang = data.get("lang", DEFAULT_LANG)
        await message.answer(t(lang, "apply.q5"))
        await SupplierApply.PORTFOLIO.set()

    @dp.message_handler(state=SupplierApply.PORTFOLIO, content_types=types.ContentTypes.TEXT)
    async def q5(message: types.Message, state: FSMContext):
        await state.update_data(portfolio=message.text.strip())
        data = await state.get_data()
        lang = data.get("lang", DEFAULT_LANG)

        preview = (
            f"**{t(lang,'apply.preview_title')}**\n"
            f"- {t(lang,'apply.q1')} {data['full_name']}\n"
            f"- {t(lang,'apply.q2')} {data['country_city']}\n"
            f"- {t(lang,'apply.q3')} {data['contact']}\n"
            f"- {t(lang,'apply.q4')} {data['android_exp']}\n"
            f"- {t(lang,'apply.q5')} {data['portfolio']}\n\n"
            f"{t(lang,'apply.confirm')}"
        )
        await message.answer(preview, parse_mode="Markdown", reply_markup=confirm_kb(lang))
        await SupplierApply.CONFIRM.set()

    @dp.callback_query_handler(lambda c: c.data in ["confirm_submit", "confirm_cancel"], state=SupplierApply.CONFIRM)
    async def confirm_submit(call: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        lang = data.get("lang", DEFAULT_LANG)

        if call.data == "confirm_cancel":
            await call.message.edit_reply_markup()
            await call.message.answer(t(lang, "apply.cancelled"))
            await state.finish()
            return

        # حفظ في قاعدة البيانات
        await upsert_application(call.from_user.id, lang, data)

        # إشعار الأدمن
        text_admin = (
            f"🆕 <b>{t(lang,'admin.new_title')}</b>\n\n"
            f"<b>ID:</b> {call.from_user.id}\n"
            f"<b>Name:</b> {data['full_name']}\n"
            f"<b>Country/City:</b> {data['country_city']}\n"
            f"<b>Contact:</b> {data['contact']}\n"
            f"<b>Android Exp:</b> {data['android_exp']}\n"
            f"<b>Portfolio:</b> {data['portfolio']}\n"
            f"<b>Status:</b> {t(lang,'status.pending')}"
        )
        kb = admin_kb(call.from_user.id, lang)
        for admin_id in ADMIN_IDS:
            try:
                await call.bot.send_message(admin_id, text_admin, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass

        if AUDIT_CHAT_ID:
            try:
                await call.bot.send_message(AUDIT_CHAT_ID, text_admin, parse_mode="HTML")
            except Exception:
                pass

        await call.message.edit_reply_markup()
        await call.message.answer(t(lang, "apply.saved"))
        await state.finish()
        await call.answer()

# ====== Admin flow ======
def register_admin(dp):
    from config import ADMIN_IDS

    @dp.callback_query_handler(apply_cb.filter(), user_id=ADMIN_IDS)
    async def admin_actions(call: types.CallbackQuery, callback_data: dict, state: FSMContext):
        action = callback_data["action"]
        user_id = int(callback_data["user_id"])

        app = await get_application(user_id)
        if not app:
            await call.answer("Not found", show_alert=True)
            return

        lang = app.get("lang", "ar")

        if action == "approve":
            await set_status(user_id, "approved")
            # إشعار المتقدم
            await call.bot.send_message(user_id, t(lang, "admin.approved.user"))
            await call.message.answer(t(lang, "admin.done"))
            await call.answer()

        elif action == "reject":
            await set_status(user_id, "rejected")
            await call.bot.send_message(user_id, t(lang, "admin.rejected.user"))
            await call.message.answer(t(lang, "admin.done"))
            await call.answer()

        elif action == "ask":
            # أدخل في حالة طرح سؤال
            await state.update_data(ask_user_id=user_id, ask_lang=lang)
            await AdminAsk.WAITING_QUESTION.set()
            await call.message.answer(t(lang, "admin.ask.prompt"))
            await call.answer()

    @dp.message_handler(state=AdminAsk.WAITING_QUESTION, content_types=types.ContentTypes.TEXT, user_id=ADMIN_IDS)
    async def admin_send_question(message: types.Message, state: FSMContext):
        data = await state.get_data()
        target_user = data.get("ask_user_id")
        lang = data.get("ask_lang", "ar")
        q = message.text.strip()

        if not target_user:
            await message.answer("No user.")
            await state.finish()
            return

        await message.bot.send_message(target_user, t(lang, "admin.ask.user", q=q))
        await message.answer(t(lang, "admin.done"))
        await state.finish()
