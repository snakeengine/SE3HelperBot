import asyncio
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter

async def safe_send(method_coro, *, retries: int = 2, backoff: float = 1.5):
    last = None
    for i in range(retries + 1):
        try:
            return await method_coro
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 2)))
        except TelegramNetworkError as e:
            last = e
            if i == retries:
                raise
            await asyncio.sleep(backoff * (i + 1))
    if last:
        raise last
