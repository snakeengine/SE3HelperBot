# handlers/start.py

from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def start_handler(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Download App", url="https://t.me/snakeengine/123")],
        [InlineKeyboardButton(text="🛠 Tools & Cheats", callback_data="tools")],
        [InlineKeyboardButton(text="📞 Support", url="https://t.me/snakeengine_support")],
        [InlineKeyboardButton(text="🌐 Language", callback_data="change_lang")],
    ])

    welcome_text = (
        "👋 Welcome to <b>Snake Engine - The Official Game Mod Assistant</b>!\n\n"
        "⚙️ Used by <b>5,000,000+</b> gamers.\n"
        "📦 Powered by <b>40+ global resellers</b>.\n"
        "🎯 Providing the most advanced tools for Android game mods.\n\n"
        "Select an option below to get started ⬇️"
    )

    await message.answer(welcome_text, reply_markup=keyboard)
