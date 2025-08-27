# db.py
import aiosqlite
from typing import Optional, Dict, Any, List, Tuple
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
    reviewed_by INTEGER,                    -- NEW: admin id who reviewed
    reviewed_at TEXT,                       -- NEW: timestamp of review
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (status IN ('pending','approved','rejected'))
);
"""

# فهارس مفيدة للوحة الأدمن
INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_suppliers_status_created ON suppliers(status, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_suppliers_updated ON suppliers(updated_at);",
    "CREATE INDEX IF NOT EXISTS idx_suppliers_status_updated ON suppliers(status, updated_at);",
]

ALLOWED_STATUS = {"pending", "approved", "rejected"}


async def _apply_pragmas(db: aiosqlite.Connection) -> None:
    # تحسين الاستقرار والأداء في SQLite
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    await db.execute("PRAGMA busy_timeout=5000;")  # 5s


async def _ensure_extra_columns(db: aiosqlite.Connection) -> None:
    # نضيف أعمدة جديدة لو مش موجودة (ترحيل بسيط وآمن)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS __schema_probe__ (x INTEGER);
    """)
    async with db.execute("PRAGMA table_info(suppliers);") as cur:
        cols = [row[1] async for row in cur]  # name at index 1
    to_add = []
    if "reviewed_by" not in cols:
        to_add.append("ALTER TABLE suppliers ADD COLUMN reviewed_by INTEGER;")
    if "reviewed_at" not in cols:
        to_add.append("ALTER TABLE suppliers ADD COLUMN reviewed_at TEXT;")
    for sql in to_add:
        await db.execute(sql)


def _utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


# ======================== تهيئة القاعدة ========================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        await db.execute(CREATE_SQL)
        await _ensure_extra_columns(db)
        for sql in INDEXES_SQL:
            await db.execute(sql)
        await db.commit()


# ======================== عمليات الكتابة ========================
async def upsert_application(user_id: int, lang: str, data: Dict[str, Any]):
    """
    إنشاء/تحديث طلب مورد. يبقي created_at كما هو في الإنشاء الأول، ويحدّث updated_at دائمًا.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        now = _utcnow_iso()
        await db.execute(
            """
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
            """,
            (
                user_id,
                lang or "ar",
                (data or {}).get("full_name"),
                (data or {}).get("country_city"),
                (data or {}).get("contact"),
                (data or {}).get("android_exp"),
                (data or {}).get("portfolio"),
                now,
                now,
            ),
        )
        await db.commit()


async def set_status(
    user_id: int,
    status: str,
    admin_note: Optional[str] = None,
    reviewed_by: Optional[int] = None,
):
    """
    تغيير حالة طلب المورد. يضبط reviewed_at و reviewed_by تلقائيًا عند الخروج من pending.
    """
    if status not in ALLOWED_STATUS:
        raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(ALLOWED_STATUS)}")

    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        now = _utcnow_iso()
        reviewed_at = now if status in {"approved", "rejected"} else None

        await db.execute(
            """
            UPDATE suppliers
               SET status=?,
                   admin_note=?,
                   reviewed_by=?,
                   reviewed_at=?,
                   updated_at=?
             WHERE user_id=?
            """,
            (status, admin_note, reviewed_by, reviewed_at, now, user_id),
        )
        await db.commit()


# (اختياري) حذف طلب — مفيد للتنظيف اليدوي
async def delete_application(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        cur = await db.execute("DELETE FROM suppliers WHERE user_id=?", (user_id,))
        await db.commit()
        return cur.rowcount


# ======================== عمليات القراءة ========================
async def get_application(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM suppliers WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_applications(
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    order: str = "-updated_at",  # '-updated_at' | 'updated_at' | '-created_at' | 'created_at'
) -> List[dict]:
    """
    استرجاع قائمة الطلبات مع تصفية وترقيم.
    q تبحث في full_name, country_city, contact, portfolio.
    """
    if status is not None and status not in ALLOWED_STATUS:
        raise ValueError(f"Invalid status '{status}'")

    order_map = {
        "-updated_at": "updated_at DESC",
        "updated_at": "updated_at ASC",
        "-created_at": "created_at DESC",
        "created_at": "created_at ASC",
    }
    order_by = order_map.get(order, "updated_at DESC")

    conds = []
    params: List[Any] = []

    if status:
        conds.append("status = ?")
        params.append(status)

    if q:
        like = f"%{q.strip()}%"
        conds.append("(full_name LIKE ? OR country_city LIKE ? OR contact LIKE ? OR portfolio LIKE ?)")
        params.extend([like, like, like, like])

    where_sql = ("WHERE " + " AND ".join(conds)) if conds else ""
    limit = max(1, int(page_size))
    offset = max(0, (max(1, int(page)) - 1) * limit)

    sql = f"""
        SELECT *
          FROM suppliers
          {where_sql}
      ORDER BY {order_by}
         LIMIT ? OFFSET ?;
    """
    params.extend([limit, offset])

    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def count_by_status() -> Dict[str, int]:
    """
    يعيد {'pending': n1, 'approved': n2, 'rejected': n3}
    """
    sql = "SELECT status, COUNT(*) AS n FROM suppliers GROUP BY status;"
    out = {k: 0 for k in ALLOWED_STATUS}
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        async with db.execute(sql) as cur:
            async for status, n in cur:
                out[str(status)] = int(n)
    return out


async def recent(n: int = 10) -> List[dict]:
    """
    أحدث N طلبات بمختلف الحالات.
    """
    n = max(1, int(n))
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM suppliers ORDER BY updated_at DESC LIMIT ?;",
            (n,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
