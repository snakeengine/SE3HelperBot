# utils/usdt_gateway.py
from __future__ import annotations

import os
import time
import hmac
import json
import aiohttp
import logging
from typing import Optional, Dict, Any, Tuple
from hashlib import sha512

log = logging.getLogger(__name__)

# ========= الإعدادات =========
NOWPAY_API_KEY: str = (os.getenv("NOWPAY_API_KEY") or "").strip()
NOWPAY_USE_SANDBOX: bool = (os.getenv("NOWPAY_USE_SANDBOX", "0") == "1")

# trc20 / erc20 / bsc
USDT_NETWORK: str = (os.getenv("USDT_NETWORK", "trc20") or "trc20").strip().lower()

# مفتاح التحقق من تواقيع IPN (اختياري)
NOWPAY_IPN_SECRET: str = (os.getenv("NOWPAY_IPN_SECRET") or "").strip()

# ========= عناوين الخدمة =========
def get_base_url() -> str:
    return "https://api-sandbox.nowpayments.io" if NOWPAY_USE_SANDBOX else "https://api.nowpayments.io"

def _headers() -> Dict[str, str]:
    return {
        "x-api-key": NOWPAY_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

# شبكة → رمز العملة عند المزود
PAY_CURRENCY_MAP: Dict[str, str] = {
    "trc20": "usdttrc20",
    "erc20": "usdt",      # بعض الحسابات تستخدم "usdt-erc20"؛ غيّر عبر env إن لزم
    "bsc": "usdtbsc",
}

# ========= أدوات عامة =========
def is_configured() -> bool:
    """هل مفاتيح NOWPayments مضبوطة؟"""
    return bool(NOWPAY_API_KEY)

def _pick_pay_currency() -> str:
    return PAY_CURRENCY_MAP.get(USDT_NETWORK, "usdttrc20")

def normalize_status(s: Optional[str]) -> str:
    """
    تحويل حالات المزود إلى مجموعة معروفة.
    حالات شائعة: waiting / confirming / finished / failed / expired / refunded / partially_paid
    """
    s = (s or "").strip().lower()
    if s in {"waiting", "confirming", "finished", "failed", "expired", "refunded", "partially_paid"}:
        return s
    return s or "unknown"

def is_final_status(s: Optional[str]) -> bool:
    """هل الحالة نهائية لا تحتاج متابعة؟"""
    return normalize_status(s) in {"finished", "failed", "expired", "refunded"}

def _timeout() -> aiohttp.ClientTimeout:
    # مهلات متوازنة: اتصال 10 ثوان، إجمالي 60 ثانية
    return aiohttp.ClientTimeout(total=60, connect=10)

async def _fetch_json(
    method: str,
    url: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
    json_payload: Optional[dict] = None,
    retries: int = 2,
    backoff: float = 1.5,
) -> Tuple[int, Dict[str, Any]]:
    """
    استدعاء HTTP مع JSON، وإعادة محاولات للأخطاء العابرة (429/5xx/شبكة).
    """
    if not is_configured():
        raise RuntimeError("NOWPayments is not configured: missing NOWPAY_API_KEY")

    owned = session is None
    sess = session or aiohttp.ClientSession(timeout=_timeout())
    last_exc: Optional[Exception] = None

    try:
        for attempt in range(retries + 1):
            try:
                async with sess.request(method, url, headers=_headers(), json=json_payload) as r:
                    status = r.status
                    # حاول قراءة JSON حتى عند الأخطاء لتشخيص أدق
                    try:
                        data = await r.json(content_type=None)
                    except Exception:
                        text = await r.text()
                        data = {"_raw": text}

                    # نجح 2xx
                    if 200 <= status < 300:
                        return status, data

                    # معالجة rate-limit 429
                    if status == 429:
                        retry_after = 2.0
                        try:
                            retry_after = float(r.headers.get("Retry-After", "2"))
                        except Exception:
                            pass
                        log.warning("NOWPayments 429, retrying in %.1fs; resp=%s", retry_after, data)
                        await aiohttp.asyncio.sleep(retry_after)
                        continue

                    # أخطاء 5xx قابلة لإعادة المحاولة
                    if 500 <= status < 600 and attempt < retries:
                        sleep_s = backoff * (attempt + 1)
                        log.warning("NOWPayments %s -> retry in %.1fs; resp=%s", status, sleep_s, data)
                        await aiohttp.asyncio.sleep(sleep_s)
                        continue

                    # أخطاء أخرى: ارفع
                    log.error("NOWPayments HTTP %s: %s", status, data)
                    raise RuntimeError(f"NOWPayments error {status}: {data}")

            except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError) as e:
                last_exc = e
                if attempt == retries:
                    break
                sleep_s = backoff * (attempt + 1)
                log.warning("NOWPayments network error (%s), retrying in %.1fs", type(e).__name__, sleep_s)
                await aiohttp.asyncio.sleep(sleep_s)

        # انتهت المحاولات
        if last_exc:
            raise last_exc
        raise RuntimeError("NOWPayments request failed after retries")
    finally:
        if owned:
            await sess.close()

