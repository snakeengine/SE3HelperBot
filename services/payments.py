# services/payments.py
from __future__ import annotations

import asyncio
import logging
import os
import json
import shutil
from pathlib import Path
from typing import Tuple, List, Callable, Any

from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from html import escape as h

from services import orders as ords
from services import inventory as inv
from services import cryptopay as cp
from utils.paths import BASE

# ===================== إعدادات عامة =====================
logger = logging.getLogger(__name__)

CRYPTOPAY_ON = bool(os.getenv("CRYPTOPAY_TOKEN"))
PRODUCT_ENV  = os.getenv("PRODUCT_KEY", "8bp").strip().lower() or "8bp"

FLAGS_PATH   = BASE / "shop_flags.json"     # {"keys_disabled": bool, "keys_stop_message": "...", "pay_modes": {...}}
SHOP_CFG     = BASE / "shop_config.json"    # {"enabled": bool}
INV_BL_PATH  = BASE / "inv_blacklist.json"  # {"keys": {"KEY": true, ...}}

WATCH_INTERVAL_SEC = int(os.getenv("SHOP_WATCH_INTERVAL", "10"))

# روابط عامة (fallback)
APP_DOWNLOAD_URL_DEFAULT     = os.getenv("APP_DOWNLOAD_URL", "")
ACTIVATION_GUIDE_URL_DEFAULT = os.getenv("ACTIVATION_GUIDE_URL", "")
TUTORIAL_URL_DEFAULT         = os.getenv("TUTORIAL_URL", "") or os.getenv("TUTORIAL_FILE_ID", "")

# ---------- تشخيص + ترحيل ملفات قديمة إلى المجلد الدائم ----------
_printed_paths_once = False
def _print_paths_once():
    global _printed_paths_once
    if _printed_paths_once:
        return
    _printed_paths_once = True
    try:
        print(f"[STORAGE] BASE={BASE}")
        print(f"[STORAGE] FLAGS_PATH={FLAGS_PATH}")
        print(f"[STORAGE] SHOP_CFG={SHOP_CFG}")
        print(f"[STORAGE] INV_BL_PATH={INV_BL_PATH}")
    except Exception:
        pass

def _migrate_legacy_file(legacy: Path, target: Path):
    """
    لو الملف موجود بمسار قديم (داخل ./ أو ./data) ننقله إلى BASE مرة واحدة.
    لا نكتب فوق هدف موجود.
    """
    try:
        if target.exists():
            return
        if legacy.exists() and legacy.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, target)
            logger.info("Migrated legacy file %s -> %s", legacy, target)
    except Exception as e:
        logger.warning("Legacy migrate failed for %s -> %s: %s", legacy, target, e)

def _maybe_migrate_legacy_files():
    """
    إمساك أشهر المواقع القديمة التي ربما استخدمتها محليًا:
      ./shop_flags.json
      ./shop_config.json
      ./inv_blacklist.json
      ./data/shop_flags.json
      ./data/shop_config.json
      ./data/inv_blacklist.json
    """
    candidates = [
        (Path("shop_flags.json"), FLAGS_PATH),
        (Path("shop_config.json"), SHOP_CFG),
        (Path("inv_blacklist.json"), INV_BL_PATH),
        (Path("data") / "shop_flags.json", FLAGS_PATH),
        (Path("data") / "shop_config.json", SHOP_CFG),
        (Path("data") / "inv_blacklist.json", INV_BL_PATH),
    ]
    for src, dst in candidates:
        _migrate_legacy_file(src, dst)

# استدعِ الترحيل/الطباعة مبكرًا
_print_paths_once()
_maybe_migrate_legacy_files()

# ===================== i18n helpers =====================
try:
    from lang import t as _t, get_user_lang as _get_user_lang
except Exception:
    # فولباك لو عندك util مختلفة
    from utils_language import t as _t, get_user_lang as _get_user_lang  # type: ignore

def _norm_lang(code: str | None) -> str:
    c = (code or "en").lower()
    return "ar" if c.startswith("ar") else "en"

def _order_lang(order: "ords.Order") -> str:
    lang = getattr(order, "lang", None)
    if lang:
        return _norm_lang(lang)
    try:
        return _norm_lang(_get_user_lang(getattr(order, "user_id", 0)))
    except Exception:
        return "en"

def L(lang: str, ar: str, en: str) -> str:
    return ar if lang == "ar" else en

def tr(lang: str, key: str, fallback: str) -> str:
    try:
        v = _t(lang, key)
        if isinstance(v, str) and v.strip() and v != key:
            return v
    except Exception:
        pass
    return fallback

