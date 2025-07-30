import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from handlers import start, help, about, support, download, tools, lang

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN is missing! Please set it in your .env file.")

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# Register all routers
dp.include_router(start.router)
dp.include_router(help.router)
dp.include_router(about.router)
dp.include_router(support.router)
dp.include_router(download.router)
dp.include_router(tools.router)
dp.include_router(lang.router)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
