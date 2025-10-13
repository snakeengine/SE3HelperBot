# services/orders.py
from __future__ import annotations

import os
import aiosqlite
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

# ✅ مسار البيانات الموحّد (يجب أن يشير إلى Volume على السيرفر)
from utils.paths import BASE

__all__ = [
    "Order",
    "ensure_db",
    "create_order",
    "get_by_id",
    "get_by_invoice_hash",
    "list_user_pending",
    "list_pending",
    "list_between",
    "count_by_status",
    "mark_cancelled_if_pending",
    "mark_paid",
    "save_delivery",
    "mark_expired_if_needed",
    "DB_PATH",
    "DB_IS_URI",
]

# ======================= أدوات مسارات قاعدة البيانات =======================
def _compute_db_path() -> tuple[str, bool]:
    """
    يُعيد (db_path, is_uri).
    - لو SHOP_DB موجود:
        * يبدأ بـ "file:" → نتعامل معه كـ SQLite URI (is_uri=True)
        * مسار مطلق يُستخدم كما هو
        * مسار نسبي → نخزّنه داخل BASE مع إزالة بادئة 'data/' أو './'
    - لو غير موجود → BASE / 'shop.db'
    """
    env = (os.getenv("SHOP_DB") or "").strip()
    if env:
        if env.startswith("file:"):
            return env, True  # URI mode
        p = Path(env)
        if p.is_absolute():
            return str(p), False
        # نسبي: نتخلّص من "." و"data/" كبادئة توافقية
        parts = [x for x in p.parts if x not in (".",)]
        if parts and parts[0].lower() == "data":
            parts = parts[1:]
        p2 = (BASE / Path(*parts if parts else ("shop.db",))).resolve()
        if p2.is_dir():
            p2 = p2 / "shop.db"
        return str(p2), False
    # الافتراضي
    return str((BASE / "shop.db").resolve()), False


DB_PATH, DB_IS_URI = _compute_db_path()

# نطبع مسارات التخزين مرة واحدة للتشخيص على السيرفر
_printed_paths_once = False
def _print_paths_once():
    global _printed_paths_once
    if _printed_paths_once:
        return
    _printed_paths_once = True
    try:
        # لا تستخدم logging هنا لضمان الظهور حتى قبل إعداد اللوجر
        print(f"[STORAGE] BASE={BASE}")
        print(f"[STORAGE] DB_PATH={DB_PATH} (URI={DB_IS_URI})")
    except Exception:
        pass


def _dir_of_db(db_path: str, is_uri: bool) -> Path:
    """
    يُرجع مجلد قاعدة البيانات مع دعم صيغة URI مثل:
      file:/data/se3helperbot/shop.db?cache=shared&mode=rwc
      file:///data/se3helperbot/shop.db
    """
    if is_uri and db_path.startswith("file:"):
        # قص 'file:' وخذ الجزء قبل علامات الاستفهام
        path_part = db_path[5:]
        # يدعم كل من file:/path و file:///path
        # نزيل أي عدد من الأشرطة المسبوقة الزائدة
        while path_part.startswith("/"):
            path_part = path_part[1:]
        # الآن path_part بدون 'file:' وبدون '/' الأول، أعده كاملاً كمسار مطلق
        # الحل الأبسط: split('?',1) وأعد '/' + left
        left = "/" + path_part.split("?", 1)[0]
        return Path(left).expanduser().resolve().parent
    # مسار عادي
    return Path(db_path).expanduser().resolve().parent


# ======================= نموذج الطلب =======================
@dataclass
class Order:
    id: int | None = None
    user_id: int | None = None
    username: str | None = ""
    slug: str | None = None
    days: int | None = None
    qty: int | None = None
    usd_amount: float | None = None
    ton_amount: float | None = None
    asset: str | None = None
    to_address: str | None = ""
    status: str | None = "pending"
    lang: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    invoice_hash: str | None = None
    delivered_text: str | None = None

    # توافق: بعض الأجزاء تعتمد على خاصية product
    product: str | None = field(default=None, repr=False)

    def __post_init__(self):
        # حافظ على التوافق بين product و slug
        if not self.product:
            self.product = self.slug
        if not self.slug and self.product:
            self.slug = self.product


