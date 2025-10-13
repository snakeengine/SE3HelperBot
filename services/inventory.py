from __future__ import annotations

# services/inventory.py

import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Tuple, List, Dict, Optional

from utils.paths import BASE

# ------------------------ تخزين ثابت تحت BASE ------------------------
DATA_DIR = BASE / "inventory"
USED_DIR = BASE / "used"                # أرشفة المصروفة/المحذوفة
LOCKS_DIR = BASE / ".locks"             # أقفال خفيفة بالملفات

for d in (DATA_DIR, USED_DIR, LOCKS_DIR):
    d.mkdir(parents=True, exist_ok=True)

PRODUCT_KEY = os.getenv("PRODUCT_KEY", "8bp")

_printed_once = False
def _print_paths_once():
    global _printed_once
    if _printed_once:
        return
    _printed_once = True
    try:
        print(f"[STORAGE] BASE={BASE}")
        print(f"[STORAGE] INVENTORY_DIR={DATA_DIR}")
        print(f"[STORAGE] USED_DIR={USED_DIR}")
    except Exception:
        pass

_print_paths_once()

# ------------------------ ترحيل مسارات قديمة (مرة واحدة) ------------------------
def _maybe_migrate_legacy_dirs():
    """
    ينقل محتوى ./inventory و ./used (إن وُجدت بجانب المشروع) إلى المسارات تحت BASE
    مع الدمج ومنع التكرار.
    """
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        (repo_root / "inventory", DATA_DIR),
        (repo_root / "used", USED_DIR),
    ]
    for src, dst in candidates:
        if not src.exists() or src.resolve() == dst.resolve():
            continue
        for p in src.rglob("*"):
            if p.is_file():
                rel = p.relative_to(src)
                t = dst / rel
                t.parent.mkdir(parents=True, exist_ok=True)
                if not t.exists():
                    try:
                        shutil.copy2(p, t)
                    except Exception:
                        pass
                else:
                    # دمج نص بسيط لملفات .txt (قوائم مفاتيح)
                    if p.suffix.lower() == ".txt":
                        try:
                            cur_lines = _read_lines(t)
                            add_lines = _read_lines(p)
                            exist = set(cur_lines)
                            extra = [k for k in add_lines if k not in exist]
                            if extra:
                                _atomic_write(t, cur_lines + extra)
                        except Exception:
                            pass

_maybe_migrate_legacy_dirs()

# ------------------------ أدوات أساسية ------------------------
def _slugify(x: str) -> str:
    x = (x or "").strip()
    x = re.sub(r"[^a-zA-Z0-9_.-]+", "-", x)
    return x or "default"

def _norm_product(p: str | None) -> str:
    s = (p or "").strip().lower()
    mapping = {
        "8bp": "8bp", "8ball": "8bp", "8ballpool": "8bp", "8-ball": "8bp", "8_ball": "8bp",
        "carrom": "carrom", "carrompool": "carrom", "carrom-pool": "carrom",
        "soccer": "soccer", "soccerstars": "soccer", "soccer-stars": "soccer", "football-kick": "soccer",
    }
    return mapping.get(s, s or "8bp")

def _cur_file(product: str, days: int) -> Path:
    product = _slugify(_norm_product(product) or PRODUCT_KEY)
    return DATA_DIR / product / f"{int(days)}d.txt"

def _legacy_file(product: str, days: int) -> Path:
    product = _slugify(_norm_product(product) or PRODUCT_KEY)
    return DATA_DIR / product / f"{int(days)}.txt"   # دعم شكل قديم بدون d

def _used_file(product: str, days: int) -> Path:
    product = _slugify(_norm_product(product) or PRODUCT_KEY)
    return USED_DIR / product / f"{int(days)}d.txt"

