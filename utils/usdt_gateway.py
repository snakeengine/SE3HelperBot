# utils/usdt_gateway.py
from __future__ import annotations
import os, time, aiohttp, logging
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)

NOWPAY_API_KEY = os.getenv("NOWPAY_API_KEY", "")
NOWPAY_USE_SANDBOX = os.getenv("NOWPAY_USE_SANDBOX", "0") == "1"
USDT_NETWORK = (os.getenv("USDT_NETWORK", "trc20") or "trc20").lower()  # trc20/erc20/bsc

# إعدادات NOWPayments
_BASE = "https://api.nowpayments.io"
if NOWPAY_USE_SANDBOX:
    _BASE = "https://api-sandbox.nowpayments.io"

HEADERS = {"x-api-key": NOWPAY_API_KEY, "Content-Type": "application/json"}

PAY_CURRENCY_MAP = {  # شبكة → رمز العملة في المزود
    "trc20": "usdttrc20",
    "erc20": "usdt",        # أو usdt-erc20 بحسب المزود/الخطة
    "bsc": "usdtbsc"
}

async def create_invoice_usdt(amount_usdt: float, order_id: str, description: str) -> Dict[str, Any]:
    """
    يرجع dict فيه payment_id, pay_address, pay_amount, payment_status, currency
    """
    pay_currency = PAY_CURRENCY_MAP.get(USDT_NETWORK, "usdttrc20")
    payload = {
        "price_amount": float(amount_usdt),
        "price_currency": "usd",  # نثبت السعر بالدولار (المزوّد يحسب USDT مكافئ)
        "pay_currency": pay_currency,
        "order_id": order_id,
        "order_description": description,
        "is_fee_paid_by_user": True
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{_BASE}/v1/payment", json=payload, headers=HEADERS, timeout=60) as r:
            data = await r.json()
            if r.status >= 300:
                log.error("NOWPayments create error (%s): %s", r.status, data)
                raise RuntimeError(f"create_invoice failed: {data}")
            return data  # يحوي payment_id, pay_address, pay_amount, etc.

async def get_payment_status(payment_id: str) -> Dict[str, Any]:
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{_BASE}/v1/payment/{payment_id}", headers=HEADERS, timeout=60) as r:
            data = await r.json()
            if r.status >= 300:
                log.error("NOWPayments status error (%s): %s", r.status, data)
                raise RuntimeError(f"status failed: {data}")
            return data  # payment_status: waiting/confirming/finished/failed/expired
