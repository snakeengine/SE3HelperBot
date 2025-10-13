from __future__ import annotations

# services/cryptopay.py


import os
import asyncio
import aiohttp
import json
import random
from typing import Any, Dict, Optional, List, Sequence

# ===== إعدادات عبر البيئة =====
API_BASE: str  = (os.getenv("CRYPTO_API_URL", "") or "https://pay.crypt.bot").rstrip("/")
API_TOKEN: str = (os.getenv("CRYPTOPAY_TOKEN", "") or "").strip()

# مهلة أساسية وإستراتيجية إعادة المحاولة
HTTP_TIMEOUT_SEC = float(os.getenv("CRYPTO_HTTP_TIMEOUT", "20"))
RETRIES = int(os.getenv("CRYPTO_RETRIES", "3"))
BACKOFF_BASE = float(os.getenv("CRYPTO_BACKOFF_BASE", "0.6"))  # ثوانٍ
BACKOFF_JITTER = float(os.getenv("CRYPTO_BACKOFF_JITTER", "0.25"))  # ثوانٍ (±)

# جلسة HTTP تُنشأ عند أول طلب ثم يُعاد استخدامها
_SESSION: Optional[aiohttp.ClientSession] = None


class CryptoPayError(Exception):
    """استثناء موحّد لاستدعاءات Crypto Pay."""
    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


async def _get_session() -> aiohttp.ClientSession:
    """إنشاء/إرجاع جلسة aiohttp مشتركة لكل الاستدعاءات."""
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
        connector = aiohttp.TCPConnector(limit=100, enable_cleanup_closed=True)
        _SESSION = aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True)
    return _SESSION


def _sleep_backoff(attempt: int, retry_after_hdr: Optional[str]) -> float:
    """احسب مدة الانتظار التالية، مع احترام Retry-After إن وُجد."""
    if retry_after_hdr:
        try:
            # قد تكون ثوانٍ مباشرة
            ra = float(retry_after_hdr.strip())
            if ra > 0:
                return ra
        except Exception:
            pass
    base = BACKOFF_BASE * (2 ** attempt)
    jitter = random.uniform(-BACKOFF_JITTER, BACKOFF_JITTER)
    return max(0.05, base + jitter)


async def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    تنفيذ POST مع JSON مع إعادة محاولات على أخطاء عابرة (429/5xx/شبكة).
    يرجّع dict (JSON.result) أو يرمي CryptoPayError.
    """
    sess = await _get_session()
    last_exc: Optional[Exception] = None

    for attempt in range(RETRIES):
        try:
            async with sess.post(url, headers=headers, json=payload) as r:
                text = await r.text()
                try:
                    data = json.loads(text)
                except Exception:
                    raise CryptoPayError("Non-JSON response from CryptoPay", status=r.status, body=text[:400])

                # أخطاء HTTP
                if r.status != 200:
                    if r.status == 429 or 500 <= r.status < 600:
                        wait_s = _sleep_backoff(attempt, r.headers.get("Retry-After"))
                        await asyncio.sleep(wait_s)
                        continue
                    raise CryptoPayError(f"HTTP {r.status} from CryptoPay", status=r.status, body=text[:400])

                # بروتوكول API
                if not bool(data.get("ok")):
                    # بعض أخطاء API قد تكون مؤقتة — جرب backoff ثم أعد المحاولة
                    if attempt < RETRIES - 1:
                        wait_s = _sleep_backoff(attempt, None)
                        await asyncio.sleep(wait_s)
                        continue
                    raise CryptoPayError(f"API error", status=r.status, body=text[:400])

                result = data.get("result")
                if result is None:
                    raise CryptoPayError("Missing 'result' in CryptoPay response", status=r.status, body=text[:400])
                return result

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_exc = e
            if attempt < RETRIES - 1:
                wait_s = _sleep_backoff(attempt, None)
                await asyncio.sleep(wait_s)
                continue
            raise CryptoPayError(f"Network error: {e!r}") from e

    if isinstance(last_exc, CryptoPayError):
        raise last_exc
    raise CryptoPayError("Request failed after retries")


async def _request(method: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    استدعاء طريقة Crypto Pay API.
    - يرمي CryptoPayError عند أي فشل (HTTP/JSON/API).
    - يعيد dict من 'result' مباشرة عند النجاح.
    """
    if not API_TOKEN:
        raise CryptoPayError("CRYPTOPAY_TOKEN is empty")

    url = f"{API_BASE}/api/{method.lstrip('/')}"
    headers = {
        "Crypto-Pay-API-Token": API_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "se3-helperbot/1.0 (+cryptopay)",
    }
    return await _post_json(url, headers, payload or {})


