# db.py
import aiosqlite
import json
from typing import Optional, Dict, Any
from datetime import datetime

DB_PATH = "bot.db"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS suppliers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    lang TEXT NOT NULL DEFAULT 'ar',
    full_name TEXT,
    country_city TEXT,
    contact TEXT,
    android_exp TEXT,
    portfolio TEXT,
    status TEXT NOT NULL DEFAULT 'pending', -- pending/approved/rejected
    admin_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_SQL)
        await db.commit()

async def upsert_application(user_id: int, lang: str, data: Dict[str, Any]):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute("""
        INSERT INTO suppliers (user_id, lang, full_name, country_city, contact, android_exp, portfolio, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            lang=excluded.lang,
            full_name=excluded.full_name,
            country_city=excluded.country_city,
            contact=excluded.contact,
            android_exp=excluded.android_exp,
            portfolio=excluded.portfolio,
            updated_at=excluded.updated_at
        """, (
            user_id, lang,
            data.get("full_name"),
            data.get("country_city"),
            data.get("contact"),
            data.get("android_exp"),
            data.get("portfolio"),
            now, now
        ))
        await db.commit()

async def set_status(user_id: int, status: str, admin_note: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute("UPDATE suppliers SET status=?, admin_note=?, updated_at=? WHERE user_id=?",
                         (status, admin_note, now, user_id))
        await db.commit()

async def get_application(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM suppliers WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
