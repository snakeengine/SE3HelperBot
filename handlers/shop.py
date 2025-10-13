from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/shop.py


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

# ... Ø¨Ø¹Ø¯ try/import Ù„Ø·Ø±Ù‚ Ø§Ù„Ø¯ÙØ¹
try:
    from services.payments import is_product_enabled as _p_is_prod_enabled
    def _is_product_enabled(product: str) -> bool:
        return bool(_p_is_prod_enabled(product))
except Exception:
    def _is_product_enabled(product: str) -> bool:
        # Ù„Ùˆ Ù…Ø§ ØªÙˆÙØ±Øª Ø§Ù„Ø¯Ø§Ù„Ø©ØŒ Ø§Ø¹ØªØ¨Ø±Ù‡ Ù…ÙØ¹Ù‘Ù„
        return True

# --- Pay modes per product (admin toggles) ---
try:
    from services.payments import (
        is_stars_enabled_for as _p_is_stars_ok,
        is_crypto_enabled_for as _p_is_crypto_ok,
    )
    def _is_stars_ok(product: str) -> bool:  # Ø¹Ø¨Ø± services.payments
        return bool(_p_is_stars_ok(product))
    def _is_crypto_ok(product: str) -> bool:
        return bool(_p_is_crypto_ok(product))
except Exception:
    # ÙÙˆÙ„Ø¨Ø§Ùƒ: Ù†Ù‚Ø±Ø£ Ù…Ù† FLAGS_PATH -> { "pay_modes": { "default": {"stars": true, "crypto": true}, "<prod>": {...} } }
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

# === Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª (Ø¯ÙŠÙ†Ø§Ù…ÙŠÙƒÙŠØ©) ===
DEFAULT_PRODUCT = (os.getenv("PRODUCT_KEY", "8bp") or "8bp").lower().strip()
PRODUCTS = [p.strip().lower() for p in (os.getenv("SHOP_PRODUCTS", "8bp,carrom,soccer").split(","))]
# Ø¥Ø²Ø§Ù„Ø© Ø§Ù„ÙØ§Ø±Øº ÙˆØ§Ù„Ù…ÙƒØ±Ù‘Ø±
PRODUCTS = list(dict.fromkeys([p for p in PRODUCTS if p])) or ["8bp", "carrom", "soccer"]


# Ù…Ù†Ø¹ Ø§Ù„ØªÙƒØ±Ø§Ø± Ø¨Ø¹Ø¯ Ø§Ù„ØªØ£ÙƒÙŠØ¯/Ø§Ù„ØªØ³Ù„ÙŠÙ…
_CONFIRMED_SHOWN: set[int] = set()
_DELIVERED_POSTED: set[int] = set()

def _code(txt: str) -> str:
    return f"<code>{h(str(txt))}</code>"

# ========= Ù…Ù„ÙØ§Øª ØØ§Ù„Ø©/Ø¥Ø¹Ø¯Ø§Ø¯ =========
FLAGS_PATH   = BASE / "shop_flags.json"
SHOP_CFG     = BASE / "shop_config.json"
PRICES_PATH  = BASE / "shop_prices.json"        # Ø£Ø³Ø¹Ø§Ø± USD (Ù…ØªØ¹Ø¯Ø¯Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª)
STARS_PRICES = BASE / "shop_stars.json"      # Ø£Ø³Ø¹Ø§Ø± Ø§Ù„Ù†Ø¬ÙˆÙ… (Ù…ØªØ¹Ø¯Ø¯Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª)
TIERS_PATH   = BASE / "vip_tiers.json"          # (Ø§Ø®ØªÙŠØ§Ø±ÙŠ) Ø¥Ù‡Ù…Ø§Ù„Ù‡ Ø¥Ù† Ù„Ù… ÙŠÙˆØ¬Ø¯

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

# ========= Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø¹Ø§Ù…Ø© =========
TON_USD_RATE      = float(os.getenv("TON_USD_RATE", "6.0"))
INVOICE_TTL_MIN   = int(os.getenv("INVOICE_TTL_MIN", "15"))
ENABLE_STARS      = int(os.getenv("ENABLE_STARS", "0")) == 1

# Ø±ÙˆØ§Ø¨Ø·/Ø£Ø¯Ù„Ø© Ø¹Ø§Ù…Ø© (fallback)
APP_DOWNLOAD_URL_DEFAULT     = os.getenv("APP_DOWNLOAD_URL", "")
ACTIVATION_GUIDE_URL_DEFAULT = os.getenv("ACTIVATION_GUIDE_URL", "")
TUTORIAL_URL_DEFAULT         = os.getenv("TUTORIAL_URL", "") or os.getenv("TUTORIAL_FILE_ID", "")

# Ø±ÙˆØ§Ø¨Ø·/Ø£Ø¯Ù„Ø© Ù„ÙƒÙ„ Ù…Ù†ØªØ¬ (Ø¥Ù† ÙˆÙØ¬Ø¯Øª)
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

ADMIN_IDS = get_admin_ids()
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ========= Ù†ØµÙˆØµ/Ù„ØºØ© =========
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

# ====== Ø£Ø³Ø¹Ø§Ø± USD (fallback) ======
DEFAULT_PRICES_FLAT = {
    3:  float(os.getenv("PRICE_USD_3", PRICE_USD_3)),
    10: float(os.getenv("PRICE_USD_10", PRICE_USD_10)),
    30: float(os.getenv("PRICE_USD_30", PRICE_USD_30)),
}

# ====== Ù‚Ø±Ø§Ø¡Ø©/ÙƒØªØ§Ø¨Ø© Ø£Ø³Ø¹Ø§Ø± USD (Ù…ØªØ¹Ø¯Ø¯Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª) ======
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

# ØªÙˆØ§ÙÙ‚ Ù…Ø¹ ÙƒÙˆØ¯ Ø§Ù„Ø¥Ø¯Ù…Ù†
def _jload(p: Path) -> dict: 
    return _load_json(p)

def _jsave(p: Path, d: dict):
    _save_json(p, d)

