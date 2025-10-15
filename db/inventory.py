# db/inventory.py
import os, time, re
import aiosqlite
from typing import Iterable, Dict, Tuple, List, Optional

DB_PATH = os.getenv("SHOP_DB", "shop.db")  # على Railway = /data/shop.db

def _norm_plan(x: str) -> str:
    x = (x or "").strip().lower()
    if not x:
        return ""
    x = x.replace(" ", "")
    m = re.fullmatch(r"(\d+)(d)?", x)
    if not m:
        return x
    return f"{int(m.group(1))}d"

async def ensure_db():
    # هام: لا تستعمل "await connect" داخل "async with"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            code       TEXT PRIMARY KEY,
            product    TEXT NOT NULL,     -- ثابت: "sevip"
            plan       TEXT NOT NULL,     -- مثل: "3d"
            game       TEXT,              -- مثل: "8bp"
            status     TEXT NOT NULL DEFAULT 'free',  -- free/used/hold
            created_at INTEGER NOT NULL,
            used_at    INTEGER
        );
        """)
        # فهرس سريع للاستعلامات
        await db.execute("CREATE INDEX IF NOT EXISTS idx_inv_prod_plan_game ON inventory(product, plan, game, status)")
        await db.commit()

async def add_codes(*, product: str, plan: str, game: Optional[str], codes: Iterable[str]) -> Tuple[int, int]:
    """ترجع (saved, duplicated)."""
    plan = _norm_plan(plan)
    now = int(time.time())
    saved = 0
    dup = 0
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        for raw in codes:
            code = (raw or "").strip()
            if not code:
                continue
            try:
                await db.execute(
                    "INSERT INTO inventory(code, product, plan, game, status, created_at) VALUES (?,?,?,?, 'free', ?)",
                    (code, product, plan, game, now),
                )
                saved += 1
            except aiosqlite.IntegrityError:
                dup += 1
        await db.commit()
    return saved, dup

async def count_available(product: str, plan: str, *, game: Optional[str] = None) -> int:
    """يعد المتاح (free). يدعم توافقاً: قيود قديمة محفوظة كـ product='8bp'."""
    plan = _norm_plan(plan)
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        if game:
            # (sevip + game) أو legacy حيث product=game
            q = """
            SELECT COUNT(*) FROM inventory
            WHERE status='free' AND plan=? AND
                  ( (product=? AND game=?) OR (product=?) )
            """
            row = await db.execute_fetchone(q, (plan, product, game, game))
        else:
            q = "SELECT COUNT(*) FROM inventory WHERE status='free' AND product=? AND plan=?"
            row = await db.execute_fetchone(q, (product, plan))
        return int(row[0]) if row else 0

async def stats_by_product(product: str, *, game: Optional[str] = None) -> Dict[str, int]:
    """إحصاء حسب الخطة."""
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        if game:
            q = """
            SELECT plan, COUNT(*) FROM inventory
            WHERE status='free' AND
                  ( (product=? AND game=?) OR (product=?) )
            GROUP BY plan
            """
            rows = await db.execute_fetchall(q, (product, game, game))
        else:
            q = "SELECT plan, COUNT(*) FROM inventory WHERE status='free' AND product=? GROUP BY plan"
            rows = await db.execute_fetchall(q, (product,))
    return {plan: int(c) for plan, c in rows}

async def bulk_use(product: str, plan: str, n: int, *, game: Optional[str] = None) -> List[str]:
    """
    يحجز n أكواد ويرجعها. (بسيطة، بدون معاملات معقدة).
    """
    plan = _norm_plan(plan)
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        if game:
            sel = """
            SELECT code FROM inventory
            WHERE status='free' AND plan=? AND
                  ( (product=? AND game=?) OR (product=?) )
            LIMIT ?
            """
            rows = await db.execute_fetchall(sel, (plan, product, game, game, n))
        else:
            sel = "SELECT code FROM inventory WHERE status='free' AND product=? AND plan=? LIMIT ?"
            rows = await db.execute_fetchall(sel, (product, plan, n))
        codes = [r[0] for r in rows]
        if not codes:
            return []
        # علّمها مستخدمة
        await db.executemany(
            "UPDATE inventory SET status='used', used_at=? WHERE code=?",
            [(int(time.time()), c) for c in codes],
        )
        await db.commit()
        return codes