def trf(lang: str, key: str, fallback: str, **fmt) -> str:
    s = tr(lang, key, fallback)
    try:
        return s.format(**fmt)
    except Exception:
        return s

# ===================== أدوات JSON =====================
def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("Failed to read %s: %s", path, e)
    return {}

def _save_json(path: Path, obj: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:
        logger.warning("Failed to write %s: %s", path, e)

def _keys_service_disabled() -> bool:
    d = _load_json(FLAGS_PATH)
    return bool(d.get("keys_disabled", False))

def _shop_enabled() -> bool:
    d = _load_json(SHOP_CFG)
    return bool(d.get("enabled", True))

def _load_blacklist() -> set[str]:
    d = _load_json(INV_BL_PATH)
    m = d.get("keys") or {}
    return {str(k).strip() for k, v in m.items() if v}

# ===================== روابط/أسماء حسب المنتج =====================
def _per_product_env(prefix: str, product: str) -> str:
    """
    يقرأ متغيرات البيئة بصيغ:
      {PRODUCT}_{PREFIX}
      {PRODUCT}_{PREFIX}_URL
      {PRODUCT}_{PREFIX}_FILE_ID
    """
    p = (product or "").strip().lower()
    key1 = f"{p.upper()}_{prefix}".replace("-", "_")
    key2 = f"{p.upper()}_{prefix}_URL".replace("-", "_")
    key3 = f"{p.upper()}_{prefix}_FILE_ID".replace("-", "_")
    return os.getenv(key1) or os.getenv(key2) or os.getenv(key3) or ""

def _product_links(product: str) -> tuple[str, str, str]:
    """
    يرجّع (app_url, guide_url, tutorial_url_or_file_id)
    مع فولباك على الإعدادات العامة إذا لم يوجد تخصيص.
    """
    app   = _per_product_env("APP_DOWNLOAD", product)     or APP_DOWNLOAD_URL_DEFAULT
    guide = _per_product_env("ACTIVATION_GUIDE", product) or ACTIVATION_GUIDE_URL_DEFAULT
    tut   = _per_product_env("TUTORIAL", product)         or TUTORIAL_URL_DEFAULT
    return app, guide, tut

def _product_of(order: "ords.Order") -> str:
    """يستخرج كود المنتج من الطلب (مع فولباك على المتغير البيئي)."""
    return (getattr(order, "product", None)
            or getattr(order, "slug", None)
            or PRODUCT_ENV).strip().lower()

def _product_display(prod: str, lang: str) -> str:
    p = (str(prod or "").lower()).strip()
    mapping = {
        "8bp": "8 Ball Pool",
        "8ball": "8 Ball Pool",
        "8ballpool": "8 Ball Pool",
        "8-ball": "8 Ball Pool",
        "8_ball": "8 Ball Pool",
        "carrom": "Carrom Pool",
        "carrompool": "Carrom Pool",
        "carrom-pool": "Carrom Pool",
        "soccer": "Soccer Stars",
        "soccerstars": "Soccer Stars",
        "soccer-stars": "Soccer Stars",
        "football-kick": "Soccer Stars",
    }
    return mapping.get(p, p or ( "غير محدد" if lang == "ar" else "Unspecified"))

def _key_type_display(lang: str) -> str:
    return "مفتاح اشتراك" if lang == "ar" else "Subscription key"

# ===================== Utilities =====================
def _extract_keys_any(text: str) -> list[str]:
    """يسحب المفاتيح من HTML/Markdown ونقاط."""
    import re
    keys: list[str] = []
    for m in re.finditer(r"<code>([^<]+)</code>", text or ""):
        keys.append(m.group(1).strip())
    for m in re.finditer(r"-\s*`([^`]+)`", text or ""):
        keys.append(m.group(1).strip())
    for m in re.finditer(r"(?m)^\s*[-•]\s*([A-Za-z0-9_\-:]{6,})\s*$", text or ""):
        keys.append(m.group(1).strip())
    seen = set(); out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k); out.append(k)
    return out

async def _call_maybe_async(fn: Callable, *a, **kw) -> Any:
    """ينفّذ الدوال سواء كانت sync أو async."""
    try:
        if asyncio.iscoroutinefunction(fn):
            return await fn(*a, **kw)
        res = fn(*a, **kw)
        if asyncio.iscoroutine(res):
            return await res
        return res
    except TypeError:
        raise

