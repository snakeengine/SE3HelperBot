# handlers/help.py

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

@router.message(Command("help"))
async def help_handler(message: Message):
    help_text = (
        "🆘 <b>Help Menu</b>\n\n"
        "Here's a list of what I can do:\n"
        "• /start - Welcome message\n"
        "• /download - Get the latest version of the app\n"
        "• /deviceinfo - Check your device info\n"
        "• /support - Contact our support team\n"
        "• /about - Learn more about this bot\n"
        "• /version - Check the current version\n"
        "• /lang - Change bot language\n\n"
        "If you have any questions, reach out to @snakeengine_support"
    )
    await message.answer(help_text)
