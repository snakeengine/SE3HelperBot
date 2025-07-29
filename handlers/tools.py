# handlers/tools.py

from aiogram import Router
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(lambda c: c.data == "tools")
async def tools_handler(callback: CallbackQuery):
    await callback.message.answer(
        "🧰 <b>Available Game Tools:</b>\n\n"
        "🎱 8Ball Pool ✅ (Ready)\n"
        "🟤 Carrom Pool – Coming soon\n"
        "🔥 Free Fire – Coming soon\n"
        "🚗 Car Parking Multiplayer – Coming soon\n"
        "🔫 Call of Duty Mobile – Coming soon\n"
        "🧠 Mobile Legends – Coming soon\n"
        "🎮 Others – Coming soon\n\n"
        "Use /support if you need help using a tool."
    )
    await callback.answer()
