from __future__ import annotations

# services/inventory_keys_adapter.py

import os
from typing import Iterable, List, Dict, Optional
from aiogram import Bot

from utils.paths import BASE
from services import keys as _k

PRODUCT_KEY = os.getenv("PRODUCT_KEY", "8bp")

# ---- تطبيع أسماء المنتجات ليتطابق مع payments/inventory/keys ----
def _norm_product(p: Optional[str]) -> str:
    s = (p or PRODUCT_KEY or "8bp").strip().lower()
    mapping = {
        "8bp": "8bp", "8ball": "8bp", "8ballpool": "8bp", "8-ball": "8bp", "8_ball": "8bp",
        "carrom": "carrom", "carrompool": "carrom", "carrom-pool": "carrom",
        "soccer": "soccer", "soccerstars": "soccer", "soccer-stars": "soccer", "football-kick": "soccer",
    }
    return mapping.get(s, s or "8bp")

def _prod(p: Optional[str]) -> str:
    return _norm_product(p)

# ----------------------- واجهات إضافة/سحب/عدّ -----------------------
async def add_keys(product: str, days: int, keys: Iterable[str]) -> tuple[int, int]:
    # keys.py دواله متزامنة؛ نستدعيها مباشرة
    inserted, dups = _k.add_keys(_prod(product), days, list(keys))
    return inserted, dups

async def add_codes(product: str, days: int, keys: Iterable[str]):
    return await add_keys(product, days, keys)

async def pop_codes(days: int, qty: int, product: str | None = None) -> List[str]:
    return _k.pop_keys(_prod(product), days, qty)

async def take(days: int, qty: int, product: str | None = None) -> List[str]:
    return await pop_codes(days, qty, product)

async def count_for(days: int, product: str | None = None) -> int:
    return _k.inv_count(_prod(product), days)

async def counts(product: str | None = None) -> Dict[int, int]:
    p = _prod(product)
    return {
        3:  _k.inv_count(p, 3),
        10: _k.inv_count(p, 10),
        30: _k.inv_count(p, 30),
    }

async def snapshot_msg(product: str | None = None) -> str:
    p = _prod(product)
    c = await counts(p)
    return f"{p}: 3d={c[3]} | 10d={c[10]} | 30d={c[30]}\n📂 data dir: {BASE}"

# ----------------------- تنبيه انخفاض المخزون -----------------------
async def maybe_alert_low_stock(bot: Bot, days: int, product: str | None = None) -> None:
    p = _prod(product)
    curr = await count_for(days, p)

    env_key = {3: "MIN_STOCK_3D", 10: "MIN_STOCK_10D", 30: "MIN_STOCK_30D"}.get(int(days), "")
    try:
        threshold = int(os.getenv(env_key, "5"))
    except Exception:
        threshold = 5

    if curr > threshold:
        return

    # حاول أولاً عبر نظام الإشعارات الموحد (إن وُجد)
    try:
        from services.notify import notify_role  # type: ignore
        text_ar = f"⚠️ انخفاض مخزون — {p} / {days} يوم: المتاح {curr} (الحد {threshold})"
        text_en = f"⚠️ Low stock — {p} / {days}d: {curr} available (threshold {threshold})"
        await notify_role(bot, role="inventory", text=f"{text_ar}\n{text_en}")
        return
    except Exception:
        pass

    # فولباك: أرسل إلى ALERTS_CHAT_ID أو أول ADMIN_IDS
    raw_chat = (os.getenv("ALERTS_CHAT_ID", "") or "").strip()
    chat: int | str | None = None
    if raw_chat:
        # إن كان رقميًا (حتى -100.. لقنوات/مجموعات)، حوّله لـ int
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
            text=f"⚠️ انخفاض مخزون {p} ({days}d): المتاح {curr} (الحد {threshold})."
        )
    except Exception:
        pass
