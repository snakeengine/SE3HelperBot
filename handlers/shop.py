# handlers/shop.py
from __future__ import annotations

import asyncio
import os
import math
import json
import re
import datetime as dt
import logging
from pathlib import Path
from typing import Dict, Union, List, Tuple

from html import escape as h

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types.input_file import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from lang import t as _t, get_user_lang
from services import orders as ords
from services import inventory as inv
from services.payments import check_and_deliver_one
from services import cryptopay as cp  # Crypto Pay
from utils.paths import BASE
from constants import PRICE_USD_3, PRICE_USD_10, PRICE_USD_30
from aiogram.fsm.context import FSMContext
from handlers.home_hero import render_home_card

# ... بعد try/import لطرق الدفع
try:
    from services.payments import is_product_enabled as _p_is_prod_enabled
    def _is_product_enabled(product: str) -> bool:
        return bool(_p_is_prod_enabled(product))
except Exception:
    def _is_product_enabled(product: str) -> bool:
        # لو ما توفرت الدالة، اعتبره مفعّل
        return True

# --- Pay modes per product (admin toggles) ---
try:
    from services.payments import (
        is_stars_enabled_for as _p_is_stars_ok,
        is_crypto_enabled_for as _p_is_crypto_ok,
    )
    def _is_stars_ok(product: str) -> bool:  # عبر services.payments
        return bool(_p_is_stars_ok(product))
    def _is_crypto_ok(product: str) -> bool:
        return bool(_p_is_crypto_ok(product))
except Exception:
    # فولباك: نقرأ من FLAGS_PATH -> { "pay_modes": { "default": {"stars": true, "crypto": true}, "<prod>": {...} } }
    def _pm_load() -> dict:
        try:
            return (_load_json(FLAGS_PATH).get("pay_modes") or {})
        except Exception:
            return {}

    def _is_stars_ok(product: str) -> bool:
        product = (product or "default").lower().strip()
        mp = _pm_load()
        base = {"stars": True, "crypto": True}
        base.update(mp.get("default") or {})
        base.update(mp.get(product) or {})
        return bool(base.get("stars", True))

    def _is_crypto_ok(product: str) -> bool:
        product = (product or "default").lower().strip()
        mp = _pm_load()
        base = {"stars": True, "crypto": True}
        base.update(mp.get("default") or {})
        base.update(mp.get(product) or {})
        return bool(base.get("crypto", True))


router = Router()

# === المنتجات (ديناميكية) ===
DEFAULT_PRODUCT = (os.getenv("PRODUCT_KEY", "8bp") or "8bp").lower().strip()
PRODUCTS = [p.strip().lower() for p in (os.getenv("SHOP_PRODUCTS", "8bp,carrom,soccer").split(","))]
# إزالة الفارغ والمكرّر
PRODUCTS = list(dict.fromkeys([p for p in PRODUCTS if p])) or ["8bp", "carrom", "soccer"]


# منع التكرار بعد التأكيد/التسليم
_CONFIRMED_SHOWN: set[int] = set()
_DELIVERED_POSTED: set[int] = set()

def _code(txt: str) -> str:
    return f"<code>{h(str(txt))}</code>"

# ========= ملفات حالة/إعداد =========
FLAGS_PATH   = BASE / "shop_flags.json"
SHOP_CFG     = BASE / "shop_config.json"
PRICES_PATH  = BASE / "shop_prices.json"        # أسعار USD (متعددة المنتجات)
STARS_PRICES = BASE / "shop_stars.json"      # أسعار النجوم (متعددة المنتجات)
TIERS_PATH   = BASE / "vip_tiers.json"          # (اختياري) إهماله إن لم يوجد

