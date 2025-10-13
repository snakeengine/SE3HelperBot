# admin/shop_admin.py
from __future__ import annotations

import os
import io
import re
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple, Any, Callable, Optional

import aiosqlite
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, Document
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types.input_file import BufferedInputFile

# =========================
# Fallbacks للبيئة/المسارات
# =========================
# BASE
try:
    from utils.paths import BASE  # مشروعك
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "data")).resolve()

# constants
try:
    from constants import PRICE_USD_3, PRICE_USD_10, PRICE_USD_30
except Exception:
    PRICE_USD_3, PRICE_USD_10, PRICE_USD_30 = 5.0, 12.0, 25.0

# NotCommand (لو مفقود)
try:
    from utils.filters_common import NotCommand
except Exception:
    from aiogram.filters import BaseFilter
    class NotCommand(BaseFilter):  # type: ignore
        async def __call__(self, message: Message) -> bool:
            txt = (message.text or "").strip()
            return not (txt.startswith("/") and len(txt) > 1)

# خدمات المشروع
from services import orders as ords
from services import inventory as inv

# check_and_deliver_one (فولباك لو غاب)
try:
    from services.payments import check_and_deliver_one
except Exception:
    async def check_and_deliver_one(bot, oid: int, notify_user: bool = False):
        # فولباك آمن لا يسلّم شيء فعليًا
        return False, "Delivery function not available."

# ---- طرق الدفع لكل منتج (نجوم/كريبتو) ----
try:
    from services.payments import (
        get_pay_modes as _p_get_pay_modes,
        set_pay_mode_enabled as _p_set_pay_mode_enabled,
        is_stars_enabled_for as _p_is_stars_ok,
        is_crypto_enabled_for as _p_is_crypto_ok,
    )
    def get_pay_modes(prod: str) -> dict: return _p_get_pay_modes(prod)
    def set_pay_mode_enabled(prod: str, mode: str, enabled: bool): return _p_set_pay_mode_enabled(prod, mode, enabled)
    def is_stars_ok(prod: str) -> bool: return _p_is_stars_ok(prod)
    def is_crypto_ok(prod: str) -> bool: return _p_is_crypto_ok(prod)
except Exception:
    # تخزين بالحقل "pay_modes" في FLAGS_PATH كنسخة احتياطية
    def _pm_load() -> dict:
        return (_jload(FLAGS_PATH).get("pay_modes") or {})
    def _pm_save(mp: dict):
        d = _jload(FLAGS_PATH); d["pay_modes"] = mp; _jsave(FLAGS_PATH, d)
    def get_pay_modes(prod: str) -> dict:
        mp = _pm_load()
        base = {"stars": True, "crypto": True}
        base.update(mp.get("default") or {})
        base.update(mp.get((prod or "default").lower()) or {})
        return {k: bool(v) for k, v in base.items() if k in ("stars","crypto")}
    def set_pay_mode_enabled(prod: str, mode: str, enabled: bool):
        if mode not in ("stars","crypto"): return
        mp = _pm_load(); p = (prod or "default").lower()
        node = dict(mp.get(p) or {})
        node[mode] = bool(enabled)
        mp[p] = node; _pm_save(mp)
    def is_stars_ok(prod: str) -> bool:
        return bool(get_pay_modes(prod).get("stars", True))
    def is_crypto_ok(prod: str) -> bool:
        return bool(get_pay_modes(prod).get("crypto", True))

# =========================
# تكوين عام
# =========================
DEFAULT_PRODUCT = (os.getenv("PRODUCT_KEY", "8bp") or "8bp").lower().strip()
PRODUCTS = [p.strip().lower() for p in (os.getenv("SHOP_PRODUCTS", "8bp,carrom,soccer").split(","))]
PRODUCTS = [p for p in PRODUCTS if p] or ["8bp", "carrom", "soccer"]
if DEFAULT_PRODUCT not in PRODUCTS:
    PRODUCTS.insert(0, DEFAULT_PRODUCT)

# توحيد مسار DB مع services.orders إن وُجد
try:
    from services.orders import DB_PATH as _ORDERS_DB_PATH  # type: ignore
    DB_PATH = str(_ORDERS_DB_PATH)
except Exception:
    DB_PATH = os.getenv("SHOP_DB", str(BASE / "shop.db"))

# دفع
_CRYPTO_ASSETS_ENV = os.getenv("CRYPTO_ASSETS", os.getenv("CRYPTO_ASSET", "USDT")) or "USDT"
CRYPTO_ASSETS = list(dict.fromkeys([s.strip().upper() for s in _CRYPTO_ASSETS_ENV.split(",") if s.strip()])) or ["USDT"]
CRYPTOPAY_ON = bool(os.getenv("CRYPTOPAY_TOKEN"))
TON_WALLET = os.getenv("TON_WALLET", "") or "—"
INVOICE_TTL_MIN = int(os.getenv("INVOICE_TTL_MIN", "15"))

# ملفات حالة/أسعار
FLAGS_PATH          = BASE / "shop_flags.json"
INV_BL_PATH         = BASE / "inv_blacklist.json"
PRICES_PATH         = BASE / "shop_prices.json"   # أسعار USD (متعددة المنتجات)
STARS_PRICES_PATH   = BASE / "shop_stars.json"    # أسعار النجوم

# إدمن
ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "0")).split(",") if x.strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

router = Router(name="shop_admin")

# جلسات مؤقتة
_INV_SESS: Dict[int, Dict[str, Any]]  = {}
_PRICE_SESS: Dict[int, Tuple[str,int]] = {}   # (prod, days)
_STAR_SESS:  Dict[int, Tuple[str,int]] = {}   # (prod, days)
_CUR_PROD: Dict[int, str] = {}

INV_MIN_LEN = int(os.getenv("INV_MIN_LEN", "4"))

from aiogram.filters import BaseFilter