# ======================= أدوات عامة =======================
def _now_iso() -> str:
    # ISO بدون تحريف المنطقة الزمنية (UTC)
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


async def ensure_db() -> None:
    """إنشاء/ترقية قاعدة البيانات وفهارس الأداء."""
    _print_paths_once()

    # أنشئ مجلد قاعدة البيانات حتى مع URI
    db_dir = _dir_of_db(DB_PATH, DB_IS_URI)
    db_dir.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        # تحسينات موصى بها لـ SQLite في الخدمات
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                slug TEXT NOT NULL,           -- مثال: 8bp (نخزن product هنا للتوافق)
                days INTEGER NOT NULL,        -- 3/10/30
                qty INTEGER NOT NULL,
                usd_amount REAL NOT NULL,
                ton_amount REAL NOT NULL,     -- نستخدمها لمبلغ العملة أياً كانت
                asset TEXT NOT NULL,          -- TON/USDT/USDC/...
                to_address TEXT,              -- عنوان/رابط الدفع (إن وجد)
                status TEXT NOT NULL DEFAULT 'pending',  -- pending/paid/delivered/cancelled/expired
                lang TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                invoice_hash TEXT,            -- invoice_id لِـ CryptoPay مثلاً
                delivered_text TEXT
            );
            """
        )
        # ✅ ترقية المخطط لو قاعدة قديمة (إضافة أعمدة ناقصة بأمان)
        await _patch_schema_if_needed(db)

        # فهارس شائعة
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_status       ON orders(status);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_status  ON orders(user_id, status);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at   ON orders(created_at);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_invoice_hash ON orders(invoice_hash);")
        await db.commit()


async def _patch_schema_if_needed(db: aiosqlite.Connection) -> None:
    """يتحقق من أعمدة الجدول ويجري ALTER TABLE للأعمدة المفقودة."""
    cur = await db.execute("PRAGMA table_info(orders)")
    cols = [r[1] for r in await cur.fetchall()]  # name في الحقل 1
    to_add: List[Tuple[str, str]] = []
    if "lang" not in cols:
        to_add.append(("lang", "TEXT"))
    if "expires_at" not in cols:
        to_add.append(("expires_at", "TEXT"))
    if "invoice_hash" not in cols:
        to_add.append(("invoice_hash", "TEXT"))
    if "delivered_text" not in cols:
        to_add.append(("delivered_text", "TEXT"))

    for name, typ in to_add:
        await db.execute(f"ALTER TABLE orders ADD COLUMN {name} {typ};")
    if to_add:
        await db.commit()


def _row_to_order(row: aiosqlite.Row) -> Order:
    """تحويل sqlite row إلى كائن Order مع الحفاظ على التوافق."""
    data: Dict[str, object] = {k: row[k] for k in row.keys()}
    if "product" not in data:
        data["product"] = data.get("slug")
    return Order(**data)  # type: ignore[arg-type]


# ======================= CRUD أساسية =======================
async def create_order(
    user_id: int,
    username: str,
    days: int,
    qty: int,
    usd_amount: float,
    ton_amount: float,
    asset: str,
    to_address: str,
    lang: str,
    expires_at,
    invoice_hash: str | None = None,
    # حقول اختيارية/توافق قديم:
    slug: str | None = None,
    **extra,  # يبتلع أي وسيط زائد (مثل product) بدون خطأ
) -> Order:
    """
    ملاحظات:
      - إن أرسلتَ product='8bp' أو slug='8bp' تُحفظ في عمود slug (توافق قديم).
      - أي وسائط إضافية ستتجاهل (extra**).
    """
    await ensure_db()

    # التوافق مع مناداة قديمة product=... أو slug=...
    if not slug:
        slug = str(extra.pop("product", "8bp"))
    else:
        slug = str(slug or "8bp")

    # صياغة تاريخ الانتهاء كنص
    if isinstance(expires_at, str):
        exp_str = expires_at
    elif isinstance(expires_at, datetime):
        exp_str = expires_at.replace(tzinfo=None).isoformat()
    else:
        exp_str = str(expires_at)

    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO orders
            (user_id, username, slug, days, qty, usd_amount, ton_amount, asset, to_address, lang, expires_at, invoice_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                username or "",
                slug,
                int(days),
                int(qty),
                float(usd_amount),
                float(ton_amount),
                asset,
                to_address or "",
                (lang or "").strip() or None,
                exp_str,
                invoice_hash,
            ),
        )
        await db.commit()

        cur = await db.execute("SELECT * FROM orders WHERE id = last_insert_rowid()")
        row = await cur.fetchone()
        return _row_to_order(row)


async def get_by_id(order_id: int) -> Optional[Order]:
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        row = await cur.fetchone()
        return _row_to_order(row) if row else None


async def get_by_invoice_hash(invoice_hash: str) -> Optional[Order]:
    """يساعد في تتبّع فواتير Crypto Pay."""
    if not invoice_hash:
        return None
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE invoice_hash=? LIMIT 1", (invoice_hash,))
        row = await cur.fetchone()
        return _row_to_order(row) if row else None


# ======================= استعلامات شائعة =======================
async def list_user_pending(user_id: int) -> List[Order]:
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE user_id=? AND status='pending' ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [_row_to_order(r) for r in rows]


async def list_pending() -> List[Order]:
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE status='pending' ORDER BY id ASC"
        )
        rows = await cur.fetchall()
        return [_row_to_order(r) for r in rows]


async def list_between(start_iso: str, end_iso: str) -> List[Order]:
    """قائمة الطلبات بين تاريخين (لمهام التقارير/التصدير)."""
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM orders
            WHERE datetime(created_at) >= datetime(?)
              AND datetime(created_at) <  datetime(?)
            ORDER BY id DESC
            """,
            (start_iso, end_iso),
        )
        rows = await cur.fetchall()
        return [_row_to_order(r) for r in rows]


