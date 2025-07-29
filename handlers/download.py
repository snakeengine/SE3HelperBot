# handlers/download.py

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

@router.message(Command("download"))
async def download_handler(message: Message):
    download_text = (
        "📥 <b>Download Snake Engine</b>\n\n"
        "Get the latest version of Snake Engine app:\n"
        "• Android (APK): https://t.me/snakeengine/123\n"
        "• Mirror Link: https://example.com/snakeengine.apk\n\n"
        "Always download from official sources to stay safe!"
    )
    await message.answer(download_text)
