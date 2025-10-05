# handlers/paydiag.py
from __future__ import annotations
import os
import aiosqlite
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from services import orders as ords

DB_PATH = os.getenv("SHOP_DB", "./data/shop.db")
ADMIN_IDS = [
    int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "7360982123")).split(",")
    if x.strip().isdigit()
]

router = Router(name="paydiag")

async def _sum(where: str = "", args: tuple = ()):
    await ords.ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        q = f"""
        SELECT
          SUM(CASE WHEN asset='USDT' THEN usd_amount ELSE 0 END) AS usd_usdt,
          SUM(CASE WHEN asset='TON'  THEN ton_amount ELSE 0 END) AS ton_sum,
          COUNT(*) AS n_orders
        FROM orders
        WHERE status IN ('paid','delivered') {(' AND ' + where) if where else ''}
        """
        cur = await db.execute(q, args)
        row = await cur.fetchone()
        usd_usdt = float(row[0] or 0)
        ton_sum  = float(row[1] or 0)
        n        = int(row[2] or 0)
        return usd_usdt, ton_sum, n

@router.message(Command("sales"))
async def sales(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.answer("Admins only.")
    parts = (msg.text or "").split()
    where, args, title = "", (), "كل الوقت"
    if len(parts) >= 2 and parts[1].isdigit():
        days = int(parts[1])
        where = "AND datetime(created_at) >= datetime('now', ?)"
        args = (f"-{days} days",)
        title = f"آخر {days} يوم"

    usd_usdt, ton_sum, n = await _sum(where, args)
    text = (
        f"📊 المبيعات — {title}\n"
        f"• فواتير ناجحة: {n}\n"
        f"• USDT المقبوضة (حسب الفواتير): ${usd_usdt:.2f}\n"
        f"• TON المقبوضة (تقريبًا): {ton_sum:.3f} TON\n\n"
        "ملاحظة: الرصيد الفعلي تتحكم به من @CryptoBot (USDT) أو محفظة TON."
    )
    await msg.answer(text)