async def count_by_status() -> Dict[str, int]:
    """عداد بسيط لكل حالة — مفيد للتبويب في لوحات الإدارة."""
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT status, COUNT(*) as c FROM orders GROUP BY status"
        )
        rows = await cur.fetchall()
        return {r["status"]: int(r["c"]) for r in rows}


# ======================= تحديثات حالة =======================
async def mark_cancelled_if_pending(order_id: int) -> None:
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        await db.execute(
            "UPDATE orders SET status='cancelled' WHERE id=? AND status='pending'",
            (order_id,),
        )
        await db.commit()


async def mark_paid(order_id: int) -> None:
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        await db.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
        await db.commit()


async def save_delivery(order_id: int, text: str) -> None:
    await ensure_db()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        await db.execute(
            "UPDATE orders SET status='delivered', delivered_text=? WHERE id=?",
            (text, order_id),
        )
        await db.commit()


async def mark_expired_if_needed(now_iso: Optional[str] = None) -> int:
    """
    يعلّم الطلبات 'expired' إذا كانت pending وانتهت مدة الفاتورة.
    يعيد عدد السجلات المتأثرة.
    """
    await ensure_db()
    now_iso = now_iso or _now_iso()
    async with aiosqlite.connect(DB_PATH, uri=DB_IS_URI) as db:
        cur = await db.execute(
            """
            UPDATE orders
               SET status='expired'
             WHERE status='pending'
               AND expires_at IS NOT NULL
               AND datetime(expires_at) < datetime(?)
            """,
            (now_iso,),
        )
        await db.commit()
        return cur.rowcount or 0
