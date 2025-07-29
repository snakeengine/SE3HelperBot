# handlers/about.py

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

@router.message(Command("about"))
async def about_handler(message: Message):
    about_text = (
        "🤖 <b>About Snake Engine</b>\n\n"
        "This is the official bot assistant for Snake Engine - محرك ثعبان.\n"
        "🎮 We help over 5,000,000 users with game cheats, tools, and automation.\n"
        "🌍 Managed by over 40 verified resellers.\n"
        "🔐 Trusted, fast, and always online via Telegram.\n\n"
        "For official news and releases, visit:\n"
        "👉 https://t.me/snakeengine"
    )
    await message.answer(about_text)
