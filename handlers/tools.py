# handlers/tools.py

from aiogram import Router
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(lambda c: c.data == "tools")
async def tools_handler(callback: CallbackQuery):
    await callback.message.answer(
        "🧰 <b>Game Tools Catalog</b>\n\n"
        "<b>✅ Now Available:</b>\n"
        "• 🎱 <b>8Ball Pool</b> — Ready to use\n\n"
        "<b>🕓 Coming Soon:</b>\n"
        "• 🟤 Carrom Pool\n"
        "• 🔥 Free Fire\n"
        "• 🚗 Car Parking Multiplayer\n"
        "• 🔫 Call of Duty Mobile\n"
        "• 🧠 Mobile Legends\n"
        "• 🎮 Other Games\n\n"
        "📌 <i>Stay tuned for upcoming releases!</i>",
        parse_mode="HTML"
    )
    await callback.answer()
