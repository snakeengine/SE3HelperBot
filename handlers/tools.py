# handlers/tools.py

from aiogram import Router, types
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(lambda c: c.data == "tools")
async def tools_handler(callback: CallbackQuery):
    await callback.message.answer(
        "🧰 <b>Available Game Tools:</b>\n\n"
        "🎮 8ballpool\n"
        "🔥 carrom pool\n"
        "🧠 Free Fire\n"
        "🚗 Car Parking Multiplayer\n"
        "🔫 Call of Duty Mobile\n"
        "📲 Others coming soon...\n\n"
        "Use /support if you need help using a tool."
    )
    await callback.answer()
