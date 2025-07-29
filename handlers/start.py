# handlers/start.py (نسخة جديدة محسّنة)

from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def start_handler(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(
        text="📥 Download App Snake",
        url="https://www.mediafire.com/file/11nrqjpa6tj7ca5/SE.V2.0.0.apk/file"
    )],
    [InlineKeyboardButton(text="🧰 Game Tools & Cheats", callback_data="tools")],
    [InlineKeyboardButton(text="🆘 Contact Support", url="https://t.me/snakeengine_support")],
    [InlineKeyboardButton(text="🌐 Change Language", callback_data="change_lang")],
    ])


    welcome_text = (
        "<b>👋 Welcome to Snake Engine</b>\n"
        "🚀 <i>The Official Game Mod Assistant</i>\n\n"
        "👾 <b>Used by:</b> 5,000,000+ gamers\n"
        "🌍 <b>Resellers:</b> 40+ trusted global partners\n"
        "🎯 <b>Mission:</b> Delivering elite tools for Android game mods\n\n"
        "👇 <b>Choose an option to continue</b>"
    )

    await message.answer(welcome_text, reply_markup=keyboard)