def _load_json(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_json(p: Path, obj: dict):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logging.exception("save_json failed: %r", e)

def _flags() -> dict:
    return _load_json(FLAGS_PATH)

def _set_flag(key: str, value):
    f = _flags()
    f[key] = value
    _save_json(FLAGS_PATH, f)

def _keys_service_disabled() -> bool:
    return bool(_flags().get("keys_disabled", False))

def _shop_enabled() -> bool:
    cfg = _load_json(SHOP_CFG)
    return bool(cfg.get("enabled", True))

def _stop_message() -> str:
    return str(_flags().get("keys_stop_message", "") or "").strip()

# ========= إعدادات عامة =========
TON_USD_RATE      = float(os.getenv("TON_USD_RATE", "6.0"))
INVOICE_TTL_MIN   = int(os.getenv("INVOICE_TTL_MIN", "15"))
ENABLE_STARS      = int(os.getenv("ENABLE_STARS", "0")) == 1

# روابط/أدلة عامة (fallback)
APP_DOWNLOAD_URL_DEFAULT     = os.getenv("APP_DOWNLOAD_URL", "")
ACTIVATION_GUIDE_URL_DEFAULT = os.getenv("ACTIVATION_GUIDE_URL", "")
TUTORIAL_URL_DEFAULT         = os.getenv("TUTORIAL_URL", "") or os.getenv("TUTORIAL_FILE_ID", "")

# روابط/أدلة لكل منتج (إن وُجدت)
def _per_product_env(prefix: str, product: str) -> str:
    key1 = f"{product.upper()}_{prefix}".replace("-", "_")
    key2 = f"{product.upper()}_{prefix}_URL".replace("-", "_")
    key3 = f"{product.upper()}_{prefix}_FILE_ID".replace("-", "_")
    return os.getenv(key1) or os.getenv(key2) or os.getenv(key3) or ""

def _product_links(product: str) -> Tuple[str, str, str]:
    product = (product or "").lower().strip()
    app   = _per_product_env("APP_DOWNLOAD", product) or APP_DOWNLOAD_URL_DEFAULT
    guide = _per_product_env("ACTIVATION_GUIDE", product) or ACTIVATION_GUIDE_URL_DEFAULT
    tut   = _per_product_env("TUTORIAL", product) or TUTORIAL_URL_DEFAULT
    return app, guide, tut

CRYPTO_ENABLED  = bool(os.getenv("CRYPTOPAY_TOKEN"))
CRYPTO_ASSETS   = [s.strip().upper() for s in (os.getenv("CRYPTO_ASSETS", os.getenv("CRYPTO_ASSET", "USDT")) or "USDT").split(",") if s.strip()]
CRYPTO_ASSETS   = list(dict.fromkeys(CRYPTO_ASSETS))
CRYPTO_ONLY     = (os.getenv("CRYPTO_ONLY", "0") == "1")
DEFAULT_ASSET   = CRYPTO_ASSETS[0] if CRYPTO_ASSETS else "USDT"

TON_ADDRESS = os.getenv("TON_WALLET", "")
ASSET_TON   = "TON"

ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")).split(",") if x.strip().isdigit()]
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ========= نصوص/لغة =========
def _user_lang(obj) -> str:
    try:
        if hasattr(obj, "from_user") and getattr(obj.from_user, "id", None):
            pref = get_user_lang(obj.from_user.id)
            if pref:
                return str(pref).split("-")[0]
    except Exception:
        pass
    code = getattr(getattr(obj, "from_user", None), "language_code", "ar") or "ar"
    return (code or "ar").split("-")[0]

def L(lang: str, ar: str, en: str) -> str:
    return ar if str(lang).startswith("ar") else en

def tr(lang: str, key: str, fallback: str) -> str:
    try:
        val = _t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fallback

def trf(lang: str, key: str, fallback: str, **fmt) -> str:
    s = tr(lang, key, fallback)
    try:
        return s.format(**fmt)
    except Exception:
        return s

# ====== أسعار USD (fallback) ======
DEFAULT_PRICES_FLAT = {
    3:  float(os.getenv("PRICE_USD_3", PRICE_USD_3)),
    10: float(os.getenv("PRICE_USD_10", PRICE_USD_10)),
    30: float(os.getenv("PRICE_USD_30", PRICE_USD_30)),
}

# ====== قراءة/كتابة أسعار USD (متعددة المنتجات) ======
def _load_prices_map() -> Dict[str, Dict[int, float]]:
    raw = _load_json(PRICES_PATH)
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
        out["default"] = dict(DEFAULT_PRICES_FLAT)
        return out

    if any(k in raw for k in ("3", "10", "30")):
        out["default"] = _to_days_map(raw)
        return out

    for prod, dct in raw.items():
        out[str(prod).lower()] = _to_days_map(dct)  # <-- lower

    if "default" not in out or not out["default"]:
        out["default"] = dict(DEFAULT_PRICES_FLAT)
    return out

def _save_prices_map(mp: Dict[str, Dict[int, float]]):
    serial: Dict[str, Dict[str, float]] = {}
    for prod, dmap in mp.items():
        serial[str(prod).lower()] = {str(k): float(v) for k, v in dmap.items() if k in (3, 10, 30)}  # <-- lower
    _save_json(PRICES_PATH, serial)


def _prices_usd(product: str) -> Dict[int, float]:
    product = (product or "").lower().strip()
    mp = _load_prices_map()
    base = dict(DEFAULT_PRICES_FLAT)
    if "default" in mp: base.update(mp["default"])
    if product in mp:   base.update(mp[product])
    return base

# توافق مع كود الإدمن
def _jload(p: Path) -> dict: 
    return _load_json(p)

def _jsave(p: Path, d: dict):
    _save_json(p, d)

# ====== أسعار النجوم ======
def _stars_per_usd_from_env() -> float:
    """
    STARS_PER_USD = نجوم لكل 1$
    أو USD_PER_STAR = سعر النجمة بالدولار (نحوّل تلقائيًا)
    """
    raw = (os.getenv("STARS_PER_USD") or os.getenv("USD_PER_STAR") or "50").strip()
    try:
        val = float(raw)
    except Exception:
        val = 50.0
    if 0 < val < 1:
        return 1.0 / val
    return max(val, 1.0)

STARS_PER_USD: float = _stars_per_usd_from_env()

def _load_stars_map() -> dict[str, dict[int, int]]:
    raw = _jload(STARS_PRICES)
    out: dict[str, dict[int, int]] = {}

    def _to_days_map(dct) -> dict[int, int]:
        m: dict[int, int] = {}
        for k, v in (dct or {}).items():
            try:
                kk = int(k)
                if kk in (3, 10, 30):
                    m[kk] = int(v)
            except Exception:
                continue
        return m

    if not raw:
        return {}  # مافيش ملف → هنشتق من USD
    if any(k in raw for k in ("3", "10", "30")):
        out["default"] = _to_days_map(raw)
        return out
    for prod, dct in raw.items():
        out[str(prod).lower()] = _to_days_map(dct)
    return out

def _save_stars_map(mp: dict[str, dict[int, int]]):
    serial: dict[str, dict[str, int]] = {}
    for prod, dmap in mp.items():
        serial[str(prod).lower()] = {str(k): int(v) for k, v in (dmap or {}).items() if k in (3, 10, 30)}
    _jsave(STARS_PRICES, serial)


def _prices_stars(product: str) -> Dict[int, int]:
    """
    يرجّع أسعار النجوم للمنتج.
    إن لم يكن هناك ملف/سعر محدّد → يحوّل من USD باستخدام STARS_PER_USD.
    """
    product = (product or "").lower().strip()
    mp = _load_stars_map()
    usd = _prices_usd(product)
    base = {}
    if "default" in mp:
        base.update(mp["default"])
    if product in mp:
        base.update(mp[product])
    out: Dict[int, int] = {}
    for d in (3, 10, 30):
        if d in base:
            out[d] = int(base[d])
        else:
            out[d] = max(1, int(round(usd[d] * STARS_PER_USD)))
    return out

# ====== tiers (اختياري) لأسعار USD فقط ======
def _tiers_from_file() -> List[dict]:
    try:
        data = _load_json(TIERS_PATH)
        if not isinstance(data, list):
            return []
        out = []
        for x in data:
            try:
                days = int(x.get("days"))
                if days not in (3, 10, 30):
                    continue
                out.append({
                    "product": str(x.get("product") or "default").lower(),
                    "days": days,
                    "usd": float(x.get("usd")),
                    "badge": str(x.get("badge", "")).strip(),
                    "enabled": bool(x.get("enabled", True)),
                })
            except Exception:
                continue
        return out
    except Exception:
        return []

def _apply_tiers(prices: Dict[int, float], product: str) -> Dict[int, float]:
    product = (product or "").lower().strip() 
    tiers = _tiers_from_file()
    if not tiers:
        return prices
    p = dict(prices)
    for t in tiers:
        if not t["enabled"]:
            continue
        if t["product"] in (product, "default"):
            p[t["days"]] = float(t["usd"])
    return p

def _usd_to_ton(usd: float) -> float:
    return usd / TON_USD_RATE if TON_USD_RATE > 0 else usd

def _fmt_money(amount: float, digits: int = 2) -> str:
    q = 10 ** digits
    return f"{math.ceil(amount * q) / q:.{digits}f}"

# ========= نص طريقة التفعيل =========
AR_ACTIVATION_STEPS = (
    "🔐 طريقة تفعيل المفتاح\n"
    "• بعد استلام المفتاح، افتح تطبيق محرك الثعبان.\n"
    "• من الزاوية العلوية (يمين/يسار) اضغط على معرّف التطبيق.\n"
    "• في أسفل الشاشة اضغط زر Entry Key.\n"
    "• انسخ مفتاح الاشتراك الذي وصلك هنا، ثم الصقه واضغط Activate.\n"
    "• المفتاح يُفعَّل مرة واحدة فقط؛ إن حاولت استخدامه ثانية سيظهر “مستخدم”.\n"
    "• يمكنك تفعيل المفتاح في أي وقت؛ الوقت لا يبدأ إلا بعد التفعيل."
)

EN_ACTIVATION_STEPS = (
    "🔐 How to activate your key\n"
    "• After you receive the key, open the Snake Engine app.\n"
    "• From the top corner (right/left), tap the App ID.\n"
    "• At the bottom of the screen, tap the Entry Key button.\n"
    "• Copy the subscription key you received here, paste it, then tap Activate.\n"
    "• Each key can be activated once; if you try again it will show as “Used”.\n"
    "• You can activate the key any time; time starts only after activation."
)

def activation_text(lang: str) -> str:
    return AR_ACTIVATION_STEPS if str(lang).startswith("ar") else EN_ACTIVATION_STEPS

def _activation_kb(lang: str, product: str, oid: int | None = None):
    app, guide, tut = _product_links(product)
    kb = InlineKeyboardBuilder()
    added = 0
    if tut:
        cb = f"shop:tutorial:{oid}" if oid else f"shop:tutorial:0"
        kb.button(text=L(lang, "🎥 شرح بالفيديو", "🎥 Video tutorial"), callback_data=cb); added += 1
    if app:
        kb.button(text="📦 تحميل التطبيق" if str(lang).startswith("ar") else "📦 Download App", url=app); added += 1
    if guide:
        kb.button(text="📘 شرح التفعيل" if str(lang).startswith("ar") else "📘 Activation Guide", url=guide); added += 1
    if added == 0:
        return None
    kb.adjust(1)
    return kb.as_markup()

async def _send_activation_help(bot, user_id: int, lang: str, product: str, oid: int | None = None):
    txt = activation_text(lang)
    kb = _activation_kb(lang, product, oid=oid)
    await bot.send_message(user_id, txt, parse_mode=ParseMode.HTML, reply_markup=kb)

# ========= إيقاف الخدمة =========
def _service_paused_text(lang: str) -> str:
    return _stop_message() or ("⏸️ خدمة المفاتيح متوقفة مؤقتًا للصيانة." if str(lang).startswith("ar") else "⏸️ Keys store is temporarily paused for maintenance.")

def _paused_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="تحديث" if str(lang).startswith("ar") else "Refresh", callback_data="shop:home")
    return kb.as_markup()