async def _inv_pop_codes_safe(days: int, qty: int, product: str) -> List[str]:
    """
    يستدعي inv.pop_codes بتوافق عالي مع اختلاف التواقيع.
    """
    cand = getattr(inv, "pop_codes", None)
    if not callable(cand):
        return []
    # 1) kwargs
    try:
        res = await _call_maybe_async(cand, days=days, qty=qty, product=product)
        return list(res or [])
    except TypeError:
        pass
    # 2) positional: (days, qty, product)
    try:
        res = await _call_maybe_async(cand, days, qty, product)
        return list(res or [])
    except TypeError:
        pass
    # 3) positional: (product, days, qty)
    try:
        res = await _call_maybe_async(cand, product, days, qty)
        return list(res or [])
    except TypeError:
        pass
    # 4) positional: (days, qty)
    try:
        res = await _call_maybe_async(cand, days, qty)
        return list(res or [])
    except Exception:
        return []

async def _inv_maybe_alert_low_stock_safe(bot, days: int, product: str):
    f = getattr(inv, "maybe_alert_low_stock", None)
    if not callable(f):
        return
    try:
        await _call_maybe_async(f, bot, days, product=product)
    except TypeError:
        try:
            await _call_maybe_async(f, bot, product, days)
        except Exception:
            pass
    except Exception:
        pass

# ===================== واجهة المستخدم بعد التسليم =====================
def _profile_card_html_simple(order: "ords.Order", keys: list[str]) -> str:
    lang = _order_lang(order)
    prod = _product_display(_product_of(order), lang)
    key_type = _key_type_display(lang)

    title = L(lang, "🧾 بطاقة الشراء", "🧾 Purchase Card")
    head_lines = [
        L(lang, f"• المنتج: {prod}",           f"• Product: {prod}"),
        L(lang, f"• النوع: {key_type}",        f"• Type: {key_type}"),
        L(lang, f"• الخطة: {order.days} يوم",  f"• Plan: {order.days}d"),
        L(lang, f"• الكمية: {order.qty}×",     f"• Qty: {order.qty}×"),
    ]
    head = "\n".join(head_lines)

    ks    = "\n".join(f"• <code>{h(k)}</code>" for k in keys) if keys else L(lang, "— لا مفاتيح —", "— No keys —")
    tip   = L(lang,
              "ℹ️ للتفعيل: افتح التطبيق → <b>Entry Key</b> → الصق المفتاح → <b>Activate</b>.",
              "ℹ️ Activate: Open the app → <b>Entry Key</b> → paste the key → <b>Activate</b>.")
    keys_title = L(lang, "🔑 المفاتيح:", "🔑 Keys:")
    return f"{title}\n{head}\n\n{keys_title}\n{ks}\n\n{tip}"

