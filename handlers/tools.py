# handlers/tools.py

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()

# عند الضغط على زر "Game Tools & Cheats"
@router.callback_query(lambda c: c.data == "tools")
async def tools_handler(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎱 8Ball Pool", callback_data="tool_8ball")],
    ])

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
        "📌 <i>Tap a tool below to see full features.</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# عند الضغط على "8Ball Pool"
@router.callback_query(lambda c: c.data == "tool_8ball")
async def tool_8ball_handler(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Download Tool", url="https://www.mediafire.com/file/11nrqjpa6tj7ca5/SE.V2.0.0.apk/file")],
        [InlineKeyboardButton(text="👑 VIP Access (coming soon)", callback_data="vip_unavailable")]
    ])

    text = (
        "🎱 <b>8Ball Pool – Snake Engine v2</b>\n\n"
        "⚡ <i>Take control with over 30+ smart features</i>\n\n"
        "🎯 <b>Core Features</b>\n"
        "• Aim lines during and after shots\n"
        "• Power lock & custom default power\n"
        "• Pocket position display\n"
        "• Ad & offer blocker\n\n"
        "🎨 <b>Visual Customization</b>\n"
        "• Line width, transparency, and style\n"
        "• Multi-language interface\n\n"
        "⚙️ <b>Auto Play Modes</b>\n"
        "• Pro Fast | Pro Player | Fast Mode\n"
        "• Break fix for illegal/failed shots\n\n"
        "🕹 <b>Auto Queue System</b>\n"
        "• Matchmaking automation\n"
        "• View rival info (Level, Coins)\n\n"
        "🧠 <b>Smart Shot Tools</b>\n"
        "• 9-ball prioritizer\n"
        "• Paralysis (disable opponent turns)\n"
        "• Golden Shot (target assist)\n\n"
        "💰 <b>Coin & Match Filters</b>\n"
        "• Table filters (e.g. 20M+ only)\n"
        "• Mixed or locked table join\n"
        "• Coin % control\n\n"
        "✅ No root\n"
        "✅ No system file edits\n"
        "✅ Safe – Works with official game\n\n"
        "<b>Download now and dominate!</b> 💥"
    )

    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

# إذا ضغط المستخدم على زر VIP (قريبًا)
@router.callback_query(lambda c: c.data == "vip_unavailable")
async def vip_unavailable_handler(callback: CallbackQuery):
    await callback.answer("👑 VIP Access will be available soon!", show_alert=True)
