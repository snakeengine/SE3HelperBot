# handlers/support.py

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

@router.message(Command("support"))
async def support_handler(message: Message):
    support_text = (
        "📞 <b>Need Help?</b>\n\n"
        "If you're facing issues with the app or need help:\n"
        "• Join our support group: @snakeengine_support\n"
        "• Contact admin: @snakeengine_admin\n"
        "• Report bugs or feedback anytime.\n\n"
        "We're here 24/7 to help Snake Engine users!"
    )
    await message.answer(support_text)