async def _send_profile_and_help(bot, order: "ords.Order", delivered_text: str) -> None:
    """يرسل بطاقة الشراء (المفاتيح + الروابط/الشرح) مرة واحدة بعد التسليم."""
    lang = _order_lang(order)
    product = _product_of(order)
    keys = _extract_keys_any(delivered_text)

    app_url, guide_url, tut_url = _product_links(product)

    kb = InlineKeyboardBuilder()
    # صف علوي اختياري حسب المتوفر
    if tut_url:
        kb.button(text=L(lang, "🎥 شرح بالفيديو", "🎥 Video tutorial"),
                  callback_data=f"shop:tutorial:{order.id}")
    if guide_url:
        kb.button(text=L(lang, "📘 شرح التفعيل", "📘 Activation Guide"),
                  url=guide_url)
    if app_url:
        kb.button(text=L(lang, "📦 تحميل التطبيق", "📦 Download App"),
                  url=app_url)

    # صف سفلي ثابت
    kb.button(text=L(lang, "💾 حفظ المفاتيح", "💾 Save keys"),
              callback_data=f"shop:save:{order.id}")
    kb.button(text=L(lang, "ℹ️ طريقة التفعيل", "ℹ️ How to activate"),
              callback_data=f"shop:howto:{order.id}")

    if tut_url or guide_url or app_url:
        kb.adjust(3, 2)
    else:
        kb.adjust(2)

    try:
        await bot.send_message(
            order.user_id,
            _profile_card_html_simple(order, keys),
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass

# ===================== قفل لكل طلب =====================
_ORDER_LOCKS: dict[int, asyncio.Lock] = {}
def _get_lock(order_id: int) -> asyncio.Lock:
    lock = _ORDER_LOCKS.get(order_id)
    if lock is None:
        lock = _ORDER_LOCKS[order_id] = asyncio.Lock()
    return lock

# ===================== منطق الدفع والتسليم =====================
async def _deliver(bot, order: "ords.Order", *, notify_user: bool = True) -> Tuple[bool, str]:
    """
    يسحب مفاتيح من المنتج الصحيح، يتجاهل المفاتيح المحظورة، ويحفظ نص التسليم (HTML).
    آمن للتكرار: لو كان الطلب مسلّمًا يعيد النص المخزَّن كما هو.
    يرسل للمستخدم بطاقة الشراء فقط (بدون رسالة 'تم استلام الدفع').
    """
    if getattr(order, "status", "") == "delivered":
        text = (
            getattr(order, "delivered_text", None)
            or getattr(order, "delivery_text", None)
            or getattr(order, "text", None)
            or ""
        ).strip()
        if text:
            return True, text

    product = _product_of(order)
    bl = _load_blacklist()

    need   = max(0, int(order.qty))
    picked: List[str] = []
    tries  = 0

    while len(picked) < need and tries < max(need * 6, 6):
        tries += 1
        batch = await _inv_pop_codes_safe(order.days, need - len(picked), product)
        if not batch:
            break
        for k in batch:
            k = str(k).strip()
            if not k or k in bl:
                continue
            picked.append(k)
            if len(picked) >= need:
                break

    lang       = _order_lang(order)
    prod_label = _product_display(product, lang)
    key_type   = _key_type_display(lang)

    if len(picked) < need:
        # نفدت قبل التسليم
        return False, L(
            lang,
            "⚠️ نفد المخزون قبل التسليم. تواصل مع الدعم لاسترجاع المبلغ.",
            "⚠️ Out of stock before delivery. Contact support for a refund."
        )

    lines = [
        tr(lang, "pay.received", L(lang, "تم استلام الدفع ✅", "Payment received ✅")),
        L(lang, f"المنتج: {prod_label}",            f"Product: {prod_label}"),
        L(lang, f"النوع: {key_type}",               f"Type: {key_type}"),
        L(lang, f"الخطة: {order.days} يوم | الكمية: {order.qty}×",
                 f"Plan: {order.days}d | Qty: {order.qty}×"),
        L(lang, "المفاتيح:", "Keys:"),
        *[f"- <code>{h(c)}</code>" for c in picked],
    ]
    text = "\n".join(lines)

    # خزّن نص التسليم (يضبط الحالة إلى delivered)
    await ords.save_delivery(order.id, text)

    if notify_user:
        # نرسل بطاقة الشراء فقط (من دون إرسال نص الإيصال أعلاه)
        try:
            await _send_profile_and_help(bot, order, text)
        except Exception as e:
            logger.warning("send profile/help failed: %s", e)

    await _inv_maybe_alert_low_stock_safe(bot, order.days, product=product)
    return True, text

async def _check_cryptopay_paid(order: "ords.Order") -> bool:
    """يتحقق من Crypto Pay عبر invoice_hash."""
    if not CRYPTOPAY_ON:
        return False
    if not getattr(order, "invoice_hash", None):
        return False
    try:
        inv_obj = await cp.get_invoice(order.invoice_hash)
        return (inv_obj or {}).get("status", "").lower() == "paid"
    except Exception as e:
        logger.warning("cryptopay check failed: %s", e)
        return False

async def check_and_deliver_one(bot, order_id: int, *, notify_user: bool = True) -> Tuple[bool, str]:
    """
    يتحقق من حالة الطلب ويسلّم إذا أمكن (Idempotent + Lock).
    يعيد (ok, delivered_text).
    """
    if _keys_service_disabled() or not _shop_enabled():
        return False, ""

    lock = _get_lock(order_id)
    async with lock:
        order = await ords.get_by_id(order_id)
        if not order:
            return False, ""

        status = getattr(order, "status", "")
        if status not in ("pending", "paid", "delivered"):
            return False, ""

        if status == "delivered":
            text = (
                getattr(order, "delivered_text", None)
                or getattr(order, "delivery_text", None)
                or getattr(order, "text", None)
                or ""
            ).strip()
            return True, text

        if status == "paid":
            return await _deliver(bot, order, notify_user=notify_user)

        # pending
        if getattr(order, "invoice_hash", None):
            if await _check_cryptopay_paid(order):
                await ords.mark_paid(order.id)
                order = await ords.get_by_id(order_id) or order
                return await _deliver(bot, order, notify_user=notify_user)
            return False, ""

        # TON (تحقق يدوي فقط)
        return False, ""

# ===================== المراقب الآلي =====================
_watcher_task: asyncio.Task | None = None

async def _watch_loop(bot, interval_sec: int):
    logger.info("[SHOP] Auto-watcher started (interval=%ss)", interval_sec)
    try:
        while True:
            try:
                if _keys_service_disabled() or not _shop_enabled():
                    await asyncio.sleep(interval_sec)
                    continue

                pending = await ords.list_pending()
                for o in pending:
                    if getattr(o, "invoice_hash", None):
                        await check_and_deliver_one(bot, o.id, notify_user=True)
                await asyncio.sleep(interval_sec)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("auto_watcher loop error: %s", e)
                await asyncio.sleep(interval_sec)
    finally:
        logger.info("[SHOP] Auto-watcher stopped")

def start_auto_watcher(bot, interval_sec: int | None = None):
    """
    ابدأ مراقب فواتير Crypto Pay.
    استدعِ هذه الدالة عند تشغيل البوت (مرة واحدة).
    """
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        return _watcher_task
    iv = int(interval_sec or WATCH_INTERVAL_SEC)
    _watcher_task = asyncio.create_task(_watch_loop(bot, iv))
    return _watcher_task

def stop_auto_watcher():
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        _watcher_task.cancel()
    _watcher_task = None

# ===================== Pay modes per product =====================
# نخزّن الإعدادات داخل FLAGS_PATH (shop_flags.json) تحت المفتاح "pay_modes"
# البنية: {"pay_modes": {"default": {"stars": true, "crypto": true}, "carrom": {...}, ...}}

def _norm_prod(p: str | None) -> str:
    return (p or "default").strip().lower() or "default"

def _pay_modes_all() -> dict:
    d = _load_json(FLAGS_PATH)
    return dict(d.get("pay_modes") or {})

def _save_pay_modes(mp: dict) -> None:
    d = _load_json(FLAGS_PATH)
    d["pay_modes"] = mp
    _save_json(FLAGS_PATH, d)

def get_pay_modes(product: str) -> dict[str, bool]:
    """
    يرجّع dict مثل {"stars": True/False, "crypto": True/False} للمنتج.
    افتراضيًا كلاهما مفعّل ما لم يُعطَّل يدويًا.
    """
    p  = _norm_prod(product)
    mp = _pay_modes_all()
    base = {"stars": True, "crypto": True}
    if "default" in mp:
        base.update({k: bool(v) for k, v in (mp.get("default") or {}).items() if k in base})
    if p in mp:
        base.update({k: bool(v) for k, v in (mp.get(p) or {}).items() if k in base})
    return base

def set_pay_mode_enabled(product: str, mode: str, enabled: bool) -> None:
    """
    mode ∈ {"stars","crypto"}
    """
    p   = _norm_prod(product)
    mp  = _pay_modes_all()
    node = dict(mp.get(p) or {})
    if mode not in ("stars", "crypto"):
        return
    node[mode] = bool(enabled)
    mp[p] = node
    _save_pay_modes(mp)

def is_stars_enabled_for(product: str) -> bool:
    if not _shop_enabled():
        return False
    # يجب أن تكون النجوم مفعّلة عالميًا في البوت أيضًا (إن وُجدت لديك راية تمكين)
    global_ok = str(os.getenv("ENABLE_STARS", "1")) != "0"
    local_ok  = bool(get_pay_modes(product).get("stars", True))
    return global_ok and local_ok

def is_crypto_enabled_for(product: str) -> bool:
    if not _shop_enabled():
        return False
    # متاح عالميًا إذا عندك Crypto Pay token (أو أي تدفّق كريبتو آخر إن وجد)
    global_ok = CRYPTOPAY_ON or bool(os.getenv("TON_WALLET", ""))
    local_ok  = bool(get_pay_modes(product).get("crypto", True))
    return global_ok and local_ok

# ========== Public API (تستخدمها ملفات الأدمن/الهاندلرز) ==========
def is_keys_service_enabled() -> bool:
    return not _keys_service_disabled()

def set_keys_service_enabled(v: bool) -> None:
    d = _load_json(FLAGS_PATH)
    d["keys_disabled"] = (not bool(v))
    _save_json(FLAGS_PATH, d)

def get_keys_stop_message() -> str:
    d = _load_json(FLAGS_PATH)
    return str(d.get("keys_stop_message", "") or "").strip()

def set_keys_stop_message(msg: str) -> None:
    d = _load_json(FLAGS_PATH)
    d["keys_stop_message"] = str(msg or "")
    _save_json(FLAGS_PATH, d)

def is_shop_enabled() -> bool:
    return _shop_enabled()