async def _ensure_service_available(ev: Union[Message, CallbackQuery]) -> bool:
    if _shop_enabled() and not _keys_service_disabled():
        return True
    lang = _user_lang(ev)
    text = _service_paused_text(lang)
    try:
        if isinstance(ev, CallbackQuery):
            try:
                await ev.message.edit_text(text, reply_markup=_paused_kb(lang))
            except Exception:
                await ev.message.answer(text, reply_markup=_paused_kb(lang))
            await ev.answer()
        else:
            await ev.answer(text, reply_markup=_paused_kb(lang))
    except Exception:
        pass
    return False

# ========= واجهة المتجر =========
def _shop_home_text(lang: str, discount_rate: float = 0.30) -> str:
    """
    يعرض فقرة متجر المفاتيح مع سطر خصم لغوي.
    يمكن تغيير نسبة الخصم عبر discount_rate (مثلاً 0.25 = 25%).
    """
    is_ar = str(lang).startswith("ar")
    pct = int(round(discount_rate * 100))

    title = "متجر المفاتيح" if is_ar else "Key Store"

    if is_ar:
        lines = [
            f"🎉 خصم {pct}٪ على الأسعار اليوم! يُطبَّق تلقائيًا عند الدفع.",
            "اختر المنتج ثم طريقة الدفع والمدة — كلها داخل تيليجرام.",
            "💳 طرق الدفع المتاحة: " +
            ("Crypto Pay: " + ", ".join(CRYPTO_ASSETS) if CRYPTO_ENABLED else "TON transfer")
            + (" • ⭐️ نجوم تيليجرام" if ENABLE_STARS else ""),
            "⚡️ التسليم فوري بعد الدفع: يصلك المفتاح هنا مع بطاقة الشراء.",
            "ملاحظة: طرق الدفع قد تختلف حسب المنتج."
        ]
    else:
        lines = [
            f"🎉 {pct}% off today! Applied automatically at checkout.",
            "Pick a product, then payment method & duration — all inside Telegram.",
            "💳 Payments: " +
            ("Crypto Pay: " + ", ".join(CRYPTO_ASSETS) if CRYPTO_ENABLED else "TON transfer")
            + (" • ⭐ Telegram Stars" if ENABLE_STARS else ""),
            "⚡️ Instant delivery: key + purchase card here.",
            "Note: available methods may vary per product."
        ]

    return f"{title}\n" + "\n".join(lines)


def _shop_home_kb(lang: str):
    kb = InlineKeyboardBuilder()
    for p in PRODUCTS:
        kb.button(text=_product_label(lang, p), callback_data=f"shop:g:{p}")
    kb.button(
        text=("⬅️ القائمة الرئيسية" if str(lang).startswith("ar") else "⬅️ Main menu"),
        callback_data="shop:menu"     # هذا يخرج للـ Hero
    )
    kb.adjust(1)
    return kb.as_markup()



def _product_label(lang: str, product: str) -> str:
    product = (product or "").lower().strip()
    fallback = {
        "8bp":    L(lang, "🎱 8Ball Pool", "🎱 8Ball Pool"),
        "carrom": L(lang, "🟢 Carrom Pool", "🟢 Carrom Pool"),
        "soccer": L(lang, "⚽ Soccer Stars: Football Kick", "⚽ Soccer Stars: Football Kick"),
    }.get(product, product)
    return tr(lang, f"shop.games.{product}", fallback)


# ========= دخول/عودة =========
@router.message(Command("shop"))
async def shop_entry(msg: Message):
    if not await _ensure_service_available(msg): return
    lang = _user_lang(msg)
    await msg.answer(_shop_home_text(lang), reply_markup=_shop_home_kb(lang))

# فتح واجهة المتجر (من /shop أو من زر شراء/فتح المتجر)
@router.callback_query(F.data.in_({"shop:open", "shop:home", "shop:sevip"}))
async def shop_open(cb: CallbackQuery):
    if not await _ensure_service_available(cb): 
        return
    lang = _user_lang(cb)
    try:
        await cb.message.edit_text(_shop_home_text(lang), reply_markup=_shop_home_kb(lang))
    except Exception:
        await cb.message.answer(_shop_home_text(lang), reply_markup=_shop_home_kb(lang))
    await cb.answer()

