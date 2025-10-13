from __future__ import annotations

# services/keys.py

import os, json, time, threading, shutil, io
from typing import Any, Iterable, List, Dict, Tuple
from pathlib import Path

# ✅ مجلد البيانات الموحّد (يحترم .env -> DATA_DIR) ويجب أن يكون على Volume
from utils.paths import BASE

# ملفات التخزين (JSON) داخل BASE
ORDERS_PATH = (BASE / "orders.json")
INV_PATH    = (BASE / "inventory.json")
USERS_PATH  = (BASE / "users.json")

# مجلد نسخ احتياطية
BACKUPS_DIR = (BASE / "backups")
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
MAX_BACKUPS_PER_FILE = int(os.getenv("JSON_BACKUPS_KEEP", "7") or "7")

# قفل خيطي + قفل ملف عبر العمليات
_LOCK = threading.RLock()
_FILELOCK_PATH = (BASE / ".keys.lock")

def _file_lock_acquire():
    _FILELOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    # نستخدم قفل بسيط متوافق (Windows/Unix)
    try:
        import msvcrt  # type: ignore
        fh = open(_FILELOCK_PATH, "a+b")
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        return ("win", fh)
    except Exception:
        try:
            import fcntl  # type: ignore
            fh = open(_FILELOCK_PATH, "a+b")
            fcntl.flock(fh, fcntl.LOCK_EX)
            return ("unix", fh)
        except Exception:
            # آخر حل: لا شيء (يبقى قفل الخيط)
            return (None, None)

def _file_lock_release(tok):
    kind, fh = tok
    if not fh:
        return
    try:
        if kind == "win":
            import msvcrt  # type: ignore
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        elif kind == "unix":
            import fcntl  # type: ignore
            fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass

# حد تنبيه انخفاض المخزون
LOW_STOCK_THRESHOLD = int(os.getenv("STOCK_THRESHOLD", "10") or "10")

# ===== ترحيل تلقائي من المسارات القديمة إلى BASE (مرة واحدة) =====
def _maybe_migrate_legacy() -> None:
    """
    لو عندك ملفات قديمة داخل مجلد المشروع المحلي data/ (وليس BASE)،
    ننقلها إلى BASE مع دمج آمن إن وُجدت ملفات هناك بالفعل.
    """
    legacy_dir = Path(__file__).resolve().parents[1] / "data"
    if not legacy_dir.exists() or legacy_dir.resolve() == BASE.resolve():
        return

    def _merge_json(src: Path, dst: Path, root_key: str | None = None) -> None:
        try:
            if not src.exists():
                return
            src_obj = json.loads(src.read_text(encoding="utf-8") or "{}") or {}
        except Exception:
            src_obj = {}

        try:
            if dst.exists():
                dst_obj = json.loads(dst.read_text(encoding="utf-8") or "{}") or {}
            else:
                dst_obj = {}
        except Exception:
            dst_obj = {}

        # دمج بسيط
        if root_key:
            s = src_obj.get(root_key)
            d = dst_obj.get(root_key)
            if isinstance(s, list) and isinstance(d, list):
                seen = {json.dumps(x, ensure_ascii=False, sort_keys=True) for x in d}
                extra = [x for x in s if json.dumps(x, ensure_ascii=False, sort_keys=True) not in seen]
                dst_obj[root_key] = d + extra
            elif isinstance(s, dict) and isinstance(d, dict):
                merged = dict(s); merged.update(d)
                dst_obj[root_key] = merged
            elif d is None and s is not None:
                dst_obj[root_key] = s
        else:
            merged = dict(src_obj); merged.update(dst_obj)
            dst_obj = merged

        tmp = dst.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(dst_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, dst)

    _merge_json(legacy_dir / "orders.json",    ORDERS_PATH, root_key="orders")
    _merge_json(legacy_dir / "inventory.json", INV_PATH,    root_key="inv")
    _merge_json(legacy_dir / "users.json",     USERS_PATH,  root_key="users")