def _ensure_file(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("", encoding="utf-8")
    return p

def _read_lines(p: Path) -> List[str]:
    if not p.exists():
        return []
    return [ln.strip() for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]

def _atomic_write(p: Path, lines: Iterable[str]) -> None:
    """كتابة ذرّية + سطر نهائي ثابت."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    text = "\n".join(lines)
    if text:
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)

def _merge_legacy_if_any(product: str, days: int) -> None:
    """ينقل محتوى 3.txt القديم إلى 3d.txt دون تكرار."""
    cur = _ensure_file(_cur_file(product, days))
    legacy = _legacy_file(product, days)
    if not legacy.exists():
        return
    cur_lines = _read_lines(cur)
    legacy_lines = _read_lines(legacy)
    if not legacy_lines:
        return
    existed = set(cur_lines)
    extra = [k for k in legacy_lines if k not in existed]
    if extra:
        _atomic_write(cur, cur_lines + extra)
    # legacy.unlink(missing_ok=True)  # يمكن تفعيل الحذف إن رغبت

# ------------------------ قفل خفيف للملفات ------------------------
@contextmanager
def _file_lock(product: str, days: int):
    """
    قفل بسيط عبر إنشاء مجلّد، آمن نوويًا على مستوى الملفات (نفس السيرفر/الخدمة).
    """
    product = _slugify(_norm_product(product) or PRODUCT_KEY)
    lock_dir = LOCKS_DIR / product
    lock_dir.mkdir(parents=True, exist_ok=True)
    lk = lock_dir / f"{int(days)}d.lock"

    while True:
        try:
            lk.mkdir()
            break
        except FileExistsError:
            import time
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            lk.rmdir()
        except Exception:
            pass

# ------------------------ أدوات تحليل/تنظيف ------------------------
def _parse_keys_from_text(text: str, min_len: int = 4) -> List[str]:
    """
    محلّل: يقبل أسطر/فواصل (، , ; ؛) ويزيل الفراغ والتكرار.
    """
    if not text:
        return []
    parts = re.split(r"[,\n؛;]+", text.replace("\r", ""))
    seen, out = set(), []
    for p in parts:
        k = (p or "").strip()
        if len(k) < min_len:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out

def _dedupe_list(lines: List[str]) -> List[str]:
    seen, out = set(), []
    for k in lines:
        if k and k not in seen:
            seen.add(k); out.append(k)
    return out

# ------------------------ واجهات عامة (إضافة/سحب/عدّ) ------------------------
async def add_keys(product: str, days: int, keys: Iterable[str]) -> Tuple[int, int]:
    """
    تُضيف مفاتيح (سطر لكل مفتاح). ترجع (inserted, duplicates_in_batch).
    تتجاهل الفراغات والمكررات (داخل الملف أو نفس الدفعة).
    """
    product = _norm_product(product or PRODUCT_KEY)
    _merge_legacy_if_any(product, days)
    p = _ensure_file(_cur_file(product, days))

    with _file_lock(product, days):
        existing = set(_read_lines(p))
        cleaned: List[str] = []
        seen_batch = set()
        for raw in keys or []:
            k = (raw or "").strip()
            if not k:
                continue
            if k in seen_batch:
                continue
            seen_batch.add(k)
            if k not in existing:
                cleaned.append(k)

        if cleaned:
            new_lines = _read_lines(p) + cleaned
            _atomic_write(p, new_lines)

    inserted = len(cleaned)
    duplicates = len(seen_batch) - inserted
    return inserted, duplicates

# توافق قديم
async def add_codes(product: str, days: int, keys: Iterable[str]) -> Tuple[int, int]:
    return await add_keys(product, days, keys)

async def add_keys_from_text(product: str, days: int, text: str, min_len: int = 4) -> Tuple[int, int]:
    keys = _parse_keys_from_text(text or "", min_len=min_len)
    return await add_keys(product, days, keys)

async def take(days: int, qty: int, product: str | None = None) -> List[str]:
    """
    يسحب أول qty من المفاتيح (FIFO) ويزيلها من المخزون ويؤرشفها في used/.
    """
    product = _norm_product(product or PRODUCT_KEY)
    _merge_legacy_if_any(product, days)
    p = _ensure_file(_cur_file(product, days))

    with _file_lock(product, days):
        lines = _read_lines(p)
        if qty is None or qty <= 0:
            qty = len(lines)
        picked = lines[:qty]
        remain = lines[qty:]
        _atomic_write(p, remain)

    if picked:
        used = _ensure_file(_used_file(product, days))
        with _file_lock(product, days):
            _atomic_write(used, _read_lines(used) + picked)

    return picked

# توافق مع payments.py
async def pop_codes(days: int, qty: int, product: str | None = None) -> List[str]:
    return await take(days=days, qty=qty, product=product)

async def count_for(days: int, product: str | None = None) -> int:
    product = _norm_product(product or PRODUCT_KEY)
    _merge_legacy_if_any(product, days)
    p = _ensure_file(_cur_file(product, days))
    return len(_read_lines(p))

async def counts(product: str | None = None) -> Dict[int, int]:
    product = _norm_product(product or PRODUCT_KEY)
    return {
        3:  await count_for(3, product),
        10: await count_for(10, product),
        30: await count_for(30, product),
    }

# ------------------------ حذف/إدارة متقدمة ------------------------
async def remove_keys(product: str, days: int, keys: Iterable[str]) -> int:
    """
    يحذف المفاتيح المطابقة تمامًا من مخزون مدة معينة.
    يرجّع عدد ما تم حذفه. (يؤرشف المحذوف في used/).
    """
    product = _norm_product(product or PRODUCT_KEY)
    _merge_legacy_if_any(product, days)
    p = _ensure_file(_cur_file(product, days))
    keys_set = { (k or "").strip() for k in keys or [] if (k or "").strip() }

    if not keys_set:
        return 0

    with _file_lock(product, days):
        lines = _read_lines(p)
        remain = [k for k in lines if k not in keys_set]
        removed = [k for k in lines if k in keys_set]
        if len(remain) != len(lines):
            _atomic_write(p, remain)

    # أرشفة المحذوف
    if removed:
        used = _ensure_file(_used_file(product, days))
        with _file_lock(product, days):
            _atomic_write(used, _read_lines(used) + [f"del:{k}" for k in removed])

    return len(removed)

# ألياسات لتوافق الإدمن
delete_keys = remove_keys
del_keys = remove_keys
rm_keys = remove_keys

async def list_keys(product: str, days: int, limit: Optional[int] = 200) -> List[str]:
    """عرض أول N من مفاتيح المدة لغايات التشخيص."""
    product = _norm_product(product or PRODUCT_KEY)
    _merge_legacy_if_any(product, days)
    p = _ensure_file(_cur_file(product, days))
    lines = _read_lines(p)
    return lines[: int(limit or len(lines))]

async def dedupe(product: str, days: int) -> int:
    """يزيل المكرّر داخل ملف المدة المعطاة. يرجّع عدد السجلات المحذوفة."""
    product = _norm_product(product or PRODUCT_KEY)
    _merge_legacy_if_any(product, days)
    p = _ensure_file(_cur_file(product, days))
    with _file_lock(product, days):
        lines = _read_lines(p)
        unique = _dedupe_list(lines)
        removed = len(lines) - len(unique)
        if removed:
            _atomic_write(p, unique)
    return removed

def migrate_product(old: str, new: str) -> int:
    """
    دمج مخزون منتج قديم في منتج جديد دون تكرار. يرجّع عدد المفاتيح المنقولة.
    """
    old = _slugify(_norm_product(old)); new = _slugify(_norm_product(new))
    src = DATA_DIR / old
    dst = DATA_DIR / new
    if not src.exists():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    moved = 0
    for days in (3, 10, 30):
        _merge_legacy_if_any(old, days)
        s = _cur_file(old, days)
        if not s.exists():
            continue
        d = _cur_file(new, days)
        src_lines = _read_lines(s)
        dst_lines = _read_lines(d) if d.exists() else []
        existing = set(dst_lines)
        extra = [k for k in src_lines if k not in existing]
        _atomic_write(d, dst_lines + extra)
        moved += len(extra)
    return moved

# ------------------------ لمحة وإشعارات ------------------------
async def used_count(product: str | None = None, days: int | None = None) -> int:
    """يحساب عدد العناصر المؤرشفة في used/ (مفيد للإحصاء/التشخيص)."""
    product = _slugify(_norm_product(product or PRODUCT_KEY))
    total = 0
    if days in (3, 10, 30):
        f = _used_file(product, int(days))
        total += len(_read_lines(_ensure_file(f)))
    else:
        for d in (3, 10, 30):
            f = _used_file(product, d)
            total += len(_read_lines(_ensure_file(f)))
    return total

async def snapshot_msg(product: str | None = None) -> str:
    """يعرض لقطة سريعة للمخزون والمستخدمة ومسار البيانات."""
    product = _norm_product(product or PRODUCT_KEY)
    c = await counts(product)
    u = await used_count(product)
    base = str(BASE)
    return (
        f"{product}: 3d={c.get(3,0)} | 10d={c.get(10,0)} | 30d={c.get(30,0)} | used≈{u}\n"
        f"📂 data dir: {base}"
    )

async def maybe_alert_low_stock(bot, days: int, product: str | None = None) -> None:
    """
    ينبه الإدمن عند انخفاض مخزون مدة معيّنة تحت حدّ بيئي:
      MIN_STOCK_3D / MIN_STOCK_10D / MIN_STOCK_30D (الافتراضي 5).
    يرسل إلى ALERTS_CHAT_ID أو أول ADMIN_IDS.
    """
    product = _norm_product(product or PRODUCT_KEY)
    curr = await count_for(days, product)
    env_key = {3: "MIN_STOCK_3D", 10: "MIN_STOCK_10D", 30: "MIN_STOCK_30D"}.get(int(days), "")
    try:
        threshold = int(os.getenv(env_key, "5"))
    except Exception:
        threshold = 5
    if curr > threshold:
        return

    raw_chat = (os.getenv("ALERTS_CHAT_ID", "") or "").strip()
    chat: int | str | None = None
    if raw_chat:
        # إن كان رقميًا (حتى -100..) حوّله لـ int
        if raw_chat.lstrip("-").isdigit():
            try:
                chat = int(raw_chat)
            except Exception:
                chat = raw_chat
        else:
            chat = raw_chat
    else:
        admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
        for part in str(admin_env).split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                chat = int(part)
                break
    if chat is None:
        return

    try:
        await bot.send_message(
            chat_id=chat,
            text=f"⚠️ انخفاض مخزون {product} ({days}d): المتاح {curr} (الحد {threshold})."
        )
    except Exception:
        pass