# الخروج إلى القائمة الرئيسية (Hero)
@router.callback_query(F.data == "shop:menu")
async def shop_to_main(cb: CallbackQuery, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass

    # خذ لغة المستخدم (محفوظة إن وجدت، وإلا من Telegram)
    lang = _user_lang(cb)   # "ar" أو "en"

    # أعرض بطاقة البداية بنفس اللغة
    await render_home_card(cb.message, lang=lang)
    await cb.answer()
# ========= اختيار المنتج ثم طريقة الدفع =========
def _pay_methods_for(product: str) -> List[str]:
    """
    تُرجع قائمة الطرق المسموحة لهذا المنتج بعد التقاطع بين:
    - التفعيل العالمي (ENABLE_STARS / CRYPTO_ENABLED أو TON_ADDRESS)
    - إعدادات الإدمن لكل منتج (pay_modes)
    - أي تقييد عبر متغير بيئة مثل 8BP_PAY=stars,crypto أو SOCCER_PAY=stars
    """
    product = (product or "").lower().strip()

    # الحالة العالمية
    allow_stars_global  = bool(ENABLE_STARS)
    allow_crypto_global = bool(CRYPTO_ENABLED or TON_ADDRESS)

    # حالة الإدمن لكل منتج
    allow_stars_admin   = _is_stars_ok(product)
    allow_crypto_admin  = _is_crypto_ok(product)

    allow_stars  = allow_stars_global  and allow_stars_admin
    allow_crypto = allow_crypto_global and allow_crypto_admin

    methods: List[str] = []

    # تقييد اختياري عبر env لكل منتج (يدعم *_PAY و *_PAYMENTS)
    conf = (os.getenv(f"{product.upper()}_PAY") or os.getenv(f"{product.upper()}_PAYMENTS") or "").strip().lower()
    if conf:
        wanted = [m.strip() for m in conf.split(",") if m.strip() in ("stars", "crypto", "ton")]
        if "stars"  in wanted and allow_stars:
            methods.append("stars")
        if ("crypto" in wanted or "ton" in wanted) and allow_crypto:
            methods.append("crypto")
        return methods

    # الافتراضي بدون تقييد env: ما دام مسموح عالميًا وإداريًا
    if allow_stars:
        methods.append("stars")
    if allow_crypto:
        methods.append("crypto")
    return methods

def _pay_methods_kb(lang: str, product: str):
    kb = InlineKeyboardBuilder()

    # لو المنتج متوقف، أعرض زر رجوع فقط
    if not _is_product_enabled(product):
        kb.button(
            text=("رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"),
            callback_data="shop:home"
        )
        kb.adjust(1)
        return kb.as_markup()

    methods = _pay_methods_for(product)

    for m in methods:
        if m == "stars":
            kb.button(
                text=("⭐ الدفع بنجوم تيليجرام" if str(lang).startswith("ar") else "⭐ Pay with Telegram Stars"),
                callback_data=f"shop:pm:{product}:stars"
            )
        elif m == "crypto":
            label = ("💳 الدفع (USDT/TON)" if str(lang).startswith("ar") else "💳 Pay (USDT/TON)")
            kb.button(
                text=label,
                callback_data=f"shop:pm:{product}:crypto"
            )

    # زر الرجوع دائمًا
    kb.button(
        text=("رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"),
        callback_data="shop:home"
    )

    # ترتيب الأعمدة (زرين في الصف كحد أقصى)
    kb.adjust(1, 1)
    return kb.as_markup()


@router.callback_query(F.data.startswith("shop:g:"))
async def choose_payment_method(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    lang = _user_lang(cb)
    _, _, product = cb.data.split(":", 2)

    # منتج متوقف؟
    if not _is_product_enabled(product):
        txt = "⏸️ هذا المنتج متوقف مؤقتًا." if str(lang).startswith("ar") else "⏸️ This product is temporarily paused."
        kb = InlineKeyboardBuilder()
        kb.button(text=("رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"), callback_data="shop:home")
        kb.adjust(1)
        try:
            await cb.message.edit_text(txt, reply_markup=kb.as_markup())
        except Exception:
            await cb.message.answer(txt, reply_markup=kb.as_markup())
        await cb.answer()
        return

    methods = _pay_methods_for(product)
    if not methods:
        txt = "⚠️ طرق الدفع لهذا المنتج متوقفة مؤقتًا." if str(lang).startswith("ar") else "⚠️ Payments for this product are temporarily disabled."
    else:
        txt = "اختر طريقة الدفع:" if str(lang).startswith("ar") else "Choose a payment method:"

    try:
        await cb.message.edit_text(txt, reply_markup=_pay_methods_kb(lang, product))
    except Exception:
        await cb.message.answer(txt, reply_markup=_pay_methods_kb(lang, product))
    await cb.answer()


# ========= اختيار الخطة (حسب الطريقة) =========
def _labels_for_usd(lang: str, product: str) -> Dict[int, str]:
    prices = _apply_tiers(_prices_usd(product), product)
    def label(days: int) -> str:
        price = _fmt_money(prices[days], 2)
        return f"💵 ${price} | {days} يوم" if str(lang).startswith("ar") else f"${price} — {days}d"
    return {d: label(d) for d in (3, 10, 30)}

def _labels_for_stars(lang: str, product: str) -> Dict[int, str]:
    prices = _prices_stars(product)
    def label(days: int) -> str:
        s = int(prices[days])
        return f"⭐ {s} | {days} يوم" if str(lang).startswith("ar") else f"⭐ {s} — {days}d"
    return {d: label(d) for d in (3, 10, 30)}

@router.callback_query(F.data.startswith("shop:pm:"))
async def choose_plan(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    lang = _user_lang(cb)
    _, _, product, method = cb.data.split(":")

    labels = _labels_for_stars(lang, product) if method == "stars" else _labels_for_usd(lang, product)

    kb = InlineKeyboardBuilder()
    for d in (3, 10, 30):
        kb.button(text=labels[d], callback_data=f"shop:p:{product}:{method}:{d}")

    cols = 2 if str(lang).startswith("ar") else 3
    kb.button(text=("رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"), callback_data=f"shop:g:{product}")
    kb.adjust(cols, 1)

    txt = "اختر المدة" if str(lang).startswith("ar") else "Choose duration"
    try:
        await cb.message.edit_text(txt, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(txt, reply_markup=kb.as_markup())
    await cb.answer()

# ========= اختيار الكمية =========
@router.callback_query(F.data.startswith("shop:p:"))
async def choose_qty(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    lang = _user_lang(cb)
    _, _, product, method, days_s = cb.data.split(":")
    days = int(days_s)

    # عرض السعر في العنوان
    if method == "stars":
        price = _prices_stars(product)[days]
        head = "الخطة: {days} يوم — ⭐ {price} | اختر الكمية:" if str(lang).startswith("ar") else "Plan: {days}d — ⭐ {price} | Choose quantity:"
        txt = head.format(days=days, price=price)
    else:
        usd = _apply_tiers(_prices_usd(product), product)[days]
        head = "السعر: ${usd} — {days} يوم | اختر الكمية:" if str(lang).startswith("ar") else "Plan: {days}d — ${usd} | Choose quantity:"
        txt = head.format(days=days, usd=_fmt_money(usd, 2))

    # أضف المتوفر الفعلي
    left = await _count_for_safe(days, product)
    if left is not None:
        if str(lang).startswith("ar"):
            txt += f"\n(المتوفر الآن: {left})"
        else:
            txt += f"\n(Available now: {left})"

    kb = InlineKeyboardBuilder()
    for n in range(1, 11):
        kb.button(text=f"{n}×", callback_data=f"shop:q:{product}:{method}:{days}:{n}")
    kb.button(text=("رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"), callback_data=f"shop:pm:{product}:{method}")
    kb.adjust(5, 5, 1)

    try:
        await cb.message.edit_text(txt, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(txt, reply_markup=kb.as_markup())
    await cb.answer()


async def _count_for_safe(days: int, product: str) -> int:
    f = getattr(inv, "count_for", None)
    if not callable(f):
        return 0

    async def _call(fn, *a, **kw):
        r = fn(*a, **kw)
        return await r if asyncio.iscoroutine(r) else r

    try:
        return int(await _call(f, days, product) or 0)
    except Exception:
        pass
    try:
        return int(await _call(f, product, days) or 0)
    except Exception:
        pass
    for kw in ({"days": days, "product": product}, {"product": product, "days": days}):
        try:
            return int(await _call(f, **kw) or 0)
        except Exception:
            pass
    try:
        return int(await _call(f, days) or 0)
    except Exception:
        return 0

# === Helpers: نص وأزرار اقتراح كمية أقل ===
def _not_enough_stock_text(lang: str, days: int, left: int) -> str:
    if str(lang).startswith("ar"):
        if left <= 0:
            return f"لا يوجد مخزون لمدة {days} يوم."
        unit = "مفتاح" if left == 1 else ("مفتاحين" if left == 2 else "مفاتيح")
        return f"الكمية المطلوبة غير متاحة لمدة {days} يوم.\nالمتوفر الآن: {left} {unit}.\n💡 جرّب كمية أقل."
    else:
        if left <= 0:
            return f"No inventory for {days}d."
        unit = "key" if left == 1 else "keys"
        return f"Requested quantity not available for {days}d.\nAvailable now: {left} {unit}.\n💡 Try a lower quantity."

def _suggest_qty_kb(lang: str, product: str, method: str, days: int, left: int):
    """
    يبني كيبورد باقتراحات كميات <= المتوفر.
    يستخدم نفس callback المستعمل سابقًا: shop:q:{product}:{method}:{days}:{qty}
    """
    kb = InlineKeyboardBuilder()
    # كميات مقترحة: إن كان المتوفر قليل (<=5) نعرض 1..left
    # وإلا نعرض بعض الخيارات الذكية + زر المتوفر بالضبط
    if left <= 5:
        options = list(range(1, left + 1))
    else:
        half = max(1, left // 2)
        options = sorted({1, half, max(half - 1, 1), left - 1, left})
    for q in options:
        label = (f"{q}×" if not str(lang).startswith("ar") else f"{q}×")
        kb.button(text=label, callback_data=f"shop:q:{product}:{method}:{days}:{q}")
    # رجوع
    back_txt = "رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"
    kb.button(text=back_txt, callback_data=f"shop:p:{product}:{method}:{days}")
    # ترتيب الأزرار
    if left <= 5:
        kb.adjust(min(left, 5), 5, 1)
    else:
        kb.adjust(3, 2, 1)
    return kb.as_markup()

# ========= تأكيد المخزون ثم إنشاء الفاتورة حسب الطريقة =========
@router.callback_query(F.data.startswith("shop:q:"))
async def prepare_invoice(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    lang = _user_lang(cb)
    _, _, product, method, days_s, qty_s = cb.data.split(":")
    days = int(days_s); qty = int(qty_s)

    left = await _count_for_safe(days, product)

    # لا يوجد أي مخزون
    if left <= 0:
        # تنبيه مع زر رجوع للمدة
        try:
            await cb.answer(_not_enough_stock_text(lang, days, left=0), show_alert=True)
        except Exception:
            pass
        try:
            back_txt = "رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"
            ask_txt  = "نفدت الكمية لهذه المدة. اختر مدة أخرى:" if str(lang).startswith("ar") else "Out of stock for this plan. Pick another duration:"
            kb = InlineKeyboardBuilder()
            kb.button(text=back_txt, callback_data=f"shop:pm:{product}:{method}")
            kb.adjust(1)
            try:
                await cb.message.edit_text(ask_txt, reply_markup=kb.as_markup())
            except Exception:
                await cb.message.answer(ask_txt, reply_markup=kb.as_markup())
        except Exception:
            pass
        try:
            await inv.maybe_alert_low_stock(cb.bot, days, product=product)
        except Exception:
            pass
        return

    # كمية مطلوبة أكبر من المتوفر → اقترح كميات أقل
    if qty > left:
        text = _not_enough_stock_text(lang, days, left=left)
        try:
            await cb.answer(text, show_alert=True)
        except Exception:
            pass
        try:
            kb = _suggest_qty_kb(lang, product, method, days, left)
            # إن أمكن عدّل الرسالة الحالية ليشوف الأزرار فورًا
            try:
                await cb.message.edit_text(text, reply_markup=kb)
            except Exception:
                await cb.message.answer(text, reply_markup=kb)
        except Exception:
            pass
        try:
            await inv.maybe_alert_low_stock(cb.bot, days, product=product)
        except Exception:
            pass
        return

    # الكمية مناسبة → تابع إنشاء الفاتورة
    if method == "stars":
        return await _create_stars_invoice(cb, product, days, qty)

    # Crypto: اختيار الأصول عند توافر أكثر من أصل
    if CRYPTO_ENABLED and len(CRYPTO_ASSETS) > 1:
        text = "اختر طريقة الدفع:" if str(lang).startswith("ar") else "Choose a payment asset:"
        kb = InlineKeyboardBuilder()
        for asset in CRYPTO_ASSETS:
            kb.button(text=asset, callback_data=f"shop:a:{product}:{days}:{qty}:{asset}")
        kb.button(text=("رجوع ◀️" if str(lang).startswith("ar") else "Back ◀️"), callback_data=f"shop:p:{product}:crypto:{days}")
        kb.adjust(3, 1)
        try:
            await cb.message.edit_text(text, reply_markup=kb.as_markup())
        except Exception:
            await cb.message.answer(text, reply_markup=kb.as_markup())
        await cb.answer()
        return

    await _create_invoice_crypto(cb, product, days, qty, asset=(DEFAULT_ASSET if CRYPTO_ENABLED else None))

@router.callback_query(F.data.startswith("shop:a:"))
async def create_invoice_with_asset(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    _, _, product, days_s, qty_s, asset = cb.data.split(":")
    await _create_invoice_crypto(cb, product, int(days_s), int(qty_s), asset=asset.upper())

def _invoice_caption(lang, usd_total: float, ton_total: float, qty: int, days: int, asset: str) -> str:
    usd_txt = _fmt_money(usd_total, 2)
    ton_txt = _fmt_money(ton_total, 3)
    if str(lang).startswith("ar"):
        return (
            "تم إنشاء الفاتورة.\n"
            f"السعر: ${usd_txt} ≈ {ton_txt} TON\n"
            f"طريقة الدفع: {asset}\n"
            f"الكمية: {qty}× | الخطة: {days} يوم\n"
            f"⏳ تنتهي خلال {INVOICE_TTL_MIN} دقيقة.\n"
            "💡 السعر يُحدَّث تلقائيًا حسب السوق."
        )
    return (
        "Invoice ready.\n"
        f"Price: ${usd_txt} ≈ {ton_txt} TON\n"
        f"Asset: {asset}\n"
        f"Qty: {qty}× | Plan: {days}d\n"
        f"⏳ Expires in {INVOICE_TTL_MIN} min.\n"
        "💡 Price auto-updates with the market."
    )

# ========= إنشاء فاتورة Crypto =========
async def _create_invoice_crypto(cb: CallbackQuery, product: str, days: int, qty: int, asset: str | None):
    lang = _user_lang(cb)
    usd_total  = _apply_tiers(_prices_usd(product), product)[days] * qty
    ton_equiv  = _usd_to_ton(usd_total)
    expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=INVOICE_TTL_MIN)

    if CRYPTO_ENABLED and asset:
        amount = ton_equiv if asset == "TON" else usd_total
        description = f"{product} | {qty}× keys | {days}d"
        try:
            inv_obj    = await cp.create_invoice(asset=asset, amount=amount, description=description,
                                                 payload=f"user:{cb.from_user.id}", expires_in=INVOICE_TTL_MIN * 60)
            pay_url    = inv_obj.get("pay_url")
            invoice_id = str(inv_obj.get("invoice_id"))

            order = await ords.create_order(
                user_id=cb.from_user.id,
                username=cb.from_user.username or "",
                days=days, qty=qty,
                usd_amount=usd_total, ton_amount=ton_equiv,
                asset=asset, to_address=pay_url or "",
                lang=lang, expires_at=expires_at,
                invoice_hash=invoice_id, product=product,
            )

            kb = InlineKeyboardBuilder()
            if pay_url:
                kb.button(text=("ادفع الآن" if str(lang).startswith("ar") else "Pay Now"), url=pay_url)
            kb.button(text=("تحديث" if str(lang).startswith("ar") else "Refresh"), callback_data=f"shop:r:{order.id}")
            kb.button(text=("إلغاء" if str(lang).startswith("ar") else "Cancel"),  callback_data=f"shop:c:{order.id}")
            kb.adjust(1, 2)

            text = _invoice_caption(lang, usd_total, ton_equiv, qty, days, asset)
            try:
                await cb.message.edit_text(text, reply_markup=kb.as_markup())
            except Exception:
                await cb.message.answer(text, reply_markup=kb.as_markup())
            await cb.answer()
            return
        except Exception as e:
            logging.exception("CryptoPay create_invoice failed: %r", e)
            if CRYPTO_ONLY:
                try:
                    await cb.answer(("⚠️ تعذّر إنشاء الفاتورة. حاول لاحقًا." if str(lang).startswith("ar") else "⚠️ Couldn't create invoice. Try again later."), show_alert=True)
                except Exception:
                    pass
                return

    # فولباك TON اليدوي
    order = await ords.create_order(
        user_id=cb.from_user.id, username=cb.from_user.username or "",
        days=days, qty=qty, usd_amount=usd_total, ton_amount=ton_equiv,
        asset=ASSET_TON, to_address=TON_ADDRESS, lang=lang, expires_at=expires_at, product=product,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=("تحديث" if str(lang).startswith("ar") else "Refresh"), callback_data=f"shop:r:{order.id}")
    kb.button(text=("إلغاء" if str(lang).startswith("ar") else "Cancel"),  callback_data=f"shop:c:{order.id}")
    kb.adjust(2)

    text = _invoice_caption(lang, usd_total, ton_equiv, qty, days, ASSET_TON)
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())
    await cb.answer()

# ========= إنشاء فاتورة نجوم تيليجرام =========
async def _create_stars_invoice(cb: CallbackQuery, product: str, days: int, qty: int):
    lang = _user_lang(cb)
    usd_one   = _apply_tiers(_prices_usd(product), product)[days]
    usd_total = usd_one * qty
    stars_one = _prices_stars(product)[days]
    stars_total = stars_one * qty
    expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=INVOICE_TTL_MIN)

    # نسجّل الطلب أولاً (asset = XTR) — نخزن مبلغ النجوم في ton_amount كحقل عام
    order = await ords.create_order(
        user_id=cb.from_user.id,
        username=cb.from_user.username or "",
        days=days, qty=qty,
        usd_amount=usd_total, ton_amount=float(stars_total),
        asset="XTR", to_address="", lang=lang, expires_at=expires_at,
        product=product,
    )

    # نرسل الفاتورة
    await cb.bot.send_invoice(
        chat_id=cb.from_user.id,
        title=L(lang, "مفاتيح اشتراك", "Subscription keys"),
        description=L(lang, f"{product} • {days} يوم × {qty}", f"{product} • {days}d × {qty}"),
        payload=f"stars:{order.id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{product} {days}d ×{qty}", amount=int(stars_total))],
    )

    # رسالة إدارية تحتها فيها «تحديث/إلغاء»
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_refresh", L(lang, "تحديث", "Refresh")), callback_data=f"shop:r:{order.id}")
    kb.button(text=tr(lang, "btn_cancel",  L(lang, "إلغاء", "Cancel")),  callback_data=f"shop:c:{order.id}")
    kb.adjust(2)

    try:
        await cb.message.edit_text(
            L(lang, "تم إنشاء فاتورة النجوم. بعد الدفع اضغط «تحديث» لو لم يصلك المفتاح.", 
                     "Stars invoice created. After payment tap “Refresh” if the key didn’t arrive."),
            reply_markup=kb.as_markup()
        )
    except Exception:
        await cb.message.answer(
            L(lang, "تم إنشاء فاتورة النجوم. بعد الدفع اضغط «تحديث».", 
                     "Stars invoice created. After payment tap “Refresh”."),
            reply_markup=kb.as_markup()
        )
    await cb.answer()

# ========= زر تحديث/إلغاء =========
@router.callback_query(F.data.startswith("shop:r:"))
async def refresh_status(cb: CallbackQuery):
    lang = _user_lang(cb)
    oid  = int(cb.data.split(":")[-1])

    # حالة الطلب قبل الفحص
    try:
        r0 = await ords.get_by_id(oid)
        pre_status = str(getattr(r0, "status", "") or "")
    except Exception:
        pre_status = ""

    # تحقّق/تسليم بدون أي إرسال تلقائي من هنا
    ok, delivered_text = await check_and_deliver_one(cb.bot, oid, notify_user=False)

    # حالة الطلب بعد الفحص
    try:
        r1 = await ords.get_by_id(oid)
        post_status = str(getattr(r1, "status", "") or "")
        days = int(getattr(r1, "days", 0) or 0)
        qty  = int(getattr(r1, "qty", 0) or 0)
        product = str(getattr(r1, "product", "") or DEFAULT_PRODUCT).lower()
    except Exception:
        r1 = None
        post_status = ""
        days, qty, product = 0, 0, DEFAULT_PRODUCT

    # لو ما زال بانتظار الدفع
    if not ok or post_status not in ("paid", "delivered"):
        await cb.answer(
            "بانتظار الدفع… (سنتحقق تلقائيًا)" if str(lang).startswith("ar") else "Waiting for payment… (auto-checking)"
        )
        return

    # لو كان مُسلَّم مسبقًا → لا ترسل البطاقة مرة ثانية
    if pre_status == "delivered" and post_status == "delivered":
        await cb.answer("تم التأكيد ✅" if str(lang).startswith("ar") else "Confirmed ✅")
        return

    # من هنا: تغيّرت الحالة للتو إلى delivered (أول مرة)
    try:
        confirm_txt = (
            "✅ تم تأكيد الدفع.\nلو واجهت مشكلة استخدم الأمر /report"
            if str(lang).startswith("ar")
            else "✅ Payment confirmed.\nIf you face any issue, use /report"
        )
        # قد تفشل edit_text لو الرسالة ليست قابلة للتعديل؛ نتجاهل بهدوء
        try:
            await cb.message.edit_text(confirm_txt, reply_markup=None)
        except Exception:
            pass
    except Exception:
        pass

    # جهّز المفاتيح المخزّنة داخل delivered_text (بدون إعادة إرسال الفاتورة/الإيصال)
    keys = _extract_keys_from_text(delivered_text or "")
    _DELIVERED_KEYS[oid] = keys

    # أرسل بطاقة الشراء مرة واحدة فقط
    if oid not in _PROFILE_SENT:
        try:
            await _send_profile_block(cb, lang, oid, days, qty, keys, product=product)
        except Exception:
            pass
        _PROFILE_SENT.add(oid)

    await cb.answer("تم التأكيد ✅" if str(lang).startswith("ar") else "Confirmed ✅")



@router.callback_query(F.data.startswith("shop:c:"))
async def cancel_order(cb: CallbackQuery):
    lang = _user_lang(cb)
    oid  = int(cb.data.split(":")[-1])
    await ords.mark_cancelled_if_pending(oid)
    await cb.message.edit_text("تم إلغاء الطلب." if str(lang).startswith("ar") else "Order cancelled.")
    await cb.answer()

# ========= معالجة مدفوعات النجوم =========
@router.pre_checkout_query()
async def pre_checkout(pre: PreCheckoutQuery):
    logging.info("[PAY⭐] pre_checkout payload=%s currency=%s amount=%s",
                 pre.invoice_payload, getattr(pre, "currency", None), getattr(pre, "total_amount", None))
    await pre.answer(ok=True)
    
@router.message(F.successful_payment)
async def on_successful_payment(msg: Message):
    """
    يلتقط نجاح دفع النجوم:
    payload = "stars:<oid>"
    """
    try:
        payload = msg.successful_payment.invoice_payload or ""
    except Exception:
        payload = ""
    if not payload.startswith("stars:"):
        return  # فواتير أخرى إن وُجدت

    try:
        oid = int(payload.split(":", 1)[1])
    except Exception:
        return

    # علّم الطلب مدفوعًا ثم سلّم
    try:
        await ords.mark_paid(oid)
    except Exception:
        pass

    try:
        ok, _ = await check_and_deliver_one(msg.bot, oid, notify_user=True)
        if ok:
            await msg.answer("✅ تم الدفع بنجاح. تم إرسال مفاتيحك." if str(_user_lang(msg)).startswith("ar") else "✅ Payment received. Your keys have been sent.")
        else:
            await msg.answer("تم الدفع. سنسلم قريبًا." if str(_user_lang(msg)).startswith("ar") else "Paid. We will deliver shortly.")
    except Exception as e:
        logging.exception("deliver after stars payment failed: %r", e)

# ================= بطاقة الشراء =================
async def _profile_kb(cb: CallbackQuery, lang: str, oid: int, product: str):
    app, guide, tut = _product_links(product)
    kb = InlineKeyboardBuilder()
    if tut:
        kb.button(text=("🎥 شرح بالفيديو" if str(lang).startswith("ar") else "🎥 Video tutorial"), callback_data=f"shop:tutorial:{oid}")
    if guide:
        kb.button(text=("📘 شرح التفعيل" if str(lang).startswith("ar") else "📘 Activation Guide"), url=guide)
    if app:
        kb.button(text=("📦 تحميل التطبيق" if str(lang).startswith("ar") else "📦 Download App"), url=app)

    kb.button(text=("💾 حفظ المفاتيح" if str(lang).startswith("ar") else "💾 Save keys"), callback_data=f"shop:save:{oid}")
    kb.button(text=("ℹ️ طريقة التفعيل" if str(lang).startswith("ar") else "ℹ️ How to activate"), callback_data=f"shop:howto:{oid}")

    if tut or guide or app:
        kb.adjust(3, 2)
    else:
        kb.adjust(2)
    return kb.as_markup()

def _profile_card_html(lang: str, days: int, qty: int, keys: List[str], product: str) -> str:
    product_disp = _product_label(lang, product) 
    title = "🧾 بطاقة الشراء" if str(lang).startswith("ar") else "🧾 Purchase Card"
    head  = (f"• المنتج: {product}\n• الخطة: {days} يوم\n• الكمية: {qty}×") if str(lang).startswith("ar") else (f"• Product: {product}\n• Plan: {days}d\n• Qty: {qty}×")
    ks    = "\n".join(f"• {_code(k)}" for k in keys) if keys else ("— لا مفاتيح —" if str(lang).startswith("ar") else "— No keys —")
    tip   = "ℹ️ للتفعيل: افتح التطبيق المناسب لمنتجك ثم أدخل المفتاح كما هو موضح في الشرح." if str(lang).startswith("ar") else "ℹ️ Activate: open the proper app for your product and enter the key as shown in the guide."
    return f"{title}\n{head}\n\n{'🔑 المفاتيح:' if str(lang).startswith('ar') else '🔑 Keys:'}\n{ks}\n\n{tip}"

async def _send_profile_block(cb_or_like, lang: str, oid: int, days: int, qty: int, keys: List[str], product: str):
    card = _profile_card_html(lang, days, qty, keys, product)
    msg_obj = getattr(cb_or_like, "message", cb_or_like)
    kb = None
    try:
        if hasattr(cb_or_like, "message"):
            kb = await _profile_kb(cb_or_like, lang, oid, product)
    except Exception:
        kb = None

    try:
        await msg_obj.answer(card, parse_mode=ParseMode.HTML, reply_markup=kb)
    except TelegramBadRequest:
        import re as _re
        plain = _re.sub(r"<[^>]+>", "", card)
        await msg_obj.answer(plain, reply_markup=kb)
    except Exception:
        try:
            await msg_obj.answer(card, parse_mode=ParseMode.HTML)
        except Exception:
            pass

_DELIVERED_KEYS: Dict[int, List[str]] = {}
_PROFILE_SENT: set[int] = set()

def _extract_keys_from_text(text: str) -> List[str]:
    import re as _re
    keys: List[str] = []
    for m in _re.finditer(r"<code>([^<]+)</code>", text or ""):
        keys.append(m.group(1).strip())
    for m in _re.finditer(r"-\s*`([^`]+)`", text or ""):
        keys.append(m.group(1).strip())
    for m in _re.finditer(r"(?m)^\s*[-•]\s*([A-Za-z0-9_\-:]{6,})\s*$", text or ""):
        keys.append(m.group(1).strip())
    seen=set(); out=[]
    for k in keys:
        if k and k not in seen:
            seen.add(k); out.append(k)
    return out

@router.callback_query(F.data.startswith("shop:howto:"))
async def send_howto(cb: CallbackQuery):
    lang = _user_lang(cb)
    try:
        oid = int(cb.data.split(":")[-1])
        r = await ords.get_by_id(oid)
        product = str(getattr(r, "product", "") or DEFAULT_PRODUCT).lower()
    except Exception:
        product = DEFAULT_PRODUCT
    try:
        await _send_activation_help(cb.bot, cb.from_user.id, lang, product, oid)
        await cb.answer("أرسلت لك خطوات التفعيل." if str(lang).startswith("ar") else "Sent you the activation steps.")
    except Exception:
        await cb.answer("تعذّر إرسال الخطوات الآن." if str(lang).startswith("ar") else "Couldn't send the steps now.", show_alert=True)

@router.callback_query(F.data.startswith("shop:tutorial:"))
async def send_tutorial(cb: CallbackQuery):
    lang = _user_lang(cb)
    try:
        oid = int(cb.data.split(":")[-1])
        r = await ords.get_by_id(oid)
        product = str(getattr(r, "product", "") or DEFAULT_PRODUCT).lower()
    except Exception:
        product = DEFAULT_PRODUCT

    _app, _guide, tut = _product_links(product)
    if not tut:
        await cb.answer("فيديو الشرح غير متاح حاليًا." if str(lang).startswith("ar") else "Tutorial video not available.", show_alert=True)
        return
    try:
        await cb.message.answer_video(
            tut,
            caption=("شرح سريع لتفعيل المفتاح." if str(lang).startswith("ar") else "Quick guide to activate your key."),
            parse_mode=ParseMode.HTML
        )
        await cb.answer()
    except Exception as e:
        logging.exception("send tutorial failed: %r", e)
        await cb.answer("تعذّر إرسال الفيديو الآن." if str(lang).startswith("ar") else "Couldn't send the video now.", show_alert=True)

@router.callback_query(F.data.startswith("shop:save:"))
async def save_keys_file(cb: CallbackQuery):
    lang = _user_lang(cb)
    try:
        oid = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer("معرّف غير صالح." if str(lang).startswith("ar") else "Invalid id.", show_alert=True)

    keys = _DELIVERED_KEYS.get(oid) or []
    if not keys:
        try:
            r = await ords.get_by_id(oid)
            delivered_text = (
                getattr(r, "delivered_text", None)
                or getattr(r, "delivery_text", None)
                or getattr(r, "text", None)
                or ""
            )
            keys = _extract_keys_from_text(delivered_text)
        except Exception:
            keys = []

    if not keys:
        return await cb.answer(
            "لم أجد المفاتيح لهذه العملية (ربما انتهت الجلسة)." if str(lang).startswith("ar") else "Couldn't find keys for this order (session may have reset).",
            show_alert=True
        )

    txt = "\n".join(keys) + "\n"
    data = txt.encode("utf-8")
    try:
        await cb.message.answer_document(
            BufferedInputFile(data, filename=f"keys-{oid}.txt"),
            caption=("تم إنشاء ملف المفاتيح. احفظه لديك." if str(lang).startswith("ar") else "Keys file generated. Save it safely.")
        )
        await cb.answer()
    except Exception:
        await cb.answer("تعذّر إرسال الملف." if str(lang).startswith("ar") else "Couldn't send the file.", show_alert=True)

# ========= أوامر إدمن: الأسعار =========
@router.message(Command("prices"))
async def prices_cmd(msg: Message):
    lang = _user_lang(msg)

    def line_usd(prod: str) -> List[str]:
        p = _apply_tiers(_prices_usd(prod), prod)
        return [
            ("الأسعار USD ({prod}):".format(prod=prod) if str(lang).startswith("ar") else f"Prices USD ({prod}):"),
            f"• 3d: ${_fmt_money(p[3], 2)}",
            f"• 10d: ${_fmt_money(p[10], 2)}",
            f"• 30d: ${_fmt_money(p[30], 2)}"
        ]

    def line_stars(prod: str) -> List[str]:
        p = _prices_stars(prod)
        return [
            ("الأسعار ⭐ ({prod}):".format(prod=prod) if str(lang).startswith("ar") else f"Prices ⭐ ({prod}):"),
            f"• 3d: {p[3]}⭐",
            f"• 10d: {p[10]}⭐",
            f"• 30d: {p[30]}⭐"
        ]

    lines = []
    for prod in PRODUCTS:
        lines += line_usd(prod) + line_stars(prod) + [""]

    if _is_admin(msg.from_user.id):
        if str(lang).startswith("ar"):
            instr = (
                "<b>أوامر التعديل:</b>\n"
                f"{_code('/set_price <days> <usd>')} (افتراضي)\n"
                f"{_code('/set_price <product> <days> <usd>')} (لكل منتج)\n"
                f"{_code('/set_prices 3=4.99 10=12.5 30=25')} (افتراضي)\n"
                f"{_code('/set_prices carrom:3=5 8bp:10=3.5')} (لكل منتج)\n"
                f"{_code('/set_star_price <days> <stars>')} أو {_code('/set_star_price <product> <days> <stars>')}\n"
                f"{_code('/set_star_prices 3=150 10=350 30=750')} أو {_code('/set_star_prices carrom:3=160 8bp:10=330')}"
            )
        else:
            instr = (
                "<b>Admin:</b>\n"
                f"{_code('/set_price <days> <usd>')} (default)\n"
                f"{_code('/set_price <product> <days> <usd>')} (per product)\n"
                f"{_code('/set_prices 3=4.99 10=12.5 30=25')} (default)\n"
                f"{_code('/set_prices carrom:3=5 8bp:10=3.5')} (per product)\n"
                f"{_code('/set_star_price <days> <stars>')} or {_code('/set_star_price <product> <days> <stars>')}\n"
                f"{_code('/set_star_prices 3=150 10=350 30=750')} or {_code('/set_star_prices carrom:3=160 8bp:10=330')}"
            )
        lines += [instr]

    await msg.reply("\n".join(lines).rstrip(), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@router.message(Command("set_price"))
async def set_price_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _user_lang(msg)
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
        txt = ( "الاستخدام: " + _code("/set_price <days> <usd>") + " أو " + _code("/set_price <product> <days> <usd>") ) if str(lang).startswith("ar") \
              else ( "Usage: " + _code("/set_price <days> <usd>") + " or " + _code("/set_price <product> <days> <usd>") )
        return await msg.reply(txt, parse_mode=ParseMode.HTML)

    mp = _load_prices_map()
    mp.setdefault(prod, {})
    mp[prod][d] = val
    _save_prices_map(mp)
    target = "الافتراضي" if str(lang).startswith("ar") and prod == "default" else (prod if prod != "default" else "default")
    await msg.reply(("تم ضبط سعر {d} يوم ({t}) إلى ${v}.".format(d=d, t=target, v=_fmt_money(val, 2))
                     if str(lang).startswith("ar") else f"Set price {d}d ({target}) to ${_fmt_money(val, 2)}."))

@router.message(Command("set_prices"))
async def set_prices_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _user_lang(msg)
    parts = (msg.text or "").split()[1:]
    if not parts:
        txt = ("استخدم: " + _code("/set_prices 3=4.99 10=12.5 30=25") + " أو " + _code("/set_prices carrom:3=5 8bp:10=3.5")) if str(lang).startswith("ar") \
              else ("Usage: " + _code("/set_prices 3=4.99 10=12.5 30=25") + " or " + _code("/set_prices carrom:3=5 8bp:10=3.5"))
        return await msg.reply(txt, parse_mode=ParseMode.HTML)
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
                    changed.append(f"{prod}:{d}d=${_fmt_money(val, 2)}")
            else:
                days_s, val_s = part.split("=", 1)
                d = int(days_s); val = float(val_s)
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault("default", {})[d] = val
                    changed.append(f"default:{d}d=${_fmt_money(val, 2)}")
        except Exception:
            continue
    _save_prices_map(mp)
    if changed:
        await msg.reply(("تم التحديث: " if str(lang).startswith("ar") else "Updated: ") + ", ".join(changed))
    else:
        await msg.reply("لم يتم تحديث أي سعر." if str(lang).startswith("ar") else "No prices updated.")

# ====== أوامر إدمن: أسعار النجوم ======
@router.message(Command("set_star_price"))
async def set_star_price_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _user_lang(msg)
    parts = (msg.text or "").split()
    try:
        if len(parts) == 3:
            prod = "default"; d = int(parts[1]); val = int(parts[2])
        elif len(parts) == 4:
            prod = parts[1].lower(); d = int(parts[2]); val = int(parts[3])
        else:
            raise ValueError
        if d not in (3, 10, 30) or val <= 0:
            raise ValueError
    except Exception:
        txt = ( "الاستخدام: " + _code("/set_star_price <days> <stars>") + " أو " + _code("/set_star_price <product> <days> <stars>") ) if str(lang).startswith("ar") \
              else ( "Usage: " + _code("/set_star_price <days> <stars>") + " or " + _code("/set_star_price <product> <days> <stars>") )
        return await msg.reply(txt, parse_mode=ParseMode.HTML)

    mp = _load_stars_map()
    mp.setdefault(prod, {})
    mp[prod][d] = val
    _save_stars_map(mp)
    target = "الافتراضي" if str(lang).startswith("ar") and prod == "default" else (prod if prod != "default" else "default")
    await msg.reply(("تم ضبط سعر {d} يوم ({t}) إلى ⭐{v}.".format(d=d, t=target, v=val)
                     if str(lang).startswith("ar") else f"Set Stars price {d}d ({target}) to ⭐{val}."))

@router.message(Command("set_star_prices"))
async def set_star_prices_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _user_lang(msg)
    parts = (msg.text or "").split()[1:]
    if not parts:
        txt = ("استخدم: " + _code("/set_star_prices 3=150 10=350 30=750") + " أو " + _code("/set_star_prices carrom:3=160 8bp:10=330")) if str(lang).startswith("ar") \
              else ("Usage: " + _code("/set_star_prices 3=150 10=350 30=750") + " or " + _code("/set_star_prices carrom:3=160 8bp:10=330"))
        return await msg.reply(txt, parse_mode=ParseMode.HTML)

    mp = _load_stars_map(); changed = []
    for part in parts:
        try:
            if ":" in part.split("=", 1)[0]:
                prod_days, val_s = part.split("=", 1)
                prod, days_s = prod_days.split(":", 1)
                prod = prod.lower().strip()
                d = int(days_s); val = int(val_s)
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault(prod, {})[d] = val
                    changed.append(f"{prod}:{d}d=⭐{val}")
            else:
                days_s, val_s = part.split("=", 1)
                d = int(days_s); val = int(val_s)
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault("default", {})[d] = val
                    changed.append(f"default:{d}d=⭐{val}")
        except Exception:
            continue

    _save_stars_map(mp)
    if changed:
        await msg.reply(("تم التحديث: " if str(lang).startswith("ar") else "Updated: ") + ", ".join(changed))
    else:
        await msg.reply("لم يتم تحديث أي سعر." if str(lang).startswith("ar") else "No prices updated.")