class AdminTextSession(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        uid = (message.from_user and message.from_user.id) or 0
        if uid not in ADMIN_IDS:
            return False
        # يُسمح بالنص فقط إذا عند الأدمن جلسة أسعار/نجوم/مخزون
        return (uid in _PRICE_SESS) or (uid in _STAR_SESS) or (_INV_SESS.get(uid) is not None)

class AdminDocSession(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        uid = (message.from_user and message.from_user.id) or 0
        if uid not in ADMIN_IDS:
            return False
        sess = _INV_SESS.get(uid)
        # الملفات فقط أثناء جلسات المخزون (add/del_one/del_bulk)
        return bool(sess and sess.get("mode") in {"add", "del_one", "del_bulk"})

# =========================
# أدوات مساعدة
# =========================
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _money(x: float, d: int = 2) -> str:
    try:
        return f"{float(x):.{d}f}"
    except Exception:
        return f"{x}"

def _cur_prod(uid: int) -> str:
    return (_CUR_PROD.get(uid) or DEFAULT_PRODUCT).lower().strip()

def _jload(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _jsave(p: Path, d: dict):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass

async def _call_maybe_async(fn: Callable, *a, **kw):
    if asyncio.iscoroutinefunction(fn):
        return await fn(*a, **kw)
    res = fn(*a, **kw)
    if asyncio.isfuture(res) or asyncio.iscoroutine(res):
        return await res
    return res

async def _edit_or_answer(cb: CallbackQuery, text: str, reply_markup=None):
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await cb.message.answer(text, reply_markup=reply_markup)

def _extract_loose(text: str, min_len: int = INV_MIN_LEN) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[,\n;]+", text.replace("\r", ""))
    seen, out = set(), []
    for p in parts:
        k = (p or "").strip()
        if len(k) >= min_len and k not in seen:
            seen.add(k)
            out.append(k)
    return out

async def _read_document_text(doc: Document, bot) -> Optional[str]:
    try:
        buf = io.BytesIO()
        await bot.download(doc, buf)
        return buf.getvalue().decode("utf-8", "ignore")
    except Exception:
        pass
    try:
        file = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        try:
            await bot.download_file(file.file_path, buf)
        except Exception:
            await bot.download(file, buf)
        return buf.getvalue().decode("utf-8", "ignore")
    except Exception:
        return None

# =========================
# تمكين/تعطيل خدمة المفاتيح
# =========================
try:
    from services.payments import (
        is_keys_service_enabled as _p_is_enabled,
        set_keys_service_enabled as _p_set_enabled,
        get_keys_stop_message as _p_get_stop_msg,
        set_keys_stop_message as _p_set_stop_msg,
    )
    def keys_service_enabled() -> bool: return bool(_p_is_enabled())
    def set_keys_service_enabled(v: bool): return _p_set_enabled(bool(v))
    def get_keys_stop_message() -> str: return _p_get_stop_msg() or ""
    def set_keys_stop_message(msg: str): return _p_set_stop_msg(msg or "")
except Exception:
    def keys_service_enabled() -> bool:
        d = _jload(FLAGS_PATH)
        return not bool(d.get("keys_disabled", False))
    def set_keys_service_enabled(v: bool):
        d = _jload(FLAGS_PATH)
        d["keys_disabled"] = (not bool(v))
        _jsave(FLAGS_PATH, d)
    def get_keys_stop_message() -> str:
        d = _jload(FLAGS_PATH)
        return str(d.get("keys_stop_message", "") or "")
    def set_keys_stop_message(msg: str):
        d = _jload(FLAGS_PATH)
        d["keys_stop_message"] = str(msg or "")
        _jsave(FLAGS_PATH, d)


# =========================
# أسعار USD
# =========================
DEFAULT_PRICES = {
    3:  float(os.getenv("PRICE_USD_3", PRICE_USD_3)),
    10: float(os.getenv("PRICE_USD_10", PRICE_USD_10)),
    30: float(os.getenv("PRICE_USD_30", PRICE_USD_30)),
}

def _load_prices_map() -> Dict[str, Dict[int, float]]:
    raw = _jload(PRICES_PATH)
    out: Dict[str, Dict[int, float]] = {}

    def _to_days_map(dct) -> Dict[int, float]:
        m: Dict[int, float] = {}
        for k, v in (dct or {}).items():
            try:
                kk = int(k)
                if kk in (3, 10, 30):
                    m[kk] = float(v)
            except Exception:
                continue
        return m

    if not raw:
        out["default"] = dict(DEFAULT_PRICES)
        return out

    if any(k in raw for k in ("3", "10", "30")):
        out["default"] = _to_days_map(raw)
        return out

    for prod, dct in raw.items():
        out[str(prod).lower()] = _to_days_map(dct)

    if "default" not in out or not out["default"]:
        out["default"] = dict(DEFAULT_PRICES)
    return out

def _save_prices_map(mp: Dict[str, Dict[int, float]]):
    serial: Dict[str, Dict[str, float]] = {}
    for prod, dmap in mp.items():
        serial[str(prod).lower()] = {str(k): float(v) for k, v in dmap.items() if k in (3, 10, 30)}
    _jsave(PRICES_PATH, serial)

def _prices_usd(product: str) -> Dict[int, float]:
    mp = _load_prices_map()
    base = dict(DEFAULT_PRICES)
    if "default" in mp:
        base.update(mp["default"])
    prod = (product or "default").lower().strip()
    if prod in mp:
        base.update(mp[prod])
    return base

# =========================
# أسعار النجوم ⭐
# =========================
def _stars_per_usd_from_env() -> float:
    raw = (os.getenv("STARS_PER_USD") or os.getenv("USD_PER_STAR") or "50").strip()
    try:
        val = float(raw)
    except Exception:
        val = 50.0
    if 0 < val < 1:
        return 1.0 / val
    return max(val, 1.0)

STARS_PER_USD: float = _stars_per_usd_from_env()

def _load_stars_map() -> Dict[str, Dict[int, int]]:
    raw = _jload(STARS_PRICES_PATH)
    out: Dict[str, Dict[int, int]] = {}

    def _to_days_map(dct) -> Dict[int, int]:
        m: Dict[int, int] = {}
        for k, v in (dct or {}).items():
            try:
                kk = int(k)
                if kk in (3, 10, 30):
                    m[kk] = int(v)
            except Exception:
                continue
        return m

    if not raw:
        return {}

    if any(k in raw for k in ("3", "10", "30")):
        out["default"] = _to_days_map(raw)
        return out

    for prod, dct in raw.items():
        out[str(prod).lower()] = _to_days_map(dct)
    return out

def _save_stars_map(mp: Dict[str, Dict[int, int]]):
    serial: Dict[str, Dict[str, int]] = {}
    for prod, dmap in mp.items():
        serial[str(prod).lower()] = {str(k): int(v) for k, v in dmap.items() if k in (3, 10, 30)}
    _jsave(STARS_PRICES_PATH, serial)

def _prices_stars_effective(product: str) -> Dict[int, int]:
    product = (product or "default").lower().strip()
    usd = _prices_usd(product)
    res: Dict[int, int] = {d: max(1, int(round(usd[d] * STARS_PER_USD))) for d in (3, 10, 30)}
    mp = _load_stars_map()
    if "default" in mp:
        for d, v in mp["default"].items():
            if d in res:
                res[d] = int(v)
    if product in mp:
        for d, v in mp[product].items():
            if d in res:
                res[d] = int(v)
    return res

# =========================
# Blacklist فولباك
# =========================
def _bl_load() -> dict:
    try:
        if INV_BL_PATH.exists():
            return json.loads(INV_BL_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _bl_save(d: dict):
    try:
        INV_BL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = INV_BL_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, INV_BL_PATH)
    except Exception:
        pass

def _blacklist_add(keys: List[str]) -> int:
    d = _bl_load()
    m = d.get("keys") or {}
    n = 0
    for k in keys:
        k2 = str(k).strip()
        if not k2:
            continue
        if k2 not in m:
            m[k2] = True
            n += 1
    d["keys"] = m
    _bl_save(d)
    return n

# =========================
# SQL صغيرة
# =========================
async def _sales_sum(where: str = "", args: Tuple = ()) -> Tuple[float, float, int]:
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
        return float(row[0] or 0), float(row[1] or 0), int(row[2] or 0)

async def _export_csv(days: int = 30) -> bytes:
    await ords.ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id,user_id,username,slug,days,qty,usd_amount,ton_amount,asset,to_address,status,created_at,expires_at,invoice_hash
            FROM orders
            WHERE datetime(created_at) >= datetime('now', ?)
            ORDER BY id DESC
            """,
            (f"-{days} days",),
        )
        rows = await cur.fetchall()
    headers = [
        "id","user_id","username","slug","days","qty","usd_amount","ton_amount",
        "asset","to_address","status","created_at","expires_at","invoice_hash"
    ]
    out = io.StringIO()
    out.write(",".join(headers) + "\n")
    for r in rows:
        vals = [str(x).replace(",", " ") if x is not None else "" for x in r]
        out.write(",".join(vals) + "\n")
    return out.getvalue().encode("utf-8")

# =========================
# واجهة رئيسية
# =========================
def _home_kb(uid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🧩 المنتج: {_cur_prod(uid)}", callback_data="sad:prod")
    kb.button(text="📦 المخزون", callback_data="sad:inv")
    kb.button(text="🧾 الطلبات", callback_data="sad:orders")
    kb.button(text="📊 الإحصائيات", callback_data="sad:stats")
    kb.button(text="💰 الأسعار (USD)", callback_data="sad:prices")
    kb.button(text="⭐ أسعار النجوم", callback_data="sad:stars")
    kb.button(text="💳 طرق الدفع", callback_data="sad:pay")
    kb.button(text="⛔️ حالة المنتج", callback_data="sad:pstate")   # ← جديد
    kb.button(text="⚙️ الإعدادات", callback_data="sad:settings")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()

def _pstate_root_kb():
    kb = InlineKeyboardBuilder()
    for p in ["default"] + PRODUCTS:
        kb.button(text=p, callback_data=f"sad:pstate:which:{p}")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(3, 1)
    return kb.as_markup()

def _pstate_edit_kb(prod: str, enabled: bool):
    kb = InlineKeyboardBuilder()
    label = "✅ البيع مفعّل" if enabled else "⛔️ البيع متوقف"
    kb.button(text=label, callback_data=f"sad:pstate:toggle:{prod}")
    kb.button(text="◀️ رجوع", callback_data="sad:pstate")
    kb.adjust(1, 1)
    return kb.as_markup()

@router.callback_query(F.data == "sad:pstate")
async def pstate_root(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    await _edit_or_answer(cb, "اختر المنتج لإيقاف/تشغيل البيع بالكامل:", reply_markup=_pstate_root_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("sad:pstate:which:"))
async def pstate_which(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = cb.data.split(":")[-1].lower()
    en = is_product_enabled(prod)
    txt = (
        f"⛔️ حالة البيع ({prod}): {'مفعّل' if en else 'متوقف'}\n"
        "اضغط الزر لتبديل الحالة."
    )
    await _edit_or_answer(cb, txt, reply_markup=_pstate_edit_kb(prod, en))
    await cb.answer()

@router.callback_query(F.data.startswith("sad:pstate:toggle:"))
async def pstate_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = cb.data.split(":")[-1].lower()
    en = is_product_enabled(prod)
    set_product_enabled(prod, not en)
    en2 = is_product_enabled(prod)
    await _edit_or_answer(
        cb,
        f"تم التحديث. حالة البيع ({prod}): {'مفعّل' if en2 else 'متوقف'}",
        reply_markup=_pstate_edit_kb(prod, en2)
    )
    await cb.answer("تم التحديث.")

def _back_home_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(1)
    return kb.as_markup()

@router.message(Command("shopadm"))
async def open_admin(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.answer("Admins only.")
    _CUR_PROD[msg.from_user.id] = _cur_prod(msg.from_user.id)
    await msg.answer("👑 لوحة تحكّم المتجر", reply_markup=_home_kb(msg.from_user.id))

@router.callback_query(F.data == "sad:home")
async def cb_home(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    await _edit_or_answer(cb, "👑 لوحة تحكّم المتجر", reply_markup=_home_kb(cb.from_user.id))
    await cb.answer()

# =========================
# اختيار المنتج
# =========================
def _prod_select_kb():
    kb = InlineKeyboardBuilder()
    for p in ["default"] + PRODUCTS:
        kb.button(text=p, callback_data=f"sad:prod:set:{p}")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(3, 1)
    return kb.as_markup()

@router.callback_query(F.data == "sad:prod")
async def prod_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    txt = "اختر المنتج الذي تريد إدارة مخزونه وضبط أسعاره."
    await _edit_or_answer(cb, txt, reply_markup=_prod_select_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("sad:prod:set:"))
async def prod_set(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = cb.data.split(":")[-1]
    _CUR_PROD[cb.from_user.id] = DEFAULT_PRODUCT if prod == "default" else prod
    await cb.answer(f"تم اختيار المنتج: {prod}")
    await cb_home(cb)

# =========================
# المخزون (إضافة/حذف) — مرونة تواقيع
# =========================
def _inv_main_kb(uid: int):
    prod = _cur_prod(uid)
    service_on = keys_service_enabled()
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🧩 المنتج: {prod}", callback_data="sad:prod")
    kb.button(text="➕ إضافة 3d",  callback_data="sad:inv:add:3")
    kb.button(text="➕ إضافة 10d", callback_data="sad:inv:add:10")
    kb.button(text="➕ إضافة 30d", callback_data="sad:inv:add:30")
    kb.button(text="🗑 حذف (مفرد)", callback_data="sad:inv:del_one")
    kb.button(text="🗑🗑 حذف (جملة)", callback_data="sad:inv:del_bulk")
    kb.button(text=("⛔️ إيقاف الخدمة" if service_on else "✅ تشغيل الخدمة"), callback_data="sad:inv:toggle")
    kb.button(text="📝 رسالة الإيقاف", callback_data="sad:inv:stopmsg")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(2, 3, 2, 1)
    return kb.as_markup()

@router.callback_query(F.data == "sad:inv")
async def inv_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = _cur_prod(cb.from_user.id)
    try:
        snap = await _call_maybe_async(getattr(inv, "snapshot_msg"), prod) if hasattr(inv, "snapshot_msg") else "—"
    except Exception:
        snap = "—"
    status = "🟢 مفعّلة" if keys_service_enabled() else "🔴 متوقفة"
    stop_msg = (get_keys_stop_message() or "").strip()
    stop_line = f"\n📝 رسالة الإيقاف:\n{stop_msg}" if stop_msg else ""
    text = (
        f"📦 المخزون ({prod}) — حالة الخدمة: {status}\n"
        f"{snap}\n{stop_line}\n\n"
        "اختر الإجراء من الأزرار بالأسفل. يمكنك أيضًا إرسال ملفات .txt داخل جلسة الإضافة."
    )
    await _edit_or_answer(cb, text, reply_markup=_inv_main_kb(cb.from_user.id))
    await cb.answer()

@router.callback_query(F.data.startswith("sad:inv:add:"))
async def inv_add_start(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    days = int(cb.data.split(":")[-1])
    prod = _cur_prod(cb.from_user.id)
    _INV_SESS[cb.from_user.id] = {"mode": "add", "product": prod, "days": days, "buf_text": ""}
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ حفظ", callback_data="sad:inv:save")
    kb.button(text="✖️ إلغاء", callback_data="sad:inv:cancel")
    kb.adjust(2)
    txt = (
        f"✍️ أرسل الأكواد (سطر لكل مفتاح أو مفصولة بفواصل/؛)، ويمكنك أيضًا إرسال ملف .txt.\n"
        f"المنتج: {prod} • المدة: {days}d\n"
        f"ثم اضغط «حفظ» أو أرسل /done."
    )
    await _edit_or_answer(cb, txt, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "sad:inv:del_one")
async def inv_del_one_start(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = _cur_prod(cb.from_user.id)
    _INV_SESS[cb.from_user.id] = {"mode": "del_one", "product": prod, "buf_text": ""}
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 احذف الآن", callback_data="sad:inv:save")
    kb.button(text="✖️ إلغاء", callback_data="sad:inv:cancel")
    kb.adjust(2)
    txt = f"✍️ أرسل المفتاح المطلوب حذفه (أسطر/فواصل/ملف .txt).\nسيتم البحث في جميع المدد 3d/10d/30d ضمن المنتج: {prod}."
    await _edit_or_answer(cb, txt, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "sad:inv:del_bulk")
async def inv_del_bulk_start(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = _cur_prod(cb.from_user.id)
    _INV_SESS[cb.from_user.id] = {"mode": "del_bulk", "product": prod, "buf_text": ""}
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑🗑 احذف الآن", callback_data="sad:inv:save")
    kb.button(text="✖️ إلغاء", callback_data="sad:inv:cancel")
    kb.adjust(2)
    txt = f"✍️ أرسل قائمة المفاتيح المراد حذفها (أسطر/فواصل/ملف .txt).\nسيتم الحذف عبر جميع المدد ضمن المنتج: {prod}."
    await _edit_or_answer(cb, txt, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "sad:inv:cancel")
async def inv_cancel(cb: CallbackQuery):
    _INV_SESS.pop(cb.from_user.id, None)
    await inv_page(cb)

# إنهاء الجلسة من رسالة
@router.message(Command("done"))
async def inv_done_cmd(msg: Message):
    if msg.from_user.id in _INV_SESS:
        await _inv_save_from_message(msg)

@router.message(Command("cancel"))
async def inv_cancel_cmd(msg: Message):
    if msg.from_user.id in _INV_SESS:
        _INV_SESS.pop(msg.from_user.id, None)
        await msg.answer("تم إلغاء الجلسة.")

# ---- helpers مرنة للتواقيع ----
async def _inv_add_any(product: str, days: int, text_blob: str) -> Tuple[int, int]:
    # 1) نص مباشر
    fn = getattr(inv, "add_keys_from_text", None)
    if callable(fn):
        try:
            return await _call_maybe_async(fn, product, days, text_blob)
        except TypeError:
            pass

    keys = _extract_loose(text_blob)

    # 2) add_keys(product, days, keys) / أشكال أخرى
    fn = getattr(inv, "add_keys", None)
    if callable(fn):
        try:
            return await _call_maybe_async(fn, product, days, keys)
        except TypeError:
            try:
                return await _call_maybe_async(fn, days, product, keys)
            except TypeError:
                return await _call_maybe_async(fn, days, keys)
    return 0, 0

async def _inv_del_any(product: str, keys: List[str]) -> Dict[int, int]:
    res = {3: 0, 10: 0, 30: 0}
    cand_names = ("remove_keys", "delete_keys", "del_keys", "rm_keys")
    for name in cand_names:
        fn = getattr(inv, name, None)
        if not callable(fn):
            continue
        for d in (3, 10, 30):
            try:
                try:
                    n = await _call_maybe_async(fn, product, d, keys)
                except TypeError:
                    try:
                        n = await _call_maybe_async(fn, d, product, keys)
                    except TypeError:
                        n = await _call_maybe_async(fn, d, keys)
                res[d] = int(n or 0)
            except Exception:
                res[d] = res.get(d, 0)
        return res
    _blacklist_add(keys)
    return res

async def _inv_save_from_message(msg: Message):
    uid = msg.from_user.id
    sess = _INV_SESS.get(uid)
    if not sess:
        return await msg.answer("لا توجد جلسة حالية.")

    mode    = sess.get("mode")
    product = sess.get("product", _cur_prod(uid))

    if mode == "add":
        days = int(sess.get("days") or 0) or 3
        text_blob = (sess.get("buf_text", "") or "").strip()
        if not text_blob:
            return await msg.answer("لا يوجد مفاتيح مُجمّعة في هذه الجلسة. أرسل المفاتيح ثم اضغط «حفظ».")
        inserted, duplicates = await _inv_add_any(product, days, text_blob)
        _INV_SESS.pop(uid, None)
        return await msg.answer(
            "🎉 تم الحفظ.\n"
            f"• المنتج: {product}\n"
            f"• المدة: {days}d\n"
            f"• أضيف: {inserted}\n"
            f"• مُهمل/مكرر: {duplicates}"
        )

    if mode in ("del_one", "del_bulk"):
        keys = _extract_loose(sess.get("buf_text", "") or "")
        if not keys:
            return await msg.answer("لم تُرسل أي مفاتيح.")
        deleted_map = await _inv_del_any(product, keys)
        _INV_SESS.pop(uid, None)
        return await msg.answer(
            "🗑 نتيجة الحذف:\n"
            f"• 3d: {deleted_map.get(3,0)}\n"
            f"• 10d: {deleted_map.get(10,0)}\n"
            f"• 30d: {deleted_map.get(30,0)}\n"
            + ("(استُخدم Blacklist لعدم توفر دوال حذف في inventory)" if sum(deleted_map.values()) == 0 else "")
        )

    if mode == "stop_msg":
        msg_text = "\n".join(sess.get("buf") or []).strip()
        set_keys_stop_message(msg_text)
        _INV_SESS.pop(uid, None)
        return await msg.answer("تم حفظ رسالة الإيقاف.")

    _INV_SESS.pop(uid, None)
    await msg.answer("انتهت الجلسة.")

# استقبال ملفات .txt داخل الجلسات
@router.message(F.document, AdminDocSession())
async def inv_collect_doc(msg: Message):
    uid = msg.from_user.id
    sess = _INV_SESS.get(uid)
    # (AdminDocSession يضمن إن فيه جلسة add/del_one/del_bulk)

    doc = msg.document
    if not doc:
        return
    if not ((doc.mime_type or "").startswith("text") or (doc.file_name or "").lower().endswith(".txt")):
        return await msg.answer("أرسل ملف .txt أو لصق المفاتيح كنص.")

    text = await _read_document_text(doc, msg.bot)
    if not text:
        return await msg.answer("⚠️ تعذّر قراءة الملف.")

    text_blob = sess.get("buf_text", "")
    text_blob += ("\n" if text_blob else "") + text
    sess["buf_text"] = text_blob
    approx = len(_extract_loose(text_blob))
    await msg.answer(f"📄 تم استلام ملف. الإجمالي المؤقت ~{approx} مفتاح.")


# حفظ من الأزرار
@router.callback_query(F.data == "sad:inv:save")
async def inv_save(cb: CallbackQuery):
    sess = _INV_SESS.get(cb.from_user.id)
    if not sess:
        return await cb.answer("لا توجد جلسة حالية.", show_alert=True)

    mode = sess.get("mode")
    product = sess.get("product", _cur_prod(cb.from_user.id))

    if mode == "add":
        days = int(sess.get("days") or 0) or 3
        text_blob = (sess.get("buf_text", "") or "").strip()
        if not text_blob:
            return await cb.answer("لا يوجد مفاتيح مُجمّعة. أرسل المفاتيح أولًا.", show_alert=True)
        inserted, duplicates = await _inv_add_any(product, days, text_blob)
        _INV_SESS.pop(cb.from_user.id, None)
        await cb.answer("تم الحفظ.", show_alert=False)
        await inv_page(cb)
        try:
            await cb.message.answer(
                "🎉 تم الإضافة.\n"
                f"• المنتج: {product}\n"
                f"• المدة: {days}d\n"
                f"• أضيف: {inserted}\n"
                f"• مُهمل/مكرر: {duplicates}"
            )
        except Exception:
            pass
        return

    if mode in ("del_one", "del_bulk"):
        keys = _extract_loose(sess.get("buf_text", "") or "")
        if not keys:
            return await cb.answer("لم تُرسل أي مفاتيح.", show_alert=True)
        deleted_map = await _inv_del_any(product, keys)
        _INV_SESS.pop(cb.from_user.id, None)
        await cb.answer("تم التنفيذ.", show_alert=False)
        await inv_page(cb)
        try:
            await cb.message.answer(
                "🗑 نتيجة الحذف:\n"
                f"• 3d: {deleted_map.get(3,0)}\n"
                f"• 10d: {deleted_map.get(10,0)}\n"
                f"• 30d: {deleted_map.get(30,0)}\n"
                + ("(استُخدم Blacklist لعدم توفر دوال حذف في inventory)" if sum(deleted_map.values()) == 0 else "")
            )
        except Exception:
            pass
        return

    _INV_SESS.pop(cb.from_user.id, None)
    await cb.answer("انتهت الجلسة.", show_alert=True)
    await inv_page(cb)

@router.callback_query(F.data == "sad:inv:stopmsg")
async def inv_stopmsg_start(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _INV_SESS[cb.from_user.id] = {"mode": "stop_msg", "buf": []}
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ حفظ الرسالة", callback_data="sad:inv:save")
    kb.button(text="🧹 مسح الرسالة", callback_data="sad:inv:stopmsg:clear")
    kb.button(text="◀️ رجوع", callback_data="sad:inv")
    kb.adjust(1, 1, 1)
    current = (get_keys_stop_message() or "").strip()
    txt = ("✍️ أرسل نص رسالة الإيقاف (يمكن عدة أسطر)."
           "\nسيتم عرضها للمستخدمين عندما تكون الخدمة متوقفة."
           f"\n\nالرسالة الحالية:\n{current if current else '—'}")
    await _edit_or_answer(cb, txt, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "sad:inv:stopmsg:clear")
async def inv_stopmsg_clear(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    set_keys_stop_message("")
    await cb.answer("تم مسح الرسالة.", show_alert=False)
    await inv_page(cb)

@router.callback_query(F.data == "sad:inv:toggle")
async def inv_toggle_service(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    new_state = not keys_service_enabled()
    set_keys_service_enabled(new_state)
    await cb.answer("تم التحديث.", show_alert=False)
    try:
        status = "🟢 مفعّلة" if new_state else "🔴 متوقفة"
        await cb.message.answer(f"حالة خدمة المفاتيح الآن: {status}")
    except Exception:
        pass
    await inv_page(cb)

# =========================
# الأسعار (USD)
# =========================
def _prices_root_kb():
    kb = InlineKeyboardBuilder()
    for p in ["default"] + PRODUCTS:
        kb.button(text=p, callback_data=f"sad:prices:which:{p}")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(3, 1)
    return kb.as_markup()

def _prices_edit_kb(prod: str, P: Dict[int, float]):
    kb = InlineKeyboardBuilder()
    for d in (3, 10, 30):
        kb.button(text=f"تعديل {d}d (${_money(P[d])})", callback_data=f"sad:prices:edit:{prod}:{d}")
    kb.button(text="◀️ رجوع", callback_data="sad:prices")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

@router.callback_query(F.data == "sad:prices")
async def prices_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    txt = "اختر مجموعة الأسعار التي تريد تعديلها (بالدولار):\n- default (افتراضي لكل المنتجات)\n- أو منتج محدد."
    await _edit_or_answer(cb, txt, reply_markup=_prices_root_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("sad:prices:which:"))
async def prices_which(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = cb.data.split(":")[-1].lower()
    P = _prices_usd(prod if prod != "default" else "default")
    txt = (
        f"💰 الأسعار الحالية ({prod}) بالدولار:\n"
        f"• 3d: ${_money(P[3])}\n"
        f"• 10d: ${_money(P[10])}\n"
        f"• 30d: ${_money(P[30])}\n\n"
        "اختر «تعديل» ثم أرسل السعر بالدولار (مثال: 4.99)."
    )
    await _edit_or_answer(cb, txt, reply_markup=_prices_edit_kb(prod, P))
    await cb.answer()

@router.callback_query(F.data.startswith("sad:prices:edit:"))
async def prices_edit(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _, _, _, prod, days_s = cb.data.split(":")
    days = int(days_s)
    if days not in (3, 10, 30):
        return await cb.answer("قيمة أيام غير صالحة.", show_alert=True)
    _PRICE_SESS[cb.from_user.id] = (prod, days)
    await cb.answer()
    try:
        await cb.message.answer(f"أرسل السعر الجديد لخطة {days}d في ({prod}) بالدولار (مثال: 4.99).")
    except Exception:
        pass

# =========================
# ⭐ أسعار النجوم
# =========================
def _stars_root_kb():
    kb = InlineKeyboardBuilder()
    for p in ["default"] + PRODUCTS:
        kb.button(text=p, callback_data=f"sad:stars:which:{p}")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(3, 1)
    return kb.as_markup()

def _stars_edit_kb(prod: str, S: Dict[int, int]):
    kb = InlineKeyboardBuilder()
    for d in (3, 10, 30):
        kb.button(text=f"تعديل {d}d (⭐{S[d]})", callback_data=f"sad:stars:edit:{prod}:{d}")
    kb.button(text="◀️ رجوع", callback_data="sad:stars")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

@router.callback_query(F.data == "sad:stars")
async def stars_prices_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = _cur_prod(cb.from_user.id)
    S = _prices_stars_effective(prod)
    txt = (
        f"⭐ أسعار النجوم الحالية ({prod}):\n"
        f"• 3d: ⭐{S[3]}\n"
        f"• 10d: ⭐{S[10]}\n"
        f"• 30d: ⭐{S[30]}\n\n"
        "اختر «تعديل» ثم أرسل قيمة النجوم كعدد صحيح (مثال: 13)."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text=f"تعديل 3d  (⭐{S[3]})",  callback_data=f"sad:stars:edit:{prod}:3")
    kb.button(text=f"تعديل 10d (⭐{S[10]})", callback_data=f"sad:stars:edit:{prod}:10")
    kb.button(text=f"تعديل 30d (⭐{S[30]})", callback_data=f"sad:stars:edit:{prod}:30")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(1, 1, 1, 1)
    await _edit_or_answer(cb, txt, reply_markup=kb.as_markup())
    await cb.answer()

# =========================
# طرق الدفع لكل منتج (نجوم/كريبتو)
# =========================
def _pay_root_kb():
    kb = InlineKeyboardBuilder()
    for p in ["default"] + PRODUCTS:
        kb.button(text=p, callback_data=f"sad:pay:which:{p}")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(3, 1)
    return kb.as_markup()

@router.callback_query(F.data == "sad:pay")
async def pay_modes_root(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    await _edit_or_answer(
        cb,
        "اختر المنتج لإدارة طرق الدفع (تفعيل/إيقاف).\n— ملاحظة: التفعيل يتأثر أيضًا بالتوفّر العالمي (تمكين النجوم أو وجود Crypto Pay/TON).",
        reply_markup=_pay_root_kb()
    )
    await cb.answer()

def _pay_edit_kb(prod: str, pm: dict):
    kb = InlineKeyboardBuilder()
    # زر تمكين/تعطيل بيع المنتج
    prod_on = is_product_enabled(prod)
    kb.button(text=("⛔️ إيقاف بيع المنتج" if prod_on else "✅ تشغيل بيع المنتج"),
              callback_data=f"sad:pay:prod:{prod}:{'off' if prod_on else 'on'}")

    stars_text  = ("✅ نجوم تيليجرام" if pm.get("stars", True) else "⛔️ نجوم تيليجرام")
    crypto_text = ("✅ كريبتو (USDT/TON)" if pm.get("crypto", True) else "⛔️ كريبتو (USDT/TON)")
    kb.button(text=stars_text,  callback_data=f"sad:pay:toggle:{prod}:stars")
    kb.button(text=crypto_text, callback_data=f"sad:pay:toggle:{prod}:crypto")
    kb.button(text="◀️ رجوع", callback_data="sad:pay")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

@router.callback_query(F.data.startswith("sad:pay:prod:"))
async def pay_modes_prod_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _, _, _, prod, action = cb.data.split(":")
    set_product_enabled(prod, action == "on")
    pm = get_pay_modes(prod)
    await cb.answer("تم التحديث.", show_alert=False)
    await _edit_or_answer(
        cb,
        f"تم تحديث حالة بيع ({prod}) إلى {'مفعّل' if is_product_enabled(prod) else 'متوقف'}.",
        reply_markup=_pay_edit_kb(prod, pm)
    )

@router.callback_query(F.data.startswith("sad:pay:which:"))
async def pay_modes_which(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = cb.data.split(":")[-1].lower()
    pm = get_pay_modes(prod)
    global_stars  = "نعم" if str(os.getenv("ENABLE_STARS","1")) != "0" else "لا"
    global_crypto = "نعم" if (bool(os.getenv("CRYPTOPAY_TOKEN")) or bool(os.getenv("TON_WALLET"))) else "لا"
    txt = (
        f"💳 طرق الدفع ({prod}):\n"
        f"• نجوم تيليجرام: {'مفعّل' if pm.get('stars', True) else 'متوقف'} (توفّر عالمي: {global_stars})\n"
        f"• كريبتو (USDT/TON): {'مفعّل' if pm.get('crypto', True) else 'متوقف'} (توفّر عالمي: {global_crypto})\n\n"
        "اضغط لتبديل الحالة."
    )
    await _edit_or_answer(cb, txt, reply_markup=_pay_edit_kb(prod, pm))
    await cb.answer()

@router.callback_query(F.data.startswith("sad:pay:toggle:"))
async def pay_modes_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _, _, _, prod, mode = cb.data.split(":")
    pm = get_pay_modes(prod)
    cur = bool(pm.get(mode, True))
    set_pay_mode_enabled(prod, mode, (not cur))
    await cb.answer("تم التحديث.", show_alert=False)
    pm2 = get_pay_modes(prod)
    await _edit_or_answer(
        cb,
        f"تم التحديث ({prod}).\n"
        f"• نجوم: {'مفعّل' if pm2.get('stars', True) else 'متوقف'}\n"
        f"• كريبتو: {'مفعّل' if pm2.get('crypto', True) else 'متوقف'}",
        reply_markup=_pay_edit_kb(prod, pm2)
    )

@router.callback_query(F.data.startswith("sad:stars:which:"))
async def stars_which(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = cb.data.split(":")[-1].lower()
    S = _prices_stars_effective(prod if prod != "default" else "default")
    txt = (
        f"⭐ أسعار النجوم الحالية ({prod}):\n"
        f"• 3d: ⭐{S[3]}\n"
        f"• 10d: ⭐{S[10]}\n"
        f"• 30d: ⭐{S[30]}\n\n"
        "اختر «تعديل» ثم أرسل قيمة النجوم كعدد صحيح (مثال: 13)."
    )
    await _edit_or_answer(cb, txt, reply_markup=_stars_edit_kb(prod, S))
    await cb.answer()

@router.callback_query(F.data.startswith("sad:stars:edit:"))
async def stars_edit(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    _, _, _, prod, days_s = cb.data.split(":")
    days = int(days_s)
    if days not in (3, 10, 30):
        return await cb.answer("قيمة أيام غير صالحة.", show_alert=True)
    _STAR_SESS[cb.from_user.id] = (prod, days)
    await cb.answer()
    try:
        await cb.message.answer(f"أرسل عدد النجوم الجديد لخطة {days}d في ({prod}) (مثال: 13).")
    except Exception:
        pass

# ---- إيقاف/تشغيل بيع المنتج بالكامل ----
try:
    from services.payments import (
        is_product_enabled as _p_is_product_enabled,
        set_product_enabled as _p_set_product_enabled,
    )
    def is_product_enabled(prod: str) -> bool: return _p_is_product_enabled(prod)
    def set_product_enabled(prod: str, enabled: bool): return _p_set_product_enabled(prod, enabled)
except Exception:
    # تخزين بالحقل "product_enabled" في FLAGS_PATH
    def _prod_enabled_all() -> dict:
        return (_jload(FLAGS_PATH).get("product_enabled") or {})
    def _prod_enabled_save(mp: dict):
        d = _jload(FLAGS_PATH); d["product_enabled"] = mp; _jsave(FLAGS_PATH, d)
    def is_product_enabled(prod: str) -> bool:
        p = (prod or "default").lower().strip()
        mp = _prod_enabled_all()
        base = True
        if "default" in mp: base = bool(mp["default"])
        if p in mp: base = bool(mp[p])
        return base
    def set_product_enabled(prod: str, enabled: bool):
        p = (prod or "default").lower().strip()
        mp = _prod_enabled_all(); mp[p] = bool(enabled); _prod_enabled_save(mp)

# =========================
# مُبدّل نصوص (جلسات الأسعار/النجوم/المخزون)
# =========================
@router.message(F.text, NotCommand(), AdminTextSession())
async def text_mux(msg: Message):
    uid = msg.from_user.id

    # 1) جلسة الأسعار (USD)
    if uid in _PRICE_SESS:
        prod, days = _PRICE_SESS.pop(uid, (None, None))
        if not prod or not days:
            return
        try:
            val = float((msg.text or "").strip().replace(",", "."))
            if val <= 0:
                raise ValueError
        except Exception:
            return await msg.reply("الرجاء إدخال رقم صالح مثل 4.99")
        mp = _load_prices_map()
        mp.setdefault(prod, {})
        mp[prod][int(days)] = val
        _save_prices_map(mp)
        return await msg.reply(f"✅ تم ضبط سعر {days}d ({prod}) إلى ${_money(val)}.")

    # 2) جلسة أسعار النجوم ⭐
    if uid in _STAR_SESS:
        prod, days = _STAR_SESS.pop(uid, (None, None))
        if not prod or not days:
            return
        try:
            raw = (msg.text or "").strip().replace(",", ".")
            val = int(float(raw))
            if val <= 0:
                raise ValueError
        except Exception:
            return await msg.reply("أدخل عدد نجوم صحيح (مثال: 13)")
        mp = _load_stars_map()
        mp.setdefault(prod, {})
        mp[prod][int(days)] = int(val)
        _save_stars_map(mp)
        return await msg.reply(f"✅ تم ضبط نجوم {days}d ({prod}) إلى ⭐{val}.")

    # 3) جلسة المخزون/الرسالة؟
    sess = _INV_SESS.get(uid)
    if not sess:
        return

    raw = (msg.text or "").strip()
    if raw.lower().startswith(("/done", "done", "حفظ", "/save")):
        return await _inv_save_from_message(msg)
    if raw.lower().startswith(("/cancel", "cancel", "الغاء", "إلغاء")):
        _INV_SESS.pop(uid, None)
        return await msg.answer("تم إلغاء الجلسة.")
    if raw.startswith("/"):
        return await msg.answer("أنت داخل جلسة. أرسل المحتوى المطلوب فقط، ثم اضغط «حفظ» أو أرسل /done.")

    mode = sess.get("mode")
    if mode == "stop_msg":
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("/")]
        sess.setdefault("buf", [])
        sess["buf"].extend(lines)
        return await msg.answer(f"تمت إضافة {len(lines)} سطرًا للرسالة. الإجمالي المؤقت: {len(sess['buf'])}.")
    else:
        text_blob = sess.get("buf_text", "")
        text_blob += ("\n" if text_blob else "") + raw
        sess["buf_text"] = text_blob
        approx = len(_extract_loose(text_blob))
        return await msg.answer(f"📥 تم الاستلام. الإجمالي المؤقت ~{approx} مفتاح.")


# =========================
# الطلبات
# =========================
def _orders_kb(page: int = 1):
    kb = InlineKeyboardBuilder()
    kb.button(text="↻ تحديث", callback_data=f"sad:orders:{page}")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(2)
    return kb.as_markup()

@router.callback_query(F.data == "sad:orders")
@router.callback_query(F.data.startswith("sad:orders:"))
async def orders_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    page = int(cb.data.split(":")[-1]) if ":" in cb.data and cb.data.count(":") == 2 else 1
    rows = await ords.list_pending()
    lines = ["🧾 الطلبات المعلّقة:"]
    if not rows:
        lines.append("• لا يوجد طلبات حالياً.")
    else:
        for r in rows[-20:][::-1]:
            amt = r.usd_amount if r.asset == "USDT" else r.ton_amount
            cur = "USDT" if r.asset == "USDT" else "TON"
            prod = getattr(r, "product", None) or getattr(r, "slug", None) or "?"
            lines.append(f"• #{r.id} | {prod} | {r.days}d×{r.qty} | {amt} {cur} | @{r.username or '-'} | {r.status}")
        lines.append("\nللتحكم بطلب محدد أرسل: /oid 123")
    await _edit_or_answer(cb, "\n".join(lines), reply_markup=_orders_kb(page))
    await cb.answer()

@router.message(Command("oid"))
async def order_view_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.answer("Admins only.")
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.answer("الاستخدام: /oid 123")
    oid = int(parts[1])
    r = await ords.get_by_id(oid)
    if not r:
        return await msg.answer("لم يتم العثور على الطلب.")
    amt = r.usd_amount if r.asset == "USDT" else r.ton_amount
    cur = "USDT" if r.asset == "USDT" else "TON"
    prod = getattr(r, "product", None) or getattr(r, "slug", None) or "-"
    text = (
        f"◽️ طلب #{r.id}\n"
        f"• المستخدم: {r.user_id} @{r.username or '-'}\n"
        f"• المنتج: {prod}\n"
        f"• الخطة: {r.days}d × {r.qty}\n"
        f"• المبلغ: {amt} {cur}\n"
        f"• الحالة: {r.status}\n"
        f"• أنشئ: {r.created_at}\n"
        f"• ينتهي: {r.expires_at}\n"
        f"• فاتورة/مرجع: {r.invoice_hash or '-'}"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ إجبار مدفوع", callback_data=f"sad:ord:paid:{oid}")
    kb.button(text="📩 سلّم الآن", callback_data=f"sad:ord:deliver:{oid}")
    kb.button(text="🛑 إلغاء", callback_data=f"sad:ord:cancel:{oid}")
    kb.button(text="◀️ رجوع", callback_data="sad:orders")
    kb.adjust(2, 2)
    await msg.answer(text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("sad:ord:paid:"))
async def ord_force_paid(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    oid = int(cb.data.split(":")[-1])
    await ords.mark_paid(oid)
    await cb.answer("تم وضعها مدفوعة.", show_alert=False)
    await orders_page(cb)

@router.callback_query(F.data.startswith("sad:ord:deliver:"))
async def ord_deliver(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    if not keys_service_enabled():
        return await cb.answer("خدمة المفاتيح متوقفة حاليًا.", show_alert=True)
    oid = int(cb.data.split(":")[-1])
    ok, delivered_text = await check_and_deliver_one(cb.bot, oid)
    if ok:
        try:
            await cb.message.answer(delivered_text, parse_mode="Markdown")
        except Exception:
            await cb.message.answer("تم التسليم.")
        await cb.answer("سُلّم.", show_alert=False)
    else:
        await cb.answer("بانتظار الدفع أو لا تتوفر مفاتيح كافية.", show_alert=True)
    await orders_page(cb)

@router.callback_query(F.data.startswith("sad:ord:cancel:"))
async def ord_cancel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    oid = int(cb.data.split(":")[-1])
    await ords.mark_cancelled_if_pending(oid)
    await cb.answer("أُلغي.", show_alert=False)
    await orders_page(cb)

# =========================
# الإحصائيات والتصدير
# =========================
@router.callback_query(F.data == "sad:stats")
async def stats_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    usd_all, ton_all, n_all = await _sales_sum()
    usd_30, ton_30, n_30 = await _sales_sum("datetime(created_at)>=datetime('now', ?)", ("-30 days",))
    usd_7, ton_7, n_7 = await _sales_sum("datetime(created_at)>=datetime('now', ?)", ("-7 days",))
    txt = (
        "📊 إحصائيات المبيعات\n"
        f"— آخر 7 أيام:   ${_money(usd_7)} USDT | {ton_7:.3f} TON | {n_7} طلب\n"
        f"— آخر 30 يوم:  ${_money(usd_30)} USDT | {ton_30:.3f} TON | {n_30} طلب\n"
        f"— كل الوقت:    ${_money(usd_all)} USDT | {ton_all:.3f} TON | {n_all} طلب\n"
        "\nيمكنك تصدير CSV لآخر 30 يوم."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🗂️ تصدير CSV (30d)", callback_data="sad:stats:csv30")
    kb.button(text="◀️ رجوع", callback_data="sad:home")
    kb.adjust(1, 1)
    await _edit_or_answer(cb, txt, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "sad:stats:csv30")
async def stats_export(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    data = await _export_csv(30)
    await cb.message.answer_document(
        BufferedInputFile(data, filename="orders_last_30d.csv"),
        caption="تصدير الطلبات (آخر 30 يوم)",
    )
    await cb.answer()

# =========================
# الإعدادات المختصرة + أوامر نصية
# =========================
@router.callback_query(F.data == "sad:settings")
async def settings_page(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    prod = _cur_prod(cb.from_user.id)
    pm = get_pay_modes(prod)
    mode = f"Crypto Pay ({', '.join(CRYPTO_ASSETS)})" if CRYPTOPAY_ON else "TON transfer"
    disabled = "لا" if keys_service_enabled() else "نعم"
    has_msg = "نعم" if (get_keys_stop_message() or "").strip() else "لا"

    enabled_line = "مفعّل" if is_product_enabled(prod) else "متوقف"

    P_def = _prices_usd("default")
    P_cur = _prices_usd(prod)
    S_def = _prices_stars_effective("default")
    S_cur = _prices_stars_effective(prod)
    txt = (
        "⚙️ الإعدادات الحالية\n"
        f"• المنتج الحالي: {prod}\n"
        f"• حالة بيع المنتج: {enabled_line}\n"
        f"• الدفع: {mode}\n"
        f"• طرق الدفع ({prod}): نجوم={'مفعّل' if pm.get('stars',True) else 'متوقف'} | كريبتو={'مفعّل' if pm.get('crypto',True) else 'متوقف'}\n"
        f"• مهلة الفاتورة: {INVOICE_TTL_MIN} دقيقة\n"
        f"• TON_WALLET: {TON_WALLET}\n"
        f"• خدمة المفاتيح متوقفة؟ {disabled}\n"
        f"• رسالة إيقاف مخصصة؟ {has_msg}\n"
        f"• الأسعار (USD default): 3d=${_money(P_def[3])} • 10d=${_money(P_def[10])} • 30d=${_money(P_def[30])}\n"
        f"• الأسعار (USD {prod}): 3d=${_money(P_cur[3])} • 10d=${_money(P_cur[10])} • 30d=${_money(P_cur[30])}\n"
        f"• ⭐ النجوم (default): 3d=⭐{S_def[3]} • 10d=⭐{S_def[10]} • 30d=⭐{S_def[30]}\n"
        f"• ⭐ النجوم ({prod}): 3d=⭐{S_cur[3]} • 10d=⭐{S_cur[10]} • 30d=⭐{S_cur[30]}\n\n"
        "يمكن تعديل الأسعار عبر اللوحات…"
    )
    await _edit_or_answer(cb, txt, reply_markup=_back_home_kb())
    await cb.answer()

@router.message(Command("prices"))
async def prices_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    P_def = _prices_usd("default")
    lines = [
        "💰 الأسعار (default):",
        f"• 3d: ${_money(P_def[3])}",
        f"• 10d: ${_money(P_def[10])}",
        f"• 30d: ${_money(P_def[30])}",
        "",
    ]
    for p in PRODUCTS:
        Pp = _prices_usd(p)
        lines += [
            f"💰 الأسعار ({p}):",
            f"• 3d: ${_money(Pp[3])}",
            f"• 10d: ${_money(Pp[10])}",
            f"• 30d: ${_money(Pp[30])}",
            "",
        ]
    lines += [
        "أوامر التعديل:",
        "/set_price 3 4.99                ← default",
        "/set_price carrom 3 4.99         ← منتج محدد",
        "/set_prices 3=4.99 10=12.5 30=25 ← default",
        "/set_prices carrom:3=5 8bp:10=3.5 ← متعدد المنتجات",
    ]
    await msg.reply("\n".join(lines).rstrip())

@router.message(Command("stars"))
async def stars_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    S_def = _prices_stars_effective("default")
    lines = [
        "⭐ أسعار النجوم (default):",
        f"• 3d: ⭐{S_def[3]}",
        f"• 10d: ⭐{S_def[10]}",
        f"• 30d: ⭐{S_def[30]}",
        "",
    ]
    for p in PRODUCTS:
        Sp = _prices_stars_effective(p)
        lines += [
            f"⭐ أسعار ({p}):",
            f"• 3d: ⭐{Sp[3]}",
            f"• 10d: ⭐{Sp[10]}",
            f"• 30d: ⭐{Sp[30]}",
            "",
        ]
    lines += [
        "أوامر التعديل:",
        "/set_star 3 13                   ← default",
        "/set_star carrom 10 27           ← منتج محدد",
        "/set_stars 3=13 10=27 30=55      ← default",
        "/set_stars carrom:3=12 8bp:10=23 ← متعدد المنتجات",
    ]
    await msg.reply("\n".join(lines).rstrip())

@router.message(Command("set_price"))
async def set_price_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split()
    try:
        if len(parts) == 3:
            prod = "default"; d = int(parts[1]); val = float(parts[2])
        elif len(parts) == 4:
            prod = parts[1].lower(); d = int(parts[2]); val = float(parts[3])
        else:
            raise ValueError
        if d not in (3, 10, 30) or val <= 0:
            raise ValueError
    except Exception:
        return await msg.reply("الاستخدام: /set_price <days> <usd> أو /set_price <product> <days> <usd>")
    mp = _load_prices_map()
    mp.setdefault(prod, {})
    mp[prod][d] = val
    _save_prices_map(mp)
    await msg.reply(f"✅ تم ضبط سعر {d}d ({prod}) إلى ${_money(val)}.")

@router.message(Command("set_prices"))
async def set_prices_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split()[1:]
    if not parts:
        return await msg.reply("استخدام: /set_prices 3=4.99 10=12.5 30=25 أو /set_prices carrom:3=5 8bp:10=3.5")
    mp = _load_prices_map(); changed = []
    for part in parts:
        try:
            if ":" in part.split("=", 1)[0]:
                prod_days, val_s = part.split("=", 1)
                prod, days_s = prod_days.split(":", 1)
                prod = prod.lower().strip()
                d = int(days_s); val = float(val_s)
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault(prod, {})[d] = val
                    changed.append(f"{prod}:{d}d=${_money(val)}")
            else:
                days_s, val_s = part.split("=", 1)
                d = int(days_s); val = float(val_s)
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault("default", {})[d] = val
                    changed.append(f"default:{d}d=${_money(val)}")
        except Exception:
            continue
    _save_prices_map(mp)
    await msg.reply("✅ تم التحديث: " + (", ".join(changed) if changed else "لا شيء."))

@router.message(Command("set_star"))
async def set_star_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split()
    try:
        if len(parts) == 3:
            prod = "default"; d = int(parts[1]); val = int(float(parts[2]))
        elif len(parts) == 4:
            prod = parts[1].lower(); d = int(parts[2]); val = int(float(parts[3]))
        else:
            raise ValueError
        if d not in (3, 10, 30) or val <= 0:
            raise ValueError
    except Exception:
        return await msg.reply("الاستخدام: /set_star <days> <stars> أو /set_star <product> <days> <stars>")
    mp = _load_stars_map()
    mp.setdefault(prod, {})
    mp[prod][d] = int(val)
    _save_stars_map(mp)
    await msg.reply(f"✅ تم ضبط نجوم {d}d ({prod}) إلى ⭐{int(val)}.")

@router.message(Command("set_stars"))
async def set_stars_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split()[1:]
    if not parts:
        return await msg.reply("استخدام: /set_stars 3=13 10=27 30=55 أو /set_stars carrom:3=12 8bp:10=23")
    mp = _load_stars_map(); changed = []
    for part in parts:
        try:
            if ":" in part.split("=", 1)[0]:
                prod_days, val_s = part.split("=", 1)
                prod, days_s = prod_days.split(":", 1)
                prod = prod.lower().strip()
                d = int(days_s); val = int(float(val_s))
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault(prod, {})[d] = val
                    changed.append(f"{prod}:{d}d=⭐{val}")
            else:
                days_s, val_s = part.split("=", 1)
                d = int(days_s); val = int(float(val_s))
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault("default", {})[d] = val
                    changed.append(f"default:{d}d=⭐{val}")
        except Exception:
            continue
    _save_stars_map(mp)
    await msg.reply("✅ تم التحديث: " + (", ".join(changed) if changed else "لا شيء."))

# =========================
# حذف مفاتيح عام (تُستخدم داخل _inv_del_any)
# =========================
# لا حاجة لدالة مستقلة هنا؛ تمت معالجتها في _inv_del_any