def _ensure_files() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    if not ORDERS_PATH.exists():
        ORDERS_PATH.write_text(json.dumps({"orders": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not INV_PATH.exists():
        INV_PATH.write_text(json.dumps({"inv": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not USERS_PATH.exists():
        USERS_PATH.write_text(json.dumps({"users": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

def _snapshot(path: Path):
    """يحفظ نسخة احتياطية قبل الكتابة، ويُدوِّر النسخ القديمة."""
    try:
        if not path.exists():
            return
        ts = time.strftime("%Y%m%d-%H%M%S")
        base = path.stem  # inventory
        ext = path.suffix # .json
        bname = f"{base}.{ts}{ext}"
        dst = BACKUPS_DIR / bname
        shutil.copy2(path, dst)
        # تدوير
        fam = sorted([p for p in BACKUPS_DIR.glob(f"{base}.*{ext}")])
        if len(fam) > MAX_BACKUPS_PER_FILE:
            for p in fam[:-MAX_BACKUPS_PER_FILE]:
                try: p.unlink()
                except Exception: pass
    except Exception:
        # لا تُفشل السريان بسبب النسخ الاحتياطي
        pass

def _load_json(path: Path, default: Any):
    _ensure_files()
    tok = _file_lock_acquire()
    with _LOCK:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
        finally:
            _file_lock_release(tok)

def _save_json(path: Path, data: Any) -> None:
    tok = _file_lock_acquire()
    with _LOCK:
        try:
            _snapshot(path)  # نسخ احتياطي قبل الكتابة
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            _file_lock_release(tok)

# شغّل الترحيل لمرة واحدة عند الاستيراد
_maybe_migrate_legacy()
_ensure_files()

# --------- تطبيع أسماء المنتجات حتى تتوافق مع بقية الخدمات ---------
def _norm_product(p: str | int | None) -> str:
    s = str(p or "").strip().lower()
    mapping = {
        "8bp": "8bp", "8ball": "8bp", "8ballpool": "8bp", "8-ball": "8bp", "8_ball": "8bp",
        "carrom": "carrom", "carrompool": "carrom", "carrom-pool": "carrom",
        "soccer": "soccer", "soccerstars": "soccer", "soccer-stars": "soccer", "football-kick": "soccer",
    }
    return mapping.get(s, s or "8bp")

def _key(game: str, days: str | int) -> str:
    return f"{str(game).strip()}:{str(days).strip()}"

def _normalize_keys(keys: Iterable[str]) -> list[str]:
    out, seen = [], set()
    for s in keys or []:
        s = (s or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out

# =============== INVENTORY API (JSON backend) ===============
def add_keys(game: str, days: str | int, keys: list[str]) -> tuple[int, int]:
    """
    تُضيف مفاتيح (مع إزالة الفراغات والتكرارات).
    ترجع (inserted, duplicates_in_batch).
    """
    db = _load_json(INV_PATH, {"inv": {}})
    k = _key(game, days)
    lst: list[str] = list(db.get("inv", {}).get(k, []))

    clean_batch = _normalize_keys(keys)
    existing = set(lst)
    inserted = [s for s in clean_batch if s not in existing]
    duplicates = len(clean_batch) - len(inserted)

    if inserted:
        db.setdefault("inv", {})
        db["inv"][k] = lst + inserted
        _save_json(INV_PATH, db)

    return len(inserted), duplicates

def inv_count(game: str, days: str | int) -> int:
    db = _load_json(INV_PATH, {"inv": {}})
    return len(db.get("inv", {}).get(_key(game, days), []))

def pop_keys(game: str, days: str | int, qty: int) -> list[str]:
    """
    يسحب مفاتيح (FIFO). يرمي RuntimeError إن لم يكن المخزون كافيًا.
    """
    if qty is None or qty <= 0:
        raise RuntimeError("qty must be > 0")

    db = _load_json(INV_PATH, {"inv": {}})
    k = _key(game, days)
    lst: list[str] = list(db.get("inv", {}).get(k, []))

    if len(lst) < qty:
        raise RuntimeError("Not enough keys in stock")

    out = lst[:qty]
    db["inv"][k] = lst[qty:]
    _save_json(INV_PATH, db)
    return out

# --------- واجهة متوافقة مع services/payments.py (inventory.*) ---------
def pop_codes(days: int, qty: int, product: str) -> list[str]:
    """
    توقيع متوافق مع calls في payments.py
    """
    product = _norm_product(product)
    return pop_keys(product, days, qty)

async def maybe_alert_low_stock(bot, days: int, product: str):
    """
    يُنبه عند انخفاض المخزون (اختياري).
    - يحاول استخدام services.notify.notify_role(role="inventory") إن توفّر.
    - لو غير متوفر، لا يرفع استثناء (فقط يتجاهل).
    """
    try:
        stock = inv_count(_norm_product(product), days)
        if stock > LOW_STOCK_THRESHOLD:
            return
        try:
            # محاولة استخدام نظام الإشعارات الموحد
            from services.notify import notify_role  # type: ignore
            text_ar = f"⚠️ مخزون منخفض — {product} / {days} يوم: {stock} مفتاح متبقٍ"
            text_en = f"⚠️ Low stock — {product} / {days}d: {stock} key(s) left"
            await notify_role(bot, role="inventory", text=f"{text_ar}\n{text_en}")
        except Exception:
            # fallback: أرسل لنفسك/لوج فقط
            import logging
            logging.getLogger(__name__).warning(
                "Low stock: product=%s days=%s stock=%s (no notify_role)", product, days, stock
            )
    except Exception:
        pass

# أدوات إضافية للإدارة/التقارير (اختيارية)
def stock_overview() -> Dict[str, int]:
    """
    يعيد قاموسًا مثل {"8bp:3": 12, "8bp:10": 0, "carrom:30": 7, ...}
    """
    db = _load_json(INV_PATH, {"inv": {}})
    inv = db.get("inv", {}) or {}
    return {str(k): int(len(v or [])) for k, v in inv.items()}

def set_threshold(v: int) -> None:
    """
    يضبط حد التنبيه (لازم تستدعيها قبل التشغيل عادةً — هي تغير قيمة الجلوبال فقط).
    """
    global LOW_STOCK_THRESHOLD
    LOW_STOCK_THRESHOLD = max(0, int(v or 0))

# =============== ORDERS (JSON mini-ledger) ===============
def save_order(order: dict) -> None:
    db = _load_json(ORDERS_PATH, {"orders": []})
    db["orders"].append(order)
    _save_json(ORDERS_PATH, db)

def get_order(oid: str) -> dict | None:
    db = _load_json(ORDERS_PATH, {"orders": []})
    for o in db["orders"]:
        if o.get("id") == oid:
            return o
    return None

def update_order(oid: str, fields: dict) -> None:
    db = _load_json(ORDERS_PATH, {"orders": []})
    for o in db["orders"]:
        if o.get("id") == oid:
            o.update(fields)
            break
    _save_json(ORDERS_PATH, db)

def user_orders(uid: int) -> list[dict]:
    db = _load_json(ORDERS_PATH, {"orders": []})
    return [o for o in db["orders"] if o.get("buyer_id") == uid]

# =============== USERS profiles ===============
def add_user_key(uid: int, game: str, days: str | int, keys: list[str], order_id: str) -> None:
    db = _load_json(USERS_PATH, {"users": {}})
    u = db["users"].get(str(uid), {"keys": []})
    u["keys"].append({
        "order_id": order_id,
        "game": str(game), "days": str(days), "qty": len(keys),
        "keys": list(keys),
        "ts": int(time.time())
    })
    db["users"][str(uid)] = u
    _save_json(USERS_PATH, db)

def get_user_profile(uid: int) -> dict:
    db = _load_json(USERS_PATH, {"users": {}})
    return db["users"].get(str(uid), {"keys": []})

# =============== منطق مساعد ===============
def maybe_low_stock(game: str, days: str | int) -> bool:
    return inv_count(game, days) <= LOW_STOCK_THRESHOLD
