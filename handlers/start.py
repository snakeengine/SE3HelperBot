from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from lang import t
from lang import get_user_lang

router = Router()

@router.message(Command("start"))
async def start_handler(message: Message):
    lang = get_user_lang(message.from_user.id)
    
    text = (
        f"👋 <b>{t(lang, 'start_welcome')}</b>\n"
        f"🚀 <i>{t(lang, 'start_description')}</i>\n\n"
        "👾 <b>Used by:</b> 5,000,000+ gamers\n"
        "🌐 <b>Resellers:</b> 40+ trusted global partners\n"
        "🎯 <b>Mission:</b> Delivering elite tools for Android game mods\n\n"
        "👇 <b>Choose an option to continue</b>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📥 {t(lang, 'btn_download')}", url="https://www.mediafire.com/file/11nrqjpa6tj7ca5/SE.V2.0.0.apk/file")],
        [InlineKeyboardButton(text=f"🧰 {t(lang, 'btn_tools')}", callback_data="tools")],
        [InlineKeyboardButton(text=f"💎 {t(lang, 'btn_vip')}", callback_data="vip_info")],
        [InlineKeyboardButton(text=f"🌐 {t(lang, 'btn_lang')}", callback_data="change_lang")]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "vip_info")
async def vip_info_handler(callback: CallbackQuery):
    vip_text = (
        "💎 <b>VIP Subscription Guide</b>\n\n"
        "To activate your VIP subscription:\n\n"
        "1. Open the Snake Engine app.\n"
        "2. Tap the <b>Shopping Cart 🛒</b> icon (bottom bar).\n"
        "3. Choose your country from the list.\n"
        "4. Contact one of the verified resellers.\n\n"
        "✅ You’ll get the best prices and instant activation."
    )
    await callback.message.edit_text(vip_text, parse_mode="HTML")
