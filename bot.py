# bot.py

import asyncio
import os
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from handlers import start, help, about

# ⬅️ استدعاء ملف الأمر /start
from handlers import start

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# إنشاء البوت والموزّع (Dispatcher)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ⬅️ تسجيل أوامر start من ملف handlers/start.py
dp.include_router(start.router)
dp.include_router(help.router)
dp.include_router(about.router)
# بدء التشغيل
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