# ========= واجهات عامة (متوافقة) =========
async def create_invoice_usdt(
    amount_usdt: float,
    order_id: str,
    description: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
    is_fee_paid_by_user: bool = True,
    price_currency: str = "usd",
) -> Dict[str, Any]:
    """
    ينشئ عملية دفع USDT ويُرجع كائنًا يحتوي على أهم الحقول.

    يعيد dict يحتوي مثلاً:
    {
      "payment_id": "...",
      "pay_address": "...",
      "pay_amount": 12.34,
      "pay_currency": "usdttrc20",
      "price_amount": 12.34,
      "price_currency": "usd",
      "payment_status": "waiting",
      "raw": {...}  # الاستجابة الخام كاملة
    }
    """
    amt = float(amount_usdt)
    if amt <= 0:
        raise ValueError("amount_usdt must be > 0")

    pay_currency = _pick_pay_currency()
    payload = {
        "price_amount": amt,
        "price_currency": price_currency,   # نثبت السعر بالدولار؛ المزود يحسب USDT المعادل
        "pay_currency": pay_currency,
        "order_id": str(order_id),
        "order_description": description or "",
        "is_fee_paid_by_user": bool(is_fee_paid_by_user),
    }

    url = f"{get_base_url()}/v1/payment"
    _, data = await _fetch_json("POST", url, session=session, json_payload=payload)

    # تطبيع الإخراج
    out = {
        "payment_id": data.get("payment_id"),
        "pay_address": data.get("pay_address"),
        "pay_amount": data.get("pay_amount"),
        "pay_currency": data.get("pay_currency", pay_currency),
        "price_amount": data.get("price_amount", amt),
        "price_currency": data.get("price_currency", price_currency),
        "payment_status": normalize_status(data.get("payment_status")),
        "raw": data,
    }
    return out

async def get_payment_status(
    payment_id: str,
    *,
    session: Optional[aiohttp.ClientSession] = None
) -> Dict[str, Any]:
    """
    يرجع حالة الدفع كما يراها المزود (waiting/confirming/finished/failed/expired/…)
    """
    if not payment_id:
        raise ValueError("payment_id is required")

    url = f"{get_base_url()}/v1/payment/{payment_id}"
    _, data = await _fetch_json("GET", url, session=session)

    out = {
        "payment_id": data.get("payment_id") or payment_id,
        "payment_status": normalize_status(data.get("payment_status")),
        "pay_address": data.get("pay_address"),
        "pay_amount": data.get("pay_amount"),
        "pay_currency": data.get("pay_currency"),
        "price_amount": data.get("price_amount"),
        "price_currency": data.get("price_currency"),
        "updated_at": data.get("updated_at") or data.get("created_at"),
        "is_final": is_final_status(data.get("payment_status")),
        "raw": data,
    }
    return out

# ========= IPN (اختياري) =========
def verify_ipn_signature(headers: Dict[str, str], body_bytes: bytes) -> bool:
    """
    تحقق توقيع IPN من NOWPayments (هيدر x-nowpayments-sig) باستخدام سرّ NOWPAY_IPN_SECRET.
    يجب تمرير جسم الطلب الخام (bytes) كما وصل تمامًا.
    """
    if not NOWPAY_IPN_SECRET:
        # إن لم يكن السر مضبوطًا، نعيد False بدل قبول أي شيء
        log.warning("NOWPAY_IPN_SECRET is not set; IPN verification will fail.")
        return False

    got = (headers.get("x-nowpayments-sig") or headers.get("X-Nowpayments-Sig") or "").strip()
    if not got:
        return False
    try:
        expected = hmac.new(NOWPAY_IPN_SECRET.encode("utf-8"), body_bytes, sha512).hexdigest()
        return hmac.compare_digest(got, expected)
    except Exception:
        return False