# ====== Ø£Ø³Ø¹Ø§Ø± Ø§Ù„Ù†Ø¬ÙˆÙ… ======
def _stars_per_usd_from_env() -> float:
    """
    STARS_PER_USD = Ù†Ø¬ÙˆÙ… Ù„ÙƒÙ„ 1$
    Ø£Ùˆ USD_PER_STAR = Ø³Ø¹Ø± Ø§Ù„Ù†Ø¬Ù…Ø© Ø¨Ø§Ù„Ø¯ÙˆÙ„Ø§Ø± (Ù†ØÙˆÙ‘Ù„ ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§)
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
        return {}  # Ù…Ø§ÙÙŠØ´ Ù…Ù„Ù â†’ Ù‡Ù†Ø´ØªÙ‚ Ù…Ù† USD
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
    ÙŠØ±Ø¬Ù‘Ø¹ Ø£Ø³Ø¹Ø§Ø± Ø§Ù„Ù†Ø¬ÙˆÙ… Ù„Ù„Ù…Ù†ØªØ¬.
    Ø¥Ù† Ù„Ù… ÙŠÙƒÙ† Ù‡Ù†Ø§Ùƒ Ù…Ù„Ù/Ø³Ø¹Ø± Ù…ØØ¯Ù‘Ø¯ â†’ ÙŠØÙˆÙ‘Ù„ Ù…Ù† USD Ø¨Ø§Ø³ØªØ®Ø¯Ø§Ù… STARS_PER_USD.
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

# ====== tiers (Ø§Ø®ØªÙŠØ§Ø±ÙŠ) Ù„Ø£Ø³Ø¹Ø§Ø± USD ÙÙ‚Ø· ======
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

# ========= Ù†Øµ Ø·Ø±ÙŠÙ‚Ø© Ø§Ù„ØªÙØ¹ÙŠÙ„ =========
AR_ACTIVATION_STEPS = (
    "ðŸ” Ø·Ø±ÙŠÙ‚Ø© ØªÙØ¹ÙŠÙ„ Ø§Ù„Ù…ÙØªØ§Ø\n"
    "â€¢ Ø¨Ø¹Ø¯ Ø§Ø³ØªÙ„Ø§Ù… Ø§Ù„Ù…ÙØªØ§ØØŒ Ø§ÙØªØ ØªØ·Ø¨ÙŠÙ‚ Ù…ØØ±Ùƒ Ø§Ù„Ø«Ø¹Ø¨Ø§Ù†.\n"
    "â€¢ Ù…Ù† Ø§Ù„Ø²Ø§ÙˆÙŠØ© Ø§Ù„Ø¹Ù„ÙˆÙŠØ© (ÙŠÙ…ÙŠÙ†/ÙŠØ³Ø§Ø±) Ø§Ø¶ØºØ· Ø¹Ù„Ù‰ Ù…Ø¹Ø±Ù‘Ù Ø§Ù„ØªØ·Ø¨ÙŠÙ‚.\n"
    "â€¢ ÙÙŠ Ø£Ø³ÙÙ„ Ø§Ù„Ø´Ø§Ø´Ø© Ø§Ø¶ØºØ· Ø²Ø± Entry Key.\n"
    "â€¢ Ø§Ù†Ø³Ø® Ù…ÙØªØ§Ø Ø§Ù„Ø§Ø´ØªØ±Ø§Ùƒ Ø§Ù„Ø°ÙŠ ÙˆØµÙ„Ùƒ Ù‡Ù†Ø§ØŒ Ø«Ù… Ø§Ù„ØµÙ‚Ù‡ ÙˆØ§Ø¶ØºØ· Activate.\n"
    "â€¢ Ø§Ù„Ù…ÙØªØ§Ø ÙŠÙÙØ¹Ù‘ÙŽÙ„ Ù…Ø±Ø© ÙˆØ§ØØ¯Ø© ÙÙ‚Ø·Ø› Ø¥Ù† ØØ§ÙˆÙ„Øª Ø§Ø³ØªØ®Ø¯Ø§Ù…Ù‡ Ø«Ø§Ù†ÙŠØ© Ø³ÙŠØ¸Ù‡Ø± â€œÙ…Ø³ØªØ®Ø¯Ù…â€.\n"
    "â€¢ ÙŠÙ…ÙƒÙ†Ùƒ ØªÙØ¹ÙŠÙ„ Ø§Ù„Ù…ÙØªØ§Ø ÙÙŠ Ø£ÙŠ ÙˆÙ‚ØªØ› Ø§Ù„ÙˆÙ‚Øª Ù„Ø§ ÙŠØ¨Ø¯Ø£ Ø¥Ù„Ø§ Ø¨Ø¹Ø¯ Ø§Ù„ØªÙØ¹ÙŠÙ„."
)

EN_ACTIVATION_STEPS = (
    "ðŸ” How to activate your key\n"
    "â€¢ After you receive the key, open the Snake Engine app.\n"
    "â€¢ From the top corner (right/left), tap the App ID.\n"
    "â€¢ At the bottom of the screen, tap the Entry Key button.\n"
    "â€¢ Copy the subscription key you received here, paste it, then tap Activate.\n"
    "â€¢ Each key can be activated once; if you try again it will show as â€œUsedâ€.\n"
    "â€¢ You can activate the key any time; time starts only after activation."
)

def activation_text(lang: str) -> str:
    return AR_ACTIVATION_STEPS if str(lang).startswith("ar") else EN_ACTIVATION_STEPS

def _activation_kb(lang: str, product: str, oid: int | None = None):
    app, guide, tut = _product_links(product)
    kb = InlineKeyboardBuilder()
    added = 0
    if tut:
        cb = f"shop:tutorial:{oid}" if oid else f"shop:tutorial:0"
        kb.button(text=L(lang, "ðŸŽ¥ Ø´Ø±Ø Ø¨Ø§Ù„ÙÙŠØ¯ÙŠÙˆ", "ðŸŽ¥ Video tutorial"), callback_data=cb); added += 1
    if app:
        kb.button(text="ðŸ“¦ ØªØÙ…ÙŠÙ„ Ø§Ù„ØªØ·Ø¨ÙŠÙ‚" if str(lang).startswith("ar") else "ðŸ“¦ Download App", url=app); added += 1
    if guide:
        kb.button(text="ðŸ“˜ Ø´Ø±Ø Ø§Ù„ØªÙØ¹ÙŠÙ„" if str(lang).startswith("ar") else "ðŸ“˜ Activation Guide", url=guide); added += 1
    if added == 0:
        return None
    kb.adjust(1)
    return kb.as_markup()

async def _send_activation_help(bot, user_id: int, lang: str, product: str, oid: int | None = None):
    txt = activation_text(lang)
    kb = _activation_kb(lang, product, oid=oid)
    await bot.send_message(user_id, txt, parse_mode=ParseMode.HTML, reply_markup=kb)

# ========= Ø¥ÙŠÙ‚Ø§Ù Ø§Ù„Ø®Ø¯Ù…Ø© =========
def _service_paused_text(lang: str) -> str:
    return _stop_message() or ("â¸ï¸ Ø®Ø¯Ù…Ø© Ø§Ù„Ù…ÙØ§ØªÙŠØ Ù…ØªÙˆÙ‚ÙØ© Ù…Ø¤Ù‚ØªÙ‹Ø§ Ù„Ù„ØµÙŠØ§Ù†Ø©." if str(lang).startswith("ar") else "â¸ï¸ Keys store is temporarily paused for maintenance.")

def _paused_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="ØªØØ¯ÙŠØ«" if str(lang).startswith("ar") else "Refresh", callback_data="shop:home")
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

# ========= ÙˆØ§Ø¬Ù‡Ø© Ø§Ù„Ù…ØªØ¬Ø± =========
def _shop_home_text(lang: str, discount_rate: float = 0.30) -> str:
    """
    ÙŠØ¹Ø±Ø¶ ÙÙ‚Ø±Ø© Ù…ØªØ¬Ø± Ø§Ù„Ù…ÙØ§ØªÙŠØ Ù…Ø¹ Ø³Ø·Ø± Ø®ØµÙ… Ù„ØºÙˆÙŠ.
    ÙŠÙ…ÙƒÙ† ØªØºÙŠÙŠØ± Ù†Ø³Ø¨Ø© Ø§Ù„Ø®ØµÙ… Ø¹Ø¨Ø± discount_rate (Ù…Ø«Ù„Ø§Ù‹ 0.25 = 25%).
    """
    is_ar = str(lang).startswith("ar")
    pct = int(round(discount_rate * 100))

    title = "Ù…ØªØ¬Ø± Ø§Ù„Ù…ÙØ§ØªÙŠØ" if is_ar else "Key Store"

    if is_ar:
        lines = [
            f"ðŸŽ‰ Ø®ØµÙ… {pct}Ùª Ø¹Ù„Ù‰ Ø§Ù„Ø£Ø³Ø¹Ø§Ø± Ø§Ù„ÙŠÙˆÙ…! ÙŠÙØ·Ø¨Ù‘ÙŽÙ‚ ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§ Ø¹Ù†Ø¯ Ø§Ù„Ø¯ÙØ¹.",
            "Ø§Ø®ØªØ± Ø§Ù„Ù…Ù†ØªØ¬ Ø«Ù… Ø·Ø±ÙŠÙ‚Ø© Ø§Ù„Ø¯ÙØ¹ ÙˆØ§Ù„Ù…Ø¯Ø© â€” ÙƒÙ„Ù‡Ø§ Ø¯Ø§Ø®Ù„ ØªÙŠÙ„ÙŠØ¬Ø±Ø§Ù….",
            "ðŸ’³ Ø·Ø±Ù‚ Ø§Ù„Ø¯ÙØ¹ Ø§Ù„Ù…ØªØ§ØØ©: " +
            ("Crypto Pay: " + ", ".join(CRYPTO_ASSETS) if CRYPTO_ENABLED else "TON transfer")
            + (" â€¢ âï¸ Ù†Ø¬ÙˆÙ… ØªÙŠÙ„ÙŠØ¬Ø±Ø§Ù…" if ENABLE_STARS else ""),
            "âš¡ï¸ Ø§Ù„ØªØ³Ù„ÙŠÙ… ÙÙˆØ±ÙŠ Ø¨Ø¹Ø¯ Ø§Ù„Ø¯ÙØ¹: ÙŠØµÙ„Ùƒ Ø§Ù„Ù…ÙØªØ§Ø Ù‡Ù†Ø§ Ù…Ø¹ Ø¨Ø·Ø§Ù‚Ø© Ø§Ù„Ø´Ø±Ø§Ø¡.",
            "Ù…Ù„Ø§ØØ¸Ø©: Ø·Ø±Ù‚ Ø§Ù„Ø¯ÙØ¹ Ù‚Ø¯ ØªØ®ØªÙ„Ù ØØ³Ø¨ Ø§Ù„Ù…Ù†ØªØ¬."
        ]
    else:
        lines = [
            f"ðŸŽ‰ {pct}% off today! Applied automatically at checkout.",
            "Pick a product, then payment method & duration â€” all inside Telegram.",
            "ðŸ’³ Payments: " +
            ("Crypto Pay: " + ", ".join(CRYPTO_ASSETS) if CRYPTO_ENABLED else "TON transfer")
            + (" â€¢ â Telegram Stars" if ENABLE_STARS else ""),
            "âš¡ï¸ Instant delivery: key + purchase card here.",
            "Note: available methods may vary per product."
        ]

    return f"{title}\n" + "\n".join(lines)


def _shop_home_kb(lang: str):
    kb = InlineKeyboardBuilder()
    for p in PRODUCTS:
        kb.button(text=_product_label(lang, p), callback_data=f"shop:g:{p}")
    kb.button(
        text=("â¬…ï¸ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ©" if str(lang).startswith("ar") else "â¬…ï¸ Main menu"),
        callback_data="shop:menu"     # Ù‡Ø°Ø§ ÙŠØ®Ø±Ø¬ Ù„Ù„Ù€ Hero
    )
    kb.adjust(1)
    return kb.as_markup()



def _product_label(lang: str, product: str) -> str:
    product = (product or "").lower().strip()
    fallback = {
        "8bp":    L(lang, "ðŸŽ± 8Ball Pool", "ðŸŽ± 8Ball Pool"),
        "carrom": L(lang, "ðŸŸ¢ Carrom Pool", "ðŸŸ¢ Carrom Pool"),
        "soccer": L(lang, "âš½ Soccer Stars: Football Kick", "âš½ Soccer Stars: Football Kick"),
    }.get(product, product)
    return tr(lang, f"shop.games.{product}", fallback)


# ========= Ø¯Ø®ÙˆÙ„/Ø¹ÙˆØ¯Ø© =========
@router.message(Command("shop"))
async def shop_entry(msg: Message):
    if not await _ensure_service_available(msg): return
    lang = _user_lang(msg)
    await msg.answer(_shop_home_text(lang), reply_markup=_shop_home_kb(lang))

# ÙØªØ ÙˆØ§Ø¬Ù‡Ø© Ø§Ù„Ù…ØªØ¬Ø± (Ù…Ù† /shop Ø£Ùˆ Ù…Ù† Ø²Ø± Ø´Ø±Ø§Ø¡/ÙØªØ Ø§Ù„Ù…ØªØ¬Ø±)
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

# Ø§Ù„Ø®Ø±ÙˆØ¬ Ø¥Ù„Ù‰ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ© (Hero)
@router.callback_query(F.data == "shop:menu")
async def shop_to_main(cb: CallbackQuery, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass

    # Ø®Ø° Ù„ØºØ© Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… (Ù…ØÙÙˆØ¸Ø© Ø¥Ù† ÙˆØ¬Ø¯ØªØŒ ÙˆØ¥Ù„Ø§ Ù…Ù† Telegram)
    lang = _user_lang(cb)   # "ar" Ø£Ùˆ "en"

    # Ø£Ø¹Ø±Ø¶ Ø¨Ø·Ø§Ù‚Ø© Ø§Ù„Ø¨Ø¯Ø§ÙŠØ© Ø¨Ù†ÙØ³ Ø§Ù„Ù„ØºØ©
    await render_home_card(cb.message, lang=lang)
    await cb.answer()
# ========= Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ù…Ù†ØªØ¬ Ø«Ù… Ø·Ø±ÙŠÙ‚Ø© Ø§Ù„Ø¯ÙØ¹ =========
def _pay_methods_for(product: str) -> List[str]:
    """
    ØªÙØ±Ø¬Ø¹ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø·Ø±Ù‚ Ø§Ù„Ù…Ø³Ù…ÙˆØØ© Ù„Ù‡Ø°Ø§ Ø§Ù„Ù…Ù†ØªØ¬ Ø¨Ø¹Ø¯ Ø§Ù„ØªÙ‚Ø§Ø·Ø¹ Ø¨ÙŠÙ†:
    - Ø§Ù„ØªÙØ¹ÙŠÙ„ Ø§Ù„Ø¹Ø§Ù„Ù…ÙŠ (ENABLE_STARS / CRYPTO_ENABLED Ø£Ùˆ TON_ADDRESS)
    - Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø§Ù„Ø¥Ø¯Ù…Ù† Ù„ÙƒÙ„ Ù…Ù†ØªØ¬ (pay_modes)
    - Ø£ÙŠ ØªÙ‚ÙŠÙŠØ¯ Ø¹Ø¨Ø± Ù…ØªØºÙŠØ± Ø¨ÙŠØ¦Ø© Ù…Ø«Ù„ 8BP_PAY=stars,crypto Ø£Ùˆ SOCCER_PAY=stars
    """
    product = (product or "").lower().strip()

    # Ø§Ù„ØØ§Ù„Ø© Ø§Ù„Ø¹Ø§Ù„Ù…ÙŠØ©
    allow_stars_global  = bool(ENABLE_STARS)
    allow_crypto_global = bool(CRYPTO_ENABLED or TON_ADDRESS)

    # ØØ§Ù„Ø© Ø§Ù„Ø¥Ø¯Ù…Ù† Ù„ÙƒÙ„ Ù…Ù†ØªØ¬
    allow_stars_admin   = _is_stars_ok(product)
    allow_crypto_admin  = _is_crypto_ok(product)

    allow_stars  = allow_stars_global  and allow_stars_admin
    allow_crypto = allow_crypto_global and allow_crypto_admin

    methods: List[str] = []

    # ØªÙ‚ÙŠÙŠØ¯ Ø§Ø®ØªÙŠØ§Ø±ÙŠ Ø¹Ø¨Ø± env Ù„ÙƒÙ„ Ù…Ù†ØªØ¬ (ÙŠØ¯Ø¹Ù… *_PAY Ùˆ *_PAYMENTS)
    conf = (os.getenv(f"{product.upper()}_PAY") or os.getenv(f"{product.upper()}_PAYMENTS") or "").strip().lower()
    if conf:
        wanted = [m.strip() for m in conf.split(",") if m.strip() in ("stars", "crypto", "ton")]
        if "stars"  in wanted and allow_stars:
            methods.append("stars")
        if ("crypto" in wanted or "ton" in wanted) and allow_crypto:
            methods.append("crypto")
        return methods

    # Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠ Ø¨Ø¯ÙˆÙ† ØªÙ‚ÙŠÙŠØ¯ env: Ù…Ø§ Ø¯Ø§Ù… Ù…Ø³Ù…ÙˆØ Ø¹Ø§Ù„Ù…ÙŠÙ‹Ø§ ÙˆØ¥Ø¯Ø§Ø±ÙŠÙ‹Ø§
    if allow_stars:
        methods.append("stars")
    if allow_crypto:
        methods.append("crypto")
    return methods

def _pay_methods_kb(lang: str, product: str):
    kb = InlineKeyboardBuilder()

    # Ù„Ùˆ Ø§Ù„Ù…Ù†ØªØ¬ Ù…ØªÙˆÙ‚ÙØŒ Ø£Ø¹Ø±Ø¶ Ø²Ø± Ø±Ø¬ÙˆØ¹ ÙÙ‚Ø·
    if not _is_product_enabled(product):
        kb.button(
            text=("Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"),
            callback_data="shop:home"
        )
        kb.adjust(1)
        return kb.as_markup()

    methods = _pay_methods_for(product)

    for m in methods:
        if m == "stars":
            kb.button(
                text=("â Ø§Ù„Ø¯ÙØ¹ Ø¨Ù†Ø¬ÙˆÙ… ØªÙŠÙ„ÙŠØ¬Ø±Ø§Ù…" if str(lang).startswith("ar") else "â Pay with Telegram Stars"),
                callback_data=f"shop:pm:{product}:stars"
            )
        elif m == "crypto":
            label = ("ðŸ’³ Ø§Ù„Ø¯ÙØ¹ (USDT/TON)" if str(lang).startswith("ar") else "ðŸ’³ Pay (USDT/TON)")
            kb.button(
                text=label,
                callback_data=f"shop:pm:{product}:crypto"
            )

    # Ø²Ø± Ø§Ù„Ø±Ø¬ÙˆØ¹ Ø¯Ø§Ø¦Ù…Ù‹Ø§
    kb.button(
        text=("Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"),
        callback_data="shop:home"
    )

    # ØªØ±ØªÙŠØ¨ Ø§Ù„Ø£Ø¹Ù…Ø¯Ø© (Ø²Ø±ÙŠÙ† ÙÙŠ Ø§Ù„ØµÙ ÙƒØØ¯ Ø£Ù‚ØµÙ‰)
    kb.adjust(1, 1)
    return kb.as_markup()


@router.callback_query(F.data.startswith("shop:g:"))
async def choose_payment_method(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    lang = _user_lang(cb)
    _, _, product = cb.data.split(":", 2)

    # Ù…Ù†ØªØ¬ Ù…ØªÙˆÙ‚ÙØŸ
    if not _is_product_enabled(product):
        txt = "â¸ï¸ Ù‡Ø°Ø§ Ø§Ù„Ù…Ù†ØªØ¬ Ù…ØªÙˆÙ‚Ù Ù…Ø¤Ù‚ØªÙ‹Ø§." if str(lang).startswith("ar") else "â¸ï¸ This product is temporarily paused."
        kb = InlineKeyboardBuilder()
        kb.button(text=("Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"), callback_data="shop:home")
        kb.adjust(1)
        try:
            await cb.message.edit_text(txt, reply_markup=kb.as_markup())
        except Exception:
            await cb.message.answer(txt, reply_markup=kb.as_markup())
        await cb.answer()
        return

    methods = _pay_methods_for(product)
    if not methods:
        txt = "âš ï¸ Ø·Ø±Ù‚ Ø§Ù„Ø¯ÙØ¹ Ù„Ù‡Ø°Ø§ Ø§Ù„Ù…Ù†ØªØ¬ Ù…ØªÙˆÙ‚ÙØ© Ù…Ø¤Ù‚ØªÙ‹Ø§." if str(lang).startswith("ar") else "âš ï¸ Payments for this product are temporarily disabled."
    else:
        txt = "Ø§Ø®ØªØ± Ø·Ø±ÙŠÙ‚Ø© Ø§Ù„Ø¯ÙØ¹:" if str(lang).startswith("ar") else "Choose a payment method:"

    try:
        await cb.message.edit_text(txt, reply_markup=_pay_methods_kb(lang, product))
    except Exception:
        await cb.message.answer(txt, reply_markup=_pay_methods_kb(lang, product))
    await cb.answer()


# ========= Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ø®Ø·Ø© (ØØ³Ø¨ Ø§Ù„Ø·Ø±ÙŠÙ‚Ø©) =========
def _labels_for_usd(lang: str, product: str) -> Dict[int, str]:
    prices = _apply_tiers(_prices_usd(product), product)
    def label(days: int) -> str:
        price = _fmt_money(prices[days], 2)
        return f"ðŸ’µ ${price} | {days} ÙŠÙˆÙ…" if str(lang).startswith("ar") else f"${price} â€” {days}d"
    return {d: label(d) for d in (3, 10, 30)}

def _labels_for_stars(lang: str, product: str) -> Dict[int, str]:
    prices = _prices_stars(product)
    def label(days: int) -> str:
        s = int(prices[days])
        return f"â {s} | {days} ÙŠÙˆÙ…" if str(lang).startswith("ar") else f"â {s} â€” {days}d"
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
    kb.button(text=("Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"), callback_data=f"shop:g:{product}")
    kb.adjust(cols, 1)

    txt = "Ø§Ø®ØªØ± Ø§Ù„Ù…Ø¯Ø©" if str(lang).startswith("ar") else "Choose duration"
    try:
        await cb.message.edit_text(txt, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(txt, reply_markup=kb.as_markup())
    await cb.answer()

# ========= Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„ÙƒÙ…ÙŠØ© =========
@router.callback_query(F.data.startswith("shop:p:"))
async def choose_qty(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    lang = _user_lang(cb)
    _, _, product, method, days_s = cb.data.split(":")
    days = int(days_s)

    # Ø¹Ø±Ø¶ Ø§Ù„Ø³Ø¹Ø± ÙÙŠ Ø§Ù„Ø¹Ù†ÙˆØ§Ù†
    if method == "stars":
        price = _prices_stars(product)[days]
        head = "Ø§Ù„Ø®Ø·Ø©: {days} ÙŠÙˆÙ… â€” â {price} | Ø§Ø®ØªØ± Ø§Ù„ÙƒÙ…ÙŠØ©:" if str(lang).startswith("ar") else "Plan: {days}d â€” â {price} | Choose quantity:"
        txt = head.format(days=days, price=price)
    else:
        usd = _apply_tiers(_prices_usd(product), product)[days]
        head = "Ø§Ù„Ø³Ø¹Ø±: ${usd} â€” {days} ÙŠÙˆÙ… | Ø§Ø®ØªØ± Ø§Ù„ÙƒÙ…ÙŠØ©:" if str(lang).startswith("ar") else "Plan: {days}d â€” ${usd} | Choose quantity:"
        txt = head.format(days=days, usd=_fmt_money(usd, 2))

    # Ø£Ø¶Ù Ø§Ù„Ù…ØªÙˆÙØ± Ø§Ù„ÙØ¹Ù„ÙŠ
    left = await _count_for_safe(days, product)
    if left is not None:
        if str(lang).startswith("ar"):
            txt += f"\n(Ø§Ù„Ù…ØªÙˆÙØ± Ø§Ù„Ø¢Ù†: {left})"
        else:
            txt += f"\n(Available now: {left})"

    kb = InlineKeyboardBuilder()
    for n in range(1, 11):
        kb.button(text=f"{n}Ã—", callback_data=f"shop:q:{product}:{method}:{days}:{n}")
    kb.button(text=("Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"), callback_data=f"shop:pm:{product}:{method}")
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

# === Helpers: Ù†Øµ ÙˆØ£Ø²Ø±Ø§Ø± Ø§Ù‚ØªØ±Ø§Ø ÙƒÙ…ÙŠØ© Ø£Ù‚Ù„ ===
def _not_enough_stock_text(lang: str, days: int, left: int) -> str:
    if str(lang).startswith("ar"):
        if left <= 0:
            return f"Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ù…Ø®Ø²ÙˆÙ† Ù„Ù…Ø¯Ø© {days} ÙŠÙˆÙ…."
        unit = "Ù…ÙØªØ§Ø" if left == 1 else ("Ù…ÙØªØ§ØÙŠÙ†" if left == 2 else "Ù…ÙØ§ØªÙŠØ")
        return f"Ø§Ù„ÙƒÙ…ÙŠØ© Ø§Ù„Ù…Ø·Ù„ÙˆØ¨Ø© ØºÙŠØ± Ù…ØªØ§ØØ© Ù„Ù…Ø¯Ø© {days} ÙŠÙˆÙ….\nØ§Ù„Ù…ØªÙˆÙØ± Ø§Ù„Ø¢Ù†: {left} {unit}.\nðŸ’¡ Ø¬Ø±Ù‘Ø¨ ÙƒÙ…ÙŠØ© Ø£Ù‚Ù„."
    else:
        if left <= 0:
            return f"No inventory for {days}d."
        unit = "key" if left == 1 else "keys"
        return f"Requested quantity not available for {days}d.\nAvailable now: {left} {unit}.\nðŸ’¡ Try a lower quantity."

def _suggest_qty_kb(lang: str, product: str, method: str, days: int, left: int):
    """
    ÙŠØ¨Ù†ÙŠ ÙƒÙŠØ¨ÙˆØ±Ø¯ Ø¨Ø§Ù‚ØªØ±Ø§ØØ§Øª ÙƒÙ…ÙŠØ§Øª <= Ø§Ù„Ù…ØªÙˆÙØ±.
    ÙŠØ³ØªØ®Ø¯Ù… Ù†ÙØ³ callback Ø§Ù„Ù…Ø³ØªØ¹Ù…Ù„ Ø³Ø§Ø¨Ù‚Ù‹Ø§: shop:q:{product}:{method}:{days}:{qty}
    """
    kb = InlineKeyboardBuilder()
    # ÙƒÙ…ÙŠØ§Øª Ù…Ù‚ØªØ±ØØ©: Ø¥Ù† ÙƒØ§Ù† Ø§Ù„Ù…ØªÙˆÙØ± Ù‚Ù„ÙŠÙ„ (<=5) Ù†Ø¹Ø±Ø¶ 1..left
    # ÙˆØ¥Ù„Ø§ Ù†Ø¹Ø±Ø¶ Ø¨Ø¹Ø¶ Ø§Ù„Ø®ÙŠØ§Ø±Ø§Øª Ø§Ù„Ø°ÙƒÙŠØ© + Ø²Ø± Ø§Ù„Ù…ØªÙˆÙØ± Ø¨Ø§Ù„Ø¶Ø¨Ø·
    if left <= 5:
        options = list(range(1, left + 1))
    else:
        half = max(1, left // 2)
        options = sorted({1, half, max(half - 1, 1), left - 1, left})
    for q in options:
        label = (f"{q}Ã—" if not str(lang).startswith("ar") else f"{q}Ã—")
        kb.button(text=label, callback_data=f"shop:q:{product}:{method}:{days}:{q}")
    # Ø±Ø¬ÙˆØ¹
    back_txt = "Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"
    kb.button(text=back_txt, callback_data=f"shop:p:{product}:{method}:{days}")
    # ØªØ±ØªÙŠØ¨ Ø§Ù„Ø£Ø²Ø±Ø§Ø±
    if left <= 5:
        kb.adjust(min(left, 5), 5, 1)
    else:
        kb.adjust(3, 2, 1)
    return kb.as_markup()

# ========= ØªØ£ÙƒÙŠØ¯ Ø§Ù„Ù…Ø®Ø²ÙˆÙ† Ø«Ù… Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„ÙØ§ØªÙˆØ±Ø© ØØ³Ø¨ Ø§Ù„Ø·Ø±ÙŠÙ‚Ø© =========
@router.callback_query(F.data.startswith("shop:q:"))
async def prepare_invoice(cb: CallbackQuery):
    if not await _ensure_service_available(cb): return
    lang = _user_lang(cb)
    _, _, product, method, days_s, qty_s = cb.data.split(":")
    days = int(days_s); qty = int(qty_s)

    left = await _count_for_safe(days, product)

    # Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ø£ÙŠ Ù…Ø®Ø²ÙˆÙ†
    if left <= 0:
        # ØªÙ†Ø¨ÙŠÙ‡ Ù…Ø¹ Ø²Ø± Ø±Ø¬ÙˆØ¹ Ù„Ù„Ù…Ø¯Ø©
        try:
            await cb.answer(_not_enough_stock_text(lang, days, left=0), show_alert=True)
        except Exception:
            pass
        try:
            back_txt = "Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"
            ask_txt  = "Ù†ÙØ¯Øª Ø§Ù„ÙƒÙ…ÙŠØ© Ù„Ù‡Ø°Ù‡ Ø§Ù„Ù…Ø¯Ø©. Ø§Ø®ØªØ± Ù…Ø¯Ø© Ø£Ø®Ø±Ù‰:" if str(lang).startswith("ar") else "Out of stock for this plan. Pick another duration:"
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

    # ÙƒÙ…ÙŠØ© Ù…Ø·Ù„ÙˆØ¨Ø© Ø£ÙƒØ¨Ø± Ù…Ù† Ø§Ù„Ù…ØªÙˆÙØ± â†’ Ø§Ù‚ØªØ±Ø ÙƒÙ…ÙŠØ§Øª Ø£Ù‚Ù„
    if qty > left:
        text = _not_enough_stock_text(lang, days, left=left)
        try:
            await cb.answer(text, show_alert=True)
        except Exception:
            pass
        try:
            kb = _suggest_qty_kb(lang, product, method, days, left)
            # Ø¥Ù† Ø£Ù…ÙƒÙ† Ø¹Ø¯Ù‘Ù„ Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ø§Ù„ØØ§Ù„ÙŠØ© Ù„ÙŠØ´ÙˆÙ Ø§Ù„Ø£Ø²Ø±Ø§Ø± ÙÙˆØ±Ù‹Ø§
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

    # Ø§Ù„ÙƒÙ…ÙŠØ© Ù…Ù†Ø§Ø³Ø¨Ø© â†’ ØªØ§Ø¨Ø¹ Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„ÙØ§ØªÙˆØ±Ø©
    if method == "stars":
        return await _create_stars_invoice(cb, product, days, qty)

    # Crypto: Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ø£ØµÙˆÙ„ Ø¹Ù†Ø¯ ØªÙˆØ§ÙØ± Ø£ÙƒØ«Ø± Ù…Ù† Ø£ØµÙ„
    if CRYPTO_ENABLED and len(CRYPTO_ASSETS) > 1:
        text = "Ø§Ø®ØªØ± Ø·Ø±ÙŠÙ‚Ø© Ø§Ù„Ø¯ÙØ¹:" if str(lang).startswith("ar") else "Choose a payment asset:"
        kb = InlineKeyboardBuilder()
        for asset in CRYPTO_ASSETS:
            kb.button(text=asset, callback_data=f"shop:a:{product}:{days}:{qty}:{asset}")
        kb.button(text=("Ø±Ø¬ÙˆØ¹ â—€ï¸" if str(lang).startswith("ar") else "Back â—€ï¸"), callback_data=f"shop:p:{product}:crypto:{days}")
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
            "ØªÙ… Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„ÙØ§ØªÙˆØ±Ø©.\n"
            f"Ø§Ù„Ø³Ø¹Ø±: ${usd_txt} â‰ˆ {ton_txt} TON\n"
            f"Ø·Ø±ÙŠÙ‚Ø© Ø§Ù„Ø¯ÙØ¹: {asset}\n"
            f"Ø§Ù„ÙƒÙ…ÙŠØ©: {qty}Ã— | Ø§Ù„Ø®Ø·Ø©: {days} ÙŠÙˆÙ…\n"
            f"â³ ØªÙ†ØªÙ‡ÙŠ Ø®Ù„Ø§Ù„ {INVOICE_TTL_MIN} Ø¯Ù‚ÙŠÙ‚Ø©.\n"
            "ðŸ’¡ Ø§Ù„Ø³Ø¹Ø± ÙŠÙØØ¯Ù‘ÙŽØ« ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§ ØØ³Ø¨ Ø§Ù„Ø³ÙˆÙ‚."
        )
    return (
        "Invoice ready.\n"
        f"Price: ${usd_txt} â‰ˆ {ton_txt} TON\n"
        f"Asset: {asset}\n"
        f"Qty: {qty}Ã— | Plan: {days}d\n"
        f"â³ Expires in {INVOICE_TTL_MIN} min.\n"
        "ðŸ’¡ Price auto-updates with the market."
    )

# ========= Ø¥Ù†Ø´Ø§Ø¡ ÙØ§ØªÙˆØ±Ø© Crypto =========
async def _create_invoice_crypto(cb: CallbackQuery, product: str, days: int, qty: int, asset: str | None):
    lang = _user_lang(cb)
    usd_total  = _apply_tiers(_prices_usd(product), product)[days] * qty
    ton_equiv  = _usd_to_ton(usd_total)
    expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=INVOICE_TTL_MIN)

    if CRYPTO_ENABLED and asset:
        amount = ton_equiv if asset == "TON" else usd_total
        description = f"{product} | {qty}Ã— keys | {days}d"
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
                kb.button(text=("Ø§Ø¯ÙØ¹ Ø§Ù„Ø¢Ù†" if str(lang).startswith("ar") else "Pay Now"), url=pay_url)
            kb.button(text=("ØªØØ¯ÙŠØ«" if str(lang).startswith("ar") else "Refresh"), callback_data=f"shop:r:{order.id}")
            kb.button(text=("Ø¥Ù„ØºØ§Ø¡" if str(lang).startswith("ar") else "Cancel"),  callback_data=f"shop:c:{order.id}")
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
                    await cb.answer(("âš ï¸ ØªØ¹Ø°Ù‘Ø± Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„ÙØ§ØªÙˆØ±Ø©. ØØ§ÙˆÙ„ Ù„Ø§ØÙ‚Ù‹Ø§." if str(lang).startswith("ar") else "âš ï¸ Couldn't create invoice. Try again later."), show_alert=True)
                except Exception:
                    pass
                return

    # ÙÙˆÙ„Ø¨Ø§Ùƒ TON Ø§Ù„ÙŠØ¯ÙˆÙŠ
    order = await ords.create_order(
        user_id=cb.from_user.id, username=cb.from_user.username or "",
        days=days, qty=qty, usd_amount=usd_total, ton_amount=ton_equiv,
        asset=ASSET_TON, to_address=TON_ADDRESS, lang=lang, expires_at=expires_at, product=product,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=("ØªØØ¯ÙŠØ«" if str(lang).startswith("ar") else "Refresh"), callback_data=f"shop:r:{order.id}")
    kb.button(text=("Ø¥Ù„ØºØ§Ø¡" if str(lang).startswith("ar") else "Cancel"),  callback_data=f"shop:c:{order.id}")
    kb.adjust(2)

    text = _invoice_caption(lang, usd_total, ton_equiv, qty, days, ASSET_TON)
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())
    await cb.answer()

# ========= Ø¥Ù†Ø´Ø§Ø¡ ÙØ§ØªÙˆØ±Ø© Ù†Ø¬ÙˆÙ… ØªÙŠÙ„ÙŠØ¬Ø±Ø§Ù… =========
async def _create_stars_invoice(cb: CallbackQuery, product: str, days: int, qty: int):
    lang = _user_lang(cb)
    usd_one   = _apply_tiers(_prices_usd(product), product)[days]
    usd_total = usd_one * qty
    stars_one = _prices_stars(product)[days]
    stars_total = stars_one * qty
    expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=INVOICE_TTL_MIN)

    # Ù†Ø³Ø¬Ù‘Ù„ Ø§Ù„Ø·Ù„Ø¨ Ø£ÙˆÙ„Ø§Ù‹ (asset = XTR) â€” Ù†Ø®Ø²Ù† Ù…Ø¨Ù„Øº Ø§Ù„Ù†Ø¬ÙˆÙ… ÙÙŠ ton_amount ÙƒØÙ‚Ù„ Ø¹Ø§Ù…
    order = await ords.create_order(
        user_id=cb.from_user.id,
        username=cb.from_user.username or "",
        days=days, qty=qty,
        usd_amount=usd_total, ton_amount=float(stars_total),
        asset="XTR", to_address="", lang=lang, expires_at=expires_at,
        product=product,
    )

    # Ù†Ø±Ø³Ù„ Ø§Ù„ÙØ§ØªÙˆØ±Ø©
    await cb.bot.send_invoice(
        chat_id=cb.from_user.id,
        title=L(lang, "Ù…ÙØ§ØªÙŠØ Ø§Ø´ØªØ±Ø§Ùƒ", "Subscription keys"),
        description=L(lang, f"{product} â€¢ {days} ÙŠÙˆÙ… Ã— {qty}", f"{product} â€¢ {days}d Ã— {qty}"),
        payload=f"stars:{order.id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{product} {days}d Ã—{qty}", amount=int(stars_total))],
    )

    # Ø±Ø³Ø§Ù„Ø© Ø¥Ø¯Ø§Ø±ÙŠØ© ØªØØªÙ‡Ø§ ÙÙŠÙ‡Ø§ Â«ØªØØ¯ÙŠØ«/Ø¥Ù„ØºØ§Ø¡Â»
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_refresh", L(lang, "ØªØØ¯ÙŠØ«", "Refresh")), callback_data=f"shop:r:{order.id}")
    kb.button(text=tr(lang, "btn_cancel",  L(lang, "Ø¥Ù„ØºØ§Ø¡", "Cancel")),  callback_data=f"shop:c:{order.id}")
    kb.adjust(2)

    try:
        await cb.message.edit_text(
            L(lang, "ØªÙ… Ø¥Ù†Ø´Ø§Ø¡ ÙØ§ØªÙˆØ±Ø© Ø§Ù„Ù†Ø¬ÙˆÙ…. Ø¨Ø¹Ø¯ Ø§Ù„Ø¯ÙØ¹ Ø§Ø¶ØºØ· Â«ØªØØ¯ÙŠØ«Â» Ù„Ùˆ Ù„Ù… ÙŠØµÙ„Ùƒ Ø§Ù„Ù…ÙØªØ§Ø.", 
                     "Stars invoice created. After payment tap â€œRefreshâ€ if the key didnâ€™t arrive."),
            reply_markup=kb.as_markup()
        )
    except Exception:
        await cb.message.answer(
            L(lang, "ØªÙ… Ø¥Ù†Ø´Ø§Ø¡ ÙØ§ØªÙˆØ±Ø© Ø§Ù„Ù†Ø¬ÙˆÙ…. Ø¨Ø¹Ø¯ Ø§Ù„Ø¯ÙØ¹ Ø§Ø¶ØºØ· Â«ØªØØ¯ÙŠØ«Â».", 
                     "Stars invoice created. After payment tap â€œRefreshâ€."),
            reply_markup=kb.as_markup()
        )
    await cb.answer()

# ========= Ø²Ø± ØªØØ¯ÙŠØ«/Ø¥Ù„ØºØ§Ø¡ =========
@router.callback_query(F.data.startswith("shop:r:"))
async def refresh_status(cb: CallbackQuery):
    lang = _user_lang(cb)
    oid  = int(cb.data.split(":")[-1])

    # ØØ§Ù„Ø© Ø§Ù„Ø·Ù„Ø¨ Ù‚Ø¨Ù„ Ø§Ù„ÙØØµ
    try:
        r0 = await ords.get_by_id(oid)
        pre_status = str(getattr(r0, "status", "") or "")
    except Exception:
        pre_status = ""

    # ØªØÙ‚Ù‘Ù‚/ØªØ³Ù„ÙŠÙ… Ø¨Ø¯ÙˆÙ† Ø£ÙŠ Ø¥Ø±Ø³Ø§Ù„ ØªÙ„Ù‚Ø§Ø¦ÙŠ Ù…Ù† Ù‡Ù†Ø§
    ok, delivered_text = await check_and_deliver_one(cb.bot, oid, notify_user=False)

    # ØØ§Ù„Ø© Ø§Ù„Ø·Ù„Ø¨ Ø¨Ø¹Ø¯ Ø§Ù„ÙØØµ
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

    # Ù„Ùˆ Ù…Ø§ Ø²Ø§Ù„ Ø¨Ø§Ù†ØªØ¸Ø§Ø± Ø§Ù„Ø¯ÙØ¹
    if not ok or post_status not in ("paid", "delivered"):
        await cb.answer(
            "Ø¨Ø§Ù†ØªØ¸Ø§Ø± Ø§Ù„Ø¯ÙØ¹â€¦ (Ø³Ù†ØªØÙ‚Ù‚ ØªÙ„Ù‚Ø§Ø¦ÙŠÙ‹Ø§)" if str(lang).startswith("ar") else "Waiting for paymentâ€¦ (auto-checking)"
        )
        return

    # Ù„Ùˆ ÙƒØ§Ù† Ù…ÙØ³Ù„Ù‘ÙŽÙ… Ù…Ø³Ø¨Ù‚Ù‹Ø§ â†’ Ù„Ø§ ØªØ±Ø³Ù„ Ø§Ù„Ø¨Ø·Ø§Ù‚Ø© Ù…Ø±Ø© Ø«Ø§Ù†ÙŠØ©
    if pre_status == "delivered" and post_status == "delivered":
        await cb.answer("ØªÙ… Ø§Ù„ØªØ£ÙƒÙŠØ¯ âœ…" if str(lang).startswith("ar") else "Confirmed âœ…")
        return

    # Ù…Ù† Ù‡Ù†Ø§: ØªØºÙŠÙ‘Ø±Øª Ø§Ù„ØØ§Ù„Ø© Ù„Ù„ØªÙˆ Ø¥Ù„Ù‰ delivered (Ø£ÙˆÙ„ Ù…Ø±Ø©)
    try:
        confirm_txt = (
            "âœ… ØªÙ… ØªØ£ÙƒÙŠØ¯ Ø§Ù„Ø¯ÙØ¹.\nÙ„Ùˆ ÙˆØ§Ø¬Ù‡Øª Ù…Ø´ÙƒÙ„Ø© Ø§Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø£Ù…Ø± /report"
            if str(lang).startswith("ar")
            else "âœ… Payment confirmed.\nIf you face any issue, use /report"
        )
        # Ù‚Ø¯ ØªÙØ´Ù„ edit_text Ù„Ùˆ Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ù„ÙŠØ³Øª Ù‚Ø§Ø¨Ù„Ø© Ù„Ù„ØªØ¹Ø¯ÙŠÙ„Ø› Ù†ØªØ¬Ø§Ù‡Ù„ Ø¨Ù‡Ø¯ÙˆØ¡
        try:
            await cb.message.edit_text(confirm_txt, reply_markup=None)
        except Exception:
            pass
    except Exception:
        pass

    # Ø¬Ù‡Ù‘Ø² Ø§Ù„Ù…ÙØ§ØªÙŠØ Ø§Ù„Ù…Ø®Ø²Ù‘Ù†Ø© Ø¯Ø§Ø®Ù„ delivered_text (Ø¨Ø¯ÙˆÙ† Ø¥Ø¹Ø§Ø¯Ø© Ø¥Ø±Ø³Ø§Ù„ Ø§Ù„ÙØ§ØªÙˆØ±Ø©/Ø§Ù„Ø¥ÙŠØµØ§Ù„)
    keys = _extract_keys_from_text(delivered_text or "")
    _DELIVERED_KEYS[oid] = keys

    # Ø£Ø±Ø³Ù„ Ø¨Ø·Ø§Ù‚Ø© Ø§Ù„Ø´Ø±Ø§Ø¡ Ù…Ø±Ø© ÙˆØ§ØØ¯Ø© ÙÙ‚Ø·
    if oid not in _PROFILE_SENT:
        try:
            await _send_profile_block(cb, lang, oid, days, qty, keys, product=product)
        except Exception:
            pass
        _PROFILE_SENT.add(oid)

    await cb.answer("ØªÙ… Ø§Ù„ØªØ£ÙƒÙŠØ¯ âœ…" if str(lang).startswith("ar") else "Confirmed âœ…")



@router.callback_query(F.data.startswith("shop:c:"))
async def cancel_order(cb: CallbackQuery):
    lang = _user_lang(cb)
    oid  = int(cb.data.split(":")[-1])
    await ords.mark_cancelled_if_pending(oid)
    await cb.message.edit_text("ØªÙ… Ø¥Ù„ØºØ§Ø¡ Ø§Ù„Ø·Ù„Ø¨." if str(lang).startswith("ar") else "Order cancelled.")
    await cb.answer()

# ========= Ù…Ø¹Ø§Ù„Ø¬Ø© Ù…Ø¯ÙÙˆØ¹Ø§Øª Ø§Ù„Ù†Ø¬ÙˆÙ… =========
@router.pre_checkout_query()
async def pre_checkout(pre: PreCheckoutQuery):
    logging.info("[PAYâ] pre_checkout payload=%s currency=%s amount=%s",
                 pre.invoice_payload, getattr(pre, "currency", None), getattr(pre, "total_amount", None))
    await pre.answer(ok=True)
    
@router.message(F.successful_payment)
async def on_successful_payment(msg: Message):
    """
    ÙŠÙ„ØªÙ‚Ø· Ù†Ø¬Ø§Ø Ø¯ÙØ¹ Ø§Ù„Ù†Ø¬ÙˆÙ…:
    payload = "stars:<oid>"
    """
    try:
        payload = msg.successful_payment.invoice_payload or ""
    except Exception:
        payload = ""
    if not payload.startswith("stars:"):
        return  # ÙÙˆØ§ØªÙŠØ± Ø£Ø®Ø±Ù‰ Ø¥Ù† ÙˆÙØ¬Ø¯Øª

    try:
        oid = int(payload.split(":", 1)[1])
    except Exception:
        return

    # Ø¹Ù„Ù‘Ù… Ø§Ù„Ø·Ù„Ø¨ Ù…Ø¯ÙÙˆØ¹Ù‹Ø§ Ø«Ù… Ø³Ù„Ù‘Ù…
    try:
        await ords.mark_paid(oid)
    except Exception:
        pass

    try:
        ok, _ = await check_and_deliver_one(msg.bot, oid, notify_user=True)
        if ok:
            await msg.answer("âœ… ØªÙ… Ø§Ù„Ø¯ÙØ¹ Ø¨Ù†Ø¬Ø§Ø. ØªÙ… Ø¥Ø±Ø³Ø§Ù„ Ù…ÙØ§ØªÙŠØÙƒ." if str(_user_lang(msg)).startswith("ar") else "âœ… Payment received. Your keys have been sent.")
        else:
            await msg.answer("ØªÙ… Ø§Ù„Ø¯ÙØ¹. Ø³Ù†Ø³Ù„Ù… Ù‚Ø±ÙŠØ¨Ù‹Ø§." if str(_user_lang(msg)).startswith("ar") else "Paid. We will deliver shortly.")
    except Exception as e:
        logging.exception("deliver after stars payment failed: %r", e)

# ================= Ø¨Ø·Ø§Ù‚Ø© Ø§Ù„Ø´Ø±Ø§Ø¡ =================
async def _profile_kb(cb: CallbackQuery, lang: str, oid: int, product: str):
    app, guide, tut = _product_links(product)
    kb = InlineKeyboardBuilder()
    if tut:
        kb.button(text=("ðŸŽ¥ Ø´Ø±Ø Ø¨Ø§Ù„ÙÙŠØ¯ÙŠÙˆ" if str(lang).startswith("ar") else "ðŸŽ¥ Video tutorial"), callback_data=f"shop:tutorial:{oid}")
    if guide:
        kb.button(text=("ðŸ“˜ Ø´Ø±Ø Ø§Ù„ØªÙØ¹ÙŠÙ„" if str(lang).startswith("ar") else "ðŸ“˜ Activation Guide"), url=guide)
    if app:
        kb.button(text=("ðŸ“¦ ØªØÙ…ÙŠÙ„ Ø§Ù„ØªØ·Ø¨ÙŠÙ‚" if str(lang).startswith("ar") else "ðŸ“¦ Download App"), url=app)

    kb.button(text=("ðŸ’¾ ØÙØ¸ Ø§Ù„Ù…ÙØ§ØªÙŠØ" if str(lang).startswith("ar") else "ðŸ’¾ Save keys"), callback_data=f"shop:save:{oid}")
    kb.button(text=("â„¹ï¸ Ø·Ø±ÙŠÙ‚Ø© Ø§Ù„ØªÙØ¹ÙŠÙ„" if str(lang).startswith("ar") else "â„¹ï¸ How to activate"), callback_data=f"shop:howto:{oid}")

    if tut or guide or app:
        kb.adjust(3, 2)
    else:
        kb.adjust(2)
    return kb.as_markup()

def _profile_card_html(lang: str, days: int, qty: int, keys: List[str], product: str) -> str:
    product_disp = _product_label(lang, product) 
    title = "ðŸ§¾ Ø¨Ø·Ø§Ù‚Ø© Ø§Ù„Ø´Ø±Ø§Ø¡" if str(lang).startswith("ar") else "ðŸ§¾ Purchase Card"
    head  = (f"â€¢ Ø§Ù„Ù…Ù†ØªØ¬: {product}\nâ€¢ Ø§Ù„Ø®Ø·Ø©: {days} ÙŠÙˆÙ…\nâ€¢ Ø§Ù„ÙƒÙ…ÙŠØ©: {qty}Ã—") if str(lang).startswith("ar") else (f"â€¢ Product: {product}\nâ€¢ Plan: {days}d\nâ€¢ Qty: {qty}Ã—")
    ks    = "\n".join(f"â€¢ {_code(k)}" for k in keys) if keys else ("â€” Ù„Ø§ Ù…ÙØ§ØªÙŠØ â€”" if str(lang).startswith("ar") else "â€” No keys â€”")
    tip   = "â„¹ï¸ Ù„Ù„ØªÙØ¹ÙŠÙ„: Ø§ÙØªØ Ø§Ù„ØªØ·Ø¨ÙŠÙ‚ Ø§Ù„Ù…Ù†Ø§Ø³Ø¨ Ù„Ù…Ù†ØªØ¬Ùƒ Ø«Ù… Ø£Ø¯Ø®Ù„ Ø§Ù„Ù…ÙØªØ§Ø ÙƒÙ…Ø§ Ù‡Ùˆ Ù…ÙˆØ¶Ø ÙÙŠ Ø§Ù„Ø´Ø±Ø." if str(lang).startswith("ar") else "â„¹ï¸ Activate: open the proper app for your product and enter the key as shown in the guide."
    return f"{title}\n{head}\n\n{'ðŸ”‘ Ø§Ù„Ù…ÙØ§ØªÙŠØ:' if str(lang).startswith('ar') else 'ðŸ”‘ Keys:'}\n{ks}\n\n{tip}"

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
    for m in _re.finditer(r"(?m)^\s*[-â€¢]\s*([A-Za-z0-9_\-:]{6,})\s*$", text or ""):
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
        await cb.answer("Ø£Ø±Ø³Ù„Øª Ù„Ùƒ Ø®Ø·ÙˆØ§Øª Ø§Ù„ØªÙØ¹ÙŠÙ„." if str(lang).startswith("ar") else "Sent you the activation steps.")
    except Exception:
        await cb.answer("ØªØ¹Ø°Ù‘Ø± Ø¥Ø±Ø³Ø§Ù„ Ø§Ù„Ø®Ø·ÙˆØ§Øª Ø§Ù„Ø¢Ù†." if str(lang).startswith("ar") else "Couldn't send the steps now.", show_alert=True)

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
        await cb.answer("ÙÙŠØ¯ÙŠÙˆ Ø§Ù„Ø´Ø±Ø ØºÙŠØ± Ù…ØªØ§Ø ØØ§Ù„ÙŠÙ‹Ø§." if str(lang).startswith("ar") else "Tutorial video not available.", show_alert=True)
        return
    try:
        await cb.message.answer_video(
            tut,
            caption=("Ø´Ø±Ø Ø³Ø±ÙŠØ¹ Ù„ØªÙØ¹ÙŠÙ„ Ø§Ù„Ù…ÙØªØ§Ø." if str(lang).startswith("ar") else "Quick guide to activate your key."),
            parse_mode=ParseMode.HTML
        )
        await cb.answer()
    except Exception as e:
        logging.exception("send tutorial failed: %r", e)
        await cb.answer("ØªØ¹Ø°Ù‘Ø± Ø¥Ø±Ø³Ø§Ù„ Ø§Ù„ÙÙŠØ¯ÙŠÙˆ Ø§Ù„Ø¢Ù†." if str(lang).startswith("ar") else "Couldn't send the video now.", show_alert=True)

@router.callback_query(F.data.startswith("shop:save:"))
async def save_keys_file(cb: CallbackQuery):
    lang = _user_lang(cb)
    try:
        oid = int(cb.data.split(":")[-1])
    except Exception:
        return await cb.answer("Ù…Ø¹Ø±Ù‘Ù ØºÙŠØ± ØµØ§Ù„Ø." if str(lang).startswith("ar") else "Invalid id.", show_alert=True)

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
            "Ù„Ù… Ø£Ø¬Ø¯ Ø§Ù„Ù…ÙØ§ØªÙŠØ Ù„Ù‡Ø°Ù‡ Ø§Ù„Ø¹Ù…Ù„ÙŠØ© (Ø±Ø¨Ù…Ø§ Ø§Ù†ØªÙ‡Øª Ø§Ù„Ø¬Ù„Ø³Ø©)." if str(lang).startswith("ar") else "Couldn't find keys for this order (session may have reset).",
            show_alert=True
        )

    txt = "\n".join(keys) + "\n"
    data = txt.encode("utf-8")
    try:
        await cb.message.answer_document(
            BufferedInputFile(data, filename=f"keys-{oid}.txt"),
            caption=("ØªÙ… Ø¥Ù†Ø´Ø§Ø¡ Ù…Ù„Ù Ø§Ù„Ù…ÙØ§ØªÙŠØ. Ø§ØÙØ¸Ù‡ Ù„Ø¯ÙŠÙƒ." if str(lang).startswith("ar") else "Keys file generated. Save it safely.")
        )
        await cb.answer()
    except Exception:
        await cb.answer("ØªØ¹Ø°Ù‘Ø± Ø¥Ø±Ø³Ø§Ù„ Ø§Ù„Ù…Ù„Ù." if str(lang).startswith("ar") else "Couldn't send the file.", show_alert=True)

# ========= Ø£ÙˆØ§Ù…Ø± Ø¥Ø¯Ù…Ù†: Ø§Ù„Ø£Ø³Ø¹Ø§Ø± =========
@router.message(Command("prices"))
async def prices_cmd(msg: Message):
    lang = _user_lang(msg)

    def line_usd(prod: str) -> List[str]:
        p = _apply_tiers(_prices_usd(prod), prod)
        return [
            ("Ø§Ù„Ø£Ø³Ø¹Ø§Ø± USD ({prod}):".format(prod=prod) if str(lang).startswith("ar") else f"Prices USD ({prod}):"),
            f"â€¢ 3d: ${_fmt_money(p[3], 2)}",
            f"â€¢ 10d: ${_fmt_money(p[10], 2)}",
            f"â€¢ 30d: ${_fmt_money(p[30], 2)}"
        ]

    def line_stars(prod: str) -> List[str]:
        p = _prices_stars(prod)
        return [
            ("Ø§Ù„Ø£Ø³Ø¹Ø§Ø± â ({prod}):".format(prod=prod) if str(lang).startswith("ar") else f"Prices â ({prod}):"),
            f"â€¢ 3d: {p[3]}â",
            f"â€¢ 10d: {p[10]}â",
            f"â€¢ 30d: {p[30]}â"
        ]

    lines = []
    for prod in PRODUCTS:
        lines += line_usd(prod) + line_stars(prod) + [""]

    if _is_admin(msg.from_user.id):
        if str(lang).startswith("ar"):
            instr = (
                "<b>Ø£ÙˆØ§Ù…Ø± Ø§Ù„ØªØ¹Ø¯ÙŠÙ„:</b>\n"
                f"{_code('/set_price <days> <usd>')} (Ø§ÙØªØ±Ø§Ø¶ÙŠ)\n"
                f"{_code('/set_price <product> <days> <usd>')} (Ù„ÙƒÙ„ Ù…Ù†ØªØ¬)\n"
                f"{_code('/set_prices 3=4.99 10=12.5 30=25')} (Ø§ÙØªØ±Ø§Ø¶ÙŠ)\n"
                f"{_code('/set_prices carrom:3=5 8bp:10=3.5')} (Ù„ÙƒÙ„ Ù…Ù†ØªØ¬)\n"
                f"{_code('/set_star_price <days> <stars>')} Ø£Ùˆ {_code('/set_star_price <product> <days> <stars>')}\n"
                f"{_code('/set_star_prices 3=150 10=350 30=750')} Ø£Ùˆ {_code('/set_star_prices carrom:3=160 8bp:10=330')}"
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
        txt = ( "Ø§Ù„Ø§Ø³ØªØ®Ø¯Ø§Ù…: " + _code("/set_price <days> <usd>") + " Ø£Ùˆ " + _code("/set_price <product> <days> <usd>") ) if str(lang).startswith("ar") \
              else ( "Usage: " + _code("/set_price <days> <usd>") + " or " + _code("/set_price <product> <days> <usd>") )
        return await msg.reply(txt, parse_mode=ParseMode.HTML)

    mp = _load_prices_map()
    mp.setdefault(prod, {})
    mp[prod][d] = val
    _save_prices_map(mp)
    target = "Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠ" if str(lang).startswith("ar") and prod == "default" else (prod if prod != "default" else "default")
    await msg.reply(("ØªÙ… Ø¶Ø¨Ø· Ø³Ø¹Ø± {d} ÙŠÙˆÙ… ({t}) Ø¥Ù„Ù‰ ${v}.".format(d=d, t=target, v=_fmt_money(val, 2))
                     if str(lang).startswith("ar") else f"Set price {d}d ({target}) to ${_fmt_money(val, 2)}."))

@router.message(Command("set_prices"))
async def set_prices_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _user_lang(msg)
    parts = (msg.text or "").split()[1:]
    if not parts:
        txt = ("Ø§Ø³ØªØ®Ø¯Ù…: " + _code("/set_prices 3=4.99 10=12.5 30=25") + " Ø£Ùˆ " + _code("/set_prices carrom:3=5 8bp:10=3.5")) if str(lang).startswith("ar") \
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
        await msg.reply(("ØªÙ… Ø§Ù„ØªØØ¯ÙŠØ«: " if str(lang).startswith("ar") else "Updated: ") + ", ".join(changed))
    else:
        await msg.reply("Ù„Ù… ÙŠØªÙ… ØªØØ¯ÙŠØ« Ø£ÙŠ Ø³Ø¹Ø±." if str(lang).startswith("ar") else "No prices updated.")

# ====== Ø£ÙˆØ§Ù…Ø± Ø¥Ø¯Ù…Ù†: Ø£Ø³Ø¹Ø§Ø± Ø§Ù„Ù†Ø¬ÙˆÙ… ======
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
        txt = ( "Ø§Ù„Ø§Ø³ØªØ®Ø¯Ø§Ù…: " + _code("/set_star_price <days> <stars>") + " Ø£Ùˆ " + _code("/set_star_price <product> <days> <stars>") ) if str(lang).startswith("ar") \
              else ( "Usage: " + _code("/set_star_price <days> <stars>") + " or " + _code("/set_star_price <product> <days> <stars>") )
        return await msg.reply(txt, parse_mode=ParseMode.HTML)

    mp = _load_stars_map()
    mp.setdefault(prod, {})
    mp[prod][d] = val
    _save_stars_map(mp)
    target = "Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠ" if str(lang).startswith("ar") and prod == "default" else (prod if prod != "default" else "default")
    await msg.reply(("ØªÙ… Ø¶Ø¨Ø· Ø³Ø¹Ø± {d} ÙŠÙˆÙ… ({t}) Ø¥Ù„Ù‰ â{v}.".format(d=d, t=target, v=val)
                     if str(lang).startswith("ar") else f"Set Stars price {d}d ({target}) to â{val}."))

@router.message(Command("set_star_prices"))
async def set_star_prices_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _user_lang(msg)
    parts = (msg.text or "").split()[1:]
    if not parts:
        txt = ("Ø§Ø³ØªØ®Ø¯Ù…: " + _code("/set_star_prices 3=150 10=350 30=750") + " Ø£Ùˆ " + _code("/set_star_prices carrom:3=160 8bp:10=330")) if str(lang).startswith("ar") \
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
                    changed.append(f"{prod}:{d}d=â{val}")
            else:
                days_s, val_s = part.split("=", 1)
                d = int(days_s); val = int(val_s)
                if d in (3, 10, 30) and val > 0:
                    mp.setdefault("default", {})[d] = val
                    changed.append(f"default:{d}d=â{val}")
        except Exception:
            continue

    _save_stars_map(mp)
    if changed:
        await msg.reply(("ØªÙ… Ø§Ù„ØªØØ¯ÙŠØ«: " if str(lang).startswith("ar") else "Updated: ") + ", ".join(changed))
    else:
        await msg.reply("Ù„Ù… ÙŠØªÙ… ØªØØ¯ÙŠØ« Ø£ÙŠ Ø³Ø¹Ø±." if str(lang).startswith("ar") else "No prices updated.")