# ========== Public API (متوافقة مع مشروعك) ==========

async def get_me() -> Dict[str, Any]:
    """تأكُّد سريع من صحة التوكن والاتصال."""
    return await _request("getMe")


async def create_invoice(
    asset: str,
    amount: float,
    description: str = "",
    payload: str = "",
    expires_in: int = 900,
    allow_anonymous: bool | None = None,
    allow_comments: bool | None = None,
    paid_btn_name: str | None = None,
    paid_btn_url: str | None = None,
) -> Dict[str, Any]:
    """
    إنشاء فاتورة جديدة.
    ملاحظات:
      - amount يجب أن يكون بوحدة الأصل (USDT ⇒ بالدولار، TON ⇒ بـ TON).
      - expires_in بالثواني.
      - الحقول الاختيارية تُرسل فقط إذا حُددت.
    يعيد كائن الفاتورة (يحتوي pay_url, invoice_id, status, ...).
    """
    body: Dict[str, Any] = {
        "asset": str(asset).upper(),
        "amount": float(amount),
        "description": (description or "")[:1024],
        "payload": (payload or "")[:128],
        "expires_in": int(expires_in),
    }
    if allow_anonymous is not None:
        body["allow_anonymous"] = bool(allow_anonymous)
    if allow_comments is not None:
        body["allow_comments"] = bool(allow_comments)
    if paid_btn_name:
        body["paid_btn_name"] = str(paid_btn_name)
    if paid_btn_url:
        body["paid_btn_url"] = str(paid_btn_url)

    return await _request("createInvoice", body)


async def get_invoice(invoice_id: str | int) -> Optional[Dict[str, Any]]:
    """
    جلب فاتورة واحدة عبر معرفها.
    يُعيد None إن لم توجد الفاتورة.
    """
    res = await _request("getInvoices", {"invoice_ids": [str(invoice_id)]})
    items = res.get("items") or []
    return items[0] if items else None


def is_paid(invoice: Dict[str, Any] | None) -> bool:
    """
    تحقّق مبسّط من حالة الفاتورة.
    الحالات الشائعة: active / paid / expired
    """
    if not invoice:
        return False
    return (str(invoice.get("status") or "").lower() == "paid")


async def close_session():
    """
    إغلاق الجلسة المشتركة يدويًا (اختياري عند الإنهاء).
    """
    global _SESSION
    sess = _SESSION
    _SESSION = None
    try:
        if sess and not sess.closed:
            await sess.close()
    except Exception:
        pass


# ========== إضافيات اختيارية مفيدة (لا تكسر التوافق) ==========

async def get_invoices(
    *,
    status: str | None = None,
    asset: str | None = None,
    count: int | None = None,
    offset: int | None = None,
    invoice_ids: Sequence[str | int] | None = None,
) -> Dict[str, Any]:
    """
    جلب مجموعة فواتير بتصفية اختيارية. يعيد كائن يحوي items وعدّادًا.
    """
    body: Dict[str, Any] = {}
    if status:
        body["status"] = str(status)
    if asset:
        body["asset"] = str(asset).upper()
    if count is not None:
        body["count"] = int(count)
    if offset is not None:
        body["offset"] = int(offset)
    if invoice_ids:
        body["invoice_ids"] = [str(x) for x in invoice_ids]

    return await _request("getInvoices", body)


async def get_exchange_rates() -> List[Dict[str, Any]]:
    """
    جلب أسعار الصرف من Crypto Pay (إن كانت متاحة للحساب).
    """
    res = await _request("getExchangeRates")
    # في بعض الحسابات يعيد {'source':'...','target':'...','rate':...}
    if isinstance(res, dict) and "rates" in res:
        return res.get("rates") or []
    if isinstance(res, list):
        return res
    return []


# ========== فحص سريع اختياري ==========
async def ensure_ready() -> bool:
    """
    يفحص الإعدادات الأساسية ويرجع True عند الجاهزية، أو يرمي CryptoPayError بمعلومة مفيدة.
    """
    if not API_TOKEN:
        raise CryptoPayError("CRYPTOPAY_TOKEN is empty")
    me = await get_me()
    # عادة يعيد معلومات التاجر. مجرد تأكيد.
    return bool(me)
